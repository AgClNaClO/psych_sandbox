from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from pydantic import ValidationError

from psychsandbox import cli
from psychsandbox.cli import _config, build_parser
from psychsandbox.config import default_config
from psychsandbox.domain import RFTConfig, SandboxConfig


def _write_runtime(root, settings):
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    (configs / "runtime.yaml").write_text(
        yaml.safe_dump(settings), encoding="utf-8"
    )


@pytest.fixture
def configured_root(tmp_path):
    _write_runtime(tmp_path, {
        "seed": 7,
        "session_count": 6,
        "max_turns_per_session": 5,
        "trace_dir": "custom-runs",
        "database_path": "custom-runs/custom.sqlite3",
        "temperature": {
            "client": 0.6, "client_planner": 0.05,
            "counselor": 0.2, "supervisor": 0.0,
        },
        "patientact": {
            "enabled": False, "pullback_after": 3,
            "disclosure_leak_retry_limit": 2,
        },
        "skill_selection": {"vector_threshold": 30, "vector_top_k": 10},
        "rft": {
            "enabled": True, "candidates": 6, "concurrency": 3,
            "judge_concurrency": 4, "min_eligible": 3,
            "counselor_temperature": 1.1, "judge_temperature": 0.2,
            "candidate_timeout_sec": 90, "judge_timeout_sec": 30,
            "counselor_weight": 0.6, "min_safety_score": 8,
            "min_fidelity_score": 7,
        },
    })
    return tmp_path


def test_default_artifact_paths_are_under_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("PSYCHSANDBOX_RUNTIME_DIR", raising=False)
    config = SandboxConfig(project_root=tmp_path)
    assert config.trace_dir == tmp_path / "runs" / "runtime"
    assert config.database_path == config.trace_dir / "psychsandbox.sqlite3"


def test_default_candidate_count_is_three_in_domain_and_project_yaml(root):
    assert RFTConfig().candidates == 3
    assert default_config(root).rft.candidates == 3
    assert default_config(root).rft.enabled is False


def test_pytest_keeps_stdlib_temp_and_default_runtime_in_test_session(root, tmp_path):
    import tempfile

    assert tmp_path.is_relative_to(root / "runs" / "tests")
    assert SandboxConfig(project_root=root).trace_dir.is_relative_to(root / "runs" / "tests")
    assert Path(tempfile.gettempdir()).is_relative_to(root / "runs" / "tests")


def test_default_config_loads_runtime_settings(configured_root):
    tmp_path = configured_root
    config = default_config(tmp_path)

    assert config.seed == 7
    assert config.session_count == 6
    assert config.max_turns_per_session == 5
    assert config.trace_dir == tmp_path / "custom-runs"
    assert config.database_path == tmp_path / "custom-runs" / "custom.sqlite3"
    assert config.temperature_client == 0.6
    assert config.temperature_client_planner == 0.05
    assert config.temperature_counselor == 0.2
    assert config.temperature_supervisor == 0.0
    assert config.patientact_enabled is False
    assert config.client_pullback_after == 3
    assert config.disclosure_leak_retry_limit == 2
    assert config.skill_selection.vector_threshold == 30
    assert config.skill_selection.vector_top_k == 10
    assert config.rft == RFTConfig(
        enabled=True, candidates=6, concurrency=3, judge_concurrency=4,
        min_eligible=3, counselor_temperature=1.1, judge_temperature=0.2,
        candidate_timeout_sec=90, judge_timeout_sec=30,
        counselor_weight=0.6, min_safety_score=8, min_fidelity_score=7,
    )


@pytest.mark.parametrize("settings", [None, {}, {"seed": 7}])
def test_missing_or_legacy_runtime_uses_domain_defaults(tmp_path, settings):
    if settings is not None:
        _write_runtime(tmp_path, settings)

    config = default_config(tmp_path)

    assert config == SandboxConfig(
        project_root=tmp_path, seed=(settings or {}).get("seed", 42)
    )
    assert config.session_count == 3
    assert config.rft == RFTConfig()


