from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from psychsandbox.agents import ClientAgent, CounselorAgent
from psychsandbox.agents.client import CLIENT_PROMPT_VERSION
from psychsandbox.client_simulation.prompts import (
    CLIENT_PLANNER_TEMPLATE,
    CLIENT_PROMPT_VERSION as CANONICAL_CLIENT_PROMPT_VERSION,
    CLIENT_UTTERANCE_TEMPLATE,
)
from psychsandbox.prompts import render_prompt
from psychsandbox.domain import (
    AtomicSkill,
    BlockedMemorySignal,
    ClientBehaviorType,
    ClientGeneration,
    ClientState,
    ClientTurnSignal,
    ClientUtterance,
    CounselorAction,
    CounselorActorOutput,
    CounselorDecision,
    CounselorPlanning,
    CounselorTurn,
    DisclosureDecision,
    HiddenFact,
    MetaSkill,
    RiskAssessment,
    RiskLevel,
    TrustChange,
    SessionMemory,
    SessionStage,
    SkillSelectionConfig,
    SkillSelectionEvidence,
    UnlockedFact,
    UnlockedClientProfile,
)
from tests.deterministic_gateway import DeterministicGateway
from psychsandbox.runtime import DisclosureGate, StateUpdater
from psychsandbox.runtime.leakage import PrematureDisclosureGuard
from psychsandbox.skills import SkillCatalog, SkillRegistry
from psychsandbox.skills.selection import SkillCandidateFilter


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
    profile = sample_case.profile.model_copy(
        update={
            "hidden_facts": [
                fact.model_copy(update={"activation_tags": ["唯一敏感话题"]})
            ]
        }
    )
    state = sample_case.profile.initial_state.model_copy(update={"trust": 0})
    decision = DisclosureGate().evaluate(
        profile,
        state,
        "我想问问唯一敏感话题",
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


def test_disclosure_advances_one_layer_at_a_time(sample_case):
    fact = sample_case.profile.hidden_facts[0].model_copy(
        update={
            "content": "表层信息；更私密的细节",
            "disclosure_layers": ["表层信息", "表层信息；更私密的细节"],
            "activation_tags": ["特定成长话题"],
            "topic_key": "specific_growth",
            "minimum_trust": 0.2,
            "minimum_topic_readiness": 0.3,
        }
    )
    profile = sample_case.profile.model_copy(update={"hidden_facts": [fact]})
    state = sample_case.profile.initial_state.model_copy(
        update={"trust": 0.8, "topic_readiness": {"specific_growth": 0.8}}
    )
    gate = DisclosureGate()

    first = gate.evaluate(profile, state, "想谈特定成长话题", {})
    second = gate.evaluate(profile, state, "继续谈特定成长话题", {fact.fact_id: 1})
    finished = gate.evaluate(profile, state, "继续谈特定成长话题", {fact.fact_id: 2})

    assert first.retrieved[0].content == "表层信息"
    assert first.retrieved[0].disclosure_level == 1
    assert second.retrieved[0].content == "表层信息；更私密的细节"
    assert second.retrieved[0].disclosure_level == 2
    assert finished.retrieved == []


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
    assert set(delta) == {
        "rule_delta",
        "model_signal_delta",
        "interaction_features",
    }


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
    assert increased.trust == 0.53


def test_skill_parent_child_integrity(root):
    asset_files = list((root / "assets" / "skills" / "sect").rglob("*.*"))
    hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in asset_files}
    registry = SkillRegistry.from_project(root)
    assert all(
        skill.meta_skill_id in registry.meta_skills
        for skill in registry.atomic_skills.values()
    )
    assert len(registry.meta_skills) == 677
    assert len(registry.atomic_skills) == 4481
    skill = registry.atomic_skills["psychagent:bt:skill:253"]
    assert skill.paths[SessionStage.CONCEPTUALIZATION.value] == (
        "bt / stage1 / 评估性会谈 [285] / 行为的观察与记录 [148] / "
        "行为记录 [151] / 使用频率记录（连续记录法） [253]"
    )
    for item in registry.atomic_skills.values():
        assert set(item.paths) == {stage.value for stage in item.stages}
        assert "brief_description" not in item.model_dump()
    assert hashes == {path: hashlib.sha256(path.read_bytes()).digest() for path in asset_files}


