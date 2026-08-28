# PsychAgent 官方 rollout / RFT 实现核查

> 后续实现更新：沙盒已新增可选整场会谈 RFT 采样/评分/选优，并修复 CLI 的 YAML 加载。
> 本文的“当前项目”对比描述的是实现前状态；现行行为以 [会谈 RFT](../docs/SESSION_RFT.md) 为准。

## 0. 版本、范围与证据

- 核查日期：2026-08-28（Asia/Shanghai）。
- 官方仓库：ECNU-ICALK/PsychAgent；固定提交 **469f45ef468b968b3fccd1936d7e6a0a574e4c5c**，提交时间 2026-04-06 01:59:54 +08:00，信息为 Update project state。[固定提交][commit]
- 本次论文依据为 **arXiv:2604.00931v3，2026-04-28**。v1 为 2026-04-01，v2 为 2026-04-02；代码提交早于 v3，不能假定二者完全同步。[论文版本页][paper-abs]
- 已读实际方法体，覆盖 src/rft、其继承的 src/sample 调用链、src/eval/reward.py、评分方法和 API wrapper。README 只用于辅助确认公开范围。
- 未读取或修改本地 Psych-new；未做模型/embedding API 调用，未读取环境变量或密钥，未执行仓库启动器，未加载技能 .pt 文件；不展示任何模型隐藏思维链内容。没有介入本地 client/dialogue 模板或 audit UI。
- 研究源码目录：D:/0test/psych_sandbox/runs/runtime/20260828T103904__psychagent-research__f74c/official。
- 该运行目录还保存 paper_2604.00931v3.html、paper_2604.00931v3_abs.html、github_commit_469f45e.json、python_asyncio_task.html、python_asyncio_sync.html。
- 下载的论文 HTML SHA-256：51ad94f07e36f874f817d239b8d3a696cd795cf3b234592cff83d58bd1634a2a。
- 本笔记中的 GitHub 代码链接全部固定上述完整提交。下文“推论”表示由已读代码推导，未声称做过真实服务运行。

## 1. 可直接采用的结论

**公开实现是“每个 session 的 best-of-8，选一个赢家推进疗程”**，不是并行生成 8 条完整疗程后选一条，也不是维持 8 条长期分支的 beam search。每次仅由当前赢家生成摘要、画像及下一会谈计划，然后为下一 session 重新生成 8 个候选。选择只看当前候选的即时组合 reward；来访者部分包含与上一赢家的分数差，并没有计算未来疗程累计回报。[会谈循环][rft-course]、[选择与状态更新][rft-select]

默认配置为 **4 个 case 并发，每个 case 当前 session 最多 8 条 rollout 并发；每条候选评分内最多 8 个指标方法并发；全 runner 共用的 reward API client 最多 64 个请求并发，默认不设 RPS 限流**。候选评分本身在同一 session 内是逐条 await，不是 8 条一起评分。[案例调度][case-schedule]、[rollout 调度][rollout-schedule]、[评分调用][rft-eval]、[评分方法调度][eval-methods]、[请求上限][eval-client]

**多样性主要来自远端模型采样及分支自身的对话反馈。** Python random_seed=7 没有传入聊天 API seed；默认咨询师及技能查询改写温度 0.9，来访者温度 0.7。所有同一 session 的候选共享相同会前状态、模板和粗筛技能池，并没有按 rollout_index 更换人格、画像、系统模板、温度或随机种子。[配置][cfg-runtime]、[咨询师配置][cfg-baseline]、[实际请求参数][sample-api]、[技能检索][skill-retrieve]

**论文 RFT 包含对选中轨迹做参数微调；公开 src/rft 只实现生成、评分、选优与保存。** 没有在该调用链中实现权重更新、RL optimizer 或训练数据到 checkpoint 的完整流程。[论文 §3.3][paper-rft]、[RFT 入口][rft-entry]、[输出与状态][rft-output]、[公开范围说明][release-scope]

## 2. 实际代码算法与 session 依赖

入口 src/rft/main.py:run_from_args 读取 baseline、runtime、dataset 和 rft-config，应用 CLI 覆盖，加载 case，然后调用 RFTPsychAgentRunner.run_cases；后者继承自 PsychAgentRunner。[入口][rft-entry]

