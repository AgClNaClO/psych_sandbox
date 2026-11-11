# HET-050 会后总结失败诊断与修复（2026-11-11）

运行：`20261111-004752-186196__psycheval-het-050__run-f2a71526b230`。

## 运行状态与四次中断

原运行最终于北京时间 2026-11-11 08:29:58 完成 9/9 场。`run.json`、正式数据库及最后一次工作台任务均为完成/成功状态，`result.json`、`trajectory.jsonl` 和 `report.html` 已保存。四条失败任务是历史尝试，不能据此把最终运行判为失败。

四次异常都在 RFT 已选出赢家后的 E.9 `DialogueSummaryAgent.summarize`，经 `complete_structured` 抛出；未发生在候选评分或 SQLite 写入。

| 中断时间（北京时间） | 场次 | 首次响应的字段错误 | 修复响应的最终错误 |
|---|---:|---|---|
| 01:02:18 | 1 | `important_results` 应为字符串数组，实际为字符串 | JSON 未正确闭合；`finish_reason=stop`，2242 completion tokens |
| 01:48:51 | 5 | 九个同级字段被放入 `goal_assessment` | JSON 未正确闭合；`finish_reason=stop`，3775 completion tokens |
| 02:16:38 | 5 | `goal_assessment.pending_items` 为额外字段 | 重复扩写至 8192 token，`finish_reason=length`，字符串被截断 |
| 02:25:46 | 6 | 额外字段 `goal_assessment.objective_recap_note=null` | 重复扩写至 8192 token，`finish_reason=length`，字符串被截断 |

证据：原目录的 `logs/errors.log`、`logs/progress.log` 和 `diagnostics/*.json`；首次/修复响应分别对应 `e94bdf687582/2c22e9dea619`、`aefcfec23640/26a90b55d44a`、`7faec561799d/c4d1f0d778f6`、`03360acc3da3/2a33fff5863d`。后续恢复日志确认已复用选中候选，原运行最终提交九场。

## 原因与修复

1. **总结结构漂移。** 模型将数组写为字符串，或把已知同级字段嵌入目标评估。提示现提供从当前 Pydantic 契约生成的结构示例，明确数组类型及对象闭合位置。网关另作两种无损修复：字符串原文包为单项数组；已知字段移回规范位置，仅在目标位置不存在或内容完全相同时处理。内容冲突、非空未知字段、未知 `null` 和缺失证据不享受该修复。
2. **修复时越过模型格式配置。** 原代码第一次使用 `json_object`，失败后无条件强制 `json_schema`；而当前自动配置为 `ecnu-max` 选择的是 `json_object`。现在各次尝试均遵守配置，并沿用原温度。四次最终错误均发生在原代码切换格式后；这些日志本身不足以证明服务端的具体实现或单独归因于某种解码方式。
3. **错误输出导致重复和截断。** 原代码把至多 12000 字符的输出尾部传给修复请求，大响应会失去开头和结构；修复再次失败即终止。现在最多三次生成，第二次修复仍失败则按原始输入重新生成；超过修复输入预算或 `finish_reason=length` 时跳过错误文本回灌。达到 token 上限的响应不能通过普通校验或单字段文本回退提交。

无损修复仍需通过完整 schema 校验，诊断保存原响应及 `local_repair` 路径。量表分数、logprob 解析、RFT 奖励、赢家选择和会后记忆整合顺序未改变。

## 验证与产物

合成回归覆盖格式模式 `off/json_object/json_schema`、原温度、三次生成上限、截断后重新生成、数组原文保留、错误层级修复、冲突拒绝及评分契约。首次真实探针进一步暴露了模型仍可能输出单个结果字符串和错误层级，因此最终实现增加了上述两类无损处理；失败探针也保留在各自目录中。

最终 `pytest -q -rs`：774 passed、1 skipped（旧运行产物缺失的可选归档回放）；相关定向测试 164 passed。完整测试记录位于 `runs/tests/20261111-091026-356387__pytest__66ef9ac06c9a/`。`git diff --check` 通过。

最终探针：[验证记录](../../runs/runtime/20261111-091006-322427__summary-repair-verification__468f4789fc2b/verification.json)，8/8 场景通过，其中真实 API 调用 6 次，输出均以 `stop` 结束，completion tokens 为 1110–3479。它使用原第 1、5、6 场的公开对话、计划和会前允许台账；部分请求先注入已有错误响应以触发恢复，实际网络调用在记录中标为 `live_api`，归档注入标为 `archived`。结果只验证总结输出与恢复，不重新生成完整疗程或评分。

探针对原运行目录所有文件逐一计算前后 SHA-256，确认原产物未改动；不写共享仿真库或工作台数据库。原报告继续保留实验当时的摘要与评分。
