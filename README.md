# 基于 PsychEval/PsychAgent 的心理咨询多智能体研究沙盒

文档按 2026-11-10 的当前工作区核对；包版本仍为 `0.3.0`。配置默认值、历史研究结果和本次验证分别记录。

本项目面向心理咨询对话仿真、多智能体机制比较和大学生创新训练研究。它以 PsychEval 病例为事实来源，结合分流派、分阶段的技能树，让“模拟来访者—咨询师—督导师”完成多次会谈，并保存披露证据、跨会谈记忆、技能选择、状态变化、候选选优和整体评分。

支持行为（BT）、认知行为（CBT）、人本—存在（HET）、心理动力（PDT）、后现代（PMT）五流派。各流派共用运行框架，但保留独立病例、原生概念化、技能目录和专属评估指标。

> 仅用于非商业教学与科研，不是真实心理咨询或医疗服务。模拟状态与模型评分不能用于诊断或证明治疗有效。

## 快速开始

已有检出目录无需重新 clone。以下示例默认在项目根目录的 **Windows CMD** 中执行；PowerShell 的迁移检查见第 5.3 节。

```bat
cd /d C:\Users\Rain\Desktop\psych_sandbox
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
if not exist .env copy .env.example .env
```

然后编辑 `.env`，填写真实 API 密钥、端点与角色模型。首次运行或缓存过期时编译数据，再查看案例：

```bat
python -B -m psychsandbox data convert --therapy all --atomizer extractive
python -B -m psychsandbox cases list --therapy cbt
```

开启逐条目 logprob 评分前先探测端点，再运行一个案例：

```bat
python -B -m psychsandbox probe logprob-scoring --case psycheval-cbt-001 --instrument wai
python -B -m psychsandbox simulate --case psycheval-cbt-001 --sessions 3 --logprob-scoring
```

RFT 默认开启（每场 3 个候选），logprob 默认关闭；配置对象、项目 YAML 和启动脚本保持一致。使用 `--no-rft` 关闭选优，使用 `--logprob-scoring` 开启逐条目概率评分，详见第 7 节。

成功运行后，终端输出 `run-xxxxxxxxxxxx` 编号及 `report.html` 路径。测试与正式运行分别写入 `runs/tests`、`runs/runtime`。完整操作说明按下列章节展开，专题文档统一从 [文档索引](docs/README.md) 进入。

## v0.3.0 更新重点

v0.3.0 建立了五流派共用运行时：病例转换、咨询师规划/执行、来访者受限生成、跨会谈记忆、纵向计划、整体督导和结果持久化。当前包版本仍为 `0.3.0`；下面的后续能力已经继续发展，不能仅依据版本号判断某个机制是否存在。

主要设计包括：咨询师不读取完整私有画像；事实披露必须核验实际台词；最终技能由模型在允许目录内选择；会后自评与纵向信号决定下一计划；生产模拟统一通过 API 完成。

## v0.3.0 之后的更新

- 咨询师技能链加入公开选技依据、完整技能路径、超阈值向量筛选和最多一次纠错，原始资源树保持不变。
- 咨询师在自动仿真和人工会谈中逐轮读取本场完整对话，已完成的询问和干预直接从对话中判断。
- 记忆改为四字段结构，并提供完整读取与近期窗口两种视图；开放作业和事项依据会谈证据退役。
- 来访者增加空转修复、信任锚点、有来源的依恋条件指导及本地主题匹配消融；内部规划与台词生成的信息边界继续分离。
- 会谈 RFT 支持隔离候选生成、资格检查、统一量表评分和贪心选优，仅赢家进入正式记忆与下一会谈。
- logprob 升级为 `item_logprob_v2`：直接读取批量 JSON 各条目 `score` 的数值 Token 分布，不再额外生成量表总体分；RRO、PANAS 也使用连续条目后按原公式汇总。
- Temperature 按任务统一：来访者生成 0.7、咨询师生成 0.9、评估与规划/记忆处理 0；显式配置覆盖仍保留，重试不再暗改温度。
- 本地 Web 工作台提供实验任务、人工多会谈、技能版本与审核、实验比较和受控 SFT/DPO 导出。
- 数据转换支持有界并发、pilot 与重复输入复用、分阶段进度和旧 processed 备份；失败现场保留在本次转换目录。
- CLI 与网页显示会谈、候选和量表进度；网页从持久事件恢复当前执行快照，支持原运行的会谈边界续跑。
- 独立技能进化试验提供提取、Append/Merge/Skip、实验快照和基线对比；实验候选不自动进入正式发布。
- 文档分为当前实现、研究参考与历史归档；旧研究笔记中的参数和测试数字不作为现行配置依据。

## 1. 项目要解决什么问题

单纯让一个模型扮演咨询师，难以控制多会谈中的事实权限、记忆延续、选技依据和评价边界。本项目把这些机制拆成可以单独观察和比较的组件：

