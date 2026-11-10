# 正式运行与接口探针

截至 2026-11-10，每次仿真、数据下载/转换、导出、探针或技能独立试验各占一个时间/用途/编号目录。正式仿真共享 `psychsandbox.sqlite3`，按 run_id 关联会谈、轨迹和整体评分；探针只保存自己目录下的 `run.json` / `probe.json`。

数据转换目录保存 `run.json`、`progress.jsonl`、诊断和成功替换前的 `processed-backup/`；失败 staging 的位置记录在元数据中。技能试验保存独立 `experiment.sqlite3`，两组完整模拟各用自己的数据库与轨迹，不写正式运行库。

工作台的 `workbench.sqlite3` 保存队列、事件、审核与导出审计；启动器将两个常驻 Worker 的日志写入 `worker_long.log`、`worker_short.log`。网页阶段进度保存在事件表中，不能从候选轮数推断正式会谈已提交。

保留目录和共享数据库的一致备份。删除先用runs delete --run <编号>预览，明确确认才加--yes；不要直接删除文件夹后推定数据库已清理。规则见 [产物管理](../../docs/RUN_ARTIFACTS.md)。
