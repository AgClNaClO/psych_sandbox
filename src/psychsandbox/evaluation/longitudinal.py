from __future__ import annotations

from typing import Literal

from ..domain import (
    LongitudinalReport,
    RiskLevel,
    SessionRecord,
    SessionStage,
)


class LongitudinalEvaluator:
    """Convert session progress into a planning signal.

    This is the ``Trajectory Refinement`` step in PsychEval's Post-Session
    Consolidation. It is driven by goal completion and client-state deltas, not
    by supervisor scale scores: clinical supervision (psychometric instruments)
    is performed once after the whole trajectory by ``PsychEvalSupervisor`` and
    is intentionally decoupled from per-session planning.
    """

    STATE_FIELDS = ("valence", "arousal", "distress", "trust", "resistance", "hope")

    def evaluate(
        self,
        session: SessionRecord,
        previous_sessions: list[SessionRecord],
    ) -> LongitudinalReport:
        deltas = {
            field: round(
                getattr(session.final_state, field)
                - getattr(session.initial_state, field),
                4,
            )
            for field in self.STATE_FIELDS
        }
        trend = self._trend(deltas, has_previous=bool(previous_sessions))
        stage_action = self._stage_action(session, trend)
        evidence = [
            f"distress_delta={deltas['distress']:+.3f}",
            f"trust_delta={deltas['trust']:+.3f}",
            f"hope_delta={deltas['hope']:+.3f}",
            f"stage_action={stage_action}",
        ]
        return LongitudinalReport(
            session_index=session.session_index,
            state_deltas=deltas,
            supervisor_score_delta=None,
            trend=trend,
            stage_action=stage_action,
            evidence=evidence,
        )

    @staticmethod
    def _trend(
        deltas: dict[str, float], *, has_previous: bool
    ) -> Literal["baseline", "improving", "stable", "worsening"]:
        if not has_previous:
            return "baseline"
        simulation_progress = (
            -deltas["distress"]
            - deltas["resistance"]
            + deltas["hope"]
            + deltas["trust"]
            + deltas["valence"]
        )
        if simulation_progress >= 0.05:
            return "improving"
        if simulation_progress <= -0.05:
            return "worsening"
        return "stable"

    @staticmethod
    def _stage_action(
        session: SessionRecord,
        trend: Literal["baseline", "improving", "stable", "worsening"],
    ) -> Literal["continue", "advance", "regress", "hold", "close"]:
        high_risk = any(
            event.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}
            for event in session.risk_events
        )
        safety_blocked = session.end_reason in {
            "imminent_risk",
            "safety_output_block",
        }
        if high_risk or safety_blocked:
            return "hold"

        goal_progress = max(
            (decision.goal_progress for decision in session.decisions),
            default=0,
        )
        goal_reached = goal_progress >= session.plan.completion_threshold
        if (
            session.plan.stage is SessionStage.CONSOLIDATION
            and goal_reached
        ):
            return "close"
        if goal_reached and trend != "worsening":
            return "advance"
        if trend == "worsening" and session.plan.stage is not SessionStage.CONCEPTUALIZATION:
            return "regress"
        return "continue"