| 研究问题 | 项目中的处理 |
|---|---|
| 前后会谈如何衔接 | 公开证据、会谈回顾、作业、事项清单及下一计划 |
| 为什么选择某种咨询技能 | 规划、公开引用、目录 Observation 与实际技能 ID 留档 |
| 如何避免提前知道来访者秘密 | 私有规划视图与受限台词生成分离，披露后再次核验台词 |
| 如何比较多条会谈候选 | 完整会谈生成、资格门、独立量表评分和可追溯选优 |
| 评分会不会影响后续规划 | 候选分只选赢家；下一计划来自咨询师自评与纵向进度 |
| 能否检查实验失败 | 配置快照、候选审计、诊断、数据库与逐会谈轨迹 |

整体流程如下：

```text
PsychEval 原始病例 → 来源抽取与 schema-v4 运行缓存
                              ↓
               当前计划 + 允许记忆 + 私有来访者状态
                              ↓
               咨询师规划 → 技能目录 → 咨询师回复
                              ↓
               披露门控 → 来访者规划 → 受限台词
                              ↓
                   台词证据、安全与状态更新
                              ↓
        可选 RFT：比较完整候选 → 只提交赢家
                              ↓
        E.7/E.8/E.9 整理 → 咨询师自评 → 纵向判断 → 下一计划
                              ↓
         全部会谈完成 → 一次整体督导 → SQLite / JSONL / HTML
```

## 2. 当前完成情况

当前随仓库提供的五流派原始病例共 **341 例**，技能注册表加载 **677 个元技能、4481 个原子技能**。这些数量描述资源规模，不表示已完成同等规模的真实 API 实验。

| 流派 | 数据目录/案例前缀 | 原始病例数 | 咨询师专属指标 | 来访者专属指标 |
|---|---|---:|---|---|
| 行为 BT | `bt` / `psycheval-bt-` | 43 | MITI | STAI |
| 认知行为 CBT | `cbt` / `psycheval-cbt-` | 148 | CTRS | BDI-II |
| 人本—存在 HET | `het` / `psycheval-het-` | 50 | TES | CCT |
| 心理动力 PDT | `pdt` / `psycheval-pdt-` | 50 | PSC | IPO |
| 后现代 PMT | `pmt` / `psycheval-pmt-` | 50 | EFT-TFS | SFBT |

已具备连续会谈、会谈边界恢复、披露隔离、咨询师自评/再规划、可选 RFT、逐条目 logprob、整体督导、HTML 报告及 Web 工作台。自动化测试主要验证接口、控制流、信息权限、状态与存储一致性；真实模型能力由接口探针和后续实验另行验证。

现阶段仍需完成正式多病例重复实验、独立专家评审、评分稳定性与临床相关效度研究。会谈选优、技能审核与数据导出不等于已经执行模型权重训练。

## 3. 项目中的三个智能体

### 3.1 模拟来访者

来访者分为内部策略规划和自然语言生成。内部规划器可读取私有画像来维持人物一致性，但发言器只接收本轮获准事实、过去实际说出的片段、表达指导、必要状态及近期对话。

事实先经过话题、信任、会谈范围、依赖和歧义检查，再由规划器选择。本轮输出的 `disclosed_fact_ids` 仍要与实际台词核对；只有有文本证据的片段才会解锁并进入后续允许记忆。blocked 话题只传元数据，不传秘密正文，规划 rationale 也不作为旁路进入台词模型。

默认 `compact_patientact` 通常一次规划加一次生成；`faithful_patientact` 分开判断反应、行为和必要的阻抗，并在接受台词后判断信任。生成重试不会重复提交状态，新信任下一轮才参与披露。

情绪、信任、疲劳与关系破裂属于仿真状态。有来源的互动先验或显式合成参数不能升级为新病例事实。详见 [来访者模拟](docs/CLIENT_SIMULATION.md)。

### 3.2 多流派咨询师

每轮 Planner 和 Actor 都读取当前计划、允许记忆，以及按时间顺序排列的本场完整对话 `dialogue`。`dialogue` 包含截至本轮的双方可见消息，模型从这些消息判断本轮来访者表达及本场已完成事项。程序按流派、阶段和批准状态过滤技能，Planner 提供元技能选择依据，程序精确展开所选组，最后由 Actor 选择原子技能并生成回复。

公开背景、议程和跨场记忆通过 JSON 提供，系统提示保留角色、权限和证据规则。Planner 的目录提供技能组 ID、名称、原始说明和选技提示。Actor 接收技能原始说明、当前阶段路径、适用时机、触发条件、禁忌等选技信息，完整技能对象和向量分数留在审计记录中。

当展开候选数 **严格大于 24** 时，默认调用 embedding 筛选至 12 项；小目录完整返回。无效查询或候选不适合时，最多一次排除上一批组的纠错。相似度只缩小候选，不能替代模型判断或公开依据。

会后咨询师核对目标是否有对话证据，必要时调整策略。日志和报告保存结构化规划/决策摘要，不展示供应商内部逐 Token 思维链。详见 [技能选择](docs/SKILL_SELECTION.md)。

### 3.3 督导师

