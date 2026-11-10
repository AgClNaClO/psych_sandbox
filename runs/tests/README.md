# 测试调用隔离

pytest每次建立新目录，测试文件使用tmp_path；环境临时目录、日志和JUnit都归本次调用。正常结束默认清除此目录，PSYCHSANDBOX_KEEP_TESTS=1可保留失败现场。

截至 2026-11-10，标准验证入口为 Python 3.11+、`.[dev]` 环境中的 `python -B -m pytest -q`。每次调用包含 `run.json`、`results/`、`logs/`、`tmp/` 和隔离运行产物 `artifacts/`；目录存在或残留 running 标记均不证明测试成功。

Windows 下仅对本次隔离临时目录继承父目录 ACL，避免受限进程被仅所有者权限阻断；不修改历史目录权限。测试及 CLI 子进程通过 `PSYCHSANDBOX_RUNTIME_DIR` 使用本次 artifacts，不写正式共享仿真数据库。
手动清理先执行runs clean-tests预览，确认后才使用--yes。这个目录独立于正式运行数据库；详见 [产物管理](../../docs/RUN_ARTIFACTS.md)。
