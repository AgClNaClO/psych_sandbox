from __future__ import annotations

from ..domain import LongitudinalReport, RiskLevel, SessionRecord, SessionStage


class LongitudinalEvaluator:
    """Convert session state and supervision results into a planning signal."""

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
        current_score = (
            session.supervisor_report.overall_score
            if session.supervisor_report
            else None
        )
        previous_score = (
            previous_sessions[-1].supervisor_report.overall_score
            if previous_sessions
            and previous_sessions[-1].supervisor_report
            else None
        )
        score_delta = (
            round(current_score - previous_score, 3)
            if current_score is not None and previous_score is not None
            else None
        )
        trend = self._trend(deltas, score_delta, has_previous=bool(previous_sessions))
        stage_action = self._stage_action(session, current_score, trend)
        evidence = [
            f"distress_delta={deltas['distress']:+.3f}",
            f"trust_delta={deltas['trust']:+.3f}",
            f"hope_delta={deltas['hope']:+.3f}",
        ]
        if score_delta is not None:
            evidence.append(f"supervisor_score_delta={score_delta:+.3f}")
        evidence.append(f"stage_action={stage_action}")
        return LongitudinalReport(
            session_index=session.session_index,
            state_deltas=deltas,
            supervisor_score_delta=score_delta,
            trend=trend,
            stage_action=stage_action,
            evidence=evidence,
        )

    @staticmethod
    def _trend(
        deltas: dict[str, float],
        score_delta: float | None,
        *,
        has_previous: bool,
    ) -> str:
        if not has_previous:
            return "baseline"
        simulation_progress = (
            -deltas["distress"]
            - deltas["resistance"]
            + deltas["hope"]
            + deltas["trust"]
            + deltas["valence"]
        )
        score_signal = 0.0 if score_delta is None else score_delta / 10
        combined = simulation_progress + score_signal
        if combined >= 0.08:
            return "improving"
        if combined <= -0.08:
            return "worsening"
        if abs(simulation_progress) < 0.03 and abs(score_signal) < 0.03:
            return "stable"
        return "mixed"

    @staticmethod
    def _stage_action(
        session: SessionRecord,
        score: float | None,
        trend: str,
    ) -> str:
        high_risk = any(
            event.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}
            for event in session.risk_events
        )
        safety_failed = any(
            metric.name == "ethics_and_safety" and metric.score < 7
            for metric in (
                session.supervisor_report.metrics
                if session.supervisor_report
                else []
            )
        )
        if high_risk or safety_failed:
            return "hold"
        score = score if score is not None else 0
        if score < 6 and session.plan.stage is not SessionStage.CONCEPTUALIZATION:
            return "regress"
        goal_progress = max(
            (decision.goal_progress for decision in session.decisions),
            default=0,
        )
        goal_reached = goal_progress >= session.plan.completion_threshold
        if (
            session.plan.stage is SessionStage.CONSOLIDATION
            and goal_reached
            and score >= 7
        ):
            return "close"
        if goal_reached and score >= 7 and trend != "worsening":
            return "advance"
        return "continue"
