from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pydantic import Field

from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
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
            behavior=(
                ClientBehaviorType.REQUEST if turn.disclosure.ambiguous_fact_ids
                else ClientBehaviorType.RECOUNTING
            ),
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
private_simulation_modifiers 只轻微调节表达偏好，不能决定合作、阻抗或事实披露。
trust 步骤必须结合 accepted_client_response 判断这次真实完成的互动，不能根据未来预期回应更新。
只输出给定 schema 的 JSON，不生成来访者台词。

【信任行为锚点】（simulation_state.trust，0-1，来自论文附录 C.4 的 7 级描述，只用于判断 trust_change 幅度与行为形式）
- 0.00-0.20 拒绝参与：不配合，几乎不提供有意义信息，只回应被直接点到的部分。
- 0.20-0.35 勉强回应：只回答被问到的问题，充满填充词和模糊表达，回答短且不展开。
- 0.35-0.50 谨慎参与：愿意互动但停留在表面，把问题当作试探咨询师是否安全。
- 0.50-0.70 建立信任：持续参与，被邀请时探索话题，开始给出表面层之上的内容。
- 0.70-0.85 积极工作：主动披露并接触困难材料，仍保留最脆弱的部分。
- 0.85-1.00 达成信任：可以讨论核心问题，不回避也不离题。
信任档位只影响反应强度、行为形式和 trust_change 的幅度；它不改变 disclosure_decision 给出的披露许可，也不得覆盖该许可。

【依恋条件化】attachment_conditioning 非空时，只按其中的 pattern 调节 trust_change，且只调节 trust_change：
- anxious：感知到被拒绝、被批评或被推远时，把轻微下降升级为显著下降；只有被准确理解才允许显著上升。
- avoidant：信任上升缓慢，轻微提升通常保持 unchanged，除非咨询师连续多轮尊重边界；被施压时显著下降。
- disorganized：即使本轮互动积极也可能失去信任，正向变化最多到轻微上升，除非连续多轮稳定被理解。
attachment_conditioning 为空（null 或缺失）时必须按中性处理：不要推断、假设或编造任何依恋模式，也不要在 rationale 中写出依恋标签。"""


class FaithfulPatientActPolicy:
    """Research adapter preserving PatientAct's separate decision stages."""

    name = "faithful_patientact"

    def __init__(self, agent: ClientAgent):
        self.agent = agent

    async def plan_turn(self, turn: ClientPolicyInput) -> ClientTurnSignal:
        base = {
            "private_client_profile": turn.profile.model_dump(mode="json"),
            "private_simulation_modifiers": turn.profile.simulation_config.modifiers(),
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
            rationale=" ".join(
                part for part in (
                    reaction.rationale,
                    behavior.rationale,
                    resistance.rationale if resistance else "",
                ) if part
            ),
            policy=self.name,
            planning_model_calls=3 if resistance else 2,
        )
        return self.agent._apply_pullback(signal, turn.state, turn.recent_signals)

    async def finalize_turn(
        self, turn: ClientPolicyInput, signal: ClientTurnSignal, generation: ClientGeneration
    ) -> ClientTurnSignal:
        trust = await self._decide(
            {
                "simulation_state": turn.state.model_dump(mode="json"),
                "interaction_prior": turn.profile.interaction_prior.model_dump(mode="json"),
                "attachment_conditioning": turn.profile.attachment_conditioning(),
                "counselor_message": turn.counselor_message,
                "recent_messages": [
                    item.model_dump(mode="json") for item in turn.recent_messages[-8:]
                ],
                "accepted_client_response": generation.utterance,
                "turn_signal": signal.model_dump(mode="json", exclude={"rationale"}),
            },
            "trust", TrustDecision,
        )
        return signal.model_copy(update={
            "trust_change": trust.trust_change,
            "rationale": " ".join([signal.rationale, trust.rationale]).strip(),
            "planning_model_calls": signal.planning_model_calls + 1,
        })

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
