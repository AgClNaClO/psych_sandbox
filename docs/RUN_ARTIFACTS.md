# 运行产物、恢复与删除

每次调用单独建立目录。生成文件不得散落根目录，不得通过整理文档或缺失文件夹推定清理授权。正式运行与共享数据库须共同保留。

## 路径和内容

| 调用 | 位置及主要文件 |
|---|---|
| pytest | `runs/tests/<时间__pytest__编号>/`：run.json、测试摘要、results、logs、tmp、artifacts |
| simulate | `runs/runtime/<时间__案例__run编号>/`：run.json、result.json、trajectory.jsonl、report.html、logs、diagnostics、tmp |
| probe | `runs/runtime/<时间__probe-logprob-scoring__编号>/`：run.json、probe.json、diagnostics、tmp |
| data fetch | 独立运行目录的 external/psycheval；成功后更新 external-latest.json |
| Web SFT/DPO 导出 | 独立 export-sft / export-dpo 目录，文件名为经过验证的普通 `.jsonl` 名 |
| 技能进化试验 | 独立 `skill-experiment__exp-<编号>` 目录：`experiment.sqlite3`、`run.json`、各任务日志/诊断；完整验证的两组数据库和轨迹各在任务目录内 |

正式仿真共享 `runs/runtime/psychsandbox.sqlite3`，按 run_id 区分；Web 的队列和审计保存在 workbench 数据库。探针不写正式仿真记录。资源 `data/<therapy>`、assets、prompts 不属于运行产物。

`data convert` 是例外：在 `data/processed/.psycheval-staging-<编号>` 暂存，成功后原子更新 `data/processed/psycheval`；抽取缓存保存在忽略目录中，不覆盖旧运行。配置显式指定 database_path/trace_dir 时，Python 调用跟随指定路径，测试必须使用 tmp_path。

## 查找、恢复和探针

```powershell
psych-sandbox runs list
psych-sandbox simulate --case psycheval-cbt-001 --sessions 6 --resume-run <运行编号>
psych-sandbox visualize --run <运行编号>
psych-sandbox probe logprob-scoring --case psycheval-cbt-001 --instrument wai
```

CLI 从项目根运行；其他位置使用子命令之前的 `--root`。移动项目或虚拟环境后重新可编辑安装。恢复读取数据库的已提交会谈边界，向原目录追加；目录缺失的旧记录仍可能有评分，但不能直接续跑。报告输出必须位于该运行目录内。

probe.json 记录实际批量请求参数、方法版本、每项原始数值质量、分布、期望分、采样分和位置，或明确失败。合成对话标记为 fixture，不作为研究观测。首次对齐诊断可能另建独立 diagnostic 运行目录；保留它以解释端点行为。

Web 后台 Worker 在仿真完成或会谈边界停止后，持有运行锁生成 `report.html`，随后才将任务标记为成功或停止。若报告生成阶段失败，已完成的轨迹保留；已完成运行的任务重试只重建报告，不重新生成或评分。旧实验可以用 `visualize --run <id>` 补出报告。网页仅在检测到报告文件时显示报告入口。

网页支持统一轮数上限（1–50）或逐场轮数上限，以及 RFT 开关与候选数量（2–32）。这些参数保存进本次运行配置；轮数是上限，咨询师仍可提前结束。续跑与任务重试沿用原运行的轮数和 RFT 设置。浏览器保存所选任务编号，返回页面后从后台恢复任务状态并重放持久日志；任务在离开期间完成也能恢复查看。日志是阶段进度，并非逐 token 或逐轮流式输出。

数值输入允许暂时清空或输入 0，启动时按整数范围校验；会谈次数为 1–100，随机种子可以为 0。选择失败或已停止的历史运行后，可点击「从会谈边界续跑」：保留已提交会谈，从下一场恢复，使用原运行的案例、随机种子和 `run.json` 中的总会谈数，不读取左侧新实验草稿。页面显示已提交场数和恢复位置；原目录或恢复信息缺失、疗程已关闭时禁用入口，安全暂停不提供普通续跑。

## 测试隔离

conftest 每次创建独立目录，并接管 tmp_path、标准库临时目录、TEMP/TMP/TMPDIR、JUnit与日志；`PSYCHSANDBOX_RUNTIME_DIR` 只在测试期间指向本次 artifacts。pytest 缓存和字节码写入禁用。默认结束后删除本次测试目录；`PSYCHSANDBOX_KEEP_TESTS=1` 保留现场。硬终止可能留下 running 标记，它不代表成功。

Windows 测试进程在本次调用目录内创建临时目录时，使用父目录继承的 ACL，避免 Python 对 `0700` 设置的仅所有者权限阻断受限进程自身访问。此兼容处理仅在测试期间生效，不修改已有目录权限；其他路径和非 Windows 平台保持原行为。

JSON 产物在 Windows 上使用扩展长度路径执行原子写入，支持嵌套任务诊断目录；目录布局和对外保存的路径不变。

正常模拟不并发调用同一个 sandbox 的 run_case；候选在同一运行内独立分支。跨实验并行使用不同进程，不在同进程互改临时环境。

## 删除授权与故障恢复

```powershell
psych-sandbox runs delete --run <编号>
psych-sandbox runs delete --run <编号> --yes
psych-sandbox runs clean-tests
psych-sandbox runs clean-tests --yes
```

无 --yes 只预览。按编号删除仅清理所属文件和数据库记录，保留共享病例/技能、其他运行和目录入口 README。先检查 OS 运行锁；`.run.lock` 文件存在本身不证明进程持锁。删除日志记录阶段与失败，未完成删除会阻止续跑和报告写入；重试沿日志继续，不能因目录已不在就跳过授权。

历史迁移脚本 `scripts/migrate-run-artifacts.ps1` 仅在停止相关写入后使用：校验路径、避免覆盖并保存哈希清单；未知归属不猜测。此次功能实现不清理历史运行或共享数据库。

## Web 导出的数据语义

导出默认排除人工数据，显式启用时只包含闭环会谈。SFT 读取会前记忆，标记 context_reconstructed=true；原文未自动脱敏，anonymized=false。DPO 只配对同一已提交 RFT 批次、安全合格、共同前缀之后首个不同咨询师回复；失败候选不是自动负例。每次新目录防止同名覆盖，路径、行数和哈希写入导出审计。旧 exports 不自动迁移。
