# 基于 PsychEval/PsychAgent 的心理咨询多智能体研究沙盒

本项目是一个面向大学生创新创业训练、智能体研究和心理咨询对话评测的实验系统。它把 PsychEval/PsychAgent 中 BT、CBT、HET、PDT、PMT 五流派的多会话案例、人物画像和咨询技能转换为可运行的多智能体环境，让“模拟来访者—咨询师—督导师”能够连续完成多次会谈，并记录记忆、技能选择、状态变化、风险判断和督导评分。

> 本项目仅用于非商业教学与科研，不是真实心理咨询或医疗服务。禁止接入真实求助者，不用于诊断、治疗、药物建议或现实危机处置。系统中的情绪状态、人格参数和自动评分都是仿真变量，不是经过临床验证的量表。

## 快速开始

本机检出目录为 `D:\study\大创\project\psych_sandbox`（2026-09 从 `D:\0test\psych_sandbox` 移动到此路径；移动检出目录后须重做可编辑安装检查）。已有项目无需重新 clone；先阅读 [迁移后的安装检查](#53-迁移后的安装检查powershell)。后文安装与运行示例除另有标注外使用 CMD。

以下命令适用于 Windows CMD。运行前请先根据 `.env.example` 配置 API 密钥、接口地址和各角色模型：

```bat
git clone https://github.com/AgClNaClO/psych_sandbox.git
cd psych_sandbox
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
pytest -q
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3
```

仓库已包含原始病例 `data/<therapy>/`、`assets/` 和 `prompts/`，不需要先下载数据。但生产 `simulate` 还要求一次性的 schema-v4 缓存 `data\processed\psycheval`（已被 Git 忽略；缺失或过期时命令会明确提示，见 6.2 节的必需转换步骤）。`data fetch` 用于重新获取官方 PsychEval 原始数据。

仿真结束后，终端会输出 `run-xxxxxxxxxxxx` 格式的运行编号，并自动生成 `runs\runtime\时间__案例ID__run-xxxxxxxxxxxx\report.html`。该报告可直接在浏览器中离线打开；也可以随时重新生成：

```bat
psych-sandbox visualize --run run-xxxxxxxxxxxx
```

测试与实际运行分别保存在 `runs/tests/` 和 `runs/runtime/`，每次建立带时间和唯一编号的目录。`pytest` 结束（无论成败）默认自动删除该次调用目录，如需保留失败现场可设置 `PSYCHSANDBOX_KEEP_TESTS=1`；也可用 `psych-sandbox runs clean-tests` 手动清理测试日志。目录结构、续跑与清理方式见 [运行文件说明](docs/RUN_ARTIFACTS.md)。

## v0.3.0 更新重点

- 将运行时扩充为行为（BT）、认知行为（CBT）、人本—存在（HET）、心理动力（PDT）和后现代（PMT）五流派；每个流派使用独立病例字段、技能树、概念化重点和专属评估指标。
- 新增 CBT 与人本—存在取向的独立 `TherapyProfile`，避免混用不同流派的数据与评估标准。
- 将模拟来访者拆分为内部策略规划和自然语言表达两个阶段，增加语义原子门控、阻抗、提前披露防护及对话循环修复。当前来访者提示词版本为 `psycheval_patientact_v5`。
- 修复来访者披露链路：规划器选择的事实才会进入语言模型；本轮声称披露的事实必须能从实际台词核验；跨会谈只复用已经说过的证据片段，不把完整隐藏层写入记忆。
- 将同类/跨类别候选统一进行歧义消解，并将公开主诉从私密泄漏匹配中排除；保留确定性近似匹配、重试和安全替代回答作为纵深防护。
- PatientAct 互动先验只从 PsychEval 有明确来源的流派字段派生；新画像不再生成无来源的 Big Five 或依恋维度，PDT 之外也不会为凑齐结构而强制生成完整 CCRT。
- 合入 `patientact-client-upgrade-v4` 的 E.7/E.8/E.9 会后记忆流水线、整体督导与存储更新。
- 将咨询师升级为 API 驱动的 `evidence_vector_retry_v2`：先规划，再查询技能并观察结果，最后执行回复；技能选择要求公开适用依据；原子候选过多时才使用向量筛选，差查询最多纠错一次。
- 新增 RFT 候选的 PsychEval 量表评分（RFT 奖励）和跨 session 纵向趋势分析。
- 每个 session 结束后由咨询师模型核对目标与对话证据；未达目标时重新选择策略、目标和元技能，纵向进度信号继续负责阶段推进与安全保持，RFT 候选评分不直接驱动计划。
- 新增单文件 HTML 可视化报告，集中呈现运行流程、状态曲线、整体督导评估、摘要与纵向判断、信息披露、安全检查和完整对话（该版式已在后续更新中改为概览页 + 每场会谈独立页，见下文）。
- 自动化测试覆盖多会话连续性、SQLite 恢复、信息隔离、安全分流、 API 结构化输出、失败状态持久化与 CLI 进度反馈。
- 新增可选整场会谈多候选、统一 PsychEval 量表评分与选优；仅胜出会谈进入会后整理和正式轨迹。默认关闭，不包含权重训练，详见 [会谈 RFT](docs/SESSION_RFT.md)。

## v0.3.0 之后的更新

- HTML 报告改为“概览页 + 每场会谈独立页”：逐轮规划/决策、技能查询记录、来访者模拟决策摘要和会后自评改为对话上方可折叠的内联卡片；原先独立的“运行过程 / 来访者状态趋势 / 纵向判断”板块不再渲染，这些数据仍保存在 `result.json`、SQLite 和 `trajectory.jsonl` 中。
- 新增 [记忆结构说明](docs/MEMORY.md)，记录当前咨询师记忆的三层结构、写入者、咨询师读取范围与已知限制。
- 本机检出目录由 `D:\0test\psych_sandbox` 移至 `D:\study\大创\project\psych_sandbox`，本文档与 `docs/` 下的路径、安装检查和提示词/测试计数同步更新。

## 1. 项目要解决什么问题

普通大模型通常只能完成单轮或短期心理咨询对话，存在以下问题：

- 不记得上一次咨询谈过什么，容易重复提问或前后矛盾。
- 只生成自然语言回复，无法解释本轮选择了什么咨询技能。
- 模型可能提前知道来访者尚未披露的经历，造成隐藏信息泄漏。
- 缺少独立督导师，无法形成“咨询—评分—反馈—调整”的闭环。
- 遇到自伤、他伤等高风险表达时，仍可能继续进行普通咨询练习。
- 高质量会谈经验不能沉淀为可回放数据、技能版本或训练样本。

本项目针对这些问题实现以下闭环：

```text
五流派 PsychEval/PsychAgent 案例
        ↓
模拟来访者 ↔ 对应流派咨询师
        ↓
安全检查 + 状态更新 + 信息披露门控
        ↓
会后摘要 + 跨 session 记忆 + 下一次计划
        ↓
RFT 候选评分（开启 RFT 时）+ 多会话后整体督导（PsychEval 量表）
        ↓
SQLite、JSONL 轨迹和后续经验池
```

## 2. 当前完成情况

“最小可运行沙盒”的代码和 API 调用链已经完成：

- 当前直接加载 341 个五流派原始案例：BT 43、CBT 148、HET 50、PDT 50、PMT 50。
- 加载 677 个元技能和 4481 个原子技能，保留 PsychAgent 原始技能 ID 并增加稳定流派前缀。
- 可选转换器按案例进行确定性训练集、验证集和测试集划分。
- 将 PsychEval 原始字段转换为带来源字段的结构化 5Ps 个案概念化。
- 支持五个独立 `TherapyProfile`，病例、阶段技能和评估量表不会跨流派混用。
- 支持单个案例连续运行 6–10 个 session，并验证状态与记忆连续性。
- 支持从 SQLite 中最近一个 session 边界恢复运行。
- 咨询师只能读取已解锁信息，不能读取完整来访者档案。
- 来访者语言生成器只能读取静态画像、本轮经规划器选中的允许记忆，以及过去已经实际说出的证据片段；完整私有画像仅进入内部状态规划器。
- 支持“反应—行为—阻抗—回答”的两阶段来访者生成、blocked 敏感话题信号和提前披露防护。
- 支持来访者话题边界识别、咨询师重复回复检测和互动修复，避免固定追问形成对话循环。
- 每轮记录 Reasoning 摘要、Planning 步骤、Action、Observation、实际技能、结构化决策、状态变化和安全结果。
- 每个 session 生成咨询师目标自评、必要的策略再规划、摘要、纵向趋势和下一次计划；开启 RFT 时另做候选评分与选优。
- 每次 CLI 仿真自动生成单文件 HTML 报告：一个概览页加每场会谈的独立页面，页内对话上方可折叠查看该轮的规划与决策、技能查询记录、会后自评和 E.9 临床摘要，并汇总整体督导评估、披露/安全记录和完整对话。
- 生产运行统一使用 OpenAI-compatible API，不提供离线或本地模型后端。
- 自动化测试覆盖 API 契约和主要控制流程。
- 测试套件当前为 386 项（2026-09-22 用 `pytest --collect-only -q` 统计）。最近一次记录的全量通过为 2026-08-28 的 383 项（173.23 秒），覆盖统一删除与 ChatECNU 配置；本次路径与文档更新只做了收集计数和两个记忆相关单测，未重跑全量套件，也未调用真实模型 API，因此不据此声称模型质量或真实接口联调通过。
- 三随机种子、30 案例正式实验和人工评审仍需要在后续实验阶段完成。

## 3. 项目中的三个智能体

### 3.1 模拟来访者

来访者采用两个严格分离的视图。内部状态规划器可以读取完整私有画像，用于判断本轮反应、行为、阻抗和信任变化；自然语言生成器只能看到：

- 基本背景和当前问题。
- 语言习惯；PsychEval 未提供人格证据时使用中性仿真先验，不再按案例 ID 随机生成。
- 情绪、联盟信任、话题准备度、疲劳和关系破裂状态。
- 当前轮通过联盟信任与话题准备度门控的渐进式记忆层。
- 过去会谈中已经实际说过的证据片段；这些旧记忆可以自然回顾，但不能据此扩写新细节。
- 不含秘密正文的 blocked 话题信号。
- 同类事实无法精确区分时的歧义信号。
- 咨询师上一轮回复和近期对话。

生成器看不到未授权成长经历、特殊情境、完整 CBT 概念化材料或咨询师内部 session 目标。
事实门控先找候选，再由内部规划器选择真正相关的事实；跨类别候选如果无法唯一定位，来访者会请求具体化而不是同时披露。生成器返回的 `disclosed_fact_ids` 还要与实际台词核验，只有找到文本证据的事实才会解锁，记忆中保存的也是本轮说出的片段而不是完整私密档案。

回答经过确定性提前披露检查；检查会排除公开主诉和已说过的旧记忆，并对相近改写做近似匹配。首次失败会重试，仍失败则使用符合当前行为信号的安全替代回答。该检查是纵深防护，不等同于完整语义理解；最终的多会话语义一致性仍由 PsychEval 整体督导和人工评审承担。

PatientAct 参数采用“有证据才派生”的原则：PsychEval 原始字段先编译为可追溯的 `EvidenceNode`，再投影为原子 `DisclosureItem`、带来源的 5Ps 和按流派构建的 `InteractionPrior`。新画像不生成 Big Five 或依恋类型；PDT 可从核心冲突、客体关系和反应模式形成 CCRT-like 结构，其他流派只保留其证据足以支持的互动倾向。状态在会谈内允许非线性波动，信任变化下一轮生效；跨会谈按配置系数保留信任并恢复短期状态，避免 6–10 次会谈中疲劳只能单向累积。

### 3.2 多流派咨询师

当前提供 BT、CBT、HET、PDT、PMT 五个适配器。咨询师智能体只能看到：

- 来访者已经明确说出的信息。
- 已解锁档案。
- 之前 session 的摘要、目标、作业和未解决问题。
- 当前 session 目标。
- 当前流派与阶段的元技能目录，以及咨询师主动查询后返回的原子技能 Observation。

咨询师看不到完整档案、未披露成长经历和其他隐藏事实。每轮先由 API 模型输出简短、可审计的 Reasoning 摘要、分步计划和 Action；程序按元技能 ID 查找原子技能并返回 Observation；模型再自主选择实际技能、策略和最终回复。元技能提示与原子技能完整路径在加载时派生，原始技能树不变。超量候选使用独立 embedding 接口筛选；候选不适合或查询无效时最多纠错一次并排除旧组。配置、适用依据和审计字段详见 [技能选择说明](docs/SKILL_SELECTION.md)。这里不保存或展示模型的私密逐 token 思维链。

### 3.3 督导师

督导师是**整体督导**（`PsychEvalSupervisor`）：在整条多 session 轨迹全部结束后运行一次，与 PsychEval §5 对齐，读取完整档案与可见对话，给出 Counselor-Level（临床胜任力）与 Client-Level（仿真保真度）评分，产出 `HolisticEvaluationReport`。它只评分、不规划下一 session。与之配套的评估组件包含以下三部分：

- **RFT 候选评分（LLM-as-Judge，奖励信号）**：`SessionSupervisorEvaluator` 仅在开启 RFT 时被 `SessionRolloutEvaluator` 调用，用同一套 `prompts/eval` PsychEval 量表给每个候选整场会谈打分，产出 `SessionEvaluationReport`（存放在候选的 `assessment`，不写入已提交 session）。Counselor-Level 使用 WAI、HTAIS、RRO、`custom_dim` 及流派专属量表（BT→MITI；CBT→CTRS；HET→TES；PDT→PSC；PMT→EFT-TFS），Client-Level 使用 SCL-90、PANAS、RRO、SRS 及流派专属量表（BT→STAI；CBT→BDI-II；HET→CCT；PDT→IPO；PMT→SFBT）。该报告只作为 RFT 候选排名信号与审计记录（对应 PsychAgent §3.3 的奖励模型），不是临床督导。
- **规则安全/披露门控**：`SessionSafetyGate` 做确定性检查——咨询师是否在来访者披露前引用隐藏事实（`hidden_information_leakage`），以及高风险场景是否停止普通干预并连接现实支持（`ethics_and_safety`）。这两项只做 RFT 候选准入/拒绝与轨迹安全标记，不参与评分。
- **量表对齐 PsychEval**：RRO 是单个 24 条目量表，按 4 因子（Client/Counselor × Realism/Genuineness）分解并对条目 {2,7,16,17,18,19,24} 反向计分，咨询师侧与来访者侧各取两个因子均值；`custom_dim` 是单个咨询师侧量表，聚合 Ethics、Interaction、Intervention、Perception 四个 criteria 为一个分数。各量表按其官方原始条目范围（WAI/HTAIS/`custom_dim`/EFT-TFS/MITI/IPO/PANAS 为 1–5，TES 为 1–7，PSC/CTRS 为 0–6，SCL-90/SRS/STAI/SFBT 为 0–4，BDI-II 为 0–3，CCT 为 0–2）归一化为 0–10 原始分（症状量表 SCL-90/BDI-II/IPO 越高越重，不取反；PANAS 按正/负情绪平衡公式计算）；原始范围记录在 `Instrument.scale`。

RFT 候选评分与规则门控不参与下一 session 规划（规划由 `PlanBuilder` 结合咨询师会后自评与纵向进度信号完成）；整体督导只给一次、RFT 候选评分留在候选审计记录，不会用一个总分覆盖具体证据和违规项。

## 4. 核心架构

```text
src/psychsandbox/
├── domain/          Pydantic 统一领域模型
├── datasets/        PsychEval/PsychAgent 原始数据适配与案例仓库
├── agents/          来访者、规划/ReAct/会后自评咨询师与督导智能体
├── client_simulation/ 来访者激活、渐进披露、反应、语言和状态的统一接口
├── therapies/       治疗流派定义、概念化焦点与阶段目标
├── runtime/         编排、安全、披露、状态、记忆、反馈计划和 SQLite
├── skills/          技能注册、精确目录查询与按需向量筛选
├── evaluation/      每 session 量表评分、安全门控、纵向评测与整体督导
├── visualization/   无外部依赖的 SVG/HTML 运行报告
├── experience/      通过安全门槛的经验池
├── evolution/       技能审核、晋升、弃用和回滚状态机
├── training/        SFT 与 DPO 数据导出
├── model_client.py  OpenAI-compatible API 网关
└── cli.py           可选数据刷新、案例、仿真和报告命令
```

跨会话记忆的分层结构、写入者、咨询师读取范围与当前限制见 [记忆结构](docs/MEMORY.md)。

### `src` 与 `tests` 分别负责什么

- `src/psychsandbox/` 是可安装的生产包：定义领域模型、数据适配、API 智能体、运行时编排、评测、持久化和可视化。`psych-sandbox` CLI 最终进入这里；生产仿真只接受真实 OpenAI-compatible API 网关。
- `tests/` 是验证层：用 `tests/deterministic_gateway.py` 提供离线、可重复的 API 测试替身，覆盖控制流、结构化输出、五流派隔离、披露/安全、连续 session、恢复和报告。测试替身不能由生产 CLI 选择，也不代表真实模型质量。

二者共享 `src` 中的公开契约，但职责方向相反：`src` 实现行为，`tests` 证明关键边界没有被破坏。

主要运行流程如下。开启 RFT 时，第 2 步在隔离候选中分别完成，先评分选优，再只对赢家执行第 3 步。

1. `prepare_session`
   - 读取上次摘要、已解锁档案、风险历史和咨询师会后自评。
   - 从 PsychEval 全局计划确定当前阶段和目标。
   - 根据疗法、阶段和审核状态构造技能目录，不计算相关性分数。
2. `run_turn`
   - 对来访者输入进行安全检查。
   - 咨询师模型先做 Reasoning 摘要与 Planning，自主决定是否执行技能查询 Action。
   - 目录按有公开依据的元技能 ID 展开原子技能；超过配置阈值才使用向量筛选。
   - 咨询师模型检查候选与适用依据，选择原子技能和策略；仅差查询可纠错一次，旧候选组排除。
   - 对咨询师输出再次进行安全检查。
   - `ClientSimulator` 在一个接口内完成事实激活、全候选歧义处理和渐进披露。
   - 内部规划器依次选择情绪反应、行为、可选阻抗形式和信任变化；blocked 不再强制等于防御。
   - 只有内部规划器从候选中选中的事实才进入语言生成器；语言生成器另可读取已披露证据记忆。
   - 回答通过事实 ID 授权、台词证据核验和提前泄漏检查后，才更新解锁档案。
   - 更新联盟信任、话题准备度、疲劳和关系破裂状态并保存审计轨迹；下一 session 开始时仅恢复部分短期疲劳，不重置联盟、困扰、希望或话题准备度。
3. `consolidate_session`
    - 运行规则安全/披露门控（`SessionSafetyGate`），只做准入与安全标记、不评分。
    - 计算状态差值、相邻会谈趋势和阶段动作。
    - 运行 E.7/E.8/E.9 记忆流水线：提取实际披露信息、门控合并演化档案并生成有证据的摘要。
    - 整理跨 session 记忆：追加本场摘要与临床摘要，更新作业、未尽议题、风险与关系记录、已使用技能和末段来访者话语。
    - 咨询师模型评测本次目标是否达到（读取刚合并的记忆）；未达到时生成改进项、修订策略、下次目标和元技能方向。
    - 将咨询师再规划与纵向阶段动作合并为下一次计划，不依赖督导评分。
    - 保存 SQLite 和 JSONL 轨迹：`memories` 保存该会谈结束后的记忆，轨迹另存会话前的记忆副本 `Trajectory.memory_before`。
4. 全部 session 结束后，`PsychEvalSupervisor` 用官方量表对整条轨迹做一次整体督导，保存 Counselor-Level 与 Client-Level 结果；CLI 再生成可折叠查看逐轮过程的 HTML 报告。

## 5. Windows CMD 环境准备

本节除标为 PowerShell 的迁移检查外，命令均使用 Windows CMD 语法。

### 5.1 前置软件

需要安装：

- Python 3.11 或更高版本。
- Git。
- 推荐使用支持长路径的 Windows 10/11。

先打开 CMD，进入项目目录：

```bat
cd /d D:\study\大创\project\psych_sandbox
```

确认 Python 和 Git：

```bat
python --version
git --version
```

### 5.2 创建并激活虚拟环境

```bat
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

以后每次重新打开 CMD，只需要执行：

```bat
cd /d D:\study\大创\project\psych_sandbox
call .venv\Scripts\activate.bat
```

如果安装成功，下面的命令应显示 CLI 帮助：

```bat
psych-sandbox --help
```

如果 CMD 找不到 `psych-sandbox`，可以使用完全等价的模块形式：

```bat
python -m psychsandbox --help
```

### 5.3 迁移后的安装检查（PowerShell）

复制或移动 `.venv` 不保证环境可移植；此前遇到过可编辑安装的 `.pth` 仍指向旧目录的问题。当前检出目录下，`pytest` 依据 `pyproject.toml` 的 `pythonpath = ["src"]` 直接收集并运行测试（收集计数见第 2 节），`.venv\Scripts\` 中已有 `psych-sandbox.exe`；直接用未安装本项目的解释器执行 `python -m psychsandbox` 会报 `No module named psychsandbox`，此时先完成可编辑安装。新环境或再次移动检出目录时，重新安装并核对实际导入位置：

```powershell
Set-Location -LiteralPath 'D:\study\大创\project\psych_sandbox'
.\.venv\Scripts\python.exe -B -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -B -c "import psychsandbox; print(psychsandbox.__file__)"
.\.venv\Scripts\python.exe -B -m psychsandbox --help
```

导入位置应在 `D:\study\大创\project\psych_sandbox\src` 下。安装需要可用的依赖源；若缺少构建依赖，不要用 `--no-build-isolation` 跳过准备。若解释器本身不能启动，应使用本机 Python 3.11+ 重建环境并重新安装依赖。旧 `pip.exe`、`pytest.exe`、激活脚本可能保留原路径，移动目录后优先直接使用 `.venv\Scripts\python.exe -m pip/pytest/psychsandbox`，不依赖这些旧入口。

CLI 默认以当前目录作为项目根目录；在其他目录调用时，将 `--root D:\study\大创\project\psych_sandbox` 放在 `simulate`、`cases` 等子命令之前。清理过的运行编号不再可查，后续运行会在当前项目的 `runs/runtime/` 下建立新目录。仅手动删除文件夹不会清除数据库，需用统一删除入口同步清理。

## 6. 数据资源与可选刷新

项目默认直接读取以下已随仓库提供的资源：

```text
data\cbt\                 CBT 原始案例
data\het\                 人本—存在取向原始案例
data\bt\                  行为取向原始案例
data\pdt\                 心理动力取向原始案例
data\pmt\                 后现代取向原始案例
assets\profiles\          Psych-new sample/rft 画像副本（当前仅作来源对照）
assets\skills\sect\       分流派、分阶段技能树
prompts\eval\             督导量表提示词（46 个，由当前代码加载，用于每 session 与整体督导）
prompts\counselor\        咨询师规划/执行/会后自评生成提示词（Jinja2 模板）
prompts\simclient\        两阶段模拟来访者（规划、台词）生成提示词（Jinja2 模板）
prompts\memory\           E.7 提取、E.8 合并、E.9 摘要生成提示词（Jinja2 模板）
prompts\client\           dialogue.jinja2 参考模板，未接入生产
```

当前运行时注册 BT、CBT、HET、PDT、PMT 五个适配器。`data\integrative` 仍作为资源保留，但在具有独立技能树和评估标准之前不会冒充其中任一流派。

提示词目录共 55 个提示词资产（另有 1 个 `README.md`），其中 54 个有当前文件加载链调用点：46 个 `prompts/eval` 量表，另有 8 个生成模板（`prompts/counselor/`、`prompts/simclient/`、`prompts/memory/`）以 **Jinja2 模板**存放，由 `psychsandbox/prompts.py::render_prompt` 在每次模型调用时渲染，并按 Pydantic schema 解析输出。`prompts/client/dialogue.jinja2` 仅作参考，未进入生产加载链。完整映射和接入要求见 [prompts/README.md](prompts/README.md)。

### 6.1 可选：重新下载官方数据

```bat
psych-sandbox data fetch psycheval
```

数据下载到：

```text
runs\runtime\时间__data-fetch__编号\external\psycheval\
```

下载器使用 PsychEval 官方仓库，并固定到提交：

```text
e04df535749e5bca76fcc45d9a85f3f46a082d91
```

### 6.2 必需：编译 schema-v4 五流派 processed 数据

```bat
psych-sandbox data convert --therapy all --atomizer extractive
```

schema-v4 运行时缓存是五流派原子替换单元，因此生产转换要求 `--therapy all` 和 `--atomizer extractive`，并要求显式配置 `PROFILE_MODEL`，不会回退 `CLIENT_MODEL`。转换先按每流派 5 个固定样本执行 pilot，再对成长经历、`language_features`、`core_demands` 和 5Ps 候选字段执行逐字 span 抽取。失败项保留原文并标记 `needs_review`；pilot fallback 超过 5% 时整批中止。

转换结果作为可重建缓存写入：

```text
data\processed\psycheval\
├── all.jsonl
├── train.jsonl
├── validation.jsonl
├── test.jsonl
├── skills.json
├── compilation_audit.json
├── by_therapy\<流派>\atomization_audit.jsonl
└── manifest.json
```

转换先在 `data\processed` 下写入独立 staging 目录，只有 schema、341 案例、五流派计数、来源 ID 和源摘要全部通过验证后，才原子替换上述目录。`manifest.json` 还保存抽取模型、prompt 版本、fallback/needs_review 与 5Ps coverage 统计。该目录是可重建且被 Git 忽略的缓存，不提交到仓库。

正常运行必须存在有效的 schema-v4 processed 数据。案例仓库不会升级旧 processed，也不会从原始 JSON 即时编译或覆盖；缺失或不匹配时会提示显式执行转换命令。

### 6.3 检查案例

```bat
psych-sandbox cases list --therapy cbt
```

正常情况下会看到 `psycheval-cbt-001` 到 `psycheval-cbt-148`。也可以将 `cbt` 替换为 `bt`、`het`、`pdt` 或 `pmt`。

## 7. 运行 API 仿真

运行前必须配置第 10 节列出的 API 环境变量，以及可能触发的独立 embedding 接口。 `configs/runtime.yaml` 默认是 3 个 session、每场最多 8 个咨询师轮、seed 42、RFT 关闭； CLI 显式参数覆盖 YAML，修改 YAML 后下一次启动即生效。

运行一个案例的 3 次连续咨询：

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3
```

限制每个 session 最多 4 轮：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --max-turns 4 ^
  --seed 42
```

输出完整 JSON：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --json
```

运行完成后，终端会显示 `run-xxxxxxxxxxxx` 形式的运行编号，请保存该编号；结尾还会输出一行“整体督导：Counselor=… Client=…”，为 PsychEval 对齐的多会话后量表评分。

### 可选：整场会谈多候选与 RFT 选优

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --rollouts 3 --rollout-concurrency 2 --judge-concurrency 2
```

每个 session 从相同会前状态生成完整候选会谈，经安全检查、去重和 PsychEval 量表评分后，只将胜出会谈推进记忆与下一会谈。默认关闭，避免普通仿真自动增加调用成本；`--no-rft` 或 `--rollouts 1` 可关闭。启用后的默认候选数为 3，生成/评分并发仍为 2，至少 2 个不同合格候选才能选优。 CLI 现在会读取 `configs/runtime.yaml`，显式命令行参数再覆盖 YAML。评分规则、失败处理和目录结构见 [会谈 RFT](docs/SESSION_RFT.md)。这里只实现采样、评分与选优，没有权重训练。

## 8. 查看评测和完整报告

查看每个 session 的 PsychEval 量表评分：

```bat
psych-sandbox evaluate --run run-xxxxxxxxxxxx
```

查看包含证据、理由和违规项的完整 JSON 报告：

```bat
psych-sandbox report --run run-xxxxxxxxxxxx
```

生成或重新生成过程与结果可视化：

```bat
psych-sandbox visualize --run run-xxxxxxxxxxxx
```

默认输出为 `runs\runtime\时间__案例ID__run-xxxxxxxxxxxx\report.html`。报告是可离线打开的单文件页面，不上传数据：顶部概览页给出运行参数、整体督导评估与各会谈入口，每场会谈是可切换的独立页面，包含 E.9 临床摘要、咨询师会后自评、可折叠的逐轮规划/决策与技能查询记录、披露与安全检查结果，以及完整对话。`simulate` 默认自动生成该报告；如只需要 JSON/SQLite，可传 `--no-visualization`。纵向进度和状态差值仍写入 `result.json`、SQLite 与 `trajectory.jsonl`，当前报告不单独渲染状态曲线。

开启 RFT 时，报告另含候选状态、分数、引用依据与胜出者，并链接到各候选原始 JSON。

默认数据库和轨迹位于：

```text
runs\runtime\psychsandbox.sqlite3
runs\runtime\时间__案例ID__run-xxxxxxxxxxxx\trajectory.jsonl
```

SQLite 保存案例、运行、session、turn、记忆、整体督导和完整轨迹。 JSONL 适合后续统计分析、经验回放和训练数据转换。

### 列出或删除运行

```bat
psych-sandbox runs list
psych-sandbox runs delete --run run-xxxxxxxxxxxx
psych-sandbox runs delete --run run-xxxxxxxxxxxx --yes
psych-sandbox runs clean-tests
psych-sandbox runs clean-tests --yes
```

`runs delete` 第二条只读预览，第三条才确认永久删除该运行目录及数据库关联记录，包括 RFT 候选。不需要 API 密钥，不删除其他运行或共享案例/技能；拒绝被运行锁占用的任务。目录已手动删除时，也能清理剩余数据库记录。中断后保留 `.deletions/<run_id>/deletion.json`，同一命令可重试。预览范围、运行锁、缺失目录和失败语义见 [统一删除说明](docs/RUN_ARTIFACTS.md#按运行编号统一删除)。

`runs clean-tests` 清理 `runs/tests` 下的测试日志（默认只预览，加 `--yes` 确认删除）；`pytest` 每次结束默认自动删除该次调用目录，如需保留失败现场可设置 `PSYCHSANDBOX_KEEP_TESTS=1`，见 [清理测试日志](docs/RUN_ARTIFACTS.md#清理测试日志runs-clean-tests)。

## 9. 从 session 边界恢复

程序只承诺从已经保存完成的 session 边界恢复，不恢复到半轮对话中间。

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --resume-run run-xxxxxxxxxxxx
```

恢复时案例必须与原运行一致。`--sessions 3` 表示最终希望该运行累计完成 3 个 session，不是额外再运行 3 个。

续跑自动沿用原始 seed；显式传入不同 seed 会被拒绝。涉及 RFT 的运行还必须保持原 RFT 配置，失败批次会新建候选批次，不复用半场对话；第一场尚未提交也可从会前边界重试。已关闭疗程或 `safety_hold` 不允许作为普通会谈续跑，详见 [恢复限制](docs/SESSION_RFT.md)。

## 10. 使用 OpenAI 兼容 API

本项目使用 Chat Completions 风格的兼容接口，可用于 DeepSeek、通义或其他提供兼容接口的模型。具体模型名称和接口地址以供应商文档为准。

在 CMD 中设置临时环境变量：

```bat
set MODEL_API_KEY=你的密钥
set MODEL_BASE_URL=https://你的兼容接口地址/v1
set CLIENT_MODEL=来访者模型名称
set PROFILE_MODEL=离线画像抽取模型名称
set COUNSELOR_MODEL=咨询师模型名称
set SUPERVISOR_MODEL=督导师模型名称
set MODEL_TIMEOUT_SECONDS=90
set MODEL_STRUCTURED_OUTPUT=auto
set MODEL_MAX_TOKENS=4096
```

不要把真实密钥写入 README、代码、测试或提交到 Git。CLI 自动读取项目根目录 `.env`，已有进程环境变量优先；示例中的模型名称和地址不是服务当前可用性的保证。

展开原子技能超过 24 项时调用 embedding 并保留 12 项。聊天与 embedding 都使用官方 ChatECNU 端点时，可以共用 `MODEL_API_KEY`，默认向量模型为 `ecnu-embedding-small`；显式 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY` 优先。其他端点仍需独立配置，不会跨主机/端口/路径转发聊天密钥。超时由 `EMBEDDING_TIMEOUT_SECONDS` 控制（默认 60 秒），缺配置时在触发筛选处明确报错。详见 [技能筛选配置](docs/SKILL_SELECTION.md)。

`SUPERVISOR_MODEL` 未设置时会回退到 `COUNSELOR_MODEL`，用于每个 session 的量表评分、多会话结束后的整体督导，以及开启 RFT 后的候选会谈评分；三处使用同一套 `prompts/eval` 量表提示词与分值定义。 `SUMMARY_MODEL` 未设置时同样回退到 `COUNSELOR_MODEL`，用于 E.7/E.8/E.9 记忆流水线（对话信息提取、档案合并与临床摘要）。

`MODEL_STRUCTURED_OUTPUT=auto` 会按角色和模型判断：ChatECNU 的 `ecnu-plus` 与 `ecnu-turbo` 自动启用原生 `response_format=json_schema`；`ecnu-max` 及其他兼容接口保持提示词 JSON 模式。已确认供应商支持 JSON Schema 时可显式设为 `json_schema`，不支持时设为 `off`。ChatECNU 推荐配置示例：

```bat
set MODEL_BASE_URL=https://chat.ecnu.edu.cn/open/api/v1
set CLIENT_MODEL=ecnu-plus
set COUNSELOR_MODEL=ecnu-plus
set SUPERVISOR_MODEL=ecnu-plus
set MODEL_STRUCTURED_OUTPUT=auto
set MODEL_TIMEOUT_SECONDS=180
set MODEL_MAX_TOKENS=4096
```

运行真实 API：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --max-turns 6 ^
  --seed 42
```

API 输出必须通过 Pydantic 结构校验。非法 JSON 会把上一次无效响应和校验错误交给模型修复，并把本地诊断文件写入 `runs\runtime\时间__案例ID__run-编号\diagnostics`。该目录可能包含案例内容，已被 Git 忽略，不应对外发送。连续失败后会返回包含模型角色、输出类型和校验错误的异常。运行过程中会逐 session 输出开始和完成进度；未捕获异常会将数据库运行状态标记为 `failed`。多会话结束后的整体督导若调用失败，只会输出提示信息，不影响已完成的运行与状态记录。

若希望关闭 CMD 后环境变量仍保留，可使用 `setx`，但新值只会对之后新开的 CMD 生效：

```bat
setx MODEL_BASE_URL "https://你的兼容接口地址/v1"
setx CLIENT_MODEL "来访者模型名称"
setx COUNSELOR_MODEL "咨询师模型名称"
```

出于安全考虑，不建议用 `setx` 长期保存 API 密钥。

## 11. 运行自动化测试

```bat
pytest -q
```

测试覆盖：

- PsychEval 官方案例数量、字段、划分和许可证。
- 领域模型数值边界。
- 咨询师信息隔离。
- 来访者静态/私有信息隔离、retrieved/blocked 披露门控、台词证据核验和提前披露 fallback。
- 泛化触发词抑制、明确话题边界响应和咨询师重复回复修复。
- 两阶段来访者生成、规划器事实选择、旧披露记忆、跨类别歧义处理、信任单次因果更新、会谈间疲劳恢复、自然回撤和独立仿真评估。
- 四级风险和输出安全检查。
- 层级技能父子关系、流派/阶段硬过滤、模型自主选择和 ReAct Observation。
- 测试专用确定性网关下的控制流程，不提供生产运行入口。
- API JSON Schema 请求、非法 JSON 修复重试与本地诊断记录。
- ECNU `auto` 模式按角色区分 `ecnu-plus`/`ecnu-turbo` 与 `ecnu-max`。
- 连续 3-session 运行。
- CLI session 进度反馈和异常运行 `failed` 状态持久化。
- 跨 session 状态连续性。
- SQLite 恢复和 JSONL 输出。
- 多会话后整体督导（PsychEval 量表）持久化，RFT 候选评分保留在候选审计记录。
- E.7/E.8/E.9 记忆流水线（信息披露提取、ground-truth 门控档案合并、临床摘要）。
- 结构化 5Ps、五流派适配、纵向报告和进度驱动计划。
- HTML 过程/结果可视化与整体督导展示。
- 技能审核、晋升和回滚约束。
- YAML 默认配置与 API-only CLI 参数。
- 多候选隔离、有限并发、去重、精确评分证据、安全整批暂停、失败留档和仅赢家提交。
- RFT 恢复约束、运行目录锁、异步诊断隔离与旧报告兼容。

## 12. 数据和存储边界

以下目录默认被 `.gitignore` 忽略：

```text
data\external\
data\processed\
runs\
outputs\
checkpoints\
```

下载产物按次保存在 `runs\runtime` 并通过最近成功指针供显式转换使用；转换后的唯一运行时案例缓存固定为 `data\processed\psycheval`。运行时不会读取旧 processed、不会动态转换原始 JSON，也不会用本地 legacy profile 回退。仓库内的 `data\<therapy>`、`assets` 和 `prompts` 是固定研究资源，但只有上述明确标为运行入口的子集会被当前代码加载。项目不采集真实医疗记录、真实咨询录音或真实求助者隐私。人工评测应仅使用公开案例、合成资料或经过批准的脱敏材料。

PsychEval 采用 CC BY-NC 4.0，本项目对其数据的使用限于非商业教学研究。转换器增加了统一字段、确定性划分、派生元技能 ID 和仿真人格先验，但不会伪造官方缺失的原子技能 ID。详见 [NOTICE.md](NOTICE.md) 和 [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md)。

## 13. 与 PsychEval、PsychAgent 的关系

### PsychEval

PsychEval 是本项目第一阶段的主要数据和技能来源。本项目直接借鉴并保留：

- BT、CBT、HET、PDT、PMT 五流派人物画像。
- 三阶段/多 session 咨询计划。
- session 目标。
- persona links 和 case materials。
- 推荐元技能与原子技能。
- 参考对话、会后摘要和下一次计划材料。

本项目在 PsychEval 之上增加可执行智能体、信息权限、安全状态机、跨 session 记忆、 SQLite 恢复、轨迹记录和督导反馈，因此不是简单的数据浏览器。

### PsychAgent

PsychAgent 论文用于指导第三阶段的经验积累和自进化设计，包括经验回放、技能提取、技能版本化和训练数据生成。目前没有声称完整复现其训练系统。项目已经实现经验池、技能生命周期、SFT/DPO 数据导出接口，以及独立的会谈多候选采样、评分和选优。选优产物尚未自动对接训练导出，也没有完成正式 QLoRA 或偏好训练实验。

## 14. 后续阶段怎么做

### 后续流派与督导反馈闭环

- EFT 明确定义为 Emotion-Focused Therapy。
- 不把 PsychEval 的 HET 或 BT 数据直接重命名为 EFT。
- 建立独立 EFT 技能库，并由心理学背景人员复核。
- 在存在独立病例、技能库和评估标准后再增加 EFT 与 integrative `TherapyProfile`。
- 对比“有督导反馈”和“无督导反馈”，验证反馈是否改变下一次 session 计划。

### 第三阶段：经验积累和自进化

- 只有安全与泄漏检查合格的轨迹可以进入训练候选集。
- 候选技能必须经过 replayed、expert_reviewed、approved、promoted 等阶段。
- 新技能不得自动进入正式技能库。
- 先在 3B/4B 模型上进行 4-bit QLoRA SFT。
- 再根据同一 session 的高低分候选生成 DPO chosen/rejected 数据。
- 在独立案例测试集验证；安全、泄漏或主要指标下降时必须回滚。

### 正式实验

- 第一轮：10 个 CBT 案例 × 3 个随机种子。
- 正式 CBT 实验：至少 30 个案例。
- 安全集：至少 100 条，覆盖高、中、低风险和正常负面情绪。
- 人工评测：两名心理学背景评审者，至少评审 30 个合成或脱敏 sessions。
- 报告均值、标准差、置信区间、失败案例和加权 Kappa。

更完整的研究路线见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 15. 常见问题

### CMD 提示“不是内部或外部命令”

确认虚拟环境已经激活：

```bat
call .venv\Scripts\activate.bat
```

或者直接使用：

```bat
python -m psychsandbox --help
```

### 提示找不到案例

先确认使用完整仓库、当前目录为仓库根目录，并检查随仓库分发的病例：

```bat
dir data\cbt\1.json
psych-sandbox cases list --therapy cbt
```

`data fetch` 和 `data convert` 是刷新/重建工具，不是读取仓库内五流派病例的前置步骤。

### 提示缺少 `MODEL_API_KEY`

所有仿真运行都通过 API 完成，因此必须设置 `MODEL_API_KEY`、`CLIENT_MODEL` 和 `COUNSELOR_MODEL`。请参考第 10 节配置兼容接口。

### API 返回的不是合法 JSON

程序会自动进行一次带校验错误信息的修复重试。若仍失败，应检查模型是否具有可靠的 JSON 输出能力、上下文是否超过限制，以及 `CLIENT_MODEL`、`COUNSELOR_MODEL` 是否配置正确。

### 中文在 CMD 中显示乱码

先切换 CMD 到 UTF-8：

```bat
chcp 65001
```

然后重新运行命令。也可以使用 Windows Terminal 打开 CMD 配置文件，以获得更好的 UTF-8 支持。
