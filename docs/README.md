# 文档索引

当前使用说明与历史研究分开维护。修改代码前先遵守根目录 [AGENTS.md](../AGENTS.md)，文档中的历史测试数字不能替代本次验证。

## 当前实现

- [项目启动](../README.md)、[Web 工作台](workbench/README.md)、[前端开发](../frontend/README.md)。
- [领域与模块边界](agents/domain.md)、[来访者模拟](CLIENT_SIMULATION.md)、[咨询师记忆](MEMORY.md)。
- [技能选择](SKILL_SELECTION.md)、[会谈 RFT](SESSION_RFT.md)、[逐条目 logprob 方法](../notes/logprob_scoring_borrowing.md)。
- [运行产物与恢复](RUN_ARTIFACTS.md)、[后续实验](ROADMAP.md)。
- [提示词维护](../prompts/README.md)、[资产入口](../assets/README.md)、[第三方许可](../THIRD_PARTY_LICENSES/README.md)。
- [Issue 操作](agents/issue-tracker.md)、[标签兼容](agents/triage-labels.md)。

## 研究与历史

[研究目录](research/README.md) 保存上游源码、论文与待实施方案；[历史目录](archive/README.md) 保存阶段实现和汇报材料。历史结论带原始日期，正文明确来源事实、当前实现与未实施建议。病例真相与合成策略的分离见 [ADR 0001](adr/0001-separate-case-truth-from-client-policy.md)。

原 CONTEXT 术语并入领域文档；原《记忆机制》拆入记忆文档与研究对照。原工作台设计/状态说明合并，阶段记录归档。AGENTS 引用的文件路径继续有效。
