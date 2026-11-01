# 人格与情绪研究文献索引

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-10-01的一手来源记录涵盖BFI-2、LLM人格心理测量、EMA、Feelings Change、PATIENT-Ψ、AnnaAgent及人格模拟反证。原表保留标题、年份和证据边界；这是当时的文献核查，不是本次重新检索。

## 当前实现

本仓库只将部分理论转化为受限提示与工程状态；测验结构不构成人格到临床行为的确定映射。参见 [设计研究](client_personality_emotion_design.md)。

## 未实施建议与验证边界

先明确事件评价、个体基线与恢复，再测试人格塑造和反证；中文文化、基础模型和提示词都应分层控制，不能直接把人类真实时间参数搬到聊天轮次。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 文献与一手来源 | 可借鉴之处 | 证据边界 |
|---|---|---|
| Soto & John (2017), The Next Big Five Inventory (BFI-2): Developing and Assessing a Hierarchical Model With 15 Facets to Enhance Bandwidth, Fidelity, and Predictive Power. [机构仓储](https://escholarship.org/uc/item/16x6n05t) | 五大人格与十五 facets 的层级测量结构 | 不是人格到临床行为的确定性映射；量表使用另需核对许可 |
| Serapio-García et al., Personality Traits in Large Language Models (2023 preprint). [arXiv](https://arxiv.org/abs/2307.00184)；后续发表题名 A psychometric framework for evaluating and shaping personality traits in large language models (2025). [出版方](https://www.nature.com/articles/s42256-025-01115-6) | LLM 人格塑造与心理测量评估框架 | 问卷和生成行为的证据不能直接外推到中文、多会谈、临床来访者 |
| Marsella & Gratch (2009), EMA: A process model of appraisal dynamics. [作者原文](https://stacymarsella.org/publications/pdf/EMA_Dynamics.pdf) | 以评价、应对及事件解释变化构建情绪动态 | 可作架构启发，并非已经校准的 LLM 来访者情绪模型 |
| Kuppens, Oravecz & Tuerlinckx (2010), Feelings Change: Accounting for Individual Differences in the Temporal Dynamics of Affect. [作者机构原文](https://www.ppw.kuleuven.be/okp/_pdf/Kuppens2010FCAFI.pdf) | 个体情绪基线与时间变化、调节动力学 | 人类时间序列参数不能直接移植到聊天轮次 |
| PATIENT-Ψ: Using Large Language Models to Simulate Patients for Training Mental Health Professionals (EMNLP 2024). [ACL](https://aclanthology.org/2024.emnlp-main.711/) | 基于认知模型构建患者模拟，并评估训练场景 | CBT 取向不能直接覆盖项目五种疗法；模拟评价不等于治疗有效性 |
| AnnaAgent: Dynamic Evolution Agent System with Multi-Session Memory for Realistic Seeker Simulation (2025). [arXiv](https://arxiv.org/abs/2506.00551) | 动态演化与跨会谈记忆，适合比较多次会谈设计 | 不应将生成行为真实性评价当成真实纵向患者分布的证明 |
| Petrov, Serapio-García & Rentfrow (2024), Limited Ability of LLMs to Simulate Human Psychological Behaviours: a Psychometric Analysis. [arXiv](https://arxiv.org/abs/2405.07248) | 作为人格模拟评估的反证和方法限制参考 | 提醒避免通过问卷结果就宣布具有真实人格 |

## 原记录来源链接

- [来源 1](https://aclanthology.org/2024.emnlp-main.711/)
- [来源 2](https://arxiv.org/abs/2307.00184)
- [来源 3](https://arxiv.org/abs/2405.07248)
- [来源 4](https://arxiv.org/abs/2506.00551)
- [来源 5](https://escholarship.org/uc/item/16x6n05t)
- [来源 6](https://stacymarsella.org/publications/pdf/EMA_Dynamics.pdf)
- [来源 7](https://www.nature.com/articles/s42256-025-01115-6)
- [来源 8](https://www.ppw.kuleuven.be/okp/_pdf/Kuppens2010FCAFI.pdf)
