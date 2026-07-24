from __future__ import annotations

import json

from psychsandbox.datasets.psycheval import _case_split


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
