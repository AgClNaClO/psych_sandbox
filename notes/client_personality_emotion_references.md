# 来访者人格与情绪建模：参考论文

核查日期：2026-10-01。以下为本次一手来源检索得到的论文。工程借鉴不等于真实来访者行为或临床效果已得到验证。实现建议见 [设计笔记](client_personality_emotion_design.md)。

| 文献与一手来源 | 可借鉴之处 | 证据边界 |
|---|---|---|
| Soto & John (2017), The Next Big Five Inventory (BFI-2): Developing and Assessing a Hierarchical Model With 15 Facets to Enhance Bandwidth, Fidelity, and Predictive Power. [机构仓储](https://escholarship.org/uc/item/16x6n05t) | 五大人格与十五 facets 的层级测量结构 | 不是人格到临床行为的确定性映射；量表使用另需核对许可 |
| Serapio-García et al., Personality Traits in Large Language Models (2023 preprint). [arXiv](https://arxiv.org/abs/2307.00184)；后续发表题名 A psychometric framework for evaluating and shaping personality traits in large language models (2025). [出版方](https://www.nature.com/articles/s42256-025-01115-6) | LLM 人格塑造与心理测量评估框架 | 问卷和生成行为的证据不能直接外推到中文、多会谈、临床来访者 |
| Marsella & Gratch (2009), EMA: A process model of appraisal dynamics. [作者原文](https://stacymarsella.org/publications/pdf/EMA_Dynamics.pdf) | 以评价、应对及事件解释变化构建情绪动态 | 可作架构启发，并非已经校准的 LLM 来访者情绪模型 |
| Kuppens, Oravecz & Tuerlinckx (2010), Feelings Change: Accounting for Individual Differences in the Temporal Dynamics of Affect. [作者机构原文](https://www.ppw.kuleuven.be/okp/_pdf/Kuppens2010FCAFI.pdf) | 个体情绪基线与时间变化、调节动力学 | 人类时间序列参数不能直接移植到聊天轮次 |
| PATIENT-Ψ: Using Large Language Models to Simulate Patients for Training Mental Health Professionals (EMNLP 2024). [ACL](https://aclanthology.org/2024.emnlp-main.711/) | 基于认知模型构建患者模拟，并评估训练场景 | CBT 取向不能直接覆盖项目五种疗法；模拟评价不等于治疗有效性 |
| AnnaAgent: Dynamic Evolution Agent System with Multi-Session Memory for Realistic Seeker Simulation (2025). [arXiv](https://arxiv.org/abs/2506.00551) | 动态演化与跨会谈记忆，适合比较多次会谈设计 | 不应将生成行为真实性评价当成真实纵向患者分布的证明 |
| Petrov, Serapio-García & Rentfrow (2024), Limited Ability of LLMs to Simulate Human Psychological Behaviours: a Psychometric Analysis. [arXiv](https://arxiv.org/abs/2405.07248) | 作为人格模拟评估的反证和方法限制参考 | 提醒避免通过问卷结果就宣布具有真实人格 |

## 建议阅读顺序

先读 EMA 与 Feelings Change，确定事件评价、基线、惯性和恢复的区别；然后读人格塑造论文与其心理测量限制；最后以 PATIENT-Ψ、AnnaAgent 对照临床画像和多会谈架构。

项目已有 PatientAct 专题笔记和实现，不必为了补人格再次重做其披露/阻抗流程。本次主检索未返回该编号的匹配结果，因此不在这里重复其未经本轮完整复核的实验数字；现有笔记不能替代原文核实。
