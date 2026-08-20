from __future__ import annotations

import asyncio

import pytest

from psychsandbox.domain import SandboxConfig, SessionStage
from psychsandbox.runtime import CounselingSandbox
from psychsandbox.therapies import get_therapy_profile, list_therapy_profiles
from psychsandbox.visualization import generate_run_report


def _sandbox(root, tmp_path, *, max_turns: int = 2) -> CounselingSandbox:
    return CounselingSandbox(
        SandboxConfig(
            project_root=root,
            provider="mock",
            max_turns_per_session=max_turns,
            database_path=tmp_path / "phase1.sqlite3",
            trace_dir=tmp_path / "traces",
        )
    )


def test_converted_case_has_complete_five_ps(sample_case):
    formulation = sample_case.profile.formulation_5ps
    assert set(formulation.covered_sections()) == {
        "presenting",
        "predisposing",
        "precipitating",
        "perpetuating",
        "protective",
    }
    assert formulation.source_fields


def test_phase_one_has_two_registered_therapy_profiles():
    ids = {item.therapy_id for item in list_therapy_profiles()}
    assert ids == {"cbt", "humanistic_existential"}
    assert get_therapy_profile("humanistic_existential").therapy_metric == "tes_lite"


def test_humanistic_case_runs_with_therapy_specific_skills(root, tmp_path):
    sandbox = _sandbox(root, tmp_path)
    result = asyncio.run(
        sandbox.run_case("humanistic_work_stress_01", session_count=2)
    )
    assert result.therapy == "humanistic_existential"
    assert all(
        skill_id.startswith("het_")
        for session in result.sessions
        for skill_id in session.interventions_used
    )
    metric_names = {
        metric.name
        for metric in result.sessions[0].supervisor_report.metrics
    }
    assert "tes_lite" in metric_names


def test_longitudinal_report_and_feedback_plan_are_persisted(root, tmp_path):
    sandbox = _sandbox(root, tmp_path)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-001", session_count=3)
    )
    assert all(session.longitudinal_report for session in result.sessions)
    assert result.sessions[0].longitudinal_report.trend == "baseline"
    # 督导评分不再回写下一 session 计划：规划由纵向进度信号驱动。
    assert not any(
        objective.startswith("督导修复：")
        for objective in result.sessions[0].next_session_plan.objectives
    )
    assert result.holistic_report is not None
    assert result.holistic_report.counselor_shared
    assert result.holistic_report.client_shared
    restored = sandbox.store.load_run(result.run_id)
    assert restored.sessions[1].longitudinal_report is not None


def test_supervision_can_advance_next_session_stage(root, tmp_path):
    sandbox = _sandbox(root, tmp_path, max_turns=8)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-001", session_count=1)
    )
    session = result.sessions[0]
    assert session.longitudinal_report.stage_action == "advance"
    assert session.next_session_plan.stage is SessionStage.INTERVENTION


def test_six_session_course_keeps_state_and_memory_continuity(root, tmp_path):
    sandbox = _sandbox(root, tmp_path, max_turns=1)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-001", session_count=6)
    )
    assert len(result.sessions) == 6
    assert result.final_memory.completed_sessions == 6
    for previous, current in zip(
        result.sessions[:-1],
        result.sessions[1:],
        strict=True,
    ):
        assert current.initial_state.model_dump(
            exclude={"fatigue"}
        ) == previous.final_state.model_dump(exclude={"fatigue"})
        assert current.initial_state.fatigue == max(
            0.1, round(previous.final_state.fatigue - 0.25, 4)
        )


def test_visual_report_contains_process_results_and_turns(root, tmp_path):
    sandbox = _sandbox(root, tmp_path, max_turns=1)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-002", session_count=2)
    )
    output = generate_run_report(result, tmp_path / "report.html")
    html = output.read_text(encoding="utf-8")
    assert "运行过程" in html
    assert "来访者状态趋势" in html
    assert "督导指标" in html
    assert "咨询师内部思考过程" in html
    assert "对话记录" in html
    assert "逐轮技术细节" in html
    assert result.run_id in html


def test_resume_rejects_different_case(root, tmp_path):
    sandbox = _sandbox(root, tmp_path, max_turns=1)
    first = asyncio.run(
        sandbox.run_case("psycheval-cbt-003", session_count=1)
    )
    with pytest.raises(ValueError, match="original case and therapy"):
        asyncio.run(
            sandbox.run_case(
                "psycheval-cbt-004",
                session_count=2,
                resume_run_id=first.run_id,
            )
        )
