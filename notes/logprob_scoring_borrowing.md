# 借鉴：论文 logprob 连续评分与拒答质量门

来源：Zhang et al., *Mechanistic control of large language models as simulated
participants via linear representation*, npj Artificial Intelligence,
DOI 10.1038/s44387-026-00160-9，式 8「通过 logprob 参数聚合 EMS 得分」，以及
`ems-activation-steering` 公开代码。

## 结论：只借鉴方法学副产品

论文主线（提取激活方向向量并用激活引导操纵模型内部状态）**不迁移**：它要求
权重开放的目标模型与逐层激活访问，本仓库的生产仿真是 API-only，且
`AGENTS.md` 明确规定确定性网关只能作为测试替身。被借鉴的只有评分器一侧的
方法学细节：

- 查询评判模型全部数值 token 的 logprob，按 `score = sum(i * p_i) / sum(p_i)`
  取概率加权期望（连续分，避免解析自然语言的歧义）；
- 数值 token 的总概率质量低于 0.25 视为拒答并丢弃该判分；
- 评判请求使用 temperature 0.7、max 16 token、top 20 logprobs。

## 落点

| 位置 | 内容 |
|---|---|
| `src/psychsandbox/logprob.py` | 纯函数：数值 token 解析、概率加权期望、质量门、`LogprobScoringUnsupported` / `LogprobRefusalError`、评分提示词渲染 |
| `src/psychsandbox/model_client.py` | `ModelGateway.complete_numeric_rating`（基类显式报错）与 `OpenAICompatibleGateway.complete_numeric_rating`（`logprobs=True`、`top_logprobs`、不发送 `response_format`）；评分调用与生成调用共用 `MODEL_MAX_ATTEMPTS`（默认 3）瞬时重试预算，预算耗尽写 `kind="api_error"` 诊断 |
| `prompts/eval/_scoring/instrument_rating.txt` | 项目新增的评分提示词资产（非官方 PsychEval 量表），要求评判模型只输出一个整数量表总分 |
| `src/psychsandbox/evaluation/psycheval_supervisor.py` | 可选 `logprob_scoring`：`score_instrument_rating` 给出量表级连续分，替换 `_score` 的条目均值；RRO/PANAS 保留官方公式 |
| `src/psychsandbox/evaluation/scoring_probe.py`、`cli.py probe logprob-scoring` | 端点可行性实测入口，一次调用一个 `runs/` 目录，写 `probe.json` |
| `run_simulate.bat` | 双击启动器：默认 `LOGPROB_SCORING=1`，仿真前先探测端点（`PROBE_LOGPROB=1`），支持 `run_simulate.bat probe` |
| `src/psychsandbox/domain/models.py`、`configs/runtime.yaml` | `LogprobScoringConfig`（配置默认开启，改为 `enabled: false` 即关闭；启动器仍显式传 `--logprob-scoring`），配置与 `runs/runtime/*/run.json` 快照同时留存 |

## 与论文的差异（有意为之）

- **评判粒度**：论文对一个回答给一个 0–100 分；本仓库的评判单位是一个 PsychEval
  量表的总体评分。量表条目仍由官方提示词 JSON 调用产出，作为 `item_scores`
  审计信息保留，连续分只替换聚合值。因此「质量门」的粒度是单个量表判分。
- **不走 JSON schema**：JSON 约束解码会把分布限制在语法允许的 token 上，破坏
  概率门的意义，所以 logprob 路径不再发送 `response_format`。论文风险清单里的
  「JSON schema 与 logprob 互斥」在此按「两条路径分开」处理。
- **单数字评分带**：本仓库量表的原始范围都是单数字（1–5、1–7、0–6、0–4、0–3、
  0–2），首个生成 token 即可覆盖整个评分带；`logprob_band` 会拒绝更宽的评分带，
  而不是把部分分布当成完整分布。
- **明确失败**：端点不返回 logprobs → `LogprobScoringUnsupported`；质量低于门限
  → `LogprobRefusalError`。两者都不回退到条目均值、零分或均分，与
  `docs/SESSION_RFT.md` 的「失败不用分数代替」一致；RFT 会记为 `scoring_failed`
  并按既有 `resample_limit` 补采，整体督导则走既有失败路径（记录提示、不生成整体
  报告，也不会生成一个假分数）。离线测试用 `tests/deterministic_gateway.py` 的
  `DISABLED_LOGPROB_SCORING` 显式关闭该路径（确定性双替身不产出 logprobs），默认开启
  只影响真实端点。

## 端点实测记录（2026-09-27）

```powershell
.\.venv\Scripts\python.exe -B -m psychsandbox probe logprob-scoring --case psycheval-cbt-001 --instrument wai
.\.venv\Scripts\python.exe -B -m psychsandbox probe logprob-scoring --case psycheval-cbt-001 --instrument ctrs
.\.venv\Scripts\python.exe -B -m psychsandbox probe logprob-scoring --case psycheval-cbt-001 --instrument bdi_ii
```

四次调用全部 `supported=true`、`accepted=true`（产物目录被 Git 忽略，仅本机保留在
`runs/runtime/20260927-*__probe-logprob-scoring__*/`，每目录含 `run.json` 与 `probe.json`）：