`PsychEvalSupervisor` 在完整多会谈轨迹结束后执行一次，读取评估所需背景及双方可见对话，生成咨询师侧与来访者侧 `HolisticEvaluationReport`。

相关组件有不同用途：

| 组件 | 时机 | 作用 |
|---|---|---|
| 规则安全/披露评估 | 会谈及候选检查 | 工程审计与资格门，不贡献临床分 |
| RFT 候选评分 | 开启 RFT 时 | 比较完整候选，报告留在候选 assessment |
| 咨询师自评与纵向判断 | 赢家或普通会谈结束后 | 核对目标并形成下一计划 |
| 整体督导 | 完整疗程结束后 | 独立评估整条轨迹，不参与下一计划 |

正式 `SessionRecord` 不保存逐会谈 `SessionEvaluationReport`。共享指标包括 WAI、HTAIS、RRO、custom_dim、SCL-90、PANAS、SRS，再加本流派专属指标；量表原始范围及症状方向分别保留。

## 4. 核心架构

```text
psych_sandbox/
├── src/psychsandbox/
│   ├── domain/             病例、会谈、记忆、评分与轨迹契约
│   ├── datasets/           来源抽取、编译与案例索引
│   ├── therapies/          五流派阶段、概念化与指标映射
│   ├── agents/             咨询师与来访者模型调用
│   ├── client_simulation/  来访者策略、受限生成与状态提交
│   ├── skills/             资源注册、精确目录与条件向量筛选
│   ├── runtime/            会谈编排、记忆、安全、RFT与存储
│   ├── evaluation/         量表、条目logprob、纵向与候选评估
│   ├── visualization/      从已存结果生成离线报告
│   └── workbench/          本地API、Worker、交互、审核与导出
├── tests/                  离线测试与确定性网关替身
├── configs/                运行配置与模型配置
├── data/                   原始病例及可重建的processed缓存
├── assets/                 原始技能树与来源画像
├── prompts/                生成模板、量表提示词及条目目录
├── frontend/               React/TypeScript/Vite工作台
├── docs/                   当前说明、研究资料与历史归档
├── notes/                  AGENTS固定引用的logprob方法说明
└── runs/                   测试和正式运行产物（主体被Git忽略）
```

### `src` 与 `tests` 分别负责什么

`src` 实现生产 API 运行路径；`tests` 用可控替身验证输入、输出、权限与恢复，不依赖真实供应商。测试通过证明工程契约，不证明模型能够稳定理解案例、选择正确技能或产生真实来访者行为。

各模块共享 Pydantic 领域契约，数据库、JSONL 和 HTML 应表达同一份规范结果。信息边界与术语见 [领域说明](docs/agents/domain.md)。

## 5. Windows CMD 环境准备

### 5.1 前置软件

- Python **3.11+**，可以在终端调用。
- Git：获取仓库或重新下载固定版本的上游资源时需要。
- 可用的 OpenAI-compatible 聊天 API，以及可能触发的 embedding API。
- 修改前端时需要与其依赖兼容的 Node.js/npm；仅运行 Python 测试不需要启动浏览器。

### 5.2 创建并激活虚拟环境

在项目根目录执行：

```bat
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
python -B -m psychsandbox --help
```

安装后可用 `psych-sandbox` 命令；模块形式 `python -B -m psychsandbox` 与之等价。后文简写命令均假定已激活当前项目虚拟环境。`.[dev]` 包含测试依赖；可选 training 依赖不表示已经提供完整训练流程。

### 5.3 迁移后的安装检查（PowerShell）

移动项目或复制 `.venv` 后，可编辑安装、启动器和解释器仍可能引用旧路径。先重新安装并验证导入位置：

```powershell
Set-Location -LiteralPath 'C:\Users\Rain\Desktop\psych_sandbox'
.\.venv\Scripts\python.exe -B -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -B -c "import psychsandbox; print(psychsandbox.__file__)"
.\.venv\Scripts\python.exe -B -m psychsandbox --help
```

导入应指向本项目 `src/psychsandbox`。解释器本身无法启动时，使用 Python 3.11+ 重建环境；不要仅因 pytest 可通过就假定可编辑安装位置正确。

CLI 默认把当前目录当作项目根。其他目录中运行时，`--root` 必须放在子命令之前：

```powershell
& 'C:\Users\Rain\Desktop\psych_sandbox\.venv\Scripts\python.exe' -B -m psychsandbox --root 'C:\Users\Rain\Desktop\psych_sandbox' cases list --therapy cbt
```

## 6. 数据资源与可选刷新

原始病例在 `data/<bt|cbt|het|pdt|pmt>`，技能在 `assets/skills/sect/<流派>/<stage1|stage2|stage3>`。`assets/profiles` 是来源对照，不是运行病例索引；integrative 资源不自动冒充已注册的五流派。

量表提示文件共 46 个，配套 `_scoring/item_catalog.json` 记录各文件的预期条目 ID、范围、来源和换行规范化后的 UTF-8 SHA-256。咨询师、来访者与记忆模板由 Jinja2 渲染。`prompts/client/dialogue.jinja2` 仅作参考，未接入生产生成链。详见 [资产](assets/README.md) 与 [提示词](prompts/README.md)。