def test_skill_selection_rejects_top_k_larger_than_threshold(tmp_path):
    with pytest.raises(ValueError, match="vector_top_k"):
        SandboxConfig(
            project_root=tmp_path,
            skill_selection={"vector_threshold": 4, "vector_top_k": 5},
        )


def test_cli_builds_api_only_config(tmp_path):
    args = build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "simulate",
            "--case",
            "psycheval-cbt-001",
        ]
    )

    config = _config(args)

    assert config.project_root == tmp_path.resolve()
    assert not hasattr(config, "provider")
    assert not hasattr(config, "local_model_name")
    assert not hasattr(config, "local_device")
    assert config == SandboxConfig(project_root=tmp_path.resolve())
    assert args.seed is None
    assert args.sessions is None
    assert args.max_turns is None


@pytest.mark.parametrize(
    ("options", "overrides", "rft_overrides"),
    [
        ([], {}, {}),
        (["--seed", "0"], {"seed": 0}, {}),
        (["--sessions", "1"], {"session_count": 1}, {}),
        (["--max-turns", "1"], {"max_turns_per_session": 1}, {}),
        (["--rollouts", "8"], {}, {"enabled": True, "candidates": 8}),
        (["--rollouts", "1"], {}, {"enabled": False}),
        (["--no-rft"], {}, {"enabled": False}),
        (["--rollout-concurrency", "1"], {}, {"concurrency": 1}),
        (["--judge-concurrency", "1"], {}, {"judge_concurrency": 1}),
        (
            ["--seed", "0", "--sessions", "2", "--max-turns", "3",
             "--rollouts", "8", "--rollout-concurrency", "2",
             "--judge-concurrency", "1"],
            {"seed": 0, "session_count": 2, "max_turns_per_session": 3},
            {"enabled": True, "candidates": 8, "concurrency": 2,
             "judge_concurrency": 1},
        ),
    ],
)
def test_cli_overrides_only_explicit_settings(
    configured_root, options, overrides, rft_overrides
):
    args = build_parser().parse_args([
        "--root", str(configured_root), "simulate",
        "--case", "psycheval-cbt-001", *options,
    ])
    expected = default_config(configured_root).model_dump()
    expected.update(overrides)
    expected["rft"].update(rft_overrides)

    assert _config(args).model_dump() == expected


@pytest.mark.parametrize("rollouts", [2, 8, 32])
def test_cli_rollouts_enable_rft_from_defaults(tmp_path, rollouts):
    args = build_parser().parse_args([
        "--root", str(tmp_path), "simulate", "--case", "psycheval-cbt-001",
        "--rollouts", str(rollouts),
    ])

    config = _config(args)

    assert config.rft.enabled is True
    assert config.rft.candidates == rollouts


def test_cli_concurrency_alone_does_not_enable_rft(tmp_path):
    args = build_parser().parse_args([
        "--root", str(tmp_path), "simulate", "--case", "psycheval-cbt-001",
        "--rollout-concurrency", "3", "--judge-concurrency", "4",
    ])

    config = _config(args)

    assert config.rft.enabled is False
    assert config.rft.concurrency == 3
    assert config.rft.judge_concurrency == 4


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        ({"session_count": 0}, "session_count"),
        ({"session_count": 101}, "session_count"),
        ({"max_turns_per_session": 0}, "max_turns_per_session"),
        ({"rft": {"candidates": 0}}, "candidates"),
        ({"rft": {"candidates": 1}}, "candidates"),
        ({"rft": {"candidates": 33}}, "candidates"),
        ({"rft": {"concurrency": 0}}, "concurrency"),
        ({"rft": {"judge_concurrency": 0}}, "judge_concurrency"),
        ({"rft": {"min_eligible": 1}}, "min_eligible"),
        ({"rft": {"candidates": 2, "min_eligible": 3}}, "min_eligible"),
        ({"rft": {"candidate_timeout_sec": 0}}, "candidate_timeout_sec"),
        ({"rft": {"judge_timeout_sec": 0}}, "judge_timeout_sec"),
    ],
)
def test_runtime_rejects_invalid_budgets(tmp_path, settings, field):
    _write_runtime(tmp_path, settings)

    with pytest.raises(ValidationError, match=field):
        default_config(tmp_path)


