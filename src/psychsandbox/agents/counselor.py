from __future__ import annotations

from ..domain import (
    CounselorAction,
    CounselorDecision,
    CounselorObservation,
    CounselorPlanning,
    CounselorSessionReview,
    CounselorTurn,
    RiskAssessment,
    RiskLevel,
    SessionMemory,
    SessionPlan,
    SessionRecord,
)
from ..model_client import ModelGateway
from ..prompts import load_prompt
from ..runtime.dialogue_guard import DialogueLoopGuard
from ..skills import SkillCatalog, SkillRegistry
from ..therapies import get_therapy_profile

# Generation prompts are file-driven assets under ``prompts/counselor/``.
COUNSELOR_PLANNER_SYSTEM = load_prompt("counselor/planner_system.txt").strip()
COUNSELOR_ACTOR_SYSTEM = load_prompt("counselor/actor_system.txt").strip()
COUNSELOR_REVIEW_SYSTEM = load_prompt("counselor/review_system.txt").strip()


class CounselorAgent:
    """API-driven planner/actor with an internal skill-catalog seam."""

    def __init__(
        self,
        gateway: ModelGateway,
        skill_catalog: SkillCatalog | None = None,
        temperature: float = 0.4,
        dialogue_guard: DialogueLoopGuard | None = None,
    ) -> None:
        self.gateway = gateway
        self.skill_catalog = skill_catalog or SkillCatalog(SkillRegistry())
        self.temperature = temperature
        self.dialogue_guard = dialogue_guard or DialogueLoopGuard()

    def build_context_payload(
        self,
        *,
        memory: SessionMemory,
        plan: SessionPlan,
        client_message: str,
        recent_messages: list[dict],
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
            "strategy_from_previous_review": plan.strategy,
            "target_meta_skill_ids": plan.target_meta_skill_ids,
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
        risk: RiskAssessment,
        counselor_turn_count: int,
    ) -> CounselorTurn:
        guarded = self._guarded_turn(
            client_message=client_message,
            recent_messages=recent_messages,
            risk=risk,
        )
        if guarded is not None:
            return guarded

        context = self.build_context_payload(
            memory=memory,
            plan=plan,
            client_message=client_message,
            recent_messages=recent_messages,
            risk=risk,
            counselor_turn_count=counselor_turn_count,
        )
        meta_catalog = self.skill_catalog.available_meta(plan=plan, risk=risk)
        planning_result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(plan, COUNSELOR_PLANNER_SYSTEM),
            input_payload={
                **context,
                "meta_skill_catalog": [
                    item.model_dump(mode="json") for item in meta_catalog
                ],
            },
            output_schema=CounselorPlanning,
            temperature=self.temperature,
        )
        planning = CounselorPlanning.model_validate(planning_result)
        allowed_meta_ids = {item.meta_skill_id for item in meta_catalog}
        planning.selected_meta_skill_ids = list(
            dict.fromkeys(
                item
                for item in planning.selected_meta_skill_ids
                if item in allowed_meta_ids
            )
        )
        observation = self.skill_catalog.observe(
            plan=plan,
            risk=risk,
            action=planning.action,
            selected_meta_skill_ids=planning.selected_meta_skill_ids,
        )

        result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(plan, COUNSELOR_ACTOR_SYSTEM),
            input_payload={
                **context,
                "planning": planning.model_dump(mode="json"),
                "observation": observation.model_dump(mode="json"),
            },
            output_schema=CounselorTurn,
            temperature=self.temperature,
        )
        turn = CounselorTurn.model_validate(result)
        turn.planning = planning
        turn.observation = observation
        self._constrain_selected_skills(turn, observation)
        turn.decision.risk_level = risk.level
        if planning.action is CounselorAction.END_SESSION:
            turn.decision.end_session = True
        if self.dialogue_guard.is_repeated_counselor_response(
            turn.response,
            recent_messages,
        ):
            turn.decision.strategy = (
                f"{turn.decision.strategy} 检测到回复重复，暂停原追问并重新校准方向。"
            )
            turn.response = self.dialogue_guard.repetition_repair_response()
        return turn

    async def review_session(
        self,
        *,
        session: SessionRecord,
        memory: SessionMemory,
        baseline_next: SessionPlan,
    ) -> CounselorSessionReview:
        low_risk = RiskAssessment(level=RiskLevel.LOW)
        next_meta = self.skill_catalog.available_meta(
            plan=baseline_next,
            risk=low_risk,
        )
        result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(
                session.plan,
                COUNSELOR_REVIEW_SYSTEM,
            ),
            input_payload={
                "session_plan": session.plan.model_dump(mode="json"),
                "session_summary": session.summary,
                "dialogue": [item.model_dump(mode="json") for item in session.messages],
                "counselor_decisions": [
                    item.model_dump(mode="json") for item in session.decisions
                ],
                "allowed_memory": {
                    "summaries": memory.summaries[-3:],
                    "confirmed_goals": memory.confirmed_goals,
                    "unresolved_topics": memory.unresolved_topics,
                },
                "baseline_next_plan": baseline_next.model_dump(mode="json"),
                "next_meta_skill_catalog": [
                    item.model_dump(mode="json") for item in next_meta
                ],
            },
            output_schema=CounselorSessionReview,
            temperature=self.temperature,
        )
        review = CounselorSessionReview.model_validate(result)
        allowed_meta_ids = {item.meta_skill_id for item in next_meta}
        review.target_meta_skill_ids = list(
            dict.fromkeys(
                item
                for item in review.target_meta_skill_ids
                if item in allowed_meta_ids
            )
        )
        if not review.goals_achieved:
            review.replanning_required = True
            if not review.next_objectives:
                review.next_objectives = list(
                    review.unmet_objectives or session.plan.objectives
                )[:8]
        return review

    @staticmethod
    def _constrain_selected_skills(
        turn: CounselorTurn,
        observation: CounselorObservation,
    ) -> None:
        allowed_atomic = {item.skill_id for item in observation.atomic_skills}
        allowed_meta = set(observation.selected_meta_skill_ids)
        turn.decision.selected_atomic_skill_ids = [
            item
            for item in turn.decision.selected_atomic_skill_ids
            if item in allowed_atomic
        ]
        turn.decision.selected_meta_skill_ids = [
            item for item in turn.decision.selected_meta_skill_ids if item in allowed_meta
        ]

    @staticmethod
    def _system_prompt(plan: SessionPlan, task_prompt: str) -> str:
        return f"{get_therapy_profile(plan.therapy).system_prompt()}\n\n{task_prompt}"

    def _guarded_turn(
        self,
        *,
        client_message: str,
        recent_messages: list[dict],
        risk: RiskAssessment,
    ) -> CounselorTurn | None:
        if risk.level is RiskLevel.MEDIUM:
            return self._fixed_turn(
                risk=risk,
                assessment="检测到含糊的绝望表达，需要先澄清安全。",
                state_observation="当前风险信息不足，先确认是否存在想法、计划或手段。",
                strategy="直接但平静地确认安全，再决定是否恢复普通咨询。",
                response=(
                    "你说“撑不下去”让我很在意。在继续谈压力之前，我想直接确认："
                    "你现在有没有伤害自己或他人的想法、具体计划或可用手段？"
                ),
            )
        if risk.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}:
            return self._fixed_turn(
                risk=risk,
                assessment="检测到高风险表达，暂停普通咨询流程。",
                state_observation="优先确认即时安全并连接现实支持。",
                strategy="安全确认、减少可用伤害手段、联系现实支持。",
                response=_crisis_response(risk.level),
                end_session=risk.level is RiskLevel.IMMINENT,
            )
        boundary = self.dialogue_guard.inspect(client_message, recent_messages)
        if boundary.detected:
            return self._fixed_turn(
                risk=risk,
                assessment="来访者明确表达了暂停或更换话题的边界。",
                state_observation=(
                    "边界已重复出现，需要停止原方向并修复互动。"
                    if boundary.repeated
                    else "当前应优先确认自主性和安全感。"
                ),
                strategy="确认边界、不追问原因、提供低压力选择并让来访者决定方向。",
                response=self.dialogue_guard.counselor_response(boundary),
            )
        return None

    @staticmethod
    def _fixed_turn(
        *,
        risk: RiskAssessment,
        assessment: str,
        state_observation: str,
        strategy: str,
        response: str,
        end_session: bool = False,
    ) -> CounselorTurn:
        action = (
            CounselorAction.END_SESSION
            if end_session
            else CounselorAction.RESPOND_WITHOUT_SKILL
        )
        return CounselorTurn(
            planning=CounselorPlanning(
                reasoning_summary=assessment,
                current_goal="优先处理安全或互动边界。",
                plan_steps=[strategy],
                action=action,
            ),
            observation=CounselorObservation(
                action=action,
                status="no_skills_requested",
                note="安全与边界硬约束优先于普通技能查询。",
            ),
            decision=CounselorDecision(
                assessment=assessment,
                state_observation=state_observation,
                strategy=strategy,
                risk_level=risk.level,
                end_session=end_session,
            ),
            response=response,
        )


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
