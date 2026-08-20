# 基于 PsychEval/PsychAgent 的心理咨询多智能体研究沙盒

本项目是一个面向大学生创新创业训练、智能体研究和心理咨询对话评测的实验系统。
它把 PsychEval 中的多会话 CBT 案例、人物画像和咨询技能转换为可运行的多智能体环境，
让“模拟来访者—咨询师—督导师”能够连续完成多次会谈，并记录记忆、技能选择、状态变化、
风险判断和督导评分。

> 本项目仅用于非商业教学与科研，不是真实心理咨询或医疗服务。禁止接入真实求助者，
> 不用于诊断、治疗、药物建议或现实危机处置。系统中的情绪状态、人格参数和自动评分
> 都是仿真变量，不是经过临床验证的量表。

## 快速开始

以下命令适用于 Windows CMD。Mock 模式不需要 API 密钥，可用于快速验证完整流程：

```bat
git clone https://github.com/AgClNaClO/psych_sandbox.git
cd psych_sandbox
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
pytest -q
psych-sandbox data fetch psycheval
psych-sandbox data convert --therapy cbt
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --provider mock
```

`data fetch` 需要访问网络；如果本地已经生成 `data\processed\psycheval`，可以跳过
数据下载和转换。

仿真结束后，终端会输出 `run-xxxxxxxxxxxx` 格式的运行编号，并自动生成
`runs\run-xxxxxxxxxxxx.html`。该报告可直接在浏览器中离线打开；也可以随时重新生成：

```bat
psych-sandbox visualize --run run-xxxxxxxxxxxx
```

## v0.3.0 更新重点

- 新增 CBT 与人本—存在取向的独立 `TherapyProfile`，避免混用不同流派的数据与评估标准。
- 将模拟来访者拆分为内部状态规划和自然语言表达两个阶段，增加话题边界、阻抗、
  提前披露防护及对话循环修复。当前来访者提示词版本为 `psycheval_patientact_v4`。
- 修复来访者披露链路：规划器选择的事实才会进入语言模型；本轮声称披露的事实必须能从
  实际台词核验；跨会谈只复用已经说过的证据片段，不把完整隐藏层写入记忆。
- 将同类/跨类别候选统一进行歧义消解，并将公开主诉从私密泄漏匹配中排除；保留确定性
  近似匹配、重试和安全替代回答作为纵深防护。
- PatientAct 关系参数只从 PsychEval 有明确证据的核心信念、应对方式、敏感主题和情绪词派生；
  无来源的人格和依恋维度保持中性或未指定，不由模型臆造。
- 合入 `patientact-client-upgrade-v4` 的 E.7/E.8/E.9 会后记忆流水线、整体督导与存储更新；
  咨询师生成和技能选择逻辑不属于本次来访者改造范围。
- 新增独立的来访者真实性评估、规则会谈评估和跨 session 纵向趋势分析。
- 督导反馈不再回写下一 session 计划：下一计划由纵向进度信号（目标完成度 + 状态差值）驱动。
- 新增单文件 HTML 可视化报告，集中呈现运行流程、状态曲线、督导指标、
  信息披露、安全检查和完整对话。
- 自动化测试扩展至 108 项，覆盖多会话连续性、SQLite 恢复、信息隔离、安全分流、
  API 结构化输出、失败状态持久化与 CLI 进度反馈。

## 1. 项目要解决什么问题

普通大模型通常只能完成单轮或短期心理咨询对话，存在以下问题：

- 不记得上一次咨询谈过什么，容易重复提问或前后矛盾。
- 只生成自然语言回复，无法解释本轮选择了什么咨询技能。
- 模型可能提前知道来访者尚未披露的经历，造成隐藏信息泄漏。
- 缺少独立督导师，无法形成“咨询—评分—反馈—调整”的闭环。
- 遇到自伤、他伤等高风险表达时，仍可能继续进行普通 CBT 练习。
- 高质量会谈经验不能沉淀为可回放数据、技能版本或训练样本。

本项目针对这些问题实现以下闭环：

