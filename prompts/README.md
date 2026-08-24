# `prompts/`

本目录共有 54 个提示词资产，全部由当前运行链消费：46 个整体督导量表由文件加载器消费，
另有 8 个生成提示词（咨询师、来访者、记忆 E.7/E.8/E.9）由 `src/psychsandbox/prompts.py`
中的 `load_prompt` 在模块导入时读取。

## 实际使用情况

| 类别 | 文件数 | 当前状态 | 实际入口 |
|---|---:|---|---|
| `eval/` 中代码映射的量表 | 46 | 已使用 | `src/psychsandbox/evaluation/psycheval_supervisor.py` |
| `counselor/`、`simclient/`、`memory/` 生成提示词 | 8 | 已使用 | `src/psychsandbox/prompts.py` 的 `load_prompt` |

当前咨询师、来访者和会后记忆生成提示词以文本文件存放，由 `src/psychsandbox/prompts.py`
的 `load_prompt` 在模块导入时读取：

- 咨询师规划、ReAct 执行和会后自评：`prompts/counselor/{planner,actor,review}_system.txt`，
  消费于 `src/psychsandbox/agents/counselor.py`
- 来访者规划与语言生成：`prompts/simclient/{planner,utterance}_system.txt`，
  消费于 `src/psychsandbox/client_simulation/prompts.py`
- E.7 信息提取、E.8 档案合并、E.9 临床摘要：
  `prompts/memory/{extraction,merge,summary}_system.txt`，
  消费于 `src/psychsandbox/runtime/memory_pipeline.py`

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