@pytest.mark.parametrize(
    ("option", "value", "field"),
    [
        ("--sessions", "0", "session_count"),
        ("--sessions", "101", "session_count"),
        ("--max-turns", "0", "max_turns_per_session"),
        ("--max-turns", "51", "max_turns_per_session"),
        ("--rollouts", "0", "rollouts"),
        ("--rollouts", "-1", "rollouts"),
        ("--rollouts", "33", "candidates"),
        ("--rollout-concurrency", "0", "concurrency"),
        ("--rollout-concurrency", "33", "concurrency"),
        ("--judge-concurrency", "0", "judge_concurrency"),
        ("--judge-concurrency", "17", "judge_concurrency"),
    ],
)
def test_cli_revalidates_overridden_budgets(tmp_path, option, value, field):
    args = build_parser().parse_args([
        "--root", str(tmp_path), "simulate", "--case", "psycheval-cbt-001",
        option, value,
    ])

    with pytest.raises(ValueError, match=field):
        _config(args)


def test_cli_checks_rollouts_against_yaml_min_eligible(configured_root):
    args = build_parser().parse_args([
        "--root", str(configured_root), "simulate",
        "--case", "psycheval-cbt-001", "--rollouts", "2",
    ])

    with pytest.raises(ValidationError, match="min_eligible"):
        _config(args)


def test_cli_rejects_conflicting_rft_flags():
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "simulate", "--case", "psycheval-cbt-001",
            "--rollouts", "8", "--no-rft",
        ])


@pytest.mark.parametrize(
    ("options", "expected_seed"),
    [
        ([], 7),
        (["--seed", "0", "--sessions", "2", "--max-turns", "3"], 0),
        (["--resume-run", "run-existing"], None),
        (["--resume-run", "run-existing", "--seed", "0"], 0),
        (["--resume-run", "run-existing", "--seed", "7"], 7),
    ],
)
def test_simulate_uses_resolved_config(
    configured_root, monkeypatch, options, expected_seed
):
    args = build_parser().parse_args([
        "--root", str(configured_root), "simulate", "--case", "psycheval-cbt-001",
        "--json", "--no-visualization", *options,
    ])
    result = Mock()
    result.model_dump_json.return_value = "{}"
    sandbox = SimpleNamespace(store=Mock(), run_case=AsyncMock(return_value=result))
    constructor = Mock(return_value=sandbox)
    monkeypatch.setattr(cli, "CounselingSandbox", constructor)

    assert asyncio.run(cli._simulate(args)) == 0

    config = constructor.call_args.args[0]
    assert config == _config(args)
    sandbox.run_case.assert_awaited_once_with(
        "psycheval-cbt-001", therapy=None, session_count=config.session_count,
        seed=expected_seed, resume_run_id=args.resume_run, progress_callback=None,
        turn_progress=None,
    )
    sandbox.store.close.assert_called_once_with()


@pytest.mark.parametrize(
    "command", [["data", "fetch", "psycheval"], ["data", "convert", "--therapy", "bt"]]
)
def test_data_commands_do_not_require_runtime_config(tmp_path, monkeypatch, command):
    _write_runtime(tmp_path, {"rft": {"candidates": 0}})
    handler = Mock(return_value=0)
    monkeypatch.setattr(cli, "_data", handler)
    monkeypatch.setattr(cli, "load_dotenv", Mock())
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "--root", str(tmp_path), *command])

    assert cli.main() == 0

    args, root = handler.call_args.args
    assert root == tmp_path.resolve()
    assert args.data_command == command[1]


def test_cli_rejects_removed_provider_option():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "simulate",
                "--case",
                "psycheval-cbt-001",
                "--provider",
                "api",
            ]
        )
