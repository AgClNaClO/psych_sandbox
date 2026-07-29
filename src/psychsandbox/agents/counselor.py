from __future__ import annotations

from ..domain import (
    CounselorDecision,
    CounselorTurn,
    RiskAssessment,
    RiskLevel,
    SessionMemory,
    SessionPlan,
    SkillCandidate,
)
from ..model_client import ModelGateway
from ..runtime.dialogue_guard import DialogueLoopGuard
from ..therapies import get_therapy_profile


class CounselorAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        temperature: float = 0.4,
        dialogue_guard: DialogueLoopGuard | None = None,
    ):
        self.gateway = gateway
        self.temperature = temperature
        self.dialogue_guard = dialogue_guard or DialogueLoopGuard()

    def build_payload(
        self,
        *,
        memory: SessionMemory,
        plan: SessionPlan,
        client_message: str,
        recent_messages: list[dict],
        candidates: SkillCandidate,
        risk: RiskAssessment,
        counselor_turn_count: int,
    ) -> dict:
        """Build the strict counselor view; a full ClientProfile never enters it."""
        therapy_profile = get_therapy_profile(plan.therapy)
        return {
            "therapy": plan.therapy,
            "therapy_name": therapy_profile.display_name,
            "conceptualization_focus": therapy_profile.conceptualization_focus,
            "stage_goals": list(therapy_profile.stage_goals[plan.stage]),
            "session_stage": plan.stage.value,
            "session_index": plan.session_index,
            "objectives": plan.objectives,
            "forbidden_actions": plan.forbidden_actions,
            "unlocked_profile": memory.unlocked_profile.model_dump(mode="json"),
            "session_memory": {
                "summaries": memory.summaries[-3:],
                "confirmed_goals": memory.confirmed_goals,
                "unresolved_topics": memory.unresolved_topics,
                "homework": memory.homework,
                "risk_history": memory.risk_history,
                "supervisor_feedback": memory.supervisor_feedback[-2:],
            },
            "client_message": client_message,
            "recent_messages": recent_messages[-8:],
            "candidate_meta_skills": [
                item.model_dump(mode="json") for item in candidates.meta_skills
            ],
            "candidate_atomic_skills": [
                item.model_dump(mode="json") for item in candidates.atomic_skills
            ],
            "risk_level": risk.level.value,
            "counselor_turn_count": counselor_turn_count,
        }

    async def respond(
        self,
        *,
        memory: SessionMemory,
        plan: SessionPlan,
        client_message: str,
        recent_messages: list[dict],
        candidates: SkillCandidate,
        risk: RiskAssessment,
        counselor_turn_count: int,
    ) -> CounselorTurn:
        if risk.level is RiskLevel.MEDIUM:
            return CounselorTurn(
                decision=CounselorDecision(
                    assessment="检测到含糊的绝望表达，需要先澄清安全。",
                    state_observation="当前风险信息不足，先确认是否存在想法、计划或手段。",
                    strategy="直接但平静地确认安全，再决定是否恢复普通 CBT。",
                    risk_level=risk.level,
                ),
                response=(
                    "你说“撑不下去”让我很在意。在继续谈压力之前，我想直接确认："
                    "你现在有没有伤害自己或他人的想法、具体计划或可用手段？"
                ),
            )
        if risk.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}:
            return CounselorTurn(
                decision=CounselorDecision(
                    assessment="检测到高风险表达，暂停普通咨询流程。",
                    state_observation="优先确认即时安全并连接现实支持。",
                    strategy="安全确认、减少可用伤害手段、联系现实支持。",
                    risk_level=risk.level,
                    end_session=risk.level is RiskLevel.IMMINENT,
                ),
                response=_crisis_response(risk.level),
            )
        boundary = self.dialogue_guard.inspect(client_message, recent_messages)
        if boundary.detected:
            return CounselorTurn(
                decision=CounselorDecision(
                    assessment="来访者明确表达了暂停或更换话题的边界。",
                    state_observation=(
                        "边界已重复出现，需要停止原方向并修复互动。"
                        if boundary.repeated
                        else "当前应优先确认自主性和安全感。"
                    ),
                    strategy="确认边界、不追问原因、提供低压力选择并让来访者决定方向。",
                    risk_level=risk.level,
                ),
                response=self.dialogue_guard.counselor_response(boundary),
            )
        payload = self.build_payload(
            memory=memory,
            plan=plan,
            client_message=client_message,
            recent_messages=recent_messages,
            candidates=candidates,
            risk=risk,
            counselor_turn_count=counselor_turn_count,
        )
        result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=get_therapy_profile(plan.therapy).system_prompt(),
            input_payload=payload,
            output_schema=CounselorTurn,
            temperature=self.temperature,
        )
        turn = CounselorTurn.model_validate(result)
        allowed_atomic = {item.skill_id for item in candidates.atomic_skills}
        allowed_meta = {item.meta_skill_id for item in candidates.meta_skills}
        turn.decision.selected_atomic_skill_ids = [
            item for item in turn.decision.selected_atomic_skill_ids
            if item in allowed_atomic
        ]
        turn.decision.selected_meta_skill_ids = [
            item for item in turn.decision.selected_meta_skill_ids
            if item in allowed_meta
        ]
        turn.decision.risk_level = risk.level
        if self.dialogue_guard.is_repeated_counselor_response(
            turn.response,
            recent_messages,
        ):
            turn.decision.strategy = (
                f"{turn.decision.strategy} 检测到回复重复，暂停原追问并重新校准方向。"
            )
            turn.response = self.dialogue_guard.repetition_repair_response()
        return turn


def _crisis_response(level: RiskLevel) -> str:
    if level is RiskLevel.IMMINENT:
        return (
            "我很重视你刚才说的情况。我们先停止普通咨询练习：请立即联系当地紧急服务，"
            "并让一位可信任的人现在陪在你身边；如果可以，把可能伤害自己的物品移远。"
            "你是否已经采取了行动，或者身边是否有人可以马上帮助你？"
        )
    return (
        "听起来你现在承受着很强的痛苦。继续之前我想先确认安全："
        "你此刻有没有具体伤害自己或他人的计划、时间或可用手段？"
        "请尽量联系一位可信任的人陪伴你。"
    )
