# 实际运行

仿真目录为 `时间__案例ID__run-编号/`。先打开 `report.html`；`result.json` 是完整结果，
`trajectory.jsonl` 是逐会谈轨迹，`run.json` 是运行状态。`logs/` 保存进度和失败详情，
`diagnostics/` 保存模型输出诊断，`tmp/` 保存临时文件。

启用整场会谈 RFT 时，`rollouts/s001__batch-编号/` 保存本场的输入、`selection.json`、
`candidate-001.json` 等所有候选；失败诊断可位于对应批次的 `d001/`。HTML 展示评分与选优，
正式 `trajectory.jsonl` 只包含已提交的胜出会谈。详见 [会谈 RFT](../../docs/SESSION_RFT.md)。

`psychsandbox.sqlite3` 是所有实际仿真共享的数据库，按运行编号区分记录；
`evaluate`、`report`、`visualize` 和 `--resume-run` 依赖它，请与运行目录一起备份。

完整删除请用 `psych-sandbox runs delete --run <编号>` 先预览，再加 `--yes` 确认。
它同时清理目录和数据库关联记录；`.deletions/<编号>/deletion.json` 留存删除状态与错误，
中断后可重试。直接删除文件夹不会自动同步数据库。详见 [清理约定](../../docs/RUN_ARTIFACTS.md)。

数据命令按次保存为 `时间__data-fetch或data-convert-流派__编号/`。
`external-latest.json`、`processed-latest.json` 指向最近一次成功的数据产物。
`*__migration.json` 是旧文件迁移清单；`*__legacy-unassigned__*/` 保留无法明确归属的旧产物。
