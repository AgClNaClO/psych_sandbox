from __future__ import annotations

import asyncio

import pytest

from psychsandbox.domain import SandboxConfig, SessionStage
from psychsandbox.evaluation.psycheval_supervisor import (
    _specific_counselor_instruments,
    _specific_client_instruments,
)
from psychsandbox.runtime import CounselingSandbox
from psychsandbox.therapies import get_therapy_profile, list_therapy_profiles
from psychsandbox.visualization import generate_run_report
from tests.deterministic_gateway import DeterministicGateway


def _sandbox(root, tmp_path, repository, *, max_turns: int = 2) -> CounselingSandbox:
    return CounselingSandbox(
        SandboxConfig(
            project_root=root,
            max_turns_per_session=max_turns,
            database_path=tmp_path / "phase1.sqlite3",
            trace_dir=tmp_path / "traces",
        ),
        gateway=DeterministicGateway(),
        repository=repository,
    )


def test_converted_case_has_source_grounded_five_ps_without_forced_sections(sample_case):
    formulation = sample_case.profile.formulation_5ps
    assert {"presenting", "precipitating", "perpetuating"}.issubset(
        set(formulation.covered_sections())
    )
    assert all(
        item.source_ids
        for section in (
            formulation.presenting_problem,
            formulation.predisposing_factors,
            formulation.precipitating_factors,
            formulation.perpetuating_factors,
            formulation.protective_factors,
        )
        for item in section
    )


def test_phase_one_has_five_registered_therapy_profiles():
    ids = {item.therapy_id for item in list_therapy_profiles()}
    assert ids == {
        "behavioral",
        "cbt",
        "humanistic_existential",
        "psychodynamic",
        "postmodern",
    }
    assert get_therapy_profile("bt").therapy_id == "behavioral"


@pytest.mark.parametrize(
    ("therapy_id", "counselor_instrument", "client_instrument"),
    [
        ("behavioral", "miti", "stai"),
        ("cbt", "ctrs", "bdi_ii"),
        ("humanistic_existential", "tes", "cct"),
        ("psychodynamic", "psc", "ipo"),
        ("postmodern", "eft_tfs", "sfbt"),
    ],
)
def test_each_therapy_uses_its_configured_holistic_instruments(
    therapy_id, counselor_instrument, client_instrument
):
    assert set(_specific_counselor_instruments(therapy_id)) == {
        counselor_instrument
    }
    assert set(_specific_client_instruments(therapy_id)) == {client_instrument}


@pytest.mark.parametrize(
    (
        "therapy_code",
        "therapy_id",
        "counselor_instrument",
        "client_instrument",
    ),
    [
        ("bt", "behavioral", "miti", "stai"),
        ("cbt", "cbt", "ctrs", "bdi_ii"),
        ("het", "humanistic_existential", "tes", "cct"),
        ("pdt", "psychodynamic", "psc", "ipo"),
        ("pmt", "postmodern", "eft_tfs", "sfbt"),
    ],
)
def test_each_therapy_runs_with_specific_skills(
    root,
    tmp_path,
    repository,
    therapy_code,
    therapy_id,
    counselor_instrument,
    client_instrument,
):
    sandbox = _sandbox(root, tmp_path, repository)
    result = asyncio.run(
        sandbox.run_case(
            f"psycheval-{therapy_code}-001",
            therapy=therapy_code,
            session_count=1,
        )
    )
    assert result.therapy == therapy_id
    assert result.sessions[0].interventions_used
    assert all(
        skill_id.startswith(f"psychagent:{therapy_code}:skill:")
        for session in result.sessions
        for skill_id in session.interventions_used
    )
    assert result.holistic_report is not None
    assert {item.name for item in result.holistic_report.counselor_specific} == {
        counselor_instrument
    }
    assert {item.name for item in result.holistic_report.client_specific} == {
        client_instrument
    }


def test_longitudinal_report_and_feedback_plan_are_persisted(root, tmp_path, repository):
    sandbox = _sandbox(root, tmp_path, repository)
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


def test_supervision_can_advance_next_session_stage(root, tmp_path, repository):
    sandbox = _sandbox(root, tmp_path, repository, max_turns=8)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-001", session_count=1)
    )
    session = result.sessions[0]
    assert session.longitudinal_report.stage_action == "advance"
    assert session.next_session_plan.stage is SessionStage.INTERVENTION


