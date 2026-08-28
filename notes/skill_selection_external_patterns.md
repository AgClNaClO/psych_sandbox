# 技能选择的外部参考：AutoCBT 督导修订与 Reflexion 反馈记忆

> 2026-08-28 更新：本文保留调查当时的分析与方案，不作为现行实现说明。项目已迁至 `D:/0test/psych_sandbox`；当前已实现按需向量筛选、公开选技依据、一次纠错及可选会谈 RFT。原子技能只新增完整路径，不新增原文摘要。现行机制见 [技能选择](../docs/SKILL_SELECTION.md) 与 [会谈 RFT](../docs/SESSION_RFT.md)。本地链接已迁移，历史代码行号不再作为现行定位依据。

调查日期：**2026-08-27（Asia/Shanghai）**。仅依据一手论文、作者或作者团队官方仓库；代码按固定提交引用。本次只读核对机制，**没有运行外部项目、调用咨询模型或验证咨询效果**，只新增本笔记。

范围：方向一选 AutoCBT，方向二选 Reflexion；不另行扩展 ExpeL，也不研究 ToolLLM、Reranker、Self-RAG/CRAG、PsychAgent。下文“原项目事实”“迁移建议”“待验证推测”分别标明，迁移建议均未实施。

## 1. 当前项目约束与结论

当前链路按任务约定保持：**Planner 最多选择 3 个叶元技能 → 程序精确展开所选组下全部可用微技能 → Actor**。本地 Planner 提示词限制 ID 与数量；目录按流派、阶段、审批和风险过滤，不做相关性排序；Actor 只能使用 Observation 中的微技能。这里不恢复逐层树遍历，也不引入向量排序。[Planner 提示词][local-planner]、[目录实现][local-catalog]、[Actor 提示词][local-actor]

优先考虑两种小改动的实验方案：**本轮的一次选技复核**、**同一案例后续决策使用的短反馈记忆**。少量平行计划作为后续对照，不先搭建完整多代理网络。依据是 AutoCBT 已实现草稿与督导建议进入后续生成，Reflexion 已实现失败反思进入后续行动上下文；把前者改成技能选择复核、把后者用于咨询连续进程，是本项目的迁移设计，尚无直接效果证据。[AutoCBT 生成入口][a-agent]、[Reflexion 记忆注入][r-history]

## 2. 来源、版本与开源可用性

| 方向 | 一手论文 | 核查的官方实现 | 可用性及边界 |
|---|---|---|---|
| AutoCBT | Xu 等，2025-01-16，arXiv v1。[论文记录][a-abs] | 作者团队 `CAS-SIAT-XinHai/XinHaiAgents` 中的 `examples/AutoCBT` 与 `backend/src/xinhai/arena/*/autocbt.py`；固定提交 `db123ee7caca099ae51aaac0e6e2e71495431ed2`，提交日期 2024-11-27。[提交][a-commit]、[作者署名代码][a-agent] | 有可检查的实现；仓库 LICENSE 标记 CC0-1.0。启动说明包含实验机器路径及控制器、存储服务配置，需要环境适配，不能据此声称今天可以直接运行。[许可证][a-license]、[示例说明][a-readme] |
| Reflexion | Shinn 等，2023-03-20 首发，2023-10-10 更新 v4；作者仓库标记 NeurIPS 2023。[论文记录][r-abs]、[仓库说明][r-readme] | `noahshinn/reflexion`，重点读 ALFWorld 分支；固定提交 `218cf0ef1df84b05ce379dd4a8e47f17766733a0`，提交日期 2025-01-14。[提交][r-commit]、[执行入口][r-main] | MIT；提供代码与运行日志，运行涉及模型服务和环境依赖。旧模型名称、SDK 与环境兼容性未在本机验证；公开代码不等于免费模型或可直接复现。[许可证][r-license]、[运行说明][r-readme]、[模型参数入口][r-main] |

**容易找错的仓库：**作者团队另有同名 `CAS-SIAT-XinHai/AutoCBT`，核查提交 `5abacef26825e4bd54cb5447468fb3d9bd81c15d` 的文件树只有 `.gitignore`、`LICENSE`、`README.md`，不是本文实现依据。实际代码来自上表 XinHaiAgents；其文件头署名包含论文第一作者 Ancheng Xu。[同名仓库快照][a-placeholder]、[实际代码署名][a-agent]

