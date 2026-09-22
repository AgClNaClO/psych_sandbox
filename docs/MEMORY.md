# 咨询师记忆结构（当前实现）

本文记录当前代码中咨询师记忆的实际结构：谁写入、咨询师每轮能看到什么、有哪些隔离约束，以及尚未解决的限制。它描述现状，不是目标设计；改动记忆字段、读取视图或会话边界整合顺序前先读本文（见 [AGENTS.md 的 Runtime invariants](../AGENTS.md)）。

## 1. 三层记忆

### 1.1 会话内工作记忆

- `SessionChecklist`（`domain/models.py`）保存 `completed_items`、`important_information`、`important_methods`、`important_results`、`pending_items`。
- 每轮由规划器输出 `checklist_update`（含 `resolved_pending_items`），`runtime/memory.py::merge_session_checklist` 只做追加和显式解除：旧条目不会因为模型没有重复而消失，解除依赖"字符串完全相同"匹配。
- 每轮随 `build_context_payload` 以 `session_checklist` 注入咨询师规划器与执行器。
- 会话结束时，E.9 的 `ClinicalSummary` 与最后一轮清单做去重合并后进入长期记忆；下一场会谈从空清单重新开始（`docs/agents/domain.md` 的不变量 9）。

### 1.2 长期记忆 `SessionMemory`

| 字段 | 内容 | 写入者 |
|---|---|---|
| `case_id` | 案例 ID | `CounselingSandbox._initial_memory` |
| `completed_sessions` | 已完成会谈数 | `MemoryConsolidator.consolidate` |
| `summaries` | 每场一条确定性模板摘要 | `MemoryConsolidator.consolidate` |
| `clinical_summaries` | 每场一份 E.9 结构化临床摘要 | `MemoryConsolidator.consolidate` |
| `unlocked_client_info` | 咨询师的结构化来访者档案（含 `facts`） | E.8 合并；`facts` 在会话内由披露门控累积 |
| `unresolved_topics` | 未尽议题 | `consolidate`（结合 E.9 的 completed/pending items） |
| `homework` | 家庭作业文本（去重） | `consolidate`（取 E.9 `homework`） |
| `interventions_used` | 使用过的技能 ID（去重） | `consolidate` |
| `risk_history` | 风险等级字符串 | `consolidate`（只取非 `low`） |
| `supervisor_feedback` | 安全/披露门控理由文本 | `consolidate`（见 `_supervisor_feedback`） |
| `relationship_events` | `session/turn/trust_change` 字符串 | `consolidate`（来自来访者规划信号） |
| `last_client_closing` | 本场最后一条来访者话语 | `consolidate` |
| `between_session_context` | 已定义字段，当前没有写入点 | 无 |
| `migration_warnings` | 旧产物迁移说明 | `SessionMemory` 的迁移校验器 |

`unlocked_client_info`（`UnlockedClientInfo`）保存 `static_traits`、`main_problem`、`topic`、`core_demands`、`growth_experiences`、`theory`、`facts`、`updated_session`。`facts` 中每条 `UnlockedFact` 都带 `evidence_session`、`evidence_turn`、`disclosure_method` 和已说出的证据片段。

### 1.3 会话边界整合顺序

`runtime/orchestrator.py::run_case` 每场会谈的实际顺序是：

1. 规则安全/披露门控（`SessionSafetyGate`，用会话前的记忆副本判定"披露前引用"）。
2. 纵向评估（状态差值、趋势、阶段动作）。
3. E.7 会话信息提取 → E.8 档案合并 → E.9 临床摘要（`runtime/memory_pipeline.py`）。
4. `MemoryConsolidator.consolidate` 把本场摘要、临床摘要和各累加字段写入 `SessionMemory`。
5. 咨询师会后自评（读取刚合并的记忆）→ `PlanBuilder` 生成下一次计划。
6. 构造轨迹（含会话前记忆副本 `Trajectory.memory_before`）→ 提交 SQLite `memories`/`sessions`/`trajectories` → 同步 `trajectory.jsonl`。

会话内的 `facts` 由 `DisclosureGate.unlock` 生成、`ClientSimulator.merge_unlocked` 合并，并在 `_run_session` 结束时写回 `memory.unlocked_client_info.facts`。

