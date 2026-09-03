# 测试与实际运行的文件约定

不需要额外指定输出参数：原有 `pytest -q`、`psych-sandbox simulate`、`data fetch` 和 `data convert` 命令会自动使用新目录。输入资源 `data/<therapy>`、`assets/`、`prompts/` 以及虚拟环境 `.venv/` 保持原位。

## 当前本机位置与迁移

项目现位于 `D:\0test\psych_sandbox`。相对输出规则不变；从该目录启动，默认产物会写入新位置的 `runs/`。若在别处启动 CLI，须在子命令之前指定 `--root D:\0test\psych_sandbox`。移动 `.venv` 后应先重新安装可编辑项目，见 [README 的迁移检查](../README.md#53-迁移后的安装检查powershell)。

此前“清理目录后数据库没有记录”的说明有误：正式运行保存在 `experiment_runs` 表，删除文件夹不会清除这些记录。当前可用下面的 `runs list` 核对数据库、目录及删除状态；本次没有删除现有运行。目录已缺失的旧记录仍可读取已保存评分，但不能直接续跑；需要彻底清理时使用统一删除入口。

## 自动归档结构

```text
runs/
├── README.md
├── tests/
│   ├── README.md
│   └── 20260827-190000-123456__pytest__唯一编号/
│       ├── run.json
│       ├── summary.txt
│       ├── results/          junit.xml、tests.jsonl
│       ├── logs/             pytest.log
│       ├── tmp/pytest/       每条测试自己的临时目录
│       └── artifacts/        使用默认路径的测试仿真产物
└── runtime/
    ├── README.md
    ├── psychsandbox.sqlite3  所有正式运行共享，记录由 run_id 区分
    ├── 时间__psycheval-cbt-001__run-编号/
    │   ├── run.json          案例、种子、状态、目标会谈数
    │   ├── result.json       本次完整结果（成功完成后）
    │   ├── trajectory.jsonl  每完成一个会谈追加一行
    │   ├── report.html       离线报告（CLI 默认生成）
    │   ├── logs/             progress.log；失败时有 errors.log
    │   ├── diagnostics/      API 结构化输出错误诊断
    │   └── tmp/              标准库和子进程临时文件
    └── 时间__data-convert-cbt__唯一编号/
        ├── run.json
        ├── tmp/
        └── processed/psycheval/
```

## 查找与续跑

目录时间使用本机时区。新的仿真仍返回 `run-xxxxxxxxxxxx`；可在资源管理器按编号搜索目录。终端会显示完整产物路径。先看 `run.json`，再打开 HTML 或测试摘要；失败运行也保留现场。

```bat
pytest -q
psych-sandbox simulate --case psycheval-cbt-001 --sessions 3
psych-sandbox visualize --run run-xxxxxxxxxxxx
psych-sandbox evaluate --run run-xxxxxxxxxxxx
psych-sandbox simulate --case psycheval-cbt-001 --sessions 6 --resume-run run-xxxxxxxxxxxx
```

重复普通运行会创建新目录；`--resume-run` 从原数据库恢复到会谈边界，继续向原目录追加轨迹和日志，更新结果及报告。`visualize --output alternate.html` 也写入该运行目录；拒绝指向目录外的路径。

`--json` 仍在标准输出返回 JSON，同时保存 `result.json`；`--no-visualization` 只跳过 HTML。直接调用 `CounselingSandbox` 同样按次归档，可从 `sandbox.run_dir` 获取当前运行目录。显式传入 `database_path`、`trace_dir` 的 Python 调用仍按调用者指定的位置写入；测试应使用 `tmp_path`，临时脚本应从 `runs/tests` 或 `runs/runtime` 分配目录。

## 测试隔离

`tests/conftest.py` 为每次 pytest 建立独立目录，配置 `tmp_path`、标准库 `tempfile`、 `TEMP/TMP/TMPDIR`、JUnit 和日志。`PSYCHSANDBOX_RUNTIME_DIR` 在测试期间指向本次 `artifacts/`，子进程自动继承，结束后恢复。该环境变量是内部隔离接口，正常运行无需设置。 pytest 的 `--basetemp`、`--junitxml`、`--log-file` 由本仓库约定统一接管，避免写到外部或清空旧目录。 pytest 缓存插件保持禁用；测试主体禁用 Python 字节码写入。

文件不会在测试结束后自动删除；失败、取消和异常时可查看已保存的部分输出。硬终止进程时 `run.json` 可能仍为 `running`，不应将它当成成功。同一个 `CounselingSandbox` 实例应顺序运行；运行期临时目录使用进程环境，并行实验请使用独立进程，不在同一进程中并发修改临时目录。

## 下载、转换与历史迁移

数据命令每次建立独立目录。成功后才更新 `external-latest.json` 或 `processed-latest.json`；失败不会替换上一份可用缓存。旧目录仍完整保留，正常仿真继续直接读取仓库中的原始病例。

仓库已有的扁平 `runs/*.jsonl`、HTML、数据库和可归属诊断可用以下 PowerShell 脚本迁移：

```powershell
.\scripts\migrate-run-artifacts.ps1
```

先退出仿真、数据库查看器及相关写入进程。脚本检查移动范围，不覆盖同名文件，并为文件记录迁移前后的 SHA-256 校验；再次执行不会重复移动已经归档的文件。原始运行编号不变，无法确认归属的旧文件放入明确标记的历史目录，不猜测其对应运行。迁移清单保存在 `runtime/*__migration.json`。

## 保留与清理

测试产物可在进程退出后按次删除；原有完成后自动删除临时目录的行为已取消，因此空间占用会增长。正式运行的目录与共享 SQLite 数据库应一起备份。只删除报告目录不会删除数据库记录，也不要只删除数据库，否则评估、重新生成报告和续跑将失去来源。诊断、轨迹和报告可能含有案例内容；全部被 Git 忽略，不提交、不自动上传。

### 清理测试日志（runs clean-tests）

`runs/tests` 下的测试产物与正式运行数据库独立，可通过以下命令清理，无需模型密钥、不调用 API：

```powershell
Set-Location -LiteralPath 'D:\0test\psych_sandbox'
.\.venv\Scripts\python.exe -B -m psychsandbox runs clean-tests
.\.venv\Scripts\python.exe -B -m psychsandbox runs clean-tests --yes
```

默认只预览 `runs/tests` 下的测试目录（不含 `README.md`），加 `--yes` 才实际删除。`pytest` 会话结束（无论成败）默认自动删除本次调用目录，避免 `runs/tests` 持续增长；如需保留失败现场以便排查，设置环境变量 `PSYCHSANDBOX_KEEP_TESTS=1`。

### 按运行编号统一删除

此入口不需要模型密钥，不调用任何 API。`--root` 指向项目根目录；清理使用该项目 YAML 的 `database_path` 和 `trace_dir`，默认就是 `runs/runtime`。先列出并预览：

```powershell
Set-Location -LiteralPath 'D:\0test\psych_sandbox'
.\.venv\Scripts\python.exe -B -m psychsandbox runs list
.\.venv\Scripts\python.exe -B -m psychsandbox runs delete --run run-xxxxxxxxxxxx
```

将占位符换成实际编号。预览显示数据库、目标目录、各表记录数和已有删除状态；**不创建数据库、目录、锁或删除日志，也不修改记录**。核对后明确确认永久删除：

```powershell
.\.venv\Scripts\python.exe -B -m psychsandbox runs delete --run run-xxxxxxxxxxxx --yes
```

删除范围是该编号的运行目录及关联数据库记录：会谈、轮次、记忆、各类评分、轨迹、RFT 批次与候选。其他运行和共享 `cases`、`skills`、`skill_versions` 保留，不删除整个 SQLite 文件。数据库文件大小不会因删除记录立刻减少，不能用文件大小判断是否清理成功。这是逻辑清理，不保证磁盘取证层面的安全擦除。

正常运行和报告生成持有运行锁；删除遇到占用会失败，不强行停止任务。已中断且释放锁的运行可以确认删除；若状态仍为 `running` 但目录已经丢失，无法核验锁，入口会拒绝，须先确认任务已停止。重复目录、元数据编号不符、链接/junction 或运行目录包含共享数据库时也会拒绝。

### 中断、重试及缺失目录

文件系统与 SQLite 不能合成同一个事务。确认删除后，程序先在运行锁内写入 `runs/runtime/.deletions/<run_id>/deletion.json` 并标记 `deleting`，再释放锁删除目录，最后以数据库事务删除全部关联记录。此时续跑和重新生成报告均被阻止，避免删除后重新产生文件。

失败时保留错误与删除状态；重新执行同一条 `--yes` 命令即可继续，已完成的删除可重复执行。数据库事务失败会整体回滚本次记录删除；若文件已删，不会凭空恢复文件，但数据库记录和删除日志仍在，重试可完成清理。日志写入失败时，先前的 `deleting` 标记仍阻止写入，应排除磁盘或权限问题后再试。不要手动删除删除日志来绕过保护。

`runs list` 也展示删除日志，`deletion_status=completed` 是清理历史，不代表正式运行记录仍然存在。该日志仅保留编号、路径、记录数量、状态和错误，不保存原始对话或候选内容。

已有“数据库有记录、目录已手动删除”的情况，可按同一编号预览/删除剩余记录；只有目录、数据库缺失时也可清理匹配目录，且不会新建空数据库。此入口不监视资源管理器操作，也不自动清理缺失记录。 `runs/tests` 中单次测试目录仍与正式运行数据库独立，测试产物可在测试结束后按次清理。

## 会谈多候选

开启 RFT 后，每场会谈另有 `rollouts/s001__batch-编号/`，保留输入快照、所有候选（含失败前缀）、评分和选优结果。续跑同一未提交会谈会新建批次；只有胜出会谈进入原有正式轨迹。详见 [会谈 RFT](SESSION_RFT.md)。候选并行不改变进程级临时目录；同进程多个 `run_case` 会明确拒绝。
