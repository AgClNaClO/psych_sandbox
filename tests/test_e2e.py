from __future__ import annotations

import asyncio

import json

import pytest

from psychsandbox.domain import SandboxConfig, SkillStatus, SkillVersion
from psychsandbox.evolution import SkillEvolutionManager
from psychsandbox.runtime import CounselingSandbox, SQLiteStore


@pytest.fixture
def sandbox(root, tmp_path):
    config = SandboxConfig(
        project_root=root,
        provider="mock",
        max_turns_per_session=2,
        database_path=tmp_path / "test.sqlite3",
        trace_dir=tmp_path / "traces",
    )
    return CounselingSandbox(config)


def test_three_session_end_to_end(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-001", session_count=3))
    assert len(result.sessions) == 3
    assert all(session.supervisor_report for session in result.sessions)


def test_each_session_has_memory_artifacts(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=3))
    assert all(session.summary and session.next_session_plan for session in result.sessions)
    assert result.final_memory.completed_sessions == 3


def test_each_turn_has_safety_and_decision(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-003", session_count=1))
    session = result.sessions[0]
    assert session.risk_events
    assert session.decisions
    assert session.turn_records[0]["state_update"]["rule_delta"]


def test_state_continues_across_sessions(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-007", session_count=2))
    assert result.sessions[1].initial_state == result.sessions[0].final_state


def test_sqlite_resume_boundary(sandbox):
    first = asyncio.run(sandbox.run_case("psycheval-cbt-004", session_count=1))
    resumed = asyncio.run(sandbox.run_case(
        "psycheval-cbt-004", session_count=3, resume_run_id=first.run_id
    ))
    assert len(resumed.sessions) == 3
    assert resumed.run_id == first.run_id


def test_jsonl_trajectory_written(sandbox):
    result = asyncio.run(sandbox.run_case("psycheval-cbt-005", session_count=1))
    path = sandbox.config.trace_dir / f"{result.run_id}.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["case_id"] == result.case_id


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


def test_patientact_pipeline_can_be_disabled(root, tmp_path):
    config = SandboxConfig(
        project_root=root,
        provider="mock",
        max_turns_per_session=1,
        patientact_enabled=False,
        database_path=tmp_path / "disabled.sqlite3",
        trace_dir=tmp_path / "disabled-traces",
    )
    result = asyncio.run(
        CounselingSandbox(config).run_case("psycheval-cbt-009", session_count=1)
    )
    signal = result.sessions[0].turn_records[0]["client_turn_signal"]
    assert signal["rationale"].startswith("PATIENTACT internal planning disabled")


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


def test_valid_skill_transition():
    version = SkillVersion(
        skill_id="s1", version="1", status=SkillStatus.CANDIDATE, content={}
    )
    updated = SkillEvolutionManager().transition(version, SkillStatus.REPLAYED)
    assert updated.status is SkillStatus.REPLAYED
