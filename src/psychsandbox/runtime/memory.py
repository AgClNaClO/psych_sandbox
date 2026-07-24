from __future__ import annotations

from ..domain import SessionMemory, SessionPlan, SessionRecord, SessionStage


class MemoryConsolidator:
    def consolidate(
        self,
        memory: SessionMemory,
        session: SessionRecord,
        *,
        next_index: int,
    ) -> SessionMemory:
        feedback = (
            session.supervisor_report.feedback if session.supervisor_report else []
        )
        return memory.model_copy(
            update={
                "completed_sessions": session.session_index,
                "summaries": memory.summaries + [session.summary],
                "interventions_used": list(
                    dict.fromkeys(memory.interventions_used + session.interventions_used)
                ),
                "risk_history": memory.risk_history
                + [event.level.value for event in session.risk_events if event.level.value != "low"],
                "supervisor_feedback": memory.supervisor_feedback + feedback,
            }
        )

    @staticmethod
    def next_plan(current: SessionPlan, next_index: int) -> SessionPlan:
        stage = (
            SessionStage.INTERVENTION
            if current.stage is SessionStage.CONCEPTUALIZATION
            else SessionStage.CONSOLIDATION
            if next_index >= 3
            else current.stage
        )
        return SessionPlan(
            session_index=next_index,
            therapy=current.therapy,
            stage=stage,
            objectives=["复盘上次会谈", "推进尚未完成的共同目标", "形成可验证的下一步"],
            target_meta_skill_ids=current.target_meta_skill_ids,
            target_atomic_skill_ids=current.target_atomic_skill_ids,
            forbidden_actions=current.forbidden_actions,
        )
