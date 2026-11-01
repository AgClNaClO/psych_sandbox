# Psych-new选技源码调查

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-08-27只读核查本机Psych-new，读取时HEAD为469f45ef468b968b3fccd1936d7e6a0a574e4c5c，另有15组JSON/PT资源检查与离线控制流验证，未运行真实backend/sample或模型API。资源meta最大深度7、micro路径最大8；运行不是逐层LLM搜索，而是叶组粗筛、查询改写、embedding精筛及预注入回复提示。sample每场粗筛一次，Web每次回复粗筛。

## 当前实现

当前沙盒的Planner/Observation/Actor与来源链不同：公开证据选组、精确展开、超阈值才向量筛选，Actor给出目录内ID。不能把来源项目文字标签当成原生tools协议。

## 未实施建议与验证边界

若比较两条链，应固定病例、目标、可见记忆与候选库，并报告成本/失败；本次没有启动外部服务或复现效果。历史表格记录资源与调用形态。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 项目 | Web | sample |
|---|---|---|
| 粗筛频率 | 每次回复一次 | 每个 session 一次 |
| 精筛频率 | 有 user_query 的回复前 | 开场前、此后每次 client 发言后 |
| 候选池 | 每次重新生成 | 会谈内复用，无法在精筛阶段找回本次粗筛排除的分支 |
| 会话目标 stage_title | 实际 stage.label | 写死为字符串“stage” |
| 精筛失败 | 进入简短 baseline prompt fallback | 重试耗尽后返回空技能，继续用流派咨询师模板 |
| 粗筛、改写日志返回值 | 调用者丢弃 | 调用者丢弃；保存 each_turn_system |

| 层或字段 | 运行作用 | 边界 |
|---|---|---|
| sect 流派 | 选择技能目录和流派提示词 | 没有 LLM 跨流派粗筛 |
| stage1/2/3 | 直接选库分区 | 每次 session/visit 内固定，不由每轮检索改写 |
| meta 中间层 | 定义 ancestry，影响 leaf 判定与路径归属 | 不做逐层 LLM 决策，父层描述不直接进入检索提示词 |
| meta leaf | LLM 粗筛的实际条目 | 输入移除了 parent_ids，只见扁平 leaf 内容 |
| parent_ids | 精确关联 leaf→micro | 无完整树 schema 校验；格式不符会导致匹配不到 |
| meta_skill 祖先名称串 | find_skill_by_id 会构造 | 两个主入口只取 micro_skills，祖先名称串在后续丢弃 |
| micro | 向量排序对象，最后提供给咨询师的具体技能 | 咨询师收到名称、描述、时机、触发线索，不收到完整树 |
| embedding_to_retrive | 与改写 query 的向量算余弦相似度 | 字段名确实拼作 retrive |
| embedding_to_merge | 启动时检查/补齐，候选缺失时也补齐 | 当前选择链路未用它合并技能、排序或执行进化 |

| 流派/阶段 | meta 节点 | meta leaf | micro | 最大 meta / micro 路径深度 |
|---|---:|---:|---:|---|
| BT stage1 | 58 | 41 | 390 | 5 / 6 |
| BT stage2 | 95 | 62 | 443 | 7 / 8 |
| BT stage3 | 3 | 2 | 21 | 2 / 3 |
| CBT stage1 | 31 | 22 | 504 | 5 / 6 |
| CBT stage2 | 54 | 40 | 609 | 5 / 6 |
| CBT stage3 | 18 | 11 | 259 | 5 / 6 |
| HET stage1 | 42 | 27 | 285 | 5 / 6 |
| HET stage2 | 81 | 58 | 409 | 6 / 7 |
| HET stage3 | 13 | 8 | 58 | 4 / 5 |
| PDT stage1 | 28 | 18 | 281 | 5 / 6 |
| PDT stage2 | 167 | 112 | 670 | 6 / 7 |
| PDT stage3 | 15 | 10 | 93 | 4 / 5 |
| PMT stage1 | 12 | 8 | 80 | 4 / 5 |
| PMT stage2 | 56 | 44 | 370 | 6 / 7 |
| PMT stage3 | 4 | 1 | 9 | 4 / 5 |

