# 来访者人格与情绪动力学：实现建议

核查日期：2026-10-01。本文是设计建议，不代表已实现或已获得临床验证。论文核查见 [参考文献笔记](client_personality_emotion_references.md)。本次不修改运行时代码。

## 当前事实

- `domain/models.py` 的 `BigFive` 定义了五维 0–1 值，但 `ClientProfile.personality` 使用 `exclude=True`；当前 planner 经 `model_dump` 接收画像，五大人格并未进入该路径。不要简单移除 exclude：ADR 0001 有意区分病例证据和合成人格种子。
- 已有 evidence-backed `InteractionPrior`、`ClientExpressionStyle`，以及 reaction / intensity / behavior / resistance / trust 规划；并非从零开始。
- `ClientState` 已有 valence、arousal、distress、trust、resistance、hope、fatigue、rupture_state。
- `runtime/state.py` 用同一 `goal_progress_signal` 更新 hope、distress、valence、arousal。该信号来自 `agents/client.py` 中 reaction/behavior 到常数的映射。这是启发式耦合，并非校准过的情绪动力学。
- `prepare_session_state` 已有部分信任保留和疲劳恢复，但不足以表示不同会谈间隔、生活事件和个体恢复速度。

## 建议的边界

把病例事实、模拟配置、时变状态和语言表达分开。病例仍由 PsychEval 及其来源证据确定；新增独立 `ClientSimulationSpec`，不要将合成特质写回病例真相或咨询师记忆。

人格条目应允许未知值，并记录 origin（来源测量/证据推断/实验操纵）、source_ids、uncertainty、版本。未知不等于五维全部为 0.5。只从简短病例推断人格不能被称为人格测量；实验操纵应形成带 variant_id 的合成变体。

Big Five 用作行为概率和情绪参数的软调节，不作为固定规则。避免“高神经质必然阻抗”“内向必然少披露”等刻板映射。五维粗分先做可解释实验，暂不同时增加大量 facets、依恋标签和症状参数，以免不可辨识。

## 每轮流程

保留现有披露门控的时序：旧状态和咨询师话语决定授权范围；API planner 在私有上下文中完成事件评价和行为决策；局部状态转移生成当前反应状态；发言器仅接收授权事实、纯表达指令、必要状态；通过泄漏检查后提交状态，下一轮才使用新的信任值。

事件评价可新增 `ClientAppraisal`：感知威胁、被理解程度、目标一致性、控制感、边界压力、负荷；用话语跨度/消息 ID 和既有证据 ID 审计。字段和权重只是待检验的工程假设。不要把内部解释、隐藏经历或完整私有画像透传给发言器。

状态分层：稳定人格；较慢变化的信任、希望和应对习惯；快速变化的效价、唤醒、羞耻/恐惧等；疲劳及会谈间恢复。类别情绪按需要增加，防止重复维度无法辨识。

可用以下最小动力学作工程基线（不是文献原式，也不是临床定律）：

`x_next = project(mu + R(dt, theta) * (x - mu) + B(theta) * appraisal + noise)`

其中 mu 是个体基线，R 是时间相关惯性/恢复，B 是事件敏感性；theta 是模拟参数，人格只能对 theta 提供待校准的弱先验。先用对角 R 和少量参数，限制参数范围、每轮变化和饱和。噪声是可追踪的可选模拟扰动，不替代生产 API 决策；记录种子也不能保证远端模型复现。

将瞬时痛苦与治疗进展分开：被理解可能同时提高信任与痛苦；回避可以暂时减轻痛苦而没有治疗进展。不能把唤醒下降、语言合作、透露更多或积极措辞自动当成疗效。

会谈间用明确的时间间隔恢复瞬时状态，保留慢状态；外部事件必须来源支持或显式标记为合成实验输入，不能偷偷补成病例经历。

## 工程落点与顺序

1. 在 domain 和配置层新增私有模拟契约、来源/未知语义及版本，保持旧基线可运行。
2. 在 compact policy 的现有规划调用中增加 appraisal，避免初期多加多个串行 API；faithful 模式另行保留可比性。
3. 在 state updater 中独立计算情绪转移；simulator 明确 state_before / response_state / state_after，防止信任双重累计或同轮自授权披露。
4. 发言 payload 只新增不含事件内容的表达指令和允许的状态，验证强度实际影响语言，不能仅改内部数字。
5. 完成隔离、持久化和回放后，再加入会谈间恢复与人格变体。

实现时必须读取 MEMORY、SESSION_RFT、RUN_ARTIFACTS 文档。RFT 的各候选共享相同人格和初始状态，只能提交胜出候选的状态；候选采样得到的轨迹并不是自然来访者总体分布。保留五种疗法原生概念化，不把所有来访者压成 CBT。不得以 holistic supervisor 或 RFT 奖励驱动情绪改善。

## 验证与识别风险

- 2×2 消融：人格开/关 × 动力学开/关，使用同一组病例、咨询师输入和初始条件；分层覆盖五种疗法，多次 API 重复。
- 固定刺激测试：准确理解、误解、强迫披露、澄清、沉默、破裂后修复。成对控制输入，检查变化方向及可解释差异。
- 分别评估事实忠实度、泄漏、行为差异、跨轮稳定性、情绪惯性/恢复、关系破裂修复、专家盲评，不用单一平均分。
- 人格测验作辅助，主要检查未知场景的行为泛化；知道预设人格的裁判存在循环验证风险。
- 真实时间序列研究不能直接给聊天轮次参数；参数需要数据或专家校准。先标为机制原型，报告区间与敏感性，避免虚假精度。
- 中文文化、咨询师风格、基础模型、提示词和 RFT 选择都可能制造“人格差异”；应做分层和跨模型验证。
- 有效工程测试包括：边界与有限值、无刺激恢复、分支隔离、重试不重复提交、恢复运行状态一致、私有字段不进入咨询师视图。

## 额外的一手基础文献

- Kuppens, Oravecz & Tuerlinckx (2010), *Feelings Change: Accounting for Individual Differences in the Temporal Dynamics of Affect*. [作者机构原文](https://www.ppw.kuleuven.be/okp/_pdf/Kuppens2010FCAFI.pdf)。用于理解个体情绪基线、波动与调节动力学，不能直接移植真实时间参数到会谈轮次。
- Soto & John (2017), *The Next Big Five Inventory (BFI-2): Developing and Assessing a Hierarchical Model With 15 Facets to Enhance Bandwidth, Fidelity, and Predictive Power*. [机构仓储](https://escholarship.org/uc/item/16x6n05t)。提供五维和十五 facets 的测量结构，不提供人格到咨询行为的确定性映射。
