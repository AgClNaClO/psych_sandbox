from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import logging
import os
import shutil
import sys
import tempfile

import pytest

sys.dont_write_bytecode = True

from psychsandbox.artifacts import create_artifact_dir, write_json
from psychsandbox.datasets import CaseRepository, convert_psycheval, merge_therapy_conversions


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Retain each invocation, including tmp_path, subprocess files and reports."""
    project_root = Path(__file__).resolve().parents[1]
    run_dir = create_artifact_dir(project_root / "runs" / "tests", "pytest")
    config._artifact_dir = run_dir
    for name in ("tmp", "logs", "results", "artifacts"):
        (run_dir / name).mkdir()
    config.option.basetemp = str(run_dir / "tmp" / "pytest")
    config.option.xmlpath = str(run_dir / "results" / "junit.xml")
    config.option.log_file = str(run_dir / "logs" / "pytest.log")
    config._artifact_old_env = {
        name: os.environ.get(name)
        for name in ("TEMP", "TMP", "TMPDIR", "PSYCHSANDBOX_RUNTIME_DIR", "PYTHONDONTWRITEBYTECODE")
    }
    config._artifact_old_tempdir = tempfile.tempdir
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(run_dir / "tmp")
    os.environ["PSYCHSANDBOX_RUNTIME_DIR"] = str(run_dir / "artifacts")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    tempfile.tempdir = str(run_dir / "tmp")
    write_json(run_dir / "run.json", {
        "kind": "pytest", "status": "running",
        "started_at": datetime.now().astimezone().isoformat(),
        "arguments": list(config.invocation_params.args),
    })


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    path = item.config._artifact_dir / "results" / "tests.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "test": report.nodeid, "phase": report.when, "outcome": report.outcome,
            "duration": report.duration, "sections": report.sections,
            "failure": str(report.longrepr) if report.failed else None,
        }, ensure_ascii=False) + "\n")


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    run_dir = session.config._artifact_dir
    path = run_dir / "run.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata.update(
        status="passed" if exitstatus == 0 else "failed",
        exit_code=int(exitstatus), collected=session.testscollected,
        failed=session.testsfailed,
        finished_at=datetime.now().astimezone().isoformat(),
    )
    write_json(path, metadata)
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    stats = {key: len(value) for key, value in terminal.stats.items() if key} if terminal else {}
    (run_dir / "summary.txt").write_text(
        f"pytest exit={int(exitstatus)}\n" + json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if terminal:
        terminal.write_sep("-", f"Artifacts: {run_dir}")
    _maybe_auto_clean_tests(run_dir)


def _maybe_auto_clean_tests(run_dir: Path) -> None:
    """Delete this invocation's test artifacts after the session finishes.

    Test output is cleaned up by default so ``runs/tests/`` does not grow
    across runs. Set ``PSYCHSANDBOX_KEEP_TESTS=1`` to retain the per-invocation
    directory for inspecting failures.
    """
    flag = os.environ.get("PSYCHSANDBOX_KEEP_TESTS", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return
    # Close the --log-file handler so the open pytest.log is not left behind
    # (Windows cannot delete a file that still has an open handle).
    logging.shutdown()
    if run_dir.is_dir():
        shutil.rmtree(run_dir, ignore_errors=True)


def pytest_unconfigure(config: pytest.Config) -> None:
    if not hasattr(config, "_artifact_old_env"):
        return
    for name, value in config._artifact_old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    tempfile.tempdir = config._artifact_old_tempdir


@pytest.fixture(scope="session")
def root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repository(root: Path, tmp_path_factory) -> CaseRepository:
    """Build an isolated schema-v4 cache; production never performs this fallback."""
    output = tmp_path_factory.mktemp("schema-v4") / "psycheval"
    manifests = []
    for therapy in ("bt", "cbt", "het", "pdt", "pmt"):
        manifest = convert_psycheval(
                root,
                output / "by_therapy" / therapy,
                therapy=therapy,
                atomizer="rules",
            )
        manifest.update({
            "atomizer": "extractive",
            "atomizer_prompt_version": "psycheval_extract_only_v2",
            "atomizer_model": "deterministic-test-double",
        })
        manifests.append(manifest)
    merge_therapy_conversions(output, manifests)
    return CaseRepository(output, raw_data_dir=root)


@pytest.fixture(scope="session")
def sample_case(repository: CaseRepository):
    return repository.get("psycheval-cbt-001")