def test_skill_catalog_observes_selected_meta_without_ranking(root, sample_case):
    registry = SkillRegistry.from_project(root)
    catalog = SkillCatalog(registry)
    risk = RiskAssessment(level=RiskLevel.LOW)
    meta = catalog.available_meta(plan=sample_case.global_plan[0], risk=risk)
    observation = catalog.observe(
        plan=sample_case.global_plan[0],
        risk=risk,
        action=CounselorAction.LOOKUP_SKILLS,
        selected_meta_skill_ids=[meta[0].meta_skill_id],
    )

    assert meta
    assert all(0 < len(item.selection_hint) <= 180 for item in meta)
    assert all(not item.selection_hint for item in registry.meta_skills.values())
    assert observation.status == "skills_found"
    assert observation.selected_meta_skill_ids == [meta[0].meta_skill_id]
    assert observation.atomic_skills
    assert all(
        item.meta_skill_id == meta[0].meta_skill_id
        for item in observation.atomic_skills
    )


def test_high_risk_catalog_returns_no_skills(root, sample_case):
    registry = SkillRegistry.from_project(root)
    result = SkillCatalog(registry).available_meta(
        plan=sample_case.global_plan[0],
        risk=RiskAssessment(level=RiskLevel.HIGH),
    )
    assert result == []


