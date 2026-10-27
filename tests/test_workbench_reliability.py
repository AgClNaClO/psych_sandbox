"""Regression coverage for the Web workbench's actual worker and storage contracts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from psychsandbox.agents.counselor import CounselorAgent
from psychsandbox.domain import SandboxConfig
from psychsandbox.runtime.storage import SQLiteStore
from psychsandbox.workbench.api import create_app
from psychsandbox.workbench.db import get_connection, init_db
from psychsandbox.workbench.events import EventHub, get_event_hub
from psychsandbox.workbench.export import DataExporter, ExperimentAnalytics
from psychsandbox.workbench.interactive import (
    CourseManager, InteractiveRunner, OperationBusyError, SessionClosedError, VersionConflictError,
)
from psychsandbox.workbench.job_manager import JobManager
from psychsandbox.workbench.projections import get_run_detail, list_experiment_runs
from psychsandbox.workbench.worker import WorkbenchWorker
from tests.deterministic_gateway import DISABLED_LOGPROB_SCORING, DeterministicGateway


@pytest.fixture
def wb(tmp_path):
    path = str(tmp_path / "workbench.sqlite3")
    init_db(path)
    return path


@pytest.fixture
def client(wb, tmp_path):
    app = create_app(
        db_path=wb, sim_db_path=tmp_path / "simulation.sqlite3",
        trace_dir=tmp_path / "traces", export_dir=tmp_path / "exports",
        frontend_dir=tmp_path / "missing-frontend",
    )
    with TestClient(app) as value:
        yield value


@pytest.mark.asyncio
async def test_worker_executes_real_simulation_contract(wb, tmp_path, root, monkeypatch):
    config = SandboxConfig(
        project_root=root, max_turns_per_session=1,
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "sim.sqlite3", trace_dir=tmp_path / "traces",
    )
    monkeypatch.setattr("psychsandbox.workbench.worker.default_config", lambda: config)
    worker = WorkbenchWorker("long", wb, gateway_factory=DeterministicGateway)
    job = worker.job_manager.enqueue_job("simulation", "long", {
        "case_id": "psycheval-cbt-001", "session_count": 1,
    })
    claimed = worker.job_manager.claim_job("long", worker.worker_id)
    await worker._execute_job(claimed)
    finished = worker.job_manager.get_job(job.job_id)
    assert finished.status == "succeeded", finished.error
    assert finished.result["sessions_completed"] == 1
    events = worker.event_hub.get_events(f"job:{job.job_id}")
    assert any(event.type == "simulation_progress" for event in events)
    assert events[-1].type == "job_succeeded"
    store = SQLiteStore(config.database_path)
    try:
        audit = DataExporter(store, wb).export_sft(tmp_path / "sft.jsonl")
        rows = [json.loads(line) for line in Path(audit.output_path).read_text(encoding="utf-8").splitlines()]
        assert rows and all(row["counselor_response"] for row in rows)
        assert all(row["memory_context"]["completed_sessions"] == 0 for row in rows)
        assert all(row["anonymized"] is False for row in rows)
        empty = DataExporter(store, wb).export_sft(tmp_path / "empty.jsonl", run_ids=[])
        assert empty.row_count == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_worker_retries_the_same_run_after_transient_failure(wb, tmp_path, root, monkeypatch):
    config = SandboxConfig(
        project_root=root, max_turns_per_session=1, logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "sim.sqlite3", trace_dir=tmp_path / "traces",
    )
    monkeypatch.setattr("psychsandbox.workbench.worker.default_config", lambda: config)

    class FlakyGateway(DeterministicGateway):
        failed = False

        async def complete_structured(self, **kwargs):
            if not self.failed:
                self.failed = True
                raise RuntimeError("transient failure")
            return await super().complete_structured(**kwargs)

    gateway = FlakyGateway()
    worker = WorkbenchWorker("long", wb, gateway_factory=lambda: gateway)
    job = worker.job_manager.enqueue_job("simulation", "long", {"case_id": "psycheval-cbt-001", "session_count": 1})
    await worker._execute_job(worker.job_manager.claim_job("long", worker.worker_id))
    failed = worker.job_manager.get_job(job.job_id)
    assert failed.status == "queued"
    assert failed.run_id
    await worker._execute_job(worker.job_manager.claim_job("long", worker.worker_id))
    finished = worker.job_manager.get_job(job.job_id)
    assert finished.status == "succeeded", finished.error
    assert finished.result["run_id"] == failed.run_id
    assert len(list(config.trace_dir.glob("*__run-*"))) == 1


@pytest.mark.asyncio
async def test_interactive_risk_is_routed_through_existing_safety_guard(wb):
    class NoModelGateway(DeterministicGateway):
        async def complete_structured(self, **kwargs):
            raise AssertionError("Crisis routing must not use ordinary model generation")

    gateway = NoModelGateway()
    manager = CourseManager(wb)
    course = manager.create_course("cbt", "Test")
    _, operation = manager.submit_user_message(course.course_id, 1, "message", "operation", 1, "我现在拿着刀想自杀")
    runner = InteractiveRunner(CounselorAgent(gateway), gateway, wb)
    await runner.execute_operation(course.course_id, operation.operation_id)
    detail = manager.get_session_detail(course.course_id, 1)
    reply = detail.messages[-1]
    assert reply.role == "counselor"
    assert reply.metadata["input_risk"]["level"] == "imminent"
    assert not reply.metadata["input_risk"]["ordinary_intervention_allowed"]


def test_server_reload_flag_reaches_uvicorn(monkeypatch):
    from psychsandbox.workbench import server
    calls = []
    monkeypatch.setattr("sys.argv", ["server", "--reload", "--port", "8765"])
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    server.main()
    assert calls[0][0] == ("psychsandbox.workbench.api:create_app",)
    assert calls[0][1] == {"factory": True, "host": "127.0.0.1", "port": 8765, "reload": True}


@pytest.mark.asyncio
async def test_event_replay_does_not_skip_pages_when_live_event_arrives(wb):
    hub = EventHub(wb)
    for number in range(210):
        hub.emit("test", "progress", {"number": number})
    stream = hub.subscribe("test")
    try:
        assert (await anext(stream)).seq == 1
        hub.emit("test", "progress", {"number": 210})
        seqs = [(await anext(stream)).seq for _ in range(200)]
        assert seqs == list(range(2, 202))
    finally:
        await stream.aclose()


def test_event_hub_default_database_is_not_rebound_by_another_app(wb):
    get_event_hub(wb)
    assert get_event_hub().db_path is None


def test_course_submission_and_job_are_atomic(wb, monkeypatch):
    manager = CourseManager(wb)
    course = manager.create_course("cbt", "Atomic")

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(JobManager, "enqueue_job", fail_enqueue)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        manager.submit_user_message(course.course_id, 1, "msg", "op", 1, "你好")
    detail = manager.get_session_detail(course.course_id, 1)
    assert detail.messages == []
    assert detail.active_operation is None
    assert manager.get_course(course.course_id).version == 1


def test_repeated_api_message_enqueues_only_one_job(client, wb):
    course = client.post("/api/courses", json={"therapy": "cbt", "title": "Test"}).json()
    url = f"/api/courses/{course['course_id']}/sessions/1/messages"
    body = {"message_id": "message", "operation_id": "operation", "expected_version": 1, "content": "你好"}
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json=body).status_code == 200
    assert len(JobManager(wb).list_jobs()) == 1
    assert client.post(url, json={**body, "content": "不同的消息"}).status_code == 409


def test_course_lifecycle_guards_and_opening_idempotency(wb):
    manager = CourseManager(wb)
    course = manager.create_course("cbt", "Test")
    with pytest.raises(ValueError, match="Close the current session"):
        manager.create_session(course.course_id)
    with pytest.raises(SessionClosedError):
        manager.submit_opening(course.course_id, 9, "missing", 1)
    opening = manager.submit_opening(course.course_id, 1, "opening", 1)
    assert manager.submit_opening(course.course_id, 1, "opening", 1) == opening
    with pytest.raises(OperationBusyError):
        manager.submit_close_session(course.course_id, 1, "close", 2)
    with pytest.raises(OperationBusyError):
        manager.close_course(course.course_id)
    other = manager.create_course("cbt", "Other")
    with pytest.raises(VersionConflictError):
        manager.submit_opening(other.course_id, 1, "opening", 1)


@pytest.mark.asyncio
async def test_reset_lock_fences_late_reply(wb, monkeypatch):
    manager = CourseManager(wb)
    course = manager.create_course("cbt", "Test")
    operation = manager.submit_opening(course.course_id, 1, "opening", 1)
    gateway = DeterministicGateway()
    counselor = CounselorAgent(gateway)
    runner = InteractiveRunner(counselor, gateway, wb)
    started, release = asyncio.Event(), asyncio.Event()
    respond = counselor.respond

    async def blocked_reply(**kwargs):
        turn = await respond(**kwargs)
        started.set()
        await release.wait()
        return turn

    monkeypatch.setattr(counselor, "respond", blocked_reply)
    task = asyncio.create_task(runner.execute_operation(course.course_id, operation.operation_id))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert manager.reset_session_lock(course.course_id, 1) == 1
        release.set()
        with pytest.raises(SessionClosedError, match="cancelled or replaced"):
            await task
        detail = manager.get_session_detail(course.course_id, 1)
        assert detail.messages == []
        assert detail.last_operation.status == "cancelled"
        assert JobManager(wb).list_jobs()[0].status == "cancelled"
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_failure_can_retry_completed_steps(wb, monkeypatch):
    manager = CourseManager(wb)
    course = manager.create_course("cbt", "Test")
    gateway = DeterministicGateway()
    runner = InteractiveRunner(CounselorAgent(gateway), gateway, wb)
    calls = 0
    extract = runner.extractor.extract

    async def counting_extract(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await extract(*args, **kwargs)

    merge = runner.merger.merge

    async def fail_merge(*args, **kwargs):
        raise RuntimeError("temporary merge failure")

    monkeypatch.setattr(runner.extractor, "extract", counting_extract)
    monkeypatch.setattr(runner.merger, "merge", fail_merge)
    operation = manager.submit_close_session(course.course_id, 1, "close-1", 1)
    with pytest.raises(RuntimeError, match="temporary merge failure"):
        await runner.execute_operation(course.course_id, operation.operation_id)
    assert manager.get_session_detail(course.course_id, 1).status == "close_failed"
    monkeypatch.setattr(runner.merger, "merge", merge)
    retry = manager.submit_close_session(course.course_id, 1, "close-2", manager.get_course(course.course_id).version)
    await runner.execute_operation(course.course_id, retry.operation_id)
    assert manager.get_session_detail(course.course_id, 1).status == "closed"
    assert calls == 1
    assert manager.create_session(course.course_id).session_index == 2


@pytest.mark.parametrize("kind", ["sft", "dpo"])
@pytest.mark.parametrize("filename", ["../escape.jsonl", r"..\escape.jsonl", "/absolute.jsonl", "C:escape.jsonl", "NUL.jsonl", "file.txt"])
def test_export_rejects_path_traversal_and_invalid_filenames(client, kind, filename):
    assert client.post(f"/api/exports/{kind}", json={"output_filename": filename}).status_code == 422


def test_exports_are_isolated_per_invocation(client, tmp_path):
    first = client.post("/api/exports/sft", json={}).json()
    second = client.post("/api/exports/sft", json={}).json()
    assert first["output_path"] != second["output_path"]
    assert Path(first["output_path"]).is_relative_to(tmp_path)
    assert Path(first["output_path"]).exists()


@pytest.mark.parametrize("body", [
    {"kind": "simulation", "lane": "short", "payload": {"case_id": "case"}},
    {"kind": "validation_replay", "lane": "short"},
    {"kind": "simulation", "payload": {}},
    {"kind": "simulation", "payload": {"case_id": "case", "session_count": 0}},
    {"kind": "simulation", "payload": {"case_id": "case"}, "max_attempts": 0},
])
def test_job_api_rejects_unexecutable_requests(client, body):
    assert client.post("/api/jobs", json=body).status_code == 422


def test_bad_course_requests_return_client_errors(client):
    assert client.post("/api/courses", json={"therapy": "invalid", "title": "Test"}).status_code == 422
    assert client.post("/api/courses/missing/close").status_code == 400
    assert client.post("/api/courses/missing/sessions/1/close?operation_id=op&expected_version=1").status_code == 400


def test_foreign_pages_cannot_write_to_local_workbench(client):
    body = {"therapy": "cbt", "title": "Test"}
    assert client.post("/api/courses", json=body, headers={"Origin": "https://foreign.example"}).status_code == 403
    assert client.get("/api/courses").json() == []
    assert client.post("/api/courses", json=body, headers={"Origin": "http://testserver"}).status_code == 200


def test_zero_supervisor_score_is_preserved_without_inventing_metrics(wb, tmp_path):
    store = SQLiteStore(tmp_path / "sim.sqlite3")
    try:
        store.start_run("run-zero", "case", "cbt", "test", 42, {})
        store.connection.execute("INSERT INTO holistic_evaluations VALUES (?, ?)", (
            "run-zero", json.dumps({"counselor_overall": 0.0, "client_overall": 0.0}),
        ))
        store.connection.commit()
        assert list_experiment_runs(store, tmp_path)[0].holistic_score == 0.0
        detail = get_run_detail(store, tmp_path, "run-zero")
        assert detail.holistic_report["holistic_score"] == 0.0
        assert "临床规范符合预期" not in detail.holistic_report["summary"]
        comparison = ExperimentAnalytics(store, wb).get_comparison_rows()[0]
        assert comparison.model_supervisor_score == 0.0
        assert comparison.auto_sim_score is None
    finally:
        store.close()


def test_dpo_uses_current_candidate_schema_and_identical_dialogue_prefix(wb, tmp_path):
    store = SQLiteStore(tmp_path / "sim.sqlite3")
    try:
        store.start_run("run-dpo", "case", "cbt", "test", 42, {})
        selection = {"batch_id": "batch", "status": "selected", "winner_index": 1}
        memory = {"case_id": "case", "known_background": {"client_id": "client"}}
        trajectory = {
            "memory_before": memory, "plan": {"therapy": "cbt"},
            "session": {"rollout_selection": selection},
        }
        store.connection.execute("INSERT INTO trajectories VALUES (?, ?, ?, ?)", (
            "trajectory", "run-dpo", 1, json.dumps(trajectory),
        ))
        store.connection.execute("INSERT INTO rollout_batches VALUES (?, ?, ?, ?)", (
            "batch", "run-dpo", 1, json.dumps(selection),
        ))
        prefix = [{"role": "counselor", "content": "您好"}, {"role": "client", "content": "我担心考试"}]
        for index, status, safe, answer in [
            (1, "selected", True, "胜出分支的第一条不同回复"),
            (2, "eligible", True, "落选分支的第一条不同回复"),
            (3, "eligible", False, "不安全输出"),
            (4, "scoring_failed", True, "评分失败"),
            (5, "eligible", True, "不同来访者上下文"),
        ]:
            messages = prefix + [{"role": "counselor", "content": answer},
                                 {"role": "client", "content": f"后续分歧 {index}"},
                                 {"role": "counselor", "content": f"不能配对的末句 {index}"}]
            if index == 5:
                messages = [{"role": "client", "content": "不同前缀"}] + messages
            payload = {
                "summary": {"status": status, "reward": {"total": 1.0 if index == 1 else 0.0}},
                "session": {"messages": messages, "safety_verdict": {"passed": safe}},
            }
            store.connection.execute("INSERT INTO rollout_candidates VALUES (?, ?, ?)", (
                "batch", index, json.dumps(payload),
            ))
        store.connection.commit()
        exporter = DataExporter(store, wb)
        audit = exporter.export_dpo(tmp_path / "dpo.jsonl")
        assert audit.row_count == 1
        pair = json.loads(Path(audit.output_path).read_text(encoding="utf-8"))
        assert pair["chosen_response"] == "胜出分支的第一条不同回复"
        assert pair["rejected_response"] == "落选分支的第一条不同回复"
        assert pair["prompt_context"]["dialogue_context"] == [
            {"role": "assistant", "content": "您好"}, {"role": "user", "content": "我担心考试"},
        ]
        assert exporter.export_dpo(tmp_path / "empty.jsonl", run_ids=[]).row_count == 0
    finally:
        store.close()


def test_sft_keeps_current_user_input_and_excludes_future_memory(wb, tmp_path):
    store = SQLiteStore(tmp_path / "sim.sqlite3")
    try:
        store.start_run("run-sft", "case", "cbt", "test", 42, {})
        session = {
            "messages": [{"role": "client", "content": "当前问题"},
                         {"role": "counselor", "content": "当前回复"}],
            "turn_records": [{"planning": {"goal": "澄清"}, "decision": {"skill_evidence": []},
                              "client_generation": {"utterance": "未来来访者回复"}}],
        }
        store.connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (
            "session", "run-sft", 1, json.dumps(session),
        ))
        store.connection.execute("INSERT INTO memories VALUES (?, ?, ?)", (
            "run-sft", 1, json.dumps({"future_private_info": "未来信息"}),
        ))
        store.connection.commit()
        audit = DataExporter(store, wb).export_sft(tmp_path / "sft.jsonl")
        text = Path(audit.output_path).read_text(encoding="utf-8")
        row = json.loads(text)
        assert row["dialogue_context"] == [{"role": "user", "content": "当前问题"}]
        assert "未来" not in text
        assert row["memory_snapshot_available"] is False
        assert row["structured_planning"] == {"goal": "澄清"}
    finally:
        store.close()
