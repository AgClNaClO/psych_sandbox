# 咨询师记忆：写入、读取与会后整合

记忆不是完整病例的副本。只有公开对话中核验过的信息、会谈摘要和允许的后续事项进入咨询师上下文；模型内部评分和未披露事实留在审计或私有域。

## 四字段契约

| 字段 | 内容 | 写入方式 |
|---|---|---|
| `known_background` | 结构化已知背景及带出处的 `facts` | 台词核验后累积事实，E.8 合并档案 |
| `session_recaps` | 每个已完成会谈的一条回顾 | `MemoryConsolidator` 汇总 E.9、目标、状态、作业及风险记录 |
| `last_homework` | 带 ID、状态、来源会谈和完成证据的作业 | 本场真实布置后加入，证据充分才退役 |
| `checklist` | `per_session` 归档、开放项和待核实项 | 归档 E.9 总结，按已有 ID 应用咨询师的明确状态 |

`case_id`、`migration_warnings` 是管理字段。历史十四键布局由模型迁移：背景并入 known_background，摘要/自评并入 recaps，作业和待办各归其位；旧 `between_session_context` 已删除。`completed_sessions`、`interventions_used`、`last_client_closing`、开放 `homework` 等是派生视图，不是新增存储抽屉。

## 会后执行顺序

1. 用会前记忆执行规则安全/披露审计。
2. E.7 从完整对话抽取信息，逐字段核验角色、轮次和原话；`language_features` 强制清空。
3. E.8 将已核验提取并入历史档案，等值白名单阻止私有真相回填，程序设置事实及管理来源。
4. 咨询师在 E.9 根据完整对话、计划和台账生成会后总结，并以 `item_updates` 记录对已有待办的状态判断和依据。
5. `MemoryConsolidator` 归档回顾，核验作业证据，并按台账 ID 应用待办的明确状态。
6. 咨询师读取合并后的允许记忆，逐目标自评；纵向进度与自评形成阶段动作和下一计划。
7. 保存会前记忆副本、轨迹及正式会谈，同步数据库与 JSONL。

RFT 只有赢家执行该闭环；其他候选不会写入记忆。E.7/E.8/E.9 默认使用 `temperature.control=0`，这是采样设置调整，未改写字段或整合顺序。

## 读取本场对话与跨场记忆

自动仿真和人工会谈的 Planner 与 Actor 每轮通过 `dialogue` 读取按时间顺序排列的本场全部消息，开场时列表为空。已完成的询问或干预直接从对话中判断。

公开背景、后台议程和允许的跨场记忆由 JSON 字段 `known_background`、`session_agenda` 和 `session_memory` 提供。系统提示引用这些字段并说明使用规则。

`MemoryViewBuilder` 为跨场记忆提供 `full` 与 `recap_window` 两种视图。两者都过滤 `migration_warnings`、`safety_notes`、`relationship_events` 和语言特征，保留结构化风险摘要。窗口模式提供当前焦点、最近回顾及较早场次的一行归档，并按字符预算裁剪历史回顾。`memory_view` 配置只影响跨场记忆。

E.9 在会后从本场完整对话提取已完成项、重要信息、方法、结果和待办，再由 `MemoryConsolidator` 归档。`completed_items` 记录已做的动作，跨场待办由 `item_updates` 中已有 ID 的明确状态更新。`done` 与 `dropped` 移出开放台账，`open` 可将待核实条目确认为需跟进，省略的条目保留原状态。待办的 `evidence` 保存咨询师的判断依据，可概述对话。作业历史留在 `session_recaps`，当前开放作业留在 `last_homework`，显式完成作业的更新仍核对本场原话。

## 维护与验证

变更记忆时核对：来源逐字段可追踪；咨询师视图无私有事实及审计旁路；历史记录可迁移；重试不会重复提交；跨场清单不串线；RFT 落选状态不泄漏。完整轨迹仍保留完整证据，字符预算只是读取投影。PsychAgent 对照材料见 [记忆研究](research/memory-comparison.md)。
