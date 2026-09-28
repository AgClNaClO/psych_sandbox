# 咨询师记忆结构（当前实现）

本文记录当前代码中咨询师记忆的实际结构：谁写入、咨询师每轮能看到什么、有哪些隔离约束，以及尚未解决的限制。它描述现状，不是目标设计；改动记忆字段、读取视图或会话边界整合顺序前先读本文（见 [AGENTS.md 的 Runtime invariants](../AGENTS.md)）。

## 0. 一句话结构

`SessionMemory` 只有 **4 个记忆内容字段**（对齐 PsychAgent 的 `PublicMemory`）：已知背景、每场回顾、上轮作业、事项清单；另有 `case_id`、`migration_warnings` 两个不进入模型的管理字段。早期版本的 14 键扁平布局由 `SessionMemory.migrate_legacy_memory_layout` 折叠进新结构（见第 7 节）。

## 1. 四字段记忆

| 字段 | 装什么 | 写入者 |
|---|---|---|
| `case_id` | 案例 ID（管理字段，不进模型） | `CounselingSandbox._initial_memory` |
| `known_background` | ① 已知背景：`UnlockedClientInfo`（结构化档案 + 带出处的 `facts`） | E.8 合并；`facts` 在会话内由披露门控累积 |
| `session_recaps` | ② 每场回顾：`SessionRecap`，一场一条 | `MemoryConsolidator` |
| `last_homework` | ③ 上轮作业：`HomeworkItem`（含 `status`/`source_session`/`completion_evidence`） | `MemoryConsolidator` |
| `checklist` | ④ 事项清单：`ChecklistMemory`（`per_session` 归档 + `open_items` + `pending_verification`） | `MemoryConsolidator` |
| `migration_warnings` | 旧数据迁移提示（管理字段，不进模型） | `SessionMemory` 的迁移校验器 |

`SessionRecap` 的字段：`session_index`、`summary`（程序拼接的确定性摘要）、`clinical_summary`（E.9 摘要正文）、`goal_assessment`、`client_state_analysis`、`homework`（本场布置原文，不可变历史）、`interventions_used`（本场技能）、`risk`（本场非低风险的结构化记录）、`safety_notes`（安全/披露门控理由）、`relationship_events`（信任变化）、`client_closing`（本场末句）。

只读派生视图（不是存储字段，便于旧读取点继续工作）：

| 派生属性 | 含义 |
|---|---|
| `completed_sessions` | `len(session_recaps)` |
| `interventions_used` | 各场 `interventions_used` 的并集 |
| `last_client_closing` | 最后一场的 `client_closing` |
| `homework` | `last_homework` 中 `status="open"` 的文本，即"现在该做什么" |
| `unresolved_topics` | `checklist.open_items` 中未完成项的文本 |

## 2. 整合映射（早期 14 键 → 4 字段）

| 早期顶层字段 | 现在的位置 |
|---|---|
| `unlocked_client_info` | `known_background` |
| `summaries[i]` + `clinical_summaries[i]` 的正文/目标/状态分析/作业 | `session_recaps[i]` |
| `clinical_summaries[i]` 的五类清单条目 | `checklist.per_session[i]`（不再与临床摘要重复） |
| `homework` | `last_homework`（带状态；已完成的项只留在 `session_recaps[*].homework`） |
| `unresolved_topics` | `checklist.open_items` |
| `interventions_used` | `session_recaps[i].interventions_used` |
| `risk_history` | `session_recaps[i].risk`（level/categories/evidence） |
| `supervisor_feedback` | `session_recaps[i].safety_notes` |
| `relationship_events` | `session_recaps[i].relationship_events` |
| `last_client_closing` | `session_recaps[-1].client_closing` |
| `completed_sessions` | 派生属性 |
| `between_session_context` | 删除（此前就没有写入点，也没有读取点） |
| `migration_warnings` | 保留为管理字段 |

## 3. 会话边界整合顺序

`runtime/orchestrator.py::run_case` 每场会谈的实际顺序是：

1. 规则安全/披露门控（`SessionSafetyGate`，用会话前的记忆副本判定"披露前引用"）。
2. 纵向评估（状态差值、趋势、阶段动作）。
3. E.7 会话信息提取 → E.8 档案合并 → E.9 临床摘要（`runtime/memory_pipeline.py`）；E.9 额外收到 `memory_items` 台账（开放作业、开放待办、待核实项及其 `item_id`）。
4. `MemoryConsolidator.consolidate` 把本场结果并入 `session_recaps`、`last_homework`、`checklist`；被拒绝的完成更新写入运行日志（`记忆整合提示：…`）。
5. 咨询师会后自评（读取刚合并的记忆）→ `PlanBuilder` 生成下一次计划。
6. 构造轨迹（含会话前记忆副本 `Trajectory.memory_before`）→ 提交 SQLite `memories`/`sessions`/`trajectories` → 同步 `trajectory.jsonl`。

