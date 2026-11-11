# 运行产物、恢复与删除

每次调用单独建立目录。生成文件不得散落根目录，不得通过整理文档或缺失文件夹推定清理授权。正式运行与共享数据库须共同保留。

本页按 2026-11-10 的路径与恢复实现核对。`runs/` 中三个受版本管理的 README 是入口文档，其他忽略产物保留原始实验含义。

## 路径和内容

| 调用 | 位置及主要文件 |
|---|---|
| pytest | `runs/tests/<时间__pytest__编号>/`：run.json、测试摘要、results、logs、tmp、artifacts |
| simulate | `runs/runtime/<时间__案例__run编号>/`：run.json、result.json、trajectory.jsonl、report.html、logs、diagnostics、tmp |
| probe | `runs/runtime/<时间__probe-logprob-scoring__编号>/`：run.json、probe.json、diagnostics、tmp |
| data fetch | 独立运行目录的 external/psycheval；成功后更新 external-latest.json |
| data convert | 独立 data-convert 目录：run.json、progress.jsonl、diagnostics，以及替换前的 processed-backup |
| Web SFT/DPO 导出 | 独立 export-sft / export-dpo 目录，文件名为经过验证的普通 `.jsonl` 名 |
| 技能进化试验 | 独立 `skill-experiment__exp-<编号>` 目录：`experiment.sqlite3`、`run.json`、各任务日志/诊断；完整验证的两组数据库和轨迹各在任务目录内 |

正式仿真共享 `runs/runtime/psychsandbox.sqlite3`，按 run_id 区分；Web 的队列和审计保存在 workbench 数据库。探针不写正式仿真记录。资源 `data/<therapy>`、assets、prompts 不属于运行产物。

`data convert` 是例外：在 `data/processed/.psycheval-staging-<编号>` 暂存，校验成功后发布到 `data/processed/psycheval`；抽取缓存保存在忽略目录中，不覆盖旧运行。配置显式指定 database_path/trace_dir 时，Python 调用跟随指定路径，测试必须使用 tmp_path。

转换默认并发 5 个抽取任务，可用 `--concurrency 1–32` 调整；实际 HTTP 请求仍受 `MODEL_MAX_CONCURRENCY` 共享上限约束（默认 5）。试转换和相同输入在本次调用内复用，缓存写入使用临时文件加原子替换。各阶段进度写入 stderr 与本次目录的 `progress.jsonl`，stdout 仅输出最终 manifest JSON，`--no-progress` 仅关闭终端显示。非交互日志按约 10% 的进度间隔输出。

模型调用向所属诊断目录追加 `request_metrics.jsonl`，按调用记录成功/失败/取消、Token 用量与逐次 HTTP 状态；`queue_seconds`、`response_seconds`、`retry_wait_seconds` 和 `overhead_seconds` 分别表示共享槽位排队、完整 HTTP 响应、重试之间的间隔及其他开销。间隔包含 SDK/外层退避与准备，不是纯睡眠时间。并行任务耗时不能直接相加作为疗程墙钟时间；统计不保存请求正文或密钥。

`runs/runtime/.model-request-slots/<端点与模型哈希>/` 是共享协调目录，不属于某次实验：每个槽位使用独立 OS 锁文件，跨本检出的进程生效，进程退出自动释放锁，空闲锁文件保留。测试跟随 `PSYCHSANDBOX_RUNTIME_DIR` 隔离。运行删除与本次改动均不清理这个目录或共享数据库；不同模型使用不同池，多个 Worker 应保持同一并发配置。

五流派依次转换，复用键包含来源路径、原文和用途；跨流派不共享抽取结果。manifest 分别记录 pilot 缓存命中、全量缓存命中、复用、跳过、回退和待复核计数；这些计数不是人工审核通过率。抽取前后的来源摘要必须一致，转换过程中不得编辑原始病例。

转换持有 `data/processed/.run.lock` 的 OS 锁。新数据通过五流派合并和完整加载校验后，将旧 processed 目录移入本次调用的 `processed-backup/` 再发布新目录；发布失败恢复旧目录。失败 staging 保留，位置记录在 `run.json`，不自动删除历史产物或共享数据库。两个目录重命名之间存在短暂切换窗口；异常断电时可按 `run.json` 中的输出、staging 与备份路径检查恢复。

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

网页支持统一轮数上限（1–50）或逐场轮数上限，以及 RFT 开关与候选数量（2–32）。这些参数保存进本次运行配置；轮数是上限，咨询师仍可提前结束。续跑与任务重试沿用原运行的轮数和 RFT 设置。浏览器保存所选实验编号，返回页面后恢复当前阶段、已提交场数、候选轮数和量表计数；任务在离开期间完成也能恢复查看。结构化进度作为 `simulation_status` 事件写入现有工作台数据库，不新增运行目录；写入受 attempt、owner 和租约保护。任务接口返回当前 attempt 的最新快照，实时事件按 revision 合并。进度是已完成步骤的计数，不是 token 流，也不把轮数上限当成必达轮数或整体耗时百分比。

数值输入允许暂时清空或输入 0，启动时按整数范围校验；会谈次数为 1–100，随机种子可以为 0。选择失败或已停止的历史运行后，可点击「从会谈边界续跑」：保留已提交会谈，从下一场恢复，使用原运行的案例、随机种子和 `run.json` 中的总会谈数，不读取左侧新实验草稿。页面显示已提交场数和恢复位置；原目录或恢复信息缺失、疗程已关闭时禁用入口，安全暂停不提供普通续跑。

已提交场数与当前候选轮数独立统计；会后整理完成并落库后才增加提交计数。`finished` 表示仿真轨迹已保存，Worker 随后仍可能处于报告生成阶段；以任务最终状态确认工作台操作结束。缺少新进度快照的旧任务仍可显示已存会谈，不伪造当前候选计数。

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
