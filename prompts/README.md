# `prompts/`

本目录共有 56 个提示词资产：55 个有当前运行链调用点（46 个整体督导量表和 9 个生成/评分模板），另有 `client/dialogue.jinja2` 仅作来源/风格参考。生成模板由 `src/psychsandbox/prompts.py::render_prompt` 在具体调用点渲染；目录中的文件不会自动启用。

## 实际使用情况

| 类别 | 文件数 | 当前状态 | 实际入口 |
|---|---:|---|---|
| `eval/` 中代码映射的量表 | 46 | 已使用 | `src/psychsandbox/evaluation/psycheval_supervisor.py` |
| `counselor/`、`simclient/`、`memory/` 生成提示词 | 8 | 已使用（Jinja2 模板） | `src/psychsandbox/prompts.py::render_prompt` |
| `rft/session_judge.jinja2` | 1 | 仅开启会谈 RFT 时使用 | `src/psychsandbox/evaluation/rollout.py` |
| `client/dialogue.jinja2` | 1 | 参考模板，未接入 | 无生产调用点 |

当前咨询师、来访者和会后记忆生成提示词以 **Jinja2 模板（`.jinja2`）** 存放。调用链路为：「Pydantic 领域对象构造输入 dict → Jinja2 渲染 → 调用大模型（结构化 JSON）→ Pydantic 输出验证」。当前 agent 直接调用 `render_prompt` 和 `complete_structured`，没有统一经过独立输入 schema；系统提示词由模板裸渲染生成，业务数据作为 `input_payload` 一并发送给 `complete_structured`。

- 咨询师规划、ReAct 执行和会后自评：`prompts/counselor/{planner,actor,review}_system.jinja2`，消费于 `src/psychsandbox/agents/counselor.py`
- 来访者规划与语言生成：`prompts/simclient/{planner,utterance}_system.jinja2`，消费于 `src/psychsandbox/agents/client.py`
- E.7 信息提取、E.8 档案合并、E.9 临床摘要： `prompts/memory/{extraction,merge,summary}_system.jinja2`，消费于 `src/psychsandbox/runtime/memory_pipeline.py`
- 通用「Pydantic → 渲染 → 模型 → Pydantic」管线封装： `src/psychsandbox/prompt_pipeline.py::run_pipeline`；当前生产调用点尚未调用此辅助函数。

> 提示词内容对齐 PsychAgent 的角色/公共上下文/风格约束（人物一致性、公开背景、历史摘要、上轮作业、逐角色输出、禁止元话语等），同时保留本仓库的 JSON 结构化输出指令，使模型输出可被 Pydantic `StrictModel` 直接解析。

## 为什么 `client/dialogue.jinja2` 未加载，如何接入

生产链为 `ClientSimulator.respond` → `ClientAgent.plan_turn/generate_utterance` → `client_simulation/prompts.py` 中的两个路径常量 → `render_prompt` → `complete_structured`。关闭 `patientact.enabled` 只跳过状态规划，语言生成仍使用 `simclient/utterance_system.jinja2`。

`client/dialogue.jinja2` 在引入五流派资源的 `b1b008f` 中添加；后续 `69102ab` 将已有 simclient 提示词改为 Jinja2，路径仍指向 simclient。当前没有 import、include 或 render 调用指向该参考模板。仅凭这些提交不能断言作者保留它的具体意图。

参考模板不能只改一个路径常量就启用：

| 参考模板要求 | 生产语言生成输入/契约 |
|---|---|
| `intake_profile.static_traits` | `static_profile` |
| 完整 `growth_experiences`、`modality_profile_text` | 仅授权的 `available_memories` 和已说过的 `known_memories` |
| `last_counselor_message` | `counselor_message` |
| `session_index`、`session_recaps`、`last_homework` | 当前没有这些顶层键；必要时须沿调用链传入经过筛选的内容 |
| 纯文本，禁止 JSON | `ClientUtterance` JSON：`utterance` 与 `disclosed_fact_ids` |

推荐把需要的人物/语言风格规则迁入现有 `simclient/utterance_system.jinja2`，保持唯一生产模板。不要将完整私密画像传给台词模型：本项目由规划器选择授权事实，语言生成再通过台词证据与泄漏检查。

如果确实要以 `client/dialogue.jinja2` 作为生产文件名，应先改写为上述受限输入及 JSON 契约，保留 `turn_signal`、阻断/歧义控制、修复指令和已披露记忆；再把 `CLIENT_UTTERANCE_TEMPLATE` 指向它，移除或标记原模板以免两份规则漂移。最后更新提示词版本，运行渲染、双阶段调用、未授权事实、泄漏重试和跨会谈记忆测试。当前改动没有启用此参考模板。

## 决策摘要的保存与展示

模型明确输出的 `planning.reasoning_summary/current_goal/plan_steps/action_input`、选技证据及 `client_turn_signal.rationale` 已随 `SessionRecord.turn_records` 保存到 SQLite、 `trajectory.jsonl` 和成功运行的 `result.json`。报告的“咨询师可审计规划与决策”展示这些摘要，来访者部分展示反应、行为、信任变化及简短依据；“逐轮技术细节”中可查看技能查询和拒绝原因。

这是结构化决策摘要，不是逐 token 内部思维链。报告按字段读取，不展示供应商内部 reasoning 字段；不为获取额外解释增加模型调用。旧记录没有相应字段时跳过。运行产物仍遵守 `runs` 目录约定。

## 已使用的 `eval/` 量表

`src/psychsandbox/runtime/orchestrator.py` 将 `prompts/eval` 传给 `PsychEvalSupervisor`。一个 case 的全部 session 完成后，督导师按流派选择以下文件，注入来访者背景和整条可见对话，再调用 `SUPERVISOR_MODEL`：

| 层级 | 共享量表 | 流派专属量表 |
|---|---|---|
| Counselor-Level | WAI、HTAIS、RRO、`custom_dim` 四维 | BT→MITI；CBT→CTRS；HET→TES；PDT→PSC；PMT→EFT-TFS |
| Client-Level | SCL-90、PANAS、RRO、SRS | BT→STAI；CBT→BDI-II；HET→CCT；PDT→IPO；PMT→SFBT |

完整文件名以 `psycheval_supervisor.py` 中 `Instrument.prompt_files` 为唯一映射来源。部分上游文件名包含弯引号，加载器会在同一目录做规范化文件名匹配。整体量表结果不回写下一 session 计划。

## 维护检查

1. 修改已使用量表时，对照 `Instrument.prompt_files`，确保路径和大小写一致。
2. 修改 `prompts/counselor|simclient|memory/` 下生成提示词文件时，同步更新 `PROMPT_TREE_VERSION` 并跑相关结构化输出测试。
3. 新增提示词资产时，先更新本表中的文件数量和入口，再更新根 README 的资源边界。

相关说明见根目录 [README](../README.md)、[Phase 1 数据流](../docs/PHASE1_IMPLEMENTATION.md)和 [第三方声明](../NOTICE.md)。
