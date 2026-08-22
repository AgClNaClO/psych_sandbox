from __future__ import annotations

import pytest

from psychsandbox.cli import _config, build_parser
from psychsandbox.config import default_config


def test_default_config_loads_runtime_settings(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "runtime.yaml").write_text(
        "\n".join(
            [
                "seed: 7",
                "max_turns_per_session: 5",
                "trace_dir: custom-runs",
                "database_path: custom-runs/custom.sqlite3",
                "temperature:",
                "  client: 0.6",
                "  client_planner: 0.05",
                "  counselor: 0.2",
                "  supervisor: 0.0",
                "patientact:",
                "  enabled: false",
                "  pullback_after: 3",
                "  disclosure_leak_retry_limit: 2",
            ]
        ),
        encoding="utf-8",
    )

    config = default_config(tmp_path)

    assert config.seed == 7
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
