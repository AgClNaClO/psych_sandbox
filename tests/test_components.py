from __future__ import annotations

import asyncio

import pytest

from psychsandbox.agents import ClientAgent, CounselorAgent
from psychsandbox.domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientState,
    ClientTurnSignal,
    ClientUtterance,
    CounselorDecision,
    CounselorTurn,
    DisclosureDecision,
    RiskAssessment,
    RiskLevel,
    TrustChange,
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


def test_disclosure_returns_blocked_signal_without_content(sample_case):
    fact = max(sample_case.profile.hidden_facts, key=lambda item: item.sensitivity)
    state = sample_case.profile.initial_state.model_copy(update={"trust": 0})
    decision = DisclosureGate().evaluate(
        sample_case.profile,
        state,
        " ".join(fact.activation_tags),
        set(),
    )
    blocked = next(item for item in decision.blocked if item.fact_id == fact.fact_id)
    assert blocked.category == fact.category
    assert "content" not in blocked.model_dump()


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


def test_trust_changes_only_from_turn_signal():
    state = ClientState(trust=0.5)
    counselor = CounselorTurn(
        decision=CounselorDecision(
            assessment="a", state_observation="b", strategy="c"
        ),
        response="我理解，也谢谢你愿意说。",
    )
    client = ClientGeneration(utterance="好", cooperation=1)
    unchanged, _ = StateUpdater().update(state, counselor, client)
    increased, _ = StateUpdater().update(
        state,
        counselor,
        client,
        ClientTurnSignal(trust_change=TrustChange.SLIGHT_INCREASE),
    )
    assert unchanged.trust == 0.5
    assert increased.trust == 0.55


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


class CountingMockGateway(MockGateway):
    def __init__(self):
        self.calls = []

    async def complete_structured(self, **kwargs):
        self.calls.append(kwargs["output_schema"])
        return await super().complete_structured(**kwargs)


def test_client_two_stage_calls_and_strict_utterance_payload(sample_case):
    gateway = CountingMockGateway()
    agent = ClientAgent(gateway)
    disclosure = DisclosureDecision()
    signal = asyncio.run(agent.plan_turn(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="最近怎么样？",
        recent_messages=[],
        disclosure=disclosure,
        recent_signals=[],
        turn_index=1,
    ))
    generation, metadata = asyncio.run(agent.generate_utterance(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="最近怎么样？",
        recent_messages=[],
        disclosure=disclosure,
        signal=signal,
        already_disclosed_ids=set(),
        turn_index=1,
    ))
    payload = agent.build_utterance_payload(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="最近怎么样？",
        recent_messages=[],
        disclosure=disclosure,
        signal=signal,
        turn_index=1,
    )
    dumped = str(payload)
    assert gateway.calls == [ClientTurnSignal, ClientUtterance]
    assert generation.utterance
    assert metadata["retry_count"] == 0
    assert "session_plan" not in payload
    assert "growth_experiences" not in dumped
    assert "special_situations" not in dumped
    for fact in sample_case.profile.hidden_facts:
        assert fact.content not in dumped


class AlwaysLeakingGateway(MockGateway):
    def __init__(self, fact):
        self.fact = fact
        self.utterance_calls = 0

    async def complete_structured(self, **kwargs):
        if kwargs["output_schema"] is ClientUtterance:
            self.utterance_calls += 1
            return ClientUtterance(
                utterance=self.fact.content,
                disclosed_fact_ids=[self.fact.fact_id],
            )
        return await super().complete_structured(**kwargs)


def test_client_leak_retries_then_uses_safe_fallback(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    gateway = AlwaysLeakingGateway(fact)
    agent = ClientAgent(gateway, leak_retry_limit=1)
    signal = ClientTurnSignal(behavior=ClientBehaviorType.RESISTANCE)
    generation, metadata = asyncio.run(agent.generate_utterance(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="请继续。",
        recent_messages=[],
        disclosure=DisclosureDecision(),
        signal=signal,
        already_disclosed_ids=set(),
        turn_index=1,
    ))
    assert gateway.utterance_calls == 2
    assert metadata["retry_count"] == 1
    assert metadata["used_fallback"] is True
    assert fact.content not in generation.utterance
    assert generation.disclosed_fact_ids == []


def test_respectful_and_pushy_messages_diverge(sample_case):
    fact = max(sample_case.profile.hidden_facts, key=lambda item: item.sensitivity)
    blocked = DisclosureGate().evaluate(
        sample_case.profile,
        sample_case.profile.initial_state.model_copy(update={"trust": 0}),
        " ".join(fact.activation_tags),
        set(),
    )
    agent = ClientAgent(MockGateway())
    pushy = asyncio.run(agent.plan_turn(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="你必须直接告诉我，为什么不说这段过去？",
        recent_messages=[],
        disclosure=blocked,
        recent_signals=[],
        turn_index=1,
    ))
    respectful = asyncio.run(agent.plan_turn(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="不着急，我们按你的节奏，也可以先不谈。",
        recent_messages=[],
        disclosure=DisclosureDecision(),
        recent_signals=[],
        turn_index=1,
    ))
    assert pushy.trust_change is TrustChange.SIGNIFICANT_DECREASE
    assert pushy.behavior is ClientBehaviorType.RESISTANCE
    assert respectful.trust_change is TrustChange.SLIGHT_INCREASE


def test_client_pulls_back_after_consecutive_exploration(sample_case):
    agent = ClientAgent(MockGateway(), pullback_after=2)
    prior = [
        ClientTurnSignal(behavior=ClientBehaviorType.COGNITIVE_EXPLORATION),
        ClientTurnSignal(behavior=ClientBehaviorType.AFFECTIVE_EXPLORATION),
    ]
    result = agent._apply_pullback(
        ClientTurnSignal(behavior=ClientBehaviorType.INSIGHT),
        sample_case.profile.initial_state.model_copy(update={"trust": 0.5}),
        prior,
    )
    assert result.behavior is ClientBehaviorType.SIMPLE_RESPONSE
