from __future__ import annotations

from ..domain import LongitudinalReport, SessionPlan, SessionStage


class PlanBuilder:
    """Advance the therapeutic plan from the baseline plan plus progress signal.

    Planning is intentionally decoupled from PsychEval supervisor scoring: the
    longitudinal progress signal (state deltas and goal completion) drives the
    next stage, matching PsychEval's ``Post-Session Consolidation`` step rather
    than using scale-based clinical evaluation to set session objectives.
    """

    _ORDER = (
        SessionStage.CONCEPTUALIZATION,
        SessionStage.INTERVENTION,
        SessionStage.CONSOLIDATION,
    )

    def build(
        self,
        current: SessionPlan,
        baseline_next: SessionPlan,
        longitudinal: LongitudinalReport,
    ) -> SessionPlan:
        stage = self._target_stage(current.stage, longitudinal.stage_action)
        objectives = list(baseline_next.objectives)
        stage_actions = {
            "hold": "暂停普通干预，优先完成安全复核与现实支持连接",
            "regress": "返回概念化，补充信息并修订维持机制",
            "advance": "基于上一会谈达成情况推进到下一治疗阶段",
            "close": "确认终止条件、复发预案与支持资源",
        }
        action = longitudinal.stage_action
        if action == "close":
            objectives = [stage_actions["close"]]
        elif action in stage_actions:
            objectives.insert(0, stage_actions[action])
        return baseline_next.model_copy(
            update={
                "therapy": current.therapy,
                "stage": stage,
                "objectives": list(dict.fromkeys(objectives)),
            }
        )

    def _target_stage(self, current: SessionStage, action: str) -> SessionStage:
        index = self._ORDER.index(current)
        if action == "advance":
            return self._ORDER[min(index + 1, len(self._ORDER) - 1)]
        if action == "regress":
            return self._ORDER[max(index - 1, 0)]
        return current
