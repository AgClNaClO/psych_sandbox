from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from .domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientReactionType,
    ClientTurnSignal,
    ClientUtterance,
    CounselorDecision,
    CounselorTurn,
    ReactionIntensity,
    ResistancePatternType,
    RiskLevel,
    TrustChange,
)


class ModelGateway(ABC):
    provider_name = "abstract"

    @abstractmethod
    async def complete_structured(
        self, *, role: str, system_prompt: str, input_payload: dict[str, Any],
        output_schema: type[BaseModel], temperature: float
    ) -> BaseModel:
        raise NotImplementedError


class MockGateway(ModelGateway):
    provider_name = "mock"

    async def complete_structured(
        self, *, role: str, system_prompt: str, input_payload: dict[str, Any],
        output_schema: type[BaseModel], temperature: float
    ) -> BaseModel:
        del role, system_prompt, temperature
        if output_schema is CounselorTurn:
            skills = input_payload.get("candidate_atomic_skills", [])
            selected = skills[:1]
            ids = [item["skill_id"] for item in selected]
            metas = list(dict.fromkeys(item["meta_skill_id"] for item in selected))
            turn = int(input_payload.get("counselor_turn_count", 0))
            return CounselorTurn(
                decision=CounselorDecision(
                    assessment="来访者正在表达当前困扰，需要确认体验并围绕本次目标探索。",
                    state_observation="当前痛苦较高，但仍愿意参与对话。",
                    selected_meta_skill_ids=metas,
                    selected_atomic_skill_ids=ids,
                    strategy="先共情和澄清，再用一个开放问题推进。",
                    goal_progress=min(0.9, 0.15 + turn * 0.12),
                    risk_level=RiskLevel(input_payload.get("risk_level", "low")),
                ),
                response=_mock_counselor_response(
                    selected[0].get("intervention_type", "") if selected else "",
                    input_payload.get("client_message", ""),
                    input_payload.get("session_stage", ""),
                    turn,
                ),
            )
        if output_schema is ClientGeneration:
            allowed = input_payload.get("allowed_facts", [])
            turn = int(input_payload.get("turn_index", 0))
            if allowed and turn >= 2:
                fact = allowed[0]
                return ClientGeneration(
                    utterance=f"其实还有一件事我一直不太敢说：{fact['content']}",
                    expressed_emotions=["anxiety", "shame"],
                    disclosed_fact_ids=[fact["fact_id"]],
                    cooperation=0.72,
                    resistance=0.28,
                    goal_progress_signal=0.15,
                )
            responses = [
                "最近这件事一直在我脑子里转，我很累，但又停不下来。",
                "我最担心的是再出错，别人会觉得我根本没有能力。",
                "这样说以后，我好像能看到压力和那些想法之间的联系了。",
                "我愿意先把一个具体情境写下来，看看当时脑中出现了什么。",
            ]
            return ClientGeneration(
                utterance=responses[turn % len(responses)],
                expressed_emotions=["anxiety"],
                cooperation=min(0.85, 0.5 + turn * 0.06),
                resistance=max(0.15, 0.48 - turn * 0.05),
                goal_progress_signal=0.08,
            )
        if output_schema is ClientTurnSignal:
            disclosure = input_payload.get("disclosure_decision", {})
            blocked = disclosure.get("blocked", [])
            retrieved = disclosure.get("retrieved", [])
            counselor = input_payload.get("counselor_message", "")
            turn = int(input_payload.get("turn_index", 0))
            if blocked:
                pushed = any(
                    term in counselor
                    for term in ("必须", "一定要", "直接告诉", "别回避", "为什么不")
                )
                return ClientTurnSignal(
                    reaction=ClientReactionType.SCARED
                    if pushed else ClientReactionType.CHALLENGED,
                    intensity=ReactionIntensity.HIGH
                    if pushed else ReactionIntensity.MODERATE,
                    behavior=ClientBehaviorType.RESISTANCE,
                    resistance_pattern=ResistancePatternType.DEFENSIVENESS,
                    blocked_fact_ids=[item["fact_id"] for item in blocked],
                    trust_change=TrustChange.SIGNIFICANT_DECREASE
                    if pushed else TrustChange.SLIGHT_DECREASE,
                    rationale="咨询师接近了当前信任不足以讨论的敏感内容。",
                )
            respected = any(
                term in counselor
                for term in ("不着急", "按你的节奏", "先不谈", "可以换个话题")
            )
            behavior = (
                ClientBehaviorType.COGNITIVE_EXPLORATION
                if turn >= 2
                else ClientBehaviorType.RECOUNTING
            )
            return ClientTurnSignal(
                reaction=ClientReactionType.UNDERSTOOD
                if respected else ClientReactionType.NO_REACTION,
                intensity=ReactionIntensity.MODERATE
                if respected else ReactionIntensity.LOW,
                behavior=behavior,
                retrieved_fact_ids=[item["fact_id"] for item in retrieved],
                trust_change=TrustChange.SLIGHT_INCREASE
                if respected else TrustChange.UNCHANGED,
                rationale="根据当前联盟和可用内容选择回应方式。",
            )
        if output_schema is ClientUtterance:
            signal = input_payload.get("turn_signal", {})
            behavior = signal.get("behavior", "simple_response")
            if input_payload.get("repair_instruction"):
                return ClientUtterance(
                    utterance="我现在还不太想把这部分说得太具体，可以先停一下吗？"
                )
            if behavior == ClientBehaviorType.RESISTANCE.value:
                turn = int(input_payload.get("turn_index", 0))
                resistance_pattern = signal.get("resistance_pattern", "")
                if resistance_pattern == ResistancePatternType.DEFENSIVENESS.value:
                    defensive_responses = [
                        "我现在还没准备好谈这部分，我们能先换个话题吗？",
                        "我已经说过暂时不想谈这个。请先停一下。",
                    ]
                    return ClientUtterance(
                        utterance=defensive_responses[min(turn, 1)]
                    )
                resistance_responses = {
                    ResistancePatternType.MINIMAL_TALK.value: "我现在只想简单说一点，不想展开。",
                    ResistancePatternType.IRRELEVANT_TALK.value: "我们能先聊点别的吗？",
                    ResistancePatternType.SUPERFICIAL.value: "大概就是这样，我还不想说得更深。",
                    ResistancePatternType.INTELLECTUALIZING.value: "我更想先从道理上把这件事分析清楚。",
                    ResistancePatternType.HOSTILITY.value: "这个追问让我不舒服，请先停一下。",
                    ResistancePatternType.COMPLIANCE_WITHOUT_ENGAGEMENT.value: "我可以回答，但感觉自己还没有真正准备好。",
                }
                return ClientUtterance(
                    utterance=resistance_responses.get(
                        resistance_pattern,
                        "我不太想现在谈这个。我们能不能先说说别的？",
                    )
                )
            allowed = input_payload.get("available_memories", [])
            turn = int(input_payload.get("turn_index", 0))
            if allowed and turn >= 2:
                fact = allowed[0]
                return ClientUtterance(
                    utterance=f"其实还有一件事我一直不太敢说：{fact['content']}",
                    disclosed_fact_ids=[fact["fact_id"]],
                )
            responses = [
                "最近这件事一直在我脑子里转，我很累，但又停不下来。",
                "我最担心的是再出错，别人会觉得我根本没有能力。",
                "这样说以后，我好像能看到压力和那些想法之间的联系了。",
                "我现在还不想急着做决定，想先把事情说清楚。",
            ]
            return ClientUtterance(utterance=responses[turn % len(responses)])
        raise ValueError(f"MockGateway does not support {output_schema.__name__}")


