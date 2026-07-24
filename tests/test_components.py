from __future__ import annotations

import asyncio

import pytest

from psychsandbox.agents import CounselorAgent
from psychsandbox.domain import (
    ClientGeneration,
    ClientState,
    CounselorDecision,
    CounselorTurn,
    RiskAssessment,
    RiskLevel,
    SessionMemory,
    UnlockedClientProfile,
)
from psychsandbox.model_client import MockGateway
from psychsandbox.runtime import DisclosureGate, StateUpdater
from psychsandbox.skills import HierarchicalSkillRetriever, SkillRegistry


def test_disclosure_rejects_low_trust(sample_case):
    state = sample_case.profile.initial_state.model_copy(update={"trust": 0})
    assert DisclosureGate().allowed(sample_case.profile, state, "", set()) == []


def test_disclosure_does_not_repeat(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    state = sample_case.profile.initial_state.model_copy(update={"trust": 1})
    result = DisclosureGate().allowed(
        sample_case.profile, state, " ".join(fact.required_topics), {fact.fact_id}
    )
    assert fact not in result


def test_unlock_records_evidence(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    unlocked = DisclosureGate().unlock(
        sample_case.profile, [fact.fact_id], session_index=2, turn_index=3
    )
    assert unlocked[0].evidence_session == 2
    assert unlocked[0].evidence_turn == 3


def test_state_stays_in_bounds():
    state = ClientState(trust=0.99, distress=0.01)
    counselor = CounselorTurn(
        decision=CounselorDecision(
            assessment="a", state_observation="b", strategy="c"
        ),
        response="我理解，我们一起尝试。",
    )
    client = ClientGeneration(
        utterance="好", cooperation=1, resistance=1, goal_progress_signal=1
    )
    updated, delta = StateUpdater().update(state, counselor, client)
    assert 0 <= updated.trust <= 1
    assert 0 <= updated.distress <= 1
    assert set(delta) == {"rule_delta", "model_signal_delta"}


def test_skill_parent_child_integrity(root):
    registry = SkillRegistry.from_json(root / "data/processed/psycheval/skills.json")
    assert all(
        skill.meta_skill_id in registry.meta_skills
        for skill in registry.atomic_skills.values()
    )


def test_retrieval_is_deterministic(root, sample_case):
    registry = SkillRegistry.from_json(root / "data/processed/psycheval/skills.json")
    retriever = HierarchicalSkillRetriever(registry)
    args = {
        "plan": sample_case.global_plan[0],
        "client_message": "我很焦虑，想理解自动想法",
        "risk": RiskAssessment(level=RiskLevel.LOW),
    }
    first = retriever.retrieve(**args)
    second = retriever.retrieve(**args)
    assert [x.skill_id for x in first.atomic_skills] == [
        x.skill_id for x in second.atomic_skills
    ]


def test_high_risk_returns_no_skills(root, sample_case):
    registry = SkillRegistry.from_json(root / "data/processed/psycheval/skills.json")
    result = HierarchicalSkillRetriever(registry).retrieve(
        plan=sample_case.global_plan[0],
        client_message="危险",
        risk=RiskAssessment(level=RiskLevel.HIGH),
    )
    assert result.atomic_skills == []


def test_counselor_payload_has_no_full_profile(sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    payload = CounselorAgent(MockGateway()).build_payload(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="你好",
        recent_messages=[],
        candidates=__import__("psychsandbox.domain", fromlist=["SkillCandidate"]).SkillCandidate(),
        risk=RiskAssessment(level=RiskLevel.LOW),
        counselor_turn_count=0,
    )
    dumped = str(payload)
    assert "full_client_profile" not in payload
    for fact in sample_case.profile.hidden_facts:
        assert fact.content not in dumped


def test_mock_gateway_structured_output(sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    result = asyncio.run(CounselorAgent(MockGateway()).respond(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="我很焦虑",
        recent_messages=[],
        candidates=__import__("psychsandbox.domain", fromlist=["SkillCandidate"]).SkillCandidate(),
        risk=RiskAssessment(level=RiskLevel.LOW),
        counselor_turn_count=0,
    ))
    assert result.response


def test_high_risk_counselor_routes_to_safety(sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    result = asyncio.run(CounselorAgent(MockGateway()).respond(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="我想自杀",
        recent_messages=[],
        candidates=__import__("psychsandbox.domain", fromlist=["SkillCandidate"]).SkillCandidate(),
        risk=RiskAssessment(level=RiskLevel.HIGH),
        counselor_turn_count=0,
    ))
    assert "安全" in result.response
