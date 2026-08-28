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
| `skills/` | 技能注册、硬过滤、按 ID 展开和超量候选的向量筛选 | 最终适用判断或自动晋升 |
| `runtime/` | 会谈编排、候选隔离与选优、披露、安全、状态、记忆、计划和 SQLite | 训练基础模型 |
| `runtime/run_management.py` | 只读预览、按编号同步删除、失败日志与重试 | 自动监视目录或删除共享案例/技能 |
| `evaluation/` | 规则、真实性、纵向、独立候选 RFT 评分和整体 PsychEval 评测 | 临床诊断或疗效判断 |
| `visualization/` | 从已保存结果渲染离线 HTML/SVG | 修改运行状态 |

## 单轮流程

```text
允许记忆 + 当前计划 + 来访者话语
  → 输入风险和话题边界检查
  → 咨询师 API：Reasoning 摘要 + 分步 Planning + Action
  → 按有公开依据的元技能 ID 精确展开原子技能；超阈值才按向量筛选
  → 咨询师 API：核对适用依据、选择策略和技能、生成结构化回复
  → 仅无效查询/候选不适合时，排除旧组后允许一次纠错；详见 SKILL_SELECTION.md
  → 输出安全检查
  → 披露候选与歧义门控
  → 来访者私有状态规划（反应、行为、阻抗、信任）
  → 受限语言生成、事实 ID/台词证据/提前泄漏复核
  → 状态和审计轨迹更新
```

这里只保存可审计的推理摘要、计划、行动和观察，不要求或展示模型私密的逐 token 思维链。

## Session 边界流程

```text
会前计划、记忆、初始状态
  → 普通模式：生成一个完整会谈
    或 RFT：隔离并发生成完整候选 → 规则门槛/去重 → 独立评分/资格门槛 → 选优
  → 正式会谈（RFT 仅胜出者）完成规则和来访者真实性评测
  → 状态差值、相邻 session 趋势与阶段动作 → 暂定下一计划
  → 咨询师 API 自评目标与证据；未达目标时提出策略和目标修订
  → PlanBuilder 合并咨询师再规划和纵向阶段动作
  → E.7 信息提取 → E.8 ground-truth 门控档案合并 → E.9 临床摘要 → 记忆整理
  → SQLite 正式提交 + JSONL 同步；CLI 完成后生成 HTML
```

规则评测用于审计与安全证据，不直接驱动下一计划。一个 case 的全部 session 完成后，
`PsychEvalSupervisor` 才使用 `prompts/eval` 中代码映射到的 46 个量表文件做一次整体
Counselor-Level/Client-Level 评分；该评分同样不回写计划。

RFT 默认关闭，启用后默认 3 条候选；候选以整场会谈为单位，不是单轮回复候选。候选失败、重复或落选时只留在独立
审计存储；少于两个不同且合格候选则失败，任何候选出现即时风险则整批暂停。选优后仍须完成
会后处理与正式提交，才能成为下一场基线。评分公式、并发和恢复见 [会谈 RFT](SESSION_RFT.md)。

## 资源边界

- 可运行病例：`data/<bt|cbt|het|pdt|pmt>/*.json`，共 341 个。
- 技能树：`assets/skills/sect/`，677 个元技能、4481 个原子技能。
- `assets/profiles` 是保留的 sample/rft 参考资产，当前病例仓库不递归加载。
- `data/integrative` 是未注册的保留资源，不出现在可运行 case 列表。
- `prompts/` 共有 56 个提示词资产，其中 55 个有调用点：46 个整体督导量表、8 个普通生成模板，
  加上仅开启 RFT 时使用的 `rft/session_judge.jinja2`。生成/评分提示词以 Jinja2
  模板存放，由具体 agent 构造输入字典并调用 `psychsandbox/prompts.py::render_prompt`，
  结构化输出按 Pydantic schema 解析。额外的 `client/dialogue.jinja2` 是参考资产，没有生产调用点。

CLI 经 `default_config(root)` 加载 `configs/runtime.yaml` 后应用显式命令行参数。
本机路径已迁至 `D:\0test\psych_sandbox`；测试/运行仍按次写入 `runs/tests` 与 `runs/runtime`，
虚拟环境的可编辑安装需要在新位置重新安装，见 [README](../README.md)。

## 流派扩展边界

EFT 或 integrative 必须同时具备独立病例、三阶段技能树、`TherapyProfile`、流派专属量表和
心理学背景复核后才能注册；不能通过重命名 HET、BT 或 PMT 代替。
