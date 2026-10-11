import asyncio
import json

import pytest

from psychsandbox.datasets.profile_compiler import AtomicSpan, PsychEvalProfileCompiler
from psychsandbox.datasets.psycheval import PsychEvalAdapter
from psychsandbox.domain import ClientState, TrustTier
from psychsandbox.runtime.disclosure import DisclosureGate


def test_converted_cbt_meaning_requires_its_own_event():
    parts = PsychEvalProfileCompiler().compile(
        case_id="test", therapy_code="cbt", plans=[],
        info={"special_situations": [
            {"event": "同事拒绝了我的建议", "automatic_thoughts": "我觉得自己没有价值"},
            {"event": "考试未通过", "automatic_thoughts": "我觉得自己无法胜任"},
        ]},
    )
    first_event, first_thought, second_event, second_thought = parts.disclosure_items
    assert first_event.depends_on == second_event.depends_on == []
    assert first_thought.depends_on == [first_event.item_id]
    assert second_thought.depends_on == [second_event.item_id]


def test_fallback_evidence_is_not_retrievable_even_without_trust_gating():
    case = PsychEvalAdapter(therapy_code="cbt").convert_case({
        "client_id": "test", "client_info": {"growth_experiences": ["一次失败后我感到羞耻"]},
        "sessions": [],
    }, source_path="test")
    assert any(node.needs_review for node in case.profile.evidence_nodes)
    result = DisclosureGate().evaluate(
        case.profile, ClientState(trust=1), "失败经历", set(), use_trust_gating=False,
    )
    assert result.retrieved == []
    assert result.activated_fact_ids == []


def test_converted_sensitive_atom_has_private_emotional_cost():
    text = "实习失败。"
    parts = PsychEvalProfileCompiler().compile(
        case_id="test", therapy_code="cbt", plans=[],
        info={"growth_experiences": [text]},
        free_text_spans={"client_info.growth_experiences[0]": [AtomicSpan(
            start=0, end=len(text), text=text, kind="event",
            activation_tags=("实习",), trust_tier=TrustTier.SENSITIVE,
        )]},
    )
    item = parts.disclosure_items[0]
    assert item.emotional_cost == 0.3
    assert item.content == text
    assert parts.evidence_nodes[0].source_text == text


@pytest.mark.parametrize("problem", [
    "没有焦虑，也不失眠", "否认抑郁、低落", "未出现明显的焦虑症状",
    "不再感到紧张", "无失眠", "并不觉得疲惫",
])
def test_initial_state_does_not_treat_negated_symptoms_as_present(problem):
    state = PsychEvalAdapter._initial_state({"main_problem": problem})
    assert state.arousal == 0.56
    assert state.valence == 0.38
    assert state.distress == 0.6


@pytest.mark.parametrize("problem", [
    "没有失眠，但仍然焦虑", "不是没有焦虑", "焦虑并不影响睡眠",
])
def test_initial_state_keeps_affirmed_symptoms(problem):
    assert PsychEvalAdapter._initial_state({"main_problem": problem}).arousal == 0.7


def test_empty_extractive_source_reports_missing_files(tmp_path):
    from psychsandbox.datasets.psycheval import convert_psycheval_extractive
    with pytest.raises(FileNotFoundError, match="No PsychEval files"):
        asyncio.run(convert_psycheval_extractive(
            tmp_path, tmp_path / "output", therapy="cbt", gateway=None,
        ))


def test_single_case_pilot_is_not_counted_three_times(tmp_path):
    from psychsandbox.datasets.psycheval import convert_psycheval_extractive
    source = tmp_path / "data" / "cbt"
    source.mkdir(parents=True)
    (source / "1.json").write_text(json.dumps({
        "client_id": "1", "client_info": {}, "sessions": [],
    }), encoding="utf-8")
    manifest = asyncio.run(convert_psycheval_extractive(
        tmp_path, tmp_path / "output", therapy="cbt", gateway=None,
    ))
    assert manifest["atomization_audit"]["pilot_cases"] == ["1"]



def test_initial_state_negation_does_not_cross_profile_fields():
    state = PsychEvalAdapter._initial_state({
        "main_problem": "没有焦虑", "core_demands": "缓解失眠",
    })
    assert state.arousal == 0.7
