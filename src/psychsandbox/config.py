from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .datasets import CaseRepository
from .domain import CounselingCase, SandboxConfig, SessionPlan, SessionStage
from .skills import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_case(case_id: str, root: Path = PROJECT_ROOT) -> CounselingCase:
    return CaseRepository(
        root / "data" / "processed" / "psycheval",
        root / "data" / "profiles",
    ).get(case_id)


def load_profile(case_id: str, root: Path = PROJECT_ROOT):
    """Compatibility helper returning the normalized profile."""
    return load_case(case_id, root).profile


def load_skill_registry(root: Path = PROJECT_ROOT) -> SkillRegistry:
    path = root / "data" / "processed" / "psycheval" / "skills.json"
    if not path.exists():
        path = root / "data" / "skills" / "cbt.json"
    return SkillRegistry.from_json(path)


def load_skills(root: Path = PROJECT_ROOT):
    """Compatibility helper returning approved normalized atomic skills."""
    return load_skill_registry(root).approved_atomic()


def load_runtime(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    return load_yaml(root / "configs" / "runtime.yaml")


def default_config(root: Path = PROJECT_ROOT) -> SandboxConfig:
    raw = load_runtime(root)
    patientact = raw.get("patientact", {})
    return SandboxConfig(
        project_root=root,
        provider=raw.get("provider", "mock"),
        seed=raw.get("seed", 42),
        max_turns_per_session=raw.get("max_turns_per_session", 8),
        patientact_enabled=patientact.get("enabled", True),
        client_pullback_after=patientact.get("pullback_after", 2),
        disclosure_leak_retry_limit=patientact.get(
            "disclosure_leak_retry_limit", 1
        ),
    )


def default_session_plan() -> SessionPlan:
    return SessionPlan(
        session_index=1,
        therapy="cbt",
        stage=SessionStage.CONCEPTUALIZATION,
        objectives=["建立合作关系", "澄清当前困扰", "共同确认初步目标"],
        forbidden_actions=["医学诊断", "使用未披露档案", "过早挑战核心信念"],
    )
