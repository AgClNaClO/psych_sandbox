# psych_sandbox 与 Psych-new：技能树与实际选技链路

> 2026-08-28 更新：本文保留调查当时的分析与方案，不作为现行实现说明。项目已迁至 `D:/0test/psych_sandbox`；当前已实现按需向量筛选、公开选技依据、一次纠错及可选会谈 RFT。原子技能只新增完整路径，不新增原文摘要。现行机制见 [技能选择](../docs/SKILL_SELECTION.md) 与 [会谈 RFT](../docs/SESSION_RFT.md)。本地链接已迁移，历史代码行号不再作为现行定位依据。

调查日期：2026-08-27。当前项目指 `D:/a华东师范/2项目/1实践/psych_sandbox`。以本地源代码、技能文件及已有历史轨迹为依据；未调用真实模型 API，未修改生产代码。“层级参与运行”与“技能能否提升咨询质量”是两件事：本次可核实前者，不声称证明后者。

## 1. 两个项目的原始技能资源相同

逐文件比较两个项目 `assets/skills/sect`：30 份 JSON、15 份 PT 文件全部字节一致。共有五个流派，每个流派三个阶段；合计 677 个元技能节点、4481 个微技能/原子技能。

| 流派 | 元技能节点 | 微技能 |
|---|---:|---:|
| BT | 156 | 854 |
| CBT | 103 | 1372 |
| HET | 136 | 752 |
| PDT | 210 | 1044 |
| PMT | 72 | 459 |

原始布局是“流派 → 治疗阶段 → 多级元技能树 → 微技能”。`meta_skills.json` 包含多个深度的类别节点，不是所有元技能都位于同一层。`micro_skills.json` 保存可供回复使用的具体技巧、描述、`when_to_use`、`trigger` 和完整 `parent_ids` 路径；该路径包含节点自身。例如 CBT stage2 的真实节点链：

```text
CBT / stage2
└── 咨询性会谈（660）
    └── 咨询性会谈开始环节（661）
        └── 评估心境（662，元技能树叶节点）
            └── 使用抑郁/焦虑问卷每周评估心境（671，微技能）
```

微技能 671 的路径为 `["660", "661", "662", "671"]`。这是资源结构示例，不是对实际来访者的操作建议。证据：[元技能资源](D:/0test/psych_sandbox/assets/skills/sect/cbt/stage2/meta_skills.json)、 [微技能资源](D:/0test/psych_sandbox/assets/skills/sect/cbt/stage2/micro_skills.json)。

## 2. 当前项目 psych_sandbox

### 2.1 分层如何进入运行时

`SkillRegistry.from_project()` 优先读取 `assets/skills/sect` 的 JSON；不读取 PT 向量文件。三阶段映射为 `case_conceptualization`、`core_intervention`、`consolidation`。元技能归一化为 `MetaSkill`，只保存名称、说明、流派和阶段，不保留祖先链；微技能从 `parent_ids` 末尾向前找最近的元技能，并只保存该 `meta_skill_id`。ID 添加流派前缀，如 `psychagent:cbt:meta:662`、`psychagent:cbt:skill:671`。证据：[registry.py](D:/0test/psych_sandbox/src/psychsandbox/skills/registry.py)、 [最近父级解析](D:/0test/psych_sandbox/src/psychsandbox/skills/registry.py)、 [领域字段](D:/0test/psych_sandbox/src/psychsandbox/domain/models.py)。

因此运行时使用的是“流派/阶段 → 有直接原子技能的元技能组 → 原子技能”，不是从原树根节点逐级选择到叶子。实测 677 个元技能中，464 个有直接原子技能，213 个上层类别节点不会进入 `available_meta()`。CBT 三阶段实际可选元技能分别为 22、40、11 个，对应原子技能 504、609、259 个。这些数字由只读加载 `SkillRegistry` 与调用 `SkillCatalog.available_meta()` 得到。

### 2.2 各层实际作用

| 层/字段 | 实际作用 | 边界 |
|---|---|---|
| 流派 | 根据 `plan.therapy` 硬过滤；另拼接流派身份和概念化焦点提示词 | `common` 类型也允许，但当前这批资源各自属于五流派 |
| 治疗阶段 | 根据 `plan.stage` 硬过滤元技能、原子技能；影响目标提示 | 会谈序号不等于治疗阶段 |
| 高层元技能祖先 | 留在 JSON 中，注册表保留节点名称等信息 | 不保存树边，不递归遍历，不将祖先路径提供给规划器 |
| 直接父级元技能 | 规划器先选组；程序据此展开原子技能 | 这是实际发挥作用的两层选技分组 |
| 原子技能 | 执行器读取描述、触发情境和适用情境后选择具体 ID、生成回复 | `trigger/when_to_use` 是语义材料，不是程序触发条件 |
| 审核状态与风险 | 只暴露 approved/promoted 技能；高风险目录为空 | 中风险、危机或明确边界可在咨询师入口直接绕过普通选技 |

