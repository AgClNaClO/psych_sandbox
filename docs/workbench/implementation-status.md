# 科研 Web 工作台实施状态记录（implementation-status.md）

本文档记录心理咨询多智能体仿真与科研 Web 工作台的实施进度、测试证据、已知问题基线和交付说明，作为断点恢复与验收的依据。

---

## 0. 实施基线与环境状态 (P0)

- **实施时间**：2026-10-26
- **代码库**：`C:\Users\Rain\Desktop\psych_sandbox`
- **活动分支**：`v9`
- **Python 环境**：本地 `.venv` (Python 3.11+, `.[dev]` editable 已安装，包含 `fastapi`, `uvicorn`, `pydantic`)
- **Node.js 环境**：Node.js v24.18.0, npm 11.16.0
- **基线测试**：`pytest -q`
  - 既有测试通过情况：532 passed, 1 failed (耗时 ~43s)
  - 预先存在的失败原因：`tests/test_launcher_script.py::test_launcher_enables_logprob_scoring_by_default` 断言 `run_simulate.bat` 中包含 `set LOGPROB_SCORING=1`，而工作区存在用户未提交的修改将其设为 `0`。按指令保护该修改，不将其视为新代码导致的回归。
- **持久记录**：`docs/workbench/design.md` 与 `docs/workbench/implementation-status.md` 均已就绪。

---

## 1. 验收清单与里程碑进度

| 阶段 | 模块 | 核心要求 | 状态 | 证据 / 关键产物 |
|---|---|---|---|---|
| **P0** | 现状核查与计划 | 检出基线、核对模块、建立 design.md 与 implementation-status.md | **已完成** | `docs/workbench/design.md`, `docs/workbench/implementation-status.md` |
| **P1** | 只读工作台与旧记录兼容 | 案例库/流派检索、旧 runs 读取、受控字段投影、会谈回放、报告查看、无快照标记未记录 | **已完成** | `src/psychsandbox/workbench/projections.py`, `tests/test_workbench_backend.py` |
| **P2** | 自动实验控制与任务执行 | `workbench.sqlite3` 短事务、job 状态机与租约、双 lane 隔离、SSE 序号事件流、会谈边界停止、Worker 心跳与栅栏 | **已完成** | `db.py`, `job_manager.py`, `events.py`, `worker.py`, `orchestrator.py` |
| **P3** | 人工多会谈聊天 | 疗程状态机、幂等发送与双标签防冲突、纯咨询师交互、失败重试、会后整理 6 步闭环与断点恢复、真实契约无虚假模拟状态 | **已完成** | `interactive.py`, `models.py`, `tests/test_workbench_backend.py` |
| **P4** | 技能版本与固定快照 | 不可变 `SkillRelease`、SHA-256 树内容哈希、原始树只读、overlay 扩展层注册、运行期固定版本、一键安全回滚 | **已完成** | `evolution.py`, `tests/test_workbench_backend.py` |
| **P5** | 经验到审核发布的演化闭环 | 经验提取、修改提案校验、固定上下文回放、独立完整仿真、专家审核作者强制回避防冒充、批准发布新快照 | **已完成** | `evolution.py`, `tests/test_workbench_backend.py`, `tests/test_workbench_api.py` |
| **P6** | 可靠数据导出与实验比较 | SFT 合法上下文、DPO 严格同批次同上下文配对并排除未过安全门控与跨轨迹拼凑候选、按案例划分防泄漏、多源实验指标对比（无数据不填零） | **已完成** | `export.py`, `tests/test_workbench_backend.py`, `tests/test_workbench_api.py` |
| **P7** | 前端工作台与集成交付 | React+TS+Vite 三栏沉浸式界面、四大中心、全局状态流、生产打包输出、FastAPI 静态托管、启动/停止脚本 | **已完成** | `frontend/`, `src/psychsandbox/workbench/frontend_dist/`, `run_workbench.bat`, `stop_workbench.bat` |

---

## 2. 核心架构与技术实现细节

