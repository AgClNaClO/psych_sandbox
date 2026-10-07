"""Contracts for the double-click launcher `run_simulate.bat`.

The launcher is the one place where a Windows shell decides whether the
simulation runs at all, so two properties are asserted here:

* it keeps the optional probability-weighted (logprob) scoring path off by
  default, while still wiring the switch that turns it on;
* it stays ASCII-only and never calls ``chcp``. cmd re-reads a batch file with
  the codepage that is active while reading it, so non-ASCII bytes make the
  parser lose its line position and execute fragments of the file as commands
  (observed as phantom "is not recognized" errors, and even a nested ``cmd``).
  Chinese console text therefore goes through Python unicode escapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def launcher(root: Path) -> str:
    return (Path(root) / "run_simulate.bat").read_text(encoding="utf-8")


def test_launcher_keeps_logprob_scoring_switched_off_by_default(launcher):
    # Item-average scoring is the default; the weighted-expectation path is an
    # opt-in comparison mode, so the launcher must not enable or probe it.
    assert "set LOGPROB_SCORING=0" in launcher
    assert "set PROBE_LOGPROB=0" in launcher
    assert "set LOGPROB_ARG=--logprob-scoring" in launcher
    assert "%LOGPROB_ARG%" in launcher
    # The switch must stay a real switch, not a hard-coded flag.
    assert 'if "%LOGPROB_SCORING%"=="1" set LOGPROB_ARG=--logprob-scoring' in launcher

def test_launcher_wires_the_turn_cap_and_the_transient_retry_budget(launcher):
    assert "set TURNS=8" in launcher
    assert "--max-turns %TURNS%" in launcher
    assert "set MODEL_MAX_ATTEMPTS=6" in launcher
    # The budget must be exported before the invocation, which appears once.
    invocation = launcher.index("psych-sandbox simulate ^")
    assert launcher.index("set MODEL_MAX_ATTEMPTS=") < invocation
    assert launcher.count("psych-sandbox simulate ^") == 1



def test_launcher_keeps_the_endpoint_probe_and_the_probe_subcommand(launcher):
    assert 'if /i "%~1"=="probe"' in launcher
    assert "psych-sandbox probe logprob-scoring" in launcher
    assert launcher.count("--json") == 1  # full record only for the probe run


def test_launcher_stays_ascii_only_and_never_changes_the_codepage(launcher):
    assert launcher.isascii()
    commands = [
        line.strip()
        for line in launcher.splitlines()
        if line.strip() and not line.strip().lower().startswith("rem")
    ]
    assert not [line for line in commands if line.lower().startswith("chcp")]