证据：[catalog.py](D:/0test/psych_sandbox/src/psychsandbox/skills/catalog.py)、 [审批状态](D:/0test/psych_sandbox/src/psychsandbox/skills/registry.py)、 [风险/边界分支](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)。

### 2.3 每轮如何挑选技能

```text
当前计划、已披露档案、允许记忆、最近对话、风险
→ 按流派/阶段/审批状态建立可用元技能目录
→ 第一次模型调用：Planner 输出 Action 与最多 3 个元技能 ID
→ 程序去掉无效 ID；若 Action 为 lookup_skills，展开所选组的全部原子技能
→ 第二次模型调用：Actor 观察候选原子技能，选实际使用的 ID 并生成自然语言回复
→ 程序过滤不在 Observation 内的 ID，记录 Planning/Observation/Decision
```

这里没有 BM25、向量相似度、Top-K 相关性排序；字典按 ID 排序只是稳定展示顺序。 `action_input` 不作为检索查询被消费。`respond_without_skill`、`end_session` 也允许，因此并非每轮都选技能。程序只证明记录的 ID 属于候选集，不能由此证明生成台词在语义上正确实施了技能。证据：[规划与执行入口](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)、 [全部原子技能展开](D:/0test/psych_sandbox/src/psychsandbox/skills/catalog.py)、 [输出 ID 约束](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)。

### 2.4 使用哪些提示词，怎样传入模型

| 用途 | 提示词 | 关键内容 |
|---|---|---|
| 流派身份 | `TherapyProfile.system_prompt()` | 流派名称、概念化焦点、信息权限及表达规则 |
| 本轮规划 | `prompts/counselor/planner_system.jinja2` | 不生成面向来访者的回复；选择 Action；最多 3 个目录中的元技能 ID |
| 本轮执行 | `prompts/counselor/actor_system.jinja2` | 只选 Observation 中原子技能；输出 decision 与 1–3 句 response |
| 会后自评 | `prompts/counselor/review_system.jinja2` | 核对目标与证据；必要时再规划；从下一阶段目录选择最多 3 个元技能 ID |

不是只把一个提示词文件原样发送：

```text
system = 流派 system_prompt() + Jinja2 渲染后的阶段任务模板
user   = JSON(input_payload + output_schema)
```

技能目录、当前目标、对话、Planning 和 Observation 等完整数据在 `input_payload` 中作为 user JSON 发送。模板提到 `meta_skill_catalog`，但不需要在模板里逐项打印技能，因为它们在同次请求的 user 消息中。Planner 的 payload 含元技能目录；Actor 的 payload 改为 Planning 与包含完整原子技能的 Observation。两次使用相同 `counselor` 模型角色，分别校验 `CounselorPlanning` 和 `CounselorActorOutput`。咨询师路径直接调用 `render_prompt()` 和 gateway，不走通用 `prompt_pipeline.run_prompt()`。证据：[模板入口常量](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)、 [流派拼接](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)、 [Jinja2 loader](D:/0test/psych_sandbox/src/psychsandbox/prompts.py)、 [API 消息与 Schema](D:/0test/psych_sandbox/src/psychsandbox/model_client.py)。

会后 `review_session()` 的技能建议进入下一次计划；`PlanBuilder` 根据纵向进度决定阶段进退，根据咨询师自评调整目标和策略。`target_meta_skill_ids` 是供下一轮模型参考的软提示， `available_meta()` 并不强制把候选范围限制到这些 ID；`target_atomic_skill_ids` 虽有字段和传递，目前不参与 `CounselorAgent` 的实际选技。证据：[review_session](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)、 [PlanBuilder](D:/0test/psych_sandbox/src/psychsandbox/runtime/planning.py)、 [上下文载荷](D:/0test/psych_sandbox/src/psychsandbox/agents/counselor.py)。

一个与“文件是否真正进入模型”有关的小差异：规划/执行模板的作业展示块读取 `session_memory.last_homework`，而 `build_context_payload()` 提供的是 `session_memory.homework`。因此该 system 模板块不显示作业，但同次请求的 user JSON 仍包含 `homework`，不能说作业信息完全丢失。这不影响本次对技能树筛选机制的判断。

### 2.5 现有真实轨迹中的证据

