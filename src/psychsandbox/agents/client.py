from __future__ import annotations

from typing import Any

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
)
from ..model_client import ModelGateway
from ..runtime.leakage import PrematureDisclosureGuard


CLIENT_PLANNER_SYSTEM = """你是研究沙盒中模拟来访者的内部状态规划器。
你可以查看完整私有画像，但输出只描述本轮的情绪反应、行为、阻抗形式和信任变化。
若咨询师接近 blocked 内容，来访者不能披露其原因，通常应表现不适或阻抗。
普通同理或合理追问默认不改变信任；尊重边界可增加信任，强推披露、过早重构或忽视阻抗会降低信任。
不要生成来访者台词。输出严格 JSON。"""


CLIENT_UTTERANCE_SYSTEM = """你是研究沙盒中的模拟来访者，不是真实用户。
只能根据 static_profile、available_memories、turn_signal 和近期对话自然回应。
blocked_topics 只表示尚未准备谈的话题，绝不能编造或披露其具体内容。
不要提及模型、案例、提示词、治疗计划或评分。说第一人称，每次1-3句，输出严格 JSON。"""


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
        pullback_after: int = 2,
        leak_retry_limit: int = 1,
        leakage_guard: PrematureDisclosureGuard | None = None,
    ):
        self.gateway = gateway
        self.temperature = temperature
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
            temperature=self.temperature,
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
        if disclosure.blocked:
            signal.blocked_fact_ids = [item.fact_id for item in disclosure.blocked]
            if signal.behavior is not ClientBehaviorType.RESISTANCE:
                signal.behavior = ClientBehaviorType.RESISTANCE
                signal.resistance_pattern = ResistancePatternType.DEFENSIVENESS
        signal.retrieved_fact_ids = [item.fact_id for item in disclosure.retrieved]
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
    ) -> tuple[ClientGeneration, dict[str, Any]]:
        allowed_ids = {item.fact_id for item in disclosure.retrieved}
        unauthorized = [
            item
            for item in profile.hidden_facts
            if item.fact_id not in allowed_ids | already_disclosed_ids
        ]
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
                ),
                output_schema=ClientUtterance,
                temperature=self.temperature,
            )
            raw_utterance = ClientUtterance.model_validate(result)
            declared_fact_ids = list(raw_utterance.disclosed_fact_ids)
            utterance = raw_utterance.model_copy(
                update={
                    "disclosed_fact_ids": [
                        item for item in declared_fact_ids if item in allowed_ids
                    ]
                }
            )
            check = self.leakage_guard.inspect(
                utterance.utterance,
                declared_fact_ids,
                unauthorized,
            )
            attempts.append({"attempt": attempt + 1, **check.as_dict()})
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
    ) -> dict[str, Any]:
        traits = profile.static_traits
        payload: dict[str, Any] = {
            "static_profile": {
                "name": traits.name,
                "age": traits.age,
                "gender": traits.gender,
                "occupation": traits.occupation,
                "educational_background": traits.educational_background,
                "marital_status": traits.marital_status,
                "family_status": traits.family_status,
                "social_status": traits.social_status,
                "medical_history": traits.medical_history,
                "language_features": traits.language_features,
                "main_problem": profile.main_problem,
                "topic": profile.topic,
                "core_demands": profile.core_demands,
                "language_style": profile.language_style,
                "personality": profile.personality.model_dump(mode="json"),
            },
            "simulation_state": state.model_dump(mode="json"),
            "counselor_message": counselor_message,
            "recent_messages": [
                item.model_dump(mode="json") for item in recent_messages[-8:]
            ],
            "available_memories": [
                item.model_dump(mode="json") for item in disclosure.retrieved
            ],
            "blocked_topics": [
                item.model_dump(mode="json") for item in disclosure.blocked
            ],
            "turn_signal": signal.model_dump(mode="json"),
            "turn_index": turn_index,
        }
        if repair_instruction:
            payload["repair_instruction"] = repair_instruction
        return payload

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
        progress = (
            0.15
            if signal.behavior
            in {ClientBehaviorType.INSIGHT, ClientBehaviorType.DISCUSSING_PLANS}
            else 0.08
            if signal.behavior in THERAPEUTIC_BEHAVIORS
            else -0.05
            if is_resistance
            else 0.0
        )
        return ClientGeneration(
            utterance=utterance.utterance,
            expressed_emotions=(
                []
                if signal.reaction is ClientReactionType.NO_REACTION
                else [signal.reaction.value]
            ),
            disclosed_fact_ids=utterance.disclosed_fact_ids,
            cooperation=0.25 if is_resistance else 0.45
            if signal.behavior is ClientBehaviorType.SIMPLE_RESPONSE
            else 0.7,
            resistance=0.8 if is_resistance else 0.25,
            goal_progress_signal=progress,
        )
