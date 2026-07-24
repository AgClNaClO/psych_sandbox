from __future__ import annotations

import json
from pathlib import Path

from ..domain import Trajectory


def export_sft(trajectories: list[Trajectory], output: Path) -> int:
    rows = []
    for trajectory in trajectories:
        if not trajectory.safety_passed:
            continue
        messages = trajectory.session.messages
        for index, message in enumerate(messages):
            if message.role == "counselor" and index:
                rows.append({
                    "case_id": trajectory.case_id,
                    "session_index": trajectory.session_index,
                    "prompt": messages[index - 1].content,
                    "response": message.content,
                })
    _write_jsonl(output, rows)
    return len(rows)


def export_dpo_pairs(
    pairs: list[tuple[Trajectory, Trajectory]], output: Path
) -> int:
    rows = []
    for chosen, rejected in pairs:
        if not chosen.safety_passed or chosen.reward <= rejected.reward:
            continue
        rows.append({
            "case_id": chosen.case_id,
            "session_index": chosen.session_index,
            "chosen": _last_counselor(chosen),
            "rejected": _last_counselor(rejected),
        })
    _write_jsonl(output, rows)
    return len(rows)


def _last_counselor(trajectory: Trajectory) -> str:
    return next(
        item.content for item in reversed(trajectory.session.messages)
        if item.role == "counselor"
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
