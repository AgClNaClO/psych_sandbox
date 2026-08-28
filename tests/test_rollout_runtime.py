from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from psychsandbox.domain import (
    EvaluationMetric, Message, RFTConfig, RolloutAssessment,
    RolloutDimension, RolloutEvidence, SessionRecord, SupervisorReport,
    CounselorActorOutput, CounselorSessionReview, SandboxConfig,
)
from psychsandbox.runtime import CounselingSandbox, SQLiteStore
from psychsandbox.runtime.rollout import RolloutSelectionError, SessionRolloutRunner
from psychsandbox.visualization import generate_run_report
from tests.deterministic_gateway import DeterministicGateway


def session_for(index, plan, state, *, text=None):
    return SessionRecord(
        session_id=f"session-{plan.session_index}-{index}", session_index=plan.session_index,
        plan=plan.model_copy(deep=True), initial_state=state.model_copy(deep=True),
        final_state=state.model_copy(deep=True), summary=f"候选 {index}", end_reason="max_turns",
        messages=[
            Message(session_index=plan.session_index, turn_index=0, role="client", content="我想慢慢谈一谈"),
            Message(session_index=plan.session_index, turn_index=1, role="counselor", content=text or f"我愿意理解你的感受，先从片段 {index} 谈起"),
        ],
        turn_records=[{"turn_index": 1}],
        supervisor_report=SupervisorReport(
            session_index=plan.session_index, overall_score=10,
            metrics=[EvaluationMetric(name=name, score=10, reason="test") for name in (
                "ethics_and_safety", "hidden_information_leakage",
            )],
        ),
    )


def assessment_for(session, score):
    def dimension(value, index):
        return RolloutDimension(
            score=value, evidence=[RolloutEvidence(message_index=index, quote=session.messages[index].content)],
            reason="离线评分替身",
        )
    return RolloutAssessment(
        counselor_alliance=dimension(score, 1), counselor_strategy=dimension(score, 1),
        counselor_goal_alignment=dimension(score, 1), counselor_safety=dimension(9, 1),
        client_engagement=dimension(6, 0), client_understanding=dimension(6, 0),
        client_agency=dimension(6, 0), simulation_fidelity=dimension(9, 0),
        safety_passed=True, safety_reason="离线测试无安全违规",
    )


class Judge:
    def __init__(self):
        self.calls = []

    async def evaluate(self, session, memory_before):
        self.calls.append(session.session_id)
        index = int(session.session_id.split("-")[-1])
        return assessment_for(session, 5 + index)


@pytest.fixture
def setup(sample_case, tmp_path):
    memory = CounselingSandbox._initial_memory(sample_case)
    plan = sample_case.global_plan[0].model_copy(deep=True)
    state = sample_case.profile.initial_state.model_copy(deep=True)
    store = SQLiteStore(tmp_path / "test.sqlite3")
    try:
        yield sample_case, memory, plan, state, store, tmp_path
    finally:
        store.close()


def runner_for(setup, judge=None, **settings):
    *_, store, path = setup
    config = RFTConfig(enabled=True, candidates=3, **settings)
    return SessionRolloutRunner(config, judge or Judge(), store, path)


async def run(runner, setup, generate):
    _, memory, plan, state, _, _ = setup
    return await runner.run(
        run_id="run-test", plan=plan, memory=memory, state=state,
        previous=None, generate=generate, notify=lambda _: None,
    )


