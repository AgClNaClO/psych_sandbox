"""Layout, retirement and read-budget contracts of the four-field memory."""

from __future__ import annotations

import json

from psychsandbox.domain import (
    ChecklistMemory,
    ClientState,
    ClinicalSummary,
    HomeworkItem,
    MemoryItemUpdate,
    MemoryViewConfig,
    Message,
    OpenItem,
    SessionMemory,
    SessionPlan,
    SessionRecap,
    SessionRecord,
    SessionStage,
    UnlockedClientInfo,
)
from psychsandbox.runtime.memory import MemoryConsolidator
from psychsandbox.runtime.memory_view import BUDGET_KEY, MemoryViewBuilder

CONSOLIDATOR = MemoryConsolidator()


def _memory(**kwargs) -> SessionMemory:
    return SessionMemory(
        case_id="case",
        known_background=UnlockedClientInfo(client_id="client"),
        **kwargs,
    )


def _record(
    session_index: int,
    *,
    clinical: ClinicalSummary | None = None,
    end_reason: str = "counselor_goal_complete",
    messages: list[Message] | None = None,
) -> SessionRecord:
    return SessionRecord(
        session_id=f"session-{session_index}",
        session_index=session_index,
        plan=SessionPlan(
            session_index=session_index,
            therapy="cbt",
            stage=SessionStage.CONCEPTUALIZATION,
            objectives=["澄清当前困扰", "共同确认下一步目标"],
        ),
        initial_state=ClientState(),
        final_state=ClientState(),
        messages=messages or [
            Message(
                session_index=session_index,
                turn_index=0,
                role="counselor",
                content="我们可以从哪里开始？",
            ),
            Message(
                session_index=session_index,
                turn_index=1,
                role="client",
                content="最近压力很大。",
            ),
        ],
        summary=f"第{session_index}次会谈摘要",
        clinical_summary=clinical,
        end_reason=end_reason,
    )


def test_session_memory_keeps_four_memory_fields_plus_management_fields():
    memory = _memory()
    assert list(SessionMemory.model_fields) == [
        "case_id",
        "known_background",
        "session_recaps",
        "last_homework",
        "checklist",
        "migration_warnings",
    ]
    assert memory.completed_sessions == 0
    assert memory.interventions_used == []
    assert memory.last_client_closing == ""
    assert memory.homework == []
    assert memory.unresolved_topics == []


def test_legacy_flat_memory_folds_into_the_four_fields():
    memory = SessionMemory.model_validate({
        "case_id": "case",
        "completed_sessions": 2,
        "summaries": ["s1", "s2"],
        "clinical_summaries": [
            {
                "session_index": 1,
                "session_summary_abstract": "a1",
                "homework": ["h1"],
                "completed_items": ["c1"],
                "pending_items": ["p1"],
            },
            {
                "session_index": 2,
                "session_summary_abstract": "a2",
                "homework": ["h2"],
                "completed_items": [],
                "pending_items": ["p2"],
            },
        ],
        "unlocked_client_info": {"client_id": "client", "main_problem": "m"},
        "unresolved_topics": ["p1"],
        "homework": ["h1", "h2"],
        "interventions_used": ["skill-1"],
        "risk_history": ["medium"],
        "supervisor_feedback": ["安全/披露：x"],
        "relationship_events": ["session=1,turn=1,trust_change=increased"],
        "between_session_context": ["legacy placeholder"],
        "last_client_closing": "closing",
        "migration_warnings": [],
    })

    assert memory.completed_sessions == 2
    assert [item.summary for item in memory.session_recaps] == ["s1", "s2"]
    assert [item.clinical_summary for item in memory.session_recaps] == ["a1", "a2"]
    assert memory.homework == ["h1", "h2"]
    assert memory.unresolved_topics == ["p1"]
    assert memory.interventions_used == ["skill-1"]
    assert memory.last_client_closing == "closing"
    assert memory.known_background.main_problem == "m"
    assert memory.checklist.per_session[0].completed_items == ["c1"]
    assert memory.checklist.per_session[0].pending_items == ["p1"]
    assert memory.session_recaps[-1].risk is not None
    assert memory.session_recaps[-1].safety_notes == ["安全/披露：x"]
    assert any("attached to session 2" in item for item in memory.migration_warnings)
    assert "between_session_context" not in memory.model_dump()


def test_homework_retires_only_with_dialogue_evidence():
    memory = _memory(last_homework=[
        HomeworkItem(item_id="homework-s1-1", text="记录一次压力事件", source_session=1),
    ])
    unproven = _record(2, clinical=ClinicalSummary(
        session_index=2,
        item_updates=[MemoryItemUpdate(
            item_id="homework-s1-1", status="done", evidence="我每天都记录了",
        )],
    ))
    notes: list[str] = []
    kept = CONSOLIDATOR.consolidate(memory, unproven, next_index=3, warnings=notes)

    assert [item.status for item in kept.last_homework] == ["open"]
    assert kept.last_homework[0].carried_sessions == 1
    assert notes and "缺少本场对话证据" in notes[0]

    proven = _record(
        2,
        messages=[Message(
            session_index=2, turn_index=0, role="client",
            content="我每天都记录了，感觉有点用。",
        )],
        clinical=ClinicalSummary(
            session_index=2,
            item_updates=[MemoryItemUpdate(
                item_id="homework-s1-1", status="done", evidence="我每天都记录了",
            )],
        ),
    )
    retired = CONSOLIDATOR.consolidate(memory, proven, next_index=3)
    assert retired.last_homework == []
    assert retired.homework == []


