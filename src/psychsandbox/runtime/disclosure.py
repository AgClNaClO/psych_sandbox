from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol

from ..domain import (
    BlockedMemorySignal,
    ClientProfile,
    ClientState,
    DisclosureItem,
    DisclosureDecision,
    UnlockedFact,
)


def normalize_activation_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


class ActivationMatcher(Protocol):
    def match(self, text: str, item: DisclosureItem) -> list[str]: ...


class TagActivationMatcher:
    """Auditable tag matcher; replaceable by a semantic matcher later."""

    LOW_INFORMATION_TAGS = frozenset(
        {"影响", "关系", "事情", "感觉", "问题"}
    )

    def match(self, text: str, item: DisclosureItem) -> list[str]:
        normalized = normalize_activation_text(text)
        matched = [
            tag
            for tag in item.activation_tags
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
        *,
        session_index: int | None = None,
    ) -> DisclosureDecision:
        disclosed_ids = set(disclosed)
        retrieved: list[DisclosureItem] = []
        blocked: list[BlockedMemorySignal] = []
        activated: list[str] = []
        evidence: dict[str, list[str]] = {}
        candidates: list[tuple[DisclosureItem, list[str]]] = []
        for item in profile.disclosure_items:
            if item.item_id in disclosed_ids:
                continue
            if (
                item.session_scope
                and session_index is not None
                and session_index not in item.session_scope
            ):
                continue
            matched = self.matcher.match(text, item)
            if item.activation_tags and not matched:
                continue
            if not set(item.depends_on).issubset(disclosed_ids):
                continue
            candidates.append((item, matched))

        candidates, ambiguous = self._resolve_ambiguity(candidates, text)
        for item, matched in candidates:
            activated.append(item.item_id)
            evidence[item.item_id] = matched
            trust_ready = state.trust >= item.trust_tier.threshold
            if trust_ready:
                retrieved.append(item)
            elif item.generates_discomfort:
                blocked.append(
                    BlockedMemorySignal(
                        item_id=item.item_id,
                        category=item.category,
                        trust_tier=item.trust_tier,
                        activation_evidence=matched,
                        reason=(
                            "insufficient_trust"
                            if not trust_ready else "unmet_dependency"
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
        candidates: list[tuple[DisclosureItem, list[str]]],
        text: str = "",
    ) -> tuple[list[tuple[DisclosureItem, list[str]]], list[str]]:
        """Select one fact globally; tied best candidates require clarification."""

        if len(candidates) <= 1:
            return candidates, []
        generic = {
            "影响", "关系", "事情", "感觉", "问题",
            "经历", "成长", "过去", "情境", "发生", "当时",
        }
        growth_cues = ("成长", "经历", "过去", "小时候")
        situation_cues = ("情境", "发生", "当时", "想法", "脑中", "假设", "应对")
        category_cues = {
            "bt_target_behavior": ("行为", "前因", "回避", "后果", "练习"),
            "het_existential_topic": ("意义", "选择", "存在", "体验", "生活"),
            "het_contact_model": ("关系", "需要", "接触", "靠近", "拒绝"),
            "pdt_core_conflict": ("愿望", "害怕", "冲突", "一方面", "另一方面"),
            "pdt_object_relation": ("自己", "他人", "关系", "感受"),
            "pdt_response_pattern": ("触发", "反应", "模式", "防御"),
            "pmt_exception_event": ("例外", "不同", "做到", "改变"),
            "pmt_force_field": ("资源", "力量", "阻碍", "改变"),
        }

        def score(candidate: tuple[DisclosureItem, list[str]]) -> int:
            fact, matched = candidate
            unique = set(matched)
            specific_count = sum(tag not in generic for tag in unique)
            generic_count = len(unique) - specific_count
            cue_bonus = 0
            if fact.category == "growth_experience" and any(
                cue in text for cue in growth_cues
            ):
                cue_bonus = 2
            elif fact.category == "cbt_special_situation" and any(
                cue in text for cue in situation_cues
            ):
                cue_bonus = 2
            elif any(
                cue in text for cue in category_cues.get(fact.category, ())
            ):
                cue_bonus = 2
            return specific_count * 3 + generic_count + cue_bonus

        scores = [score(candidate) for candidate in candidates]
        best_score = max(scores)
        best = [
            candidate
            for candidate, candidate_score in zip(candidates, scores, strict=True)
            if candidate_score == best_score
        ]
        if len(best) == 1:
            return best, []
        return [], [candidate[0].item_id for candidate in best]

    def allowed(
        self,
        profile: ClientProfile,
        state: ClientState,
        text: str,
        disclosed: set[str] | Mapping[str, int],
        *,
        session_index: int | None = None,
    ) -> list[DisclosureItem]:
        return self.evaluate(
            profile, state, text, disclosed, session_index=session_index
        ).retrieved

    def unlock(
        self,
        profile: ClientProfile,
        fact_ids: list[str],
        *,
        session_index: int,
        turn_index: int,
        retrieved_facts: list[DisclosureItem] | None = None,
        evidence_by_fact_id: Mapping[str, str] | None = None,
    ) -> list[UnlockedFact]:
        index = {item.item_id: item for item in profile.disclosure_items}
        active = {item.item_id: item for item in retrieved_facts or []}
        evidence = evidence_by_fact_id or {}
        return [
            UnlockedFact(
                fact_id=fact_id,
                content=(
                    evidence.get(fact_id)
                    or active.get(fact_id, index[fact_id]).content
                ),
                evidence_session=session_index,
                evidence_turn=turn_index,
            )
            for fact_id in dict.fromkeys(fact_ids)
            if fact_id in index
        ]
