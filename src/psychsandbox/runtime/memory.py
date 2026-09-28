from __future__ import annotations

from difflib import SequenceMatcher

from ..domain import (
    ChecklistRecord,
    ClientStateAnalysis,
    GoalAssessment,
    HomeworkItem,
    MemoryItemUpdate,
    OpenItem,
    RecapRisk,
    RiskLevel,
    SessionChecklist,
    SessionChecklistUpdate,
    SessionMemory,
    SessionPlan,
    SessionRecap,
    SessionRecord,
    SessionStage,
)
from .leakage import normalize_disclosure_text

_RISK_ORDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.IMMINENT)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def _normalized(value: str) -> str:
    return normalize_disclosure_text(value)


def _same_item(left: str, right: str) -> bool:
    """Match two item texts despite rewording.

    Exact normalized equality always matches; containment and fuzzy similarity
    only count for reasonably long texts so a short generic phrase cannot retire
    an unrelated item.
    """

    first, second = _normalized(left), _normalized(right)
    if not first or not second:
        return False
    if first == second:
        return True
    if min(len(first), len(second)) < 6:
        return False
    if first in second or second in first:
        return True
    return SequenceMatcher(None, first, second).ratio() >= 0.85


def _grounded(evidence: str, dialogue: str) -> bool:
    """True when ``evidence`` really occurs in the current session dialogue."""

    normalized = _normalized(evidence)
    return len(normalized) >= 2 and normalized in _normalized(dialogue)


def merge_session_checklist(
    current: SessionChecklist,
    update: SessionChecklistUpdate,
) -> SessionChecklist:
    """Apply one model-selected delta without allowing earlier entries to vanish."""

    resolved = {item.strip() for item in update.resolved_pending_items if item.strip()}
    pending = [item for item in current.pending_items if item not in resolved]
    pending.extend(update.pending_items)
    return SessionChecklist(
        completed_items=_unique(current.completed_items + update.completed_items),
        important_information=_unique(
            current.important_information + update.important_information
        ),
        important_methods=_unique(current.important_methods + update.important_methods),
        important_results=_unique(current.important_results + update.important_results),
        pending_items=_unique(pending),
    )


def _supervisor_feedback(session: SessionRecord) -> list[str]:
    """Surface rule-based safety/disclosure gate reasons only.

    The supervisor is a scorer, not a planner (PsychAgent §3.3 / PsychEval §5):
    its scale scores must not drive the next session's goals. This function
    therefore only surfaces deterministic safety/disclosure gate reasons; goal
    and strategy revision is handled by ``LongitudinalEvaluator`` (goal
    completion / client-state deltas) and the counselor's post-session review,
    never by scale scores.
    """
    verdict = session.safety_verdict
    if not verdict:
        return []
    return [f"安全/披露：{reason}" for reason in verdict.reasons]