def test_parallel_candidates_are_isolated_and_only_winner_memory_returns(setup):
    _, memory, plan, state, store, path = setup
    original = memory.model_dump()
    active = peak = 0

    async def generate(index, branch_memory, branch_state, checkpoint):
        nonlocal active, peak
        assert branch_memory.model_dump() == original
        active += 1
        peak = max(peak, active)
        branch_memory.unresolved_topics.append(f"private-branch-{index}")
        branch_state.trust = index / 10
        checkpoint({"prefix": f"branch {index}"})
        await asyncio.sleep(0.01)
        active -= 1
        return session_for(index, plan, branch_state)

    session, winner_memory = asyncio.run(run(runner_for(setup), setup, generate))
    assert peak == 2
    assert memory.model_dump() == original
    assert winner_memory.unresolved_topics[-1] == "private-branch-3"
    assert not any("private-branch-1" in s for s in winner_memory.unresolved_topics)
    assert session.final_state.trust == 0.3
    selection = session.rollout_selection
    assert selection.winner_index == 3
    assert len(store.load_sessions("run-test")) == 0
    assert store.load_memory("run-test") is None
    candidates = store.load_rollout_candidates(selection.batch_id)
    assert len(candidates) == 3
    assert candidates[-1]["summary"]["status"] == "selected"
    assert candidates[-1]["session"]["rollout_selection"] is None
    assert json.loads((path / selection.candidates[0].artifact_path).read_text(encoding="utf-8")) == candidates[0]


def test_duplicate_sessions_are_not_scored_again_and_ties_use_index(setup):
    _, _, plan, _, _, _ = setup
    judge = Judge()

    async def tied(session, memory):
        judge.calls.append(session.session_id)
        return assessment_for(session, 8)
    judge.evaluate = tied

    async def generate(index, memory, state, checkpoint):
        await asyncio.sleep(0.02 if index == 1 else 0)
        return session_for(index, plan, state, text="一样的文本" if index <= 2 else "另一个文本")

    session, _ = asyncio.run(run(runner_for(setup, judge), setup, generate))
    assert session.rollout_selection.winner_index == 1
    assert session.rollout_selection.candidates[1].status == "duplicate"
    assert session.rollout_selection.candidates[1].duplicate_of == 1
    assert len(judge.calls) == 2


def test_all_duplicates_fail_without_committing_and_retain_batch(setup):
    _, memory, plan, _, store, path = setup

    async def generate(index, branch_memory, state, checkpoint):
        return session_for(index, plan, state, text="全部重复")

    with pytest.raises(RolloutSelectionError, match="至少需要 2") as error:
        asyncio.run(run(runner_for(setup), setup, generate))
    selection = error.value.selection
    assert selection.status == "failed" and selection.winner_index is None
    assert store.load_rollout_batches("run-test")[-1] == selection
    assert len(store.load_rollout_candidates(selection.batch_id)) == 3
    assert not memory.unresolved_topics
    assert list(path.glob("rollouts/s001__*/selection.json"))


@pytest.mark.parametrize("failure", ["generation", "score", "timeout", "unsafe", "fidelity", "rule", "leak"])
def test_failed_or_rejected_candidate_never_wins(setup, failure):
    _, _, plan, _, _, _ = setup
    judge = Judge()
    original_evaluate = judge.evaluate

    async def evaluate(session, memory):
        result = await original_evaluate(session, memory)
        if session.session_id.endswith("-3"):
            if failure == "score":
                raise ValueError("bad evidence")
            if failure == "unsafe":
                result.safety_passed = False
            if failure == "fidelity":
                result.simulation_fidelity.score = 2
        return result
    judge.evaluate = evaluate

    async def generate(index, memory, state, checkpoint):
        checkpoint({"prefix": "already saved"})
        if index == 3:
            if failure == "generation":
                raise RuntimeError("model failed")
            if failure == "timeout":
                await asyncio.Event().wait()
        session = session_for(index, plan, state)
        if index == 3 and failure == "rule":
            session.end_reason = "safety_output_block"
        if index == 3 and failure == "leak":
            session.turn_records[0]["client_leakage"] = {"exposed_to_counselor": True}
        return session

    session, _ = asyncio.run(run(runner_for(setup, judge, candidate_timeout_sec=0.05), setup, generate))
    assert session.rollout_selection.winner_index == 2
    failed = session.rollout_selection.candidates[-1]
    assert failed.reward is None
    assert failed.status in {"rejected", "generation_failed", "scoring_failed"}
    records = setup[-2].load_rollout_candidates(session.rollout_selection.batch_id)
    assert records[-1]["partial"] == {"prefix": "already saved"}


