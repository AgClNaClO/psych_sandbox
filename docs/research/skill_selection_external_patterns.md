# AutoCBT与Reflexion的反馈机制参考

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-08-27只读研究AutoCBT和Reflexion。实际AutoCBT源码来自XinHaiAgents固定提交db123ee7caca099ae51aaac0e6e2e71495431ed2，早于论文；同名AutoCBT仓库当时只有说明/许可。Reflexion核查提交218cf0ef1df84b05ce379dd4a8e47f17766733a0。前者督导修订草稿，后者失败反思进入行动上下文，都不是直接验证本仓库选技改进。

## 当前实现

当前已有一次查询纠错和公开选技依据，临床督导评分仍独立。原方案中的一次技能复核、同案例短反馈记忆属于迁移设想，不能因存在自评而宣布完整Reflexion已经实施。

2026-11-10 对照：现有 [技能独立试验](../workbench/SKILL_EVOLUTION_EXPERIMENT.md) 可承载固定上下文与两组新轨迹比较，提取的证据和版本单独保存；它不会把外部督导意见写入正式咨询师决策。引入草稿复核或反馈记忆时仍须作为新的实验条件，不能与已实现的一次查询纠错混记。

## 未实施建议与验证边界

可先做固定上下文配对：有无复核、少量有来源经验、两个平行计划；保持权限、候选数量和最终ID约束，单独计成本。未来接入外部代码须复核许可与接口，不复制过期机器配置。

