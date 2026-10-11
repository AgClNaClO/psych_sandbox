"""Session stopping must not substitute for evidence of stage completion."""
import asyncio

from psychsandbox.domain import (
    ClientState, CounselorActorOutput, CounselorDecision, CounselorSessionReview,
    Message, SandboxConfig, SessionPlan, SessionRecord, SessionStage,
)
from psychsandbox.evaluation.longitudinal import LongitudinalEvaluator
from psychsandbox.runtime import CounselingSandbox
from tests.deterministic_gateway import DISABLED_LOGPROB_SCORING, DeterministicGateway


def record(stage=SessionStage.CONCEPTUALIZATION):
    return SessionRecord(
        session_id="s1", session_index=1,
        plan=SessionPlan(session_index=1, stage=stage, objectives=["确认下一步行动"]),
        initial_state=ClientState(), final_state=ClientState(),
        messages=[Message(session_index=1, turn_index=1, role="client", content="今天很累了。")],
        decisions=[CounselorDecision(assessment="暂定进度", state_observation="疲劳", strategy="收尾", goal_progress=0.95)],
        summary="来访者疲劳，本场结束。", end_reason="counselor_stopped",
    )


def test_high_turn_progress_without_review_cannot_advance():
    assert LongitudinalEvaluator().evaluate(record(), []).stage_action == "continue"


def test_incomplete_post_session_review_vetoes_turn_progress():
    session = record(SessionStage.CONSOLIDATION)
    session.counselor_review = CounselorSessionReview(
        goals_achieved=False, goal_progress=0.4, evidence=["今天很累了。"],
        unmet_objectives=["确认下一步行动"], replanning_required=True,
    )
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_high_progress_does_not_automatically_stop_session(root, tmp_path, repository):
    class HighProgressGateway(DeterministicGateway):
        async def complete_structured(self, **kwargs):
            result = await super().complete_structured(**kwargs)
            if kwargs["output_schema"] is CounselorActorOutput:
                result.decision.goal_progress = 0.95
                result.decision.end_session = False
            return result

    sandbox = CounselingSandbox(SandboxConfig(
        project_root=root, max_turns_per_session=2,
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "control.sqlite3", trace_dir=tmp_path / "traces",
    ), gateway=HighProgressGateway(), repository=repository)
    try:
        result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=1))
        assert len(result.sessions[0].turn_records) == 2
        assert result.sessions[0].end_reason == "max_turns"
    finally:
        sandbox.store.close()


def reviewed_session(stage=SessionStage.CONCEPTUALIZATION):
    from psychsandbox.domain import DialogueEvidence, ObjectiveAssessment, TerminationReview
    session = record(stage)
    session.messages = [
        Message(session_index=1, turn_index=1, role="counselor", content="我们整理了复发时的应对预案，也确定了可以联系的支持资源。"),
        Message(session_index=1, turn_index=1, role="client", content="下一步行动已经确认，我同意结束整个疗程。"),
    ]
    client = DialogueEvidence(turn_index=1, role="client", quote="下一步行动已经确认")
    counselor = DialogueEvidence(turn_index=1, role="counselor", quote="我们整理了复发时的应对预案")
    session.counselor_review = CounselorSessionReview(
        goals_achieved=True, goal_progress=0.01, replanning_required=False, stage_ready=True,
        objective_assessments=[ObjectiveAssessment(
            objective="确认下一步行动", status="completed", evidence=[client],
        )],
        termination=TerminationReview(
            mutual_agreement=[DialogueEvidence(turn_index=1, role="client", quote="我同意结束整个疗程")],
            relapse_plan=[counselor],
            support_plan=[DialogueEvidence(turn_index=1, role="counselor", quote="确定了可以联系的支持资源")],
        ),
    )
    return session


def test_grounded_objectives_can_advance_without_percentage_threshold():
    assert LongitudinalEvaluator().evaluate(reviewed_session(), []).stage_action == "advance"


