# 本地科研Web工作台

工作台提供自动实验、人工多会谈、技能版本/审核、实验比较及受控数据导出。运行时规则与CLI一致，生产调用真实API；测试替身不进入产品路径。

新增可选的[技能进化独立试验](SKILL_EVOLUTION_EXPERIMENT.md)：默认关闭，单独保存实验快照和验证轨迹，Web 顶部“进化试验”进入；不更新正式技能发布指针。

## 启动和开发

根目录运行run_workbench.bat，先初始化数据库，再启动long/short两个Worker和端口8001的本地服务，浏览器访问 [工作台](http://127.0.0.1:8001)。stop_workbench.bat仅停止本项目.venv启动的工作台进程。手动调试服务仍使用默认端口8000，与前端开发代理保持一致：

```powershell
.\.venv\Scripts\python.exe -B -m psychsandbox.workbench.server --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

单独运行服务不会替你启动任务Worker。生产静态包来自frontend构建，见 [前端说明](../../frontend/README.md)。密钥留在环境/本机.env，不进入前端；服务定位为本机研究工具。

后台 Worker 在启动时加载 Python 代码。更新代码后，先让当前任务结束或在会谈边界停止，再运行 `stop_workbench.bat` 和 `run_workbench.bat`。启动脚本发现本项目已有服务或 Worker 时会退出，避免旧 Worker 与新 Worker 争抢任务。两个 Worker 的启动和认领日志分别写入 `runs/runtime/worker_long.log` 和 `runs/runtime/worker_short.log`。

API 与两个 Worker 可同时初始化工作台数据库。连接先设置 5 秒锁等待，再检查 WAL；已启用时不重复设置。连接配置和幂等建表遇到 SQLITE_BUSY/SQLITE_LOCKED 各最多尝试 3 次，失败连接会关闭；持续占锁或其他数据库错误仍报错。重试只覆盖初始化，不重放业务事务。不要删除数据库或 WAL/SHM 文件来解锁。

## 执行与恢复

任务入队、幂等操作ID和会谈版本在事务内维护；回复、整理步骤、会谈提交和失败标记在写事务内校验操作 token 与任务的 attempt、owner、状态、有效期限及取消标记；Worker通过租约/attempt栅栏避免迟到结果覆盖。long通道运行自动仿真，short通道处理交互与会后闭环。停止在安全边界结束，取消不提交迟到结果；恢复沿持久化运行编号，不新造同一实验。人工会谈每轮读取本场已保存的完整对话，E.9 复用与自动仿真相同的 ID 事项台账；自动重试复用数据库中 `completed` 的疗程，不再要求达到请求会谈数。

人工疗程创建、发送、开场和关闭均受版本及状态检查，上一会谈未闭环不能进入下一场。关闭失败标记close_failed，可沿已完成步骤继续。SSE按持久化seq分页重放并去重，前端按任务通道订阅，切换选择时忽略旧请求。

## 查看与导出

咨询师视图只显示允许的记忆/背景；私有事实不通过投影泄漏。总督导展示counselor_overall/client_overall及分项，无记录显示未知，零分保留零分；没有文字评语时仅组合客观量表摘要，不推断临床结论。

技能版本是不可变快照。提案需要回放与专家审核，作者不得自审；只有批准后才能发布/回滚指针，模型分数不能自动晋升。审核者先经 `POST /api/skills/reviewers` 登记，验证经 `POST /api/skills/proposals/{id}/validations` 记录；审批要求固定上下文回放与独立仿真各一条记录，且 `clinical_safety` 与 `evidence_grounding` 为真。任务首次加载时把活动发布 ID 固定进 `job_skill_snapshots`，重试沿用同一版本，回滚只影响之后的新任务。

SFT只用会前记忆和合法对话上下文；DPO要求已提交、安全合格的同批次候选及共同前缀，不拼接分支末句。每次导出新目录，保留哈希/行数审计，原文未自动脱敏。人工数据默认不导出。记忆按轨迹 `model_config_snapshot.memory_view` 重建，旧轨迹缺该配置时沿用完整视图；导出继续标记上下文为重建结果。详见 [产物管理](../RUN_ARTIFACTS.md)。

## 参数和验证

Worker读取项目配置并加载实际技能目录。咨询师生成默认0.9，规划、自评、会后记忆默认0，显式control配置贯通Web与CLI。自动仿真复用逐条目logprob、RFT隔离与评分版本保护。人工会谈的阶段动作复用 `LongitudinalEvaluator.stage_action` 的公开证据与安全规则，不生成模拟状态增量。

后端变更运行全套pytest；前端变更运行npm test、lint、build。离线自动化通过不能代替浏览器全流程、供应商能力或专家验收。[2026-10-28质量记录](../archive/workbench-code-quality-review.md)保存当时问题和验证，旧设计与实施说明已合并到本文。