def test_counselor_payload_has_no_full_profile(sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    payload = CounselorAgent(DeterministicGateway()).build_context_payload(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="你好",
        recent_messages=[],
        risk=RiskAssessment(level=RiskLevel.LOW),
        counselor_turn_count=0,
    )
    dumped = str(payload)
    assert "full_client_profile" not in payload
    for fact in sample_case.profile.hidden_facts:
        assert fact.content not in dumped


def test_counselor_uses_plan_then_react_observation(root, sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    gateway = CountingDeterministicGateway()
    result = asyncio.run(CounselorAgent(
        gateway,
        SkillCatalog(SkillRegistry.from_project(root)),
    ).respond(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="我很焦虑",
        recent_messages=[],
        risk=RiskAssessment(level=RiskLevel.LOW),
        counselor_turn_count=0,
    ))
    assert result.response
    assert gateway.calls == [CounselorPlanning, CounselorActorOutput]
    assert result.planning.action is CounselorAction.LOOKUP_SKILLS
    assert result.observation.status == "skills_found"
    assert result.decision.selected_atomic_skill_ids
    actor_skills = gateway.requests[1]["input_payload"]["observation"]["atomic_skills"]
    assert all(item["paths"] and "brief_description" not in item for item in actor_skills)


def test_high_risk_counselor_routes_to_safety(sample_case):
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
    )
    result = asyncio.run(CounselorAgent(DeterministicGateway()).respond(
        memory=memory,
        plan=sample_case.global_plan[0],
        client_message="我想自杀",
        recent_messages=[],
        risk=RiskAssessment(level=RiskLevel.HIGH),
        counselor_turn_count=0,
    ))
    assert "安全" in result.response


class CountingDeterministicGateway(DeterministicGateway):
    def __init__(self):
        self.calls = []
        self.requests = []

    async def complete_structured(self, **kwargs):
        self.calls.append(kwargs["output_schema"])
        self.requests.append(kwargs)
        return await super().complete_structured(**kwargs)


@pytest.fixture
def selection_catalog(sample_case):
    plan = sample_case.global_plan[0]
    meta = [MetaSkill(
        meta_skill_id=f"group-{group}", name=f"技能组{group}", description="探索具体困扰",
        therapy=plan.therapy, stages=[plan.stage],
    ) for group in range(3)]
    atomic = [AtomicSkill(
        skill_id=f"skill-{group}-{index}", name=f"技能{group}-{index}",
        description=f"探索困扰的具体场景{index}", when_to_use="愿意讨论具体的焦虑场景时",
        therapy=plan.therapy, stages=[plan.stage], meta_skill_id=f"group-{group}",
    ) for group in range(3) for index in range(3)]
    return SkillCatalog(SkillRegistry(meta, atomic))


class SkillQueryGateway(CountingDeterministicGateway):
    def __init__(self, assessments=("suitable",), *, invalid_first=False, replay_first=False):
        super().__init__()
        self.assessments = iter(assessments)
        self.invalid_first = invalid_first
        self.replay_first = replay_first
        self.first_planning = None
        self.embedding_requests = []

    async def complete_structured(self, **kwargs):
        result = await super().complete_structured(**kwargs)
        if kwargs["output_schema"] is CounselorPlanning:
            if self.first_planning is None:
                self.first_planning = result.model_copy(deep=True)
                if self.invalid_first:
                    result.selection_evidence[0].evidence_quote = "未披露的秘密事件"
            elif self.replay_first:
                result.selected_meta_skill_ids += self.first_planning.selected_meta_skill_ids
                result.selection_evidence += self.first_planning.selection_evidence
        elif kwargs["output_schema"] is CounselorActorOutput:
            result.query_assessment = next(self.assessments)
            if result.query_assessment == "unsuitable":
                result.query_rejection_reason = "候选集中于行为记录，本轮需要探索关系冲突。"
        return result

    async def embed_texts(self, texts):
        self.embedding_requests.append(texts)
        return await super().embed_texts(texts)


def _run_skill_query(gateway, catalog, sample_case, config=None):
    return asyncio.run(CounselorAgent(
        gateway, catalog, skill_selection=config,
    ).respond(
        memory=SessionMemory(
            case_id=sample_case.case_id,
            unlocked_profile=UnlockedClientProfile(client_id=sample_case.profile.client_id),
        ),
        plan=sample_case.global_plan[0], client_message="我很焦虑，想谈谈具体的困扰",
        recent_messages=[], risk=RiskAssessment(level=RiskLevel.LOW), counselor_turn_count=0,
    ))


@pytest.mark.parametrize("assessment", ["suitable", "needs_clarification", "not_needed"])
def test_skill_query_does_not_retry_without_rejected_candidates(
    selection_catalog, sample_case, assessment,
):
    gateway = SkillQueryGateway((assessment,))
    turn = _run_skill_query(gateway, selection_catalog, sample_case)
    assert gateway.calls == [CounselorPlanning, CounselorActorOutput]
    assert len(turn.skill_queries) == 1
    assert turn.skill_queries[0].assessment == assessment
    assert bool(turn.decision.selected_atomic_skill_ids) == (assessment == "suitable")
    assert not gateway.embedding_requests


@pytest.mark.parametrize("second_assessment", ["suitable", "unsuitable"])
def test_rejected_query_retries_once_and_excludes_entire_previous_group(
    selection_catalog, sample_case, second_assessment,
):
    gateway = SkillQueryGateway(("unsuitable", second_assessment), replay_first=True)
    turn = _run_skill_query(
        gateway, selection_catalog, sample_case,
        SkillSelectionConfig(vector_threshold=2, vector_top_k=1),
    )
    assert gateway.calls == [CounselorPlanning, CounselorActorOutput] * 2
    first, second = turn.skill_queries
    assert first.rejection_reason
    assert first.assessment == "unsuitable"
    assert second.assessment == second_assessment
    assert not set(first.candidate_skill_ids) & set(second.candidate_skill_ids)
    assert len(first.candidate_skill_ids) == len(second.candidate_skill_ids) == 3
    assert len(first.returned_skill_ids) == len(second.returned_skill_ids) == 1
    assert second.selection_warnings  # Replayed excluded ID was rejected in code.
    assert gateway.requests[2]["input_payload"]["previous_query_rejection"] == first.rejection_reason
    assert gateway.requests[3]["input_payload"]["query_retry_available"] is False
    embedding_query = json.loads(gateway.embedding_requests[0][0])
    assert embedding_query["current_client_message"] == "我很焦虑，想谈谈具体的困扰"
    for fact in sample_case.profile.hidden_facts:
        assert fact.content not in str(gateway.embedding_requests)


def test_ungrounded_planner_evidence_allows_only_one_correction(selection_catalog, sample_case):
    gateway = SkillQueryGateway(invalid_first=True)
    turn = _run_skill_query(gateway, selection_catalog, sample_case)
    assert gateway.calls == [CounselorPlanning, CounselorPlanning, CounselorActorOutput]
    assert turn.skill_queries[0].assessment == "invalid"
    assert "适用依据" in turn.skill_queries[0].rejection_reason
    assert not turn.skill_queries[0].candidate_skill_ids
    assert turn.decision.selected_atomic_skill_ids


@pytest.mark.parametrize("failure", ["outside_observation", "fabricated_evidence"])
def test_actor_selection_requires_returned_id_and_public_evidence(
    selection_catalog, sample_case, failure,
):
    class InvalidActorGateway(SkillQueryGateway):
        async def complete_structured(self, **kwargs):
            output = await super().complete_structured(**kwargs)
            if kwargs["output_schema"] is CounselorActorOutput:
                if failure == "outside_observation":
                    output.decision.selected_atomic_skill_ids = ["skill-2-2"]
                else:
                    output.decision.skill_evidence[0].evidence_quote = "未披露的秘密事件"
            return output

    turn = _run_skill_query(InvalidActorGateway(), selection_catalog, sample_case)
    assert not turn.decision.selected_atomic_skill_ids
    assert not turn.decision.skill_evidence
    assert turn.skill_queries[0].selection_warnings


def test_unsuitable_assessment_requires_reason():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="concrete rejection reason"):
        CounselorActorOutput(
            decision=CounselorDecision(assessment="a", state_observation="b", strategy="c"),
            response="请再说说", query_assessment="unsuitable",
        )