按方法体等价整理的流程如下（解释性伪代码，不是新增实现）：

    启动：加载共享技能库；创建共享咨询师、来访者后端
    并发处理 cases，整个 case 生命周期持有一个 case semaphore 槽位
      新 case：history=[]，已获画像={}，默认初始目标与阶段
      或从已存 session 记录恢复历史、画像、计划和上一赢家分数
      顺序处理 session t
        当前目标与阶段 -> 一次粗筛 -> 本 session 共享候选技能池
        创建 N 个任务；每个任务持有 rollout semaphore 直至完整对话结束
          新建本分支 transcript/messages/client_transcript
          深拷贝候选技能池
          检索技能 -> 咨询师开场
          循环：来访者回应 -> 技能检索 -> 咨询师回应
        等所有候选生成完，按 rollout_index 排序
        依次对每个候选评分（单次评分内的指标方法并发）
        取 final_score 最大者
        只对赢家生成摘要/下一会谈计划，然后生成更新画像
        保存赢家及候选评分；更新 history/profile/focus/stage/homework/pre_rewards
        进入 session t+1，或遇到 Termination/上限结束

证据：[初始与恢复状态][init-state]、[粗筛和生成入口][rft-build]、[逐轮对话][dialogue]、[评分和选优][rft-eval]、[赢家摘要与画像][rft-select]。

关键依赖：

- 同一 session 内各分支的双方对话是顺序依赖，后续来访者回应依赖该分支刚生成的咨询师回应，咨询师后续回应依赖该分支最新来访者回应。不能并行生成同一分支的所有轮次。[逐轮对话][dialogue]
- session t+1 必须等待 t 的所有候选完成、评分选优、赢家摘要及画像生成后才能开始。跨 session 保留的是赢家的结构化摘要和画像等，并非把所有赢家的完整逐字对话直接串接。[会谈循环][rft-course]、[历史更新][rft-select]
- 正常走满 T 个 session，生成约 N×T 个 session 候选，并非 N 的 T 次方条疗程分支；下一轮并不按旧 rollout_index 续接“同编号分支”。这是由每轮重新创建候选和只保留一份 next_state 得出的推论。[rollout 调度][rollout-schedule]、[状态推进][rft-output]
- 达到 max_sessions 不等于治疗目标完成：未到 Termination 时记录 finished=false、max_sessions_reached。默认最多 20 个 session；实际对话循环采用 psychagent_max_turns=45，而不是直接读取 max_counselor_turns。开场计入咨询师轮数。[会谈循环][rft-course]、[对话循环][dialogue]、[runtime 配置][cfg-runtime]

## 3. 并发层、Semaphore 与 gather 的准确含义

| 层次 | 实际方法/机制 | 默认及作用域 |
|---|---|---|
| case / 疗程 | PsychAgentRunner.run_cases：Semaphore + asyncio.gather | runtime.concurrency=4；一个槽位包住整个 case，包括多会谈、评分与保存 |
| 同一 case 的 session | RFTPsychAgentRunner._run_case：普通 for + await | 串行；没有 session semaphore 或跨 session 并行 |
| 同一 session 的候选对话 | _run_rollout_dialogues：create_task + 独立 Semaphore + as_completed | rollout_n=8，rollout_concurrency=8；每个当前 session 各建一个 semaphore |
| 同一 session 的候选评分 | _run_single_session_rft：for rollout + await evaluate_dialogue | 串行，且所有对话先生成完才开始评分 |
| 单条候选的指标方法 | RewardEvaluator.evaluate_dialogue：create_task + 局部 Semaphore + as_completed | reward_method_concurrency=8；每次 evaluate_dialogue 各建一个 semaphore |
| 单指标内部的子维度 | 例如 Custom_Dim、CTRS 内部 asyncio.gather | Custom_Dim 4 路、CTRS 6 路；一个指标槽位不等于一个 API 请求 |
| reward API 请求 | 共用 GPT5ChatClient._sem，包住每次实际请求 | reward_api_concurrency=64；跨所有 case/候选/方法共享；RPS=null |

源码：[case][case-schedule]、[rollout][rollout-schedule]、[串行候选评分][rft-eval]、[指标方法][eval-methods]、[Custom_Dim][custom-dim]、[CTRS][ctrs]、[API client][eval-client]、[RFT 默认][cfg-rft]。

**正常执行时的数量推论：** 至少有 4 个可运行 case 且都处于生成阶段时，活跃对话分支上界为 4×min(8,8)=32。不是“整个程序只有 8 个并发”，也不是“64 个生成分支”。64 只限制 reward client 请求；咨询师、来访者和 embedding 客户端没有共用这个 semaphore。具体每秒吞吐取决于服务端及请求时延，代码不足以保证。[后端共享][runner-init]、[聊天后端][sample-api]、[embedding 请求][embedding]

