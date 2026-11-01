# PsychAgent与沙盒的记忆对照

## 来源事实（历史核查）

原记录于2026-10-03校对，分析更早的sandbox十四字段布局及PsychAgent的公开纪要。旧D盘检出已不存在，旧源码行号不能作为当前定位。PsychAgent主要保存已知背景、会谈回顾和上轮作业；摘要中也可能携带下一计划。默认公开记忆不等于向量检索或模型参数记忆。

## 当前实现

沙盒已在de99081将十四字段折叠为known_background、session_recaps、last_homework、checklist四字段。持久记忆完整保留，读取视图可选择full或recap_window并限制字符；咨询师看不到私有画像及仅供审计的记录。原CONTEXT术语合并至领域文档，原《记忆机制》的当前说明并入 [MEMORY](../MEMORY.md)。

## 未实施建议与验证边界

窗口压缩不能证明模型使用了正确证据，公开摘要也可能遗漏或失真。后续比较应固定会前事实、会谈长度和Token预算，检查引用、完成事项退役、跨场信息召回与泄漏；临床真实性须另测。旧文中“没有窗口”“十四抽屉”等描述只属于旧版本。

来源：[PsychAgent公开仓库](https://github.com/ECNU-ICALK/PsychAgent)。本次没有用旧检出重新验证历史行为。
