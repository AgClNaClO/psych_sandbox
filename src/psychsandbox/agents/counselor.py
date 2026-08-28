from __future__ import annotations

import json

from ..domain import (
    CounselorAction,
    CounselorActorOutput,
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
    SkillQueryAttempt,
    SkillSelectionConfig,
    SkillSelectionEvidence,
)
from ..model_client import ModelGateway
from ..prompts import render_prompt
from ..runtime.dialogue_guard import DialogueLoopGuard
from ..skills import SkillCatalog, SkillRegistry
from ..skills.selection import SkillCandidateFilter
from ..therapies import get_therapy_profile

# Generation prompts are Jinja2 templates under ``prompts/counselor/``.
COUNSELOR_PLANNER_TEMPLATE = "counselor/planner_system.jinja2"
COUNSELOR_ACTOR_TEMPLATE = "counselor/actor_system.jinja2"
COUNSELOR_REVIEW_TEMPLATE = "counselor/review_system.jinja2"


class CounselorAgent:
    """API-driven planner/actor with an internal skill-catalog seam."""

    def __init__(
        self,
        gateway: ModelGateway,
        skill_catalog: SkillCatalog | None = None,
        temperature: float = 0.4,
        dialogue_guard: DialogueLoopGuard | None = None,
        skill_selection: SkillSelectionConfig | None = None,
    ) -> None:
        self.gateway = gateway
        self.skill_catalog = skill_catalog or SkillCatalog(SkillRegistry())
        self.temperature = temperature
        self.dialogue_guard = dialogue_guard or DialogueLoopGuard()
        self.candidate_filter = SkillCandidateFilter(
            gateway, skill_selection or SkillSelectionConfig()
        )

    def reset_run_state(self) -> None:
        self.candidate_filter.reset()

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
        planning, observation, candidates, warnings = await self._query_skills(
            context=context, plan=plan, risk=risk, excluded_meta_ids=set()
        )
        attempts = []
        if observation.status == "invalid_selection" and planning.action is CounselorAction.LOOKUP_SKILLS:
            attempts.append(self._query_attempt(
                1, planning, candidates, observation, "invalid", observation.note, warnings
            ))
            planning, observation, candidates, warnings = await self._query_skills(
                context=context,
                plan=plan,
                risk=risk,
                excluded_meta_ids=set(planning.selected_meta_skill_ids),
                previous_rejection=attempts[0].rejection_reason,
            )

        actor_output, actor_warnings = await self._act(
            context=context, plan=plan, planning=planning, observation=observation,
            retry_available=not attempts,
        )
        warnings.extend(actor_warnings)
        if (
            actor_output.query_assessment == "unsuitable"
            and planning.action is CounselorAction.LOOKUP_SKILLS
            and observation.status == "skills_found"
            and not attempts
        ):
            attempts.append(self._query_attempt(
                1, planning, candidates, observation, "unsuitable",
                actor_output.query_rejection_reason, warnings,
            ))
            planning, observation, candidates, warnings = await self._query_skills(
                context=context,
                plan=plan,
                risk=risk,
                excluded_meta_ids=set(planning.selected_meta_skill_ids),
                previous_rejection=actor_output.query_rejection_reason,
            )
            actor_output, actor_warnings = await self._act(
                context=context, plan=plan, planning=planning,
                observation=observation, retry_available=False,
            )
            warnings.extend(actor_warnings)

        assessment = (
            actor_output.query_assessment
            if planning.action is CounselorAction.LOOKUP_SKILLS
            else "not_needed"
        )
        rejection_reason = actor_output.query_rejection_reason
        if observation.status == "invalid_selection":
            assessment = "invalid"
            rejection_reason = observation.note
        attempts.append(self._query_attempt(
            len(attempts) + 1, planning, candidates, observation,
            assessment, rejection_reason, warnings,
            selected_atomic_ids=actor_output.decision.selected_atomic_skill_ids,
        ))
        turn = CounselorTurn(
            decision=actor_output.decision,
            response=actor_output.response,
            planning=planning,
            observation=observation,
            skill_queries=attempts,
        )
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

    async def _query_skills(
        self,
        *,
        context: dict,
        plan: SessionPlan,
        risk: RiskAssessment,
        excluded_meta_ids: set[str],
        previous_rejection: str = "",
    ) -> tuple[CounselorPlanning, CounselorObservation, list[str], list[str]]:
        meta_catalog = [
            item for item in self.skill_catalog.available_meta(plan=plan, risk=risk)
            if item.meta_skill_id not in excluded_meta_ids
        ]
        planning_payload = {
            **context,
            "meta_skill_catalog": [
                item.model_dump(mode="json") for item in meta_catalog
            ],
            "previous_query_rejection": previous_rejection,
        }
        planning_result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(
                plan, render_prompt(COUNSELOR_PLANNER_TEMPLATE, **planning_payload)
            ),
            input_payload=planning_payload,
            output_schema=CounselorPlanning,
            temperature=self.temperature,
        )
        planning = CounselorPlanning.model_validate(planning_result)
        allowed_meta_ids = {item.meta_skill_id for item in meta_catalog}
        requested = list(dict.fromkeys(planning.selected_meta_skill_ids))
        selected = list(
            dict.fromkeys(
                item
                for item in planning.selected_meta_skill_ids
                if item in allowed_meta_ids
            )
        )
        selected, planning.selection_evidence, warnings = self._grounded_selection(
            selected, planning.selection_evidence, context
        )
        planning.selected_meta_skill_ids = selected
        if planning.action is not CounselorAction.LOOKUP_SKILLS:
            planning.selected_meta_skill_ids = []
            planning.selection_evidence = []
        observation = self.skill_catalog.observe(
            plan=plan,
            risk=risk,
            action=planning.action,
            selected_meta_skill_ids=planning.selected_meta_skill_ids,
        )
        if warnings and observation.status == "invalid_selection":
            observation.note = "；".join(warnings)
        candidate_ids = [item.skill_id for item in observation.atomic_skills]
        observation = await self.candidate_filter.narrow(
            observation,
            query=self._vector_query(context, planning),
            stage=plan.stage.value,
        )
        invalid_ids = [item for item in requested if item not in allowed_meta_ids]
        warnings.extend(f"元技能ID不在当前可用目录：{item}" for item in invalid_ids)
        return planning, observation, candidate_ids, warnings

    async def _act(
        self, *, context: dict, plan: SessionPlan, planning: CounselorPlanning,
        observation: CounselorObservation, retry_available: bool,
    ) -> tuple[CounselorActorOutput, list[str]]:
        actor_payload = {
            **context,
            "planning": planning.model_dump(mode="json"),
            "observation": observation.model_dump(mode="json"),
            "query_retry_available": retry_available,
        }
        result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(
                plan, render_prompt(COUNSELOR_ACTOR_TEMPLATE, **actor_payload)
            ),
            input_payload=actor_payload,
            output_schema=CounselorActorOutput,
            temperature=self.temperature,
        )
        actor_output = CounselorActorOutput.model_validate(result)
        if actor_output.query_assessment != "suitable":
            actor_output.decision.selected_atomic_skill_ids = []
            actor_output.decision.selected_meta_skill_ids = []
            actor_output.decision.skill_evidence = []
        warnings = self._constrain_selected_skills(
            actor_output.decision, observation, context
        )
        return actor_output, warnings

    @classmethod
    def _grounded_selection(
        cls, selected: list[str], evidence: list[SkillSelectionEvidence], context: dict,
    ) -> tuple[list[str], list[SkillSelectionEvidence], list[str]]:
        sources = cls._evidence_sources(context)
        by_id = {item.skill_id: item for item in evidence}
        grounded = []
        warnings = []
        for skill_id in selected:
            item = by_id.get(skill_id)
            if item and cls._quote_is_grounded(item.evidence_quote, sources):
                grounded.append(skill_id)
            else:
                warnings.append(f"元技能{skill_id}缺少来自公开上下文的适用依据")
        return grounded, [by_id[item] for item in grounded], warnings

    @classmethod
    def _evidence_sources(cls, context: dict) -> list[str]:
        values = [context.get("client_message", "")]
        values.extend(
            message.get("content", "") for message in context.get("recent_messages", [])
            if message.get("role") == "client"
        )
        profile = context.get("unlocked_profile", {})
        for key in ("public_background", "confirmed_goals", "expressed_problems", "theory"):
            values.extend(cls._strings(profile.get(key, {})))
        values.extend(fact.get("content", "") for fact in profile.get("facts", []))
        memory = context.get("session_memory", {})
        for key in ("summaries", "confirmed_goals", "unresolved_topics", "supervisor_feedback"):
            values.extend(cls._strings(memory.get(key, [])))
        return [cls._normalize_text(item) for item in values if str(item).strip()]

    @classmethod
    def _strings(cls, value) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [item for child in value.values() for item in cls._strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in cls._strings(child)]
        return []

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value).split()).casefold()

    @classmethod
    def _quote_is_grounded(cls, quote: str, sources: list[str]) -> bool:
        normalized = cls._normalize_text(quote)
        return bool(normalized and any(normalized in source for source in sources))

    @staticmethod
    def _vector_query(context: dict, planning: CounselorPlanning) -> str:
        memory = context.get("session_memory", {})
        payload = {
            "current_client_message": str(context.get("client_message", ""))[:2000],
            "current_goal": planning.current_goal[:300],
            "selection_evidence": [item.evidence_quote for item in planning.selection_evidence],
            "session_objectives": [str(item)[:160] for item in context.get("objectives", [])[:4]],
            "recent_client_messages": [
                str(item.get("content", ""))[:500]
                for item in context.get("recent_messages", [])[-6:]
                if item.get("role") == "client"
            ],
            "recent_summary": [str(item)[:500] for item in memory.get("summaries", [])[-1:]],
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _query_attempt(
        attempt: int, planning: CounselorPlanning, candidates: list[str],
        observation: CounselorObservation, assessment: str, rejection_reason: str,
        warnings: list[str], selected_atomic_ids: list[str] | None = None,
    ) -> SkillQueryAttempt:
        return SkillQueryAttempt(
            attempt=attempt,
            planning=planning,
            candidate_skill_ids=candidates,
            returned_skill_ids=[item.skill_id for item in observation.atomic_skills],
            selected_atomic_skill_ids=selected_atomic_ids or [],
            assessment=assessment,
            rejection_reason=rejection_reason,
            selection_warnings=list(dict.fromkeys(warnings)),
            vector_filtered=observation.vector_filtered,
            embedding_model=observation.embedding_model,
            similarity_scores=observation.similarity_scores,
        )

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
        review_payload = {
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
        }
        result = await self.gateway.complete_structured(
            role="counselor",
            system_prompt=self._system_prompt(
                session.plan,
                render_prompt(COUNSELOR_REVIEW_TEMPLATE, **review_payload),
            ),
            input_payload=review_payload,
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
        decision: CounselorDecision,
        observation: CounselorObservation,
        context: dict,
    ) -> list[str]:
        allowed_atomic = {item.skill_id for item in observation.atomic_skills}
        parents = {item.skill_id: item.meta_skill_id for item in observation.atomic_skills}
        sources = CounselorAgent._evidence_sources(context)
        by_id = {item.skill_id: item for item in decision.skill_evidence}
        warnings = []
        selected_atomic = []
        for skill_id in dict.fromkeys(decision.selected_atomic_skill_ids):
            evidence = by_id.get(skill_id)
            if skill_id not in allowed_atomic:
                warnings.append(f"原子技能ID不在Observation：{skill_id}")
            elif not evidence or not CounselorAgent._quote_is_grounded(evidence.evidence_quote, sources):
                warnings.append(f"原子技能{skill_id}缺少来自公开上下文的适用依据")
            else:
                selected_atomic.append(skill_id)
        decision.selected_atomic_skill_ids = selected_atomic
        decision.skill_evidence = [by_id[item] for item in selected_atomic]
        decision.selected_meta_skill_ids = list(dict.fromkeys(parents[item] for item in selected_atomic))
        return warnings

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
