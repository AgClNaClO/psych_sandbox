from __future__ import annotations

import asyncio

import json
import tempfile
from pathlib import Path

import pytest

from psychsandbox.domain import SandboxConfig, SkillStatus, SkillVersion, StaticTraits
from psychsandbox.evolution import SkillEvolutionManager
from psychsandbox.model_client import ModelGateway
from psychsandbox.runtime import CounselingSandbox, SQLiteStore
from tests.deterministic_gateway import DeterministicGateway


@pytest.fixture
def sandbox(root, tmp_path, repository):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=2,
        database_path=tmp_path / "test.sqlite3",
        trace_dir=tmp_path / "traces",
    )
    return CounselingSandbox(config, gateway=DeterministicGateway(), repository=repository)


def test_three_session_end_to_end(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=3))
    assert len(result.sessions) == 3
    assert all(session.supervisor_report for session in result.sessions)


def test_first_session_is_counselor_first_and_initial_memory_is_empty(sandbox):
    case = sandbox.repository.get("psycheval-cbt-001")
    initial = sandbox._initial_memory(case)
    assert initial.unlocked_client_info.client_id == case.profile.client_id
    assert initial.unlocked_client_info.main_problem == ""
    assert initial.unlocked_client_info.core_demands == ""
    assert initial.unlocked_client_info.facts == []

    result = asyncio.run(sandbox.run_case(case.case_id, session_count=1))
    assert result.sessions[0].messages[0].role == "counselor"


def test_each_session_has_memory_artifacts(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=3))
    assert all(session.summary and session.next_session_plan for session in result.sessions)
    assert result.final_memory.completed_sessions == 3


def test_e7_e8_e9_feed_counselor_review_before_next_session(root, tmp_path, repository):
    class MemoryClosureGateway(DeterministicGateway):
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        async def complete_structured(self, **kwargs):
            schema = kwargs["output_schema"]
            payload = kwargs["input_payload"]
            self.calls.append((schema.__name__, payload))
            if schema.__name__ == "_ClientInfoGet":
                return schema.model_validate({
                    "client_info_get": {
                        "static_traits": StaticTraits(name="小林").model_dump(mode="json"),
                        "main_problem": "最近总担心自己出错",
                        "topic": "情绪管理",
                        "core_demands": "希望不再被担心牵着走",
                        "growth_experiences": [],
                        "theory": {},
                        "source_session": payload["current_session_number"],
                    }
                })
            return await super().complete_structured(**kwargs)

    gateway = MemoryClosureGateway()
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        database_path=tmp_path / "memory-closure.sqlite3",
        trace_dir=tmp_path / "memory-closure-traces",
    )
    sandbox = CounselingSandbox(config, gateway=gateway, repository=repository)

    result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=2))

    first_review = next(
        payload
        for name, payload in gateway.calls
        if name == "CounselorSessionReview"
    )
    assert (
        first_review["allowed_memory"]["unlocked_client_info"]["main_problem"]
        == "最近总担心自己出错"
    )
    assert first_review["allowed_memory"]["clinical_summaries"]
    planning_payloads = [
        payload for name, payload in gateway.calls if name == "CounselorPlanning"
    ]
    second_session_planning = planning_payloads[1]
    assert (
        second_session_planning["unlocked_client_info"]["main_problem"]
        == "最近总担心自己出错"
    )
    assert second_session_planning["session_memory"]["clinical_summaries"]
    assert result.sessions[1].messages[0].role == "counselor"
    persisted = sandbox.store.load_memory(result.run_id)
    assert persisted is not None
    assert persisted.unlocked_client_info.main_problem == "最近总担心自己出错"
    assert len(persisted.clinical_summaries) == 2