def test_any_immediate_risk_holds_entire_batch_including_final_client_message(setup):
    _, _, plan, _, store, _ = setup
    judge = Judge()

    async def generate(index, memory, state, checkpoint):
        session = session_for(index, plan, state)
        if index == 3:
            session.messages.append(Message(
                session_index=1, turn_index=1, role="client", content="我现在拿着刀准备伤害自己",
            ))
        return session

    with pytest.raises(RolloutSelectionError) as error:
        asyncio.run(run(runner_for(setup, judge), setup, generate))
    assert error.value.selection.status == "safety_hold"
    assert not judge.calls
    assert store.load_memory("run-test") is None


def test_cancellation_drains_workers_and_preserves_prefixes(setup):
    _, _, plan, _, store, _ = setup
    active = 0
    entered = asyncio.Event()

    async def generate(index, memory, state, checkpoint):
        nonlocal active
        active += 1
        checkpoint({"message": "partial"})
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    async def scenario():
        task = asyncio.create_task(run(runner_for(setup), setup, generate))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert active == 0

    asyncio.run(scenario())
    batch = store.load_rollout_batches("run-test")[-1]
    assert batch.status == "cancelled"
    assert all(c.status == "cancelled" for c in batch.candidates)
    assert any(record["partial"] for record in store.load_rollout_candidates(batch.batch_id))


class RolloutGateway(DeterministicGateway):
    """Distinct offline draws; never an available production provider."""
    def __init__(self):
        self.branches = {}
        self.review_payloads = []
        self.fail_judge = False

    async def complete_structured(self, **kwargs):
        schema = kwargs["output_schema"]
        if schema is RolloutAssessment:
            if self.fail_judge:
                raise RuntimeError("judge temporarily unavailable")
            dialogue = kwargs["input_payload"]["dialogue"]
            number = int(re.findall(r"离线样本 (\d+)", " ".join(m["content"] for m in dialogue))[-1])
            session = SimpleNamespace(messages=[SimpleNamespace(content=m["content"]) for m in dialogue])
            return assessment_for(session, 7 if number % 2 else 9)
        if schema is CounselorSessionReview:
            self.review_payloads.append(kwargs["input_payload"])
        result = await super().complete_structured(**kwargs)
        if schema is CounselorActorOutput:
            task = asyncio.current_task()
            if task not in self.branches:
                self.branches[task] = len(self.branches) + 1
            result.response += f"（离线样本 {self.branches[task]}）"
        return result


def sandbox_for(root, tmp_path, gateway):
    return CounselingSandbox(
        SandboxConfig(
            project_root=root, max_turns_per_session=1,
            database_path=tmp_path / "course.sqlite3", trace_dir=tmp_path / "artifacts",
            rft={"enabled": True, "candidates": 2},
        ), gateway=gateway,
    )


@pytest.mark.parametrize("therapy", ["bt", "cbt", "het", "pdt", "pmt"])
def test_real_session_pipeline_selects_and_persists_one_winner_per_therapy(root, tmp_path, therapy):
    gateway = RolloutGateway()
    sandbox = sandbox_for(root, tmp_path, gateway)
    try:
        result = asyncio.run(sandbox.run_case(f"psycheval-{therapy}-001", session_count=1))
        session = result.sessions[0]
        assert session.rollout_selection.winner_index == 2
        assert len(sandbox.store.load_sessions(result.run_id)) == 1
        assert len(gateway.review_payloads) == 1
        assert "rollout_selection" not in json.dumps(gateway.review_payloads[0])
        stored = sandbox.store.load_run(result.run_id)
        assert stored.sessions[0].rollout_selection == session.rollout_selection
        candidates = sandbox.store.load_rollout_candidates(session.rollout_selection.batch_id)
        assert len(candidates) == 2
        assert all(c["session"]["counselor_review"] is None for c in candidates)
        assert all(c["session"]["clinical_summary"] is None for c in candidates)
        assert "离线样本 1" not in json.dumps(result.final_memory.model_dump(), ensure_ascii=False)
        trace = json.loads((sandbox.run_dir / "trajectory.jsonl").read_text(encoding="utf-8"))
        assert trace["reward"] == session.rollout_selection.candidates[1].reward.total
        html = generate_run_report(result, sandbox.run_dir / "report.html").read_text(encoding="utf-8")
        assert "整场会谈候选与 RFT 选优" in html
        assert "胜出候选：2" in html
        for item in session.rollout_selection.candidates:
            assert item.artifact_path in html
            assert (sandbox.run_dir / item.artifact_path).is_file()
    finally:
        sandbox.store.close()


