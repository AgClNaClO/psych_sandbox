from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Protocol

from ..domain import (
    BlockedMemorySignal,
    ClientProfile,
    ClientState,
    DisclosureDecision,
    HiddenFact,
    UnlockedFact,
)


def normalize_activation_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


class ActivationMatcher(Protocol):
    def match(self, text: str, fact: HiddenFact) -> list[str]: ...


class TagActivationMatcher:
    """Auditable tag matcher; replaceable by a semantic matcher later."""

    LOW_INFORMATION_TAGS = frozenset(
        {"影响", "关系", "事情", "感觉", "问题"}
    )

    def match(self, text: str, fact: HiddenFact) -> list[str]:
        normalized = normalize_activation_text(text)
        matched = [
            tag
            for tag in fact.activation_tags
            if normalize_activation_text(tag)
            and normalize_activation_text(tag) in normalized
        ]
        # A single low-information tag such as “影响” or “关系” is too generic
        # to justify activating a hidden memory. A specific tag, or multiple
        # generic tags occurring together, remains valid and auditable.
        strong = [
            tag
            for tag in matched
            if normalize_activation_text(tag) not in self.LOW_INFORMATION_TAGS
        ]
        return matched if strong or len(matched) >= 2 else []


class DisclosureGate:
    def __init__(self, matcher: ActivationMatcher | None = None):
        self.matcher = matcher or TagActivationMatcher()

    def evaluate(
        self,
        profile: ClientProfile,
        state: ClientState,
        text: str,
        disclosed: set[str] | Mapping[str, int],
    ) -> DisclosureDecision:
        disclosed_levels = disclosed if isinstance(disclosed, Mapping) else {}
        retrieved: list[HiddenFact] = []
        blocked: list[BlockedMemorySignal] = []
        activated: list[str] = []
        evidence: dict[str, list[str]] = {}
        candidates: list[tuple[HiddenFact, list[str], int]] = []
        for fact in profile.hidden_facts:
            if isinstance(disclosed, set) and fact.fact_id in disclosed:
                continue
            current_level = int(disclosed_levels.get(fact.fact_id, 0))
            if current_level >= len(fact.disclosure_layers):
                continue
            matched = self.matcher.match(text, fact)
            if fact.activation_tags and not matched:
                continue
            candidates.append((fact, matched, current_level + 1))

        candidates, ambiguous = self._resolve_ambiguity(candidates)
        for fact, matched, next_level in candidates:
            activated.append(fact.fact_id)
            evidence[fact.fact_id] = matched
            topic_readiness = state.topic_readiness.get(fact.topic_key, state.trust)
            trust_ready = state.trust >= fact.minimum_trust
            topic_ready = topic_readiness >= fact.minimum_topic_readiness
            if trust_ready and topic_ready:
                retrieved.append(
                    fact.model_copy(
                        update={
                            "content": fact.disclosure_layers[next_level - 1],
                            "disclosure_level": next_level,
                        }
                    )
                )
            elif fact.generates_discomfort:
                blocked.append(
                    BlockedMemorySignal(
                        fact_id=fact.fact_id,
                        category=fact.category,
                        sensitivity=fact.sensitivity,
                        activation_evidence=matched,
                        reason=(
                            "insufficient_trust"
                            if not trust_ready
                            else "insufficient_topic_readiness"
                        ),
                    )
                )
        return DisclosureDecision(
            retrieved=retrieved,
            blocked=blocked,
            activated_fact_ids=activated,
            activation_evidence=evidence,
            ambiguous_fact_ids=ambiguous,
        )

    @staticmethod
    def _resolve_ambiguity(
        candidates: list[tuple[HiddenFact, list[str], int]],
    ) -> tuple[list[tuple[HiddenFact, list[str], int]], list[str]]:
        """Do not arbitrarily unlock several facts matched by identical generic tags."""

        by_category: dict[str, list[tuple[HiddenFact, list[str], int]]] = defaultdict(list)
        for candidate in candidates:
            by_category[candidate[0].category].append(candidate)
        resolved: list[tuple[HiddenFact, list[str], int]] = []
        ambiguous: list[str] = []
        for group in by_category.values():
            if len(group) == 1:
                resolved.extend(group)
                continue
            best_score = max(len(set(matched)) for _, matched, _ in group)
            best = [item for item in group if len(set(item[1])) == best_score]
            evidence_sets = {tuple(sorted(set(item[1]))) for item in best}
            if len(best) > 1 and len(evidence_sets) == 1:
                ambiguous.extend(item[0].fact_id for item in best)
                continue
            resolved.extend(best)
        return resolved, ambiguous

    def allowed(
        self,
        profile: ClientProfile,
        state: ClientState,
        text: str,
        disclosed: set[str] | Mapping[str, int],
    ) -> list[HiddenFact]:
        return self.evaluate(profile, state, text, disclosed).retrieved

    def unlock(
        self,
        profile: ClientProfile,
        fact_ids: list[str],
        *,
        session_index: int,
        turn_index: int,
        retrieved_facts: list[HiddenFact] | None = None,
    ) -> list[UnlockedFact]:
        index = {fact.fact_id: fact for fact in profile.hidden_facts}
        active = {fact.fact_id: fact for fact in retrieved_facts or []}
        return [
            UnlockedFact(
                fact_id=fact_id,
                content=active.get(fact_id, index[fact_id]).content,
                evidence_session=session_index,
                evidence_turn=turn_index,
                disclosure_level=active.get(fact_id, index[fact_id]).disclosure_level,
            )
            for fact_id in dict.fromkeys(fact_ids)
            if fact_id in index
        ]
