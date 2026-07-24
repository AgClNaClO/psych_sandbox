from __future__ import annotations

from ..domain import ClientProfile, ClientState, HiddenFact, UnlockedFact


class DisclosureGate:
    def allowed(
        self,
        profile: ClientProfile,
        state: ClientState,
        text: str,
        disclosed_ids: set[str],
    ) -> list[HiddenFact]:
        lowered = text.lower()
        return [
            fact for fact in profile.hidden_facts
            if fact.fact_id not in disclosed_ids
            and state.trust >= fact.minimum_trust
            and (
                not fact.required_topics
                or any(topic.lower() in lowered for topic in fact.required_topics)
            )
        ]

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
