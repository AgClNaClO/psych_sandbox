# 技能选择改进的候选实验

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-08-27提出五类方案：技能卡/适用条件补全、选组后微技能精筛、多路召回重排、有限纠错及多个方案独立评审。原比较针对当时基线，不是当前实施状态；对应来源和方案表保留为历史证据。

## 当前实现

现已实现公开依据、完整路径、超阈值向量缩减和一次纠错；技能树原文不改，也不添加自动短摘要。原建议和当前实现只部分重叠，按 [当前选技](../SKILL_SELECTION.md) 判定。

## 未实施建议与验证边界

多路召回、额外评审、适用性字段增强等需独立实验。优先固定候选集比较单次机制改变，不能同时扩大技能池、增加请求再将收益全部归因于树结构。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 库 | 可选末级元技能组 | 每组微技能中位数 | 单组最大微技能数 | 更可能的瓶颈 |
|---|---:|---:|---:|---|
| CBT stage1 | 22 | 26 | 43 | 展开后的微技能输入较长 |
| CBT stage3 | 11 | 18 | 46 | 展开后的微技能输入较长 |
| BT stage1 | 41 | 10 | 20 | 选组与展开均需关注 |
| PDT stage2 | 112 | 5 | 17 | 末级元技能粗筛更困难 |

| 方案 | 主要问题 | 是否引入程序相关性排序 | 成本与成熟条件 |
|---|---|---|---|
| A 技能卡与适用条件核对 | 只凭类别名称匹配、条件未知时仍选技能 | 否 | 低至中；需要审核卡片内容 |
| B PsychAgent 式微技能精筛 | 展开后候选过多、当前话语与技能未充分匹配 | 是 | 中；需要一致的向量模型与索引 |
| C 多路召回与重排 | 元技能粗筛漏掉跨组的适用微技能 | 是 | 中至高；需要召回和重排评测 |
| D 有限次数的纠错查询 | 首次候选不合适后无法再选其他组 | 否，可继续模型选 ID | 中；需要校准重查与停止条件 |
| E 多个技能方案的独立评审 | 单次选择缺少备选比较，技能与回复脱节 | 否，可保持目录精确查询 | 中至高；增加模型调用和评审偏差 |
| F 经审核的技能使用经验 | 忽略相似情境的成功条件和失败教训 | 最小版否；后续经验检索可选 | 需要高质量经验与严格数据划分 |

## 原记录来源链接

- [来源 1](https://arxiv.org/abs/2303.11366v4)
- [来源 2](https://arxiv.org/abs/2307.16789)
- [来源 3](https://arxiv.org/abs/2310.01798)
- [来源 4](https://arxiv.org/html/2401.15884v3)
- [来源 5](https://bge-model.com/Introduction/reranker.html)
- [来源 6](https://bge-model.com/tutorial/5_Reranking/5.2.html)
- [来源 7](https://github.com/AkariAsai/self-rag)
- [来源 8](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/agents/autocbt.py#L30)
- [来源 9](https://github.com/ECNU-ICALK/PsychAgent/blob/main/src/sample/skill_manager.py)
- [来源 10](https://github.com/HuskyInSalt/CRAG)
- [来源 11](https://github.com/OpenBMB/ToolBench#training-retriever)
- [来源 12](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/env_history.py#L38)