上述 XinHaiAgents 快照早于 AutoCBT 论文，不能假定它与论文实验版本完全一致；下面保留已发现的差异，不补写未公开的实现。

## 3. 方向一：AutoCBT 实际做什么

### 3.1 原项目事实与代码定位

AutoCBT 面向**单轮心理咨询问答的回复生成**：咨询师可以直接回应，也可以把草稿交给督导，收到建议后继续生成。论文将其作为动态路由与监督机制，而不是技能树搜索算法。[论文摘要][a-abs]、[方法与图 1][a-method]

| 已核实机制 | 实现证据 | 对“多候选”的准确解释 |
|---|---|---|
| 多个专长督导 | 中文配置定义共情、信念、反思、策略、鼓励五名督导；边连接咨询师与督导，未配置督导之间的边。[角色与拓扑配置][a-config] | 是多个反馈视角，不是五份独立咨询方案竞争 |
| 路由目标选择 | `AutoCBTTopology.__call__()` 从图的邻接节点构造 `candidate_agents`；只有一个目标时直接路由，否则调用模型选择合法目标，再由队列处理。[拓扑实现][a-topology] | 候选对象是通信代理；不能称为微技能检索、并行生成 N 个完整答案或 best-of-N 排名 |
| 草稿加反馈驱动生成 | `AutoCBTAgent.step()` 取历史中的草稿，并收集含督导角色关键词的消息作为 `revise_of_draft`；咨询师模板显式接收 `draft_response` 和 `revise_of_draft`。[生成入口][a-agent]、[修订模板][a-config] | 后续回复消费修改建议；该入口未实现对多个独立完整答案的统一打分选优 |
| 反馈回到接收者记忆 | 环境遍历消息目标，对每个接收者调用 `update_memory([message])`。[环境实现][a-env] | 督导意见有进入后续上下文的代码路径，不只是写在报告中的旁观评价 |

### 3.2 实现限制与证据强度

**原项目事实：**论文评估使用中英文各 100 条问答，包含 GPT-4o-mini 自动评分和心理学专业人员对回复的评审；评价对象是生成回复。本文不把这些结果解释为症状改善、长期咨询疗效或当前技能库的选技正确率。[数据与实验 §§3.3–4.2][a-experiment]

**论文与代码存在差异：**论文讨论将“同时选择来访者与督导”视为结束信号，而所核查 `AutoCBTAgent.routing()` 在该情形下继续重试；论文列举五种路由方式，中文配置实际只启用三种。外层虽然配置了轮数限制，内部路由仍有 `while True`，因此不能把外层上限当成所有调用都必然终止的保证。[论文 §4.3.2][a-discussion]、[路由重试][a-agent]、[路由配置][a-config]、[外层检查][a-env]

**迁移限制：**不能把五种 CBT 回复要求机械套到本项目所有流派、所有阶段；也不能把“识别信念、提出挑战”等模板内容强制塞进每一轮。原配置是其特定问答生成设定，尚未证明适合当前多流派、多阶段、短回复链路。[原模板][a-config]、[本地 Actor 约束][local-actor]

## 4. 方向二：Reflexion 如何让反馈影响后续决策

### 4.1 原项目事实与实现闭环

Reflexion 用语言反馈改变后续生成的上下文，**不依靠更新模型权重**。论文区分行动生成、评价、反思三个职责；行动历史与评价信号生成反思文本，再存入经验记忆供后续尝试使用。[论文摘要][r-abs]、[方法 §3][r-method]

这里选 ALFWorld 代码，因其能明确追踪“失败 → 新计划 → 下一次行动”，不将仓库其他任务的细节混入这个分支：

