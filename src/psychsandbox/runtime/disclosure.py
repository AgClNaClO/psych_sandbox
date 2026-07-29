from __future__ import annotations

import re
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
        disclosed_ids: set[str],
    ) -> DisclosureDecision:
        retrieved: list[HiddenFact] = []
        blocked: list[BlockedMemorySignal] = []
        activated: list[str] = []
        evidence: dict[str, list[str]] = {}
        for fact in profile.hidden_facts:
            if fact.fact_id in disclosed_ids:
                continue
            matched = self.matcher.match(text, fact)
            if fact.activation_tags and not matched:
                continue
            activated.append(fact.fact_id)
            evidence[fact.fact_id] = matched
            if state.trust >= fact.minimum_trust:
                retrieved.append(fact)
            elif fact.generates_discomfort:
                blocked.append(
                    BlockedMemorySignal(
                        fact_id=fact.fact_id,
                        category=fact.category,
                        sensitivity=fact.sensitivity,
                        activation_evidence=matched,
                    )
                )
        return DisclosureDecision(
            retrieved=retrieved,
            blocked=blocked,
            activated_fact_ids=activated,
            activation_evidence=evidence,
        )

    def allowed(
        self,
        profile: ClientProfile,
        state: ClientState,
        text: str,
        disclosed_ids: set[str],
    ) -> list[HiddenFact]:
        return self.evaluate(profile, state, text, disclosed_ids).retrieved

    def unlock(
        self,
        profile: ClientProfile,
        fact_ids: list[str],
        *,
        session_index: int,
        turn_index: int,
    ) -> list[UnlockedFact]:
        index = {fact.fact_id: fact for fact in profile.hidden_facts}
        return [
            UnlockedFact(
                fact_id=fact_id,
                content=index[fact_id].content,
                evidence_session=session_index,
                evidence_turn=turn_index,
            )
            for fact_id in dict.fromkeys(fact_ids)
            if fact_id in index
        ]