def test_resume_uses_only_previous_winner_baseline_and_rebuilds_trace(root, tmp_path):
    sandbox = sandbox_for(root, tmp_path, RolloutGateway())
    try:
        first = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1, seed=17))
        first_selection = first.sessions[0].rollout_selection
        (sandbox.run_dir / "trajectory.jsonl").write_text("", encoding="utf-8")
        running = []
        def progress(message):
            if message == "Session 2/2 开始":
                metadata = sandbox.store.load_run_metadata(first.run_id)
                running.append((metadata["status"], metadata["completed_at"]))
        resumed = asyncio.run(sandbox.run_case(
            first.case_id, session_count=2, resume_run_id=first.run_id, progress_callback=progress,
        ))
        assert running == [("running", None)]
        selection = resumed.sessions[1].rollout_selection
        assert selection.baseline_session_index == 1
        assert selection.baseline_client_snapshot == first_selection.candidates[1].reward.client_snapshot
        assert resumed.seed == 17
        assert len(sandbox.store.load_sessions(first.run_id)) == 2
        rows = (sandbox.run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(row)["session_index"] for row in rows] == [1, 2]
        assert first.sessions[0].session_id == resumed.sessions[0].session_id
        assert len(sandbox.store.load_rollout_batches(first.run_id)) == 2
    finally:
        sandbox.store.close()


def test_failed_first_batch_can_resume_without_overwriting_rejected_candidates(root, tmp_path):
    gateway = RolloutGateway()
    gateway.fail_judge = True
    sandbox = sandbox_for(root, tmp_path, gateway)
    try:
        with pytest.raises(RolloutSelectionError):
            asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
        metadata = json.loads((sandbox.run_dir / "run.json").read_text(encoding="utf-8"))
        run_id = metadata["run_id"]
        before = sandbox.store.load_rollout_batches(run_id)[0]
        saved_path = sandbox.run_dir / before.candidates[0].artifact_path
        saved_bytes = saved_path.read_bytes()
        assert not sandbox.store.load_sessions(run_id)
        gateway.fail_judge = False
        result = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1, resume_run_id=run_id))
        assert len(result.sessions) == 1
        assert len(sandbox.store.load_rollout_batches(run_id)) == 2
        assert saved_path.read_bytes() == saved_bytes
    finally:
        sandbox.store.close()


def test_resume_rejects_rft_configuration_changes(root, tmp_path):
    sandbox = sandbox_for(root, tmp_path, RolloutGateway())
    try:
        result = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
        sandbox.config.rft.candidates = 3
        with pytest.raises(ValueError, match="RFT configuration"):
            asyncio.run(sandbox.run_case(result.case_id, session_count=2, resume_run_id=result.run_id))
    finally:
        sandbox.store.close()


def test_judging_has_its_own_concurrency_limit_and_deadline(setup):
    _, _, plan, _, _, _ = setup
    active = peak = 0
    judge = Judge()

    async def evaluate(session, memory):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            if session.session_id.endswith("-3"):
                await asyncio.Event().wait()
            await asyncio.sleep(0.01)
            return assessment_for(session, 8)
        finally:
            active -= 1
    judge.evaluate = evaluate

    async def generate(index, memory, state, checkpoint):
        return session_for(index, plan, state)

    session, _ = asyncio.run(run(runner_for(setup, judge, judge_timeout_sec=0.06), setup, generate))
    assert peak == 2 and active == 0
    assert session.rollout_selection.candidates[-1].status == "scoring_failed"


