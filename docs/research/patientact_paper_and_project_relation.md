# PatientAct论文与项目适配边界

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

原核查依据PatientAct arXiv 2608.12750v2：静态身份与动态记忆分离，以话题和信任控制检索、反应、行为与阻抗，再受限发言。论文人评和自动裁判可能不一致，机制证据不能代替临床效果。原实验数字和对照表保留为历史摘录。

## 当前实现

Compact压缩内部决策为一次规划；Faithful分阶段规划并在接受台词后判断信任。项目额外保留会谈范围、依赖、歧义、台词证据和泄漏检查；blocked只传元数据，生成器不见完整画像。详见 [实现说明](../CLIENT_SIMULATION.md)。

## 未实施建议与验证边界

真实度、阻抗质量、事实忠实及披露节奏需独立评价。关闭记忆的基线故意不直喂私有画像，因此不宣称逐项复现论文消融。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 指标 | 结果（5 分制） | 一致性 |
|---|---:|---:|
| 临床可信度 | 4.43 ± 0.59 | α = 0.41 |
| 内部一致性 | 4.38 ± 0.58 | α = 0.43 |
| 个案具体性 | 4.32 ± 0.52 | α = 0.43 |
| 临床深度 | 4.28 ± 0.55 | α = 0.45 |

| 人工评分 | PatientAct | 次优基线 | 增益 |
|---|---:|---:|---:|
| 一致性 | 4.37 | 3.98 | +0.39 |
| 披露节奏 | 4.15 | 3.65 | +0.50 |
| 阻抗质量 | 3.82 | 3.15 | +0.67 |
| 情绪真实性 | 4.15 | 3.83 | +0.32 |
| 行为真实性 | 4.15 | 3.52 | +0.63 |

| PatientAct 论文机制 | 当前项目对应物 | 关系 |
|---|---|---|
| 静态身份/表达与动态记忆分离 | `ClientProfile.static_traits`、`DisclosureItem` | 结构思想相近，但字段来自 PsychEval 编译，不照搬论文生成画像 |
| 激活标签 + 信任阈值 | `TagActivationMatcher`、`DisclosureGate.evaluate` | 当前实现还加入 session scope、依赖条件、歧义消解 |
| retrieved 与 blocked 分离 | `DisclosureDecision.retrieved/blocked` | blocked 只提供元数据，不授权发言模型取得正文 |
| 反应 → 行为 → 阻抗 → 信任 | `FaithfulPatientActPolicy` 的分阶段结构 | 明确作为研究适配器；阻抗出现时为 4 次，否则 3 次规划调用 |
| 低成本实现 | 默认 `CompactPatientActPolicy` | 把内部决策压成 1 次规划调用，不是论文的逐阶段调用形态 |
| 生成后更新信任 | `ClientTurnSignal.trust_change` → `StateUpdater` | 信任变化下一轮才影响披露 |
| 防止整份画像直接外泄 | 发言前 allowlist + `PrematureDisclosureGuard` | 属于本项目额外强化的信息边界与失败恢复机制 |

## 原记录来源链接

- [来源 1](https://arxiv.org/abs/2608.12750)
- [来源 2](https://arxiv.org/html/2608.12750v2)
- [来源 3](https://arxiv.org/html/2608.12750v2#S1)
- [来源 4](https://arxiv.org/html/2608.12750v2#S2)
- [来源 5](https://arxiv.org/html/2608.12750v2#S3.SS1)
- [来源 6](https://arxiv.org/html/2608.12750v2#S3.SS2)
- [来源 7](https://arxiv.org/html/2608.12750v2#S3.SS3.SSS1)
- [来源 8](https://arxiv.org/html/2608.12750v2#S3.SS3.SSS2)
- [来源 9](https://arxiv.org/html/2608.12750v2#S3.SS3.SSS3)
- [来源 10](https://arxiv.org/html/2608.12750v2#S3.SS3.SSS4)
- [来源 11](https://arxiv.org/html/2608.12750v2#S4.SS1)
- [来源 12](https://arxiv.org/html/2608.12750v2#S4.SS2)
- [来源 13](https://arxiv.org/html/2608.12750v2#S5)
- [来源 14](https://arxiv.org/html/2608.12750v2#S6)
- [来源 15](https://github.com/AgClNaClO/psych_sandbox/tree/c1b796392874e99aebbfa226653f0dad95b70ac9)
- [来源 16](https://github.com/Sahandfer/PatientHub)
