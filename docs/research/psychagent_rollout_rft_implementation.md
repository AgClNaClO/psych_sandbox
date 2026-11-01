# PsychAgent公开会谈RFT实现核查

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

来源公开代码是每session best-of-8：当前赢家推进摘要、画像和下一计划，再生成下一场8个候选；不是8条完整疗程或长期beam。典型YAML为case并发4、候选生成并发8、指标并发8、reward请求并发64；候选评分在单case内串行，指标内部仍可能多请求。咨询师0.9、来访者0.7，本地seed7未传API seed。

## 当前实现

沙盒默认3候选，生成/评分并发跟随候选数，独立复制会前状态，只提交赢家。统一生成温度0.9/0.7；评估0为本项目选择。来源默认指标首次调用若未传response_format就未显式传温度，只有格式约束/修复时设0，不能声称上游所有评分均固定0。

## 未实施建议与验证边界

公开src/rft不包含从训练数据到checkpoint的完整权重更新。若研究训练粒度或跨会谈回报，要另行实施；现行 [RFT约定](../SESSION_RFT.md) 是运行依据，下方参数表均标记为历史对照。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 层次 | 实际方法/机制 | 默认及作用域 |
|---|---|---|
| case / 疗程 | PsychAgentRunner.run_cases：Semaphore + asyncio.gather | runtime.concurrency=4；一个槽位包住整个 case，包括多会谈、评分与保存 |
| 同一 case 的 session | RFTPsychAgentRunner._run_case：普通 for + await | 串行；没有 session semaphore 或跨 session 并行 |
| 同一 session 的候选对话 | _run_rollout_dialogues：create_task + 独立 Semaphore + as_completed | rollout_n=8，rollout_concurrency=8；每个当前 session 各建一个 semaphore |
| 同一 session 的候选评分 | _run_single_session_rft：for rollout + await evaluate_dialogue | 串行，且所有对话先生成完才开始评分 |
| 单条候选的指标方法 | RewardEvaluator.evaluate_dialogue：create_task + 局部 Semaphore + as_completed | reward_method_concurrency=8；每次 evaluate_dialogue 各建一个 semaphore |
| 单指标内部的子维度 | 例如 Custom_Dim、CTRS 内部 asyncio.gather | Custom_Dim 4 路、CTRS 6 路；一个指标槽位不等于一个 API 请求 |
| reward API 请求 | 共用 GPT5ChatClient._sem，包住每次实际请求 | reward_api_concurrency=64；跨所有 case/候选/方法共享；RPS=null |

| 对象 | 实际处理 | 判断 |
|---|---|---|
| candidate_skills | 每条 rollout 调用前 copy.deepcopy | 分支内补 embedding 等操作不改兄弟分支技能对象 |
| transcript、counselor_messages、each_turn_system、client_transcript | 每次 _run_dialogue_rollout 新建列表 | 分支对话独立累积，不共享同一聊天历史列表 |
| history_list、obtain_client_info、session_focus、homework_assigned | 作为同一引用传给各分支；stage 是同一字符串值 | 当前方法体以读取/渲染为主；不是深复制隔离 |
| case、prompt manager、SkillManager、后端 client | runner 内共享 | 共享服务对象不等于共享分支对话；也不构成独立进程隔离 |
| PublicMemory | 每条分支新建对象、recaps 列表及 homework 列表 | 部分嵌套字典/列表仍引用原会前内容，不能宣称完全 deep copy |
| next_history、profile_snapshot | list(history_list)、dict(obtain_client_info) | 浅拷贝；只有赢家产生的新摘要被追加 |

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

| 范围/疗法 | 指标 |
|---|---|
| 通用六项 | PANAS、RRO、SRS、Custom_Dim、HTAIS、WAI |
| BT 另加 | MITI、STAI |
| CBT 另加 | CTRS、BDI_II |
| PMT 另加 | EFT_TFS、SFBT |
| HET 另加 | TES、CCT |
| PDT 另加 | PSC、IPO |