已有运行 `run-a64137af7653` 首个会谈第一轮：从 CBT 概念化阶段的 22 个可用元技能中选出“收集来访者人口学与基本信息”“建立咨询关系”“评估主诉的临床表现与功能影响”三个组； Observation 返回 78 个原子技能；Actor 最终记录使用一个技能 `psychagent:cbt:skill:265`（梳理家庭结构、父母职业与经济状况）。

这次历史运行的三个会谈都处于 `case_conceptualization`，并没有按第 1/2/3 次会谈机械切换 stage1/2/3。其中也有 `respond_without_skill` 轮次。该证据是读取既有历史轨迹，不是重新调用当前版本 API 得到的新实验，也不证明该选择有临床收益。历史证据来自该运行的 `trajectory.jsonl`；2026-08-28 清理后该文件已不存在，上述数值仅保留为调查时记录，不能在当前目录重新核验。

## 3. Psych-new 与比较结论

### 3.1 树结构的使用

实际技能加载器为 `SkillManager`，按 `sect` 和 `stage1/2/3` 建立技能库；读取元技能 JSON，微技能在 PT 存在且安装了 torch 时优先读取 `micro_skills.pt`、否则读取 JSON。保留完整 `parent_ids`，由 `get_leaf_nodes()` 找出元技能树的叶节点，再将这些叶元技能送入粗筛模型。模型看到的粗筛条目移除了 `parent_ids`。证据：[加载](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:127)、 [叶节点计算](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:387)、 [PT 优先](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:545)。

`find_skill_by_id()` 通过完整路径的严格前缀关系找所选元技能的直接微技能：微技能路径长度应为元技能路径长度加一、前缀完全相等、最后一项等于微技能自己的 ID。因此祖先层仍参与结构归属检查，但不是逐层模型决策。该函数还把祖先名称拼成 `meta_skill` 文本，但采样和 Web 两个主调用方都只展开 `micro_skills`，未保留这个文本；最终咨询师模板也只展示微技能名称、描述、适用时机、触发线索。不能因为代码生成了祖先名称链，就声称咨询师能看到完整技能树。证据：[路径匹配与名称链](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:346)、 [采样入口展开](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:492)、 [Web 入口展开](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:309)。

### 3.2 实际挑选流程

```text
当前流派 + 当前治疗阶段
→ 该流派/阶段的叶元技能目录
→ LLM 根据本会谈目标粗筛元技能（默认 n=20）
→ 路径匹配，展开其微技能作为候选池
→ 每轮用 LLM 将当前发言 + 对话历史 + 会谈目标改写为 Trigger / When_to_Use
→ 查询向量与候选微技能 embedding_to_retrive 做余弦相似度
→ 降序取默认 top_k=5（threshold 默认 None）
→ 将这几个微技能作为 suggested_skills 渲染到咨询师 system 提示词
→ 咨询师在生成文本时，用 <skill> 写所用技能名称，并生成 <response>
```

向量筛选使用的是 `embedding_to_retrive`（代码原拼写），其补全输入是微技能的 `Trigger:...\nWhen_to_Use:...`，不是整棵树或完整技能说明。`embedding_to_merge` 虽会加载/补全，但不参与这条回复检索链的相似度排名。默认模型配置为 `BAAI/bge-m3`，向量请求调用 API；初始化缺失向量时会写回 PT。这里只核查代码和已有文件，未执行这些联网或写回操作。证据：[检索默认参数和排序](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:233)、 [向量补全材料](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:113)、 [默认配置](D:/a华东师范/2项目/1实践/Psych-new/configs/runtime/psychagent_sglang_local.yaml:27)。

两个实际入口的调用频率不同：

| 入口 | 粗筛时间 | 微技能检索时间 |
|---|---|---|
| `src/sample/runner.py` 自动采样 | 每个会谈开始时建立一次候选池 | 开场及每个后续咨询师回复前 |
| `src/web/backend/psychagent_engine.py` Web 会谈 | `reply_from_visit()` 每次回复都重新建立候选池 | 每次回复，在存在最新用户发言时 |

证据：[采样会谈粗筛](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:221)、 [采样逐轮检索](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:343)、 [Web 回复](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:83)。

主链没有让咨询师输出工具 Action、再由工具返回 Observation 的循环；检索是程序预先调用的。提示词中有分析段落和技能选择标签，不应据此把整个实现称为主动调用工具的 ReAct。

### 3.3 提示词位置与载荷

