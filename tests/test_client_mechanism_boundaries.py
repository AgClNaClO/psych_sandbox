from __future__ import annotations

import asyncio
import json

import pytest
import yaml

from psychsandbox.agents import ClientAgent, CounselorAgent
from psychsandbox.client_simulation import ClientSimulator, ClientTurnInput
from psychsandbox.client_simulation.policies import (
    FAITHFUL_PROMPT,
    FaithfulPatientActPolicy,
)
from psychsandbox.client_simulation.prompts import CLIENT_PLANNER_TEMPLATE
from psychsandbox.config import default_config
from psychsandbox.domain import (
    BigFive, ClientBehaviorType, ClientGeneration, ClientReactionType,
    ClientRelationalProfile, ClientSimulationConfig, ClientState, ClientTurnSignal,
    ClientUtterance, CounselorDecision, CounselorTurn, DisclosureDecision,
    DisclosureItem, RiskAssessment, RuptureState, SessionMemory, TrustChange,
    TrustTier, UnlockedClientInfo, UnlockedFact,
)
from psychsandbox.prompts import render_prompt
from psychsandbox.runtime.disclosure import DisclosureGate
from psychsandbox.runtime.state import StateUpdater
from tests.deterministic_gateway import DeterministicGateway


def counselor(text="Can we discuss the unique topic?"):
    return CounselorTurn(
        decision=CounselorDecision(assessment="test", state_observation="test", strategy="clarify"),
        response=text,
    )


def profile_with_item(sample_case, **updates):
    item = DisclosureItem(
        item_id="private-event", evidence_ids=["private-event"],
        content="A uniquely private event happened at the observatory.",
        activation_tags=["unique topic"], trust_tier=TrustTier.DEEP,
        generates_discomfort=True, emotional_cost=0.9,
    ).model_copy(update=updates)
    return sample_case.profile.model_copy(update={"disclosure_items": [item]})


def turn_input(profile, **updates):
    args = dict(
        profile=profile, state=ClientState(trust=0.1), counselor_turn=counselor(),
        recent_messages=[], unlocked_facts=[], recent_signals=[], session_index=1, turn_index=1,
    )
    args.update(updates)
    return ClientTurnInput(**args)


class RecordingGateway(DeterministicGateway):
    def __init__(self):
        self.calls = []

    async def complete_structured(self, **kwargs):
        payload = kwargs["input_payload"]
        self.calls.append((kwargs["output_schema"].__name__, payload))
        return await super().complete_structured(**kwargs)


def test_blocked_content_and_planner_rationale_cannot_enter_generation(sample_case):
    profile = profile_with_item(sample_case)
    gate = DisclosureGate().evaluate(profile, ClientState(trust=0.1), "unique topic", set())
    signal = ClientTurnSignal(rationale=profile.disclosure_items[0].content)
    payload = ClientAgent(RecordingGateway()).build_utterance_payload(
        profile=profile, state=ClientState(), counselor_message="unique topic",
        recent_messages=[], disclosure=gate, signal=signal, turn_index=1,
    )
    assert payload["blocked_topics"]
    assert "content" not in payload["blocked_topics"][0]
    assert profile.disclosure_items[0].content not in json.dumps(payload)
    assert "rationale" not in payload["turn_signal"]
    assert "trust_change" not in payload["turn_signal"]


class FaithfulRecordingGateway(RecordingGateway):
    async def complete_structured(self, **kwargs):
        step = kwargs["input_payload"].get("decision_step")
        if step:
            self.calls.append((step, kwargs["input_payload"]))
            schema = kwargs["output_schema"]
            if step == "reaction":
                return schema(reaction=ClientReactionType.UNDERSTOOD)
            if step == "behavior":
                return schema(behavior=ClientBehaviorType.SIMPLE_RESPONSE)
            return schema(trust_change=TrustChange.SLIGHT_INCREASE)
        return await super().complete_structured(**kwargs)


def test_faithful_trust_reads_accepted_response_after_generation(sample_case):
    gateway = FaithfulRecordingGateway()
    agent = ClientAgent(gateway)
    before = ClientState(trust=0.1)
    result = asyncio.run(ClientSimulator(agent, policy=FaithfulPatientActPolicy(agent)).respond(
        turn_input(sample_case.profile, state=before)
    ))
    assert [name for name, _ in gateway.calls] == ["reaction", "behavior", "ClientUtterance", "trust"]
    assert gateway.calls[-1][1]["accepted_client_response"] == result.generation.utterance
    assert gateway.calls[2][1]["simulation_state"]["trust"] == 0.1
    assert before.trust == 0.1
    assert result.state_after.trust == 0.13
    assert result.leakage["client_model_calls"] == 4