Semaphore 是异步计数门：全部任务可以先创建，但只有取得槽位的任务进入受保护区；await 网络响应会让事件循环调度其他任务，却不会自动归还当前 semaphore 槽位。这里的并发主要是异步 I/O，不等于为每个 rollout 启一个 OS 进程或训练 worker。[Python Semaphore][py-sem]

注意不要笼统说“rollout 用 gather”：

- 最外层 case 使用 gather；rollout 层与指标方法层实际使用 create_task/as_completed。候选按完成顺序收集，之后显式按 index 排序。
- gather 并不自身限流；必须看外围 semaphore。指标内部的 gather 又会扩展 API 请求数。
- 普通 gather 默认发生异常时会向等待者传播异常，并不自动取消其他 awaitable；rollout 的 as_completed 循环也没有失败后取消并等待剩余任务的 finally 逻辑。候选抛出异常后，case 级处理会记录失败，但兄弟 rollout 可能继续运行。因此“32”是正常路径的结构上界，不能当作异常情况下的严格全局请求保护；代码没有“失败分支自动丢弃，余下分支照常选优”的策略。[case 异常处理][case-schedule]、[rollout 无清理逻辑][rollout-schedule]、[Python gather/as_completed][py-tasks]
- 指标异常处理不同：单方法异常被捕获并返回 failed，其他指标继续，最终仅聚合成功分数。[指标异常处理][eval-methods]

## 4. 状态拷贝与隔离：不是“所有状态深拷贝”

| 对象 | 实际处理 | 判断 |
|---|---|---|
| candidate_skills | 每条 rollout 调用前 copy.deepcopy | 分支内补 embedding 等操作不改兄弟分支技能对象 |
| transcript、counselor_messages、each_turn_system、client_transcript | 每次 _run_dialogue_rollout 新建列表 | 分支对话独立累积，不共享同一聊天历史列表 |
| history_list、obtain_client_info、session_focus、homework_assigned | 作为同一引用传给各分支；stage 是同一字符串值 | 当前方法体以读取/渲染为主；不是深复制隔离 |
| case、prompt manager、SkillManager、后端 client | runner 内共享 | 共享服务对象不等于共享分支对话；也不构成独立进程隔离 |
| PublicMemory | 每条分支新建对象、recaps 列表及 homework 列表 | 部分嵌套字典/列表仍引用原会前内容，不能宣称完全 deep copy |
| next_history、profile_snapshot | list(history_list)、dict(obtain_client_info) | 浅拷贝；只有赢家产生的新摘要被追加 |

证据：[rollout 入参及 deep copy][rollout-schedule]、[局部对话容器][dialogue]、[公共记忆构造][public-memory]、[共享服务][runner-init]、[赢家状态][rft-output]。

从正常调用链看，分支运行期间没有将失败候选的对话写入其他分支的历史；跨 session 更新发生在选优之后。这个结论建立在这些共享输入保持只读的现有方法体上，不应描述成语言层面强制不可变或所有状态深拷贝。

技能库在 case 调度之前加载，可能补齐并保存已有技能的 embedding；这属于资源初始化，不是“看了某个赢家后提取新技能并更新所有后续 case”的完整技能演化。当前 RFT 会谈循环没有调用这种演化流程。[技能库初始化][skill-load]、[RFT 会谈循环][rft-course]

## 5. 同一 case / session 的轨迹究竟为何不同

| 项目 | 分支起点相同还是不同 | 实际变化来源 |
|---|---|---|
| 人物画像与疗法 | 相同 case、modality、intake/theory profile | 不为每条候选另采一个人物 |
| 咨询师会前记忆与目标 | 相同 history、已获画像、stage、focus、homework | 下一 session 才根据当前赢家统一更新 |
| 模板与开场指令 | 同一 modality 模板，同一 session_index | 没有 rollout_index 特定模板或提示扰动 |
| 粗筛技能池 | 每个 session 只粗筛一次，然后每分支复制 | 不是每条候选单独随机抽粗筛池 |
| 每轮技能选择 | 分支分别进行查询改写、embedding 相似度排序、取 top_k=5 | 改写生成可随机；后续查询和历史也随本分支对话变化 |
| 咨询师回答 | 同一后端、配置、temperature=0.9 | 服务端采样及已经分化的上下文 |
| 来访者回答 | 同一人物设定、temperature=0.7 | 服务端采样及本分支咨询师回应 |
| 会后摘要/画像 | 仅为赢家生成 | 使用咨询师后端；重复运行时这部分也可能变化，但不是当轮候选间预设差异 |

证据：[同起点及粗筛][rft-build]、[分支入参][rollout-schedule]、[逐轮提示渲染][dialogue]、[client 调用][client-sim]、[画像输入构造][client-input]、[技能检索][skill-retrieve]。

