from __future__ import annotations

import json
from pathlib import Path

from ..domain import AtomicSkill, MetaSkill, SessionStage, SkillStatus


class SkillRegistry:
    def __init__(
        self,
        meta_skills: list[MetaSkill] | None = None,
        atomic_skills: list[AtomicSkill] | None = None,
    ) -> None:
        self.meta_skills = {item.meta_skill_id: item for item in meta_skills or []}
        self.atomic_skills = {item.skill_id: item for item in atomic_skills or []}

    @classmethod
    def from_json(cls, path: Path) -> "SkillRegistry":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "atomic_skills" in raw:
            return cls(
                [MetaSkill.model_validate(item) for item in raw.get("meta_skills", [])],
                [AtomicSkill.model_validate(item) for item in raw["atomic_skills"]],
            )
        return cls.from_legacy(raw)

    @classmethod
    def from_legacy(cls, items: list[dict]) -> "SkillRegistry":
        meta: dict[str, MetaSkill] = {}
        atomic: list[AtomicSkill] = []
        stage_map = {
            "all": list(SessionStage),
            "case_conceptualization": [SessionStage.CONCEPTUALIZATION],
            "core_intervention": [SessionStage.INTERVENTION],
            "consolidation": [SessionStage.CONSOLIDATION],
        }
        for item in items:
            meta_id = f"local:{item['meta_skill']}"
            meta.setdefault(
                meta_id,
                MetaSkill(
                    meta_skill_id=meta_id,
                    name=item["meta_skill"],
                    description=item["meta_skill"],
                    therapy=item["therapy"],
                    stages=stage_map.get(item["stage"], list(SessionStage)),
                ),
            )
            atomic.append(
                AtomicSkill(
                    skill_id=item["skill_id"],
                    name=item["name"],
                    description=item["description"],
                    therapy=item["therapy"],
                    stages=stage_map.get(item["stage"], list(SessionStage)),
                    meta_skill_id=meta_id,
                    when_to_use=item.get("example", ""),
                    triggers=item.get("triggers", []),
                    contraindications=item.get("contraindications", []),
                    intervention_type=item.get(
                        "intervention_type", "supportive_exploration"
                    ),
                    status=SkillStatus(item.get("status", "approved")),
                )
            )
        return cls(list(meta.values()), atomic)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta_skills": [
                item.model_dump(mode="json") for item in self.meta_skills.values()
            ],
            "atomic_skills": [
                item.model_dump(mode="json") for item in self.atomic_skills.values()
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def approved_atomic(self) -> list[AtomicSkill]:
        return [
            item
            for item in self.atomic_skills.values()
            if item.status in {SkillStatus.APPROVED, SkillStatus.PROMOTED}
        ]

