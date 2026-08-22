from __future__ import annotations

from ..domain import (
    CounselorSessionReview,
    LongitudinalReport,
    SessionPlan,
    SessionStage,
)


class PlanBuilder:
    """Advance the therapeutic plan from the baseline plan plus progress signal.

    Planning is intentionally decoupled from PsychEval supervisor scoring. The
    longitudinal signal controls stage safety/progression, while the counselor's
    API-generated self-review controls unmet goals and strategy revision.
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
        counselor_review: CounselorSessionReview | None = None,
    ) -> SessionPlan:
        stage = self._target_stage(current.stage, longitudinal.stage_action)
        objectives = list(baseline_next.objectives)
        strategy = baseline_next.strategy
        target_meta_skill_ids = list(baseline_next.target_meta_skill_ids)
        if counselor_review is not None:
            if counselor_review.next_objectives:
                objectives = counselor_review.next_objectives + objectives
            if counselor_review.replanning_required:
                strategy = counselor_review.revised_strategy
                target_meta_skill_ids = counselor_review.target_meta_skill_ids
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
                "objectives": list(dict.fromkeys(objectives))[:8],
                "strategy": strategy,
                "target_meta_skill_ids": target_meta_skill_ids,
            }
        )

    def _target_stage(self, current: SessionStage, action: str) -> SessionStage:
        index = self._ORDER.index(current)
        if action == "advance":
            return self._ORDER[min(index + 1, len(self._ORDER) - 1)]
        if action == "regress":
            return self._ORDER[max(index - 1, 0)]
        return current
