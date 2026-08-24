# Phase 1 代码结构与数据流

本文描述当前最小可运行沙盒。BT、CBT、HET、PDT、PMT 五流派共用运行时，但保留各自病例、
技能树、概念化焦点和专属评测。参数训练、技能自动进化和临床验证尚未完成。

## 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| `domain/` | 5Ps、状态、计划、评测和轨迹等稳定契约 | API 调用和流程编排 |
| `datasets/` | 五流派原始案例转换和索引 | 技能选择 |
| `therapies/` | 流派、阶段目标、概念化焦点和量表映射 | 对话生成 |
| `agents/` | 来访者两阶段生成、咨询师 ReAct 与会后自评 | 持久化 |
| `skills/` | 技能注册、流派/阶段硬过滤和按 ID 查询 | 语义排序或自动晋升 |
| `runtime/` | 会谈编排、披露、安全、状态、记忆、计划和 SQLite | 训练基础模型 |
| `evaluation/` | 规则、真实性、纵向和整体 PsychEval 评测 | 临床诊断或疗效判断 |
| `visualization/` | 从已保存结果渲染离线 HTML/SVG | 修改运行状态 |

## 单轮流程

```text
允许记忆 + 当前计划 + 来访者话语
  → 输入风险和话题边界检查
  → 咨询师 API：Reasoning 摘要 + 分步 Planning + Action
  → Observation：按模型选择的元技能 ID 返回原子技能（无 BM25/向量/相关性排序）
  → 咨询师 API：选择策略、技能并生成结构化回复
  → 输出安全检查
  → 披露候选与歧义门控
  → 来访者私有状态规划（反应、行为、阻抗、信任）
  → 受限语言生成、事实 ID/台词证据/提前泄漏复核
  → 状态和审计轨迹更新
```

这里只保存可审计的推理摘要、计划、行动和观察，不要求或展示模型私密的逐 token 思维链。

## Session 边界流程

```text
完整会谈记录
  → 咨询师 API 自评目标与对话证据
  → 未达目标：改进项、修订策略、下次目标和元技能方向
  → E.7 信息提取 → E.8 ground-truth 门控档案合并 → E.9 临床摘要
  → 规则会谈评测 + 来访者真实性评测
  → 状态差值、相邻 session 趋势与阶段动作
  → PlanBuilder 合并咨询师再规划和纵向阶段动作
  → SQLite + JSONL + HTML
```

规则评测用于审计与安全证据，不直接驱动下一计划。一个 case 的全部 session 完成后，
`PsychEvalSupervisor` 才使用 `prompts/eval` 中代码映射到的 46 个量表文件做一次整体
Counselor-Level/Client-Level 评分；该评分同样不回写计划。

## 资源边界

- 可运行病例：`data/<bt|cbt|het|pdt|pmt>/*.json`，共 341 个。
- 技能树：`assets/skills/sect/`，677 个元技能、4481 个原子技能。
- `assets/profiles` 是保留的 sample/rft 参考资产，当前病例仓库不递归加载。
- `data/integrative` 是未注册的保留资源，不出现在可运行 case 列表。
- `prompts/` 共有 54 个提示词资产，全部由当前文件加载链消费：46 个整体督导量表，另有
  8 个生成提示词（`prompts/counselor/`、`prompts/simclient/`、`prompts/memory/`）由
  `psychsandbox/prompts.py` 的 `load_prompt` 在模块导入时读取，作为咨询师、来访者
  和 E.7/E.8/E.9 的生成提示词来源。

## 流派扩展边界

EFT 或 integrative 必须同时具备独立病例、三阶段技能树、`TherapyProfile`、流派专属量表和
心理学背景复核后才能注册；不能通过重命名 HET、BT 或 PMT 代替。