| 参数 | 默认值/当前默认 YAML | 实际作用 |
|---|---|---|
| psychagent_skill_base_dir | assets/skills/sect | 技能资源根目录 |
| psychagent_skill_sects | all，即 cbt、bt、pdt、het、pmt | 启动加载这五个流派各三个阶段 |
| 粗筛 n / top_n | 20 | Python 函数默认值，入口不覆盖 |
| 精筛 top_k | 5 | Python 函数默认值，入口不覆盖 |
| 精筛 threshold | None | 不设最低相似度 |
| psychagent_embedding_model | BAAI/bge-m3 | query 及补齐向量的 embedding 模型 |
| embedding base URL | https://api.siliconflow.cn/v1 | 配置中的地址；调查未访问 |
| embedding API key env | PSYCHAGENT_EMBEDDING_API_KEY | RuntimeConfig.validate 及 load_library 都要求存在 |
| embedding batch / max retries / sleep | 64 / 16 / 0.5 秒 | 批量补齐及失败重试；sleep 按 attempt 线性增加 |
| psychagent_counselor_system_filename | system.jinja2 | 流派 counsel 子目录的模板文件 |
| psychagent_max_retries | 16 | sample 外层粗筛、检索、回复等重试 |
| psychagent_max_turns | 45 | sample rollout 的咨询师轮次上限 |

| 提示词 | 当前调查入口中的状态 |
|---|---|
| skill/select_skill/system.txt、user.txt | 启动时读入；粗筛时渲染并发送 |
| skill/rewrite/system.txt、user.txt | 启动时读入；非空候选的精筛调用中发送 |
| 各流派 counsel/system.jinja2 | 首次创建该流派 PromptManager 时加载；每轮渲染 |
| 各流派 summary/profile 的 system/user | 同一 PromptManager 创建时全部加载；会谈收尾实际调用 |
| public/counselor_system.jinja2、session_opening.jinja2、public_recap.jinja2 | core PromptManager 有对应方法，但当前 sample/Web 咨询师链路没有调用这些方法 |
| Web fallback 提示词 | 来自 visit_service.build_visit_prompt 中的 Python 字符串，不是 public 模板 |

| 失败/异常条件 | 已核实行为 |
|---|---|
| embedding key 缺失 | RuntimeConfig.validate 就拒绝配置；load_library 也再次要求。不是等逐轮检索时才检查 |
| 缺少检索提示词文件 | load_library 直接 read_text 失败，没有缺文件时自动使用默认提示词 |
| leaf 库为空 | 粗筛直接返回空，后续可无技能继续 |
| 粗筛 LLM 异常、解析失败、空 ID 列表 | fallback 为 leaf 插入顺序前 n 个；不是相关度排序或安全技能兜底 |
| 返回非空无效 ID 列表 | find_skill_by_id 跳过不存在的 meta；不会因最终候选为空再次 fallback |
| 返回非 leaf 但存在的 meta ID | 可被接受；按严格直接路径匹配，通常没有 micro，不递归展开 |
| rewrite/embedding 失败 | sample 外层重试耗尽返回 []；Web 则由整条 prompt chain 的异常处理换到简短 fallback |
| 无候选 | retrive 返回 []，不做 rewrite，也不调用 query embedding |
| 启动时 load_library 失败 | Web 的 startup 在回复 try 之前、也在应用 startup 运行；正常回复 fallback 不能兜住启动失败 |

| 固定返回内容 | 实际结果 |
|---|---|
| {"skill_id":["3"]} | 1 组、24 个候选 micro |
| {"skill_id":["3","3"]} | 2 组、48 个候选，只有 24 个唯一 micro |
| {"skill_id":["1"]} | 1 个 meta 组，0 个 micro；不递归收集后代 |
| {"skill_id":["NOT_REAL"]} | 0 组、0 micro；不触发空 ids fallback |
| {"skill_id":"32"} | 被按字符遍历成 "3"、"2"，而非一个 ID "32" |
| {"skill_id":[]} | fallback 20 个 leaf，458 个 micro |

## 原记录来源链接

- [来源 1](https://api.siliconflow.cn/v1)
