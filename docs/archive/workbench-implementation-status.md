# 工作台实施状态历史记录（2026-10-26至28）

## 原记录范围

阶段设计覆盖任务长短通道、租约与事件流、人工多会谈闭环、技能不可变快照、审核发布以及SFT/DPO导出。实施清单反映当时的可运行能力，不能将计划中的专家审核或训练视为已经发生。

## 历史验证与后续更正

原专项曾报告15项通过，后续可靠性核查为工作台49项、全库582项通过；这些均是历史离线证据。2026-10-28修复Worker接线、幂等事务、迟到写入、关闭恢复、SSE重放及导出上下文。原UI中/7等旧评分描述不适用于当前0–10报告。

## 当前入口

设计和使用步骤已合并到 [工作台](../workbench/README.md)，当前验证必须重新执行； [质量修复](workbench-code-quality-review.md)保留问题分级与限制。

2026-11-10 阅读校正：P0 中原 `docs/workbench/design.md`、`implementation-status.md` 的记录分别迁移为本目录的 [设计记录](workbench-design.md) 与本文。P5 的“已完成”描述审核发布接口和约束，不是专家已批准具体技能。新的 [技能独立试验](../workbench/SKILL_EVOLUTION_EXPERIMENT.md) 使用自己的数据库和未审核候选，不接管正式发布指针。

当前网页还支持持久进度、原配置会谈续跑和报告生成重试；这些能力不回填到原阶段的 P0–P7 验证数字中。

## 原阶段清单（历史）

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