class MemoryConsolidator:
    def consolidate(
        self,
        memory: SessionMemory,
        session: SessionRecord,
        *,
        next_index: int,
        warnings: list[str] | None = None,
    ) -> SessionMemory:
        """Fold one finished session into the four-field memory.

        ``warnings`` collects rejected retirement decisions (a ``done`` update
        without a quote from this session's dialogue, for example) so the caller
        can log them; it never changes the stored structure.
        """

        notes = warnings if warnings is not None else []
        clinical = session.clinical_summary
        dialogue = "\n".join(message.content for message in session.messages)
        recap = self._recap(session, clinical)
        homework = self._homework(memory, session, recap, dialogue, notes)
        checklist = self._checklist(
            memory, session, clinical, dialogue, next_index, notes
        )
        return memory.model_copy(
            update={
                "session_recaps": memory.session_recaps + [recap],
                "last_homework": homework,
                "checklist": checklist,
            }
        )

    @staticmethod
    def _recap(session: SessionRecord, clinical) -> SessionRecap:
        """Build the single per-session recap (replaces summaries + clinical)."""

        return SessionRecap(
            session_index=session.session_index,
            summary=session.summary,
            clinical_summary=clinical.session_summary_abstract if clinical else "",
            goal_assessment=clinical.goal_assessment if clinical else GoalAssessment(),
            client_state_analysis=(
                clinical.client_state_analysis if clinical else ClientStateAnalysis()
            ),
            homework=_unique(list(clinical.homework)) if clinical else [],
            interventions_used=_unique(list(session.interventions_used)),
            risk=MemoryConsolidator._risk(session),
            safety_notes=_supervisor_feedback(session),
            relationship_events=MemoryConsolidator._relationship_events(session),
            client_closing=MemoryConsolidator._client_closing(session),
        )

    @staticmethod
    def _risk(session: SessionRecord) -> RecapRisk | None:
        events = [item for item in session.risk_events if item.level in _RISK_ORDER[1:]]
        if not events:
            return None
        return RecapRisk(
            session_index=session.session_index,
            level=max(events, key=lambda item: _RISK_ORDER.index(item.level)).level,
            categories=_unique([entry for item in events for entry in item.categories]),
            evidence=_unique([entry for item in events for entry in item.evidence]),
        )

    @staticmethod
    def _relationship_events(session: SessionRecord) -> list[str]:
        return [
            (
                f"session={session.session_index},turn={record.get('turn_index')},"
                f"trust_change={record.get('client_turn_signal', {}).get('trust_change')}"
            )
            for record in session.turn_records
            if record.get("client_turn_signal", {}).get("trust_change")
            not in (None, "unchanged")
        ]

    @staticmethod
    def _client_closing(session: SessionRecord) -> str:
        clients = [item.content for item in session.messages if item.role == "client"]
        return clients[-1] if clients else ""

    @staticmethod
    def _item_updates(session: SessionRecord) -> list[MemoryItemUpdate]:
        clinical = session.clinical_summary
        return list(clinical.item_updates) if clinical else []

    @staticmethod
    def _apply_update(
        item: HomeworkItem | OpenItem,
        update: MemoryItemUpdate,
        dialogue: str,
        notes: list[str],
        *,
        label: str,
    ) -> None:
        """Apply one id-addressed update, refusing unproven completions."""

        if update.status == "done" and not _grounded(update.evidence, dialogue):
            notes.append(
                f"{label}条目 {item.item_id} 的完成更新缺少本场对话证据，保持未完成"
            )
            return
        item.status = update.status
        if update.status != "done":
            return
        if isinstance(item, HomeworkItem):
            item.completion_evidence = update.evidence
        else:
            item.evidence = update.evidence

    def _homework(
        self,
        memory: SessionMemory,
        session: SessionRecord,
        recap: SessionRecap,
        dialogue: str,
        notes: list[str],
    ) -> list[HomeworkItem]:
        """Carry open assignments forward, retire proven ones, add new ones."""

        items = [item.model_copy(deep=True) for item in memory.last_homework]
        for item in items:
            if item.status == "open" and item.source_session < session.session_index:
                item.carried_sessions += 1
        clinical = session.clinical_summary
        by_id = {item.item_id: item for item in items}
        for update in self._item_updates(session):
            item = by_id.get(update.item_id)
            if item is not None:
                self._apply_update(item, update, dialogue, notes, label="作业")
        completed = list(clinical.completed_items) if clinical else []
        for item in items:
            if item.status != "open":
                continue
            match = next(
                (entry for entry in completed if _same_item(entry, item.text)), None
            )
            if match is not None:
                item.status = "done"
                item.completion_evidence = match
        for text in recap.homework:
            if any(_same_item(text, item.text) for item in items if item.status == "open"):
                continue
            items.append(HomeworkItem(
                item_id=f"homework-s{session.session_index}-{len(items) + 1}",
                text=text,
                source_session=session.session_index,
            ))
        return [item for item in items if item.status == "open"]

    def _checklist(
        self,
        memory: SessionMemory,
        session: SessionRecord,
        clinical,
        dialogue: str,
        next_index: int,
        notes: list[str],
    ):
        """Archive this session's checklist, then retire or verify open items."""

        checklist = memory.checklist.model_copy(deep=True)
        if clinical is not None:
            checklist.per_session = [
                record for record in checklist.per_session
                if record.session_index != session.session_index
            ] + [ChecklistRecord(
                session_index=session.session_index,
                completed_items=_unique(list(clinical.completed_items)),
                important_information=_unique(list(clinical.important_information)),
                important_methods=_unique(list(clinical.important_methods)),
                important_results=_unique(list(clinical.important_results)),
                pending_items=_unique(list(clinical.pending_items)),
            )]
        tracked = {item.item_id: item for item in checklist.open_items}
        tracked.update({item.item_id: item for item in checklist.pending_verification})
        explicit: set[str] = set()
        for update in self._item_updates(session):
            item = tracked.get(update.item_id)
            if item is None:
                continue
            explicit.add(item.item_id)
            self._apply_update(item, update, dialogue, notes, label="待办")
        completed = list(clinical.completed_items) if clinical else []
        for item in checklist.open_items:
            if item.status == "open" and any(
                _same_item(entry, item.text) for entry in completed
            ):
                item.status = "done"
        # A boundary item the summary explicitly kept is a verified open topic now.
        confirmed = [
            item for item in checklist.pending_verification
            if item.item_id in explicit and item.status == "open"
        ]
        confirmed_ids = {item.item_id for item in confirmed}
        for item in confirmed:
            item.needs_verification = False
        checklist.pending_verification = [
            item for item in checklist.pending_verification
            if item.status == "open" and item.item_id not in confirmed_ids
        ]
        checklist.open_items = [
            item for item in checklist.open_items if item.status == "open"
        ]
        checklist.open_items.extend(confirmed)
        open_texts = [item.text for item in checklist.open_items]
        for text in (clinical.pending_items if clinical else []):
            if any(_same_item(text, existing) for existing in open_texts):
                continue
            checklist.open_items.append(OpenItem(
                item_id=f"topic-s{session.session_index}-{len(open_texts) + 1}",
                text=text,
                source_session=session.session_index,
            ))
            open_texts.append(text)
        if session.end_reason == "max_turns":
            objective = next(
                (item.strip() for item in session.plan.objectives if item.strip()), ""
            )
            if objective:
                checklist.pending_verification.append(OpenItem(
                    item_id=f"goal-s{session.session_index}-1",
                    kind="goal",
                    text=objective,
                    source_session=session.session_index,
                    needs_verification=True,
                    carried_to_session=next_index,
                ))
        return checklist

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
