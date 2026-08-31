from __future__ import annotations

import pytest
import json

from psychsandbox.datasets.psycheval import (
    CaseRepository,
    PsychEvalAdapter,
    _case_split,
    _files_digest,
    convert_psycheval,
)
from psychsandbox.datasets.profile_compiler import ATOMIZER_PROMPT_VERSION
from psychsandbox.runtime import DisclosureGate


def test_repository_rejects_stale_processed_without_raw_fallback(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "manifest.json").write_text(
        '{"profile_schema_version":"3","case_count":148}', encoding="utf-8"
    )
    (processed / "all.jsonl").write_text("", encoding="utf-8")

    repository = CaseRepository(processed, raw_data_dir=tmp_path / "raw")

    with pytest.raises(RuntimeError, match="schema-v4"):
        repository.list()


def _valid_manifest(root):
    return {
        "profile_schema_version": "4",
        "case_count": 341,
        "atomizer": "extractive",
        "atomizer_prompt_version": ATOMIZER_PROMPT_VERSION,
        "atomizer_model": "test-model",
        "therapy_counts": {"bt": 43, "cbt": 148, "het": 50, "pdt": 50, "pmt": 50},
        "therapies": {
            therapy: {
                "source_digest": _files_digest(sorted(
                    (root / "data" / therapy).glob("*.json"),
                    key=lambda path: int(path.stem),
                ))
            }
            for therapy in ("bt", "cbt", "het", "pdt", "pmt")
        },
    }