| 步骤 | 模板 | 输入 | 输出与门控 |
|---|---|---|---|
| E.7 提取 | `prompts/memory/extraction_system.jinja2` | 本场完整对话、流派代码、会话序号 | `ExtractedClientInfo`；代码强制清空 `language_features`。提示词要求只提取来访者亲口表达的内容。 |
| E.8 合并 | `prompts/memory/merge_system.jinja2` | 历史档案、本场提取、全局背景（脱敏）、会序号 | `UnlockedClientInfo`；代码用 `_prevent_global_backfill` 做等值白名单，并强制 `facts = history.facts`。 |
| E.9 摘要 | `prompts/memory/summary_system.jinja2` | 本场对话、会话计划、最后一轮清单 | `ClinicalSummary` 与清单字段去重合并；提示词要求证据来自本场对话。 |

### 1.4 持久化与恢复

- SQLite `memories` 表按 `(run_id, session_index)` 保存该会谈结束后的整份记忆 JSON；`sessions`、`trajectories` 分开保存。
- `Trajectory.memory_before` 保存该会谈开始前的记忆副本，`RunResult.final_memory` 保存最后一版记忆；HTML 报告可离线重生成。
- `--resume-run` 从 `memories` 最近一行恢复记忆与初始状态；旧运行的已解锁事实会经 `ClientSimulator.migrate_legacy_unlocked` 按原文重新映射。
- 旧产物里的 `unlocked_profile` 会被 `SessionMemory` 的迁移校验器映射为 `unlocked_client_info`，并写入 `migration_warnings`；被丢弃的预置背景、语言风格和核心诉求不再回填，需要靠对话重放。

## 2. 咨询师每轮读到的内容

`CounselorAgent.build_context_payload`（`agents/counselor.py`）负责组装，咨询师可见内容只有：

- 流派/阶段/目标、后台议程 `session_agenda`（明确声明"议程不是已知案例事实"）；
- `unlocked_client_info`（已解锁档案与已说出的事实片段）；
- `session_memory`：`_allowed_memory_payload` 的返回值，当前是**整份记忆序列化，只排除 `migration_warnings` 和 `static_traits.language_features`**；
- 当前 `session_checklist`；
- 本轮来访者话语、近期对话、风险判定和技能目录/Observation。

注入点：规划器与执行器每轮各一次，会后自评一次（`review_session` 的 `allowed_memory`）。

其他与记忆有关的读取点：

- 技能向量查询（`_vector_query`）读取 `session_memory.summaries[-1]`（截断 500 字）作为查询文本的一部分。
- 技能证据校验（`_evidence_sources`）把来访者消息、已解锁档案、`session_memory` 的**全部字符串**和 `session_checklist` 都纳入允许来源，因此 E.9 摘要、`relationship_events`、`supervisor_feedback` 等文本同样可以成为 `evidence_quote` 的出处。详见 [技能选择说明](SKILL_SELECTION.md)。

## 3. 隔离与安全不变量

1. 咨询师上下文只包含已披露证据与允许记忆，完整 `ClientProfile` 永不进入（回归测试：`tests/test_components.py::test_counselor_payload_has_no_full_profile`）。
2. E.8 的等值白名单阻止"全局真值回填"：`main_problem`、`topic`、`core_demands`、`growth_experiences`、`static_traits`、`theory` 键只允许取自历史档案或本场提取的原文；`language_features` 始终为空。
3. `SessionSafetyGate` 用会话前记忆中的已解锁事实判定咨询师是否提前引用隐藏信息；它只做 RFT 准入与安全标记，不参与评分。
4. RFT 候选各自深拷贝记忆、计划与状态，只有胜出会谈的记忆回流并进入提交；候选记忆只留在候选审计文件里。
5. `relationship_events`、`risk_history` 记录的是模拟器内部信号与会谈风险判定，属于仿真变量，不是来访者原话或临床事实；督导量表评分不进记忆、也不驱动计划。

## 4. 当前已知限制

以下是现状描述，用于评估改动前的影响面，不代表目标设计。