```text
PsychEval CBT 案例
        ↓
模拟来访者 ↔ CBT 咨询师
        ↓
安全检查 + 状态更新 + 信息披露门控
        ↓
会后摘要 + 跨 session 记忆 + 下一次计划
        ↓
规则督导 + 多会话后整体督导（PsychEval 量表）
        ↓
SQLite、JSONL 轨迹和后续经验池
```

## 2. 当前完成情况

第一阶段“最小可运行沙盒”的代码和 Mock 工程验证已经完成：

- 转换 PsychEval 官方 148 个 CBT 案例。
- 提取 346 个元技能和 1171 个原子技能，保留官方原子 `skill_id`。
- 按案例进行确定性训练集、验证集和测试集划分：108/19/21。
- 将 PsychEval 原始字段转换为带来源字段的结构化 5Ps 个案概念化。
- 支持 CBT 与人本—存在取向两个独立 `TherapyProfile`；后者仅使用合成案例和
  第一阶段演示技能，不冒充 PsychEval 官方流派数据。
- 支持单个案例连续运行 6–10 个 session，并验证状态与记忆连续性。
- 支持从 SQLite 中最近一个 session 边界恢复运行。
- 咨询师只能读取已解锁信息，不能读取完整来访者档案。
- 来访者语言生成器只能读取静态画像、本轮经规划器选中的允许记忆，以及过去已经实际说出的
  证据片段；完整私有画像仅进入内部状态规划器。
- 支持“反应—行为—阻抗—回答”的两阶段来访者生成、blocked 敏感话题信号和提前披露防护。
- 支持来访者话题边界识别、咨询师重复回复检测和互动修复，避免固定追问形成对话循环。
- 每轮记录技能候选、实际技能、结构化决策、状态变化和安全结果。
- 每个 session 生成摘要、六维规则督导、独立来访者仿真报告、纵向趋势和
  进度驱动的下一次计划。
- 每次 CLI 仿真自动生成单文件 HTML 报告，展示流程、状态曲线、督导指标、
  披露/安全过程和完整对话。
- 支持 Mock、OpenAI 兼容 API 和本地 Transformers 三种模型后端。
- 108 项自动化测试全部通过，无跳过测试。
- 已完成 10 个案例、30 个 session 的 Mock 基线实验。

Mock 基线平均规则督导分为 7.889，未检测到提前泄漏和规则级安全违规。
这只是工程基线，不代表真实咨询效果。真实 API、三随机种子、30 案例正式实验和人工评审
仍需要在后续实验阶段完成。

## 3. 项目中的三个智能体

### 3.1 模拟来访者

来访者采用两个严格分离的视图。内部状态规划器可以读取完整私有画像，用于判断本轮反应、
行为、阻抗和信任变化；自然语言生成器只能看到：

- 基本背景和当前问题。
- 语言习惯；PsychEval 未提供人格证据时使用中性仿真先验，不再按案例 ID 随机生成。
- 情绪、联盟信任、话题准备度、疲劳和关系破裂状态。
- 当前轮通过联盟信任与话题准备度门控的渐进式记忆层。
- 过去会谈中已经实际说过的证据片段；这些旧记忆可以自然回顾，但不能据此扩写新细节。
- 不含秘密正文的 blocked 话题信号。
- 同类事实无法精确区分时的歧义信号。
- 咨询师上一轮回复和近期对话。

生成器看不到未授权成长经历、特殊情境、完整 CBT 概念化材料或咨询师内部 session 目标。
事实门控先找候选，再由内部规划器选择真正相关的事实；跨类别候选如果无法唯一定位，来访者会
请求具体化而不是同时披露。生成器返回的 `disclosed_fact_ids` 还要与实际台词核验，只有找到
文本证据的事实才会解锁，记忆中保存的也是本轮说出的片段而不是整层隐藏档案。

回答经过确定性提前披露检查；检查会排除公开主诉和已说过的旧记忆，并对相近改写做近似匹配。
首次失败会重试，仍失败则使用符合当前行为信号的安全替代回答。该检查是纵深防护，不等同于
完整语义理解；最终的多会话语义一致性仍由 PsychEval 整体督导和人工评审承担。

