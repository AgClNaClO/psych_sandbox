from __future__ import annotations

import asyncio

import json
import tempfile
from pathlib import Path

import pytest

from psychsandbox.domain import (
    ClientUtterance,
    CounselorPlanning,
    CounselorActorOutput,
    DialogueEvidence,
    HomeworkAssignment,
    SandboxConfig,
    SkillStatus,
    SkillVersion,
    StaticTraits,
)
from psychsandbox.evolution import SkillEvolutionManager
from psychsandbox.model_client import ModelGateway
from psychsandbox.runtime import CounselingSandbox, SQLiteStore
from tests.deterministic_gateway import (
    DISABLED_LOGPROB_SCORING,
    DeterministicGateway,
)


@pytest.fixture
def sandbox(root, tmp_path, repository):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=2,
        rft={"enabled": False},
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "test.sqlite3",
        trace_dir=tmp_path / "traces",
    )
    return CounselingSandbox(config, gateway=DeterministicGateway(), repository=repository)


def test_first_session_is_counselor_first_and_initial_memory_is_empty(sandbox):
    case = sandbox.repository.get("psycheval-cbt-001")
    initial = sandbox._initial_memory(case)
    assert initial.known_background.client_id == case.profile.client_id
    assert initial.known_background.main_problem == ""
    assert initial.known_background.core_demands == ""
    assert initial.known_background.facts == []

    result = asyncio.run(sandbox.run_case(case.case_id, session_count=1))
    assert result.sessions[0].messages[0].role == "counselor"


def test_e7_e8_e9_feed_counselor_review_before_next_session(root, tmp_path, repository):
    class MemoryClosureGateway(DeterministicGateway):
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        async def complete_structured(self, **kwargs):
            schema = kwargs["output_schema"]
            payload = kwargs["input_payload"]
            self.calls.append((schema.__name__, payload))
            if schema.__name__ == "_ClientInfoGet":
                client_message = next(m for m in payload["dialogue"] if m["role"] == "client")
                return schema.model_validate({
                    "client_info_get": {
                        "static_traits": StaticTraits(name="小林").model_dump(mode="json"),
                        "main_problem": client_message["content"],
                        "topic": "情绪管理",
                        "core_demands": "希望不再被担心牵着走",
                        "growth_experiences": [],
                        "theory": {},
                        "source_session": payload["current_session_number"],
                        "field_evidence": [{
                            "field_path": "main_problem", "value": client_message["content"],
                            "evidence": {"turn_index": client_message["turn_index"],
                                         "role": "client", "quote": client_message["content"]},
                        }],
                    }
                })
            return await super().complete_structured(**kwargs)

    gateway = MemoryClosureGateway()
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        rft={"enabled": False},
        logprob_scoring=DISABLED_LOGPROB_SCORING,
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
        first_review["allowed_memory"]["known_background"]["main_problem"]
        == result.sessions[0].messages[-1].content
    )
    assert first_review["allowed_memory"]["session_recaps"]
    planning_payloads = [
        payload for name, payload in gateway.calls if name == "CounselorPlanning"
    ]
    second_session_planning = planning_payloads[1]
    assert (
        second_session_planning["known_background"]["main_problem"]
        == result.sessions[0].messages[-1].content
    )
    assert second_session_planning["session_memory"]["session_recaps"]
    assert result.sessions[1].messages[0].role == "counselor"
    persisted = sandbox.store.load_memory(result.run_id)
    assert persisted is not None
    assert persisted.known_background.main_problem == result.sessions[0].messages[-1].content
    assert len(persisted.session_recaps) == 2