### 6.1 可选：重新下载官方数据

```bat
psych-sandbox data fetch psycheval
```

下载固定 PsychEval 提交 `e04df535749e5bca76fcc45d9a85f3f46a082d91`，写入独立 `runs/runtime/<时间__data-fetch__编号>/external/psycheval`，成功后更新来源指针。已有原始病例时不必每次下载；当前转换优先读取项目原始数据，缺失五流派目录时才查找已下载来源。

### 6.2 必需：编译 schema-v4 五流派 processed 数据

```bat
psych-sandbox data convert --therapy all --atomizer extractive
```

默认最多并发 5 个抽取任务；可用 `--concurrency 5` 显式设置，范围为 1–32，`--concurrency 1` 为串行。实际 HTTP 请求另受共享的 `MODEL_MAX_CONCURRENCY` 限制（默认 5）；提高任务数不会绕过请求限制。试转换结果和同流派内的相同输入会直接复用；已有缓存仍按原文、用途、模型和版本核验，纯标点输入不调用模型。

进度分为试转换、抽取、编译、合并、校验和发布。进度事件记录完成数量、缓存命中、结果复用、失败回退、跳过数量与耗时；交互终端按窗口宽度显示计数与预计剩余时间。进度写入标准错误，标准输出保留最终 manifest JSON；重定向时每推进约 10% 输出一行，`--no-progress` 只关闭终端显示，仍保存 `progress.jsonl`。

复用限于同流派内来源路径、原文和用途相同的抽取输入，pilot 结果也在本次全量抽取中复用。五流派依次编译，各自使用独立缓存命名空间；`--concurrency` 限制当前流派的抽取并发，不表示同时启动多个转换。转换期间原始文件发生变化会报错，须保持输入稳定后重新执行。

生产转换要求五流派一起编译、使用 extractive 并显式配置 `PROFILE_MODEL`；不会在模拟时自动升级旧缓存。虽然参数解析器列出其他选项，当前生产 CLI 不接受单流派或 rules 转换。

转换从成长经历、语言特征、核心诉求和相关字段抽取原文 span，核验出处、顺序与覆盖。每流派先运行最多 5 个固定 pilot 案例，pilot fallback 比例超过 5% 则中止；其他失败项保留来源及待复核标记，不能把“有来源”理解为分类已通过人工审核。

主要缓存位于：

```text
data/processed/psycheval/
├── all.jsonl
├── train.jsonl / validation.jsonl / test.jsonl
├── skills.json
├── compilation_audit.json
├── by_therapy/<流派>/
└── manifest.json
```

缓存经过 staging 验证后替换，manifest 保存来源、模型和编译版本。每次转换在 `runs/runtime/<时间__data-convert__编号>/` 保存 `run.json`、`progress.jsonl` 和诊断；替换前的 processed 目录完整保留为其中的 `processed-backup/`，发布失败会恢复旧目录，抽取或校验失败保留 staging 供检查。转换锁避免两个转换同时发布。该目录及抽取缓存可重建、被 Git 忽略；旧运行中的病例快照和共享数据库不因此清理。

### 6.3 检查案例

```bat
psych-sandbox cases list --therapy cbt
psych-sandbox cases list --therapy bt
psych-sandbox cases list --therapy het
psych-sandbox cases list --therapy pdt
psych-sandbox cases list --therapy pmt
```

案例编号如 `psycheval-cbt-001`。案例列表也依赖有效 processed 缓存；提示缺失或过期时先显式转换，不把不匹配的原始/缓存记录混合运行。

## 7. 运行 API 仿真

### 7.1 普通连续会谈

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --max-turns 4 --seed 42
```

当前项目 YAML 为 3 场会谈、每场最多 20 个咨询师轮、seed 42、RFT 开启（3 个候选）、logprob 关闭。纯 `SandboxConfig` 的轮数默认是 8，启动脚本也显式传 8；CLI 显式参数覆盖 YAML。轮数上限是工程预算，会谈仍可能提前因结束条件或安全状态停止。

`--json` 输出规范结果并关闭交互进度绘制；`--no-visualization` 跳过 HTML 自动生成，不跳过结果持久化。

CMD 中的进度条随窗口宽度调整，显示已提交场数、当前阶段、候选轮数、评估量表数量和耗时；等待模型响应时继续更新计时。重定向到文件时按约 10% 输出普通文本，不写入回车或终端转义序列。候选轮数的分母是预算上限，预计剩余时间是当前步骤的估计，不代表实验必须用满这些轮数。

### 7.2 默认开启：整场会谈多候选与 RFT 选优

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --rollouts 3
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --rollouts 3 --rollout-concurrency 2 --judge-concurrency 2
```

每场从共同会前状态独立生成完整候选，执行安全/有效性门、去重和评分，再选一个赢家推进；不是并行生成几条完整疗程。并发为 null 时跟随候选数；`--rollouts 1` 或 `--no-rft` 明确关闭选优。

