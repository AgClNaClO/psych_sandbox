from __future__ import annotations

import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from .domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientReactionType,
    ClientTurnSignal,
    ClientUtterance,
    ClinicalSummary,
    CounselorDecision,
    CounselorTurn,
    ExtractedClientInfo,
    GoalAssessment,
    MergedClientProfile,
    ReactionIntensity,
    ResistancePatternType,
    RiskLevel,
    ScaleItem,
    ScaleItems,
    StaticTraits,
    TrustChange,
)

ECNU_JSON_SCHEMA_MODELS = {"ecnu-plus", "ecnu-turbo"}


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
            ambiguous = disclosure.get("ambiguous_fact_ids", [])
            counselor = input_payload.get("counselor_message", "")
            turn = int(input_payload.get("turn_index", 0))
            if ambiguous:
                return ClientTurnSignal(
                    reaction=ClientReactionType.CHALLENGED,
                    intensity=ReactionIntensity.LOW,
                    behavior=ClientBehaviorType.REQUEST,
                    trust_change=TrustChange.UNCHANGED,
                    rationale="问题可能指向多段经历，先请咨询师具体化。",
                )
            if blocked:
                pushed = any(
                    term in counselor
                    for term in ("必须", "一定要", "直接告诉", "别回避", "为什么不")
                )
                return ClientTurnSignal(
                    reaction=ClientReactionType.SCARED
                    if pushed else ClientReactionType.CHALLENGED,
                    intensity=ReactionIntensity.HIGH if pushed else ReactionIntensity.LOW,
                    behavior=(
                        ClientBehaviorType.RESISTANCE
                        if pushed
                        else ClientBehaviorType.REQUEST
                    ),
                    resistance_pattern=(
                        ResistancePatternType.DEFENSIVENESS if pushed else None
                    ),
                    blocked_fact_ids=[item["fact_id"] for item in blocked],
                    trust_change=TrustChange.SIGNIFICANT_DECREASE
                    if pushed else TrustChange.UNCHANGED,
                    rationale="敏感内容尚未准备披露；是否阻抗取决于咨询师是否施压。",
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
        if output_schema is ScaleItems:
            return _mock_scale_items()

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
            if behavior == ClientBehaviorType.REQUEST.value:
                if input_payload.get("ambiguous_fact_ids"):
                    return ClientUtterance(
                        utterance="你具体是想问哪一段经历？我想先确认一下。"
                    )
                return ClientUtterance(
                    utterance="这部分我还没有准备好细说，可以先从现在的感受谈起吗？"
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

        schema_name = output_schema.__name__
        if schema_name == "_ClientInfoGet":
            return output_schema.model_validate(
                {"client_info_get": _mock_extracted_client_info(input_payload)}
            )
        if schema_name == "_ClientInfoMerge":
            return output_schema.model_validate(
                {"client_info_merge": _mock_merged_client_profile(input_payload)}
            )
        if schema_name == "_SessionSummaryWrapper":
            return output_schema.model_validate(
                {"session_summary": _mock_clinical_summary(input_payload)}
            )
        raise ValueError(f"MockGateway does not support {output_schema.__name__}")


class OpenAICompatibleGateway(ModelGateway):
    provider_name = "openai_compatible"

    def __init__(self, diagnostic_dir: Path | None = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("API mode requires the openai package") from exc
        api_key = os.getenv("MODEL_API_KEY")
        if not api_key:
            raise RuntimeError("MODEL_API_KEY is required for API mode")
        base_url = os.getenv("MODEL_BASE_URL") or None
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
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
        structured_mode = os.getenv("MODEL_STRUCTURED_OUTPUT", "auto").strip().lower()
        if structured_mode not in {"auto", "json_schema", "off"}:
            raise RuntimeError(
                "MODEL_STRUCTURED_OUTPUT must be auto, json_schema, or off"
            )
        self.json_schema_roles = _structured_output_roles(
            mode=structured_mode,
            base_url=base_url,
            models=self.models,
        )
        self.max_tokens = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.diagnostic_dir = Path(diagnostic_dir) if diagnostic_dir else None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    async def _complete_text(
        self, *, role: str, system_prompt: str, user_prompt: str, temperature: float,
        output_schema: type[BaseModel],
    ) -> str:
        request: dict[str, Any] = {
            "model": self.models[role],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if role in self.json_schema_roles:
            schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", output_schema.__name__)
            request.update(
                {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "schema": output_schema.model_json_schema(),
                        },
                    },
                }
            )
        result = await self.client.chat.completions.create(**request)
        return result.choices[0].message.content or ""

    async def complete_structured(
        self, *, role: str, system_prompt: str, input_payload: dict[str, Any],
        output_schema: type[BaseModel], temperature: float
    ) -> BaseModel:
        payload = dict(input_payload)
        payload["output_schema"] = output_schema.model_json_schema()
        error = ""
        text = ""
        for attempt in range(2):
            if error:
                payload["repair_instruction"] = (
                    "上次输出未通过 JSON 解析或 schema 校验。请根据错误修复上次输出，"
                    "只返回一个符合 output_schema 的 JSON 对象，不要添加 Markdown 或解释。"
                )
                payload["validation_error"] = error
                payload["invalid_previous_output"] = text[-12000:]
            text = await self._complete_text(
                role=role,
                system_prompt=system_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                temperature=temperature,
                output_schema=output_schema,
            )
            try:
                return output_schema.model_validate(json.loads(_strip_fence(text)))
            except Exception as exc:
                error = str(exc)
                self._write_invalid_output(
                    role=role,
                    output_schema=output_schema,
                    attempt=attempt + 1,
                    error=error,
                    text=text,
                )
        raise ValueError(
            f"{self.provider_name}/{role} failed {output_schema.__name__}: {error}"
        )

    def _write_invalid_output(
        self, *, role: str, output_schema: type[BaseModel], attempt: int,
        error: str, text: str,
    ) -> None:
        if self.diagnostic_dir is None:
            return
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        path = self.diagnostic_dir / (
            f"{timestamp}-{role}-{output_schema.__name__}-"
            f"attempt-{attempt}-{uuid.uuid4().hex[:8]}.json"
        )
        path.write_text(
            json.dumps(
                {
                    "role": role,
                    "output_schema": output_schema.__name__,
                    "attempt": attempt,
                    "error": error,
                    "raw_response": text,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
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
    provider: str, *, local_model_name: str = "", local_device: str = "auto",
    diagnostic_dir: Path | None = None,
) -> ModelGateway:
    if provider == "mock":
        return MockGateway()
    if provider == "api":
        return OpenAICompatibleGateway(diagnostic_dir=diagnostic_dir)
    if provider == "local":
        return LocalTransformersGateway(local_model_name, local_device)
    raise ValueError(f"Unsupported model provider: {provider}")


def _structured_output_roles(
    *, mode: str, base_url: str | None, models: dict[str, str],
) -> set[str]:
    if mode == "off":
        return set()
    if mode == "json_schema":
        return set(models)
    if not base_url or "chat.ecnu.edu.cn" not in base_url.lower():
        return set()
    return {
        role
        for role, model in models.items()
        if model.strip().lower() in ECNU_JSON_SCHEMA_MODELS
    }


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines)
    return value


def _mock_scale_items() -> ScaleItems:
    return ScaleItems(
        items=[ScaleItem(item=str(index), score=4.0) for index in range(1, 16)]
    )


def _mock_extracted_client_info(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mock for E.7. Only fabricates session-one intake fields."""
    dialogue = str(payload.get("current_session_dialogue", ""))
    session_number = int(payload.get("current_session_number", 1))
    return {
        "static_traits": StaticTraits().model_dump(mode="json"),
        "main_problem": "在对话中表达当前困扰" if session_number == 1 else "",
        "topic": "",
        "core_demands": "希望得到理解并找到改善方向" if session_number == 1 else "",
        "growth_experiences": [],
        "theory": {},
        "source_session": session_number,
    }


def _mock_merged_client_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic E.8 mock: prefer history fields if present, else current."""
    history = payload.get("history_profile", {})
    current = payload.get("current_profile", {})
    merged = {
        "client_id": str(payload.get("client_id", "")),
        "static_traits": StaticTraits().model_dump(mode="json"),
        "main_problem": str(history.get("main_problem") or current.get("main_problem", "")),
        "topic": str(history.get("topic") or current.get("topic", "")),
        "core_demands": str(
            history.get("core_demands") or current.get("core_demands", "")
        ),
        "growth_experiences": list(history.get("growth_experiences", []))
        + [
            item
            for item in current.get("growth_experiences", [])
            if item not in history.get("growth_experiences", [])
        ],
        "theory": {**history.get("theory", {}), **current.get("theory", {})},
        "updated_session": int(payload.get("session_number", 1)),
    }
    global_profile = payload.get("global_profile", {})
    if not merged["client_id"]:
        merged["client_id"] = str(global_profile.get("client_id", ""))
    traits_raw = global_profile.get("static_traits", {}) or {}
    merged["static_traits"] = {
        key: history.get("static_traits", {}).get(key)
        or current.get("static_traits", {}).get(key)
        or ""
        for key in StaticTraits.model_fields
    }
    return merged


def _mock_clinical_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic E.9 mock grounded in the session index and objectives."""
    session_index = int(payload.get("session_index", 1))
    session_focus = payload.get("session_focus", {})
    objectives = "; ".join(session_focus.get("objective", []))
    return {
        "session_index": session_index,
        "session_summary_abstract": f"第{session_index}次会谈完成对话，聚焦于目标与感受。",
        "goal_assessment": {
            "objective_recap": objectives,
            "completion_status": "部分达成 (Partially Completed)",
            "evidence_and_analysis": "mock 模式未引用真实对话证据。",
        },
        "client_state_analysis": {
            "affective_state": "存在一定困扰，但能参与对话。",
            "behavioral_patterns": "愿意表达，合作度可。",
            "therapeutic_alliance": "初步建立合作。",
            "unresolved_points_or_tensions": "",
            "cognitive_patterns": "",
            "subconscious_manifestation": "",
            "personal_agency": "",
            "existentialism_topic": "",
            "target_behavior": "",
        },
        "homework": [],
    }


def _mock_counselor_response(
    intervention: str,
    client: str,
    stage: str,
    turn: int = 0,
) -> str:
    # Natural, colloquial Chinese - like a real counselor speaking
    if stage == "consolidation":
        return "今天我们聊了不少。如果只选一件事这周试试，你会选什么？"
    templates = {
        "empathic_reflection": "嗯，听起来你扛了很久，挺不容易的。能说说最近哪一刻最难受吗？",
        "open_question": "谢谢你愿意说这些。你觉得我们先从哪聊起比较好？",
        "clarification": "当时具体是什么样的？你脑子里最先跳出来的想法是什么？",
        "socratic_question": "你觉得支持这个想法的有哪些事情？有没有哪怕一次不太一样的？",
        "behavioral_suggestion": "不用一下解决全部。你能不能想一件十分钟就能做的小事，先试试？",
        "emotion_reflection": "好像你一边撑着，一边又越来越不确定这是不是自己想要的。",
        "experiential_clarification": "说到这的时候，你现在的感觉是什么？身体上或者情绪上。",
        "meaning_exploration": "在别人对你的期待和你自己的感受之间，哪部分最让你纠结？",
        "choice_support": "如果不急着找对的答案，你觉得哪条路更像你愿意走下去的？",
        "session_summary": "今天我们聊到一个挺重要的地方。你觉得我理解的对不对？有没有漏掉的？",
    }
    if intervention in templates:
        return templates[intervention]
    fallback_responses = [
        "我们慢一点没关系。刚才说的这些，你希望我先接着哪部分？",
        "先停一下——你是想继续聊刚才的事，还是换个方向？",
        "嗯，我感觉我们可能需要换个角度。你觉得现在什么样的回应对你有用？",
    ]
    return fallback_responses[turn % len(fallback_responses)]
