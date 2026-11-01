# 测试调用隔离

pytest每次建立新目录，测试文件使用tmp_path；环境临时目录、日志和JUnit都归本次调用。正常结束默认清除此目录，PSYCHSANDBOX_KEEP_TESTS=1可保留失败现场。

手动清理先执行runs clean-tests预览，确认后才使用--yes。这个目录独立于正式运行数据库；详见 [产物管理](../../docs/RUN_ARTIFACTS.md)。
