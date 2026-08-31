from __future__ import annotations

import asyncio

from psychsandbox.agents import CounselorAgent
from psychsandbox.domain import (
    RiskAssessment,
    RiskLevel,
    SandboxConfig,
    SessionMemory,
    UnlockedClientInfo,
)
from psychsandbox.runtime import CounselingSandbox, DialogueLoopGuard, DisclosureGate
from tests.deterministic_gateway import DeterministicGateway


def _memory_for(sample_case) -> SessionMemory:
    return SessionMemory(
        case_id=sample_case.case_id,
        unlocked_client_info=UnlockedClientInfo(
            client_id=sample_case.profile.client_id
        ),
    )


def test_single_generic_tag_does_not_activate_hidden_memory(sample_case):
    state = sample_case.profile.initial_state.model_copy(update={"trust": 0})
    decision = DisclosureGate().evaluate(
        sample_case.profile,
        state,
        "这对你最直接的影响是什么？",
        set(),
    )
    growth_ids = {
        fact.item_id
        for fact in sample_case.profile.disclosure_items
        if fact.category == "growth_experience"
    }
    assert growth_ids
    assert growth_ids.isdisjoint(decision.activated_fact_ids)


def test_shared_activation_tags_are_reported_as_ambiguous(sample_case):
    state = sample_case.profile.initial_state.model_copy(update={"trust": 0})
    decision = DisclosureGate().evaluate(
        sample_case.profile,
        state,
        "可以谈谈过去的成长经历吗？",
        set(),
    )
    growth_ids = {
        fact.item_id
        for fact in sample_case.profile.disclosure_items
        if fact.category == "growth_experience"
    }
    assert growth_ids
    assert growth_ids.issubset(set(decision.ambiguous_fact_ids))
    assert growth_ids.isdisjoint(decision.activated_fact_ids)


def test_counselor_respects_explicit_topic_boundary(sample_case):
    client_message = "我不太想现在谈这个。我们能不能先说说别的？"
    result = asyncio.run(
        CounselorAgent(DeterministicGateway()).respond(
            memory=_memory_for(sample_case),
            plan=sample_case.global_plan[0],
            client_message=client_message,
            recent_messages=[{"role": "client", "content": client_message}],
            risk=RiskAssessment(level=RiskLevel.LOW),
            counselor_turn_count=1,
        )
    )
    assert "先不谈" in result.response
    assert "最直接的影响" not in result.response
    assert result.decision.selected_atomic_skill_ids == []


def test_repeated_boundary_triggers_relationship_repair(sample_case):
    client_message = "我不太想现在谈这个。我们能不能先说说别的？"
    result = asyncio.run(
        CounselorAgent(DeterministicGateway()).respond(
            memory=_memory_for(sample_case),
            plan=sample_case.global_plan[0],
            client_message=client_message,
            recent_messages=[
                {"role": "client", "content": client_message},
                {"role": "counselor", "content": "这对你最直接的影响是什么？"},
                {"role": "client", "content": client_message},
            ],
            risk=RiskAssessment(level=RiskLevel.LOW),
            counselor_turn_count=2,
        )
    )
    assert "对不起" in result.response
    assert "停下" in result.response


def test_exact_counselor_reply_is_detected_as_repetition():
    guard = DialogueLoopGuard()
    response = "这对你最直接的影响是什么？"
    assert guard.is_repeated_counselor_response(
        response,
        [
            {"role": "counselor", "content": response},
            {"role": "client", "content": "我不想谈这个。"},
        ],
    )


def test_original_case_does_not_enter_refusal_loop(root, tmp_path, repository):
    sandbox = CounselingSandbox(
        SandboxConfig(
            project_root=root,
            max_turns_per_session=4,
            database_path=tmp_path / "dialogue-loop.sqlite3",
            trace_dir=tmp_path / "dialogue-loop-traces",
        ),
            gateway=DeterministicGateway(),
            repository=repository,
    )
    result = asyncio.run(
        sandbox.run_case("psycheval-cbt-001", session_count=1)
    )
    messages = result.sessions[0].messages
    refusal_count = sum(
        message.role == "client"
        and ("不想现在谈" in message.content or "暂时不想谈" in message.content)
        for message in messages
    )
    counselor_messages = [
        message.content for message in messages if message.role == "counselor"
    ]
    assert refusal_count <= 1
    assert len(counselor_messages) == len(set(counselor_messages))
