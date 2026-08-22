from __future__ import annotations

from ..domain import (
    CounselorAction,
    CounselorObservation,
    MetaSkill,
    RiskAssessment,
    RiskLevel,
    SessionPlan,
)
from .registry import SkillRegistry


class SkillCatalog:
    """Expose therapy/stage-valid skills without relevance ranking.

    The catalog only enforces structural and safety constraints. Semantic
    selection belongs to the counselor model: it first chooses meta-skill IDs,
    then receives the corresponding atomic skills as a ReAct observation.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def available_meta(
        self,
        *,
        plan: SessionPlan,
        risk: RiskAssessment,
    ) -> list[MetaSkill]:
        if risk.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}:
            return []
        valid_meta_ids = {
            skill.meta_skill_id
            for skill in self.registry.approved_atomic()
            if skill.therapy in {"common", plan.therapy}
            and plan.stage in skill.stages
        }
        return sorted(
            (
                item
                for item in self.registry.meta_skills.values()
                if item.meta_skill_id in valid_meta_ids
                and item.therapy in {"common", plan.therapy}
                and plan.stage in item.stages
            ),
            key=lambda item: item.meta_skill_id,
        )

    def observe(
        self,
        *,
        plan: SessionPlan,
        risk: RiskAssessment,
        action: CounselorAction,
        selected_meta_skill_ids: list[str],
    ) -> CounselorObservation:
        if action is not CounselorAction.LOOKUP_SKILLS:
            return CounselorObservation(
                action=action,
                status="no_skills_requested",
                note="咨询师规划器选择了无需查询技能的动作。",
            )

        allowed_meta = {
            item.meta_skill_id for item in self.available_meta(plan=plan, risk=risk)
        }
        selected = list(
            dict.fromkeys(
                item for item in selected_meta_skill_ids if item in allowed_meta
            )
        )
        if not selected:
            return CounselorObservation(
                action=action,
                status="invalid_selection",
                note="规划器没有选择当前流派与阶段中有效的元技能。",
            )

        atomic = sorted(
            (
                item
                for item in self.registry.approved_atomic()
                if item.meta_skill_id in selected
                and item.therapy in {"common", plan.therapy}
                and plan.stage in item.stages
            ),
            key=lambda item: item.skill_id,
        )
        return CounselorObservation(
            action=action,
            status="skills_found" if atomic else "invalid_selection",
            selected_meta_skill_ids=selected,
            atomic_skills=atomic,
            note=(
                "已返回所选元技能下的全部可用原子技能；未进行任何相关性排序。"
                if atomic
                else "所选元技能下没有当前阶段可用的原子技能。"
            ),
        )