def test_counselor_reads_full_session_dialogue_and_e9_archives_it(root, tmp_path, repository):
    class DialogueGateway(DeterministicGateway):
        def __init__(self):
            self.counselor_payloads: list[tuple[type, dict]] = []
            self.summary_payloads: list[dict] = []

        async def complete_structured(self, **kwargs):
            schema = kwargs["output_schema"]
            payload = kwargs["input_payload"]
            if schema is ClientUtterance:
                return ClientUtterance(utterance=f"第{payload['turn_index']}次练习时我注意到自己的反应。")
            result = await super().complete_structured(**kwargs)
            if schema in (CounselorPlanning, CounselorActorOutput):
                self.counselor_payloads.append((schema, payload))
            if schema is CounselorActorOutput and payload["session_opening"]:
                result.response += "这周请试着记录一次压力事件。"
            if schema.__name__ == "_SessionSummaryWrapper":
                self.summary_payloads.append(payload)
                summary = result.session_summary.model_copy(update={
                    "homework": ["记录一次压力事件"],
                    "homework_assignments": [HomeworkAssignment(
                        text="记录一次压力事件",
                        proposed_evidence=DialogueEvidence(turn_index=1, role="counselor", quote="这周请试着记录一次压力事件"),
                    )],
                    "important_information": [payload["dialogue"][1]["content"]],
                    "completed_items": ["了解来访者练习时的反应"],
                    "pending_items": ["讨论压力对睡眠的影响"],
                })
                return result.model_copy(update={"session_summary": summary})
            return result

    gateway = DialogueGateway()
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=6,
        rft={"enabled": False},
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "dialogue.sqlite3",
        trace_dir=tmp_path / "dialogue-traces",
    )
    sandbox = CounselingSandbox(config, gateway=gateway, repository=repository)

    result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=2))

    obsolete = {"session_checklist", "client_message", "recent_messages"}
    assert len(result.sessions) == len(gateway.summary_payloads) == 2
    for session, summary_payload in zip(result.sessions, gateway.summary_payloads, strict=True):
        messages = [message.model_dump(mode="json") for message in session.messages]
        assert summary_payload["dialogue"] == messages
        assert not obsolete & summary_payload.keys()
        for schema in (CounselorPlanning, CounselorActorOutput):
            calls = [payload for kind, payload in gateway.counselor_payloads
                     if kind is schema and payload["session_index"] == session.session_index]
            assert [len(payload["dialogue"]) for payload in calls] == [0, 2, 4, 6, 8, 10]
            for turn, payload in enumerate(calls):
                assert payload["dialogue"] == messages[:2 * turn]
                assert not obsolete & payload.keys()
        for record in session.turn_records:
            assert "session_checklist" not in record
            assert "checklist_update" not in record["planning"]

    first_client_text = result.sessions[0].messages[1].content
    archived = result.final_memory.checklist.per_session[0]
    assert archived.important_information == [first_client_text]
    assert archived.completed_items == ["了解来访者练习时的反应"]
    assert archived.pending_items == ["讨论压力对睡眠的影响"]
    assert "讨论压力对睡眠的影响" in result.final_memory.unresolved_topics
    assert "记录一次压力事件" in result.final_memory.homework
    next_opening = next(payload for kind, payload in gateway.counselor_payloads
                        if kind is CounselorPlanning and payload["session_index"] == 2)
    assert next_opening["session_memory"]["checklist"]["per_session"][0][
        "important_information"
    ] == [first_client_text]


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


def test_run_reports_session_progress_and_writes_trajectory(sandbox):
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

    path = sandbox.run_dir / "trajectory.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["case_id"] == result.case_id


def test_patientact_pipeline_can_be_disabled(root, tmp_path, repository):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        rft={"enabled": False},
        logprob_scoring=DISABLED_LOGPROB_SCORING,
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
        rft={"enabled": False},
        logprob_scoring=DISABLED_LOGPROB_SCORING,
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
    from psychsandbox.config import default_config
    from psychsandbox.domain import LogprobScoringConfig
    from psychsandbox.runtime import orchestrator

    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(orchestrator, "create_gateway", lambda: DeterministicGateway())
    monkeypatch.setattr(cli.CaseRepository, "from_project", lambda _root: repository)
    # The CLI reads the YAML default, and the offline double emits no logprobs.
    monkeypatch.setattr(
        cli,
        "default_config",
        lambda _root: default_config(root).model_copy(
            update={"logprob_scoring": LogprobScoringConfig(enabled=False)}
        ),
    )
    args = cli.build_parser().parse_args([
        "--root", str(root), "simulate", "--case", "psycheval-cbt-001",
        "--sessions", "1", "--max-turns", "1", "--no-rft", "--json",
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