def test_repository_rejects_hidden_fact_record_even_with_current_manifest(root, tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "manifest.json").write_text(
        json.dumps(_valid_manifest(root)), encoding="utf-8"
    )
    (processed / "all.jsonl").write_text(
        json.dumps({"profile": {"schema_version": "4", "hidden_facts": []}}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="strict schema-v4"):
        CaseRepository(processed, raw_data_dir=root).list()


def test_repository_rejects_source_digest_mismatch(root, tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    manifest = _valid_manifest(root)
    manifest["therapies"]["cbt"]["source_digest"] = "stale"
    (processed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (processed / "all.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="source digest mismatch"):
        CaseRepository(processed, raw_data_dir=root).list()


def test_official_case_count(repository):
    assert len(repository.list("cbt")) == 148


def test_legacy_data_handler_cannot_create_non_atomic_processed_cache(tmp_path):
    from psychsandbox import cli

    args = cli.build_parser().parse_args(["data", "convert", "--therapy", "bt"])
    with pytest.raises(RuntimeError, match="atomic staging pipeline"):
        cli._data(args, tmp_path)
    assert not (tmp_path / "data" / "processed").exists()


@pytest.mark.parametrize(
    ("therapy_code", "expected_count"),
    [("bt", 43), ("cbt", 148), ("het", 50), ("pdt", 50), ("pmt", 50)],
)
def test_bundled_supported_source_counts(root, therapy_code, expected_count):
    assert len(list((root / "data" / therapy_code).glob("*.json"))) == expected_count


@pytest.mark.parametrize(
    ("therapy_code", "expected_count"),
    [("bt", 43), ("cbt", 148), ("het", 50), ("pdt", 50), ("pmt", 50)],
)
def test_converter_supports_each_therapy(
    root, tmp_path, therapy_code, expected_count
):
    output = tmp_path / therapy_code
    manifest = convert_psycheval(root, output, therapy=therapy_code)
    assert manifest["therapy"] == therapy_code
    assert manifest["case_count"] == expected_count
    assert (output / "all.jsonl").exists()
    assert sum(manifest["split_counts"].values()) == expected_count


def test_supported_raw_case_ids_are_unique(repository):
    case_ids = [case.case_id for case in repository.list()]
    assert len(case_ids) == 341
    assert len(case_ids) == len(set(case_ids))


def test_case_sessions_ordered(sample_case):
    assert [x.session_index for x in sample_case.global_plan] == list(
        range(1, len(sample_case.global_plan) + 1)
    )


def test_case_keeps_reference_sessions(sample_case):
    assert sample_case.reference_sessions


def test_split_is_case_deterministic():
    assert _case_split("psycheval-cbt-001") == _case_split("psycheval-cbt-001")


def test_raw_case_ids_are_scoped_by_therapy(repository):
    ids_by_code = {
        code: {case.case_id for case in repository.list(code)}
        for code in ("bt", "cbt", "het", "pdt", "pmt")
    }
    for code, case_ids in ids_by_code.items():
        assert all(case_id.startswith(f"psycheval-{code}-") for case_id in case_ids)
    for index, code in enumerate(ids_by_code):
        for other in list(ids_by_code)[index + 1 :]:
            assert ids_by_code[code].isdisjoint(ids_by_code[other])


@pytest.mark.parametrize(
    ("therapy_code", "expected_category"),
    [
        ("bt", "bt_target_behavior"),
        ("cbt", "cbt_special_situation"),
        ("het", "het_existential_topic"),
        ("pdt", "pdt_core_conflict"),
        ("pmt", "pmt_force_field"),
    ],
)
def test_each_therapy_builds_source_grounded_disclosure_items(
    repository, therapy_code, expected_category
):
    case = repository.get(f"psycheval-{therapy_code}-001")
    assert any(
        fact.category == expected_category for fact in case.profile.disclosure_items
    )
    evidence_ids = {item.evidence_id for item in case.profile.evidence_nodes}
    assert all(item.evidence_ids for item in case.profile.disclosure_items)
    assert all(
        set(item.evidence_ids).issubset(evidence_ids)
        for item in case.profile.disclosure_items
    )


def test_adapter_builds_source_grounded_atomic_memories():
    raw = {
        "client_id": 999,
        "client_info": {
            "static_traits": {"name": "测试来访者", "language_features": "表达简短"},
            "main_problem": "最近因为实习失败持续焦虑和失眠。",
            "topic": "职业发展",
            "core_demands": "希望理解自己的担心。",
            "growth_experiences": [
                "小时候父母对成绩要求很高。被批评时会觉得自己不够好。"
            ],
            "core_beliefs": ["只有表现好才有价值"],
            "special_situations": [
                {
                    "event": "实习任务没有完成",
                    "automatic_thoughts": "我肯定没有能力",
                    "conditional_assumptions": "只有成功才会被认可",
                    "compensatory_strategies": "反复检查并回避汇报",
                }
            ],
        },
        "sessions": [],
    }

    case = PsychEvalAdapter().convert_case(raw, "data/cbt/999.json")
    growth = next(
        item for item in case.profile.disclosure_items
        if item.category == "growth_experience"
    )
    situation = [
        item for item in case.profile.disclosure_items
        if item.category == "cbt_special_situation"
    ]

    assert "父母" in growth.activation_tags
    assert growth.content == raw["client_info"]["growth_experiences"][0]
    assert {item.content for item in situation} >= {
        "实习任务没有完成",
        "我肯定没有能力",
        "只有成功才会被认可",
        "反复检查并回避汇报",
    }
    growth_node = next(
        node for node in case.profile.evidence_nodes
        if node.evidence_id == growth.evidence_ids[0]
    )
    assert growth_node.source_path == "client_info.growth_experiences[0]"
    assert case.profile.initial_state.arousal == 0.7
    assert case.profile.interaction_prior.therapist_pattern is None
    assert case.profile.interaction_prior.coping_patterns
    dumped = case.profile.model_dump(mode="json")
    assert "hidden_facts" not in dumped
    assert "personality" not in dumped
    assert "relational" not in dumped


def test_routine_intake_requires_an_explicit_question_at_initial_trust():
    raw = {
        "client_id": 999,
        "client_info": {
            "static_traits": {"name": "测试来访者", "age": "28"},
            "main_problem": "最近总是担心",
            "topic": "情绪管理",
            "core_demands": "",
            "growth_experiences": [],
            "special_situations": [],
        },
        "sessions": [],
    }
    profile = PsychEvalAdapter().convert_case(raw).profile
    gate = DisclosureGate()

    assert gate.allowed(profile, profile.initial_state, "欢迎你来", set()) == []
    asked = gate.allowed(profile, profile.initial_state, "我可以怎么称呼你？", set())

    assert len(asked) == 1
    assert asked[0].category == "name"
    assert asked[0].trust_tier.value == "routine"
