from __future__ import annotations

import asyncio

from psychsandbox.agents import ClientAgent
from psychsandbox.client_simulation import ClientSimulator, ClientTurnInput
from psychsandbox.domain import (
    ClientState,
    CounselorDecision,
    CounselorTurn,
    SessionMemory,
    UnlockedClientInfo,
    DisclosureItem,
    TrustTier,
)
from tests.deterministic_gateway import DeterministicGateway


def _counselor(response: str) -> CounselorTurn:
    return CounselorTurn(
        decision=CounselorDecision(
            assessment="测试",
            state_observation="测试",
            strategy="澄清",
        ),
        response=response,
    )


def test_session_boundary_recovers_fatigue_and_decays_trust_to_baseline():
    previous = ClientState(
        trust=0.63,
        distress=0.71,
        hope=0.44,
        fatigue=0.82,
        resistance=0.7,
    )
    baseline = ClientState(trust=0.25, resistance=0.4)

    recovered = ClientSimulator.prepare_session_state(previous, baseline, 0.5)

    assert recovered.fatigue == 0.57
    assert recovered.trust == 0.44
    assert recovered.resistance == 0.4
    assert recovered.distress == previous.distress


def test_simulator_owns_atomic_disclosure_pipeline(sample_case):
    event = DisclosureItem(
        item_id="unique:event",
        evidence_ids=["unique:event"],
        content="表层经历",
        activation_tags=["独特经历"],
        trust_tier=TrustTier.BASIC,
    )
    meaning = DisclosureItem(
        item_id="unique:meaning",
        evidence_ids=["unique:meaning"],
        content="更私密的意义",
        activation_tags=["独特经历"],
        trust_tier=TrustTier.SENSITIVE,
        depends_on=[event.item_id],
    )
    profile = sample_case.profile.model_copy(
        update={"disclosure_items": [event, meaning]}
    )
    state = profile.initial_state.model_copy(update={"trust": 0.8})
    simulator = ClientSimulator(ClientAgent(DeterministicGateway()))

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

    assert first.newly_unlocked[0].content == "表层经历"
    assert second.newly_unlocked[0].content == "更私密的意义"
    merged = simulator.merge_unlocked(first.newly_unlocked, second.newly_unlocked)
    assert len(merged) == 2


def test_merge_unlocked_preserves_separate_spoken_evidence_fragments():
    from psychsandbox.domain import UnlockedFact

    first = UnlockedFact(
        fact_id="fact:1",
        content="我上次只说了表层经历",
        evidence_session=1,
        evidence_turn=2,
    )
    second = first.model_copy(
        update={
            "content": "这次补充了它对我的意义",
            "evidence_session": 2,
            "evidence_turn": 3,
        }
    )

    merged = ClientSimulator.merge_unlocked([first], [second])

    assert merged[0].content == "我上次只说了表层经历；这次补充了它对我的意义"


def test_legacy_spoken_fact_maps_only_to_one_substantiated_atomic_item(sample_case):
    from psychsandbox.domain import UnlockedFact

    item = next(
        candidate for candidate in sample_case.profile.disclosure_items
        if len(candidate.content) >= 4
        and sum(
            candidate.content in other.content
            for other in sample_case.profile.disclosure_items
        ) == 1
    )
    legacy = UnlockedFact(
        fact_id="legacy:fact:1",
        content=item.content,
        evidence_session=1,
        evidence_turn=2,
    )
    migrated, warnings = ClientSimulator.migrate_legacy_unlocked(
        sample_case.profile, [legacy]
    )

    assert migrated[0].fact_id == item.item_id
    assert warnings and warnings[0].startswith("mapped legacy spoken fact")
