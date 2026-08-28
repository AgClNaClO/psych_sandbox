"""Optional vector narrowing after exact lookup, with no mutation of the tree."""

from __future__ import annotations

import hashlib
import math

from ..domain import AtomicSkill, CounselorObservation, SkillSelectionConfig
from ..model_client import ModelGateway


class SkillCandidateFilter:
    def __init__(self, gateway: ModelGateway, config: SkillSelectionConfig) -> None:
        self.gateway = gateway
        self.config = config
        self._vectors: dict[tuple[str, str], list[float]] = {}

    def reset(self) -> None:
        """Skill-only cache is scoped to a run; queries are never cached."""
        self._vectors.clear()

    async def narrow(
        self, observation: CounselorObservation, *, query: str, stage: str,
    ) -> CounselorObservation:
        skills = observation.atomic_skills
        if observation.status != "skills_found" or len(skills) <= self.config.vector_threshold:
            return observation
        identity = self.gateway.embedding_identity
        texts = [self._skill_text(skill, stage) for skill in skills]
        keys = [(identity, hashlib.sha256(text.encode("utf-8")).hexdigest()) for text in texts]
        missing = dict.fromkeys(key for key in keys if key not in self._vectors)
        text_by_key = dict(zip(keys, texts))
        result = await self.gateway.embed_texts([query] + [text_by_key[key] for key in missing])
        if len(result) != len(missing) + 1:
            raise ValueError("Embedding result count does not match the skill query")
        normalized = [self._normalize(vector) for vector in result]
        query_vector = normalized[0]
        new_vectors = dict(zip(missing, normalized[1:]))
        vectors = [new_vectors.get(key, self._vectors.get(key)) for key in keys]
        if any(vector is None or len(vector) != len(query_vector) for vector in vectors):
            raise ValueError("Embedding dimensions differ within the skill query")
        self._vectors.update(new_vectors)
        scored = sorted(
            ((sum(a * b for a, b in zip(query_vector, vector)), skill)
             for skill, vector in zip(skills, vectors)),
            key=lambda item: (-item[0], item[1].skill_id),
        )[:self.config.vector_top_k]
        return observation.model_copy(update={
            "atomic_skills": [skill for _, skill in scored],
            "candidate_count": len(skills),
            "vector_filtered": True,
            "embedding_model": self.gateway.embedding_model,
            "similarity_scores": {skill.skill_id: score for score, skill in scored},
            "note": f"已精确展开{len(skills)}项；超过阈值{self.config.vector_threshold}，按向量相似度保留{len(scored)}项。相似度不是适用性判断。",
        })

    @staticmethod
    def _skill_text(skill: AtomicSkill, stage: str) -> str:
        return "\n".join([
            f"路径：{skill.paths.get(stage, skill.name)}",
            f"说明：{skill.description}",
            f"使用时机：{skill.when_to_use}",
            f"触发线索：{'；'.join(skill.triggers)}",
        ])

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        if not isinstance(vector, list) or not vector:
            raise ValueError("Embedding must be a non-empty numeric vector")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise ValueError("Embedding must contain only finite numbers")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding must contain only finite numbers")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("Embedding norm must be finite and non-zero")
        return [value / norm for value in vector]
