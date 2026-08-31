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
        client_messages = [
            item.content for item in session.messages if item.role == "client"
        ]
        relationship_events = [
            (
                f"session={session.session_index},turn={record.get('turn_index')},"
                f"trust_change={record.get('client_turn_signal', {}).get('trust_change')}"
            )
            for record in session.turn_records
            if record.get("client_turn_signal", {}).get("trust_change")
            not in (None, "unchanged")
        ]
        unresolved = list(memory.unresolved_topics)
        if session.end_reason == "max_turns":
            unresolved.extend(session.plan.objectives[:1])
        return memory.model_copy(
            update={
                "completed_sessions": session.session_index,
                "summaries": memory.summaries + [session.summary],
                "clinical_summaries": memory.clinical_summaries
                + ([session.clinical_summary] if session.clinical_summary else []),
                "interventions_used": list(
                    dict.fromkeys(memory.interventions_used + session.interventions_used)
                ),
                "risk_history": memory.risk_history
                + [event.level.value for event in session.risk_events if event.level.value != "low"],
                "supervisor_feedback": memory.supervisor_feedback + feedback,
                "relationship_events": memory.relationship_events
                + relationship_events,
                "unresolved_topics": list(dict.fromkeys(unresolved)),
                "last_client_closing": client_messages[-1] if client_messages else "",
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
