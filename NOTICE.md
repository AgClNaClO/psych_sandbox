# 第三方材料与方法归属

本仓库改编 [PsychEval](https://github.com/ECNU-ICALK/PsychEval) 的病例、分层技能和量表提示，转换固定版本为e04df535749e5bca76fcc45d9a85f3f46a082d91。来源材料采用CC BY-NC 4.0，仅用于非商业教学研究。归一化字段、病例切分、证据披露层、流派前缀ID与来源清单属于本项目适配，原始技能ID保留。

assets/profiles保存本机Psych-new研究树中的来源副本；资产存在不代表生产加载。PsychAgent论文启发记忆、候选选优与技能演化研究设计；这里不宣称复现未公开训练或模型权重。AutoSkill/SkillEvo未被复制进仓库，未来复制MIT代码必须保留原声明并通过适配器接入。

2026-11-10 的实现说明：独立技能进化试验在本项目代码中实现来源会谈提取、语义查重、Append/Merge/Skip 和隔离验证，基线继续使用上述原始技能资源。实验快照、转换或导出不会取消来源材料的归属与非商业使用限制，也不代表已经训练或发布新的模型。流程见 [试验文档](docs/workbench/SKILL_EVOLUTION_EXPERIMENT.md)。

逐条目logprob评分借鉴Zhang et al., *Mechanistic control of large language models as simulated participants via linear representation*，DOI [10.1038/s44387-026-00160-9](https://doi.org/10.1038/s44387-026-00160-9)的式8和质量门；实现、请求与审计由本项目编写，未包含该项目代码、权重或数据。它不迁移激活控制。具体差异见 [方法记录](notes/logprob_scoring_borrowing.md)。

许可汇总见 [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md)。