def test_six_session_course_keeps_state_and_memory_continuity(root, tmp_path, repository):
    sandbox = _sandbox(root, tmp_path, repository, max_turns=1)
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
        baseline = sandbox.repository.get("psycheval-cbt-001").profile.initial_state
        expected_trust = baseline.trust + 0.5 * (
            previous.final_state.trust - baseline.trust
        )
        assert current.initial_state.trust == round(expected_trust, 4)
        assert current.initial_state.resistance == baseline.resistance
        assert current.initial_state.model_dump(
            exclude={"fatigue", "trust", "resistance", "rupture_state"}
        ) == previous.final_state.model_dump(
            exclude={"fatigue", "trust", "resistance", "rupture_state"}
        )
        assert current.initial_state.fatigue == max(
            0.1, round(previous.final_state.fatigue - 0.25, 4)
        )


def test_visual_report_contains_process_results_and_turns(root, tmp_path, repository):
    sandbox = _sandbox(root, tmp_path, repository, max_turns=2)
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-002", session_count=2)
    )
    output = generate_run_report(result, tmp_path / "report.html")
    html = output.read_text(encoding="utf-8")
    assert "运行过程" in html
    assert "来访者状态趋势" in html
    assert "整体督导分" in html
    assert "纵向判断" in html
    assert "咨询师可审计规划与决策" in html
    assert "Action / Observation" in html
    assert "咨询师会后自评" in html
    assert "对话记录" in html
    assert "逐轮技术细节" in html
    assert "技能查询记录（1 次）" in html
    assert "元技能依据" in html
    assert "原子技能依据" in html
    record = result.sessions[0].turn_records[0]
    assert record["planning"]["current_goal"] in html
    assert record["client_turn_signal"]["rationale"] in html
    assert "来访者模拟决策摘要" in html
    assert result.run_id in html


def test_decision_summary_renders_only_explicit_fields_and_escapes_text():
    from types import SimpleNamespace
    from psychsandbox.visualization.report import _session_thinking_summary

    record = {
        "planning": {"reasoning_summary": "简短决策依据", "current_goal": "确认具体场景"},
        "client_turn_signal": {"rationale": "<script>unsafe()</script>", "reaction": "neutral"},
        "reasoning_content": "provider-internal-field-must-not-render",
    }
    html = _session_thinking_summary(SimpleNamespace(turn_records=[record]))
    assert "简短决策依据" in html
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in html
    assert "<script>unsafe()" not in html
    assert "provider-internal-field-must-not-render" not in html
    assert _session_thinking_summary(SimpleNamespace(turn_records=[{}]))


def test_decision_summary_shows_rejected_and_accepted_query_plans():
    from types import SimpleNamespace
    from psychsandbox.visualization.report import _session_thinking_summary

    record = {
        "skill_queries": [
            {
                "attempt": 1,
                "planning": {
                    "reasoning_summary": "首次依据：来访者提到回避",
                    "current_goal": "了解回避场景",
                    "plan_steps": ["确认情境", "核对前提"],
                    "action": "query_skills",
                    "action_input": "<script>query()</script>",
                    "reasoning_content": "hidden-provider-field",
                },
                "assessment": "unsuitable",
                "rejection_reason": "缺少练习意愿",
                "candidate_skill_ids": ["skill-a"],
                "returned_skill_ids": ["skill-a"],
            },
            {
                "attempt": 2,
                "planning": {
                    "reasoning_summary": "调整依据：先建立共同目标",
                    "current_goal": "澄清求助期待",
                },
                "assessment": "suitable",
                "returned_skill_ids": ["skill-b"],
            },
        ]
    }
    html = _session_thinking_summary(SimpleNamespace(turn_records=[record]))
    assert "技能查询记录（2 次）" in html
    assert html.index("首次依据：来访者提到回避") < html.index("调整依据：先建立共同目标")
    assert "了解回避场景" in html and "澄清求助期待" in html
    assert "确认情境 → 核对前提" in html
    assert "query_skills" in html
    assert "缺少练习意愿" in html
    assert "&lt;script&gt;query()&lt;/script&gt;" in html
    assert "<script>query()" not in html
    assert "hidden-provider-field" not in html


def test_resume_rejects_different_case(root, tmp_path, repository):
    sandbox = _sandbox(root, tmp_path, repository, max_turns=1)
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
