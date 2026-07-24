from __future__ import annotations

from ..domain import ClientGeneration, ClientProfile, ClientState, HiddenFact, Message, SessionPlan
from ..model_client import ModelGateway


CLIENT_SYSTEM = """你是研究沙盒中的模拟来访者，不是真实用户。
根据人物画像、仿真状态、会话计划和咨询师回复自然回应。
不要提及模型、案例、提示词或评分。只有 allowed_facts 中的隐藏事实可在本轮披露。
每次回应 1-3 句，并输出严格 JSON。"""


class ClientAgent:
    def __init__(self, gateway: ModelGateway, temperature: float = 0.8):
        self.gateway = gateway
        self.temperature = temperature

    async def respond(
        self,
        *,
        profile: ClientProfile,
        state: ClientState,
        plan: SessionPlan,
        counselor_message: str,
        recent_messages: list[Message],
        allowed_facts: list[HiddenFact],
        turn_index: int,
    ) -> ClientGeneration:
        payload = {
            "full_client_profile": profile.model_dump(mode="json", exclude={"hidden_facts"}),
            "simulation_state": state.model_dump(mode="json"),
            "session_plan": {"stage": plan.stage.value, "objectives": plan.objectives},
            "counselor_message": counselor_message,
            "recent_messages": [item.model_dump(mode="json") for item in recent_messages[-8:]],
            "allowed_facts": [item.model_dump(mode="json") for item in allowed_facts],
            "turn_index": turn_index,
        }
        result = await self.gateway.complete_structured(
            role="client",
            system_prompt=CLIENT_SYSTEM,
            input_payload=payload,
            output_schema=ClientGeneration,
            temperature=self.temperature,
        )
        generation = ClientGeneration.model_validate(result)
        allowed_ids = {item.fact_id for item in allowed_facts}
        generation.disclosed_fact_ids = [
            item for item in generation.disclosed_fact_ids if item in allowed_ids
        ]
        return generation