def test_failed_generation_cannot_hide_risk_already_in_saved_prefix(setup):
    _, _, plan, _, _, _ = setup

    async def generate(index, memory, state, checkpoint):
        if index == 3:
            checkpoint({"messages": [{"role": "client", "content": "我现在拿着刀准备伤害自己"}]})
            raise RuntimeError("failed after disclosure")
        return session_for(index, plan, state)

    with pytest.raises(RolloutSelectionError) as error:
        asyncio.run(run(runner_for(setup), setup, generate))
    assert error.value.selection.status == "safety_hold"


def test_process_run_and_directory_locks_release_after_failure(tmp_path):
    from psychsandbox.artifacts import exclusive_run_dir, single_simulation

    with pytest.raises(ValueError):
        with single_simulation(), exclusive_run_dir(tmp_path):
            with pytest.raises(RuntimeError, match="one run_case"):
                with single_simulation():
                    pass
            with pytest.raises(RuntimeError, match="another process"):
                with exclusive_run_dir(tmp_path):
                    pass
            raise ValueError("test")
    with single_simulation(), exclusive_run_dir(tmp_path):
        pass


def test_committed_session_cannot_be_overwritten_and_old_holistic_is_invalidated(root, tmp_path):
    from psychsandbox.domain import Trajectory

    sandbox = sandbox_for(root, tmp_path, RolloutGateway())
    try:
        result = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
        trajectory = Trajectory.model_validate_json(sandbox.store.trajectory_rows(result.run_id)[0])
        with pytest.raises(ValueError, match="advance exactly one"):
            sandbox.store.save_session(result.run_id, result.sessions[0], result.final_memory, trajectory)
        assert len(sandbox.store.load_sessions(result.run_id)) == 1
        assert sandbox.store.load_holistic_report(result.run_id) is not None
        # Fail only the final course evaluation; the new winner still commits.
        async def fail_final(*args):
            raise RuntimeError("final evaluation unavailable")
        sandbox.holistic_supervisor.evaluate = fail_final
        resumed = asyncio.run(sandbox.run_case(result.case_id, session_count=2, resume_run_id=result.run_id))
        assert resumed.holistic_report is None
        assert sandbox.store.load_holistic_report(result.run_id) is None
    finally:
        sandbox.store.close()


def test_checkpoint_risk_immediately_cancels_other_candidates(setup):
    waiting = asyncio.Event()
    cancelled = []

    async def generate(index, memory, state, checkpoint):
        if index == 1:
            await waiting.wait()
            checkpoint({"messages": [{"role": "client", "content": "我现在拿着刀准备伤害自己"}]})
        else:
            waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(index)

    with pytest.raises(RolloutSelectionError) as error:
        asyncio.run(run(runner_for(setup), setup, generate))
    assert error.value.selection.status == "safety_hold"
    assert error.value.selection.candidates[0].status == "safety_hold"
    assert cancelled
    assert all(c.status != "generating" for c in error.value.selection.candidates)


def test_resume_detects_risk_saved_to_file_before_database_checkpoint(root, tmp_path):
    gateway = RolloutGateway()
    gateway.fail_judge = True
    sandbox = sandbox_for(root, tmp_path, gateway)
    try:
        with pytest.raises(RolloutSelectionError) as error:
            asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
        run_id = json.loads((sandbox.run_dir / "run.json").read_text(encoding="utf-8"))["run_id"]
        path = sandbox.run_dir / error.value.selection.candidates[0].artifact_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["partial"] = {"messages": [{"role": "client", "content": "我现在拿着刀准备伤害自己"}]}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = len(gateway.branches)
        with pytest.raises(ValueError, match="Saved candidate risk"):
            asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1, resume_run_id=run_id))
        assert sandbox.store.load_run_metadata(run_id)["status"] == "safety_hold"
        assert len(gateway.branches) == before
    finally:
        sandbox.store.close()
