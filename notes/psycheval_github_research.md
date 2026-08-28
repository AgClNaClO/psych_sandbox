# PsychEval 官方 GitHub 源码核查笔记

> 文档性质：这是对上游固定提交的历史核查记录，不是本仓库当前运行说明。本地实现入口、资源使用状态和流程边界以根 `README.md`、`docs/PHASE1_IMPLEMENTATION.md` 与当前源码为准。

核查对象：官方仓库 `ECNU-ICALK/PsychEval`，固定提交 [`e04df535749e5bca76fcc45d9a85f3f46a082d91`](https://github.com/ECNU-ICALK/PsychEval/commit/e04df535749e5bca76fcc45d9a85f3f46a082d91)。以下只写仓库源码和数据能够直接验证的事实。

## 最重要的边界

当前公开仓库**没有**论文中“从案例构建来访者模拟器、再与咨询师模型逐轮生成对话”的可运行流水线，也没有来访者/咨询师生成 prompt、训练脚本或生成模型调用代码。仓库树只有 `data/`、`eval/` 和图片；README 也把公开内容定义为数据集与评测框架（[`README.md` L44–71](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L44-L71)）。因此，源码可以说明**最终构造物的形态及评测数据流**，但不能独立复现两个 agent 的生成过程。README 仅概述：Client Simulator 用于真实角色扮演，Supervisor Agent 用于专业评分（[`README.md` L8–19](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L8-L19)）。

## 来访者（client）如何被表示

每个案例不是一个简单 persona 字符串，而是一个纵向状态包。以官方 [`data/cbt/1.json`](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/data/cbt/1.json) 为例，顶层含 `theoretical`、`client_id`、`client_info`、`global_plan`、`sessions`。`client_info` 包含人口学与语言特征、主诉、主题、核心信念、成长经历、特殊情境和核心诉求；特殊情境进一步拆为事件、条件假设、补偿策略、自动思维、认知模式。这些字段共同约束模拟来访者“知道什么、如何说、为何这样反应”。

状态不是每次会谈重置。每个 session 保存 `session_summary`（摘要、目标完成度、来访者状态分析、作业、本次获得/合并的信息、下一次计划）以及 `client_info_last`（更新后的纵向档案）。这表明数据层面的记忆链是：初始档案 → 本次对话 → 信息抽取/合并与状态分析 → 更新档案和下一次计划 → 后续 session。公开仓库没有显示是哪一个模型或 prompt 完成这些更新，不能把字段结构误说成已开源的 simulator 实现。

## 咨询师（counselor）如何被表示

咨询师侧首先受疗法和长期计划约束。README 声明 6–10 次会谈分“个案概念化、核心干预、巩固/结束”三阶段，并覆盖多疗法（[`README.md` L8–18](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L8-L18)）。数据目录实际按 `bt/cbt/het/integrative/pdt/pmt` 分组。CBT 样例的 `global_plan` 将 7 次会谈分为“问题概念化与目标设定（1–2）—核心认知与行为干预（3–6）—巩固与复发预防（7）”；每次又有 `session_goals` 与 `suggest_skills`。

`suggest_skills` 是分层技能条件：`meta_skill` 下列出多个 `micro_skills`，每个原子技能有 ID、名称、描述、适用时机和触发条件。实际 `Counselor` 消息还保留 `<think>` 轨迹，内部显式写 `assessment`、`client_state`、`skill`、`strategy`，随后才是面向来访者的回复。由此可见，最终咨询师数据样例是“疗法标签 + 三阶段全局计划 + session 目标 + 检索/建议技能 + 对当前来访者状态的判断 + 策略 + 外显回复”的结构；但仓库未公开负责产生该轨迹的 counselor agent 代码或模型配置。

## 对话与评测数据流

公开代码实现的是**离线评测**。管理器读取 `client_info` 和 `sessions`（[`evaluation_multi.py` L458–486](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L458-L486)），把 `Client/user` 规范为 `client:`、把 `Counselor/assistant` 规范为 `counselor:`，并删除咨询师 `<think>` 块（[`evaluation_multi.py` L488–518](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L488-L518)）。随后将档案和单个 session 对话交给所有注册指标；每个指标各建一个 OpenAI-compatible 客户端并并发调用（[`evaluation_multi.py` L620–670](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L620-L670)）。

模型端点、密钥、模型名来自 `CHAT_API_BASE / CHAT_API_KEY / CHAT_MODEL_NAME`；默认模型为 DeepSeek-V3.1-Terminus，调用 `AsyncOpenAI.chat.completions.create`，带并发限制、限流与指数退避重试（[`gpt5_chat_client.py` L29–75](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/utils/gpt5_chat_client.py#L29-L75)、[`L92–142`](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/utils/gpt5_chat_client.py#L92-L142)）。这是 **Supervisor/Judge 的模型调用**，不是来访者或咨询师的生成调用。

评测同时分咨询师侧和来访者侧。WAI 将档案与对话渲染进 prompt、要求 JSON Schema 输出，并返回 `{"counselor": score}`（[`wai.py` L26–68](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/methods/counselor/wai.py#L26-L68)）；其 prompt 明确把 judge 设为“专业的第三方督导”（[`wai.txt` L1–14](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/prompts_cn/wai/wai.txt#L1-L14)）。SCL-90 使用相同输入方式推断来访者症状并返回 `{"client": score}`（[`scl_90.py` L24–64](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/methods/client/scl_90.py#L24-L64)）。所以三者角色应严格区分：Client Simulator 产出角色扮演数据，Counselor 产出干预回复，Supervisor 只在生成后读取档案与可见对话评分。
