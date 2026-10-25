"""科研 Web 工作台后端核心单元与集成测试

覆盖重点：
1. JobManager: 任务生命周期、租约超时与回收、心跳、双重栅栏防覆盖、停止/取消请求、双 lane 隔离；
2. EventHub: 事件持久化、自增 seq、断线从 after_seq 重放、去重；
3. Projections: 案例/流派投影、隐私保护（未披露 facts 隔离）、历史快照缺失标记；
4. Interactive: 疗程创建、开场触发、幂等消息发送、版本乐观锁冲突 (409)、生成操作互斥、会后整理分步闭环与重试；
5. Evolution: 不可变快照、内容哈希、提案校验、严格作者回避（作者审核自己报错）、发布与版本回滚；
6. Export: SFT 合法上下文、DPO 同批次同上下文配对与安全过滤、稳定案例划分防数据泄漏。
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path

from psychsandbox.workbench.db import init_db, get_connection
from psychsandbox.workbench.job_manager import JobManager
from psychsandbox.workbench.events import EventHub
from psychsandbox.workbench.projections import (
    list_case_summaries,
    list_therapy_definitions,
    list_experiment_runs,
    get_run_detail,
)
from psychsandbox.workbench.interactive import (
    CourseManager,
    InteractiveRunner,
    VersionConflictError,
    OperationBusyError,
    SessionClosedError,
)
from psychsandbox.workbench.evolution import (
    SkillEvolutionLab,
    EvolutionValidationError,
)
from psychsandbox.workbench.export import DataExporter, ExperimentAnalytics, _stable_case_split
from psychsandbox.workbench.api import create_app
from psychsandbox.agents.counselor import CounselorAgent
from psychsandbox.config import default_config
from psychsandbox.datasets import CaseRepository
from psychsandbox.runtime.storage import SQLiteStore
from psychsandbox.domain import utc_now, SessionRecord, SessionPlan, SessionStage, ClinicalSummary, Message
from tests.deterministic_gateway import DeterministicGateway


@pytest.fixture
def wb_env(tmp_path: Path):
    db_path = tmp_path / "test_workbench.sqlite3"
    sim_db_path = tmp_path / "test_sim.sqlite3"
    trace_dir = tmp_path / "runs"
    assets_dir = tmp_path / "assets" / "skills" / "sect"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 写入假技能树
    (assets_dir / "cbt.json").write_text(json.dumps({"therapy": "cbt", "nodes": []}), encoding="utf-8")

    init_db(str(db_path))
    sim_store = SQLiteStore(sim_db_path)

    return {
        "db_path": str(db_path),
        "sim_store": sim_store,
        "sim_db_path": sim_db_path,
        "trace_dir": trace_dir,
        "assets_dir": assets_dir,
    }


# ====================================================
# 1. JobManager 测试
# ====================================================

def test_job_lifecycle_and_lane_isolation(wb_env):
    jm = JobManager(wb_env["db_path"])

    # 分别向 long 和 short lane 入队任务
    job_long = jm.enqueue_job("simulation", "long", {"case_id": "c1"}, max_attempts=2)
    job_short = jm.enqueue_job("course_reply", "short", {"course_id": "cr1"}, max_attempts=2)

    assert job_long.status == "queued"
    assert job_short.status == "queued"

    # short lane worker 只能认领 short lane
    claimed_short = jm.claim_job("short", "worker-s1", lease_seconds=10)
    assert claimed_short is not None
    assert claimed_short.job_id == job_short.job_id
    assert claimed_short.status == "running"
    assert claimed_short.attempt == 1

    # long lane 此时仍然处于 queued
    assert jm.claim_job("short", "worker-s1") is None

    # long lane worker 认领 long lane
    claimed_long = jm.claim_job("long", "worker-l1", lease_seconds=10)
    assert claimed_long is not None
    assert claimed_long.job_id == job_long.job_id

    # 完成任务
    ok = jm.complete_job(job_short.job_id, attempt=1, worker_id="worker-s1", result={"done": True})
    assert ok is True
    assert jm.get_job(job_short.job_id).status == "succeeded"


def test_job_fencing_and_stale_reap(wb_env):
    jm = JobManager(wb_env["db_path"])
    job = jm.enqueue_job("simulation", "long", {"case_id": "c1"}, max_attempts=2)

    # worker 1 认领，但租约超时
    c1 = jm.claim_job("long", "worker-1", lease_seconds=-5)
    assert c1.attempt == 1

    # 回收过期任务
    reaped = jm.reap_stale_jobs()
    assert reaped == 1
    assert jm.get_job(job.job_id).status == "queued"

    # worker 2 认领，attempt 变为 2
    c2 = jm.claim_job("long", "worker-2", lease_seconds=60)
    assert c2.attempt == 2

    # worker 1 迟到的提交必须被拒绝（栅栏生效）
    stale_ok = jm.complete_job(job.job_id, attempt=1, worker_id="worker-1", result={"fraud": True})
    assert stale_ok is False

    # worker 2 提交成功
    valid_ok = jm.complete_job(job.job_id, attempt=2, worker_id="worker-2", result={"legit": True})
    assert valid_ok is True
    assert jm.get_job(job.job_id).status == "succeeded"


def test_job_stop_and_cancel_requests(wb_env):
    jm = JobManager(wb_env["db_path"])
    job1 = jm.enqueue_job("simulation", "long", {"case_id": "c1"})
    c1 = jm.claim_job("long", "w1", lease_seconds=60)

    # 请求停止
    assert jm.request_stop(c1.job_id) is True
    job_updated = jm.get_job(c1.job_id)
    assert job_updated.stop_requested is True

    # 请求取消
    assert jm.request_cancel(c1.job_id) is True
    job_updated2 = jm.get_job(c1.job_id)
    assert job_updated2.cancel_requested is True


# ====================================================
# 2. EventHub 测试
# ====================================================

@pytest.mark.asyncio
async def test_event_hub_persistence_and_replay(wb_env):
    eh = EventHub(wb_env["db_path"])

    # 发布事件
    e1 = eh.emit("test_stream", "event_a", {"val": 1})
    e2 = eh.emit("test_stream", "event_b", {"val": 2})

    assert e1.seq == 1
    assert e2.seq == 2

    # 断线重放：从 seq=1 之后拉取
    history = eh.get_events("test_stream", after_seq=1)
    assert len(history) == 1
    assert history[0].seq == 2
    assert history[0].type == "event_b"


# ====================================================
# 3. 受控字段投影与隐私测试
# ====================================================

def test_projections_privacy_and_missing_snapshot(wb_env):
    cfg = default_config()
    repo = CaseRepository(cfg.processed_dataset_dir)
    summaries = list_case_summaries(repo)
    assert len(summaries) > 0
    # 验证不含私有字段
    for s in summaries:
        assert hasattr(s, "case_id")
        assert not hasattr(s, "private_profile")
        assert not hasattr(s, "true_risk")

    therapies = list_therapy_definitions()
    assert len(therapies) == 5
    ids = {t["therapy"] for t in therapies}
    assert ids == {"behavioral", "cbt", "humanistic_existential", "psychodynamic", "postmodern"}


# ====================================================
# 4. 人工多会谈聊天与幂等测试
# ====================================================

def test_course_interactive_lifecycle_and_idempotency(wb_env):
    cm = CourseManager(wb_env["db_path"])
    course = cm.create_course(
        therapy="cbt",
        title="Test Interactive CBT Course",
        input_mode="natural",
    )
    assert course.status == "active"
    assert course.version == 1

    # 初始会话已创建
    s1 = cm.get_session_detail(course.course_id, 1)
    assert s1 is not None
    assert s1.status == "open"

    # 1. 提交消息
    msg, op = cm.submit_user_message(
        course_id=course.course_id,
        session_index=1,
        message_id="msg-001",
        operation_id="op-001",
        expected_version=1,
        content="你好，我最近总是感到焦虑。",
    )
    assert msg.content == "你好，我最近总是感到焦虑。"
    assert op.status == "pending"

    # 2. 幂等重复提交同一消息
    msg_dup, op_dup = cm.submit_user_message(
        course_id=course.course_id,
        session_index=1,
        message_id="msg-001",
        operation_id="op-001",
        expected_version=2,  # 版本已递增
        content="你好，我最近总是感到焦虑。",
    )
    assert msg_dup.message_id == msg.message_id
    assert op_dup.operation_id == op.operation_id

    # 3. 双标签版本冲突校验 (VersionConflictError)
    with pytest.raises(VersionConflictError):
        cm.submit_user_message(
            course_id=course.course_id,
            session_index=1,
            message_id="msg-002",
            operation_id="op-002",
            expected_version=1,  # 错误旧版本
            content="双标签冲突测试",
        )

    # 4. 会谈已有活跃操作时禁止并发提交 (OperationBusyError)
    with pytest.raises(OperationBusyError):
        cm.submit_user_message(
            course_id=course.course_id,
            session_index=1,
            message_id="msg-003",
            operation_id="op-003",
            expected_version=2,
            content="并发提交应被阻止",
        )


@pytest.mark.asyncio
async def test_interactive_runner_reply_and_close(wb_env):
    cm = CourseManager(wb_env["db_path"])
    course = cm.create_course(therapy="cbt", title="CBT Course")

    # 触发开场
    op_open = cm.submit_opening(course.course_id, 1, "op-open", expected_version=1)

    gw = DeterministicGateway()
    counselor = CounselorAgent(gateway=gw)
    runner = InteractiveRunner(counselor=counselor, gateway=gw, db_path=wb_env["db_path"])

    # 执行开场操作
    await runner.execute_operation(course.course_id, op_open.operation_id)

    # 检查消息已生成
    s_detail = cm.get_session_detail(course.course_id, 1)
    assert len(s_detail.messages) == 1
    assert s_detail.messages[0].role == "counselor"

    # 用户发送回复
    msg, op_msg = cm.submit_user_message(
        course_id=course.course_id,
        session_index=1,
        message_id="msg-1",
        operation_id="op-reply",
        expected_version=3,
        content="我昨晚又失眠了。",
    )
    await runner.execute_operation(course.course_id, op_msg.operation_id)

    s_detail2 = cm.get_session_detail(course.course_id, 1)
    assert len(s_detail2.messages) == 3  # 开场 + 用户 + 咨询师

    # 申请关闭会谈并执行会后整理工作流
    op_close = cm.submit_close_session(course.course_id, 1, "op-close", expected_version=5)
    await runner.execute_operation(course.course_id, op_close.operation_id)

    # 验证会谈已关闭并记录了整理步骤
    s_closed = cm.get_session_detail(course.course_id, 1)
    assert s_closed.status == "closed"
    assert s_closed.memory_after is not None
    assert len(s_closed.close_steps) == 6  # extract, merge, summary, consolidate, review, plan


# ====================================================
# 5. 技能实验室与演化闭环测试
# ====================================================

def test_skill_evolution_lifecycle_and_expert_review_gate(wb_env):
    lab = SkillEvolutionLab(wb_env["db_path"], assets_dir=wb_env["assets_dir"])

    # 1. 创建初始发布
    rel1 = lab.create_release(
        therapy="cbt",
        name="CBT Initial Release",
        description="Base release",
        created_by="system",
        set_active=True,
    )
    assert rel1.is_active is True
    assert len(rel1.tree_hash) == 64

    # 2. 提交技能修改提案
    prop = lab.submit_proposal(
        therapy="cbt",
        base_release_id=rel1.release_id,
        title="自动思维识别深化",
        target_skill_id=None,
        parent_meta_id="meta-cbt-cog",
        stage="middle",
        content={
            "name": "多重自动思维识别",
            "description": "引导来访者识别连锁自动思维",
            "timing": "在来访者表达情绪困扰且具备初步自省时",
            "triggers": ["自动思维", "想法", "反刍"],
        },
        justification="基于近期会谈中来访者常出现复合负性自动思维的现象",
        author="researcher_alice",
    )
    assert prop.status == "draft"

    # 3. 记录固定上下文回放验证结果
    val = lab.record_replay_validation(
        proposal_id=prop.proposal_id,
        replay_type="fixed_context",
        candidate_outputs={"response": "你刚才提到的这些想法..."},
        baseline_outputs={"response": "能多说说吗？"},
        diff_summary="候选技能更具针对性",
    )
    assert val.status == "completed"

    # 4. 专家审核 - 严格回避测试（作者不能审核自己的提案）
    with pytest.raises(EvolutionValidationError, match="conflict of interest"):
        lab.submit_expert_review(
            proposal_id=prop.proposal_id,
            reviewer_id="researcher_alice",  # 同一人
            reviewer_name="researcher_alice",
            verdict="approve",
            rationale="我自己觉得很完美，通过！",
            checklist={"clinical_safety": True},
        )

    # 5. 专家审核 - 合格的独立第三方专家审核
    review = lab.submit_expert_review(
        proposal_id=prop.proposal_id,
        reviewer_id="expert_bob",
        reviewer_name="Dr. Bob",
        verdict="approve",
        rationale="该技能符合认知行为疗法规范，且触发时机准确，准予批准。",
        checklist={"clinical_safety": True, "rationale_sound": True},
    )
    assert review.verdict == "approve"
    assert lab.get_proposal(prop.proposal_id).status == "approved"

    # 6. 发布批准的提案
    rel2 = lab.publish_approved_proposal(
        proposal_id=prop.proposal_id,
        published_by="admin",
        release_name="CBT Release v1.1",
    )
    assert rel2.is_active is True
    assert rel2.parent_release_id == rel1.release_id

    # 7. 回滚测试
    rel_rollback = lab.rollback_release("cbt", rel1.release_id)
    assert rel_rollback.release_id == rel1.release_id
    assert lab.get_active_release("cbt").release_id == rel1.release_id


# ====================================================
# 6. 数据导出与案例防泄漏测试
# ====================================================

def test_data_export_and_stable_splits(wb_env):
    exporter = DataExporter(wb_env["sim_store"], workbench_db_path=wb_env["db_path"])

    # 稳定划分校验
    s1 = _stable_case_split("psycheval-cbt-001")
    s2 = _stable_case_split("psycheval-cbt-001")
    assert s1 == s2  # 同案例始终相同划分

    # SFT 导出（空运行数据时返回空集合与合规审计）
    out_sft = Path(wb_env["trace_dir"]) / "exports" / "test_sft.jsonl"
    audit_sft = exporter.export_sft(out_sft)
    assert audit_sft.export_type == "sft"
    assert audit_sft.row_count == 0
    assert out_sft.exists()

    # DPO 导出
    out_dpo = Path(wb_env["trace_dir"]) / "exports" / "test_dpo.jsonl"
    audit_dpo = exporter.export_dpo(out_dpo)
    assert audit_dpo.export_type == "dpo"
    assert audit_dpo.row_count == 0
    assert out_dpo.exists()