PatientAct 参数采用“有证据才派生”的原则：核心信念、显式应对策略、高敏感事实标签和原文情绪词
可进入关系画像；PsychEval 没有提供证据的 Big Five 和依恋类型保持中性/未指定。状态在会谈内
允许非线性波动，信任变化只按内部规划器的本轮信号计算一次；跨会谈保留长期状态，同时恢复一部分
短期疲劳，避免 6–10 次会谈中疲劳只能单向累积。

### 3.2 多流派咨询师

第一阶段提供 CBT 与人本—存在取向两个适配器。咨询师智能体只能看到：

- 来访者已经明确说出的信息。
- 已解锁档案。
- 之前 session 的摘要、目标、作业和未解决问题。
- 当前 session 目标。
- 经过阶段过滤和 BM25 召回的候选技能。

咨询师看不到完整档案、未披露成长经历和其他隐藏事实。每轮会输出简短、可审计的结构化决策，
包括评估、状态观察、所选元技能、所选原子技能、策略、目标进度和最终回复。

### 3.3 督导师

督导师拥有审计视图，可以查看完整档案、会谈计划、对话和技能决策。第一阶段评估六个维度：

- `wai_lite`：目标、任务和关系联盟。
- `ctrs_lite` / `tes_lite`：分别检查 CBT 或人本—存在取向的可观察流派行为。
- `stage_consistency`：干预是否符合当前咨询阶段。
- `persona_consistency`：来访者人设和跨 session 一致性。
- `hidden_information_leakage`：咨询师是否提前使用隐藏信息。
- `ethics_and_safety`：高风险场景是否停止普通干预并进行安全分流。

每 session 结束后运行确定性规则督导，用于审计与安全门控，不参与下一 session 规划。
整条多 session 轨迹全部结束后，再运行一次与 PsychEval 对齐的整体督导：直接使用官方
`eval/prompts_cn` 量表提示词，给出 Counselor-Level（临床胜任力）与 Client-Level
（仿真保真度）评分。整体督导在 Mock 与 API 模式下都会运行；规则督导与整体督导分开
保存，不会用一个总分覆盖具体证据和违规项。

## 4. 核心架构

```text
src/psychsandbox/
├── domain/          Pydantic 统一领域模型
├── datasets/        PsychEval 下载、转换、划分和案例仓库
├── agents/          来访者、咨询师门面与可选 LLM 督导
├── client_simulation/ 来访者激活、渐进披露、反应、语言和状态的统一接口
├── therapies/       治疗流派定义、概念化焦点与阶段目标
├── runtime/         编排、安全、披露、状态、记忆、反馈计划和 SQLite
├── skills/          元技能/原子技能注册与层级检索
├── evaluation/      规则督导、来访者仿真、纵向评测与整体督导
├── visualization/   无外部依赖的 SVG/HTML 运行报告
├── experience/      通过安全门槛的经验池
├── evolution/       技能审核、晋升、弃用和回滚状态机
├── training/        SFT 与 DPO 数据导出
├── model_client.py  Mock、API 和本地模型网关
└── cli.py           数据、案例、仿真和报告命令
```

主要运行流程如下：

1. `prepare_session`
   - 读取上次摘要、已解锁档案、风险历史和督导反馈。
   - 从 PsychEval 全局计划确定当前阶段和目标。
   - 根据疗法与阶段过滤技能。
2. `run_turn`
   - 对来访者输入进行安全检查。
   - BM25 召回元技能及其原子技能。
   - 咨询师生成结构化决策和回复。
   - 对咨询师输出再次进行安全检查。
   - `ClientSimulator` 在一个接口内完成事实激活、全候选歧义处理和渐进披露。
   - 内部规划器依次选择情绪反应、行为、可选阻抗形式和信任变化；blocked 不再强制等于防御。
   - 只有内部规划器从候选中选中的事实才进入语言生成器；语言生成器另可读取已披露证据记忆。
   - 回答通过事实 ID 授权、台词证据核验和提前泄漏检查后，才更新解锁档案。
   - 更新联盟信任、话题准备度、疲劳和关系破裂状态并保存审计轨迹；下一 session 开始时仅恢复
     部分短期疲劳，不重置联盟、困扰、希望或话题准备度。
