# 正式运行与接口探针

每次仿真、下载、导出或探针各占一个时间/用途/编号目录。正式仿真共享psychsandbox.sqlite3，按run_id关联会谈、轨迹和整体评分；探针只保存自己目录下的run.json/probe.json。

保留目录和共享数据库的一致备份。删除先用runs delete --run <编号>预览，明确确认才加--yes；不要直接删除文件夹后推定数据库已清理。规则见 [产物管理](../../docs/RUN_ARTIFACTS.md)。