def test_each_turn_has_safety_and_decision(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-003", session_count=1))
    session = result.sessions[0]
    assert session.risk_events
    assert session.decisions
    assert session.turn_records[0]["planning"]["action"] == "respond_without_skill"
    assert session.turn_records[1]["planning"]["action"] == "lookup_skills"
    assert session.turn_records[1]["observation"]["status"] == "skills_found"
    assert session.turn_records[1]["state_update"]["rule_delta"]
    queries = session.turn_records[1]["skill_queries"]
    assert len(queries) == 1
    assert queries[0]["assessment"] == "suitable"
    assert queries[0]["planning"]["selection_evidence"]
    stored = sandbox.store.load_run(result.run_id)
    assert stored.sessions[0].turn_records[1]["skill_queries"] == queries
    record = session.turn_records[1]
    stored_record = stored.sessions[0].turn_records[1]
    assert stored_record["planning"]["reasoning_summary"] == record["planning"]["reasoning_summary"]
    assert stored_record["client_turn_signal"]["rationale"] == record["client_turn_signal"]["rationale"]
    rows = (sandbox.run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["session"]["turn_records"][1]["skill_queries"] == queries


def test_counselor_reviews_progress_and_replans_unmet_goals(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-003", session_count=1))
    session = result.sessions[0]

    assert session.counselor_review is not None
    assert session.counselor_review.goals_achieved is False
    assert session.counselor_review.replanning_required is True
    assert session.counselor_review.evidence
    assert session.next_session_plan is not None
    assert session.next_session_plan.strategy == session.counselor_review.revised_strategy
    assert session.next_session_plan.target_meta_skill_ids == (
        session.counselor_review.target_meta_skill_ids
    )


def test_state_continues_across_sessions(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-007", session_count=2))
    previous = result.sessions[0].final_state
    current = result.sessions[1].initial_state
    assert current.fatigue == max(0.1, round(previous.fatigue - 0.25, 4))
    baseline = sandbox.repository.get("psycheval-cbt-007").profile.initial_state
    assert current.trust == round(
        baseline.trust + 0.5 * (previous.trust - baseline.trust), 4
    )
    assert current.resistance == baseline.resistance
    assert current.model_dump(
        exclude={"fatigue", "trust", "resistance", "rupture_state"}
    ) == previous.model_dump(
        exclude={"fatigue", "trust", "resistance", "rupture_state"}
    )


def test_sqlite_resume_boundary(sandbox):
    first = asyncio.run(sandbox.run_case("psycheval-cbt-004", session_count=1))
    first_dir = sandbox.run_dir
    resumed = asyncio.run(sandbox.run_case(
        "psycheval-cbt-004", session_count=3, resume_run_id=first.run_id
    ))
    assert len(resumed.sessions) == 3
    assert resumed.run_id == first.run_id
    assert sandbox.run_dir == first_dir
    assert len((first_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_jsonl_trajectory_written(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-005", session_count=1))
    path = sandbox.run_dir / "trajectory.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["case_id"] == result.case_id


def test_run_reports_session_progress(sandbox):
    messages: list[str] = []

    result = asyncio.run(
        sandbox.run_case(
            "psycheval-cbt-005",
            session_count=1,
            progress_callback=messages.append,
        )
    )

    assert any(result.run_id in message and "已开始" in message for message in messages)
    assert any("Session 1/1 开始" in message for message in messages)
    assert any("Session 1/1 完成" in message for message in messages)
    assert any("状态=completed" in message for message in messages)


def test_supervisor_has_six_dimensions(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-006", session_count=1))
    assert len(result.sessions[0].supervisor_report.metrics) == 6


def test_client_simulation_report_has_separate_dimensions(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-006", session_count=1))
    report = result.sessions[0].client_simulation_report
    assert report is not None
    assert len(report.metrics) == 8
    rows = sandbox.store.evaluation_rows(result.run_id)
    assert rows[0]["client_report"]["session_index"] == 1


def test_old_session_json_without_client_report_still_loads(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-008", session_count=1))
    raw = result.sessions[0].model_dump(mode="json")
    raw.pop("client_simulation_report")
    from psychsandbox.domain import SessionRecord

    restored = SessionRecord.model_validate(raw)
    assert restored.client_simulation_report is None


def test_patientact_pipeline_can_be_disabled(root, tmp_path, repository):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        patientact_enabled=False,
        database_path=tmp_path / "disabled.sqlite3",
        trace_dir=tmp_path / "disabled-traces",
    )
    result = asyncio.run(
        CounselingSandbox(
            config, gateway=DeterministicGateway(), repository=repository
        ).run_case("psycheval-cbt-009", session_count=1)
    )
    signal = result.sessions[0].turn_records[0]["client_turn_signal"]
    assert signal["rationale"].startswith("PATIENTACT internal planning disabled")


class FailingGateway(ModelGateway):
    provider_name = "failing"

    async def complete_structured(self, **kwargs):
        raise RuntimeError("synthetic model failure")


def test_failed_run_is_persisted(root, tmp_path, repository):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        database_path=tmp_path / "failed.sqlite3",
        trace_dir=tmp_path / "failed-traces",
    )
    sandbox = CounselingSandbox(config, gateway=FailingGateway(), repository=repository)
    messages: list[str] = []

    with pytest.raises(RuntimeError, match="synthetic model failure"):
        asyncio.run(
            sandbox.run_case(
                "psycheval-cbt-009",
                session_count=1,
                progress_callback=messages.append,
            )
        )

    row = sandbox.store.connection.execute(
        "SELECT status, completed_at FROM experiment_runs"
    ).fetchone()
    assert row["status"] == "failed"
    assert row["completed_at"]
    assert any("状态已记录为 failed" in message for message in messages)
    assert json.loads((sandbox.run_dir / "run.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert "synthetic model failure" in (sandbox.run_dir / "logs" / "errors.log").read_text(encoding="utf-8")


def test_store_unknown_run(tmp_path):
    store = SQLiteStore(tmp_path / "empty.sqlite3")
    with pytest.raises(KeyError):
        store.load_run("missing")


def test_skill_cannot_skip_review():
    version = SkillVersion(
        skill_id="s1", version="1", status=SkillStatus.CANDIDATE, content={}
    )
    with pytest.raises(ValueError):
        SkillEvolutionManager().transition(version, SkillStatus.PROMOTED)


def test_expert_review_requires_note():
    version = SkillVersion(
        skill_id="s1", version="1", status=SkillStatus.REPLAYED, content={}
    )
    with pytest.raises(ValueError):
        SkillEvolutionManager().transition(version, SkillStatus.EXPERT_REVIEWED)


def test_repeated_runs_keep_separate_results_and_resume_in_new_instance(sandbox):
    first = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
    first_dir = sandbox.run_dir
    original = (first_dir / "result.json").read_bytes()
    second = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=1))
    assert first.run_id != second.run_id
    assert sandbox.run_dir != first_dir
    assert (first_dir / "result.json").read_bytes() == original
    other = CounselingSandbox(
        sandbox.config,
        gateway=DeterministicGateway(),
        repository=sandbox.repository,
    )
    try:
        resumed = asyncio.run(other.run_case(
            first.case_id, session_count=2, resume_run_id=first.run_id
        ))
        assert other.run_dir == first_dir
        assert len(resumed.sessions) == 2
        assert json.loads((first_dir / "result.json").read_text(encoding="utf-8"))["run_id"] == first.run_id
    finally:
        other.store.close()


def test_runtime_diagnostics_and_temporary_files_stay_with_run(sandbox):
    class RecordingGateway(DeterministicGateway):
        diagnostic_dir = None

        async def complete_structured(self, **kwargs):
            (self.diagnostic_dir / "probe.txt").write_text("diagnostic", encoding="utf-8")
            with tempfile.NamedTemporaryFile(delete=False) as handle:
                self.temporary_path = Path(handle.name)
            return await super().complete_structured(**kwargs)

    gateway = RecordingGateway()
    instance = CounselingSandbox(
        sandbox.config, gateway=gateway, repository=sandbox.repository
    )
    previous_tempdir = tempfile.gettempdir()
    try:
        asyncio.run(instance.run_case("psycheval-cbt-001", session_count=1))
        assert gateway.temporary_path.is_relative_to(instance.run_dir / "tmp")
        assert (instance.run_dir / "diagnostics" / "probe.txt").exists()
        assert tempfile.gettempdir() == previous_tempdir
    finally:
        instance.store.close()


def test_cli_simulate_report_and_visualize_share_artifacts(
    root, tmp_path, repository, monkeypatch, capsys
):
    from psychsandbox import cli
    from psychsandbox.artifacts import find_run_dir
    from psychsandbox.runtime import orchestrator

    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(orchestrator, "create_gateway", lambda: DeterministicGateway())
    monkeypatch.setattr(cli.CaseRepository, "from_project", lambda _root: repository)
    args = cli.build_parser().parse_args([
        "--root", str(root), "simulate", "--case", "psycheval-cbt-001",
        "--sessions", "1", "--max-turns", "1", "--json",
    ])
    assert asyncio.run(cli._simulate(args)) == 0
    result = json.loads(capsys.readouterr().out)
    run_dir = find_run_dir(tmp_path / "artifacts", result["run_id"])
    assert (run_dir / "report.html").exists()
    assert cli._evaluate(root, result["run_id"], full=True) == 0
    capsys.readouterr()
    assert cli._visualize(root, result["run_id"], Path("alternate.html")) == 0
    assert (run_dir / "alternate.html").exists()
    with pytest.raises(ValueError, match="inside"):
        cli._visualize(root, result["run_id"], tmp_path / "outside.html")
    assert not (tmp_path / "outside.html").exists()


def test_valid_skill_transition():
    version = SkillVersion(
        skill_id="s1", version="1", status=SkillStatus.CANDIDATE, content={}
    )
    updated = SkillEvolutionManager().transition(version, SkillStatus.REPLAYED)
    assert updated.status is SkillStatus.REPLAYED