| 量表 | 评分带 | 提示词文件 | 概率加权期望 | 总质量 | 分布（节选） |
|---|---:|---:|---:|---:|---|
| `wai` | 1–5 | 1 | 3.8197 | 0.99998 | 3: 0.191, 4: 0.798, 5: 0.011 |
| `ctrs` | 0–6 | 6 | 3.6908 | 0.99997 | 2: 0.005, 3: 0.430, 4: 0.360, 5: 0.176, 6: 0.012 |
| `ctrs`（重复） | 0–6 | 6 | 4.1054 | 0.99994 | 3: 0.249, 4: 0.356, 5: 0.356 |
| `bdi_ii` | 0–3 | 1 | 1.1077 | 0.99999 | 0: 0.454, 1: 0.076, 2: 0.379, 3: 0.091 |

- 端点：当前配置的 OpenAI 兼容端点在不发送 `response_format` 时确实返回
  `top_logprobs`，因此 `logprob_scoring` 的端侧前置条件成立。该结论只覆盖本次实测的
  base_url / model / 参数组合，换模型或换供应商后必须重跑同一条命令。
- 三个评分带（单个位数范围）都被首个生成 token 的分布完整覆盖，多文件量表
  （CTRS 六个 criteria）拼接后同样可用。
- 两次 CTRS 探测在 temperature 0.7 下给出不同期望（3.69 / 4.11），说明该路径不保证
  复现；`probe.json` 保留每次的完整分布，方法学结论应看多次观测而不是单次数值。
- 对话为固定合成 fixture（`probe.json.dialogue_note` 有标注），只用于探测端点能力，
  不是研究数据，也不代表量表效度。

## 验证与回归

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_logprob_scoring.py
.\.venv\Scripts\python.exe -B -m pytest -q
```

`tests/test_logprob_scoring.py` 覆盖：加权期望与越界 token、质量门边界
（0.25 通过、0.24 拒绝）、非法 token、单数字评分带校验、提示词占位符、网关请求
契约（`logprobs`/`top_logprobs`/无 `response_format`）、拒答不重试、不支持时显式
报错、基类网关拒绝、supervisor 集成（连续分与条目审计并存、失败不外退、复合量表
不受影响）、探针记录与 CLI 目录约定、默认开启（`enabled=true`）断言、传输重试预算
与 `api_error` 诊断、默认开启且端点不支持时不回退条目均值。

## Windows 启动脚本

`run_simulate.bat` 默认 `LOGPROB_SCORING=1`，并在跑仿真前先执行一次探测量表
（`PROBE_LOGPROB=1`）：探测失败即打印错误并中止，避免整批 RFT 候选生成完才发现评分
不可用。`PROBE_LOGPROB=0` 跳过探测，`run_simulate.bat probe` 只探测并打印完整记录
（等价于 `psych-sandbox probe logprob-scoring ... --json`）。探测量表由
`PROBE_INSTRUMENT` 指定，默认 `wai`；案例、会话数、每场轮数上限（`TURNS`）、候选数、并发与瞬时重试预算
（`MODEL_MAX_ATTEMPTS`，启动器默认 6）同样在脚本顶部可调。

脚本必须保持**纯 ASCII 且不调用 `chcp`**。原因在 2026-09-27 实测复现：cmd 按“读取
某一行时生效的代码页”解释批处理文件，一旦文件里出现非 ASCII 字节（无论是
`chcp 65001` 之后的 UTF-8 中文，还是无 `chcp` 时的 UTF-8 中文注释），解析器都会丢掉
行位置，把注释行碎片当成命令执行，出现 `'...' 不是内部或外部命令` 报错，极端情况下
还会因为碎片恰好是 `cmd` 而弹出嵌套 shell：

| 文件形态 | 结果 |
|---|---|
| UTF-8 + `chcp 65001` + 中文 rem/echo | 复现碎片报错（原脚本即如此） |
| UTF-8 + 无 `chcp` + 中文 rem 注释 | 长脚本仍复现碎片报错 |
| UTF-8 + `chcp 65001` + 纯 ASCII | 干净 |
| UTF-8 + 无 `chcp` + 纯 ASCII | 干净 |

因此用户可见的中文提示改由 Python Unicode 转义输出（`%PY% -c "print('\uXXXX...')"`），
CMD 窗口与重定向日志都能正确显示。修改提示文案时，先把中文写好再转换成 `\uXXXX`
转义写入脚本；`tests/test_launcher_script.py` 会拒绝非 ASCII 内容、`chcp` 调用、
以及丢失 logprob 默认开关或 `probe` 子命令的改动。

## 已知限制与后续

- 连续分会改变「同分」比例，可能影响 RFT 的去重与门槛行为；启用前应先跑一次
  `--rollouts` 小样本对比，本仓库未做该对比实验。
- 开启后每个非复合量表多一次评判调用（条目 JSON 调用保留），成本约翻倍。
- 只有实测过的端点组合可以开启；未实测的端点应先跑 probe，把 `probe.json` 与运行
  一起留档。
- 端到端临床效度没有变化：该路径只改变分数聚合方式，不改变量表本身的口径。