class RetryingGateway(FaithfulRecordingGateway):
    def __init__(self, item):
        super().__init__()
        self.item = item
        self.utterance_calls = 0

    async def complete_structured(self, **kwargs):
        if kwargs["output_schema"] is ClientUtterance:
            self.utterance_calls += 1
            if self.utterance_calls == 1:
                self.calls.append(("ClientUtterance", kwargs["input_payload"]))
                return ClientUtterance(utterance=self.item.content, disclosed_fact_ids=[self.item.item_id])
        return await super().complete_structured(**kwargs)


class CountingUpdater(StateUpdater):
    def __init__(self):
        self.calls = 0

    def update(self, *args, **kwargs):
        self.calls += 1
        return super().update(*args, **kwargs)


def test_leak_retry_updates_state_and_trust_once(sample_case):
    profile = profile_with_item(sample_case)
    gateway = RetryingGateway(profile.disclosure_items[0])
    updater = CountingUpdater()
    agent = ClientAgent(gateway)
    result = asyncio.run(ClientSimulator(
        agent, state_updater=updater, policy=FaithfulPatientActPolicy(agent)
    ).respond(turn_input(profile)))
    assert result.leakage["retry_count"] == 1
    assert updater.calls == 1
    assert sum(name == "trust" for name, _ in gateway.calls) == 1
    assert result.newly_unlocked == []
    assert gateway.calls[-1][1]["accepted_client_response"] == result.generation.utterance
    assert profile.disclosure_items[0].content != result.generation.utterance


@pytest.mark.parametrize("setting", ["use_memory", "use_pipeline", "use_trust_gating"])
def test_ablation_switch_preserves_fact_firewall(sample_case, setting):
    gateway = RecordingGateway()
    profile = profile_with_item(sample_case)
    result = asyncio.run(ClientSimulator(ClientAgent(gateway)).respond(
        turn_input(profile, **{setting: False})
    ))
    payload = next(payload for name, payload in gateway.calls if name == "ClientUtterance")
    if setting == "use_memory":
        assert result.disclosure.retrieved == result.disclosure.blocked == []
        assert payload["available_memories"] == []
    elif setting == "use_pipeline":
        assert len(gateway.calls) == 1
        assert payload["use_pipeline"] is False
        assert payload["available_memories"] == []
    else:
        assert [item.item_id for item in result.disclosure.retrieved] == ["private-event"]
        assert not result.disclosure.blocked


def test_trust_ablation_keeps_session_and_dependency_boundaries(sample_case):
    profile = profile_with_item(sample_case, session_scope=[2], depends_on=["parent"])
    gate = DisclosureGate()
    assert not gate.evaluate(profile, ClientState(), "unique topic", set(), session_index=1, use_trust_gating=False).retrieved
    assert not gate.evaluate(profile, ClientState(), "unique topic", set(), session_index=2, use_trust_gating=False).retrieved
    assert gate.evaluate(profile, ClientState(), "unique topic", {"parent"}, session_index=2, use_trust_gating=False).retrieved


def test_memory_ablation_keeps_spoken_evidence_across_sessions(sample_case):
    spoken = UnlockedFact(fact_id="spoken", content="I already described this.", evidence_session=1, evidence_turn=1)
    gateway = RecordingGateway()
    asyncio.run(ClientSimulator(ClientAgent(gateway)).respond(turn_input(
        profile_with_item(sample_case), use_memory=False, session_index=2, unlocked_facts=[spoken]
    )))
    payload = next(payload for name, payload in gateway.calls if name == "ClientUtterance")
    assert payload["known_memories"][0]["content"] == spoken.content


def test_understanding_and_sensitive_disclosure_increase_trust_and_distress_independently(sample_case):
    before = ClientState()
    profile = profile_with_item(sample_case)
    after, audit = StateUpdater().update(
        before, counselor("We can go slowly."),
        ClientGeneration(utterance="I feel heard, but this is painful.", disclosed_fact_ids=["private-event"]),
        ClientTurnSignal(reaction=ClientReactionType.UNDERSTOOD, trust_change=TrustChange.SLIGHT_INCREASE), profile,
    )
    assert after.trust > before.trust
    assert after.distress > before.distress
    assert after.hope == before.hope
    assert audit["interaction_features"]["emotional_load"] == 0.9


def test_avoidance_reduces_activation_without_progress():
    before = ClientState()
    after, _ = StateUpdater().update(
        before, counselor(), ClientGeneration(utterance="Nothing much.", goal_progress_signal=1),
        ClientTurnSignal(behavior=ClientBehaviorType.RESISTANCE),
    )
    assert after.distress < before.distress
    assert after.arousal < before.arousal
    assert after.hope == before.hope


