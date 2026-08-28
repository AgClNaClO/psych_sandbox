from __future__ import annotations

import pytest

from psychsandbox.datasets.psycheval import (
    PsychEvalAdapter,
    _case_split,
    convert_psycheval,
)


def test_official_case_count(repository):
    assert len(repository.list("cbt")) == 148


def test_cli_conversion_retains_each_invocation_and_latest_success(root, tmp_path, monkeypatch):
    import json
    from psychsandbox import cli
    from psychsandbox.artifacts import latest_data_dir

    base = tmp_path / "artifacts"
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(base))
    args = cli.build_parser().parse_args(["data", "convert", "--therapy", "bt"])
    cli._data(args, root)
    first = latest_data_dir(root, "processed")
    first_manifest = (first / "manifest.json").read_bytes()
    cli._data(args, root)
    second = latest_data_dir(root, "processed")
    assert second != first
    assert (first / "manifest.json").read_bytes() == first_manifest
    assert (second / "all.jsonl").exists()

    def fail(*args, **kwargs):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(cli, "convert_psycheval", fail)
    with pytest.raises(RuntimeError, match="conversion failed"):
        cli._data(args, root)
    assert latest_data_dir(root, "processed") == second
    statuses = [json.loads(path.read_text(encoding="utf-8"))["status"] for path in base.glob("*/run.json")]
    assert sorted(statuses) == ["completed", "completed", "failed"]


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
def test_each_therapy_builds_source_grounded_hidden_facts(
    repository, therapy_code, expected_category
):
    case = repository.get(f"psycheval-{therapy_code}-001")
    assert any(fact.category == expected_category for fact in case.profile.hidden_facts)
    assert all(fact.source_field for fact in case.profile.hidden_facts)
    assert all(fact.disclosure_layers for fact in case.profile.hidden_facts)


def test_adapter_builds_source_grounded_layered_memories():
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
    growth, situation = case.profile.hidden_facts

    assert case.profile.theory["_personality_source"] == "unspecified_neutral_prior"
    assert case.profile.personality.openness == 0.5
    assert "父母" in growth.activation_tags
    assert len(growth.disclosure_layers) >= 2
    assert situation.disclosure_layers[-1].endswith("应对方式：反复检查并回避汇报")
    assert growth.source_field == "client_info.growth_experiences[0]"
    assert case.profile.initial_state.arousal == 0.7
    assert case.profile.relational.core_belief_theme == "只有表现好才有价值"
    assert case.profile.relational.attachment_pattern == "unspecified"
    assert case.profile.personality.openness == 0.5
    assert case.profile.relational.preferred_resistance_patterns
    assert case.profile.relational.emotional_range
    assert case.profile.relational.confidence == 0.6