技能细节：corse_filter（源码拼写如此）默认 n=20，基于当前疗法/阶段的叶级 meta skills；模型结果缺失/解析失败时用前 n 个 ID。子技能展开成共同 candidate_skills。retrive（源码拼写如此）对分支的当前话语和分支历史做查询改写，再计算 cosine similarity、降序取前 5；默认 threshold=None。这不是显式随机抽 top-k，不保证 8 个候选的技能组合互不重复。[粗筛][skill-coarse]、[检索][skill-retrieve]

llm_response 显式丢弃 model_kwgs，只向咨询师 backend 传 messages，因此技能粗筛与改写实际继承该 backend 的默认温度等参数，示例配置下为 0.9。[技能模型调用][skill-model]、[backend 参数回退][sample-api]

### RNG 与 API 采样参数

- runner 初始化执行 random.seed(runtime.random_seed)。数据加载另用 random.Random(seed)，只有 case_selection_strategy=random 时 shuffle；官方两份 RFT 示例 dataset 都是 sequential。它不是按候选编号分配的模型采样种子。[runner 初始化][runner-init]、[dataset RNG][dataset-loader]、[dataset 默认][cfg-dataset]
- 咨询师/来访者实际 chat.completions.create 只传 model、messages、temperature、max_tokens、timeout；**没有 seed、top_p、采样 top_k、n 或 logprobs**。rollout 数量来自外层任务数，不是单次 API 的 n。即使上层随意加 seed/top_p kwargs，这个 wrapper 也没有转发通路。[实际 API 方法][sample-api]
- 技能检索 top_k=5 是检索数量，不能误当模型解码 top_k。temperature 相同也不保证文本相同；未传远端 seed，所以 random_seed=7 不能保证整条疗程复现。API 是否尊重温度、未传参数的服务端默认值、批处理非确定性，均未验证。
- **没有候选间 reward 反馈回路。** 8 条对话先全部完成才评估；后生成的候选不会看到先生成候选的 reward、批评或赢家。previous_reward_snapshot 只参与打分运算，不传入 _run_dialogue_rollout。对话内部的来访者反馈会影响本分支；跨 session 的赢家摘要/画像影响下一 session，这两者与“失败分支反馈后重采样”不同。[生成与评分顺序][rft-build]、[评分参数][rft-eval]、[分支参数][rollout-schedule]

## 6. 默认配置：区分 YAML 与类默认值

| 项目 | 官方 CLI 默认加载的 YAML | 无配置时对应类默认值/补充 |
|---|---|---|
| case concurrency | 4 | RuntimeConfig.concurrency=1 |
| 候选数 | rollout_n=8 | 同为 8；源码字段不是 num_rollouts |
| rollout concurrency | 8 | 同为 8 |
| reward method concurrency | 8 | 同为 8 |
| reward API concurrency | 64 | 同为 64 |
| reward RPS | null；period=1.0 | RFT 路径明确传 None，不采用 GPT5ChatClient 裸构造时的 60 |
| random_seed | 7 | 7；无 API seed |
| 咨询师模型/温度/token 上限 | model=default；0.9；8196 | BaselineConfig 的温度=0.7、max_tokens=512，不是示例 YAML 实际值 |
| 来访者模型/温度/token 上限 | deepseek-v3-huawei-910b；0.7；512 | RuntimeConfig client 温度=0.7、max_tokens=256 |
| session/turn 上限 | max_sessions=20；psychagent_max_turns=45 | 实际循环按这两项控制 |
| 输出与恢复 | keep_all_rollout_transcripts=true；resume=true；overwrite=false | 默认保留所有候选 transcript 及每轮 system 字段 |
| 技能检索 | coarse n=20；retrive top_k=5；threshold=None | 方法签名默认，不是 rollout 采样超参数 |

证据：[baseline YAML][cfg-baseline]、[runtime YAML][cfg-runtime]、[RFT YAML][cfg-rft]、[RFT schema][rft-schema]、[sample schema][sample-schema]、[技能方法][skill-coarse]、[检索方法][skill-retrieve]。

CLI 可分别覆盖 --concurrency、--rollout-n、--rollout-concurrency、--reward-method-concurrency。默认 dataset 为 profiles_rft.yaml（split=rft）；README 命令使用 psycheval_bt_cbt_het_pdt_pmt.yaml（实际指向 assets/profiles，split=sample）。二者皆五疗法、sequential、每疗法最多 20 case，不能凭文件名推断加载了论文全规模训练集。[CLI 默认][rft-cli]、[RFT dataset][cfg-dataset]、[README 命令 dataset][cfg-dataset-sample]

