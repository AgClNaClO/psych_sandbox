from __future__ import annotations

from ..domain import SkillStatus, SkillVersion


class SkillEvolutionManager:
    """Enforces review gates; it deliberately cannot auto-promote candidates."""

    transitions = {
        SkillStatus.CANDIDATE: {SkillStatus.REPLAYED},
        SkillStatus.REPLAYED: {SkillStatus.EXPERT_REVIEWED},
        SkillStatus.EXPERT_REVIEWED: {SkillStatus.APPROVED},
        SkillStatus.APPROVED: {SkillStatus.PROMOTED, SkillStatus.DEPRECATED},
        SkillStatus.PROMOTED: {SkillStatus.DEPRECATED, SkillStatus.ROLLED_BACK},
    }

    def transition(
        self, version: SkillVersion, target: SkillStatus, *, review_note: str = ""
    ) -> SkillVersion:
        if target not in self.transitions.get(version.status, set()):
            raise ValueError(f"Invalid skill transition: {version.status} -> {target}")
        if target in {SkillStatus.EXPERT_REVIEWED, SkillStatus.APPROVED} and not review_note:
            raise ValueError("Expert review transitions require a review note")
        return version.model_copy(update={"status": target, "review_note": review_note})
