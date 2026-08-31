from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pydantic import Field

from ..domain import (
    ClientBehaviorType,
    ClientProfile,
    ClientReactionType,
    ClientState,
    ClientTurnSignal,
    DisclosureDecision,
    Message,
    ReactionIntensity,
    ResistancePatternType,
    TrustChange,
)
from ..domain.models import StrictModel

if TYPE_CHECKING:
    from ..agents.client import ClientAgent


@dataclass(slots=True)
class ClientPolicyInput:
    profile: ClientProfile
    state: ClientState
    counselor_message: str
    recent_messages: list[Message]
    disclosure: DisclosureDecision
    recent_signals: list[ClientTurnSignal]
    turn_index: int


class ClientPolicy(Protocol):
    name: str

    async def plan_turn(self, turn: ClientPolicyInput) -> ClientTurnSignal: ...


class CompactPatientActPolicy:
    name = "compact_patientact"

    def __init__(self, agent: ClientAgent):
        self.agent = agent

    async def plan_turn(self, turn: ClientPolicyInput) -> ClientTurnSignal:
        signal = await self.agent.plan_turn(
            profile=turn.profile,
            state=turn.state,
            counselor_message=turn.counselor_message,
            recent_messages=turn.recent_messages,
            disclosure=turn.disclosure,
            recent_signals=turn.recent_signals,
            turn_index=turn.turn_index,
        )
        return signal.model_copy(
            update={"policy": self.name, "planning_model_calls": 1}
        )


class SimpleClientPolicy:
    name = "simple"

    async def plan_turn(self, turn: ClientPolicyInput) -> ClientTurnSignal:
        return ClientTurnSignal(
            behavior=ClientBehaviorType.RECOUNTING,
            retrieved_fact_ids=[item.item_id for item in turn.disclosure.retrieved],
            blocked_fact_ids=[item.item_id for item in turn.disclosure.blocked],
            rationale="PATIENTACT internal planning disabled by configuration.",
            policy=self.name,
            planning_model_calls=0,
        )


class ReactionDecision(StrictModel):
    reaction: ClientReactionType = ClientReactionType.NO_REACTION
    intensity: ReactionIntensity = ReactionIntensity.LOW
    rationale: str = ""


class BehaviorDecision(StrictModel):
    behavior: ClientBehaviorType = ClientBehaviorType.SIMPLE_RESPONSE
    retrieved_fact_ids: list[str] = Field(default_factory=list)
    blocked_fact_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class ResistanceDecision(StrictModel):
    resistance_pattern: ResistancePatternType
    rationale: str = ""


class TrustDecision(StrictModel):
    trust_change: TrustChange = TrustChange.UNCHANGED
    rationale: str = ""


FAITHFUL_PROMPT = """你是模拟来访者的内部决策器。只完成 input_payload 指定的 decision_step。
私有画像只用于一致性；只有 disclosure_decision.retrieved 中的 item 可以选择披露。
blocked 只有元数据，不得在 rationale 中推测或复述正文。普通同理不应自动提高信任。
只输出给定 schema 的 JSON，不生成来访者台词。"""


class FaithfulPatientActPolicy:
    """Research adapter preserving PatientAct's separate decision stages."""

    name = "faithful_patientact"

    def __init__(self, agent: ClientAgent):
        self.agent = agent

    async def plan_turn(self, turn: ClientPolicyInput) -> ClientTurnSignal:
        base = {
            "private_client_profile": turn.profile.model_dump(mode="json"),
            "simulation_state": turn.state.model_dump(mode="json"),
            "counselor_message": turn.counselor_message,
            "recent_messages": [
                item.model_dump(mode="json") for item in turn.recent_messages[-8:]
            ],
            "disclosure_decision": turn.disclosure.model_dump(mode="json"),
            "recent_signals": [
                item.model_dump(mode="json") for item in turn.recent_signals[-3:]
            ],
            "turn_index": turn.turn_index,
        }
        reaction = await self._decide(base, "reaction", ReactionDecision)
        behavior = await self._decide(
            {**base, "reaction_decision": reaction.model_dump(mode="json")},
            "behavior",
            BehaviorDecision,
        )
        resistance = None
        if behavior.behavior is ClientBehaviorType.RESISTANCE:
            resistance = await self._decide(
                {
                    **base,
                    "reaction_decision": reaction.model_dump(mode="json"),
                    "behavior_decision": behavior.model_dump(mode="json"),
                },
                "resistance",
                ResistanceDecision,
            )
        trust = await self._decide(
            {
                **base,
                "reaction_decision": reaction.model_dump(mode="json"),
                "behavior_decision": behavior.model_dump(mode="json"),
                "resistance_decision": (
                    resistance.model_dump(mode="json") if resistance else None
                ),
            },
            "trust",
            TrustDecision,
        )
        retrieved = {item.item_id for item in turn.disclosure.retrieved}
        blocked = {item.item_id for item in turn.disclosure.blocked}
        signal = ClientTurnSignal(
            reaction=reaction.reaction,
            intensity=reaction.intensity,
            behavior=behavior.behavior,
            resistance_pattern=(resistance.resistance_pattern if resistance else None),
            retrieved_fact_ids=(
                [] if turn.disclosure.ambiguous_fact_ids else
                [item for item in behavior.retrieved_fact_ids if item in retrieved]
            ),
            blocked_fact_ids=[
                item for item in behavior.blocked_fact_ids if item in blocked
            ],
            trust_change=trust.trust_change,
            rationale=" ".join(
                part for part in (
                    reaction.rationale,
                    behavior.rationale,
                    resistance.rationale if resistance else "",
                    trust.rationale,
                ) if part
            ),
            policy=self.name,
            planning_model_calls=4 if resistance else 3,
        )
        return self.agent._apply_pullback(signal, turn.state, turn.recent_signals)

    async def _decide(self, base: dict, step: str, schema: type[StrictModel]):
        payload = {**base, "decision_step": step}
        result = await self.agent.gateway.complete_structured(
            role="client",
            system_prompt=FAITHFUL_PROMPT,
            input_payload=payload,
            output_schema=schema,
            temperature=self.agent.planning_temperature,
        )
        return schema.model_validate(result)


def create_client_policy(name: str, agent: ClientAgent) -> ClientPolicy:
    if name == "compact_patientact":
        return CompactPatientActPolicy(agent)
    if name == "faithful_patientact":
        return FaithfulPatientActPolicy(agent)
    if name == "simple":
        return SimpleClientPolicy()
    raise ValueError(f"Unknown client policy: {name}")
