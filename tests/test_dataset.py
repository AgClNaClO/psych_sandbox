from __future__ import annotations

import json

from psychsandbox.datasets.psycheval import PsychEvalAdapter, _case_split


def test_official_case_count(repository):
    assert len(repository.list("cbt")) == 148


def test_manifest_counts(root):
    manifest = json.loads(
        (root / "data/processed/psycheval/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["case_count"] == 148
    assert sum(manifest["split_counts"].values()) == 148


def test_manifest_revision_pinned(root):
    manifest = json.loads(
        (root / "data/processed/psycheval/manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["revision"]) == 40


def test_manifest_noncommercial_license(root):
    manifest = json.loads(
        (root / "data/processed/psycheval/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["license"] == "CC BY-NC 4.0"


def test_case_sessions_ordered(sample_case):
    assert [x.session_index for x in sample_case.global_plan] == list(
        range(1, len(sample_case.global_plan) + 1)
    )


def test_case_keeps_reference_sessions(sample_case):
    assert sample_case.reference_sessions


def test_split_is_case_deterministic():
    assert _case_split("psycheval-cbt-001") == _case_split("psycheval-cbt-001")


def test_no_case_crosses_splits(root):
    split_ids = {}
    for split in ("train", "validation", "test"):
        lines = (root / f"data/processed/psycheval/{split}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        split_ids[split] = {json.loads(line)["case_id"] for line in lines}
    assert not (split_ids["train"] & split_ids["validation"])
    assert not (split_ids["train"] & split_ids["test"])
    assert not (split_ids["validation"] & split_ids["test"])


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