reward_api_model=null 时 RFT runner 回退到 client_model，再回退 counselor model；因此示例下通常是 deepseek-v3-huawei-910b，而非仅凭 RewardEvaluator 默认形参就断言是 Gemini。GPT5ChatClient 还允许 CHAT_MODEL_NAME 覆盖传入模型名；本次没有读取环境变量，所以实际部署模型未确认。[evaluator 构造][rft-reward-client]、[模型覆盖][eval-client-model]

**评分温度不能写成“统一为 0”。** 已核对默认涉及的 16 个具体指标实现：它们调用 chat_api 时不传 response_format。EvaluationMethod.chat_api 仅在 response_format 非 None 时为首次请求设置 temperature=0；默认首次请求不会显式传 temperature，取服务端默认值。JSON 修复重试显式设 temperature=0、json_object。评估调用链也未设置 seed。[公共评分调用层][eval-base]、[默认方法示例 RRO][rro]、[Custom_Dim][custom-dim]

## 7. reward、过滤和赢家选择

### 7.1 评估对象与历史来源

每条候选调用 evaluate_dialogue(modality, dialogue=该候选完整 transcript, profile=会前 obtain_client_info)。评估发生在赢家摘要/画像更新之前；不是给每个候选先构建独立更新画像再评分，也不直接传完整历史疗程列表。[调用位置][rft-eval]

fresh case 的 obtain_client_info={}，与模拟来访者持有的完整 intake/theory profile 不同。后续会前画像来自前次赢家提取结果。前次赢家分数以 pre_rewards 进入 reward 运算，所有当前候选使用同一个基线。[初始状态][init-state]、[前次 reward 恢复][rft-pre-reward]、[状态保存][rft-output]

formatter 跳过 system 并去掉结束标记，但并未统一抽取“仅对外答复”；runner 同时维护内部原始 transcript 与供后续对话使用的答复文本。因此不能假定评分输入与用户界面显示文本完全相同。本笔记仅指出结构差异，不展示或转述任何隐藏推理内容。[对话容器][dialogue]、[reward formatter][eval-format]

### 7.2 默认指标与精确聚合

每个疗法默认八个方法：

| 范围/疗法 | 指标 |
|---|---|
| 通用六项 | PANAS、RRO、SRS、Custom_Dim、HTAIS、WAI |
| BT 另加 | MITI、STAI |
| CBT 另加 | CTRS、BDI_II |
| PMT 另加 | EFT_TFS、SFBT |
| HET 另加 | TES、CCT |
| PDT 另加 | PSC、IPO |

配置与实现一致。[RFT 方法配置][cfg-rft]、[RewardEvaluator 默认][eval-defaults]

RRO 返回 counselor 和 client 两个侧面；在全部成功且均有前值时，默认组合为 5 个 counselor 信号、4 个 client 信号，并非八项各一个单分数。Dialogue_Planning 虽在论文总体评估指标中出现，却未列入公开 RFT 默认八方法清单；也不在默认标准化统计表中，不能认为其自动参与选优。[RRO 输出][rro]、[评分统计表][reward-stats]、[默认方法][cfg-rft]

compute_rollout_reward 的计算为：

    counselor 指标：z = clip((当前值 - 固定均值) / 固定标准差, -3, 3)
    client 指标：delta = 当前值 - 上一赢家同指标值
                z = clip((delta - 固定均值) / 固定标准差, -3, 3)
                SCL_90、BDI_II、IPO 的 z 再取负
    final_score = 所有可用 z 的算术平均；没有可用信号则为 0.0

均值/标准差是 reward.py 中硬编码常量，不是对当前 8 条 rollout 临时归一化；counselor 用绝对分，client 用跨 session 差值；不是两侧各算平均再 50:50 混合。[常量][reward-stats]、[聚合方法][reward-compute]

- 首次 session 的上一分数为空：client 项仍评估并存快照，但全部以 missing_previous_reward 跳过选优计算，所以第一轮正常只比较 counselor 五项。
- 缺少标准化统计的项被跳过；失败指标没有数值也不进入均值。不存在“所有方法成功”“达到最低分”“安全指标全部通过”才可入选的硬门槛。
- 所有指标失败时 final_score=0.0，仍可能被 max 选中；成功候选可以是负分，所以全失败的 0 不一定垫底。这是代码的边界行为，不是建议。
- max 按 final_score 选一个候选；候选已按 rollout_index 排序，因此相同分数时选最小 index，不是最先完成者。没有显式去重、多样性约束、淘汰阈值或未来回报搜索。
- keep_all_rollout_transcripts=false 仅减少保存内容，不改变选优规则；默认为 true。