def test_goal_score_alone_does_not_change_emotion():
    updater = StateUpdater()
    low, _ = updater.update(ClientState(), counselor(), ClientGeneration(utterance="Okay", goal_progress_signal=-1))
    high, _ = updater.update(ClientState(), counselor(), ClientGeneration(utterance="Okay", goal_progress_signal=1))
    assert low == high


def test_pressure_and_rupture_persist_until_gradual_repair():
    updater = StateUpdater()
    before = ClientState()
    pressured, _ = updater.update(before, counselor("必须直接告诉我"), ClientGeneration(utterance="No"),
        ClientTurnSignal(reaction=ClientReactionType.SCARED, trust_change=TrustChange.SLIGHT_DECREASE))
    assert pressured.trust < before.trust
    assert pressured.arousal > before.arousal
    assert pressured.resistance > before.resistance
    carried = ClientSimulator.prepare_session_state(pressured, before)
    assert carried.rupture_state is RuptureState.ACTIVE
    repairing, _ = updater.update(carried, counselor("按你的节奏，可以停"), ClientGeneration(utterance="Okay"),
        ClientTurnSignal(trust_change=TrustChange.SLIGHT_INCREASE))
    assert repairing.rupture_state is RuptureState.REPAIRING


def test_synthetic_traits_are_private_bounded_and_roundtrip(sample_case):
    simulation = ClientSimulationConfig(
        traits=BigFive(extraversion=1, openness=1, neuroticism=1),
        origin="synthetic_configuration", source_ids=["experiment:synthetic"], uncertainty=0.2,
    )
    profile = sample_case.profile.model_copy(update={"simulation_config": simulation})
    assert type(profile).model_validate(profile.model_dump()).simulation_config == simulation
    assert max(abs(value) for value in simulation.modifiers().values()) <= 0.1
    assert all(value == 0 for value in ClientSimulationConfig(traits=simulation.traits).modifiers().values())
    context = CounselorAgent(RecordingGateway()).build_context_payload(
        memory=SessionMemory(case_id=sample_case.case_id, known_background=UnlockedClientInfo(client_id=profile.client_id)),
        plan=sample_case.global_plan[0], client_message="Hello", recent_messages=[],
        risk=RiskAssessment(level="low"), counselor_turn_count=1,
    )
    encoded = json.dumps(context)
    for private in ("simulation_config", "\"traits\"", "experiment:synthetic", "emotional_cost", "appraisal"):
        assert private not in encoded


def test_ablation_yaml_loading(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "runtime.yaml").write_text(yaml.safe_dump({"client": {
        "use_memory": False, "use_pipeline": False, "use_trust_gating": False,
        "topic_matcher": "semantic",
    }}), encoding="utf-8")
    config = default_config(tmp_path)
    assert not config.client_use_memory
    assert not config.client_use_pipeline
    assert not config.client_use_trust_gating
    assert config.client_topic_matcher == "semantic"


def test_default_config_keeps_the_auditable_topic_matcher(root):
    assert default_config(root).client_topic_matcher == "tags"


def test_unlock_cannot_backfill_without_authorization_and_spoken_evidence(sample_case):
    profile = profile_with_item(sample_case)
    item = profile.disclosure_items[0]
    gate = DisclosureGate()
    kwargs = dict(session_index=1, turn_index=1)
    assert gate.unlock(profile, [item.item_id], **kwargs) == []
    assert gate.unlock(profile, [item.item_id], retrieved_facts=[item], **kwargs) == []
    assert gate.unlock(profile, [item.item_id], evidence_by_fact_id={item.item_id: item.content}, **kwargs) == []


def test_personality_modifiers_affect_expression_and_recovery_not_gating(sample_case):
    profile = profile_with_item(sample_case)
    configured = profile.model_copy(update={"simulation_config": ClientSimulationConfig(
        traits=BigFive(extraversion=1, openness=1, neuroticism=1),
        origin="synthetic_configuration", uncertainty=0,
    )})
    gateway = RecordingGateway()
    agent = ClientAgent(gateway)
    disclosure = DisclosureGate().evaluate(profile, ClientState(), "unique topic", set())
    kwargs = dict(state=ClientState(), counselor_message="unique topic", recent_messages=[],
        disclosure=disclosure, signal=ClientTurnSignal(), turn_index=1)
    neutral = agent.build_utterance_payload(profile=profile, **kwargs)
    modified = agent.build_utterance_payload(profile=configured, **kwargs)
    assert modified["expression_modifiers"]["expression_length"] > neutral["expression_modifiers"]["expression_length"]
    assert modified["available_memories"] == neutral["available_memories"] == []
    updater = StateUpdater()
    args = (ClientState(), counselor("按你的节奏，可以停"), ClientGeneration(utterance="Okay"), ClientTurnSignal())
    ordinary, _ = updater.update(*args, profile)
    sensitive, _ = updater.update(*args, configured)
    assert sensitive.distress > ordinary.distress
    assert sensitive.trust == ordinary.trust


