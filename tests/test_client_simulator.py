from __future__ import annotations

import asyncio

from psychsandbox.agents import ClientAgent
from psychsandbox.client_simulation import ClientSimulator, ClientTurnInput
from psychsandbox.domain import (
    ClientState,
    CounselorDecision,
    CounselorTurn,
    SessionMemory,
    UnlockedClientProfile,
)
from psychsandbox.model_client import MockGateway


def _counselor(response: str) -> CounselorTurn:
    return CounselorTurn(
        decision=CounselorDecision(
            assessment="测试",
            state_observation="测试",
            strategy="澄清",
        ),
        response=response,
    )


def test_session_boundary_recovers_fatigue_without_resetting_longitudinal_state():
    previous = ClientState(
        trust=0.63,
        distress=0.71,
        hope=0.44,
        fatigue=0.82,
        topic_readiness={"work": 0.55},
    )

    recovered = ClientSimulator.prepare_session_state(previous)

    assert recovered.fatigue == 0.57
    assert recovered.model_dump(exclude={"fatigue"}) == previous.model_dump(
        exclude={"fatigue"}
    )


def test_simulator_owns_progressive_disclosure_pipeline(sample_case):
    original = sample_case.profile.hidden_facts[0]
    fact = original.model_copy(
        update={
            "content": "表层经历；更私密的意义",
            "disclosure_layers": ["表层经历", "表层经历；更私密的意义"],
            "activation_tags": ["独特经历"],
            "topic_key": "unique_experience",
            "minimum_trust": 0.2,
            "minimum_topic_readiness": 0.2,
        }
    )
    profile = sample_case.profile.model_copy(update={"hidden_facts": [fact]})
    state = profile.initial_state.model_copy(
        update={"trust": 0.8, "topic_readiness": {"unique_experience": 0.8}}
    )
    simulator = ClientSimulator(ClientAgent(MockGateway()))

    first = asyncio.run(
        simulator.respond(
            ClientTurnInput(
                profile=profile,
                state=state,
                counselor_turn=_counselor("可以具体谈谈这段独特经历吗？"),
                recent_messages=[],
                unlocked_facts=[],
                recent_signals=[],
                session_index=1,
                turn_index=2,
            )
        )
    )
    second = asyncio.run(
        simulator.respond(
            ClientTurnInput(
                profile=profile,
                state=first.state_after,
                counselor_turn=_counselor("如果愿意，可以继续谈这段独特经历。"),
                recent_messages=[],
                unlocked_facts=first.newly_unlocked,
                recent_signals=[first.signal],
                session_index=1,
                turn_index=3,
            )
        )
    )

    assert first.newly_unlocked[0].disclosure_level == 1
    assert first.newly_unlocked[0].content == "表层经历"
    assert second.newly_unlocked[0].disclosure_level == 2
    merged = simulator.merge_unlocked(first.newly_unlocked, second.newly_unlocked)
    assert len(merged) == 1
    assert merged[0].content == "表层经历；更私密的意义"


def test_merge_unlocked_preserves_separate_spoken_evidence_fragments():
    from psychsandbox.domain import UnlockedFact

    first = UnlockedFact(
        fact_id="fact:1",
        content="我上次只说了表层经历",
        evidence_session=1,
        evidence_turn=2,
        disclosure_level=1,
    )
    second = first.model_copy(
        update={
            "content": "这次补充了它对我的意义",
            "evidence_session": 2,
            "evidence_turn": 3,
            "disclosure_level": 2,
        }
    )

    merged = ClientSimulator.merge_unlocked([first], [second])

    assert merged[0].content == "我上次只说了表层经历；这次补充了它对我的意义"


def test_session_opening_does_not_reuse_context_dependent_name_answer(sample_case):
    profile = sample_case.profile.model_copy(update={"opening": "叫我明山就可以。"})
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=profile.client_id),
    )

    opening = ClientSimulator.start_session(profile, memory, 1)

    assert opening != "叫我明山就可以。"
    assert profile.main_problem[:10] in opening