完成的候选通过资格检查后即可评分，与其他候选生成重叠；量表及其原始子提示也并行，RFT 和最终整体督导共用这一实现。所有生成、评分和 SDK 重试按服务端点/模型共享默认 5 个 HTTP 槽位，跨本项目 Worker 进程生效。每批仍等待全部候选检查后选赢家；后续出现即时风险会取消并等待生成、评分任务退出。评分按固定量表/提示顺序汇总，公式与严格失败规则不变。离散评分只在系统提示中提供一份背景和对话。

咨询师指标按固定统计标准化，来访者部分比较上一已提交赢家；首场没有历史增量时跳过该部分。只有赢家执行记忆整理、目标自评和下一计划，失败及落选分支只留审计。即时风险会使整批 safety_hold，高分不能抵消违规。详见 [会谈 RFT](docs/SESSION_RFT.md)。

### 7.3 可选：逐条目概率加权（logprob）评分

```bat
psych-sandbox probe logprob-scoring --case psycheval-cbt-001 --instrument wai --json
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --logprob-scoring
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --no-logprob-scoring
```

开启 `item_logprob_v2` 后，每个原量表提示文件请求一次批量 JSON，精确定位每个 `items[*].score` 对应的 Token 分布，再计算：

```text
p_i = exp(logprob_i)
条目连续分 = Σ(i × p_i) / Σp_i
```

默认 top-20、8192 输出 Token、评分温度 0、原始数值概率质量门 0.25。ID/证据中的数字不参与评分；缺项、重复项、无分布、截断、无法可靠对齐或任一必需条目质量不足均明确失败。不用离散分、部分均值或零分替代，也不逐项追加补问。

RRO 对连续条目执行原反向计分/因子公式；PANAS 执行原正负情绪公式；其他量表按各自原始范围归一化。`item_scores` 保存连续原始分，`item_logprobs` 保存分布、质量、采样分及位置。此处 top-20 是截断的条件分布，不是完整且相互独立的边际分布。

| 入口 | 当前开关行为 |
|---|---|
| `SandboxConfig` / `LogprobScoringConfig` 代码默认 | 关闭 |
| 当前 `configs/runtime.yaml` | `enabled: false`，普通 CLI 随之关闭 |
| CLI `--logprob-scoring` / `--no-logprob-scoring` | 显式覆盖 YAML |
| 当前 `run_simulate.bat` | 评分和预探针均为 0，默认关闭 |
| `probe logprob-scoring` | 即使 YAML 关闭也执行能力探测 |

探针使用标记为 fixture 的合成对话，输出 probe.json，不测量实际病例效果。换端点/模型后重新探测。2026-11-02的六类实测记录覆盖 WAI、CTRS、BDI-II、SCL-90、RRO、PANAS，仅证明当时部署能返回可用位置分布；详见 [方法及记录](notes/logprob_scoring_borrowing.md)。

### 7.4 双击启动脚本

`run_simulate.bat` 顶部可调案例、会谈数、轮数、候选数、并发、评分与探针开关。当前为 3 场、每场 8 轮、3 候选，传输重试预算 6；`run_simulate.bat probe` 只运行探针。

脚本参数会覆盖 YAML 对应项。设置 `LOGPROB_SCORING=0` 会传 `--no-logprob-scoring`，并跳过模拟前预探针；独立 probe 子命令仍可用。批处理保持纯 ASCII，不添加中文字节或 chcp；中文提示通过 Python Unicode 转义输出。

### 7.5 Web 工作台

```bat
run_workbench.bat
```

