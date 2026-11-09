# 提示词与评分目录

生产生成模板在counselor、simclient、memory中，由Jinja2渲染，模型返回Pydantic契约。咨询师规划/执行/自评、来访者规划/台词和E.7/E.8/E.9各自有入口；通用prompt_pipeline辅助函数不代表所有调用已统一经过它。

## 量表

46个eval量表提示文件供RFT候选评估和完整疗程督导复用。固定映射在Instrument.prompt_files，条目目录在eval/_scoring/item_catalog.json：ID、原始范围、来源和换行规范化后的UTF-8 SHA-256必须与提示词一致。

item_logprob_v2直接获取每个原提示文件的批量JSON及位置logprobs，无response_format/tools。每项score连续化后再聚合；旧instrument_rating总体判分提示已移除。修改量表要人工复核条目目录与哈希，不能只让程序自动接受新文本。

范围：WAI/HTAIS/custom_dim/MITI/EFT-TFS/IPO/PANAS为1–5；TES为1–7；CTRS/PSC为0–6；SCL-90/SRS/STAI/SFBT为0–4；BDI-II为0–3；CCT为0–2；RRO为1–5并含反向项。RRO/PANAS维持原复合公式。

## 信息边界与参考模板

咨询师的 Planner 和 Actor 系统提示定义任务、权限和证据规则。公开背景、后台议程、允许的跨场记忆、完整场内对话和技能信息通过 JSON 字段提供。选技纠错原因也由 JSON 字段传入。技能输入和审计字段见 [技能选择](../docs/SKILL_SELECTION.md)。

E.9 会后总结使用咨询师视角，根据完整对话判断跨会谈待办，并在同一结果的 `item_updates` 中提供已有 ID、明确状态和判断依据。

simclient台词模板只接收授权事实、已说片段和表达指令，不能为复用模板而引入完整私密画像。client/dialogue.jinja2是来源/风格参考，生产调用仍是simclient模板；它的输入名和纯文本输出不符合ClientUtterance契约，不能只改路径启用。

报告展示模型主动返回的简短规划/决策摘要与证据，不读取或索取供应商内部思维链。修改生成提示时同步相应版本并检查渲染、结构化输出、披露与跨会谈边界；最后跑pytest。评分细节见 [方法说明](../notes/logprob_scoring_borrowing.md)。