会话内的 `facts` 由 `DisclosureGate.unlock` 生成、`ClientSimulator.merge_unlocked` 合并，并在 `_run_session` 结束时写回 `known_background.facts`。

| 步骤 | 模板 | 输入 | 输出与门控 |
|---|---|---|---|
| E.7 提取 | `prompts/memory/extraction_system.jinja2` | 本场完整对话、流派代码、会话序号 | `ExtractedClientInfo`；代码强制清空 `language_features`。提示词要求只提取来访者亲口表达的内容。 |
| E.8 合并 | `prompts/memory/merge_system.jinja2` | 历史档案、本场提取、全局背景（脱敏）、会话序号 | `UnlockedClientInfo`；代码用 `_prevent_global_backfill` 做等值白名单，并强制 `facts = history.facts`。 |
| E.9 摘要 | `prompts/memory/summary_system.jinja2` | 本场对话、会话计划、最后一轮清单、记忆台账 | `ClinicalSummary`（含 `item_updates`）与清单字段去重合并；提示词要求证据来自本场对话。 |

## 4. 会话内工作记忆 `SessionChecklist`

- `SessionChecklist`（`domain/models.py`）保存 `completed_items`、`important_information`、`important_methods`、`important_results`、`pending_items`。
- 每轮由规划器输出 `checklist_update`（含 `resolved_pending_items`），`runtime/memory.py::merge_session_checklist` 只做追加和显式解除：旧条目不会因为模型没有重复而消失，解除依赖"字符串完全相同"匹配。
- 每轮随 `build_context_payload` 以 `session_checklist` 注入咨询师规划器与执行器。
- 会话结束时，E.9 的 `ClinicalSummary` 与最后一轮清单做去重合并，归档进 `checklist.per_session[i]`；下一场会谈仍从空清单重新开始（`docs/agents/domain.md` 的不变量 9）。

## 5. 咨询师每轮读到的内容（读取视图 + 输入预算）

`CounselorAgent._allowed_memory_payload` 现在委托 `runtime/memory_view.py::MemoryViewBuilder`，由 `SandboxConfig.memory_view`（`configs/runtime.yaml` 的 `memory_view:` 段）控制：

| 模式 | 行为 |
|---|---|
| `full`（默认） | 整份四字段记忆，去掉管理字段与审计日志；与改动前的投喂范围一致，便于对照。 |
| `recap_window` | 只给当前焦点 + 最近 `recent_sessions` 场回顾 + 更早场次一行归档，并始终受 `max_chars` 约束。 |

两种模式都：排除 `migration_warnings`；排除 `session_recaps[*].safety_notes`（安全/披露门禁理由）与 `session_recaps[*].relationship_events`（模拟器信任变化）这两类审计日志；始终屏蔽 `known_background.static_traits.language_features`。`session_recaps[*].risk` 保留，因为它是结构化的风险摘要。

`recap_window` 视图的字段：

```text
case_id, completed_sessions, known_background,
current_focus: { last_homework, open_items, pending_verification, recent_risk, last_session },
recent_session_recaps, recent_checklist_records, earlier_session_archive,
view_budget: { mode, limit, chars, truncated, dropped_sessions, dropped_archive_lines, dropped_focus_items }
```

预算算法（确定性）：先按 `per_field_chars` 截断字符串、按 `focus_items_max` 截断焦点条目；超预算时按"最旧归档行 → 最旧窗口回顾"的顺序丢弃，焦点（已知背景、上轮作业、开放待办、待核实项、最近风险）永不丢弃；无法再缩小时把 `truncated` 置为 true 并返回。`view_budget.chars` 是**不含预算块本身**的字符数，`_BUDGET_SLACK`（64）保证连同预算块的完整 JSON 仍不超过 `max_chars`。

咨询师可见内容因此只有：流派/阶段/目标、后台议程 `session_agenda`（声明"议程不是已知案例事实"）、`known_background`（独立键）、`session_memory`（上述视图）、当前 `session_checklist`、本轮来访者话语、最近对话、风险判定和技能目录/Observation。注入点是规划器与执行器每轮各一次，会后自评一次（`review_session` 的 `allowed_memory`）。

