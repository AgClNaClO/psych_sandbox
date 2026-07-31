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
    registry = SkillRegistry.from_json(path)
    for extra in sorted((root / "data" / "skills").glob("*.json")):
        if extra.resolve() != path.resolve() and extra.name != "cbt.json":
            registry = registry.merge(SkillRegistry.from_json(extra))
    return registry


def load_skills(root: Path = PROJECT_ROOT):
    """Compatibility helper returning approved normalized atomic skills."""
    return load_skill_registry(root).approved_atomic()


def load_runtime(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    return load_yaml(root / "configs" / "runtime.yaml")


def load_models(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    return load_yaml(root / "configs" / "models.yaml")


def _project_path(root: Path, value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def default_config(root: Path = PROJECT_ROOT) -> SandboxConfig:
    raw = load_runtime(root)
    model_config = load_models(root)
    patientact = raw.get("patientact", {})
    temperatures = raw.get("temperature", {})
    local = model_config.get("local", {})
    return SandboxConfig(
        project_root=root,
        provider=raw.get("provider", "mock"),
        seed=raw.get("seed", 42),
        max_turns_per_session=raw.get("max_turns_per_session", 8),
        database_path=_project_path(root, raw.get("database_path")),
        trace_dir=_project_path(root, raw.get("trace_dir")),
        local_model_name=local.get("model_name", ""),
        local_device=local.get("device", "auto"),
        temperature_client=temperatures.get("client", 0.8),
        temperature_counselor=temperatures.get("counselor", 0.4),
        temperature_supervisor=temperatures.get("supervisor", 0.1),
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