| 环节 | 核查到的代码行为 | 直达来源 |
|---|---|---|
| 每个任务维护状态 | `main()` 为各环境建立独立的 `memory`、`is_success`、`skip`，每次 trial 执行后，在启用记忆时更新反思，并将状态写入 JSON | [main.py][r-main] |
| 失败才生成反思 | `update_memory()` 只处理未成功且未跳过的环境；提示词要求基于失败动作提出简洁的新行动计划，不只是概述环境；结果追加到该环境记忆 | [generate_reflections.py][r-reflect] |
| 有界使用过去经验 | 生成反思与执行动作时都只取最近最多 3 条旧反思；底层列表继续追加，因此“最多 3 条”是上下文窗口限制，不是磁盘只保存 3 条 | [反思窗口][r-reflect]、[行动窗口][r-trial] |
| 反思确实进入决策输入 | `_get_base_query()` 将这些记忆放入任务提示；行动模型根据该基础提示和当前行动/观察历史生成下一动作，无需向量检索或相关性排序 | [env_history.py][r-history]、[动作生成][r-trial] |
| 后续尝试重新开始 | `run_trial()` 重置环境、跳过已成功任务；在启用记忆时把对应任务的记忆传给 `alfworld_run()` | [alfworld_trial.py][r-trial] |

### 4.2 可以说什么，不能说什么

**原项目事实：**论文实验覆盖 ALFWorld、HotPotQA 和代码生成基准，不是心理咨询试验；环境成功信号、答案匹配或程序测试反馈与来访者反馈不是同一种评价条件。[实验 §4][r-experiment]

**迁移判断：**可借的是“把有依据的失败反馈转成下次可执行的选择约束”，而不是把咨询过程当成可以无限重置的关卡。ALFWorld 实现主要保留同一任务的重试经验，并不直接证明跨来访者的通用经验规则有效。[每任务记忆与重试][r-main]、[反思提示][r-reflect]

**待验证推测：**把这类记忆交给本项目 Planner，可能减少在来访者明确表示不适合后继续重复同类技能；但模型也可能误判原因，形成“某技能总是不好”的错误规则。反思文本是待核实的行动建议，不是因果证明或新的临床事实。[原始反思生成方式][r-reflect]

## 5. 对当前技能选择的三个迁移方案

本节全部是**建议与待验证假设**，不是两个原项目已经实现的咨询选技算法。

### A. 优先：对本轮选技做一次有依据的复核

借鉴 AutoCBT 的草稿与反馈接口，把复核对象从整段回复改为 **Planning + 精确展开的 Observation**。最小实验流程：

```text
现有风险/权限/流派/阶段硬约束
→ Planner P0（≤3 个元技能）→ 精确展开 Observation O0
→ 一次 Reviewer：通过，或指出具体适用性问题和修订要求
→ 若需修订，Planner 仅重选一次 P1（仍≤3 个）并重新精确展开 O1
→ Actor 只接收最终 Planning 与其对应 Observation
```

Reviewer 检查本轮目标、已披露证据、技能适用前提、重复或冲突以及来访者边界；反馈采用“问题—证据位置—建议保持/替换/暂缓—不确定之处”。元技能替换仍由能看到合法目录的 Planner 完成；Reviewer 不自行发明 ID。基于的是 AutoCBT 的反馈进入生成机制，**把反馈作用点提前到选技，是迁移假设**。[AutoCBT 模板][a-config]、[本地选技边界][local-catalog]

注意：如果元技能组本身不合适，只润色 Actor 台词未必能补救；如果只是表述问题，不应无故换技能。把“选择错误”和“实施错误”分开记录。相对通常的两次模型调用，方案 A 增加一次 Reviewer、最多一次重规划；设置总调用与 token 上限，不能照搬无界重试。高风险仍走现有安全分支，不参与候选试探。[当前生成入口][local-counselor]、[原实现重试限制][a-agent]

### B. 优先：同一案例使用最多三条有依据的选技经验

借鉴 Reflexion 的每任务记忆，在下一轮或下一会谈的 Planner 输入中增加少量结构化反馈。建议每条记录：`发生阶段 / 原元技能与微技能 ID / 已披露反馈及证据位置 / 下次选择条件 / 不适用条件 / 来源与时间 / 复核状态`。该字段设计是本项目建议，不是 Reflexion 原始 schema。[原始每任务状态][r-main]、[有界反思使用][r-reflect]

先限定**同一案例、同一流派、经复核仍适用于当前阶段**，按时间取最近最多 3 条，不用向量排序；条件失效就不注入，且不覆盖当前显式意愿。虚构示例：“本轮对方明确不愿做练习；在意愿改变前避免再次安排同类练习，可先澄清顾虑。”这只是反馈格式示例，不是临床规则，也不是原论文结论。[原记忆注入方式][r-history]