其他与记忆有关的读取点：

- 技能向量查询（`_vector_query`）读取 `session_memory.session_recaps[-1].summary`（截断 500 字）。
- 技能证据校验（`_evidence_sources`）把来访者消息、`known_background`、视图内的字符串和 `session_checklist` 纳入允许来源。由于审计日志已不在视图内，`safety_notes`/`relationship_events` 不再能作为 `evidence_quote` 的出处。详见 [技能选择说明](SKILL_SELECTION.md)。
- `evaluation/safety_gate.py::SessionSafetyGate._leaked_fact_ids` 读 `memory_before.known_background.facts`。

## 6. 退休语义（作业与待办）

1. **按 ID 退休。** E.9 输出的 `ClinicalSummary.item_updates`（`item_id` + `status` + `evidence`）由 `MemoryConsolidator` 应用到 `last_homework`、`checklist.open_items`、`checklist.pending_verification`。措辞改写不再导致条目"退不了休"。
2. **完成必须有对话证据。** `status="done"` 的 `evidence` 经 `normalize_disclosure_text` 规范化后必须出现在本场对话中，否则该更新被拒绝、条目保持 `open`，并记录 `记忆整合提示：…`。
3. **兼容旧式输出。** 若 E.9 只用 `completed_items` 表述完成，`_same_item` 会做规范化相等 → 包含 → 相似度（`SequenceMatcher` ≥ 0.85，且最短一侧 ≥ 6 字）三层匹配，把改写过的待办/作业也算作完成。
4. **边界不再乱扣"未完成"。** `end_reason == "max_turns"` 时，本场第一个目标写入 `checklist.pending_verification`（`kind="goal"`、`needs_verification=True`、`carried_to_session=next_index`）。视图把它与已确认待办分开显示；下一场若 E.9 明确保留（`status="open"`）就转为已确认待办，若给出证据就退休。
5. **列表有界。** `last_homework` 只保留 `status="open"` 的项；已完成的作业原文仍留在 `session_recaps[*].homework` 与 `checklist.per_session[*]`，历史不丢。

## 7. 迁移与兼容

1. **旧运行可直接加载。** `SessionMemory` 的 `@model_validator(mode="before")`（`migrate_legacy_memory_layout` → `_fold_legacy_memory`）识别早期 14 键布局后一次性折叠：
   - `unlocked_client_info` → `known_background`；旧 `unlocked_profile` 只保留 `client_id`/`facts`，并写入"需要对话重放"的迁移提示（`orchestrator` 据此触发 `migrate_legacy_unlocked`）。
   - `summaries[i]` + `clinical_summaries[i]` 按 `session_index` 配对成 `session_recaps[i]`；五类清单条目归档进 `checklist.per_session[i]`。
   - `homework` → `last_homework`（全部 `open`），`unresolved_topics` → `checklist.open_items`。
   - `interventions_used`/`risk_history`/`supervisor_feedback`/`relationship_events`/`last_client_closing` 没有场次归属，统一归并到最后一场回顾并写入迁移提示。
   - `completed_sessions`、`between_session_context` 直接丢弃（前者改为派生）。
   - 若新旧键混用，会写入"legacy flat keys … were dropped"提示。
2. **持久化不变。** SQLite `memories` 表仍按 `(run_id, session_index)` 保存整份记忆 JSON；`Trajectory.memory_before` 保存该会谈开始前的记忆副本；`RunResult.final_memory` 保存最后一版记忆。字段新增/折叠都在 Pydantic 层完成，不需要改表结构。
3. **轨迹版本。** `model_config_snapshot.trace_schema_version` 由 4 提升到 5（记忆/轨迹结构变化），并新增 `memory_view` 快照，便于消融对比（见 `docs/agents/domain.md` 第 8 条）。
4. **`--resume-run`** 从 `memories` 最近一行恢复；旧运行的 `known_background.facts` 仍按 `ClientSimulator.migrate_legacy_unlocked` 按原文重新映射。

## 8. 隔离与安全不变量