def _selection_observation(catalog, sample_case):
    return catalog.observe(
        plan=sample_case.global_plan[0], risk=RiskAssessment(level=RiskLevel.LOW),
        action=CounselorAction.LOOKUP_SKILLS, selected_meta_skill_ids=["group-0"],
    )


def test_vector_threshold_never_reads_embedding_config_for_small_queries(
    selection_catalog, sample_case,
):
    class NoEmbeddingsGateway(DeterministicGateway):
        @property
        def embedding_identity(self):
            raise AssertionError("Small queries must not inspect embedding configuration")

    observation = _selection_observation(selection_catalog, sample_case)
    result = asyncio.run(SkillCandidateFilter(
        NoEmbeddingsGateway(), SkillSelectionConfig(vector_threshold=3, vector_top_k=2),
    ).narrow(observation, query="焦虑", stage=sample_case.global_plan[0].stage.value))
    assert result is observation


def test_vector_filter_ranks_cosine_and_caches_only_skill_vectors(selection_catalog, sample_case):
    class VectorGateway(DeterministicGateway):
        def __init__(self):
            self.requests = []

        async def embed_texts(self, texts):
            self.requests.append(texts)
            return [[1., 0.]] + [[0., 1.], [1., 1.], [2., 0.]][:len(texts) - 1]

    gateway = VectorGateway()
    candidate_filter = SkillCandidateFilter(gateway, SkillSelectionConfig(vector_threshold=2, vector_top_k=2))
    observation = _selection_observation(selection_catalog, sample_case)
    stage = sample_case.global_plan[0].stage.value
    first = asyncio.run(candidate_filter.narrow(observation, query="焦虑", stage=stage))
    assert [item.skill_id for item in first.atomic_skills] == ["skill-0-2", "skill-0-1"]
    assert first.similarity_scores["skill-0-2"] == pytest.approx(1.)
    assert first.vector_filtered and first.candidate_count == 3
    assert len(observation.atomic_skills) == 3
    asyncio.run(candidate_filter.narrow(observation, query="新的公开表达", stage=stage))
    assert gateway.requests[1] == ["新的公开表达"]
    candidate_filter.reset()
    asyncio.run(candidate_filter.narrow(observation, query="第三次", stage=stage))
    assert len(gateway.requests[2]) == 4


@pytest.mark.parametrize("vectors", [
    [[1., 0.]],
    [[1., 0.], [1.], [1., 0.], [1., 0.]],
    [[1., 0.], [0., 0.], [1., 0.], [1., 0.]],
    [[1., 0.], [float("nan"), 1.], [1., 0.], [1., 0.]],
])
def test_vector_filter_rejects_invalid_embeddings(selection_catalog, sample_case, vectors):
    class InvalidVectorGateway(DeterministicGateway):
        async def embed_texts(self, texts):
            return vectors

    candidate_filter = SkillCandidateFilter(
        InvalidVectorGateway(), SkillSelectionConfig(vector_threshold=2, vector_top_k=1),
    )
    with pytest.raises(ValueError, match="Embedding"):
        asyncio.run(candidate_filter.narrow(
            _selection_observation(selection_catalog, sample_case),
            query="焦虑", stage=sample_case.global_plan[0].stage.value,
        ))
    assert not candidate_filter._vectors


