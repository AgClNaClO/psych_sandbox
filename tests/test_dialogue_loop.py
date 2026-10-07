from __future__ import annotations

import asyncio

import pytest

from psychsandbox.agents import CounselorAgent
from psychsandbox.domain import (
    ClientBehaviorType,
    ClientState,
    ClientTurnSignal,
    CounselorAction,
    DisclosureItem,
    RiskAssessment,
    RiskLevel,
    SandboxConfig,
    SessionMemory,
    TrustTier,
    UnlockedClientInfo,
)
from psychsandbox.runtime import (
    CounselingSandbox,
    DialogueLoopGuard,
    DisclosureGate,
    SemanticActivationMatcher,
)
from psychsandbox.runtime.dialogue_guard import (
    IDLE_REASON_REPEATED_CONTENT,
    IDLE_REASON_SIMPLE_RESPONSE,
    IDLE_REASON_WITHDRAWAL,
)
from psychsandbox.runtime.disclosure import (
    TagActivationMatcher,
    create_activation_matcher,
)
from tests.deterministic_gateway import (
    DISABLED_LOGPROB_SCORING,
    DeterministicGateway,
)


def _memory_for(sample_case) -> SessionMemory:
    return SessionMemory(
        case_id=sample_case.case_id,
        known_background=UnlockedClientInfo(
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
            logprob_scoring=DISABLED_LOGPROB_SCORING,
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


def _client(text: str) -> dict:
    return {"role": "client", "content": text}


def _counselor(text: str) -> dict:
    return {"role": "counselor", "content": text}


def test_repeated_minimal_client_turns_are_detected_as_idling():
    history = [
        _counselor("我们谈谈这周的情况。"),
        _client("我不知道。"),
        _counselor("那睡眠呢？"),
        _client("没什么。"),
        _counselor("上周有没有变化？"),
    ]
    signal = DialogueLoopGuard().inspect_client_idling("我不知道。", history)
    assert signal.detected
    assert signal.observed_client_turns == 3
    assert IDLE_REASON_REPEATED_CONTENT in signal.reasons
    assert IDLE_REASON_WITHDRAWAL in signal.reasons
    assert IDLE_REASON_SIMPLE_RESPONSE not in signal.reasons


def test_single_idling_cue_does_not_trigger_a_repair():
    history = [
        _counselor("最近怎么样？"),
        _client("我不知道。"),
        _counselor("那从最近的一天说起？"),
        _client("没什么。"),
        _counselor("周三呢？"),
    ]
    signal = DialogueLoopGuard().inspect_client_idling("都行吧。", history)
    assert signal.observed_client_turns == 3
    assert signal.reasons == (IDLE_REASON_WITHDRAWAL,)
    assert not signal.detected
    unrelated = DialogueLoopGuard().inspect_client_idling(
        "周三去看了朋友。",
        [
            _counselor("最近怎么样？"),
            _client("我不知道。"),
            _counselor("那从最近的一天说起？"),
            _client("周一开了会。"),
            _counselor("会上发生了什么？"),
        ],
    )
    assert unrelated.reasons == ()
    assert not unrelated.detected


def test_consecutive_simple_responses_alone_do_not_repair():
    guard = DialogueLoopGuard()
    signals = [
        ClientTurnSignal(behavior=ClientBehaviorType.COGNITIVE_EXPLORATION),
        ClientTurnSignal(behavior=ClientBehaviorType.SIMPLE_RESPONSE),
        ClientTurnSignal(behavior=ClientBehaviorType.SIMPLE_RESPONSE),
    ]
    history = [
        _counselor("周一发生了什么？"),
        _client("周一开了会。"),
        _counselor("周二呢？"),
        _client("周二在家休息。"),
        _counselor("周三呢？"),
    ]
    signal = guard.inspect_client_idling("周三去看了朋友。", history, signals)
    assert signal.reasons == (IDLE_REASON_SIMPLE_RESPONSE,)
    assert not signal.detected
    combined = guard.inspect_client_idling(
        "都行吧。",
        [
            _counselor("周一发生了什么？"),
            _client("没什么。"),
            _counselor("周二呢？"),
            _client("我不知道。"),
            _counselor("周三呢？"),
        ],
        signals,
    )
    assert combined.detected
    assert combined.reasons == (IDLE_REASON_SIMPLE_RESPONSE, IDLE_REASON_WITHDRAWAL)


def test_idling_requires_enough_observed_client_turns():
    history = [_counselor("最近？"), _client("我不知道。")]
    signal = DialogueLoopGuard().inspect_client_idling("没什么。", history)
    assert signal.observed_client_turns == 2
    assert not signal.detected


def test_idle_client_gets_a_direction_change_not_another_probe(sample_case):
    history = [
        _counselor("我们谈谈这周的情况。"),
        _client("我不知道。"),
        _counselor("那睡眠呢？"),
        _client("没什么。"),
        _counselor("上周有没有变化？"),
    ]
    result = asyncio.run(
        CounselorAgent(DeterministicGateway()).respond(
            memory=_memory_for(sample_case),
            plan=sample_case.global_plan[0],
            client_message="我不知道。",
            recent_messages=history,
            risk=RiskAssessment(level=RiskLevel.LOW),
            counselor_turn_count=3,
            recent_signals=[
                ClientTurnSignal(behavior=ClientBehaviorType.SIMPLE_RESPONSE)
            ] * 2,
        )
    )
    assert result.response == DialogueLoopGuard.IDLE_REPAIR
    assert "空转" in result.decision.assessment
    assert IDLE_REASON_WITHDRAWAL in result.decision.state_observation
    assert result.decision.selected_atomic_skill_ids == []
    assert result.planning.action is CounselorAction.RESPOND_WITHOUT_SKILL


def test_repeated_idle_repair_hands_the_direction_back(sample_case):
    history = [
        _counselor("我们谈谈这周的情况。"),
        _client("我不知道。"),
        _counselor(DialogueLoopGuard.IDLE_REPAIR),
        _client("没什么。"),
        _counselor("上周有没有变化？"),
    ]
    result = asyncio.run(
        CounselorAgent(DeterministicGateway()).respond(
            memory=_memory_for(sample_case),
            plan=sample_case.global_plan[0],
            client_message="我不知道。",
            recent_messages=history,
            risk=RiskAssessment(level=RiskLevel.LOW),
            counselor_turn_count=4,
        )
    )
    assert result.response == DialogueLoopGuard.IDLE_HANDOVER


def test_semantic_topic_matcher_recovers_variants_the_tag_matcher_misses(sample_case):
    item = DisclosureItem(
        item_id="coworker-relation",
        evidence_ids=["coworker-relation"],
        content="A private coworker conflict story.",
        activation_tags=["同事关系"],
        trust_tier=TrustTier.MODERATE,
    )
    profile = sample_case.profile.model_copy(update={"disclosure_items": [item]})
    text = "我想谈谈我和同事之间的关系模式。"
    state = ClientState(trust=0.5)
    default = DisclosureGate().evaluate(profile, state, text, set())
    semantic = DisclosureGate(SemanticActivationMatcher()).evaluate(
        profile, state, text, set()
    )
    assert default.activated_fact_ids == []
    assert semantic.activated_fact_ids == ["coworker-relation"]
    assert [entry.item_id for entry in semantic.retrieved] == ["coworker-relation"]
    assert semantic.activation_evidence["coworker-relation"] == ["同事关系"]
    gated = DisclosureGate(SemanticActivationMatcher()).evaluate(
        profile, ClientState(trust=0.1), text, set()
    )
    assert gated.activated_fact_ids == ["coworker-relation"]
    assert gated.retrieved == []


def test_semantic_matcher_keeps_the_low_information_guard(sample_case):
    item = DisclosureItem(
        item_id="vague", evidence_ids=["vague"], content="x", activation_tags=["关系"]
    )
    assert sample_case.case_id
    matcher = SemanticActivationMatcher()
    assert matcher.match("我们能谈谈同事关系吗？", item) == []
    assert matcher.match("", item) == []
    paired = item.model_copy(update={"activation_tags": ["关系", "问题"]})
    assert matcher.match("我最近有一个关系上的问题", paired) == ["关系", "问题"]


def test_topic_matcher_selection_is_explicit_and_defaults_to_tags():
    assert isinstance(create_activation_matcher("tags"), TagActivationMatcher)
    assert isinstance(create_activation_matcher("semantic"), SemanticActivationMatcher)
    with pytest.raises(ValueError, match="activation matcher"):
        create_activation_matcher("llm")


def test_sandbox_builds_the_configured_topic_matcher(root, tmp_path, repository):
    sandbox = CounselingSandbox(
        SandboxConfig(
            project_root=root,
            max_turns_per_session=4,
            logprob_scoring=DISABLED_LOGPROB_SCORING,
            client_topic_matcher="semantic",
            database_path=tmp_path / "topic-matcher.sqlite3",
            trace_dir=tmp_path / "topic-matcher-traces",
        ),
        gateway=DeterministicGateway(),
        repository=repository,
    )
    assert isinstance(sandbox.disclosure.matcher, SemanticActivationMatcher)
    assert isinstance(DisclosureGate().matcher, TagActivationMatcher)
