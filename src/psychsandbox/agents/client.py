from __future__ import annotations

import re
from typing import Any

from ..client_simulation.prompts import (
    CLIENT_PLANNER_SYSTEM,
    CLIENT_PROMPT_VERSION,
    CLIENT_UTTERANCE_SYSTEM,
)
from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientProfile,
    ClientReactionType,
    ClientState,
    ClientTurnSignal,
    ClientUtterance,
    DisclosureDecision,
    HiddenFact,
    Message,
    ResistancePatternType,
    UnlockedFact,
)
from ..model_client import ModelGateway
from ..runtime.leakage import PrematureDisclosureGuard, normalize_disclosure_text


THERAPEUTIC_BEHAVIORS = {
    ClientBehaviorType.COGNITIVE_EXPLORATION,
    ClientBehaviorType.AFFECTIVE_EXPLORATION,
    ClientBehaviorType.INSIGHT,
    ClientBehaviorType.DISCUSSING_PLANS,
}


class ClientAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        temperature: float = 0.8,
        *,
        planning_temperature: float = 0.1,
        pullback_after: int = 2,
        leak_retry_limit: int = 1,
        leakage_guard: PrematureDisclosureGuard | None = None,
    ):
        self.gateway = gateway
        self.temperature = temperature
        self.planning_temperature = planning_temperature
        self.pullback_after = pullback_after
        self.leak_retry_limit = leak_retry_limit
        self.leakage_guard = leakage_guard or PrematureDisclosureGuard()

    async def plan_turn(
        self,
        *,
        profile: ClientProfile,
        state: ClientState,
        counselor_message: str,
        recent_messages: list[Message],
        disclosure: DisclosureDecision,
        recent_signals: list[ClientTurnSignal],
        turn_index: int,
    ) -> ClientTurnSignal:
        result = await self.gateway.complete_structured(
            role="client",
            system_prompt=CLIENT_PLANNER_SYSTEM,
            input_payload={
                "private_client_profile": profile.model_dump(mode="json"),
                "simulation_state": state.model_dump(mode="json"),
                "counselor_message": counselor_message,
                "recent_messages": [
                    item.model_dump(mode="json") for item in recent_messages[-8:]
                ],
                "disclosure_decision": disclosure.model_dump(mode="json"),
                "recent_signals": [
                    item.model_dump(mode="json") for item in recent_signals[-3:]
                ],
                "turn_index": turn_index,
            },
            output_schema=ClientTurnSignal,
            temperature=self.planning_temperature,
        )
        signal = ClientTurnSignal.model_validate(result)
        signal.retrieved_fact_ids = [
            item
            for item in signal.retrieved_fact_ids
            if item in {fact.fact_id for fact in disclosure.retrieved}
        ]
        signal.blocked_fact_ids = [
            item
            for item in signal.blocked_fact_ids
            if item in {fact.fact_id for fact in disclosure.blocked}
        ]
        if disclosure.ambiguous_fact_ids:
            signal.retrieved_fact_ids = []
        return self._apply_pullback(signal, state, recent_signals)

    async def generate_utterance(
        self,
        *,
        profile: ClientProfile,
        state: ClientState,
        counselor_message: str,
        recent_messages: list[Message],
        disclosure: DisclosureDecision,
        signal: ClientTurnSignal,
        already_disclosed_ids: set[str],
        turn_index: int,
        disclosed_levels: dict[str, int] | None = None,
        known_memories: list[UnlockedFact] | None = None,
    ) -> tuple[ClientGeneration, dict[str, Any]]:
        known_levels = dict(disclosed_levels or {})
        for item in already_disclosed_ids:
            fact = next((fact for fact in profile.hidden_facts if fact.fact_id == item), None)
            if fact is not None:
                known_levels.setdefault(item, len(fact.disclosure_layers))
        selected_ids = set(signal.retrieved_fact_ids)
        if disclosure.ambiguous_fact_ids:
            selected_ids.clear()
        allowed_facts = [
            item for item in disclosure.retrieved if item.fact_id in selected_ids
        ]
        allowed_levels = {
            item.fact_id: max(known_levels.get(item.fact_id, 0), item.disclosure_level)
            for item in allowed_facts
        }
        allowed_ids = set(allowed_levels)
        public_texts = self._public_authorized_texts(profile, known_memories or [])
        unauthorized = self._unauthorized_remainders(
            profile.hidden_facts,
            # Current authorized layers may be spoken now.  Earlier sessions
            # authorize only their stored evidence text, not the rest of the
            # canonical layer that was never actually verbalized.
            allowed_levels,
            public_texts,
        )
        attempts: list[dict[str, Any]] = []
        utterance: ClientUtterance | None = None
        repair_instruction = ""
        for attempt in range(self.leak_retry_limit + 1):
            result = await self.gateway.complete_structured(
                role="client",
                system_prompt=CLIENT_UTTERANCE_SYSTEM,
                input_payload=self.build_utterance_payload(
                    profile=profile,
                    state=state,
                    counselor_message=counselor_message,
                    recent_messages=recent_messages,
                    disclosure=disclosure,
                    signal=signal,
                    turn_index=turn_index,
                    repair_instruction=repair_instruction,
                    known_memories=known_memories or [],
                ),
                output_schema=ClientUtterance,
                temperature=self.temperature,
            )
            raw_utterance = ClientUtterance.model_validate(result)
            declared_fact_ids = list(raw_utterance.disclosed_fact_ids)
            confirmed_ids, unsubstantiated_ids, disclosed_evidence = (
                self.leakage_guard.substantiate(
                    raw_utterance.utterance,
                    declared_fact_ids,
                    allowed_facts,
                )
            )
            utterance = raw_utterance.model_copy(
                update={"disclosed_fact_ids": confirmed_ids}
            )
            check = self.leakage_guard.inspect(
                utterance.utterance,
                declared_fact_ids,
                unauthorized,
                allowed_ids,
            )
            attempts.append(
                {
                    "attempt": attempt + 1,
                    **check.as_dict(),
                    "unsubstantiated_fact_ids": unsubstantiated_ids,
                    "disclosed_evidence": disclosed_evidence,
                }
            )
            if not check.leaked:
                break
            repair_instruction = (
                "上次回答提前使用了未授权事实ID："
                + ", ".join(check.leaked_fact_ids)
                + "。重新回答，不得暗示这些经历；只表现当前反应和边界。"
            )
        used_fallback = bool(attempts and attempts[-1]["leaked"])
        if utterance is None or used_fallback:
            utterance = ClientUtterance(
                utterance=self.leakage_guard.safe_fallback(signal),
                disclosed_fact_ids=[],
            )
        generation = self._generation_from_signal(utterance, signal)
        return generation, {
            "attempts": attempts,
            "retry_count": max(0, len(attempts) - 1),
            "used_fallback": used_fallback,
            "disclosed_evidence": (
                {} if used_fallback or not attempts
                else attempts[-1]["disclosed_evidence"]
            ),
        }

    def build_utterance_payload(
        self,
        *,
        profile: ClientProfile,
        state: ClientState,
        counselor_message: str,
        recent_messages: list[Message],
        disclosure: DisclosureDecision,
        signal: ClientTurnSignal,
        turn_index: int,
        repair_instruction: str = "",
        known_memories: list[UnlockedFact] | None = None,
    ) -> dict[str, Any]:
        traits = profile.static_traits
        payload: dict[str, Any] = {
            "static_profile": {
                "name": traits.name,
                "age": traits.age,
                "gender": traits.gender,
                "occupation": traits.occupation,
                "language_features": traits.language_features,
                "main_problem": profile.main_problem,
                "topic": profile.topic,
                "language_style": profile.language_style,
                "personality": profile.personality.model_dump(mode="json"),
            },
            "simulation_state": state.model_dump(mode="json"),
            "counselor_message": counselor_message,
            "recent_messages": [
                item.model_dump(mode="json") for item in recent_messages[-8:]
            ],
            "known_memories": [
                item.model_dump(mode="json")
                for item in (known_memories or [])[-12:]
            ],
            "available_memories": [
                item.model_dump(mode="json")
                for item in disclosure.retrieved
                if item.fact_id in set(signal.retrieved_fact_ids)
                and not disclosure.ambiguous_fact_ids
            ],
            "blocked_topics": [
                item.model_dump(mode="json") for item in disclosure.blocked
            ],
            "ambiguous_fact_ids": disclosure.ambiguous_fact_ids,
            "turn_signal": signal.model_dump(mode="json"),
            "turn_index": turn_index,
        }
        if repair_instruction:
            payload["repair_instruction"] = repair_instruction
        return payload

    @staticmethod
    def _unauthorized_remainders(
        facts: list[HiddenFact],
        authorized_levels: dict[str, int],
        public_texts: list[str] | None = None,
    ) -> list[HiddenFact]:
        public = normalize_disclosure_text(" ".join(public_texts or []))
        remaining: list[HiddenFact] = []
        for fact in facts:
            level = authorized_levels.get(fact.fact_id, 0)
            if level >= len(fact.disclosure_layers):
                continue
            final = fact.disclosure_layers[-1]
            authorized = fact.disclosure_layers[level - 1] if level else ""
            hidden_text = final[len(authorized):].lstrip(" ，。！？；,!?;")
            clauses = [
                item.strip()
                for item in re.split(r"(?<=[，。！？；,.!?;])", hidden_text)
                if item.strip()
                and normalize_disclosure_text(item) not in public
            ]
            if clauses:
                remaining.append(
                    fact.model_copy(update={"content": "".join(clauses)})
                )
        return remaining

    @staticmethod
    def _public_authorized_texts(
        profile: ClientProfile,
        known_memories: list[UnlockedFact],
    ) -> list[str]:
        traits = profile.static_traits
        return [
            str(traits.name),
            str(traits.age),
            str(traits.gender),
            str(traits.occupation),
            traits.language_features,
            profile.main_problem,
            profile.topic,
            profile.language_style,
            *(item.content for item in known_memories),
        ]

    async def respond(
        self,
        *,
        profile: ClientProfile,
        state: ClientState,
        plan,
        counselor_message: str,
        recent_messages: list[Message],
        allowed_facts: list[HiddenFact],
        turn_index: int,
    ) -> ClientGeneration:
        """Compatibility entry point for callers that have not adopted two-stage planning."""
        del plan
        disclosure = DisclosureDecision(retrieved=allowed_facts)
        signal = await self.plan_turn(
            profile=profile,
            state=state,
            counselor_message=counselor_message,
            recent_messages=recent_messages,
            disclosure=disclosure,
            recent_signals=[],
            turn_index=turn_index,
        )
        generation, _ = await self.generate_utterance(
            profile=profile,
            state=state,
            counselor_message=counselor_message,
            recent_messages=recent_messages,
            disclosure=disclosure,
            signal=signal,
            already_disclosed_ids=set(),
            turn_index=turn_index,
        )
        return generation

    def _apply_pullback(
        self,
        signal: ClientTurnSignal,
        state: ClientState,
        recent_signals: list[ClientTurnSignal],
    ) -> ClientTurnSignal:
        if state.trust >= 0.75 or signal.behavior not in THERAPEUTIC_BEHAVIORS:
            return signal
        prior = recent_signals[-self.pullback_after :]
        if len(prior) < self.pullback_after or not all(
            item.behavior in THERAPEUTIC_BEHAVIORS for item in prior
        ):
            return signal
        return signal.model_copy(
            update={
                "behavior": ClientBehaviorType.SIMPLE_RESPONSE,
                "resistance_pattern": None,
                "rationale": (
                    signal.rationale
                    + " 连续探索后自然回撤，暂时缩短回应。"
                ).strip(),
            }
        )

    @staticmethod
    def _generation_from_signal(
        utterance: ClientUtterance,
        signal: ClientTurnSignal,
    ) -> ClientGeneration:
        is_resistance = signal.behavior is ClientBehaviorType.RESISTANCE
        progress = {
            ClientReactionType.GAINED_CLARITY: 0.07,
            ClientReactionType.HOPEFUL: 0.05,
            ClientReactionType.UNDERSTOOD: 0.02,
            ClientReactionType.MISUNDERSTOOD: -0.06,
            ClientReactionType.SCARED: -0.05,
            ClientReactionType.CHALLENGED: -0.02,
            ClientReactionType.NO_REACTION: 0.0,
        }[signal.reaction]
        if signal.behavior is ClientBehaviorType.INSIGHT:
            progress += 0.03
        elif signal.behavior is ClientBehaviorType.DISCUSSING_PLANS:
            progress += 0.02
        return ClientGeneration(
            utterance=utterance.utterance,
            expressed_emotions=(
                []
                if signal.reaction is ClientReactionType.NO_REACTION
                else [signal.reaction.value]
            ),
            disclosed_fact_ids=utterance.disclosed_fact_ids,
            cooperation=0.3 if is_resistance else 0.45
            if signal.behavior is ClientBehaviorType.SIMPLE_RESPONSE
            else 0.7,
            resistance=0.75 if is_resistance else 0.4
            if signal.reaction in {ClientReactionType.SCARED, ClientReactionType.CHALLENGED}
            else 0.25,
            goal_progress_signal=progress,
        )
