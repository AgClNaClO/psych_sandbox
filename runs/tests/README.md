# 测试运行

每次执行 `pytest -q` 自动新增一个 `时间__pytest__唯一编号/`：

- `summary.txt`、`run.json`：结果摘要、退出码、执行参数和起止时间。
- `results/junit.xml`：标准测试报告。
- `results/tests.jsonl`：逐测试的 setup/call/teardown 结果、捕获输出及失败详情。
- `logs/pytest.log`：测试日志。
- `tmp/pytest/`：按测试名称区分的 `tmp_path` 文件，包括测试数据库、轨迹及报告。
- `tmp/`：标准库及子进程临时文件。
- `artifacts/`：测试中使用默认路径的仿真和 CLI 输出，不混入正式运行。

测试结束后保留文件。可以在所有测试进程退出后，按次手动删除不需要的目录。
