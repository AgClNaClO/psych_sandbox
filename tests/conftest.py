from __future__ import annotations

from pathlib import Path

import pytest

from psychsandbox.datasets import CaseRepository


@pytest.fixture(scope="session")
def root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repository(root: Path) -> CaseRepository:
    return CaseRepository(root / "data/processed/psycheval", root / "data/profiles")


@pytest.fixture(scope="session")
def sample_case(repository: CaseRepository):
    return repository.get("psycheval-cbt-001")
