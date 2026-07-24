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


COUNSELOR_SYSTEM = """你是研究沙盒中的 CBT 咨询师智能体，并非真实医疗服务。
只能使用 unlocked_profile、session_memory、当前对话和候选技能中的信息；
不得猜测或暗示未披露档案，不得诊断、提供药物剂量或承诺疗效。
高风险时停止普通 CBT。输出严格 JSON，只给简短、可审计的结构化判断。"""


class CounselorAgent:
    def __init__(self, gateway: ModelGateway, temperature: float = 0.4):
        self.gateway = gateway
        self.temperature = temperature

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
        return {
            "therapy": plan.therapy,
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
            system_prompt=COUNSELOR_SYSTEM,
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
