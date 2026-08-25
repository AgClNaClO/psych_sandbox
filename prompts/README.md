# `prompts/`

本目录共有 54 个提示词资产，全部由当前运行链消费：46 个整体督导量表由文件加载器消费，
另有 8 个生成提示词（咨询师、来访者、记忆 E.7/E.8/E.9）以 **Jinja2 模板**存放，由
`src/psychsandbox/prompts.py::render_prompt` 在每次调用时用经 Pydantic 校验的业务数据渲染。

## 实际使用情况

| 类别 | 文件数 | 当前状态 | 实际入口 |
|---|---:|---|---|
| `eval/` 中代码映射的量表 | 46 | 已使用 | `src/psychsandbox/evaluation/psycheval_supervisor.py` |
| `counselor/`、`simclient/`、`memory/` 生成提示词 | 8 | 已使用（Jinja2 模板） | `src/psychsandbox/prompts.py::render_prompt` |

当前咨询师、来访者和会后记忆生成提示词以 **Jinja2 模板（`.jinja2`）** 存放。调用链路为：
「Pydantic 输入校验 → Jinja2 渲染提示词 → 调用大模型（结构化 JSON 输出）→ Pydantic 输出解析验证」。
输入数据先在对应 agent 侧校验/构造为 dict，再交给 `render_prompt` 注入模板；系统提示词由
模板裸渲染生成，业务数据作为 `input_payload` 一并发送给 `complete_structured`。

- 咨询师规划、ReAct 执行和会后自评：`prompts/counselor/{planner,actor,review}_system.jinja2`，
  消费于 `src/psychsandbox/agents/counselor.py`
- 来访者规划与语言生成：`prompts/simclient/{planner,utterance}_system.jinja2`，
  消费于 `src/psychsandbox/agents/client.py`
- E.7 信息提取、E.8 档案合并、E.9 临床摘要：
  `prompts/memory/{extraction,merge,summary}_system.jinja2`，
  消费于 `src/psychsandbox/runtime/memory_pipeline.py`
- 通用「Pydantic → 渲染 → 模型 → Pydantic」管线封装：
  `src/psychsandbox/prompt_pipeline.py::run_pipeline`

> 提示词内容对齐 PsychAgent 的角色/公共上下文/风格约束（人物一致性、公开背景、历史摘要、
> 上轮作业、逐角色输出、禁止元话语等），同时保留本仓库的 JSON 结构化输出指令，
> 使模型输出可被 Pydantic `StrictModel` 直接解析。

## 已使用的 `eval/` 量表

`src/psychsandbox/runtime/orchestrator.py` 将 `prompts/eval` 传给 `PsychEvalSupervisor`。一个 case 的
全部 session 完成后，督导师按流派选择以下文件，注入来访者背景和整条可见对话，再调用
`SUPERVISOR_MODEL`：

| 层级 | 共享量表 | 流派专属量表 |
|---|---|---|
| Counselor-Level | WAI、HTAIS、RRO、`custom_dim` 四维 | BT→MITI；CBT→CTRS；HET→TES；PDT→PSC；PMT→EFT-TFS |
| Client-Level | SCL-90、PANAS、RRO、SRS | BT→STAI；CBT→BDI-II；HET→CCT；PDT→IPO；PMT→SFBT |

完整文件名以 `psycheval_supervisor.py` 中 `Instrument.prompt_files` 为唯一映射来源。部分上游文件名
包含弯引号，加载器会在同一目录做规范化文件名匹配。整体量表结果不回写下一 session 计划。

## 维护检查

1. 修改已使用量表时，对照 `Instrument.prompt_files`，确保路径和大小写一致。
2. 修改 `prompts/counselor|simclient|memory/` 下生成提示词文件时，同步更新 `PROMPT_TREE_VERSION` 并跑相关结构化输出测试。
3. 新增提示词资产时，先更新本表中的文件数量和入口，再更新根 README 的资源边界。

相关说明见根目录 [README](../README.md)、[Phase 1 数据流](../docs/PHASE1_IMPLEMENTATION.md)和
[第三方声明](../NOTICE.md)。
