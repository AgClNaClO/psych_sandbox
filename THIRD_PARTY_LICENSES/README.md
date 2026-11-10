# 第三方许可与使用边界

| 来源 | 许可或借鉴范围 | 本仓库处理 |
|---|---|---|
| PsychEval病例、技能、提示与仓库材料 | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | 保留归属，仅非商业教学研究；data fetch取得上游LICENSE |
| AutoSkill / SkillEvo | MIT | 当前没有vendored上游代码，后续复制须保留MIT声明 |
| Zhang等线性表征论文 | 仅方法学借鉴：式8及概率质量门 | 未复制代码、权重或数据，见 [评分说明](../notes/logprob_scoring_borrowing.md) |

原始病例来源在 `data/` 下，来源画像在 `assets/profiles`；生产运行读取显式编译的 processed 缓存。转换生成的忽略目录 manifest 记录来源版本和 SHA-256；生成适配不取消上游限制。完整归属见 [NOTICE](../NOTICE.md)。

截至 2026-11-10，本目录是许可入口，不表示已经保存所有上游许可证副本。`data fetch psycheval` 获取固定提交的上游材料与 LICENSE；下载记录保留在本次运行目录。新引入的第三方实现需连同原许可声明维护，不能以方法参考表代替代码的许可证文件。

独立技能试验的基线、实验快照及 Web SFT/DPO 导出继续保留来源关系；实验隔离和 `experimental-unreviewed` 状态不会解除原资源限制。导出未自动脱敏，具体数据语义见 [产物管理](../docs/RUN_ARTIFACTS.md)。