阶段、候选和量表进度可以帮助区分耗时来源，但还需单独记录真实调用与 token 成本；完成计数不是效果指标。本次未刷新 AutoCBT 或 Reflexion 的上游提交，以下外部机制继续以原固定版本为证据。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 方向 | 一手论文 | 核查的官方实现 | 可用性及边界 |
|---|---|---|---|
| AutoCBT | Xu 等，2025-01-16，arXiv v1。[论文记录](https://arxiv.org/abs/2501.09426v1) | 作者团队 `CAS-SIAT-XinHai/XinHaiAgents` 中的 `examples/AutoCBT` 与 `backend/src/xinhai/arena/*/autocbt.py`；固定提交 `db123ee7caca099ae51aaac0e6e2e71495431ed2`，提交日期 2024-11-27。[提交](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/commit/db123ee7caca099ae51aaac0e6e2e71495431ed2)、[作者署名代码](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/agents/autocbt.py#L25) | 有可检查的实现；仓库 LICENSE 标记 CC0-1.0。启动说明包含实验机器路径及控制器、存储服务配置，需要环境适配，不能据此声称今天可以直接运行。[许可证](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/LICENSE)、[示例说明](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/README.md) |
| Reflexion | Shinn 等，2023-03-20 首发，2023-10-10 更新 v4；作者仓库标记 NeurIPS 2023。[论文记录](https://arxiv.org/abs/2303.11366v4)、[仓库说明](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/README.md) | `noahshinn/reflexion`，重点读 ALFWorld 分支；固定提交 `218cf0ef1df84b05ce379dd4a8e47f17766733a0`，提交日期 2025-01-14。[提交](https://github.com/noahshinn/reflexion/commit/218cf0ef1df84b05ce379dd4a8e47f17766733a0)、[执行入口](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/main.py#L25) | MIT；提供代码与运行日志，运行涉及模型服务和环境依赖。旧模型名称、SDK 与环境兼容性未在本机验证；公开代码不等于免费模型或可直接复现。[许可证](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/LICENSE)、[运行说明](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/README.md)、[模型参数入口](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/main.py#L25) |

| 已核实机制 | 实现证据 | 对“多候选”的准确解释 |
|---|---|---|
| 多个专长督导 | 中文配置定义共情、信念、反思、策略、鼓励五名督导；边连接咨询师与督导，未配置督导之间的边。[角色与拓扑配置](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/configs/xinhai_cbt_zh.yaml#L50) | 是多个反馈视角，不是五份独立咨询方案竞争 |
| 路由目标选择 | `AutoCBTTopology.__call__()` 从图的邻接节点构造 `candidate_agents`；只有一个目标时直接路由，否则调用模型选择合法目标，再由队列处理。[拓扑实现](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/topology/autocbt.py#L14) | 候选对象是通信代理；不能称为微技能检索、并行生成 N 个完整答案或 best-of-N 排名 |
| 草稿加反馈驱动生成 | `AutoCBTAgent.step()` 取历史中的草稿，并收集含督导角色关键词的消息作为 `revise_of_draft`；咨询师模板显式接收 `draft_response` 和 `revise_of_draft`。[生成入口](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/agents/autocbt.py#L25)、[修订模板](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/configs/xinhai_cbt_zh.yaml#L50) | 后续回复消费修改建议；该入口未实现对多个独立完整答案的统一打分选优 |
| 反馈回到接收者记忆 | 环境遍历消息目标，对每个接收者调用 `update_memory([message])`。[环境实现](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/environments/autocbt.py#L16) | 督导意见有进入后续上下文的代码路径，不只是写在报告中的旁观评价 |

| 环节 | 核查到的代码行为 | 直达来源 |
|---|---|---|
| 每个任务维护状态 | `main()` 为各环境建立独立的 `memory`、`is_success`、`skip`，每次 trial 执行后，在启用记忆时更新反思，并将状态写入 JSON | [main.py](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/main.py#L25) |
| 失败才生成反思 | `update_memory()` 只处理未成功且未跳过的环境；提示词要求基于失败动作提出简洁的新行动计划，不只是概述环境；结果追加到该环境记忆 | [generate_reflections.py](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/generate_reflections.py#L10) |
| 有界使用过去经验 | 生成反思与执行动作时都只取最近最多 3 条旧反思；底层列表继续追加，因此“最多 3 条”是上下文窗口限制，不是磁盘只保存 3 条 | [反思窗口](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/generate_reflections.py#L10)、[行动窗口](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/alfworld_trial.py#L41) |
| 反思确实进入决策输入 | `_get_base_query()` 将这些记忆放入任务提示；行动模型根据该基础提示和当前行动/观察历史生成下一动作，无需向量检索或相关性排序 | [env_history.py](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/env_history.py#L38)、[动作生成](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/alfworld_trial.py#L41) |
| 后续尝试重新开始 | `run_trial()` 重置环境、跳过已成功任务；在启用记忆时把对应任务的记忆传给 `alfworld_run()` | [alfworld_trial.py](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/alfworld_trial.py#L41) |

| 评价层 | 建议指标 | 解释边界 |
|---|---|---|
| 结构与权限 | ID 合法率；每份最终计划≤3；最终 Observation 是否与最终计划精确对应；Actor 引用 ID 是否属于该 Observation；跨流派/阶段与隐私越界次数 | 是可程序检查的不变量，不是咨询质量 |
| 元技能选择 | 两名具备相关训练的评审者盲评“目标匹配、适用前提、时机、冲突/冗余、是否应暂不调用技能”；允许多个合理答案 | 不把某个唯一 ID 集合作为当然金标准 |
| 微技能实施 | 选出的具体微技能与台词是否一致；是否误将支持性回应包装为某个未实际使用的技能 | 与元技能选择分别评分，避免把润色收益当成选技收益 |
| 反馈记忆 | 反馈是否有前文证据；下一次是否仍重复已确认的问题；过期记忆是否误导；是否跨案例污染 | “换了技能”本身不等于变好 |
| 成本与稳定性 | 重试、总调用、token、延迟；复核造成的退化比例；评审分歧 | 不只报告总体平均分或优胜案例 |

## 原记录来源链接

- [来源 1](https://arxiv.org/abs/2303.11366v4)
- [来源 2](https://arxiv.org/abs/2501.09426v1)
- [来源 3](https://arxiv.org/html/2303.11366v4#S3)
- [来源 4](https://arxiv.org/html/2303.11366v4#S4)
- [来源 5](https://arxiv.org/html/2501.09426v1#S3)
- [来源 6](https://arxiv.org/html/2501.09426v1#S4)
- [来源 7](https://arxiv.org/html/2501.09426v1#S4.SS3.SSS2)
- [来源 8](https://github.com/CAS-SIAT-XinHai/AutoCBT/tree/5abacef26825e4bd54cb5447468fb3d9bd81c15d)
- [来源 9](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/LICENSE)
- [来源 10](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/agents/autocbt.py#L25)
- [来源 11](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/environments/autocbt.py#L16)
- [来源 12](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/topology/autocbt.py#L14)
- [来源 13](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/README.md)
- [来源 14](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/configs/xinhai_cbt_zh.yaml#L50)
- [来源 15](https://github.com/CAS-SIAT-XinHai/XinHaiAgents/commit/db123ee7caca099ae51aaac0e6e2e71495431ed2)
- [来源 16](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/LICENSE)
- [来源 17](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/README.md)
- [来源 18](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/alfworld_trial.py#L41)
- [来源 19](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/env_history.py#L38)
- [来源 20](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/generate_reflections.py#L10)
- [来源 21](https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/main.py#L25)
- [来源 22](https://github.com/noahshinn/reflexion/commit/218cf0ef1df84b05ce379dd4a8e47f17766733a0)