def _planner_payload(profile):
    gateway = RecordingGateway()
    asyncio.run(ClientAgent(gateway).plan_turn(
        profile=profile, state=ClientState(), counselor_message="最近怎么样？",
        recent_messages=[], disclosure=DisclosureDecision(), recent_signals=[],
        turn_index=1,
    ))
    name, payload = gateway.calls[-1]
    assert name == "ClientTurnSignal"
    return payload


def _conditioned(sample_case, **relational):
    return sample_case.profile.model_copy(update={
        "relational": ClientRelationalProfile(**relational)
    })


def test_unsourced_attachment_conditioning_stays_inert(sample_case):
    profile = _conditioned(sample_case, attachment_pattern="anxious")
    assert profile.attachment_conditioning() is None
    payload = _planner_payload(profile)
    assert payload["attachment_conditioning"] is None
    rendered = render_prompt(CLIENT_PLANNER_TEMPLATE, **payload)
    assert "attachment_conditioning 为空" in rendered
    assert "pattern=anxious" not in rendered


def test_attachment_conditioning_requires_evidence_and_confidence(sample_case):
    evidence_id = sample_case.profile.evidence_nodes[0].evidence_id
    low = _conditioned(
        sample_case, attachment_pattern="anxious",
        source_fact_ids=[evidence_id], confidence=0.2,
    )
    assert low.attachment_conditioning() is None
    unknown = _conditioned(
        sample_case, attachment_pattern="anxious",
        source_fact_ids=["not-an-evidence-node"], confidence=0.9,
    )
    assert unknown.attachment_conditioning() is None
    for pattern in ("secure", "unspecified"):
        assert _conditioned(
            sample_case, attachment_pattern=pattern,
            source_fact_ids=[evidence_id], confidence=0.9,
        ).attachment_conditioning() is None
    sourced = _conditioned(
        sample_case, attachment_pattern="avoidant",
        source_fact_ids=[evidence_id], confidence=0.9,
    ).attachment_conditioning()
    assert sourced == {
        "pattern": "avoidant", "source_ids": [evidence_id], "confidence": 0.9,
    }


def test_sourced_attachment_conditioning_reaches_both_trust_decision_sites(sample_case):
    evidence_id = sample_case.profile.evidence_nodes[0].evidence_id
    profile = _conditioned(
        sample_case, attachment_pattern="anxious",
        source_fact_ids=[evidence_id], confidence=0.8,
    )
    payload = _planner_payload(profile)
    assert payload["attachment_conditioning"]["pattern"] == "anxious"
    assert payload["attachment_conditioning"]["source_ids"] == [evidence_id]
    rendered = render_prompt(CLIENT_PLANNER_TEMPLATE, **payload)
    assert "依恋条件化（有来源）" in rendered
    assert "pattern=anxious" in rendered
    assert "attachment_conditioning 为空" not in rendered

    faithful = FaithfulRecordingGateway()
    agent = ClientAgent(faithful)
    asyncio.run(
        ClientSimulator(agent, policy=FaithfulPatientActPolicy(agent)).respond(
            turn_input(profile)
        )
    )
    trust_step = next(
        payload for name, payload in faithful.calls if name == "trust"
    )
    assert trust_step["attachment_conditioning"]["pattern"] == "anxious"


def test_trust_anchors_and_neutral_attachment_rule_are_in_both_decision_prompts(sample_case):
    rendered = render_prompt(
        CLIENT_PLANNER_TEMPLATE,
        private_client_profile={},
        simulation_state={},
        counselor_message="",
        recent_messages=[],
        disclosure_decision={"retrieved": [], "blocked": []},
        recent_signals=[],
        turn_index=1,
    )
    for text in (rendered, FAITHFUL_PROMPT):
        for anchor in ("0.00-0.20", "0.35-0.50", "0.85-1.00"):
            assert anchor in text
        assert "attachment_conditioning 为空" in text
        assert "披露许可" in text
    for pattern in ("anxious", "avoidant", "disorganized"):
        assert f"- {pattern}：" in FAITHFUL_PROMPT
        assert f"- {pattern}：" not in rendered
    evidence_id = sample_case.profile.evidence_nodes[0].evidence_id
    sourced = _planner_payload(_conditioned(
        sample_case, attachment_pattern="anxious",
        source_fact_ids=[evidence_id], confidence=0.9,
    ))
    sourced_render = render_prompt(CLIENT_PLANNER_TEMPLATE, **sourced)
    assert "- anxious：" in sourced_render
    assert "attachment_conditioning 为空" not in sourced_render
    assert "只调节 trust_change" in sourced_render
