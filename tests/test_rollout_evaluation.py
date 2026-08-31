from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from psychsandbox.domain import RFTConfig, RolloutAssessment, RolloutReward, SessionMemory, SessionRecord
from psychsandbox.evaluation.rollout import SessionRolloutEvaluator, compute_rollout_reward


COUNSELOR = (
    "counselor_alliance", "counselor_strategy", "counselor_goal_alignment", "counselor_safety",
)
CLIENT = ("client_engagement", "client_understanding", "client_agency")
DIMENSIONS = COUNSELOR + CLIENT + ("simulation_fidelity",)


class JudgeStub:
    """Return the supplied response without production parsing or fallback."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.fixture
def response():
    result = {}
    for name, score in zip(DIMENSIONS, (8, 7, 6, 9, 6, 5, 4, 8), strict=True):
        is_client = name in CLIENT
        result[name] = {
            "score": score,
            "evidence": [{
                "message_index": 4 if is_client else 2,
                "quote": "我想先试一次" if is_client else "可以按你的节奏",
            }],
            "reason": "有具体对话依据。",
        }
    result.update(safety_passed=True, safety_reason="尊重公开表达的边界。")
    return result


@pytest.fixture
def session():
    return SessionRecord.model_validate({
        "session_id": "PRIVATE_SESSION_ID", "session_index": 19,
        "plan": {
            "session_index": 19, "therapy": "cbt", "stage": "core_intervention",
            "objectives": ["共同选择下一步"], "strategy": "PRIVATE_PLAN",
            "persona_links": ["PRIVATE_PROFILE"], "case_materials": ["PRIVATE_MATERIAL"],
            "target_atomic_skill_ids": ["PRIVATE_SKILL"],
        },
        "initial_state": {"topic_readiness": {"PRIVATE_STATE": 0.5}},
        "final_state": {},
        "messages": [
            {"session_index": 19, "turn_index": index + 30, "role": role, "content": content}
            for index, (role, content) in enumerate([
                ("system", "PRIVATE_SYSTEM"),
                ("client", "我还有些担心。"),
                ("counselor", "可以按你的节奏，不必急着答应。"),
                ("system", "PRIVATE_INTERNAL_PLAN"),
                ("client", "我想先试一次，但现在不想多谈。\n  我仍有顾虑。"),
            ])
        ],
        "turn_records": [{"candidate_index": 8, "reasoning_summary": "PRIVATE_REASONING"}],
        "summary": "PRIVATE_SUMMARY", "end_reason": "PRIVATE_END_REASON",
        "supervisor_report": {
            "session_index": 19, "overall_score": 10, "metrics": [],
            "feedback": ["PRIVATE_SCORE"],
        },
    })


@pytest.fixture
def memory():
    return SessionMemory.model_validate({
        "case_id": "PRIVATE_CASE_ID", "completed_sessions": 18,
        "unlocked_profile": {
            "client_id": "PRIVATE_CLIENT_ID", "public_background": {"occupation": "教师"},
            "facts": [{
                "fact_id": "PRIVATE_FACT_ID", "content": "已经公开的工作压力",
                "evidence_session": 18, "evidence_turn": 2,
            }],
            "confirmed_goals": ["改善沟通"], "expressed_problems": ["紧张"],
        },
        "confirmed_goals": ["自主决定尝试"], "unresolved_topics": ["工作压力"],
        "homework": ["记录一次体验"], "last_client_closing": "下次再谈。",
        "summaries": ["PRIVATE_MEMORY_SUMMARY"],
        "supervisor_feedback": ["PRIVATE_PREVIOUS_SCORE"],
        "relationship_events": ["PRIVATE_TRUST_CHANGE"], "risk_history": ["PRIVATE_RISK_STATE"],
        "interventions_used": ["PRIVATE_SKILL_HISTORY"],
        "evolving_profile": {"client_id": "PRIVATE_EVOLVING_ID", "main_problem": "PRIVATE_INFERENCE"},
    })


def evaluate(response, session, memory, **config):
    gateway = JudgeStub(response)
    result = asyncio.run(SessionRolloutEvaluator(gateway, RFTConfig(**config)).evaluate(session, memory))
    return result, gateway


def test_first_reward_is_counselor_mean_and_keeps_client_snapshot(response):
    reward = compute_rollout_reward(RolloutAssessment.model_validate(response), None, RFTConfig())
    assert reward.total == reward.counselor_score == 7.5
    assert reward.client_snapshot == dict(zip(CLIENT, (6, 5, 4), strict=True))
    assert reward.client_delta is reward.client_gain_score is reward.baseline_session_index is None


@pytest.mark.parametrize("weight, expected", [(0.7, 6.9), (0.25, 6.0)])
def test_followup_uses_matching_client_deltas_and_explicit_baseline(response, weight, expected):
    previous = RolloutReward(
        total=1, counselor_score=1,
        client_snapshot={CLIENT[2]: 2, CLIENT[0]: 2, CLIENT[1]: 8},
        baseline_session_index=2,
    )
    assessment = RolloutAssessment.model_validate(response)
    reward = compute_rollout_reward(assessment, previous, RFTConfig(counselor_weight=weight),
                                    baseline_session_index=18)
    assert reward.counselor_score == 7.5
    assert reward.client_delta == 1  # mean(6-2, 5-8, 4-2)
    assert reward.client_gain_score == 5.5
    assert reward.total == pytest.approx(expected)
    assert reward.baseline_session_index == 18
    assert compute_rollout_reward(assessment, previous, RFTConfig()).baseline_session_index is None


@pytest.mark.parametrize("counselor, current, old, expected", [
    (0, 0, None, 0), (10, 10, None, 10),
    (0, 0, 10, 0), (10, 10, 0, 10),
    (0, 10, 0, 3), (10, 0, 10, 7), (10, 5, 5, 8.5),
])
def test_reward_boundaries_do_not_apply_safety_filter(response, counselor, current, old, expected):
    for name in COUNSELOR:
        response[name]["score"] = counselor
    for name in CLIENT:
        response[name]["score"] = current
    response["simulation_fidelity"]["score"] = 0
    response["safety_passed"] = False
    previous = None if old is None else RolloutReward(
        total=5, counselor_score=5, client_snapshot=dict.fromkeys(CLIENT, old),
    )
    reward = compute_rollout_reward(RolloutAssessment.model_validate(response), previous, RFTConfig())
    assert reward.total == pytest.approx(expected)


def test_judge_permissions_temperature_and_original_message_indices(response, session, memory):
    before = (session.model_dump(), memory.model_dump())
    assessment, gateway = evaluate(RolloutAssessment.model_validate(response), session, memory,
                                   judge_temperature=0.37)
    call, = gateway.calls
    assert call["role"] == "supervisor"
    assert call["temperature"] == 0.37
    assert call["output_schema"] is RolloutAssessment
    payload = call["input_payload"]
    assert set(payload) == {"dialogue", "plan", "memory"}
    assert payload["plan"] == {
        "stage": "core_intervention", "objectives": ["共同选择下一步"], "therapy": "cbt",
    }
    assert payload["dialogue"] == [
        {"message_index": i, "role": message.role, "content": message.content}
        for i, message in enumerate(session.messages) if message.role != "system"
    ]
    assert payload["memory"]["unlocked_client_info"]["facts"] == [
        {"content": "已经公开的工作压力"}
    ]
    assert "language_features" not in (
        payload["memory"]["unlocked_client_info"]["static_traits"]
    )
    assert payload["memory"]["homework"] == ["记录一次体验"]
    assert "PRIVATE_" not in json.dumps(payload)
    assert "PRIVATE_" not in call["system_prompt"]
    assert assessment.model_dump() == RolloutAssessment.model_validate(response).model_dump()
    assert before == (session.model_dump(), memory.model_dump())


def test_exact_multiline_quote_and_mixed_client_evidence_are_accepted(response, session, memory):
    response["client_agency"]["evidence"] = [
        {"message_index": 2, "quote": "可以按你的节奏"},
        {"message_index": 4, "quote": "但现在不想多谈。\n  我仍有顾虑。"},
    ]
    assessment, _ = evaluate(response, session, memory)
    assert assessment.client_agency.evidence[1].quote == "但现在不想多谈。\n  我仍有顾虑。"


@pytest.mark.parametrize("index, quote", [
    (4, "我已经完全好了"), (1, "我想先试一次"), (0, "PRIVATE_SYSTEM"),
    (3, "PRIVATE_INTERNAL_PLAN"), (99, "我想先试一次"), (-1, "我想先试一次"),
    (4, ""), (4, "  "), (4, "不想多谈。\n我仍有顾虑。"),
])
def test_invalid_evidence_is_rejected_without_repair(response, session, memory, index, quote):
    response["client_agency"]["evidence"] = [{"message_index": index, "quote": quote}]
    original = deepcopy(response)
    gateway = JudgeStub(response)
    with pytest.raises(ValueError):
        asyncio.run(SessionRolloutEvaluator(gateway, RFTConfig()).evaluate(session, memory))
    assert len(gateway.calls) == 1
    assert response == original


@pytest.mark.parametrize("name", CLIENT)
def test_each_client_dimension_requires_client_role(response, session, memory, name):
    response[name]["evidence"] = [{"message_index": 2, "quote": "可以按你的节奏"}]
    with pytest.raises(ValueError, match="client evidence"):
        evaluate(response, session, memory)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf"), -0.1, 10.1, True, "8"])
def test_invalid_scores_are_rejected(response, session, memory, score):
    response["counselor_strategy"]["score"] = score
    with pytest.raises(ValueError):
        evaluate(response, session, memory)


@pytest.mark.parametrize("path", [(name,) for name in DIMENSIONS] + [
    ("safety_passed",), ("safety_reason",),
    ("counselor_alliance", "score"), ("counselor_alliance", "evidence"),
    ("counselor_alliance", "reason"),
])
def test_missing_fields_are_rejected(response, session, memory, path):
    target = response if len(path) == 1 else response[path[0]]
    del target[path[-1]]
    with pytest.raises(ValueError):
        evaluate(response, session, memory)


@pytest.mark.parametrize("count", [0, 4])
def test_evidence_count_is_bounded(response, session, memory, count):
    response["counselor_alliance"]["evidence"] *= count
    with pytest.raises(ValueError):
        evaluate(response, session, memory)


@pytest.mark.parametrize("snapshot", [{}, dict.fromkeys(CLIENT, float("nan")), dict.fromkeys(CLIENT, 11)])
def test_invalid_previous_snapshot_is_rejected(response, snapshot):
    previous = RolloutReward(total=5, counselor_score=5, client_snapshot=snapshot)
    with pytest.raises(ValueError):
        compute_rollout_reward(RolloutAssessment.model_validate(response), previous, RFTConfig())