证据：[指标失败处理][eval-methods]、[reward 缺项/首轮逻辑][reward-compute]、[排序][rollout-schedule]、[max 及保存][rft-select]、[候选输出][rft-output]。

### 7.3 teacher forcing 与 chosen session history

**该公开 RFT 生成路径不从数据集逐 session 注入参考会谈历史。** DatasetLoader 读取人物 basic_info/theory 字段，并不加载参考 session_dialogue 来逐会谈覆盖状态。新 case 从空咨询师记忆开始；下一 session 由前一个被选中的候选摘要/画像/计划递推。resume 时也是恢复本地保存 session 记录，而不是自动回到外部“标准历史”。若外部手工改动恢复文件，那已超出这条正常来源链。[dataset 读取][dataset-loader]、[初始化/恢复][init-state]、[赢家推进][rft-output]

因此，若“teacher forcing”指每个会谈都换成数据集给定的真实历史，这不是本提交 RFT 的实现。如果该术语指训练时以目标序列前缀计算监督损失，则属于论文训练部分；公开代码没有训练循环，不能据此核对 loss mask 或训练前缀的具体处理。

不要把独立 src/eval 对现有对话文件的评分误当生成 teacher forcing。它不生成候选。另一个可比性 caveat 是：sample course 的 eval adapter 会取最后一个非空画像作为整个 course 的 client_info，随后各 session 使用该画像评分；这与 RFT 内部“当前候选+会前画像”的在线评估上下文不同，离线重评分可能不完全相同。[course 适配][eval-adapter]、[独立 eval 会谈循环][eval-course]

## 8. 论文方法与发布代码：可确认和不可确认

论文 §3.3 描述从上一最优历史生成并行 session 候选、用 reward 贪心选一个、仅凭赢家更新下一状态；再以选出的轨迹做似然最大化的 Rejection Fine-Tuning（式 6）。§4.1 写 rollout N=8。论文还描述会后技能提取/合并。公开代码对应了 session 生成与选优，但不包含完整训练和技能演化闭环。[论文 §3.2–3.3][paper-rft]、[论文实现说明][paper-impl]

公开入口的生命周期是构造 runner → run_cases → close → 报告结果；RFT runner 的结果是 session/course JSON 和 reward 元数据，没有模型参数、梯度或训练 checkpoint 写出。全文检索 src 的 optimizer、backward、Trainer、deepspeed、训练调用等未发现相应实现；torch 的实际用途是技能字典 .pt 读写。该否定结论同时依赖已读调用链和仓库范围检查，不只是看目录名。[入口][rft-entry]、[输出][rft-output]、[技能保存][skill-load]、[技能读取][skill-pt]

因此准确表述应为：

> 此提交提供“用于 RFT 的 session 级 best-of-n rollout/奖励选优数据生成”，而非已经公开完整 RFT 权重训练。论文的 RFT 是选优后的监督式参数优化；不能仅因名称含 Reinforced 就把这套发布脚本说成 PPO/GRPO 或 policy-gradient 训练。

没有公开 optimizer 不等于作者没有训练模型，也不能否定另行发布的 checkpoint；只说明这份仓库无法独立审计或复现未公开的训练过程。README 对未包含完整 post-training recipe 和会后技能演化也明确说明。[公开范围][release-scope]

版本交叉检查：本次完整 clone 只有两个提交。与 638646b6f49f08c347815fe93fa6c9b80d112142 比较，src/rft、src/eval、sample/runner.py、skill_manager.py 和 backends 无差异；后续提交涉及技能路径修正、profile 数据调整和 Web 内容等。这里不推断未公开历史版本，也未将本地 Psych-new 的任何行为归于官方代码。

## 9. 已做验证与剩余缺口

本次除静态阅读外，做了**无网络、无模型的内存验证**：

1. 直接执行官方纯 reward 模块，验证首轮 client 跳过、负向 delta 取反、全缺项得 0、[-3,3] 裁剪及同分优先最小候选编号。
2. AST 检查 sample API 最终参数只有 model/messages/temperature/max_tokens/timeout。
3. AST 检查默认 16 种评分方法的 chat_api 调用没有设置 response_format、temperature 或 seed。
4. 从官方 AST 提取原样 _run_rollout_dialogues 方法，用只 sleep/返回空容器的替身替代对话函数：N=8、concurrency=3 时观察峰值 3；输出按 1..8 排序；各分支技能池深拷贝、history 仍为共同引用。此项验证的是 Python 调度/副本行为，不是实际生成吞吐或疗效。
5. clone 工作树未修改；没有执行官方 CLI，避免启动时 embedding 请求及技能库回写。

