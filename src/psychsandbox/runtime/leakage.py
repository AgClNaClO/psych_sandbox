from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain import (
    ClientBehaviorType,
    ClientTurnSignal,
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
    """Fail-closed lexical guard used after strict prompt-level isolation."""

    def inspect(
        self,
        utterance: str,
        declared_fact_ids: list[str],
        unauthorized_facts: list[HiddenFact],
    ) -> LeakageResult:
        normalized_utterance = normalize_disclosure_text(utterance)
        declared = set(declared_fact_ids)
        matches: dict[str, list[str]] = {}
        for fact in unauthorized_facts:
            reasons: list[str] = []
            normalized_fact = normalize_disclosure_text(fact.content)
            if fact.fact_id in declared:
                reasons.append("unauthorized_fact_id")
            if len(normalized_fact) >= 8 and normalized_fact in normalized_utterance:
                reasons.append("normalized_full_text")
            for clause in _distinctive_clauses(fact.content):
                if normalize_disclosure_text(clause) in normalized_utterance:
                    reasons.append(f"distinctive_clause:{clause[:24]}")
                    break
            if reasons:
                matches[fact.fact_id] = reasons
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