| 环节 | 实际加载的文件 | 渲染/发送内容 |
|---|---|---|
| 元技能粗筛 | `prompts/psychagent/skill/select_skill/system.txt`、`user.txt` | system 填 `number=20`；user 填 `session_goals` 与叶元技能字典 `skills_library`；解析 `{"skill_id":[...]}` |
| 查询改写 | `prompts/psychagent/skill/rewrite/system.txt`、`user.txt` | user 填本会谈目标、当前会谈历史、最新发言；代码将 `Treatment_Structure` 固定为 `General`；提取返回文本中 `<response>` 的 Trigger/When_to_Use |
| 最终回复 | `prompts/psychagent/<bt/cbt/het/pdt/pmt>/counsel/system.jinja2` | 填画像、历史会谈、当前阶段、会谈目标、上轮作业及检索出的微技能；之后附实际对话 messages |

粗筛/改写虽然扩展名为 `.txt`，仍经 Jinja2 `Template.render()` 插值。 `SkillManager._load_prompts()` 从配置指定目录加载四个 TXT 文件；`PsychAgentPromptManager` 加载当前流派 `counsel/system.jinja2`。最终回复模板要求技能按名称写入 `<skill>`，而不是像当前项目那样输出受 Schema 校验的技能 ID 列表。证据：[四个 TXT 的 loader](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:499)、 [查询改写载荷](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:299)、 [流派模板 loader](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:24)、 [CBT 回复模板](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:1)。

### 3.4 哪些限制没有真正成为硬约束

1. **数量要求存在冲突。** 粗筛默认要求恰好 20 个唯一 ID，但同一提示词又允许只有 0–2 个真正相关时少选或不选。调用方没有将 20 缩小到叶节点数；例如 CBT stage3 只有 11 个叶元技能。程序解析后也未强制数量、去重或叶节点白名单。不存在的 ID 在后续查表时被忽略；模型若返回非叶元节点，通常不能得到直接微技能。证据：[粗筛提示词](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:1)、 [粗筛实现](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:172)。
2. **空选择不等于不用技能。** 无 ID 或解析异常会回退为字典中前 n 个叶元技能；这个回退不是相关性排序。
3. **最终技能忠实性主要依赖提示词。** 代码抽取 `<response>` 作为对话，没有对应当前项目的“把选中技能 ID 限制到 Observation 集合”后处理；`<skill>` 名称是否来自候选列表并未强制校验。证据：[采样响应抽取](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:567)、 [Web 响应抽取](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:538)。
4. **提示词中的治疗结构不是树的实时展开。** 查询改写明确填 `Treatment_Structure="General"`；不能把模板写着“治疗结构”理解为实际注入了该阶段的完整结构。粗筛 system 虽提到扫描历史危机，但其 user 模板只收到目标与元技能库，并没有独立的对话历史字段。
5. **存在回退路径。** Web 提示链内部失败时使用 `fallback_messages` 生成回复，可能绕过技能链；采样逐轮检索重试耗尽后返回空候选列表。初始化失败的处理边界与该回复回退不同，不能混为一谈。证据：[Web 回退](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:143)、 [采样检索回退](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:523)。

## 4. 对照总结

| 问题 | psych_sandbox | Psych-new |
|---|---|---|
| 原始技能资源 | 与另一个项目相同 | 与另一个项目相同 |
| 是否逐层遍历整棵树做语义决策 | 否 | 否 |
| 流派、阶段 | 程序硬过滤 | 程序按对应库分区 |
| 高层祖先路径 | 归一化时不保留 | 保留用于结构匹配，但祖先说明未进入主链最终提示 |
| 元技能筛选依据 | 当前对话、允许记忆、目标、风险；模型选最多 3 个组 | 主要按会谈目标；默认请求 20 个叶元技能 |
| 微技能候选缩减 | 所选组全部返回，不做相关性排序 | 对 Trigger/When_to_Use 向量排序，默认前 5 个 |
| 最终选择 | Actor 输出技能 ID，程序限制在 Observation 内 | 咨询师输出技能名称标签，主要靠提示词约束 |
| 选技控制方式 | 固定 Planner → 程序 Observation → Actor 两阶段 | 程序预检索 → 将建议技能写入最终回复提示词 |
| 分层的主要收益 | 限定边界、分组减少一次看见的技能量、审计选技过程 | 限定分区、组级粗筛、缩小向量候选池与最终提示词 |

两个项目都真实利用了“流派/阶段分区”和“叶元技能→微技能”的结构；更高层树形结构的语义价值都没有被充分传递到最终模型。当前项目将最终语义选择留给模型；Psych-new 先由向量排名截断候选。因此不能简单说某一方的“技能树更完整”就一定选得更好。是否提高回复质量，需要同案例、同模型、同预算的检索/选技消融实验及人工评估，本次源码调查没有提供这种效果证据。

Psych-new 的逐文件调查、默认配置及离线 ID 边界验证，见 [详细调查](D:/0test/psych_sandbox/notes/psych_new_skill_analysis.md)。
