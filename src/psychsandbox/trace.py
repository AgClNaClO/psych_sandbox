"""Compatibility JSONL helpers for normalized trajectories."""

from __future__ import annotations

from pathlib import Path

from .artifacts import create_artifact_dir, find_run_dir
from .domain import RunResult, Trajectory


class TraceLogger:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def event_path(self, run_id: str) -> Path:
        return self._directory(run_id) / "trajectory.jsonl"

    def _directory(self, run_id: str) -> Path:
        try:
            return find_run_dir(self.run_dir, run_id)
        except FileNotFoundError:
            return create_artifact_dir(self.run_dir, "trace", run_id)

    def log(self, event: Trajectory) -> None:
        with self.event_path(event.run_id).open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def save_result(self, result: RunResult) -> Path:
        path = self._directory(result.run_id) / "result.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return path
