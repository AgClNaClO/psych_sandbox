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
    def from_project(cls, project_root: Path) -> "SkillRegistry":
        """Load the preferred skill source for a project checkout."""

        assets_dir = project_root / "assets" / "skills" / "sect"
        if assets_dir.is_dir():
            return cls.from_psychagent_assets(assets_dir)

        primary = project_root / "data" / "processed" / "psycheval" / "skills.json"
        if not primary.exists():
            primary = project_root / "data" / "skills" / "cbt.json"
        registry = cls.from_json(primary)
        for extra in sorted((project_root / "data" / "skills").glob("*.json")):
            if extra.resolve() != primary.resolve() and extra.name != "cbt.json":
                registry = registry.merge(cls.from_json(extra))
        return registry

    @classmethod
    def from_psychagent_assets(
        cls,
        base_dir: Path,
        therapy_map: dict[str, str] | None = None,
    ) -> "SkillRegistry":
        """Load the staged skill trees bundled under ``assets/skills/sect``."""

        therapy_map = therapy_map or {
            "bt": "behavioral",
            "cbt": "cbt",
            "het": "humanistic_existential",
            "pdt": "psychodynamic",
            "pmt": "postmodern",
        }
        stage_map = {
            "stage1": SessionStage.CONCEPTUALIZATION,
            "stage2": SessionStage.INTERVENTION,
            "stage3": SessionStage.CONSOLIDATION,
        }
        meta: dict[str, MetaSkill] = {}
        atomic: dict[str, AtomicSkill] = {}

        for asset_therapy, therapy in therapy_map.items():
            therapy_dir = base_dir / asset_therapy
            for stage_name, stage in stage_map.items():
                stage_dir = therapy_dir / stage_name
                meta_path = stage_dir / "meta_skills.json"
                micro_path = stage_dir / "micro_skills.json"
                if not meta_path.exists() or not micro_path.exists():
                    continue

                raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                raw_micro = json.loads(micro_path.read_text(encoding="utf-8"))
                meta_ids = {str(value) for value in raw_meta}

                for raw_id, item in raw_meta.items():
                    stable_id = f"psychagent:{asset_therapy}:meta:{raw_id}"
                    if stable_id in meta:
                        if stage not in meta[stable_id].stages:
                            meta[stable_id].stages.append(stage)
                        continue
                    meta[stable_id] = MetaSkill(
                        meta_skill_id=stable_id,
                        name=str(item.get("skill_name", "")),
                        description=str(item.get("skill_description", "")),
                        therapy=therapy,
                        stages=[stage],
                        source="PsychAgent assets",
                    )

                for raw_id, item in raw_micro.items():
                    stable_id = f"psychagent:{asset_therapy}:skill:{raw_id}"
                    if stable_id in atomic:
                        if stage not in atomic[stable_id].stages:
                            atomic[stable_id].stages.append(stage)
                        continue
                    parent_ids = [str(value) for value in item.get("parent_ids", [])]
                    parent_id = next(
                        (value for value in reversed(parent_ids) if value in meta_ids),
                        None,
                    )
                    if parent_id is None:
                        parent_id = f"unassigned-{stage_name}"
                        meta_id = f"psychagent:{asset_therapy}:meta:{parent_id}"
                        meta.setdefault(
                            meta_id,
                            MetaSkill(
                                meta_skill_id=meta_id,
                                name="未分类技能",
                                description="PsychAgent 资源中未关联元技能的技能。",
                                therapy=therapy,
                                stages=[stage],
                                source="PsychAgent assets",
                            ),
                        )
                    else:
                        meta_id = f"psychagent:{asset_therapy}:meta:{parent_id}"

                    trigger = item.get("trigger", "")
                    triggers = (
                        [str(value) for value in trigger]
                        if isinstance(trigger, list)
                        else [
                            part.strip()
                            for part in str(trigger).replace("；", "，").split("，")
                            if part.strip()
                        ]
                    )
                    atomic[stable_id] = AtomicSkill(
                        skill_id=stable_id,
                        name=str(item.get("skill_name", "")),
                        description=str(item.get("skill_description", "")),
                        therapy=therapy,
                        stages=[stage],
                        meta_skill_id=meta_id,
                        when_to_use=str(item.get("when_to_use", "")),
                        triggers=triggers,
                        source="PsychAgent assets",
                        status=SkillStatus.APPROVED,
                    )

        if not atomic:
            raise FileNotFoundError(
                f"No PsychAgent skill assets found under {base_dir}"
            )
        return cls(list(meta.values()), list(atomic.values()))

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
                    source=item.get("source", "local"),
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
                    source=item.get("source", "local"),
                    version=int(item.get("version", 1)),
                    status=SkillStatus(item.get("status", "approved")),
                )
            )
        return cls(list(meta.values()), atomic)

    def merge(self, other: "SkillRegistry") -> "SkillRegistry":
        """Merge registries while rejecting conflicting stable identifiers."""

        meta = dict(self.meta_skills)
        atomic = dict(self.atomic_skills)
        for key, item in other.meta_skills.items():
            if key in meta and meta[key] != item:
                raise ValueError(f"Conflicting meta skill ID: {key}")
            meta[key] = item
        for key, item in other.atomic_skills.items():
            if key in atomic and atomic[key] != item:
                raise ValueError(f"Conflicting atomic skill ID: {key}")
            atomic[key] = item
        return SkillRegistry(list(meta.values()), list(atomic.values()))

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

