"""Compatibility JSONL helpers for normalized trajectories."""

from __future__ import annotations

from pathlib import Path

from .domain import RunResult, Trajectory


class TraceLogger:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def event_path(self, run_id: str) -> Path:
        return self.run_dir / f"{run_id}.jsonl"

    def log(self, event: Trajectory) -> None:
        with self.event_path(event.run_id).open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def save_result(self, result: RunResult) -> Path:
        path = self.run_dir / f"{result.run_id}.result.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return path