### 2.1 数据库与事务隔离
- **正式仿真库 (`psychsandbox.sqlite3`)**：保持既有结构不变，确保 `RunManager` 与现有 CLI/回放契约完全兼容。
- **工作台专有库 (`workbench.sqlite3`)**：独立管理 Web 状态，WAL 模式开启短事务，涵盖：
  - `jobs`：长任务调度、long/short 双 lane 隔离、`attempt` 租约递增与栅栏、心跳与崩溃回收；
  - `events`：全局单调递增 `seq`，支持断线从 `after_seq` 重放与去重；
  - `courses`, `course_sessions`, `course_messages`, `course_operations`, `course_close_steps`：人工连续多会谈实体，支持乐观锁版本控制与 6 步闭环整理恢复；
  - `skill_releases`, `active_skill_releases`, `skill_proposals`, `expert_reviews`, `replay_validations`：技能不可变版本与回避审核机制；
  - `export_audits`：导出审计留痕。

### 2.2 自动仿真长任务与边界控制
- 调度器实现 long lane（实验仿真长任务）与 short lane（人工交互回复/会后整理/单轮回放）严格物理隔离，保证人工短请求不被长仿真队列阻塞。
- `orchestrator.py` 支持会谈边界检查回调 `should_stop: Callable[[], bool]`。当收到停止请求时，在当场会谈提交后安全结束运行并置为 `stopped` 状态，不触发全疗程整体督导。
- 任务执行采用 60s 租约与 10s 心跳机制，崩溃或超时任务由 `reap_stale_jobs()` 自动回收；失效 worker 迟到结果由于栅栏机制无法覆盖新 attempt。

### 2.3 人工多会谈交互模式 (Interactive)
- **纯咨询师引擎复用**：人工模式下不实例化 `ClientSimulator`，不伪造 `ClientState`。
- **并发与幂等**：消息提交接收 `message_id`、`operation_id` 与 `expected_version`。先持久化用户消息再调用模型生成；同一会话同时只能有一条活跃生成操作，版本冲突直接返回 409。
- **会后整理 6 步闭环**：
  1. `extract_summary`：提取当场临床小结；
  2. `merge_summary`：合并更新累计摘要；
  3. `update_checklist`：更新临床检查清单；
  4. `consolidate_memory`：整合长短期记忆台账；
  5. `counselor_review`：咨询师当场表现自评（含治疗同盟评估）；
  6. `build_next_plan`：结合自评与纵向进展生成下一会谈计划。
  若任意步骤失败，记录具体失败步骤并保持会谈处于 `close_failed` 状态，支持断点重试与恢复。
- **真实结束契约**：结束当前会谈与结束整个疗程解耦。用户主动结束疗程明确记录原因 `participant_closed_course`，严禁记为目标达成。

### 2.4 技能不可变快照与专家审核回避
- 原始五流派技能树（BT, CBT, HET, PDT, PMT）位于 `assets/skills/sect/`，保持严格只读与隔离。
- 扩展层变更以 `SkillProposal` 形式提交，经过结构合法性校验与阶段元 ID 匹配。
- 验证流程区分固定上下文回放与独立交互仿真；
- **专家审核回避原则**：后端强制校验 `reviewer_id != author`，作者自审直接抛出 400 异常；禁止按模型分数自动批准或晋升，确保科研伦理。
- 批准后生成不可变 `SkillRelease`，计算 SHA-256 树指纹，支持一键安全回滚版本指针。

### 2.5 可靠数据导出与实验比较大盘
- **SFT 导出**：导出包含合法上下文、前缀、记忆证据与结构化规划；默认排除人工数据（需显式授权开关才可导出已闭环的人工会谈）。
- **DPO 偏好对导出**：严格限制在同一 RFT 批次内、同一提示上下文下配对；严格排除未过安全门控与失败输出；严禁跨轨迹末句配凑。
- **防数据泄漏划分**：基于 `case_id` 计算确定性 SHA-256 哈希，同案例全部候选归入同一划分（Train/Val/Test），保证测试集物理隔离。
- **实验对比大盘**：模型督导分、人工反馈分与自动仿真分分栏并列；平均延迟与成本无数据时显示未知，严禁虚假填零；样本量不足时（`n<2`）如实标注无法估计方差。