必须沿用当前信息权限：反馈只能引用当时已经披露的信息和允许记忆，不读取来访者私有档案，不使用未来轮次信息。项目已有会后 review 与纵向进展驱动后续计划；可先离线比较其现有摘要与上述反馈条目，避免重复记忆。**现有会话规则评估和完整轨迹后的 `PsychEvalSupervisor` 分数继续只作审计，不回灌成 Planner 奖励。**[项目运行约束][local-guidance]、[Planner 已有记忆输入][local-planner]

### C. 次选：两个平行计划，而不是扩大最终技能数

若 A/B 显示确有选技问题，可让 Planner 对同一合法目录独立提出两个计划，每份仍最多 3 个元技能，再用公开证据和适用前提比较，选出一份后精确展开全部微技能交给 Actor。**不能把两份计划的技能取并集交给 Actor，也不对微技能做向量排名。**重复计划需要去重并记录，不能把文字改写当成策略多样性。

这是受 AutoCBT 多反馈视角启发的额外实验，**不是 AutoCBT 已有的 best-of-N 实现**。潜在收益是暴露单次规划遗漏；潜在代价是调用增加、候选同质化和评审偏爱语言漂亮的计划。它不会减少所选元技能组的展开规模，也不能解决组内微技能过多的问题。[原拓扑与候选含义][a-topology]、[本地全量展开][local-catalog]

## 6. 建议的小规模验证：先测选择机制，不谈疗效

以下是未执行的离线实验设计；不改生产链路、不面向真实来访者在线试错。

### 6.1 固定上下文的配对比较

1. 先用 10 个开发快照确定提示与评审表，再冻结设置。另取 30 个不重叠的测试快照，例如 CBT 三阶段各 10 个；以案例隔离开发集与测试集。只给模型截至该轮已披露的信息。其他流派之后单独验证，不外推 CBT 结果。
2. 第一轮只比三组：原链路；A（最多一次复核/重选）；B（有界反馈记忆）。B 使用已有公开前文或人工明确标注的反馈；没有可用历史就保持空记忆，不能为凑样本生成“已经发生”的经验。
3. 第二轮仅对有信号的方案增加匹配预算对照：A 与“同样允许一次重规划、但不给针对性批评”比较；B 与“同 token 上限的普通历史摘要”比较。若进一步测试 C，单独报告两个计划是否不同，避免把更多调用产生的改善全归因于机制。
4. 固定模型版本、目录快照、上下文和预算；每组每快照运行 2 次，记录实际 token、调用数、延迟和失败原因。为比较选择质量，保留修订前后的 ID 与证据摘要，不记录或要求私密思维链。

### 6.2 评什么、怎样避免评价泄漏

| 评价层 | 建议指标 | 解释边界 |
|---|---|---|
| 结构与权限 | ID 合法率；每份最终计划≤3；最终 Observation 是否与最终计划精确对应；Actor 引用 ID 是否属于该 Observation；跨流派/阶段与隐私越界次数 | 是可程序检查的不变量，不是咨询质量 |
| 元技能选择 | 两名具备相关训练的评审者盲评“目标匹配、适用前提、时机、冲突/冗余、是否应暂不调用技能”；允许多个合理答案 | 不把某个唯一 ID 集合作为当然金标准 |
| 微技能实施 | 选出的具体微技能与台词是否一致；是否误将支持性回应包装为某个未实际使用的技能 | 与元技能选择分别评分，避免把润色收益当成选技收益 |
| 反馈记忆 | 反馈是否有前文证据；下一次是否仍重复已确认的问题；过期记忆是否误导；是否跨案例污染 | “换了技能”本身不等于变好 |
| 成本与稳定性 | 重试、总调用、token、延迟；复核造成的退化比例；评审分歧 | 不只报告总体平均分或优胜案例 |

