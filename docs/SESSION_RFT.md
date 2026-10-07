# 整场会谈候选、评分与选优

这是研究用的可选采样模式。沿用 PsychAgent 论文的会谈级探索、会谈级评分与贪心选优逻辑，不包含训练数据打包、优化器、权重更新或自动技能演化。技能树不变。

## 开启与预算

```powershell
Set-Location -LiteralPath 'C:\Users\Rain\Desktop\psych_sandbox'
.\.venv\Scripts\python.exe -B -m psychsandbox simulate --case psycheval-cbt-001 --sessions 3 --rollouts 3
```

需要限流时再加 `--rollout-concurrency 2 --judge-concurrency 2`；默认值与候选数相同，见下节。

迁移后先完成 [可编辑安装检查](../README.md#53-迁移后的安装检查powershell)，并配置聊天 API 和 [条件 embedding 服务](SKILL_SELECTION.md)。这里的命令会消耗真实 API 额度，不是离线测试。

`configs/runtime.yaml` 的 `rft` 段是完整默认配置。CLI 读取 YAML，再应用显式参数；未显式传入的 seed、session_count、温度、技能筛选等参数也会使用 YAML。Python 直接构造 `SandboxConfig` 不读文件，需要时使用 `default_config(root)`。默认 `rft.enabled=false`，`--rollouts N`（N≥2）启用， `--rollouts 1` / `--no-rft` 关闭。没有批量病例并发命令。

默认采样 3 个候选；生成并发与评分并发默认都等于候选数（`rft.concurrency` / `rft.judge_concurrency` 为 `null` 时跟随 `candidates`），所以 3 个候选会同时生成、同时评分，不会剩下只跑 1 个候选的尾轮。只有显式传入 `--rollout-concurrency` / `--judge-concurrency`（或 YAML 中的同名项）才会限制并发上限，用于主动降低并发请求量；上限高于候选数没有额外作用。至少 2 个不同且合格候选才能选优。每个生成候选在取得并发许可后有 1800 秒总时限，每次评分 240 秒（`rft.judge_timeout_sec`，代码与 `configs/runtime.yaml` 默认值均为 240）；排队时间不计入这两个时限。生成失败（例如瞬时网络错误）默认最多补采 `resample_limit=2` 个新候选；评分失败（如瞬时评分 API 500）在合格候选不足 `min_eligible` 时也会补采。补采的新候选使用递增编号且不覆盖失败留档，与生成失败共用同一个 `resample_limit` 预算。评分器对校验失败（如非法 JSON 或量表 schema 不符）先按 `judge_retries` 重试（模型默认 1 次，`configs/runtime.yaml` 当前为 3），每次重试独立计时。网关的瞬时重试预算由 `MODEL_MAX_ATTEMPTS` 控制（默认 3 次，等于此前的 tenacity 预算；OpenAI SDK 自身另有 2 次内置重试），聊天生成、logprob 评判与技能向量 embedding 批次调用共用该预算，重试包含在上述总时限中，预算耗尽时请求元数据写入该候选的 `dNNN/api_error` 诊断记录。RFT 仅提高咨询师生成温度至 0.9，来访者使用原配置；评分模型默认温度为 0，`configs/runtime.yaml` 当前设为 0.2（非零让评分校验重试有机会得到不同输出）。会后自评仍使用正常咨询师温度。

同会谈的候选从相同案例、计划、记忆和初始状态开始，不分配不同人格或强制不同策略。独立 API 采样及后续不同的对话/技能选择产生分歧。API 请求没有远端 seed 参数；运行 seed 不保证远端可复现，温度也不保证候选一定不同。完全相同的双方对话只评分一次，暂不做语义去重。

开启后，单会谈生成成本大致随候选数增加；每个通过规则门槛的独特候选都会调用一次督导模型，逐量表运行本流派用到的 PsychEval 量表（Counselor-Level 与 Client-Level）。这组默认值是工程起点，不是经实验证明的最佳超参数。

## 执行顺序与隔离

1. 取得会前计划、已提交记忆、初始状态和上次胜出会谈的评分快照。
2. 深拷贝各候选的记忆、状态、计划和案例；各自新建 counselor/client/simulator 与技能向量缓存。
3. 在有界 asyncio 任务中运行完整会谈；每条分支内部仍依次进行技能选择、安全检查、来访者反应。
4. 保存候选和完整对话。先检查即时风险，再按 `resample_limit` 补采生成失败的候选，然后排除安全/披露不合格分支，最后去重。
5. 对其余候选逐量表评分（PsychEval 量表）；校验失败按 `judge_retries` 自动重试，再应用规则安全门控和咨询师总分门槛。
6. 从合格候选中选总分最高者；同分选编号最小者，结果不依赖完成顺序。
7. 仅胜出者进行纵向评估、咨询师会后自评、下一计划、E.7/E.8/E.9 记忆整理和正式会谈提交。

CLI 在候选生成阶段为每个候选绘制一条实时进度条（`Session N 候选 K [图形] 百分比 已用 预计剩余`），在评分阶段绘制一条汇总进度条（`Session N 评分 [图形] 百分比 量表 x/y 候选 x/y 最近 <量表> 已用 预计剩余`）。评分条按已进入评分的候选累计量表步数，补采的新候选会加进同一批次的总量，评分校验重试不会重复计数；判分器若不报告逐量表步数（自定义实现），则回退为候选级进度。`--json` 不绘制进度条，`logs/progress.log` 仍逐行记录每个候选的状态，并记录每批实际生效的候选数、生成并发与评分并发（用于事后核对 `null` 解析结果）。

评分不进入咨询师提示词或记忆；下一计划仍由胜出会谈的自评与纵向信号决定。RFT 选优分数与整段疗程结束后 `PsychEvalSupervisor` 的整体督导同用一套 PsychEval 量表，但前者是单 session 的排名信号，后者是整条轨迹的汇总，不能直接比较。技能查询的一次纠错预算仍是每轮、每个分支各自的预算，不是 RFT 的补采许可。

同一进程只允许一个 `run_case`，避免进程临时目录和环境串线；候选任务不调用 `run_case`。同一运行目录使用 OS 文件锁，阻止两个进程同时恢复该运行，退出或崩溃后系统释放锁；`.run.lock` 文件会保留，但文件存在本身不代表仍被锁定。候选共用 API 连接；诊断目录和请求元数据通过 `ContextVar` 按异步任务隔离。父任务取消或异常时会取消并等待全部子任务退出。

## 评分规则

评分器：`evaluation/rollout.py::SessionRolloutEvaluator`，复用 `evaluation/session_supervisor.py::SessionSupervisorEvaluator` 与 `evaluation/psycheval_supervisor.py` 中的 PsychEval 量表。评估输入只有本次双方完整对话与来访者背景（与整体督导一致），不注入其他候选、候选编号、模拟状态数值或此前评分。评分模型使用 `SUPERVISOR_MODEL`。

每个候选逐量表运行本流派用到的 PsychEval 量表：

| 层级 | 共享量表 | 流派专属量表 |
|---|---|---|
| Counselor-Level | WAI、HTAIS、RRO、`custom_dim` | BT→MITI；CBT→CTRS；HET→TES；PDT→PSC；PMT→EFT-TFS |
| Client-Level | SCL-90、PANAS、RRO、SRS | BT→STAI；CBT→BDI-II；HET→CCT；PDT→IPO；PMT→SFBT |

对齐 PsychEval 的细节：RRO 是单个 24 条目量表，按 4 因子（Client/Counselor × Realism/Genuineness）分解并对条目 {2,7,16,17,18,19,24} 反向计分，咨询师侧与来访者侧各取两个因子均值、共用同一次模型调用；`custom_dim` 是单个咨询师侧量表，聚合 Ethics、Interaction、Intervention、Perception 四个 criteria 为一个分数。流派专属量表也修正了多文件条目编号互相覆盖的问题（现在按所有条目聚合，不再按编号去重丢条目）。

可选的概率加权评分：`configs/runtime.yaml` 的 `logprob_scoring`（默认 `enabled=true`）或 `simulate --logprob-scoring` 会让每个非复合量表额外做一次只输出整数总分的评判调用，按 `score = sum(i * p_i) / sum(p_i)` 取概率加权期望作为该量表的 0–10 归一化输入，取代条目均值（条目级 JSON 调用仍执行，`item_scores` 保留作审计）。数值 token 总概率质量低于 `mass_floor`（默认 0.25）判为拒答。RRO 与 PANAS 仍用各自的官方复合公式；该选项每个量表多一次调用，评分器口径不变。该路径默认开启：端点必须返回 `logprobs`/`top_logprobs`，否则按下一节记评分失败；把 `configs/runtime.yaml` 的 `logprob_scoring.enabled` 改为 `false` 即可关闭（`simulate --logprob-scoring` 只会显式开启）。评分调用与生成调用共用同一份瞬时重试预算。

每个量表按其官方原始条目范围归一化为 0–10 原始分（与官方 eval 方法一致，不因方向取反）：WAI、HTAIS、`custom_dim`、EFT-TFS、MITI、IPO、PANAS 为 1–5，TES 为 1–7，PSC、CTRS 为 0–6，SCL-90、SRS、STAI、SFBT 为 0–4，BDI-II 为 0–3，CCT 为 0–2。各量表的原始范围记录在 `Instrument.scale`，评分时按 `(条目均值 - 下限) / (上限 - 下限) × 10` 换算；症状量表（SCL-90、BDI-II、IPO）保持原始方向（越高越重），`direction` 仅作元数据，不对分数取反。PANAS 单独按正/负情绪平衡公式 `(positive − negative + 10) / 2` 计算，不是条目均值。缺字段、非法 JSON 或 schema 不符会使该候选评分失败，不用零分或均分代替。量表评分没有临床效度保证，也无法完全防御对话中的评分操纵。

设咨询师侧各量表 0–10 归一化分数为 C_k，来访者侧各量表 0–10 归一化分数为 L_k。奖励对齐 PsychAgent `src/rft/reward.py` 的固定 z-score 标准化：

```text
咨询师侧：z_k = clip((C_k - μ_k) / σ_k, -3, 3)
来访者侧：delta_k = L_current[k] - L_previous_winner[k]
          z_k = clip((delta_k - μ_k) / σ_k, -3, 3)
          SCL-90、BDI-II、IPO 的 z_k 再取负（负向 delta 表示改善）
R = 所有可用 z_k 的算术平均；没有可用信号时为 0.0
```

μ_k / σ_k 是 `evaluation/rollout.py::REWARD_STD_MEAN` 中硬编码常量，逐字取自官方 `src/rft/reward.py` 的 `DEFAULT_REWARD_STD_MEAN`，不对当前候选临时归一化。咨询师侧用绝对分、来访者侧用跨 session 差值，不是两侧各算平均再按权重混合。首次没有上次胜出快照时，来访者侧全部跳过（`missing_previous_reward`），首轮只比较咨询师侧 z 值。缺少标准化统计的指标被跳过，失败指标没有数值也不进入均值。总分反映候选排名信号，不表示疗效。来访者合理拒绝、悲伤或谨慎不天然是低分；不能靠讨好、突然康复或强行消除阻抗获取高分。跨会谈的评分噪声和来访者采样随机性仍会影响结果，正式实验应独立复评并做多次重复。

SCL-90 仍出现在每 session 的 PsychEval 报告中，但不进入 RFT 奖励（官方 RFT 默认八方法不含 SCL-90）。奖励公式与官方 `compute_rollout_reward` 相同；量表本身对齐 PsychEval，公开仓库未包含权重训练，因此最终 z 值不当作论文分数的逐字复现。

## 资格、安全与失败

- 规则安全/披露门控（`SessionSafetyGate`）必须通过：咨询师不得在来访者披露前引用隐藏事实，高风险场景必须停止普通干预并连接现实支持；输出安全阻断和实际暴露的隐藏信息直接排除。门控只决定准入，不参与分数。
- 咨询师侧总分只用于 best-of-n 排序，不设绝对分数下限；其他高分不能抵消安全或披露违规。
- 任何候选前缀出现即时风险时，立即保存风险标记、取消其他任务并令整批 `safety_hold`，不选赢家、不推进记忆。恢复同时核对候选文件与数据库，取消或崩溃不能绕过已记录风险。
- 评分器校验失败（如非法 JSON 或量表 schema 不符）先按 `judge_retries` 重试，重试仍失败才记 `scoring_failed`；生成失败与评分失败都会按 `resample_limit` 补采新候选，补采仍不足 `min_eligible` 才整批失败。
- 瞬时网络错误与 HTTP 5xx 先按 `MODEL_MAX_ATTEMPTS`（默认 3）重试，预算耗尽才记 `generation_failed`/`scoring_failed`；聊天生成、logprob 评判与技能向量 embedding 批次调用共用这一预算，最终失败的请求元数据（角色、模型、状态码、尝试次数）写入该候选的 `dNNN/api_error` 记录，不写提示词或密钥。embedding 失败记为 `role="embedding"`、`output_schema="Embedding"`，`request` 只含向量模型、批次序号与批量，不含技能文本。
- `logprob_scoring` 默认开启：端点未返回 `logprobs`/`top_logprobs` 或数值 token 总质量低于 `mass_floor` 时同样记评分失败并按上面的补采规则处理：不把条目均值、零分或均分当作该候选的分数。启用前先用 `psych-sandbox probe logprob-scoring` 留档端点实测记录，换模型或供应商后重跑；不需要该路径时把 `configs/runtime.yaml` 的 `logprob_scoring.enabled` 改为 `false`。
- 少于 `min_eligible` 个不同且合格的候选时，整批失败；不把 API 失败、评分失败或不合格候选当作低分负例。
- 失败或取消保留已经生成的对话前缀、当时记忆、诊断与错误；强制终止进程可能留下 `running` 状态，不应当成已完成候选。失败批次可从最后已提交会谈重跑，第一场尚未提交也可以恢复。

## 产物和恢复

```text
runs/runtime/<本次运行>/
  run.json
  trajectory.jsonl                只含正式胜出会谈
  result.json / report.html       完成后的正式疗程与选优摘要
  rollouts/
    s001__batch-<唯一编号>/        第 1 次会谈的一次采样批次
      input.json                  公共记忆/计划、模拟初态、采样配置和上一胜出评分
      selection.json              所有状态、评分依据、分数与赢家；不是提交成功标志
      candidate-001.json          完整候选、督导报告与安全门控、对话后记忆、失败前缀
      candidate-002.json
      candidate-004.json          补采的新候选（编号递增，不覆盖原失败候选）
      d001/                       候选 001 的 API 错误诊断（如有）
    s002__batch-<另一编号>/
```

紧凑目录减少 Windows 深层路径问题。SQLite 新增独立 `rollout_batches` / `rollout_candidates` 表，候选绝不写正式 sessions/turns/memories/trajectories；批次详情与候选 JSON 同时保留。 HTML 展示各候选状态、总分、变化项、引用和原始记录链接。旧结果没有 RFT 字段仍可加载显示。

只有胜出会谈完成后处理并成功提交 SQLite，才成为下一会谈的基线。如果选优成功但会后 API 失败，批次的 selected 仍保留，但正式会谈不会前进。续跑会重新创建批次，不覆盖失败或未提交候选。续跑必须使用相同 RFT 配置和原始 seed；完整会谈已提交时从后一个会谈开始，SQLite 是恢复来源，会重新同步 JSONL。正式会谈禁止覆盖已提交编号；新增会谈提交会使旧整体评估失效。

```powershell
.\.venv\Scripts\python.exe -B -m psychsandbox simulate --case psycheval-cbt-001 --sessions 6 --rollouts 3 --resume-run run-xxxxxxxxxxxx
```

此接口不提供中途某个 token/turn 的恢复，不自动删除失败候选，不把选优数据直接交给训练导出。命令中的运行编号须替换为实际保留的记录；清理过的历史编号不能恢复。示例沿用默认 RFT 配置，若原运行改过候选数、并发、温度或门槛，应保持原值，不能借续跑做不同配置的对比实验。例如旧运行实际使用 8 候选，续跑仍须显式传 `--rollouts 8`，不能因新默认值为 3 而更换设置。并发默认跟随候选数，因此恢复在旧默认（生成/评分并发固定为 2）下启动的运行，需显式传 `--rollout-concurrency 2 --judge-concurrency 2` 才能通过配置一致性检查。完整删除使用 `runs delete --run <编号>` 预览，再加 `--yes`；会同时清除该运行全部 RFT 批次及候选，不把落选分支留下作为悬空数据库记录。删除开始后拒绝续跑，详见 [运行文件约定](RUN_ARTIFACTS.md)。测试产物采用同样结构，位于对应 `runs/tests/<批次>` 内；没有调用真实服务的测试只能验证流程约束。

## 参考范围

- [PsychAgent 论文 §3.3](https://arxiv.org/html/2604.00931v3#S3.SS3)：完整会谈候选、评分选优、仅胜出历史推进。
- [官方固定提交 rollout](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/runner.py)：有界异步采样、会谈选择及存档。
- [官方 reward](https://github.com/ECNU-ICALK/PsychAgent/blob/469f45ef468b968b3fccd1936d7e6a0a574e4c5c/src/rft/reward.py)：双侧评分及上次胜出来访者分数作为变化基线。

本实现新增严格资格门、精确对话去重、任务隔离与失败留档；奖励公式对齐官方 `src/rft/reward.py` 的固定 z-score 标准化，量表本身对齐 PsychEval，但公开仓库未包含权重训练，不能据工程参考宣称复制了论文训练收益。