def test_client_prompts_are_versioned_and_reexported():
    assert CLIENT_PROMPT_VERSION == "psycheval_patientact_v4"
    assert CLIENT_PROMPT_VERSION == CANONICAL_CLIENT_PROMPT_VERSION
    assert CLIENT_PLANNER_TEMPLATE == "simclient/planner_system.jinja2"
    assert CLIENT_UTTERANCE_TEMPLATE == "simclient/utterance_system.jinja2"


def test_client_planner_prompt_contract():
    required_rules = (
        "private_client_profile",
        "disclosure_decision.retrieved",
        "rationale",
        "ambiguous_fact_ids",
        "优先选择 request",
        "不自动等于 resistance",
        "不得默认每轮线性改善",
        "不得因为多个事实标签相似",
        "只有确实出现防御、回避或表面配合时才选择 resistance",
        "显著变化必须有明确互动依据",
        "不生成来访者台词",
        "ClientTurnSignal",
    )
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
    assert all(rule in rendered for rule in required_rules)


def test_client_utterance_prompt_contract():
    payload_fields = (
        "static_profile",
        "simulation_state",
        "counselor_message",
        "recent_messages",
        "available_memories",
        "blocked_topics",
        "ambiguous_fact_ids",
        "turn_signal",
        "turn_index",
        "repair_instruction",
    )
    required_rules = (
        "被动、渐进披露",
        "不得编造",
        "不得提前扩展到更私密的层级",
        "不猜测咨询师指的是哪件事",
        "安全、具体的问题可以正常合作",
        "不要突然顿悟、痊愈、完全信任咨询师",
        "专业术语",
        "本轮 utterance 实际表达过",
        "ClientUtterance",
    )
    rendered = render_prompt(
        CLIENT_UTTERANCE_TEMPLATE,
        static_profile={},
        simulation_state={},
        counselor_message="最近怎么样？",
        recent_messages=[],
        available_memories=[],
        blocked_topics=[],
        ambiguous_fact_ids=[],
        turn_signal={},
        turn_index=1,
        known_memories=[],
        repair_instruction="",
    )
    assert all(field in rendered for field in payload_fields)
    assert all(rule in rendered for rule in required_rules)
    assert "private_client_profile" not in rendered
    assert "session_goals" not in rendered
    assert "suggested_skills" not in rendered
    assert "响应外层仍必须是 ClientUtterance JSON" in rendered
    assert "不要输出 JSON、XML、项目符号或解释。" not in rendered


def test_client_two_stage_calls_and_strict_utterance_payload(sample_case):
    gateway = CountingDeterministicGateway()
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
    assert "ClientTurnSignal" in gateway.requests[0]["system_prompt"]
    assert "ClientUtterance" in gateway.requests[1]["system_prompt"]
    assert generation.utterance
    assert metadata["retry_count"] == 0
    assert "session_plan" not in payload
    assert "growth_experiences" not in dumped
    assert "special_situations" not in dumped
    for fact in sample_case.profile.hidden_facts:
        assert fact.content not in dumped


def test_ambiguous_facts_request_clarification_without_disclosure(sample_case):
    facts = sample_case.profile.hidden_facts[:2]
    disclosure = DisclosureDecision(
        retrieved=facts,
        ambiguous_fact_ids=[fact.fact_id for fact in facts],
    )
    agent = ClientAgent(DeterministicGateway())
    signal = asyncio.run(
        agent.plan_turn(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="你说的那段过去，当时发生了什么？",
            recent_messages=[],
            disclosure=disclosure,
            recent_signals=[],
            turn_index=1,
        )
    )
    generation, _ = asyncio.run(
        agent.generate_utterance(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="你说的那段过去，当时发生了什么？",
            recent_messages=[],
            disclosure=disclosure,
            signal=signal,
            already_disclosed_ids=set(),
            turn_index=1,
        )
    )

    assert signal.behavior is ClientBehaviorType.REQUEST
    assert "具体" in generation.utterance
    assert generation.disclosed_fact_ids == []
    assert all(fact.content not in generation.utterance for fact in facts)