3. `consolidate_session`
    - 运行 E.7/E.8/E.9 记忆流水线：提取本 session 实际披露信息、按 ground-truth 门控合并演化档案、
      生成有对话证据支撑的临床摘要。
    - 生成摘要并更新跨 session 记忆。
    - 保存新解锁事实、目标进度和已使用技能。
    - 调用确定性规则督导。
    - 计算状态差值、相邻会谈趋势和阶段动作。
    - 由纵向进度信号生成下一次计划，不依赖督导评分。
    - 保存 SQLite 和 JSONL 轨迹。
    - CLI 模式生成可折叠查看逐轮过程的 HTML 报告。
4. 全部 session 结束后，`PsychEvalSupervisor` 用官方量表对整条轨迹做一次整体督导，
   输出 Counselor-Level 与 Client-Level 报告并写入 HTML 报告与 SQLite。

## 5. Windows CMD 环境准备

以下命令都应在 Windows 的“命令提示符（CMD）”中运行，而不是 PowerShell。

### 5.1 前置软件

需要安装：

- Python 3.11 或更高版本。
- Git。
- 推荐使用支持长路径的 Windows 10/11。

先打开 CMD，进入项目目录：

```bat
cd /d D:\Projects\psych_sandbox
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
cd /d D:\Projects\psych_sandbox
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

## 6. 下载和转换 PsychEval

### 6.1 下载官方数据

```bat
psych-sandbox data fetch psycheval
```

数据下载到：

```text
data\external\psycheval\
```

下载器使用 PsychEval 官方仓库，并固定到提交：

```text
e04df535749e5bca76fcc45d9a85f3f46a082d91
```

### 6.2 转换 CBT 案例

```bat
psych-sandbox data convert --therapy cbt
```

转换结果位于：

```text
data\processed\psycheval\
├── all.jsonl
├── train.jsonl
├── validation.jsonl
├── test.jsonl
├── skills.json
└── manifest.json
```

`manifest.json` 保存案例数量、技能数量、上游提交、许可证、集合划分和源文件摘要。

### 6.3 检查案例

```bat
psych-sandbox cases list --therapy cbt
```

正常情况下会看到 `psycheval-cbt-001` 到 `psycheval-cbt-148`。

## 7. 运行 Mock 仿真

Mock 模式不需要 API 密钥，适合测试、答辩演示和验证控制流程。

运行一个案例的 3 次连续咨询：

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --provider mock
```

限制每个 session 最多 4 轮：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --provider mock ^
  --max-turns 4 ^
  --seed 42
```

输出完整 JSON：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --provider mock ^
  --json
```

运行完成后，终端会显示 `run-xxxxxxxxxxxx` 形式的运行编号，请保存该编号；结尾还会输出
一行“整体督导：Counselor=… Client=…”，为 PsychEval 对齐的多会话后量表评分。

## 8. 查看评测和完整报告

查看每个 session 的六维评分：

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

默认输出为 `runs\run-xxxxxxxxxxxx.html`。报告是可离线打开的单文件页面，不上传数据，
包括六步运行流程、来访者状态曲线、逐 session 督导指标、纵向判断、逐轮技能/披露/安全记录
和完整对话。`simulate` 默认自动生成该报告；如只需要 JSON/SQLite，可传
`--no-visualization`。

默认数据库和轨迹位于：

```text
runs\psychsandbox.sqlite3
runs\run-xxxxxxxxxxxx.jsonl
```

SQLite 保存案例、运行、session、turn、记忆、规则评测、整体督导和完整轨迹。
JSONL 适合后续统计分析、经验回放和训练数据转换。

## 9. 从 session 边界恢复

程序只承诺从已经保存完成的 session 边界恢复，不恢复到半轮对话中间。

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 3 ^
  --provider mock ^
  --resume-run run-xxxxxxxxxxxx