1. **读取视图没有分层与预算。** 咨询师每轮（规划器 + 执行器）都会收到整份记忆序列化，会后自评时再注入一次。用内容长度合理的合成记忆实测 `_allowed_memory_payload` 的 JSON 字符数（探针脚本，2026-09-22，非基准测试）：

   | 会话数 | 1 | 3 | 6 | 12 | 24 | 50 | 100 |
   |---|---|---|---|---|---|---|---|
   | 记忆块字符数 | 6.2k | 10.1k | 15.9k | 27.6k | 50.9k | 101k | 199k |

   约 1.9k 字符/会话线性增长，`SandboxConfig.session_count` 上限为 100；当前没有压缩、窗口或相关性检索。
2. **两份摘要并存。** `summaries`（确定性模板文本，末段含最后两条来访者话语）与 `clinical_summaries[*].session_summary_abstract` 内容重叠，且后者与 `last_client_closing` 也会重复。
3. **作业与待办是字符串。** `homework` 只做去重追加，没有完成状态与来源会话；`unresolved_topics` 的移除依赖与 E.9 `completed_items` 完全相同；措辞改写会被当成新条目。
4. **`risk_history` 只保存等级字符串**（如 `medium`），没有会话、轮次、类别和证据，且每轮风险判定都会追加。
5. **`supervisor_feedback` 实际是安全/披露门控理由**（`_supervisor_feedback`），不是临床督导意见；命名容易与 `PsychEvalSupervisor` 的评分混淆。
6. **档案字段没有来源标记。** E.8 的规则是"历史非空则保留历史"，而 `main_problem`、`topic`、`core_demands`、`static_traits` 不携带 `source_session` 或证据原文，因此一旦写入就缺少可审计的修正路径（`facts` 有 `evidence_session/turn`，这些字段没有）。
7. **`theory` 与 `updated_session` 约束不全。** 提示词要求只合并 `theory_select` 中的流派字段，代码只按"历史或本场已有的键"过滤，未按流派代码白名单过滤；除迁移路径外没有代码写入 `updated_session`，该值取决于合并模型的输出。
8. **E.7/E.9 的输出没有对话级证据校验。** 提取与摘要都只由提示词约束"必须来自对话"，没有代码校验内容真的出现在来访者发言中；临床摘要入库前也没有单独的泄漏门控（`SessionSafetyGate` 只检查咨询师会话发言与未披露披露项）。
9. **未接通的字段与参数：** `between_session_context` 已定义但全仓库没有写入点；`MemoryConsolidator.consolidate` 的 `next_index` 参数在函数体内未被使用。

## 5. 修改记忆时的检查项

1. **不要直接删除或重命名字段。** `StrictModel` 使用 `extra="forbid"`，而 `memories` 表保存整份 JSON，删字段会让旧运行无法 `load_memory`、续跑或重生成报告。字段改名需使用别名或迁移校验器，参考 `SessionMemory.migrate_legacy_unlocked_profile`。
2. **同步全部读取点：** `CounselorAgent._allowed_memory_payload`、`_vector_query`（读取 `summaries[-1]`）、`_evidence_sources`、`CounselorAgent.review_session` 的 `allowed_memory`、`runtime/orchestrator.py::_consolidate_memory_pipeline`、`runtime/memory.py::MemoryConsolidator.consolidate`、`evaluation/safety_gate.py::SessionSafetyGate._leaked_fact_ids`。
3. **保持不变量：** 咨询师上下文不出私密档案；E.8 的等值白名单与空 `language_features` 不放松；候选记忆隔离与"仅胜者回流"不变；督导评分不写入记忆、不驱动计划。
4. **更新测试：** `tests/test_components.py`（payload 契约、清单合并、legacy 迁移、反回填）、`tests/test_e2e.py`（E.7→E.8→E.9→自评链路、记忆持久化）、`tests/test_dialogue_loop.py`、`tests/test_rollout_runtime.py`（候选隔离）。
5. **产物与文档：** 记忆结构变化会影响 `result.json`、SQLite、`trajectory.jsonl` 和报告内容；新增输出路径或迁移时按 [运行产物约定](RUN_ARTIFACTS.md) 处理并保留既有运行。