**剩余缺口（可由主任务按需本地验证，不影响上述源码结论）：**

- 未对真实后端运行 end-to-end；模型对 temperature 的支持、服务端缺省 top_p/seed、排队/限流、可复现性和实际吞吐均未知。
- 未读取运行环境变量，故实际 reward 模型是否被 CHAT_MODEL_NAME 覆盖未知。
- 论文 v3 晚于该代码提交；没有建立逐实验产物与该提交一一对应的证据，也未确认仓库内 PDF 与 arXiv v3 是否逐字一致。
- 完整权重训练、训练数据导出/掩码、optimizer 和会后技能演化未公开；不补写或猜测训练配方。
- 未核对本地 Psych-new 的版本差异、client 模板、audit UI；这些由主任务负责。任何本地 teacher forcing 或额外 semaphore 行为应独立标为本地实现，不能套用为官方行为。
- 异常分支未取消、缺失指标仍选优等边界已由代码确认，但没有对真实服务器做故障注入。

## 补充：训练粒度与配置实际生效位置（2026-08-28）

### 训练粒度

论文区分多任务 SFT（记忆提取、规划、回复，以及技能提取/管理）与会谈级 RFT。
RFT 每个候选是一整个 session，评分、拒绝和选优同样以 session 为单位，只有胜出会谈推进历史。
参数目标是胜出会谈在已选历史条件下的最大似然；低分候选被排除，不等于显式 DPO 偏好损失。
公开说明给出上下文 32768、每设备 batch 1、history masking，但不足以确认训练数据如何切片、
哪些角色/字段计算 token loss，不能声称一条训练样本就是整段多会谈疗程。
依据：[论文方法][paper-rft]、[实现说明][paper-impl]。

公开仓库的 `src/rft` 主要实现采样、评分、选优、存档；并未公开 optimizer、collator、loss mask
或权重更新训练器。[发布范围][release-scope]

当前沙盒 `src/psychsandbox/training/export.py` 中，`export_sft` 每行只包含咨询师回复和紧邻的前一条
消息；没有完整历史、规划、技能输入。`export_dpo_pairs` 要求调用者提供轨迹对，用轨迹级 reward
比较后只导出两条末次咨询师回复，也未包含 prompt。两者是导出辅助函数，不是会谈级 RFT 训练闭环。
依据：[当前导出代码](../src/psychsandbox/training/export.py)。

### 配置声明不等于有效控制

| 配置 | 官方固定提交中的实际行为 | 当前 psych_sandbox |
|---|---|---|
| `temperature: 0.9` | baseline 温度传入咨询师 API；来访者有单独温度，样例为 0.7 | 咨询师 0.4，来访者 0.8、来访者 Planner 0.1、supervisor 0.1 |
| `memory_mode: public_recap` | schema 接受并传递字段，但 runner 没有按字段分支；固定 `_build_public_memory` 构建已知特征、历次摘要、上次作业 | 无这个切换项；采用固定的已披露信息、受限近期记录、跨会谈摘要管线 |
| `max_sessions: 20` | baseline 上限控制外层会谈循环，runtime 同名项可覆盖；终止阶段可提前结束 | `run_case(session_count=...)` / CLI `--sessions`，默认 3 |
| `max_counselor_turns: 45` | 虽加载并允许 runtime 覆盖，但实际对话循环读 `runtime.psychagent_max_turns`，包含咨询师开场白 | `max_turns_per_session` / `--max-turns`，默认 8，允许 1..50 |
| `end_token: "</end>"` | runner 检查文本标记并移除；不是 API 请求中的 `stop` 参数 | 无字符串哨兵；结构化 `decision.end_session` 和安全/轮数规则 |
| `timeout_sec: 120` | 一次后端尝试的等待时间；不是整个会谈或所有重试的总时限 | `MODEL_TIMEOUT_SECONDS`，源码默认 90，本机 `.env` 为 90，示例文件为 180 |
| `max_retries: 16` | 后端 RetryPolicy 解释为额外 16 次，即至多 17 次尝试；SDK 自带重试关闭。runner 另有 `psychagent_max_retries`，层次不同 | Tenacity 至多 3 次尝试；本地 OpenAI SDK 默认另有 2 次额外重试；JSON 修复最多两次生成，选技纠错最多额外一次，预算互不等价 |
| `retry_sleep_sec: 1.0` | 后端指数退避基数 1 秒，上限 2 秒，再加 0..0.2 秒抖动；不代表每次固定 1 秒 | Tenacity 指数退避 min=1/max=8，未开放同名配置 |