```

恢复时案例必须与原运行一致。`--sessions 3` 表示最终希望该运行累计完成 3 个 session，
不是额外再运行 3 个。

## 10. 使用 OpenAI 兼容 API

本项目使用 Chat Completions 风格的兼容接口，可用于 DeepSeek、通义或其他提供兼容接口的模型。
具体模型名称和接口地址以供应商文档为准。

在 CMD 中设置临时环境变量：

```bat
set MODEL_API_KEY=你的密钥
set MODEL_BASE_URL=https://你的兼容接口地址/v1
set CLIENT_MODEL=来访者模型名称
set COUNSELOR_MODEL=咨询师模型名称
set SUPERVISOR_MODEL=督导师模型名称
set MODEL_TIMEOUT_SECONDS=90
set MODEL_STRUCTURED_OUTPUT=auto
set MODEL_MAX_TOKENS=4096
```

不要把真实密钥写入 README、代码、测试或提交到 Git。

`SUPERVISOR_MODEL` 未设置时会回退到 `COUNSELOR_MODEL`，用于多会话结束后的一次性整体督导。
`SUMMARY_MODEL` 未设置时同样回退到 `COUNSELOR_MODEL`，用于 E.7/E.8/E.9 记忆流水线
（对话信息提取、档案合并与临床摘要）。

`MODEL_STRUCTURED_OUTPUT=auto` 会按角色和模型判断：ChatECNU 的 `ecnu-plus` 与
`ecnu-turbo` 自动启用原生 `response_format=json_schema`；`ecnu-max` 及其他兼容接口
保持提示词 JSON 模式。已确认供应商支持 JSON Schema 时可显式设为 `json_schema`，
不支持时设为 `off`。ChatECNU 推荐配置示例：

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
  --provider api ^
  --max-turns 6 ^
  --seed 42
```

API 输出必须通过 Pydantic 结构校验。非法 JSON 会把上一次无效响应和校验错误交给模型
修复，并把本地诊断文件写入 `runs\diagnostics`。该目录可能包含案例内容，已被 Git 忽略，
不应对外发送。连续失败后会返回包含模型角色、输出类型和校验错误的异常。运行过程中会
逐 session 输出开始和完成进度；未捕获异常会将数据库运行状态标记为 `failed`。
多会话结束后的整体督导若调用失败，只会输出提示信息，不影响已完成的运行与状态记录。

若希望关闭 CMD 后环境变量仍保留，可使用 `setx`，但新值只会对之后新开的 CMD 生效：

```bat
setx MODEL_BASE_URL "https://你的兼容接口地址/v1"
setx CLIENT_MODEL "来访者模型名称"
setx COUNSELOR_MODEL "咨询师模型名称"
```

出于安全考虑，不建议用 `setx` 长期保存 API 密钥。

## 11. 本地模型模式

本地模式是后续 QLoRA 模型的推理入口，需要额外依赖：

```bat
python -m pip install -e ".[local]"
```

当前机器为 8GB 显存时，建议从 3B/4B 指令模型的 4-bit 量化推理开始。本地运行示例：

```bat
psych-sandbox simulate ^
  --case psycheval-cbt-001 ^
  --sessions 1 ^
  --provider local ^
  --local-model 模型仓库名或本地路径 ^
  --local-device auto
```

Python API 的 `default_config()` 会读取 `configs\runtime.yaml` 中的路径、温度和
PATIENTACT 参数，以及 `configs\models.yaml` 中的本地模型配置。CLI 以命令行参数为准。
本地 7B/14B 训练不属于第一阶段验收内容。

## 12. 运行自动化测试

```bat
pytest -q
```

当前预期结果：

```text
108 passed
```

测试覆盖：

- PsychEval 官方案例数量、字段、划分和许可证。
- 领域模型数值边界。
- 咨询师信息隔离。
- 来访者静态/私有信息隔离、retrieved/blocked 披露门控、台词证据核验和提前披露 fallback。
- 泛化触发词抑制、明确话题边界响应和咨询师重复回复修复。
- 两阶段来访者生成、规划器事实选择、旧披露记忆、跨类别歧义处理、信任单次因果更新、
  会谈间疲劳恢复、自然回撤和独立仿真评估。
