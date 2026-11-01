# 咨询师记忆：写入、读取与会后整合

记忆不是完整病例的副本。只有公开对话中核验过的信息、会谈摘要和允许的后续事项进入咨询师上下文；模型内部评分和未披露事实留在审计或私有域。

## 四字段契约

| 字段 | 内容 | 写入方式 |
|---|---|---|
| `known_background` | 结构化已知背景及带出处的 `facts` | 台词核验后累积事实，E.8 合并档案 |
| `session_recaps` | 每个已完成会谈的一条回顾 | `MemoryConsolidator` 汇总 E.9、目标、状态、作业及风险记录 |
| `last_homework` | 带 ID、状态、来源会谈和完成证据的作业 | 本场真实布置后加入，证据充分才退役 |
| `checklist` | `per_session` 归档、开放项和待核实项 | 场内清单与 E.9 对账后归档 |

`case_id`、`migration_warnings` 是管理字段。历史十四键布局由模型迁移：背景并入 known_background，摘要/自评并入 recaps，作业和待办各归其位；旧 `between_session_context` 已删除。`completed_sessions`、`interventions_used`、`last_client_closing`、开放 `homework` 等是派生视图，不是新增存储抽屉。

## 会后执行顺序

1. 用会前记忆执行规则安全/披露审计。
2. E.7 从完整对话抽取信息，逐字段核验角色、轮次和原话；`language_features` 强制清空。
3. E.8 将已核验提取并入历史档案，等值白名单阻止私有真相回填，程序设置事实及管理来源。
4. E.9 根据对话、计划、末轮清单和开放事项 ID 生成临床摘要及 `item_updates`。
5. `MemoryConsolidator` 对账回顾、作业和事项；拒绝无证据的完成更新并留日志。
6. 咨询师读取合并后的允许记忆，逐目标自评；纵向进度与自评形成阶段动作和下一计划。
7. 保存会前记忆副本、轨迹及正式会谈，同步数据库与 JSONL。

RFT 只有赢家执行该闭环；其他候选不会写入记忆。E.7/E.8/E.9 默认使用 `temperature.control=0`，这是采样设置调整，未改写字段或整合顺序。

## 读取与场内清单

`MemoryViewBuilder` 支持 `full` 与 `recap_window`。两者都去掉管理字段、`safety_notes`、`relationship_events` 与语言特征；结构化风险摘要保留。窗口模式提供当前焦点、最近回顾及更早场次的一行摘要，并严格受字符预算约束；预算参数在 `memory_view` 配置中。

`SessionChecklist` 包含已完成项、重要信息、方法、结果与待办。每轮仅追加或显式解除；下一场从空清单开始。作业历史留在 recaps，当前开放作业留在 last_homework。退役依赖本场对话中的完成证据，不能因模型漏提而消失。

## 维护与验证

变更记忆时核对：来源逐字段可追踪；咨询师视图无私有事实及审计旁路；历史记录可迁移；重试不会重复提交；跨场清单不串线；RFT 落选状态不泄漏。完整轨迹仍保留完整证据，字符预算只是读取投影。PsychAgent 对照材料见 [记忆研究](research/memory-comparison.md)。
