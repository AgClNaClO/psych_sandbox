from __future__ import annotations

import json
from pathlib import Path

from ..domain import Trajectory


class ExperiencePool:
    """Safety-gated JSONL pool used to prepare later replay and training sets."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def add(self, trajectory: Trajectory) -> bool:
        if not trajectory.safety_passed:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(trajectory.model_dump_json() + "\n")
        return True

    def load(self) -> list[Trajectory]:
        if not self.path.exists():
            return []
        return [
            Trajectory.model_validate(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