def test_ordinary_follow_up_does_not_change_trust(sample_case):
    signal = asyncio.run(
        ClientAgent(DeterministicGateway()).plan_turn(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="最近怎么样？",
            recent_messages=[],
            disclosure=DisclosureDecision(),
            recent_signals=[],
            turn_index=1,
        )
    )

    assert signal.trust_change is TrustChange.UNCHANGED


class SelectivePlannerGateway(DeterministicGateway):
    def __init__(self, selected_fact_id):
        self.selected_fact_id = selected_fact_id

    async def complete_structured(self, **kwargs):
        if kwargs["output_schema"] is ClientTurnSignal:
            return ClientTurnSignal(retrieved_fact_ids=[self.selected_fact_id])
        return await super().complete_structured(**kwargs)


def test_planner_fact_selection_constrains_utterance_payload(sample_case):
    facts = sample_case.profile.hidden_facts[:2]
    agent = ClientAgent(SelectivePlannerGateway(facts[0].fact_id))
    disclosure = DisclosureDecision(retrieved=facts)
    signal = asyncio.run(
        agent.plan_turn(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="请说一件最相关的经历。",
            recent_messages=[],
            disclosure=disclosure,
            recent_signals=[],
            turn_index=1,
        )
    )
    payload = agent.build_utterance_payload(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="请说一件最相关的经历。",
        recent_messages=[],
        disclosure=disclosure,
        signal=signal,
        turn_index=1,
    )

    assert signal.retrieved_fact_ids == [facts[0].fact_id]
    assert [item["fact_id"] for item in payload["available_memories"]] == [
        facts[0].fact_id
    ]


class UnsupportedDisclosureGateway(DeterministicGateway):
    def __init__(self, fact_id):
        self.fact_id = fact_id

    async def complete_structured(self, **kwargs):
        if kwargs["output_schema"] is ClientUtterance:
            return ClientUtterance(
                utterance="我今天只是有点累。",
                disclosed_fact_ids=[self.fact_id],
            )
        return await super().complete_structured(**kwargs)


