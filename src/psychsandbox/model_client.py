from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from .domain import ClientGeneration, CounselorDecision, CounselorTurn, RiskLevel


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


def _mock_counselor_response(intervention: str, client: str, stage: str) -> str:
    if stage == "consolidation":
        return "今天我们梳理了压力、自动想法和应对之间的联系。你愿意尝试的最小行动是什么？"
    templates = {
        "empathic_reflection": "听起来你在紧张和疲惫里坚持了很久。最近哪个具体时刻最难受？",
        "open_question": "谢谢你愿意说出来。你希望我们先从哪一部分开始理解？",
        "clarification": "当时具体发生了什么？那一刻你脑中最先出现的想法是什么？",
        "socratic_question": "支持这个想法的证据有哪些？又有没有哪怕一个例外？",
        "behavioral_suggestion": "我们先不要求一次解决全部问题。你愿意选择一个十分钟内可完成的小行动吗？",
        "session_summary": "今天我们确认了一个重要模式。哪些理解准确，哪些需要修正？",
    }
    return templates.get(intervention, f"我听到你提到“{client[:24]}”。这对你最直接的影响是什么？")
