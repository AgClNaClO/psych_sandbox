from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import pytest

from psychsandbox.datasets import CaseRepository


def pytest_configure(config: pytest.Config) -> None:
    """Keep tmp_path isolated from stale Windows ACLs and parallel test runs."""
    if config.option.basetemp is None:
        project_root = Path(__file__).resolve().parents[1]
        config.option.basetemp = str(
            project_root / f".pytest_tmp-{uuid.uuid4().hex}"
        )


def pytest_unconfigure(config: pytest.Config) -> None:
    base_temp = config.option.basetemp
    if base_temp and Path(base_temp).name.startswith(".pytest_tmp-"):
        shutil.rmtree(base_temp, ignore_errors=True)


@pytest.fixture(scope="session")
def root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repository(root: Path) -> CaseRepository:
    return CaseRepository.from_project(root)


@pytest.fixture(scope="session")
def sample_case(repository: CaseRepository):
    return repository.get("psycheval-cbt-001")