评审材料随机排列，隐藏方案名称；改进阶段用的 Reviewer 与最终评价者分离。人工建立参考判断时也只看当时可见信息；测试集评分与未来来访者回复不能回流到测试决策。可报告配对偏好、逐案差异和不确定性，不以小样本追求“显著疗效”。这是实验设计建议，依据两个原项目的任务边界：AutoCBT 评价问答回复，Reflexion 评价任务完成。[AutoCBT 实验][a-experiment]、[Reflexion 实验][r-experiment]

### 6.3 小型连续回放与停止条件

若固定快照实验通过，再用约 6 个脱敏或合成的连续案例，各观察 3–5 个后续决策，专门检查 B 的记忆是否帮助避免重复已证实的问题。若新回复导致对话分叉，不能硬接原日志中的下一句当作真实反应；只做开放环选择审查，或明确标注使用模拟来访者的闭环试验。模拟结果仍不构成咨询疗效证据。

先要求结构约束和信息边界零违规；任何高风险分支绕过、跨案例记忆泄漏或明显由复核引起的安全退化，都应暂停对应方案。只有在盲评选择适用性出现稳定正向信号、退化案例可解释、成本可接受时，才讨论后续原型。A/B 未分别建立收益前，不急于叠加 A+B+C。

## 7. 调查结论与未验证项

- **可直接借鉴的工程模式：**草稿/计划与批评意见一起输入下一步；反馈有明确接收位置，不只是旁路打分。[AutoCBT 生成入口][a-agent]
- **可直接借鉴的工程模式：**按任务隔离经验，限制注入数量，把失败反馈写成下次可执行的计划。[Reflexion 反思][r-reflect]、[上下文注入][r-history]
- **需要本地验证的扩展：**技能选择复核、连续咨询反馈记忆、平行计划比较均不由这些论文直接证明；目前也没有证据表明需要替换现有无排序、精确展开机制。

本次完成论文与代码静态核查及方案笔记；未进行依赖安装、API 调用、外部项目运行或本地咨询实验。仅文档新增，不涉及代码/资源变化，未运行生产测试。现有其他变更不在本次修改范围。

<!-- 下列引用均解析为原论文、作者官方仓库或本地直接证据。 -->

[local-planner]: D:/0test/psych_sandbox/prompts/counselor/planner_system.jinja2
[local-catalog]: D:/0test/psych_sandbox/src/psychsandbox/skills/catalog.py
[local-actor]: D:/0test/psych_sandbox/prompts/counselor/actor_system.jinja2
[local-counselor]: D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py
[local-guidance]: D:/0test/psych_sandbox/AGENTS.md
[a-abs]: https://arxiv.org/abs/2501.09426v1
[a-method]: https://arxiv.org/html/2501.09426v1#S3
[a-experiment]: https://arxiv.org/html/2501.09426v1#S4
[a-discussion]: https://arxiv.org/html/2501.09426v1#S4.SS3.SSS2
[a-commit]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/commit/db123ee7caca099ae51aaac0e6e2e71495431ed2
[a-placeholder]: https://github.com/CAS-SIAT-XinHai/AutoCBT/tree/5abacef26825e4bd54cb5447468fb3d9bd81c15d
[a-agent]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/agents/autocbt.py#L25
[a-topology]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/topology/autocbt.py#L14
[a-env]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/backend/src/xinhai/arena/environments/autocbt.py#L16
[a-config]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/configs/xinhai_cbt_zh.yaml#L50
[a-readme]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/examples/AutoCBT/README.md
[a-license]: https://github.com/CAS-SIAT-XinHai/XinHaiAgents/blob/db123ee7caca099ae51aaac0e6e2e71495431ed2/LICENSE
[r-abs]: https://arxiv.org/abs/2303.11366v4
[r-method]: https://arxiv.org/html/2303.11366v4#S3
[r-experiment]: https://arxiv.org/html/2303.11366v4#S4
[r-commit]: https://github.com/noahshinn/reflexion/commit/218cf0ef1df84b05ce379dd4a8e47f17766733a0
[r-readme]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/README.md
[r-license]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/LICENSE
[r-main]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/main.py#L25
[r-reflect]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/generate_reflections.py#L10
[r-trial]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/alfworld_trial.py#L41
[r-history]: https://github.com/noahshinn/reflexion/blob/218cf0ef1df84b05ce379dd4a8e47f17766733a0/alfworld_runs/env_history.py#L38