官方依据：[baseline 配置][cfg-baseline]、[对话循环][dialogue]、[公共记忆构造][public-memory]、
[后端 API][sample-api]、[重试实现][retry-policy]、[配置覆盖][baseline-overrides]。
`memory_mode` 结论来自固定提交 `src/` 全文引用检查，不能推断其他历史版本也无实现。

当前依据：[SandboxConfig](../src/psychsandbox/domain/models.py)、[CLI](../src/psychsandbox/cli.py)、
[配置加载](../src/psychsandbox/config.py)、[API gateway](../src/psychsandbox/model_client.py)、
[咨询师上下文](../src/psychsandbox/agents/counselor.py)、[编排器](../src/psychsandbox/runtime/orchestrator.py)。
超时环境文件只读取了数字型 `MODEL_TIMEOUT_SECONDS`，没有导出任何凭据；环境变量仍可覆盖 `.env`。

**当前 CLI 加载缺口：** `cli._config` 没有调用 `default_config`，只从命令行设置 root、seed、max-turns。
`default_config` 才会读取 `configs/runtime.yaml`；它本身也不读取 `session_count`。
因此 YAML 中温度/向量阈值的值虽然与当前类默认值恰好一致，直接改 YAML 不会影响 CLI；
会谈数必须通过 `--sessions` 或 Python 参数设置。本次仅记录此差异，未修改配置加载或训练流程。

## 固定来源索引

[commit]: https://github.com/ECNU-ICALK/PsychAgent/commit/469f45ef468b968b3fccd1936d7e6a0a574e4c5c
[paper-abs]: https://arxiv.org/abs/2604.00931v3
[paper-rft]: https://arxiv.org/html/2604.00931v3#S3.SS3
[paper-impl]: https://arxiv.org/html/2604.00931v3#S4.SS1
[py-sem]: https://docs.python.org/3/library/asyncio-sync.html#asyncio.Semaphore
[py-tasks]: https://docs.python.org/3/library/asyncio-task.html#asyncio.gather
[rft-cli]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/main.py#L27-L82
[rft-entry]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/main.py#L93-L145
[rft-course]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L52-L115
[rft-pre-reward]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L117-L122
[rft-build]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L124-L167
[rft-eval]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L169-L194
[rft-select]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L191-L236
[rft-output]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L238-L281
[rollout-schedule]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L283-L320
[rft-reward-client]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L335-L359
[case-schedule]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L84-L135
[runner-init]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L55-L82
[dialogue]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L306-L415
[init-state]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L623-L678
[public-memory]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L680-L709
[sample-api]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/backends/openai_api.py#L66-L112
[client-sim]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/client/simulator.py#L28-L76
[client-input]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/prompt_manager.py#L111-L168
[dataset-loader]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/io/dataset_loader.py#L61-L154
[skill-load]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L127-L170
[skill-coarse]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L172-L231
[skill-retrieve]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L233-L297
[skill-model]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L299-L344
[embedding]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L403-L468
[skill-pt]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L545-L566
[cfg-baseline]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/baselines/psychagent_sglang_local.yaml#L1-L15
[cfg-runtime]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/runtime/psychagent_sglang_local.yaml#L1-L40
[cfg-rft]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/runtime/rft_default.yaml#L1-L22
[cfg-dataset]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/datasets/profiles_rft.yaml#L1-L11
[cfg-dataset-sample]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/datasets/psycheval_bt_cbt_het_pdt_pmt.yaml#L1-L11
[rft-schema]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/core/schemas.py#L19-L59
[sample-schema]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/schemas.py#L33-L143
[eval-defaults]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L14-L20
[eval-methods]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L74-L147
[eval-format]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L196-L221
[eval-client]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/chat_client.py#L82-L151
[eval-client-model]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/chat_client.py#L49-L84
[eval-base]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/base.py#L45-L83
[reward-stats]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/reward.py#L15-L40
[reward-compute]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/reward.py#L73-L192
[rro]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/rro.py#L69-L106
[custom-dim]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/counselor/custom_dim.py#L69-L118
[ctrs]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/counselor/ctrs.py#L41-L87
[eval-adapter]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/io/input_adapter.py#L64-L100
[eval-course]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/manager/evaluation_orchestrator.py#L141-L192
[release-scope]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/README.md#L259-L264
[retry-policy]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/retry.py#L20-L70
[baseline-overrides]: https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/main.py#L167-L196
