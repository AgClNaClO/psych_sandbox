# 来源画像的保留范围

这里保存Psych-new的五流派sample/rft人物画像，以及_excluded来源记录，用于核查和后续适配研究。历史盘点为1027份JSON：每流派196份，另有排除记录47份；这些不是341个沙盒病例的另一个索引。

CaseRepository.from_project不递归加载本目录。生产病例由data/<therapy>或data/processed/psycheval读取。若要启用这些画像，须先明确dataset adapter、ID映射、去重、来源许可及隔离测试，不能只换一个目录参数。当前任务不启用或改写这些资产。