- 四级风险和输出安全检查。
- 层级技能父子关系、过滤和确定性检索。
- Mock 结构化输出。
- API JSON Schema 请求、非法 JSON 修复重试与本地诊断记录。
- ECNU `auto` 模式按角色区分 `ecnu-plus`/`ecnu-turbo` 与 `ecnu-max`。
- 连续 3-session 运行。
- CLI session 进度反馈和异常运行 `failed` 状态持久化。
- 跨 session 状态连续性。
- SQLite 恢复和 JSONL 输出。
- 六维规则督导报告与多会话后整体督导（PsychEval 量表）持久化。
- E.7/E.8/E.9 记忆流水线（信息披露提取、ground-truth 门控档案合并、临床摘要）。
- 结构化 5Ps、双流派适配、纵向报告和进度驱动计划。
- HTML 过程/结果可视化与整体督导展示。
- 技能审核、晋升和回滚约束。
- YAML 默认配置读取与本地模型 CLI 参数。

## 13. 数据和存储边界

以下目录默认被 `.gitignore` 忽略：

```text
data\external\
data\processed\
runs\
outputs\
checkpoints\
```

原因是原始数据、转换数据、实验轨迹和模型权重不应直接进入代码仓库。项目不采集真实医疗记录、
真实咨询录音或真实求助者隐私。人工评测应仅使用公开案例、合成资料或经过批准的脱敏材料。

PsychEval 采用 CC BY-NC 4.0，本项目对其数据的使用限于非商业教学研究。转换器增加了统一字段、
确定性划分、派生元技能 ID 和仿真人格先验，但不会伪造官方缺失的原子技能 ID。
详见 [NOTICE.md](NOTICE.md) 和 [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md)。

## 14. 与 PsychEval、PsychAgent 的关系

### PsychEval

PsychEval 是本项目第一阶段的主要数据和技能来源。本项目直接借鉴并保留：

- CBT 人物画像。
- 三阶段/多 session 咨询计划。
- session 目标。
- persona links 和 case materials。
- 推荐元技能与原子技能。
- 参考对话、会后摘要和下一次计划材料。

本项目在 PsychEval 之上增加可执行智能体、信息权限、安全状态机、跨 session 记忆、
SQLite 恢复、轨迹记录和督导反馈，因此不是简单的数据浏览器。

### PsychAgent

PsychAgent 论文用于指导第三阶段的经验积累和自进化设计，包括经验回放、技能提取、
技能版本化和训练数据生成。目前没有声称完整复现其训练系统。项目已经实现经验池、
技能生命周期、SFT/DPO 数据导出接口，但还没有完成正式 QLoRA 或偏好训练实验。

## 15. 后续阶段怎么做

### 第二阶段：多流派和督导反馈闭环

- EFT 明确定义为 Emotion-Focused Therapy。
- 不把 PsychEval 的 HET 或 BT 数据直接重命名为 EFT。
- 建立独立 EFT 技能库，并由心理学背景人员复核。
- 支持 CBT、EFT 和 integrative 三种 `TherapyProfile`。
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

更完整的研究路线见 [docs/ROADMAP.md](docs/ROADMAP.md)，当前 Mock 基线见
[reports/phase1_mock_baseline.md](reports/phase1_mock_baseline.md)。

## 16. 常见问题

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

先执行数据下载和转换：

```bat
psych-sandbox data fetch psycheval
psych-sandbox data convert --therapy cbt
```

### 提示缺少 `MODEL_API_KEY`

只有 `--provider api` 需要密钥。无密钥演示请使用：

```bat
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3 --provider mock
```

### API 返回的不是合法 JSON

程序会自动进行一次带校验错误信息的修复重试。若仍失败，应检查模型是否具有可靠的 JSON
输出能力、上下文是否超过限制，以及 `CLIENT_MODEL`、`COUNSELOR_MODEL` 是否配置正确。

### 中文在 CMD 中显示乱码

先切换 CMD 到 UTF-8：

```bat
chcp 65001
```

然后重新运行命令。也可以使用 Windows Terminal 打开 CMD 配置文件，以获得更好的 UTF-8 支持。