### 2.6 前端工作台与工程打包
- 采用 React 19 + TypeScript + Vite 构建经典三栏沉浸式布局：
  - 左侧：案例/流派/疗程导航与控制台；
  - 中间：会谈时间线、对话交互流与核心对比表格；
  - 右侧：结构化计划、允许记忆快照、技能依据与安全审计事件。
- 前端生产构建完成，静态产物部署于 `src/psychsandbox/workbench/frontend_dist/`。
- FastAPI API 服务通过 `StaticFiles` 自动挂载前端产物，实现单机一键启动。

---

## 3. 测试验证证据

### 3.1 工作台专用测试套件
执行命令：
```powershell
.venv\Scripts\pytest -q tests/test_workbench_backend.py tests/test_workbench_api.py
```
测试结果：
- **15 passed in 7.00s (100% 通过)**
- 覆盖项：
  1. `test_job_lifecycle_and_lane_isolation`: 任务生命周期、租约、心跳、双重栅栏防覆盖、停止请求与双 lane 隔离；
  2. `test_event_hub_persistence_and_replay`: 事件落库、自增 seq、断线从 after_seq 重放与去重；
  3. `test_projections_privacy_and_missing_snapshots`: 案例/流派投影、隐私事实隔离、无快照标记未记录；
  4. `test_interactive_course_lifecycle_and_idempotency`: 疗程创建、乐观锁防冲突、幂等发送、生成互斥；
  5. `test_interactive_close_workflow_and_recovery`: 会后整理 6 步闭环与失败恢复；
  6. `test_skill_evolution_lifecycle_and_rollback`: 不可变快照、提案校验、专家审核作者回避、发布与版本回滚；
  7. `test_data_export_and_stable_splits`: SFT 合法上下文、DPO 安全过滤、确定性哈希划分防泄漏；
  8. `test_api_therapies_and_cases`: FastAPI 端点流派与受控案例投影测试；
  9. `test_api_jobs_lifecycle`: FastAPI 任务提交、详情查询与边界停止测试；
  10. `test_api_interactive_courses_and_messages`: FastAPI 人工多会谈消息发送与冲突测试；
  11. `test_api_skill_evolution_lifecycle`: FastAPI 技能提案、回避审核、发布与回滚端点测试；
  12. `test_api_analytics_and_audited_exports`: FastAPI 评测大盘与 SFT/DPO 合规导出端点测试；
  13. `test_api_frontend_static_serving`: FastAPI 前端静态 SPA 首页托管测试。

### 3.2 项目全库测试基线验证
- 全库既有测试全部保持原状，未引入任何破坏性变更或回归错误。

---

## 4. 本地启动与运维使用说明

### 4.1 启动工作台
双击运行根目录下的批处理脚本：
```cmd
run_workbench.bat
```
脚本将依次启动：
1. 后台长任务调度器 Worker (`--lane long`)；
2. 交互短任务调度器 Worker (`--lane short`)；
3. FastAPI Web 服务（默认监听 `http://127.0.0.1:8000`）。

打开浏览器访问：`http://127.0.0.1:8000` 即可使用工作台。

### 4.2 停止工作台
双击运行根目录下的停止脚本：
```cmd
stop_workbench.bat
```
脚本将优雅终止监听 8000 端口的服务进程及所有相关的后台 Worker 进程。

### 4.3 独立调试模式 (前端 HMR)
如需进行前端代码修改与热重载调试：
```cmd
# 启动后端
python -m psychsandbox.workbench.server --host 127.0.0.1 --port 8000

# 另起终端启动前端开发服务器 (支持反向代理)
npm --prefix frontend run dev
```
访问：`http://localhost:5173`。

---

## 5. 边界与合规声明

1. **真实 API 与付费模型**：本地工作台默认未绑定真实付费模型密钥。生产运行将调用真实 API 网关，测试环境中已严格使用 `tests/deterministic_gateway.py` 替身。
2. **专家审核与晋升**：软件层面已完整建立回避规则、审查表单与发布回滚机制。未经人类临床专家实际审核的技能提案在系统中保持真实的待处理状态，不自动假冒专家通过。
3. **训练与模型权重**：数据导出模块已严格实现受控合法上下文过滤与防泄漏划分，系统不包含未经授权的自动权重训练任务。
