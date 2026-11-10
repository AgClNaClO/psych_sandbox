# 静态资产入口

`skills/sect/<bt|cbt|het|pdt|pmt>/<stage1|stage2|stage3>` 保存原元技能和微技能JSON。生产加载器保留来源ID、流派和阶段，批准后才可用；运行时派生完整路径，不回写原树，不使用附带的旧.pt向量。

截至 2026-11-10，五流派注册表加载 677 个元技能、4481 个原子技能。这是当前静态资源规模，不包含工作台 overlay 或独立试验创建的候选版本。

元技能组按公开证据选择并精确展开，只有超阈值目录才向量缩减；见 [技能选择](../docs/SKILL_SELECTION.md)。

`profiles/` 是Psych-new来源对照资产，不是模拟病例入口。生产病例来自data下原始记录及可重建缓存，不能把同名ID自动映射到来源画像。画像详情见 [profiles说明](profiles/README.md)，许可见 [NOTICE](../NOTICE.md)。

独立技能试验从只读资产树创建带哈希的基线，提取与合并保存到 `runs/runtime` 的实验快照，不回写这里的 JSON。正式发布指针和实验版本分别维护，见 [试验边界](../docs/workbench/SKILL_EVOLUTION_EXPERIMENT.md)。
