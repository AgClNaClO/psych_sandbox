from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from psychsandbox.domain import (
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
    ScaleItem,
    ScaleItems,
    StaticTraits,
    TrustChange,
)
from psychsandbox.model_client import ModelGateway


class DeterministicGateway(ModelGateway):
    """Offline test double for component tests; never selectable at runtime."""

    provider_name = "deterministic_test"

    async def complete_structured(
        self,
        *,
        role: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: type[BaseModel],
        temperature: float,
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
                response=_counselor_response(
                    selected[0].get("intervention_type", "") if selected else "",
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
                    reaction=(
                        ClientReactionType.SCARED
                        if pushed
                        else ClientReactionType.CHALLENGED
                    ),
                    intensity=(
                        ReactionIntensity.HIGH if pushed else ReactionIntensity.LOW
                    ),
                    behavior=(
                        ClientBehaviorType.RESISTANCE
                        if pushed
                        else ClientBehaviorType.REQUEST
                    ),
                    resistance_pattern=(
                        ResistancePatternType.DEFENSIVENESS if pushed else None
                    ),
                    blocked_fact_ids=[item["fact_id"] for item in blocked],
                    trust_change=(
                        TrustChange.SIGNIFICANT_DECREASE
                        if pushed
                        else TrustChange.UNCHANGED
                    ),
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
                reaction=(
                    ClientReactionType.UNDERSTOOD
                    if respected
                    else ClientReactionType.NO_REACTION
                ),
                intensity=(
                    ReactionIntensity.MODERATE
                    if respected
                    else ReactionIntensity.LOW
                ),
                behavior=behavior,
                retrieved_fact_ids=[item["fact_id"] for item in retrieved],
                trust_change=(
                    TrustChange.SLIGHT_INCREASE
                    if respected
                    else TrustChange.UNCHANGED
                ),
                rationale="根据当前联盟和可用内容选择回应方式。",
            )
        if output_schema is ScaleItems:
            return ScaleItems(
                items=[ScaleItem(item=str(index), score=4.0) for index in range(1, 16)]
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
                    responses = [
                        "我现在还没准备好谈这部分，我们能先换个话题吗？",
                        "我已经说过暂时不想谈这个。请先停一下。",
                    ]
                    return ClientUtterance(utterance=responses[min(turn, 1)])
                responses = {
                    ResistancePatternType.MINIMAL_TALK.value: "我现在只想简单说一点，不想展开。",
                    ResistancePatternType.IRRELEVANT_TALK.value: "我们能先聊点别的吗？",
                    ResistancePatternType.SUPERFICIAL.value: "大概就是这样，我还不想说得更深。",
                    ResistancePatternType.INTELLECTUALIZING.value: "我更想先从道理上把这件事分析清楚。",
                    ResistancePatternType.HOSTILITY.value: "这个追问让我不舒服，请先停一下。",
                    ResistancePatternType.COMPLIANCE_WITHOUT_ENGAGEMENT.value: "我可以回答，但感觉自己还没有真正准备好。",
                }
                return ClientUtterance(
                    utterance=responses.get(
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
                {"client_info_get": _extracted_client_info(input_payload)}
            )
        if schema_name == "_ClientInfoMerge":
            return output_schema.model_validate(
                {"client_info_merge": _merged_client_profile(input_payload)}
            )
        if schema_name == "_SessionSummaryWrapper":
            return output_schema.model_validate(
                {"session_summary": _clinical_summary(input_payload)}
            )
        raise ValueError(
            f"DeterministicGateway does not support {output_schema.__name__}"
        )


def _extracted_client_info(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "static_traits": StaticTraits().model_dump(mode="json"),
        "main_problem": "",
        "topic": "",
        "core_demands": "",
        "growth_experiences": [],
        "theory": {},
        "source_session": int(payload.get("current_session_number", 1)),
    }


def _merged_client_profile(payload: dict[str, Any]) -> dict[str, Any]:
    history = payload.get("history_profile", {})
    current = payload.get("current_profile", {})
    global_profile = payload.get("global_profile", {})
    merged = {
        "client_id": global_profile.get("client_id", ""),
        "main_problem": history.get("main_problem")
        or current.get("main_problem")
        or global_profile.get("main_problem", ""),
        "topic": history.get("topic")
        or current.get("topic")
        or global_profile.get("topic", ""),
        "core_demands": history.get("core_demands")
        or current.get("core_demands")
        or global_profile.get("core_demands", ""),
        "growth_experiences": list(
            dict.fromkeys(
                (history.get("growth_experiences", []) or [])
                + (current.get("growth_experiences", []) or [])
            )
        ),
        "theory": history.get("theory") or current.get("theory") or {},
        "updated_session": int(payload.get("session_number", 1)),
    }
    merged["static_traits"] = {
        key: history.get("static_traits", {}).get(key)
        or current.get("static_traits", {}).get(key)
        or ""
        for key in StaticTraits.model_fields
    }
    return merged


def _clinical_summary(payload: dict[str, Any]) -> dict[str, Any]:
    session_index = int(payload.get("session_index", 1))
    session_focus = payload.get("session_focus", {})
    objectives = "; ".join(session_focus.get("objective", []))
    return {
        "session_index": session_index,
        "session_summary_abstract": f"第{session_index}次会谈完成对话，聚焦于目标与感受。",
        "goal_assessment": {
            "objective_recap": objectives,
            "completion_status": "部分达成 (Partially Completed)",
            "evidence_and_analysis": "测试网关未引用真实对话证据。",
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


def _counselor_response(intervention: str, stage: str, turn: int = 0) -> str:
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
    responses = [
        "我们慢一点没关系。刚才说的这些，你希望我先接着哪部分？",
        "先停一下——你是想继续聊刚才的事，还是换个方向？",
        "嗯，我感觉我们可能需要换个角度。你觉得现在什么样的回应对你有用？",
    ]
    return responses[turn % len(responses)]