1. 咨询师上下文只包含已披露证据与允许记忆，完整 `ClientProfile` 永不进入（回归测试：`tests/test_components.py::test_counselor_payload_has_no_full_profile`）。
2. E.8 的等值白名单阻止"全局真值回填"：`main_problem`、`topic`、`core_demands`、`growth_experiences`、`static_traits`、`theory` 键只允许取自历史档案或本场提取的原文；`language_features` 始终为空且不进视图。
3. `SessionSafetyGate` 用会话前记忆中的已解锁事实判定咨询师是否提前引用隐藏信息；它只做 RFT 准入与安全标记，不参与评分。
4. RFT 候选各自深拷贝记忆、计划与状态，只有胜出会谈的记忆回流并进入提交；候选记忆只留在候选审计文件里。
5. `risk`、`safety_notes`、`relationship_events` 记录的是模拟器内部信号与会谈风险判定，属于仿真变量/门禁理由，不是来访者原话或临床事实；它们保存在记忆里供审计与报告，但不进入模型视图。督导量表评分不进记忆、也不驱动计划。

## 9. 当前已知限制

以下是现状描述，用于评估改动前的影响面，不代表目标设计。

1. **默认仍是全量投喂。** `memory_view.mode` 默认 `full`，每轮（规划器 + 执行器）仍会收到整份记忆；`recap_window` 的默认参数（`recent_sessions=3`、`max_chars=8000`）是初始工程值，尚未在真实案例集上做效果调优。
2. **`recap_window` 会丢历史细节。** 被裁掉的老场次只剩一行归档，`safety_notes`/`relationship_events` 在任何模式下都不进模型；需要复盘时请读 SQLite/`result.json`。
3. **退休的质量仍取决于 E.9。** 代码能拒绝"没有证据的完成"，但不能保证 E.9 主动为每个开放条目给出更新；未更新的条目会留在 `open_items` 里（视图按 `focus_items_max` 截断，并记录 `dropped_focus_items`）。
4. **`checklist.per_session` 与 `session_recaps` 是"明细 + 叙述"关系。** 归档清单条目不进入 recap，因此窗口模式下老场次的清单条目只能通过 `earlier_session_archive` 与 SQLite 回溯。
5. **`risk` 只记录非低风险场次。** 低风险轮次仍只留在 `SessionRecord.risk_events` 与会话产物里。
6. **档案字段仍没有来源标记。** 除 `facts` 外，`main_problem`、`topic`、`core_demands`、`static_traits` 不携带 `source_session` 或证据原文，一旦写入就缺少可审计的修正路径。
7. **`theory` 与 `updated_session` 约束不全。** 提示词要求只合并 `theory_select` 中的流派字段，代码只按"历史或本场已有的键"过滤；`updated_session` 取决于合并模型的输出。
8. **E.7/E.9 的输出没有对话级证据校验（退休更新除外）。** 提取与摘要仍只由提示词约束"必须来自对话"；只有 `item_updates.status="done"` 有代码级证据校验。

## 10. 修改记忆时的检查项

1. **不要直接删除或重命名字段。** `StrictModel` 使用 `extra="forbid"`，而 `memories` 表保存整份 JSON；删字段会让旧运行无法 `load_memory`、续跑或重生成报告。改动必须同时更新第 7 节的折叠校验器。
2. **同步全部读取点：** `CounselorAgent._allowed_memory_payload`、`_vector_query`（`session_recaps[-1].summary`）、`_evidence_sources`、`CounselorAgent.review_session` 的 `allowed_memory`、`runtime/memory_view.py`、`runtime/orchestrator.py::_consolidate_memory_pipeline`/`_memory_items`、`runtime/memory.py::MemoryConsolidator`、`evaluation/safety_gate.py::SessionSafetyGate._leaked_fact_ids`。
3. **保持不变量：** 咨询师上下文不出私密档案；审计日志不进视图；E.8 的等值白名单与空 `language_features` 不放松；候选记忆隔离与"仅胜者回流"不变；督导评分不写入记忆、不驱动计划；"完成"必须有本场对话证据。
4. **更新测试：** `tests/test_memory_layout.py`（四字段契约、迁移、退休、视图预算）、`tests/test_components.py`（payload 契约、清单合并、legacy 迁移、反回填）、`tests/test_e2e.py`（E.7→E.8→E.9→自评链路、记忆持久化）、`tests/test_dialogue_loop.py`、`tests/test_rollout_runtime.py`（候选隔离）。
5. **提示词与版本：** 改动 `prompts/` 下任何被消费的模板时要同步 `src/psychsandbox/prompts.py::PROMPT_TREE_VERSION`。
6. **产物与文档：** 记忆结构变化会影响 `result.json`、SQLite、`trajectory.jsonl` 和报告内容；新增输出路径或迁移时按 [运行产物约定](RUN_ARTIFACTS.md) 处理并保留既有运行。
