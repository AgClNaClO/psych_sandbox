# Phase 1 代码结构与数据流

本文只描述第一阶段最小可运行沙盒。参数训练、技能自动进化、完整五流派和临床验证不在本阶段。

## 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| `domain/` | 5Ps、状态、计划、评测、轨迹等稳定契约 | 模型调用和业务流程 |
| `therapies/` | 流派名称、概念化焦点、阶段目标、专属指标 | 技能检索和回复生成 |
| `agents/` | 来访者两阶段生成、咨询师行动、规则督导 | 持久化和跨会谈编排 |
| `skills/` | 技能注册、合并、流派/阶段过滤和 BM25 检索 | 自动晋升技能 |
| `runtime/` | 会谈编排、披露、安全、状态、记忆、反馈计划和 SQLite | 训练基础模型 |
| `evaluation/` | 纵向差值、趋势和阶段动作 | 临床诊断或疗效判断 |
| `visualization/` | 将已保存轨迹渲染为离线 HTML/SVG | 修改运行状态 |

## 单轮数据流

```text
允许记忆 + 当前计划 + 来访者话语
  → 风险检查
  → 流派/阶段技能检索
  → 咨询师结构化决策与回复
  → 输出安全检查
  → 来访者披露门控
  → 反应/行为/抗拒规划
  → 受限语言生成与泄漏复核
  → 状态更新与审计记录
```

## 会谈边界数据流

```text
会谈记录
  → 咨询师侧规则督导（安全/泄漏/阶段/人设的一致性校验，仅用于审计）
  → 来访者仿真真实性评测
  → 状态差值与相邻会谈趋势（由目标完成度与状态驱动，非量表驱动）
  → continue / advance / regress / hold / close
  → 进度驱动的下一次计划（PlanBuilder，与督导解耦）
  → SQLite + JSONL + HTML
```

## 督导师定位（与 PsychEval 对齐）

- 论文中的 LLM supervisor 是 **external supervisory paradigm**：在整条多 session
  轨迹完成后，用心理量表做一次性评估，分为 **Counselor-Level**（临床胜任力）
  与 **Client-Level**（仿真保真度），**不参与逐 session 规划**。
- 因此本阶段的逐 session 督导仅保留确定性规则校验（安全、信息泄漏、阶段/人设
  一致性），用于审计与安全门控。
- 整体督导由 `PsychEvalSupervisor` 在 `run_case` 的所有 session 结束后执行一次，
  直接使用官方 `eval/prompts_cn` 下的量表提示词，输出 `RunResult.holistic_report`。
- 下一 session 的计划由 `PlanBuilder` 依据纵向进展信号（目标完成度 + 状态差值）
  生成，不再回写督导师的评分反馈。

## 第一阶段流派边界

- CBT 使用 PsychEval 案例与技能。
- 人本—存在取向只用于验证多流派适配接口，使用项目内合成案例和显式标记的演示技能。
- EFT、心理动力、行为、后现代和整合治疗留到后续阶段，未注册的流派会被拒绝。

## 可视化

`simulate` 默认在 `runs/` 生成 HTML；也可运行：

```bat
psych-sandbox visualize --run run-xxxxxxxxxxxx
```

页面完全离线，不请求外部脚本、字体或图表服务。
