from __future__ import annotations

import re

from ..domain import (
    CounselorAction,
    CounselorObservation,
    MetaSkill,
    RiskAssessment,
    RiskLevel,
    SessionPlan,
)
from .registry import SkillRegistry


def brief_text(value: str, limit: int) -> str:
    """A bounded verbatim excerpt for meta hints, not a generated clinical rule."""
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


class SkillCatalog:
    """Expose therapy/stage-valid skills without relevance ranking.

    The catalog only enforces structural and safety constraints. Semantic
    selection belongs to the counselor model. Large expansions may be narrowed
    downstream by SkillCandidateFilter before the actor sees the observation.
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
        groups = {}
        for skill in self.registry.approved_atomic():
            if skill.therapy in {"common", plan.therapy} and plan.stage in skill.stages:
                groups.setdefault(skill.meta_skill_id, []).append(skill)
        return sorted(
            (
                item.model_copy(update={"selection_hint": self._selection_hint(groups[item.meta_skill_id])})
                for item in self.registry.meta_skills.values()
                if item.meta_skill_id in groups
                and item.therapy in {"common", plan.therapy}
                and plan.stage in item.stages
            ),
            key=lambda item: item.meta_skill_id,
        )

    @staticmethod
    def _selection_hint(skills) -> str:
        ordered = sorted(skills, key=lambda item: item.skill_id)
        positions = sorted({0, len(ordered) // 2, len(ordered) - 1})
        examples = "、".join(brief_text(ordered[index].name, 18) for index in positions)
        cues = list(dict.fromkeys(
            item.when_to_use or "；".join(item.triggers) for item in ordered
            if item.when_to_use or item.triggers
        ))
        cue_excerpt = "；".join(brief_text(value, 44) for value in cues[:2])
        return brief_text(
            f"共{len(skills)}项；范围示例（非全部）：{examples}；适用线索节选：{cue_excerpt}", 180
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
            candidate_count=len(atomic),
            note=(
                "已返回所选元技能下的全部可用原子技能；未进行任何相关性排序。"
                if atomic
                else "所选元技能下没有当前阶段可用的原子技能。"
            ),
        )