def test_reworded_completed_item_retires_an_open_topic():
    memory = _memory(checklist=ChecklistMemory(open_items=[
        OpenItem(item_id="topic-1", text="讨论压力对睡眠的影响", source_session=1),
    ]))
    session = _record(2, clinical=ClinicalSummary(
        session_index=2,
        completed_items=["讨论压力对睡眠影响"],
        pending_items=["练习呼吸放松"],
    ))

    updated = CONSOLIDATOR.consolidate(memory, session, next_index=3)

    assert updated.unresolved_topics == ["练习呼吸放松"]
    assert updated.checklist.per_session[0].completed_items == ["讨论压力对睡眠影响"]
    assert updated.checklist.open_items[0].text == "练习呼吸放松"


def test_max_turns_objective_is_carried_over_as_unverified():
    session = _record(2, end_reason="max_turns")

    memory = CONSOLIDATOR.consolidate(_memory(), session, next_index=3)

    pending = memory.checklist.pending_verification
    assert [item.text for item in pending] == ["澄清当前困扰"]
    assert pending[0].needs_verification is True
    assert pending[0].kind == "goal"
    assert pending[0].carried_to_session == 3
    # An implied boundary is not asserted as unfinished work.
    assert memory.unresolved_topics == []


def test_new_session_assigns_homework_and_archives_the_checklist():
    session = _record(1, clinical=ClinicalSummary(
        session_index=1,
        homework=["记录一次压力事件"],
        important_information=["来访者希望称呼为明山"],
        pending_items=["讨论睡眠"],
    ))

    memory = CONSOLIDATOR.consolidate(_memory(), session, next_index=2)

    assert [item.text for item in memory.last_homework] == ["记录一次压力事件"]
    assert memory.checklist.per_session[0].important_information == ["来访者希望称呼为明山"]
    assert memory.unresolved_topics == ["讨论睡眠"]
    assert memory.session_recaps[0].client_closing == "最近压力很大。"
    assert memory.completed_sessions == 1


def _recaps(count: int) -> list[SessionRecap]:
    return [
        SessionRecap(
            session_index=index,
            summary="摘" * 300,
            clinical_summary="临" * 300,
            homework=["记录一次压力事件"],
        )
        for index in range(1, count + 1)
    ]


def test_recap_window_keeps_focus_and_stays_within_budget():
    memory = _memory(
        session_recaps=_recaps(50),
        last_homework=[
            HomeworkItem(item_id="homework-s50-1", text="记录一次压力事件", source_session=50),
        ],
        checklist=ChecklistMemory(open_items=[
            OpenItem(item_id="topic-1", text="继续讨论睡眠", source_session=1),
        ]),
    )
    config = MemoryViewConfig(mode="recap_window", recent_sessions=3, max_chars=3000)

    view = MemoryViewBuilder(config).build(memory)

    assert view[BUDGET_KEY]["truncated"] is True
    assert view[BUDGET_KEY]["chars"] <= config.max_chars
    assert len(json.dumps(view, ensure_ascii=False)) <= config.max_chars + 64
    assert view["current_focus"]["last_homework"][0]["text"] == "记录一次压力事件"
    assert view["current_focus"]["open_items"][0]["text"] == "继续讨论睡眠"
    assert view["recent_session_recaps"][-1]["session_index"] == 50
    assert view["completed_sessions"] == 50
    assert memory.known_background.client_id in view["known_background"]["client_id"]


def test_recap_window_payload_never_grows_with_session_count():
    config = MemoryViewConfig(mode="recap_window", recent_sessions=2, max_chars=4000)
    builder = MemoryViewBuilder(config)

    sizes = [
        builder.build(_memory(session_recaps=_recaps(count)))[BUDGET_KEY]["chars"]
        for count in (1, 3, 6, 12, 24, 50)
    ]

    assert sizes == sorted(sizes)
    assert max(sizes) <= config.max_chars


def test_full_view_omits_management_fields_audit_logs_and_language_style():
    memory = _memory(
        session_recaps=[
            SessionRecap(
                session_index=1,
                summary="s1",
                safety_notes=["安全/披露：unauthorized_fact:x"],
                relationship_events=["session=1,turn=1,trust_change=increased"],
            ),
        ],
        migration_warnings=["legacy migrated"],
        checklist=ChecklistMemory(open_items=[
            OpenItem(item_id="topic-1", text="继续讨论睡眠", source_session=1),
        ]),
    )

    view = MemoryViewBuilder(MemoryViewConfig()).build(memory)

    assert "migration_warnings" not in view
    assert "language_features" not in view["known_background"]["static_traits"]
    assert [
        "safety_notes" not in item and "relationship_events" not in item
        for item in view["session_recaps"]
    ] == [True]
    assert view["checklist"]["open_items"][0]["text"] == "继续讨论睡眠"
    # The stored memory keeps the audit material.
    assert memory.session_recaps[0].safety_notes == ["安全/披露：unauthorized_fact:x"]
