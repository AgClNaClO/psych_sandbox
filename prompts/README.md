# `prompts/`

本目录共有 93 个提示词资产。它们并非全部进入当前 `psych-sandbox` 运行链：46 个被文件加载器
实际消费，47 个作为 Psych-new 来源模板或尚未接入的评测参考保留。

## 实际使用情况

| 类别 | 文件数 | 当前状态 | 实际入口 |
|---|---:|---|---|
| `eval/` 中代码映射的量表 | 46 | 已使用 | `src/psychsandbox/evaluation/psycheval_supervisor.py` |
| `eval/` 其余量表/对话评测 | 14 | 未接入 | 无当前运行入口 |
| `psychagent/` | 29 | 未接入 | 来源于 Psych-new 的生成/技能模板 |
| `public/` | 3 | 未接入 | 来源于 Psych-new 的公共上下文模板 |
| `client/dialogue.jinja2` | 1 | 未接入 | 来源于 Psych-new 的来访者模板 |

因此，“仓库中存在”不等于“当前 API 调用会读取”。当前咨询师、来访者和会后记忆生成提示词
是版本化 Python 常量：

- 咨询师规划、ReAct 执行和会后自评：`src/psychsandbox/agents/counselor.py`
- 来访者规划与语言生成：`src/psychsandbox/client_simulation/prompts.py`
- E.7 信息提取、E.8 档案合并、E.9 临床摘要：`src/psychsandbox/runtime/memory_pipeline.py`

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

## 保留但未接入的文件

- `psychagent/<therapy>/counsel|summary|profile/`：Psych-new 的五流派生成模板。
- `psychagent/skill/`：Psych-new 的技能选择与改写模板。
- `public/` 和 `client/`：Psych-new 的公共上下文及来访者生成模板。
- `eval/PHQ_9`、`dialogue_*`、`human_eval`、`plan_consistency` 和
  `human_vs_llm_eval.txt`：当前 `Instrument` 映射未引用的评测模板。

这些文件当前只用于来源对照。要接入其中任何文件，必须先建立明确加载入口、输入/输出契约和
测试；仅修改模板内容不会改变当前仿真行为。

## 维护检查

1. 修改已使用量表时，对照 `Instrument.prompt_files`，确保路径和大小写一致。
2. 修改 Python 内嵌生成提示词时，同步更新其版本常量和结构化输出测试。
3. 新接入保留模板时，先更新本表中的文件数量和状态，再更新根 README 的资源边界。

相关说明见根目录 [README](../README.md)、[Phase 1 数据流](../docs/PHASE1_IMPLEMENTATION.md)和
[第三方声明](../NOTICE.md)。
