from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..domain import (
    ClientBehaviorType,
    ClientTurnSignal,
    DisclosureItem,
    HiddenFact,
    ResistancePatternType,
)


def normalize_disclosure_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


@dataclass(slots=True)
class LeakageResult:
    leaked_fact_ids: list[str] = field(default_factory=list)
    matches: dict[str, list[str]] = field(default_factory=dict)

    @property
    def leaked(self) -> bool:
        return bool(self.leaked_fact_ids)

    def as_dict(self) -> dict:
        return {
            "leaked": self.leaked,
            "leaked_fact_ids": self.leaked_fact_ids,
            "matches": self.matches,
        }


class PrematureDisclosureGuard:
    """Deterministic defense-in-depth after strict prompt-level isolation."""

    def substantiate(
        self,
        utterance: str,
        declared_fact_ids: list[str],
        allowed_facts: list[DisclosureItem | HiddenFact],
    ) -> tuple[list[str], list[str], dict[str, str]]:
        """Keep only declarations supported by something the client actually said."""

        normalized = [
            fact.to_disclosure_item() if isinstance(fact, HiddenFact) else fact
            for fact in allowed_facts
        ]
        allowed = {fact.item_id: fact for fact in normalized}
        confirmed: list[str] = []
        rejected: list[str] = []
        evidence: dict[str, str] = {}
        for fact_id in dict.fromkeys(declared_fact_ids):
            fact = allowed.get(fact_id)
            if fact is None:
                rejected.append(fact_id)
                continue
            excerpt = _disclosure_evidence(utterance, fact.content)
            if excerpt is None:
                rejected.append(fact_id)
                continue
            confirmed.append(fact_id)
            evidence[fact_id] = excerpt
        return confirmed, rejected, evidence

    def inspect(
        self,
        utterance: str,
        declared_fact_ids: list[str],
        unauthorized_facts: list[DisclosureItem | HiddenFact],
        allowed_fact_ids: set[str] | None = None,
    ) -> LeakageResult:
        normalized_utterance = normalize_disclosure_text(utterance)
        declared = set(declared_fact_ids)
        allowed = allowed_fact_ids or set()
        matches: dict[str, list[str]] = {}
        for raw_fact in unauthorized_facts:
            fact = (
                raw_fact.to_disclosure_item()
                if isinstance(raw_fact, HiddenFact) else raw_fact
            )
            reasons: list[str] = []
            normalized_fact = normalize_disclosure_text(fact.content)
            if fact.item_id in declared and fact.item_id not in allowed:
                reasons.append("unauthorized_fact_id")
            if len(normalized_fact) >= 8 and normalized_fact in normalized_utterance:
                reasons.append("normalized_full_text")
            for clause in _distinctive_clauses(fact.content):
                normalized_clause = normalize_disclosure_text(clause)
                if normalized_clause in normalized_utterance:
                    reasons.append(f"distinctive_clause:{clause[:24]}")
                    break
                if _fuzzy_disclosure_overlap(normalized_utterance, normalized_clause):
                    reasons.append(f"fuzzy_clause:{clause[:24]}")
                    break
            if reasons:
                matches[fact.item_id] = reasons
        return LeakageResult(
            leaked_fact_ids=list(matches),
            matches=matches,
        )

    @staticmethod
    def safe_fallback(signal: ClientTurnSignal) -> str:
        if signal.behavior is not ClientBehaviorType.RESISTANCE:
            return "我现在还不太知道该怎么说，能不能先停在这里想一想？"
        patterns = {
            ResistancePatternType.MINIMAL_TALK: "我不知道……现在不太想说这个。",
            ResistancePatternType.IRRELEVANT_TALK: "要不我们先说说最近的事情吧，这部分我还没准备好。",
            ResistancePatternType.SUPERFICIAL: "大概就是最近状态不太好，具体的我现在不想展开。",
            ResistancePatternType.INTELLECTUALIZING: "我能分析出一些原因，但现在谈感受对我来说有点太多了。",
            ResistancePatternType.HOSTILITY: "我不觉得现在追问这个会有帮助，能先别问了吗？",
            ResistancePatternType.DEFENSIVENESS: "事情没有那么严重，我现在不想把它说成别的什么。",
            ResistancePatternType.COMPLIANCE_WITHOUT_ENGAGEMENT: "嗯，也许你说得对。不过我现在没什么可补充的。",
        }
        return patterns.get(
            signal.resistance_pattern,
            "我现在还不太想谈这个，可以先换个话题吗？",
        )


def _distinctive_clauses(content: str) -> list[str]:
    clauses = [
        item.strip()
        for item in re.split(r"[，。！？；,.!?;\n]+", content)
        if len(normalize_disclosure_text(item)) >= 10
    ]
    return clauses[:4]


def _disclosure_evidence(utterance: str, content: str) -> str | None:
    normalized_utterance = normalize_disclosure_text(utterance)
    normalized_content = normalize_disclosure_text(content)
    # Routine facts such as names ("明山"), occupations ("学生") or education
    # ("大专") are legitimately two characters long, so the literal-match
    # threshold must accept them.  It stays above the leakage detector's
    # distinctive-clause threshold because the fact has already been both
    # declared by the client and authorized for this turn.
    if len(normalized_content) >= 2 and normalized_content in normalized_utterance:
        return content
    clauses = [
        item.strip()
        for item in re.split(r"[，。！？；,.!?;\n]+", content)
        # Short layer labels such as “表层经历” can still be valid, directly
        # observable disclosure evidence.  This threshold is intentionally
        # lower than the leakage detector's distinctive-clause threshold:
        # here the fact has already been authorized for this turn.
        if len(normalize_disclosure_text(item)) >= 2
    ]
    for clause in clauses:
        normalized_clause = normalize_disclosure_text(clause)
        if normalized_clause in normalized_utterance:
            return clause
    if _fuzzy_disclosure_overlap(normalized_utterance, normalized_content):
        return utterance.strip()
    return None


def _fuzzy_disclosure_overlap(left: str, right: str) -> bool:
    if min(len(left), len(right)) < 8:
        return False
    shared = set(left) & set(right)
    if len(shared) < 6:
        return False
    overlap = len(shared) / min(len(set(left)), len(set(right)))
    sequence = SequenceMatcher(None, left, right).ratio()
    return overlap >= 0.6 and sequence >= 0.46
