from __future__ import annotations

import math
import re
from collections import Counter

from ..domain import (
    AtomicSkill,
    MetaSkill,
    RiskAssessment,
    RiskLevel,
    SessionPlan,
    SkillCandidate,
)
from .registry import SkillRegistry


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    chars = list(chinese)
    bigrams = [chinese[index : index + 2] for index in range(len(chinese) - 1)]
    return words + chars + bigrams


class HierarchicalSkillRetriever:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def retrieve(
        self,
        *,
        plan: SessionPlan,
        client_message: str,
        risk: RiskAssessment,
        top_meta: int = 3,
        top_atomic: int = 5,
    ) -> SkillCandidate:
        if risk.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}:
            return SkillCandidate()
        atomic = [
            item
            for item in self.registry.approved_atomic()
            if item.therapy in {"common", plan.therapy}
            and plan.stage in item.stages
            and not any(term and term in client_message for term in item.contraindications)
        ]
        if not atomic:
            return SkillCandidate()
        query = " ".join(plan.objectives) + " " + client_message
        atomic_scores = self._bm25(query, atomic)
        meta_scores: dict[str, float] = {}
        for skill in atomic:
            meta_scores[skill.meta_skill_id] = max(
                meta_scores.get(skill.meta_skill_id, 0),
                atomic_scores.get(skill.skill_id, 0),
            )
        selected_meta_ids = [
            key
            for key, _ in sorted(
                meta_scores.items(), key=lambda pair: (-pair[1], pair[0])
            )[:top_meta]
        ]
        selected_atomic = sorted(
            [item for item in atomic if item.meta_skill_id in selected_meta_ids],
            key=lambda item: (-atomic_scores[item.skill_id], item.skill_id),
        )[:top_atomic]
        selected_meta = [
            self.registry.meta_skills[item]
            for item in selected_meta_ids
            if item in self.registry.meta_skills
        ]
        return SkillCandidate(
            meta_skills=selected_meta,
            atomic_skills=selected_atomic,
            scores={item.skill_id: atomic_scores[item.skill_id] for item in selected_atomic},
        )

    @staticmethod
    def _bm25(query: str, skills: list[AtomicSkill]) -> dict[str, float]:
        documents = [
            _tokens(
                " ".join(
                    [
                        item.name,
                        item.description,
                        item.when_to_use,
                        " ".join(item.triggers),
                    ]
                )
            )
            for item in skills
        ]
        query_tokens = _tokens(query)
        average_length = sum(map(len, documents)) / max(len(documents), 1)
        document_frequency: Counter[str] = Counter()
        for document in documents:
            document_frequency.update(set(document))
        scores: dict[str, float] = {}
        for skill, document in zip(skills, documents, strict=True):
            frequencies = Counter(document)
            score = 0.0
            for token in query_tokens:
                if not frequencies[token]:
                    continue
                inverse = math.log(
                    1
                    + (len(documents) - document_frequency[token] + 0.5)
                    / (document_frequency[token] + 0.5)
                )
                numerator = frequencies[token] * 2.5
                denominator = frequencies[token] + 1.5 * (
                    0.25 + 0.75 * len(document) / max(average_length, 1)
                )
                score += inverse * numerator / denominator
            score += 0.2 * sum(
                trigger in query for trigger in skill.triggers if trigger
            )
            scores[skill.skill_id] = score
        return scores


class SkillRetriever(HierarchicalSkillRetriever):
    """Compatibility wrapper for the original flat skill list API."""

    def __init__(self, skills: list[AtomicSkill]):
        meta = {
            item.meta_skill_id: MetaSkill(
                meta_skill_id=item.meta_skill_id,
                name=item.meta_skill_id,
                description=item.meta_skill_id,
                therapy=item.therapy,
                stages=item.stages,
            )
            for item in skills
        }
        super().__init__(SkillRegistry(list(meta.values()), skills))