def test_missing_or_wrong_role_quotes_cannot_certify_goal_completion():
    session = reviewed_session()
    session.counselor_review.objective_assessments[0].evidence[0].role = "counselor"
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_critical_goal_cannot_be_deferred_but_standard_goal_can():
    from psychsandbox.domain import ObjectiveAssessment
    session = reviewed_session()
    session.plan.objectives.append("核对登记信息")
    session.counselor_review.objective_assessments.append(ObjectiveAssessment(
        objective="核对登记信息", status="not_assessed", defer_to_next_stage=True,
        reason="本场疲劳，下一场核对，不影响已确认的阶段条件",
    ))
    session.counselor_review.next_objectives = ["核对登记信息"]
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "advance"
    session.plan.objective_priorities["核对登记信息"] = "critical"
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_deferred_goal_requires_an_explicit_next_session_target():
    from psychsandbox.domain import ObjectiveAssessment
    session = reviewed_session()
    session.plan.objectives.append("核对登记信息")
    session.counselor_review.objective_assessments.append(ObjectiveAssessment(
        objective="核对登记信息", status="not_completed", defer_to_next_stage=True, reason="延期",
    ))
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_closing_trajectory_requires_separate_grounded_termination_conditions():
    session = reviewed_session(SessionStage.CONSOLIDATION)
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "close"
    session.counselor_review.termination.support_plan = []
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"
    session.counselor_review.termination.support_plan = session.counselor_review.termination.relapse_plan
    session.counselor_review.termination.mutual_agreement[0].quote = "下次见"
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_self_review_controls_committed_stage_after_memory_merge(root, tmp_path, repository):
    class IncompleteReviewGateway(DeterministicGateway):
        async def complete_structured(self, **kwargs):
            result = await super().complete_structured(**kwargs)
            if kwargs["output_schema"] is CounselorActorOutput:
                result.decision.goal_progress = 0.99
                result.decision.end_session = True
            if kwargs["output_schema"] is CounselorSessionReview:
                assert kwargs["input_payload"]["allowed_memory"]["session_recaps"]
                result.goals_achieved = False
                result.goal_progress = 0.4
                result.stage_ready = False
            return result

    sandbox = CounselingSandbox(SandboxConfig(
        project_root=root, max_turns_per_session=2, logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / "review.sqlite3", trace_dir=tmp_path / "review-traces",
    ), gateway=IncompleteReviewGateway(), repository=repository)
    try:
        result = asyncio.run(sandbox.run_case("psycheval-cbt-002", session_count=2))
        assert len(result.sessions) == 2
        assert all(s.end_reason == "counselor_stopped" for s in result.sessions)
        assert all(s.longitudinal_report.stage_action == "continue" for s in result.sessions)
        assert result.sessions[1].plan.stage == result.sessions[0].plan.stage
        saved = sandbox.store.load_sessions(result.run_id)
        assert saved[0].counselor_review.objective_assessments == []
        assert saved[0].longitudinal_report.stage_action == "continue"
    finally:
        sandbox.store.close()


def test_review_can_promote_a_new_critical_prerequisite_without_keyword_rules():
    from psychsandbox.domain import ObjectiveAssessment
    session = reviewed_session()
    session.plan.objectives.append("澄清尚未解决的必要条件")
    session.counselor_review.objective_assessments.append(ObjectiveAssessment(
        objective="澄清尚未解决的必要条件", priority="critical", status="not_assessed",
        defer_to_next_stage=True, reason="这是阶段推进的必要条件，尚无证据",
    ))
    session.counselor_review.next_objectives = ["澄清尚未解决的必要条件"]
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"


def test_deferring_all_goals_is_not_evidence_of_stage_progress():
    session = reviewed_session()
    item = session.counselor_review.objective_assessments[0]
    item.status = "not_assessed"
    item.defer_to_next_stage = True
    item.reason = "下次再谈"
    session.counselor_review.next_objectives = [item.objective]
    assert LongitudinalEvaluator().evaluate(session, []).stage_action == "continue"