在浏览器打开 [本地工作台](http://127.0.0.1:8001)。脚本先初始化工作台数据库，再启动 long/short 两个 Worker 和端口 8001 的 API 服务；`stop_workbench.bat` 仅停止本项目 `.venv` 启动的工作台进程。

启动脚本的配置区设置 `PSYCHSANDBOX_SKILL_EXPERIMENT=1`，统一启用“进化试验”；如需关闭，改为 `0` 后重新启动工作台。

手动启动 API 和 Worker 时，未设置该变量则关闭试验。试验使用独立进程和数据库，操作说明见 [技能进化独立试验](docs/workbench/SKILL_EVOLUTION_EXPERIMENT.md)。

工作台可创建自动实验、人工多会谈、检查公开记忆/计划、审核技能版本、比较结果和导出数据。人工会谈受版本与操作 ID 约束，上一场闭环后才进入下一场；技能作者不能自审，模型分数不能自动晋升技能。

会谈区直接显示已提交场数、当前阶段、候选轮数和量表计数，刷新或重连后恢复。轮数分母是上限，提交比例不代表整体耗时；疗程可以提前结束。失败或已停止的历史运行可按原案例、种子、总场数、轮数与 RFT 设置从下一场续跑；页面不使用新实验表单覆盖这些参数，安全暂停或恢复资料缺失时不提供普通续跑。

开发前端时在后端/Worker之外运行 `npm --prefix frontend run dev`，默认开发页面为端口 5173，API 代理至 8000；build 输出到 `src/psychsandbox/workbench/frontend_dist`。仅启动 API 服务不会处理队列任务。详见 [工作台](docs/workbench/README.md) 和 [前端开发](frontend/README.md)。

## 8. 查看评测和完整报告

```bat
psych-sandbox evaluate --run run-xxxxxxxxxxxx
psych-sandbox report --run run-xxxxxxxxxxxx
psych-sandbox visualize --run run-xxxxxxxxxxxx
```

`evaluate` 打印已存整体评分摘要，`report` 打印完整整体督导 JSON；两者都**读取已有结果，不重新调用评判模型**。`visualize` 从数据库结果重建 HTML，可用 `--output alternate.html` 在同一运行目录生成另一报告名。

报告提供概览、会谈对话、可折叠规划/选技依据、自评、摘要与整体指标。0–10 原始症状指标仍可能是越高越重，读取时结合 direction，不能把所有分项一律理解为越高越好。整体督导失败时没有可读的整体报告，不会用假分填补。

### 列出或删除运行

```bat
psych-sandbox runs list
psych-sandbox runs delete --run run-xxxxxxxxxxxx
```

第二条只预览。确认删除才额外使用 `--yes`，按运行编号关联清理所属文件及数据库记录；保留其他运行、共享病例/技能和入口 README。运行锁或未完成删除日志可能阻止操作。不要直接删文件夹后认定数据库记录也已删除。

测试日志清理同样先执行 `psych-sandbox runs clean-tests` 预览，确认后才加 `--yes`。详细规则见 [运行产物](docs/RUN_ARTIFACTS.md)。

## 9. 从 session 边界恢复

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 6 --resume-run run-xxxxxxxxxxxx
```

`--sessions 6` 是目标总场数，不是再追加 6 场；从数据库中已提交会谈边界继续，不恢复尚未完成的一半对话。保留原案例、流派和 seed，RFT 配置也须与原运行兼容。

新逐条目方法不能混用旧总体 logprob 的奖励基线；检测到 RFT 评分方法变化会要求新建运行。safety_hold、已闭合疗程、缺失必要目录/记忆或未完成删除的运行不能作为普通疗程绕过检查继续。

恢复向原目录追加并保留原会谈；仅有数据库而没有必要产物不能保证可恢复。正式备份应同时包含运行目录和共享数据库。

CLI 续跑的目标总场数由 `--sessions` 或当前 YAML 决定，建议显式指定，并保持原轮数、RFT 与评分配置兼容。网页入口从原 `run.json` 读取目标总场数，Worker 从原运行元数据恢复轮数与 RFT 设置；其他评分配置仍须兼容。已选中赢家的 RFT 检查点可避免重复生成和评分，但会后整理步骤尚未逐步缓存，见 [恢复约定](docs/SESSION_RFT.md)。

## 10. 使用 OpenAI 兼容 API

### 10.1 `.env` 中的模型与传输配置

从 `.env.example` 创建本机 `.env`，填写端点及模型。以下是字段说明，不包含可直接使用的密钥：

| 字段 | 用途 |
|---|---|
| `MODEL_API_KEY` / `MODEL_BASE_URL` | 聊天服务认证与 OpenAI-compatible 端点 |
| `CLIENT_MODEL` | 模拟来访者规划/生成角色 |
| `COUNSELOR_MODEL` | 咨询师规划、回复及自评角色 |
| `SUPERVISOR_MODEL` | RFT 候选与整体量表评估 |
| `PROFILE_MODEL` | 数据编译中的有来源抽取，生产转换要求显式配置 |
| `SUMMARY_MODEL` | E.7/E.8 信息提取与合并，E.9 咨询师会后总结和待办判断 |
| `MODEL_STRUCTURED_OUTPUT` | 普通结构化调用的输出格式策略，示例为 auto |
| `MODEL_TIMEOUT_SECONDS` | 请求超时，示例为 180 秒 |
| `MODEL_MAX_TOKENS` | 普通生成输出预算，示例为 8192 |
| `MODEL_MAX_ATTEMPTS` | 瞬时传输重试预算，代码默认 3，示例.env/启动器设 6 |
| `MODEL_MAX_CONCURRENCY` | 同一检出目录内，按端点/模型共享的实际 HTTP 并发上限，默认 5，范围 1–32 |

普通结构化输出可以采用 JSON Schema/JSON object 策略；logprob 路径单独请求位置分布，不发送 response_format 或 tools。传输重试、结构校验重试与 RFT 补采是不同层的预算；SDK自身重试还可能增加实际 HTTP 尝试数。诊断归属于本次运行，不将密钥写入记录。

每次模型传输调用还会在所属 `diagnostics/request_metrics.jsonl` 追加耗时：`queue_seconds` 为槽位排队，`response_seconds` 为实际 HTTP 发送至完整响应，`retry_wait_seconds` 为尝试之间的间隔（包含 SDK/外层退避及请求准备），`overhead_seconds` 为其余开销。各次 HTTP 尝试单列状态与耗时，顶层同时记录成功/失败/取消、重试数及 Token 用量；不记录提示正文或密钥。RFT 的文件位于对应候选诊断目录。该统计不证明真实服务已经获得某个固定加速比。

### 10.2 Temperature 与运行配置

```yaml
temperature:
  client: 0.7
  client_planner: 0.0
  control: 0.0
  counselor: 0.9
  supervisor: 0.0
```

生成温度 0.7/0.9 对齐 PsychAgent 示例配置。评估、规划及记忆的 0 是本项目低随机性选择，不能宣称所有上游首次评估请求都显式设了 0。

`control` 控制咨询师规划、自评、记忆流水线与画像抽取；来访者规划保留独立 client_planner 覆盖。RFT 咨询师使用 `rft.counselor_temperature`（0.9），离散评估使用 judge_temperature（0），logprob 评估使用 `logprob_scoring.temperature`（0）。画像语义修复按 `+0.1/+0.2` 微幅升温退避，其余重试保持所选温度，既有显式覆盖仍有效。

Python seed 主要控制本地流程；温度0也不保证远端模型逐次逐字复现。实验应保存模型、配置、评分方法及实际结果。

### 10.3 条件 embedding 服务

只有技能精确展开后超过阈值才调用 embedding。官方 ChatECNU 同源 HTTPS 服务可按网关规则继承聊天密钥及默认向量模型；其他端点应分别设置 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`，不会跨主机/端口/路径自动传递聊天密钥。

网关按当前供应商限制拆批：ChatECNU最多32条输入，并采用8192字符预算进行保守分批；单条超限报错，不静默截断。.env 中的说明可能滞后于代码，实际约束以网关实现为准。原始技能树中的 `.pt` 缓存不参与当前检索。

## 11. 运行自动化测试

```bat
python -B -m pytest -q
```

使用 Python 3.11+ 与 `.[dev]`，全部 `tests/` 通过才完成代码或资源变更。测试包含模型请求契约、五流派隔离、披露证据、记忆、会谈恢复、RFT安全/选优、逐条目位置分布、并发审计、工作台与导出等。

测试按次写入 `runs/tests/<时间__pytest__编号>`，结束默认清除本次目录。保留现场可在 CMD 中先执行：

```bat
set PSYCHSANDBOX_KEEP_TESTS=1
python -B -m pytest -q
```

前端代码变更另执行 `npm --prefix frontend test`、`npm --prefix frontend run lint`、`npm --prefix frontend run build`。离线测试不调用真实模型，不替代供应商探针或人工浏览器验收；历史通过数只能作为对应日期的证据。

## 12. 数据和存储边界

| 内容 | 存储与可见性 |
|---|---|
| 原始病例与技能 | data/与assets/，保留来源；完整私有病例不进入咨询师视图 |
| processed与抽取缓存 | data/processed下，可重建、被Git忽略 |
| 允许记忆 | known_background、session_recaps、last_homework、checklist |
| 正式仿真 | runs/runtime中的独立目录，共享psychsandbox.sqlite3按run_id索引 |
| 候选及评分审计 | 对应运行的候选/诊断产物，不进入落选分支的正式记忆 |
| 接口探针 | 独立目录的run.json/probe.json，不写正式仿真记录 |
| 测试产物 | runs/tests中的本次隔离目录 |
| 工作台状态 | 工作台数据库、事件、任务与导出审计；并非另一份私有画像投喂通道 |

`full` 与 `recap_window` 控制跨场记忆的读取范围。本场对话始终按完整消息列表传入。会谈结束时，咨询师在 E.9 总结中根据完整对话判断待办是否完成，并用 `item_updates` 返回已有条目的 ID、明确状态及判断依据。程序按 ID 应用这些判断，`completed_items` 作为本场归档。详见 [记忆](docs/MEMORY.md)。

生成产物、凭据、虚拟环境、字节码与下载资源按 `.gitignore` 管理，不提交 Git。Web 的 SFT/DPO 每次导出新目录，SFT标记上下文重建，原文未自动脱敏；DPO只取同一已提交安全批次共同前缀后的首个差异回复，失败候选不是自动负例。

## 13. 与 PsychEval、PsychAgent 的关系

### PsychEval

提供病例事实、原生流派结构、技能及评测资源。本项目在固定来源基础上编写运行时适配、证据披露、记忆权限和持久化；上游离线评测客户端不等于已公开的完整来访者生成器。

### PsychAgent

其公开记忆、技能组织、会谈候选探索和固定奖励统计为实现提供参考。当前沙盒有独立的权限、结构化输出和审计约束；公开的采样/选优代码不代表已经复现论文中的参数训练、完整技能演化或实验结果。

logprob 额外借鉴线性表征论文式8及质量门，仅采用评分方法，没有迁移激活引导、模型权重或内部表征控制。第三方许可、固定提交和方法归属见 [NOTICE](NOTICE.md) 与 [许可汇总](THIRD_PARTY_LICENSES/README.md)。

## 14. 后续阶段怎么做

### 后续流派与督导反馈闭环

新增流派需要独立病例契约、技能树、阶段策略和评估映射，不能仅改标签。若研究外部评分反馈驱动规划，应设为独立实验条件；当前基线继续由咨询师自评和纵向信号形成下一计划。

### 第三阶段：经验积累和自进化

工作台已有技能快照、提案、回放/审核、发布/回滚与受控导出，以及隔离的技能提取与对比试验。试验版候选标为 `experimental-unreviewed`，不会修改原始资产或正式活动发布指针。专家批准和模型训练仍需独立完成；后续需明确训练数据质量、案例划分、版本归属和回退门，不能把审计候选直接当成现成偏好训练集。

### 正式实验

优先做离散条目与连续条目的固定上下文配对，记录评分失败、概率质量、排名变化、成本和延迟；然后分层比较记忆、技能、会后自评、披露控制与候选数。多病例、多次API重复及专家盲评分别报告，不用单一总均值掩盖失败。计划与文献见 [路线](docs/ROADMAP.md)、[研究资料](docs/research/README.md)；旧汇报见 [历史归档](docs/archive/README.md)。

## 15. 常见问题

### CMD 提示“不是内部或外部命令”

确认激活的是当前 `.venv`，并完成可编辑安装。也可直接用 `.venv\Scripts\python.exe -B -m psychsandbox`，避开失效的命令入口。迁移后按第5.3节检查实际导入路径。

### 提示找不到案例或 processed 数据过期

先确认当前目录/--root，再执行五流派 extractive 转换。检查案例编号前缀；不要手动把旧缓存的版本号改成新值来绕过来源验证。

网页病例接口在 processed 无效时返回 503 和修复说明；这表示病例库不可用，不能当作空列表。转换失败时查看本次 `run.json`、`progress.jsonl`、诊断和 staging 路径；旧 processed 与共享运行数据库应保留。

### 提示缺少密钥或 PROFILE_MODEL

检查本机.env是否填写对应角色和端点，且不是在其他检出目录运行。画像转换要求显式PROFILE_MODEL；来访者、咨询师、督导和摘要角色也应按.env.example配置。

### API 返回的不是合法 JSON

普通结构化请求最多生成三次：首次输出、一次修复、仍失败则按原始输入重新生成。重试沿用 `MODEL_STRUCTURED_OUTPUT` 为该模型选定的格式和原温度，不强制切换到 `json_schema`。达到输出 token 上限或超过修复输入长度预算时，直接按原始输入重新生成，不回灌截断的输出尾部。所有结果仍须通过完整 schema 校验，失败保留在本次 diagnostics。logprob 路径不做文本修复，非法 JSON 或不完整条目会明确失败，不能靠删除条目后取平均继续评分。

普通请求会在系统提示中列明顶层允许/必需字段，要求嵌套键名和枚举值保持 schema 原样、补全必需字段并正确闭合 JSON。若校验错误全部来自值为 `""` 的额外字段，网关按校验路径移除这些字段，再校验完整对象。E.9 总结另支持两种无损格式修复：将字符串数组字段的单个字符串原文包为一项；将错放到 `goal_assessment` 的已知同级字段移回 schema 指定位置，仅在正确位置不存在或内容完全相同时处理。冲突内容、未知的非空或 `null` 字段、缺失字段及其他类型错误仍需模型修复，诊断保留原响应和修复路径。

E.9 摘要会尝试修复已识别的对象闭合前多余逗号和引号。修复后校验整个摘要，诊断保留原响应和修复原因。

### 端点有普通聊天能力，却不能进行 logprob 评分

普通结构化输出与位置logprobs是不同能力。运行probe检查完整条目分布；不支持时用--no-logprob-scoring或YAML enabled:false明确选离散路径，不会自动回退。开启前读取 [方法限制](notes/logprob_scoring_borrowing.md)。

### YAML 已关闭评分，双击脚本为什么仍调用探针

仓库当前 `LOGPROB_SCORING=0`、`PROBE_LOGPROB=0`，普通启动不会预探测。若仍发生探针调用，检查实际运行的脚本路径、本机修改和 `probe` 参数；预探针只在两个开关都为 1 时执行，独立 `run_simulate.bat probe` 始终主动探测。显式 CLI 参数优先于 YAML。

### 恢复运行提示评分方法或 RFT 配置不一致

旧总体评分和新逐条目评分不能共享RFT奖励基线。保留旧结果，使用新运行做比较；不要手工改快照或删除候选文件绕过恢复检查。

### Web 页面能打开，但任务一直排队

确认long/short Worker均已启动；仅API服务或前端开发服务器不执行队列任务。查看工作台日志和任务状态，按文档恢复，不通过直接删数据库解锁。

### 中文在 CMD 中乱码

尝试支持UTF-8显示的终端，并检查重定向输出的解码方式；批处理本身继续保持ASCII，不插入中文注释或chcp。必要时通过PowerShell直接调用当前虚拟环境解释器。