def test_unspoken_fact_id_is_not_accepted_as_disclosure(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    agent = ClientAgent(UnsupportedDisclosureGateway(fact.fact_id))
    generation, metadata = asyncio.run(
        agent.generate_utterance(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="可以说说吗？",
            recent_messages=[],
            disclosure=DisclosureDecision(retrieved=[fact]),
            signal=ClientTurnSignal(retrieved_fact_ids=[fact.fact_id]),
            already_disclosed_ids=set(),
            turn_index=1,
        )
    )

    assert generation.disclosed_fact_ids == []
    assert metadata["attempts"][0]["unsubstantiated_fact_ids"] == [fact.fact_id]
    assert metadata["disclosed_evidence"] == {}


def test_disclosure_memory_uses_spoken_evidence_not_full_layer(sample_case):
    fact = sample_case.profile.hidden_facts[0].model_copy(
        update={
            "content": "表层经历；更私密的意义",
            "disclosure_layers": ["表层经历；更私密的意义"],
        }
    )
    confirmed, rejected, evidence = PrematureDisclosureGuard().substantiate(
        "我现在能说的是表层经历。",
        [fact.fact_id],
        [fact],
    )
    unlocked = DisclosureGate().unlock(
        sample_case.profile.model_copy(update={"hidden_facts": [fact]}),
        confirmed,
        session_index=1,
        turn_index=2,
        retrieved_facts=[fact],
        evidence_by_fact_id=evidence,
    )

    assert rejected == []
    assert unlocked[0].content == "表层经历"
    assert "更私密" not in unlocked[0].content


def test_known_memories_are_available_without_being_new_disclosures(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    known = UnlockedFact(
        fact_id=fact.fact_id,
        content="这是我上次已经说过的部分。",
        evidence_session=1,
        evidence_turn=2,
        disclosure_level=len(fact.disclosure_layers),
    )
    payload = ClientAgent(DeterministicGateway()).build_utterance_payload(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="上次那件事后来怎么样？",
        recent_messages=[],
        disclosure=DisclosureDecision(),
        signal=ClientTurnSignal(),
        turn_index=1,
        known_memories=[known],
    )

    assert payload["available_memories"] == []
    assert payload["known_memories"][0]["content"] == known.content


def test_known_evidence_does_not_authorize_unspoken_same_layer_detail(sample_case):
    fact = sample_case.profile.hidden_facts[0].model_copy(
        update={
            "content": "我说过的表层经历；我没有说过的私密意义",
            "disclosure_layers": ["我说过的表层经历；我没有说过的私密意义"],
        }
    )
    unauthorized = ClientAgent(DeterministicGateway())._unauthorized_remainders(
        [fact],
        {},
        ["我说过的表层经历"],
    )

    assert len(unauthorized) == 1
    assert "私密意义" in unauthorized[0].content
    assert "表层经历" not in unauthorized[0].content


def test_public_main_problem_is_not_treated_as_private_leak(repository):
    case = repository.get("psycheval-cbt-020")
    agent = ClientAgent(DeterministicGateway())
    unauthorized = agent._unauthorized_remainders(
        case.profile.hidden_facts,
        {},
        agent._public_authorized_texts(case.profile, []),
    )
    result = PrematureDisclosureGuard().inspect(
        case.profile.main_problem,
        [],
        unauthorized,
        set(),
    )

    assert result.leaked is False


def test_close_paraphrase_has_fuzzy_leak_signal():
    fact = HiddenFact(
        fact_id="semantic",
        content="小学时父亲经常把我关在门外罚站",
    )
    result = PrematureDisclosureGuard().inspect(
        "小学的时候父亲总把我关在门外罚站。",
        [],
        [fact],
        set(),
    )

    assert result.leaked is True
    assert any(
        reason.startswith("fuzzy_clause:")
        for reason in result.matches[fact.fact_id]
    )


def test_cross_category_overlap_selects_one_best_fact(sample_case):
    state = sample_case.profile.initial_state.model_copy(
        update={
            "trust": 1.0,
            "topic_readiness": {
                fact.topic_key: 1.0 for fact in sample_case.profile.hidden_facts
            },
        }
    )
    decision = DisclosureGate().evaluate(
        sample_case.profile,
        state,
        "实习工作时发生了什么？",
        {},
    )

    assert [fact.fact_id for fact in decision.retrieved] == [
        "psycheval-cbt-001:situation:1"
    ]


def test_trust_signal_is_not_double_counted_by_text_markers():
    state = ClientState(trust=0.5)
    counselor = CounselorTurn(
        decision=CounselorDecision(
            assessment="a", state_observation="b", strategy="c"
        ),
        response="不着急，我们按你的节奏，也可以先不谈。",
    )
    updated, features = StateUpdater().update(
        state,
        counselor,
        ClientGeneration(utterance="好。"),
        ClientTurnSignal(trust_change=TrustChange.SLIGHT_INCREASE),
    )

    assert updated.trust == 0.53
    assert features["interaction_features"]["respected_boundary"] == 1.0


class AlwaysLeakingGateway(DeterministicGateway):
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
    blocked = DisclosureDecision(
        blocked=[
            BlockedMemorySignal(
                fact_id=fact.fact_id,
                category=fact.category,
                sensitivity=fact.sensitivity,
            )
        ]
    )
    agent = ClientAgent(DeterministicGateway())
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


def test_blocked_memory_does_not_force_resistance_without_pressure(sample_case):
    fact = sample_case.profile.hidden_facts[0]
    disclosure = DisclosureDecision(
        blocked=[
            BlockedMemorySignal(
                fact_id=fact.fact_id,
                category=fact.category,
                sensitivity=fact.sensitivity,
            )
        ]
    )
    signal = asyncio.run(
        ClientAgent(DeterministicGateway()).plan_turn(
            profile=sample_case.profile,
            state=sample_case.profile.initial_state,
            counselor_message="如果你愿意，可以只说现在能说的部分。",
            recent_messages=[],
            disclosure=disclosure,
            recent_signals=[],
            turn_index=1,
        )
    )
    assert signal.behavior is ClientBehaviorType.REQUEST
    assert signal.resistance_pattern is None


def test_client_pulls_back_after_consecutive_exploration(sample_case):
    agent = ClientAgent(DeterministicGateway(), pullback_after=2)
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