| 配置 | 官方固定提交中的实际行为 | 当前 psych_sandbox |
|---|---|---|
| `temperature: 0.9` | baseline 温度传入咨询师 API；来访者有单独温度，样例为 0.7 | 咨询师 0.4，来访者 0.8、来访者 Planner 0.1、supervisor 0.1 |
| `memory_mode: public_recap` | schema 接受并传递字段，但 runner 没有按字段分支；固定 `_build_public_memory` 构建已知特征、历次摘要、上次作业 | 无这个切换项；采用固定的已披露信息、受限近期记录、跨会谈摘要管线 |
| `max_sessions: 20` | baseline 上限控制外层会谈循环，runtime 同名项可覆盖；终止阶段可提前结束 | `run_case(session_count=...)` / CLI `--sessions`，默认 3 |
| `max_counselor_turns: 45` | 虽加载并允许 runtime 覆盖，但实际对话循环读 `runtime.psychagent_max_turns`，包含咨询师开场白 | `max_turns_per_session` / `--max-turns`，默认 8，允许 1..50 |
| `end_token: "</end>"` | runner 检查文本标记并移除；不是 API 请求中的 `stop` 参数 | 无字符串哨兵；结构化 `decision.end_session` 和安全/轮数规则 |
| `timeout_sec: 120` | 一次后端尝试的等待时间；不是整个会谈或所有重试的总时限 | `MODEL_TIMEOUT_SECONDS`，源码默认 90，本机 `.env` 为 90，示例文件为 180 |
| `max_retries: 16` | 后端 RetryPolicy 解释为额外 16 次，即至多 17 次尝试；SDK 自带重试关闭。runner 另有 `psychagent_max_retries`，层次不同 | Tenacity 默认 3 次尝试，可用 `MODEL_MAX_ATTEMPTS` 调高（预算耗尽写 `api_error` 诊断）；本地 OpenAI SDK 默认另有 2 次额外重试；JSON 修复最多两次生成，选技纠错最多额外一次，预算互不等价 |
| `retry_sleep_sec: 1.0` | 后端指数退避基数 1 秒，上限 2 秒，再加 0..0.2 秒抖动；不代表每次固定 1 秒 | Tenacity 指数退避 min=1/max=8（退避参数固定，未开放同名配置） |

## 原记录来源链接

- [来源 1](https://arxiv.org/abs/2604.00931v3)
- [来源 2](https://arxiv.org/html/2604.00931v3#S3.SS3)
- [来源 3](https://arxiv.org/html/2604.00931v3#S4.SS1)
- [来源 4](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Semaphore)
- [来源 5](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)
- [来源 6](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/README.md#L259-L264)
- [来源 7](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/baselines/psychagent_sglang_local.yaml#L1-L15)
- [来源 8](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/datasets/profiles_rft.yaml#L1-L11)
- [来源 9](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/datasets/psycheval_bt_cbt_het_pdt_pmt.yaml#L1-L11)
- [来源 10](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/runtime/psychagent_sglang_local.yaml#L1-L40)
- [来源 11](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/configs/runtime/rft_default.yaml#L1-L22)
- [来源 12](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/base.py#L45-L83)
- [来源 13](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/chat_client.py#L49-L84)
- [来源 14](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/core/chat_client.py#L82-L151)
- [来源 15](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/io/input_adapter.py#L64-L100)
- [来源 16](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/manager/evaluation_orchestrator.py#L141-L192)
- [来源 17](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/counselor/ctrs.py#L41-L87)
- [来源 18](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/counselor/custom_dim.py#L69-L118)
- [来源 19](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/methods/rro.py#L69-L106)
- [来源 20](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L14-L20)
- [来源 21](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L196-L221)
- [来源 22](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/eval/reward.py#L74-L147)
- [来源 23](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/core/schemas.py#L19-L59)
- [来源 24](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/main.py#L27-L82)
- [来源 25](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/main.py#L93-L145)
- [来源 26](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/reward.py#L15-L40)
- [来源 27](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/reward.py#L73-L192)
- [来源 28](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L117-L122)
- [来源 29](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L124-L167)
- [来源 30](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L169-L194)
- [来源 31](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L191-L236)
- [来源 32](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L238-L281)
- [来源 33](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L283-L320)
- [来源 34](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L335-L359)
- [来源 35](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py#L52-L115)
- [来源 36](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/backends/openai_api.py#L66-L112)
- [来源 37](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/client/simulator.py#L28-L76)
- [来源 38](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/prompt_manager.py#L111-L168)
- [来源 39](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/retry.py#L20-L70)
- [来源 40](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/core/schemas.py#L33-L143)
- [来源 41](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/io/dataset_loader.py#L61-L154)
- [来源 42](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/main.py#L167-L196)
- [来源 43](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L306-L415)
- [来源 44](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L55-L82)
- [来源 45](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L623-L678)
- [来源 46](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L680-L709)
- [来源 47](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/runner.py#L84-L135)
- [来源 48](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L127-L170)
- [来源 49](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L172-L231)
- [来源 50](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L233-L297)
- [来源 51](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L299-L344)
- [来源 52](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L403-L468)
- [来源 53](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/sample/skill_manager.py#L545-L566)
- [来源 54](https://github.com/ECNU-ICALK/PsychAgent/commit/469f45ef468b968b3fccd1936d7e6a0a574e4c5c)