class OpenAICompatibleGateway(ModelGateway):
    provider_name = "openai_compatible"

    def __init__(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("API mode requires the openai package") from exc
        api_key = os.getenv("MODEL_API_KEY")
        if not api_key:
            raise RuntimeError("MODEL_API_KEY is required for API mode")
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=os.getenv("MODEL_BASE_URL") or None,
            timeout=float(os.getenv("MODEL_TIMEOUT_SECONDS", "90")),
        )
        counselor = os.getenv("COUNSELOR_MODEL", "")
        self.models = {
            "client": os.getenv("CLIENT_MODEL", ""),
            "counselor": counselor,
            "supervisor": os.getenv("SUPERVISOR_MODEL", counselor),
            "summarizer": os.getenv("SUMMARY_MODEL", counselor),
        }
        if not self.models["client"] or not counselor:
            raise RuntimeError("CLIENT_MODEL and COUNSELOR_MODEL are required")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    async def _complete_text(
        self, *, role: str, system_prompt: str, user_prompt: str, temperature: float
    ) -> str:
        result = await self.client.chat.completions.create(
            model=self.models[role],
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return result.choices[0].message.content or ""

    async def complete_structured(
        self, *, role: str, system_prompt: str, input_payload: dict[str, Any],
        output_schema: type[BaseModel], temperature: float
    ) -> BaseModel:
        payload = dict(input_payload)
        payload["output_schema"] = output_schema.model_json_schema()
        error = ""
        for _ in range(2):
            if error:
                payload["repair_instruction"] = (
                    f"上次输出校验失败：{error}。只返回一个符合 schema 的 JSON 对象。"
                )
            text = await self._complete_text(
                role=role,
                system_prompt=system_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                temperature=temperature,
            )
            try:
                return output_schema.model_validate(json.loads(_strip_fence(text)))
            except Exception as exc:
                error = str(exc)
        raise ValueError(
            f"{self.provider_name}/{role} failed {output_schema.__name__}: {error}"
        )


class LocalTransformersGateway(ModelGateway):
    provider_name = "local_transformers"

    def __init__(self, model_name: str, device: str = "auto") -> None:
        if not model_name:
            raise RuntimeError("local_model_name is required for local mode")
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Install transformers, accelerate and bitsandbytes for local mode"
            ) from exc
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, device_map=device, load_in_4bit=True
        )

    async def complete_structured(
        self, *, role: str, system_prompt: str, input_payload: dict[str, Any],
        output_schema: type[BaseModel], temperature: float
    ) -> BaseModel:
        del role
        prompt = (
            system_prompt + "\nINPUT:\n" + json.dumps(input_payload, ensure_ascii=False)
            + "\nSCHEMA:\n" + json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        output = self.model.generate(
            **inputs, max_new_tokens=768, do_sample=temperature > 0,
            temperature=max(temperature, 0.01),
        )
        text = self.tokenizer.decode(
            output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        return output_schema.model_validate(json.loads(_strip_fence(text)))


def create_gateway(
    provider: str, *, local_model_name: str = "", local_device: str = "auto"
) -> ModelGateway:
    if provider == "mock":
        return MockGateway()
    if provider == "api":
        return OpenAICompatibleGateway()
    if provider == "local":
        return LocalTransformersGateway(local_model_name, local_device)
    raise ValueError(f"Unsupported model provider: {provider}")


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines)
    return value


def _mock_counselor_response(
    intervention: str,
    client: str,
    stage: str,
    turn: int = 0,
) -> str:
    if stage == "consolidation":
        return "今天我们梳理了压力、自动想法和应对之间的联系。你愿意尝试的最小行动是什么？"
    templates = {
        "empathic_reflection": "听起来你在紧张和疲惫里坚持了很久。最近哪个具体时刻最难受？",
        "open_question": "谢谢你愿意说出来。你希望我们先从哪一部分开始理解？",
        "clarification": "当时具体发生了什么？那一刻你脑中最先出现的想法是什么？",
        "socratic_question": "支持这个想法的证据有哪些？又有没有哪怕一个例外？",
        "behavioral_suggestion": "我们先不要求一次解决全部问题。你愿意选择一个十分钟内可完成的小行动吗？",
        "emotion_reflection": "听起来你一边努力维持，一边又越来越难感受到这是不是自己真正想要的。",
        "experiential_clarification": "当你说到这里时，此刻身体和情绪里最明显的感受是什么？",
        "meaning_exploration": "在别人的期待与自己的真实感受之间，哪一部分最让你为难？",
        "choice_support": "如果不急着找标准答案，哪些选择更接近你愿意承担的生活？",
        "session_summary": "今天我们确认了一个重要模式。哪些理解准确，哪些需要修正？",
    }
    if intervention in templates:
        return templates[intervention]
    fallback_responses = [
        "我们可以慢一点。刚才的内容里，哪一部分最希望先被理解？",
        "在继续前，我想确认方向是否合适。你更想谈当前感受、具体事件，还是先确定今天的目标？",
        "我注意到我们可能在重复追问。我们停下来校准一下，什么样的谈法对你更有帮助？",
    ]
    return fallback_responses[turn % len(fallback_responses)]
