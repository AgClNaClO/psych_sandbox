# 逐条目 logprob 评分：方法、边界与端点验证

借鉴 Zhang et al., *Mechanistic control of large language models as simulated participants via linear representation*，DOI [10.1038/s44387-026-00160-9](https://doi.org/10.1038/s44387-026-00160-9)，式8及数值概率质量门。只借鉴评分方法，不迁移激活引导、开放权重或内部表征访问。

## 当前实现：item_logprob_v2

每个 PsychEval 原提示文件只请求一次完整 `{"items":[...]}` JSON，开启 logprobs/top_logprobs，不发送 response_format 或 tools。逐项定位 `items[*].score` 的 JSON 词法跨度，并与 UTF-8 Token 字节位置对齐。条目编号、证据字符串和其他数字不参与评分；不通过宽泛正则扫描或文本修复猜位置。

每项按 `E=Σ(i·exp(logprob_i))/Σexp(logprob_i)` 计算。默认数值质量门0.25、top-20、8192输出Token、温度0。质量门作用于原始概率质量，低于门限报错；同Token去重，同值不同拼写合并，采样Token未列入候选时补入一次。NaN、正logprob、冲突重复项或总概率超过容差均拒绝；负无穷表示零质量。

固定目录 `prompts/eval/_scoring/item_catalog.json` 保存预期ID、评分带、来源路径和换行规范化后的UTF-8 SHA-256。目录覆盖46个量表提示文件；资源变化必须人工同步目录并回归，不从模型输出推断应有多少条目。多文件量表审计键为来源文件加条目ID。

新接口 `ModelGateway.complete_item_ratings` 返回 `BatchItemRatings`；条目期望保存在 ScaleScore.item_scores，分布、质量、采样分、Token索引及字节跨度保存在 item_logprobs。旧 ScaleScore 没有审计字段时按空字典读取。RRO/PANAS 同样连续化条目，随后保持官方复合公式；不再额外生成一个量表总体分。

## 明确失败与解释限制

只支持0–9内严格递增的单数字评分带及单Token整数评分。缺项/重项、重复JSON键、非法结构、非正常结束、没有top_logprobs、分数字符串或小数、分数与标点合并、拆Token、字节错位、任一条目质量不足，都使整次评分失败。不以离散值、零分、部分均值代替，不额外逐项补问。既有传输/RFT预算负责整体失败处理。

兼容端点可能在logprobs尾部附加结束标记而不放入正文。实现只在正文已经精确重建时排除已知尾部EOS（DeepSeek结束符、im_end、endoftext、eot_id）；任意额外文本和正文错位仍拒绝。首次真实探针发现这一行为，独立alignment-diagnostic运行保留了长度和首差位置，不代表评分成功。

Top-20不是全词表；缺席候选不能当作已知零概率。期望与质量均针对可观察候选。后续score是给定已生成JSON前缀的条件分布，不是独立的完整边际分布。无约束JSON避免语法约束人为抬高数值质量，但不能消除提示词和前缀依赖。温度0不保证远端完全复现，也不保证评分有临床效度。

## 2026-11-02批量端点实测

使用当前配置的SUPERVISOR_MODEL与端点、固定合成对话；每个量表独立一次probe目录。结果只验证本次部署和参数组合，不能沿用旧总体评分记录来证明新路径可用。分数为0–10聚合值；RRO此处展示咨询师侧。

| 量表 | 条目数 | 聚合分 | 最低条目质量 | 运行目录（runs/runtime下） |
|---|---:|---:|---:|---|
| wai | 12 | 5.000000 | 1.000000 | `20261102-013943-814449__probe-logprob-scoring__033ed170e030` |
| ctrs | 6 | 6.667000 | 0.999999 | `20261102-013948-877199__probe-logprob-scoring__a18f2f8efd3c` |
| bdi_ii | 21 | 1.348000 | 0.999951 | `20261102-013959-203107__probe-logprob-scoring__5dc75c5fabb8` |
| scl90 | 90 | 0.493000 | 0.999963 | `20261102-014003-881753__probe-logprob-scoring__858b5a0a58af` |
| rro | 24 | 4.985000 | 0.999980 | `20261102-014012-144599__probe-logprob-scoring__49f89a29f428` |
| panas | 20 | 4.011000 | 0.999988 | `20261102-014017-461300__probe-logprob-scoring__b5d788a3abfb` |

运行 `psych-sandbox probe logprob-scoring --case psycheval-cbt-001 --instrument <量表键>` 可复查；换供应商或模型后重跑。完整逐项分布见各目录probe.json。这些对话不是研究数据，不用于效度判断。历史首次字节校验失败记录保留，不覆盖或删除。

## 参数与恢复

logprob默认关闭，可用YAML enabled:true或CLI --logprob-scoring显式开启；开启前先执行端点探针。启动器默认关闭评分和预探针，可分别设置LOGPROB_SCORING=1与PROBE_LOGPROB=1启用；批处理保持ASCII且不调用chcp。RFT默认开启，候选数为3。`temperature.control=0`控制规划/记忆，生成温度分别为来访者0.7和咨询师0.9，评分0是项目的稳定性默认，区别于论文0.7。

评分快照记录item_logprob_v2。旧instrument_logprob_v1历史奖励不能作为新RFT运行的比较基线；恢复时不匹配要求新建运行。已有文件和共享数据库不自动迁移。

## 历史：总体评分探针（2026-09-27，仅代表旧方法）

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


## 验证方式与后续研究

运行全套 `python -B -m pytest -q`。专项覆盖JSON路径、Unicode字节、结束符、质量门、分布数值、五流派公式、RFT恢复和参数传递。研究上仍需离散/连续评分的配对实验、重复评估、排名稳定性及专家复评；上述端点探针未完成这些研究。输出与清理遵守 [运行产物](../docs/RUN_ARTIFACTS.md)。
