"""Execution stages, candidate turns and scoring counts for CLI and Web views."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time


PHASE_LABELS = {
    "preparing": "准备实验", "planning": "准备会谈", "generating": "生成对话",
    "scoring": "候选评估", "consolidating": "会后整理", "committed": "会谈已提交",
    "holistic": "全程督导", "report": "生成报告", "finished": "轨迹已保存",
    "failed": "执行中断",
}


@dataclass(frozen=True)
class RunProgress:
    """Execution telemetry only; never a planning signal or clinical score."""

    phase: str
    session_index: int
    sessions_total: int
    sessions_completed: int
    elapsed: float


class SimulationProgressTracker:
    """Combine stage, parallel candidate and scoring ticks into a public snapshot."""

    def __init__(self, sessions_total: int, *, candidates_total: int = 1, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.stage = RunProgress("preparing", 0, sessions_total, 0, 0.0)
        self.candidates: dict[str, dict] = {}
        self.scoring: dict | None = None
        self.candidates_total = candidates_total

    def update(self, event: RunProgress | TurnProgress | ScoringProgress | None) -> dict:
        if isinstance(event, RunProgress):
            if event.session_index != self.stage.session_index:
                self.candidates.clear()
                self.scoring = None
            self.stage = event
            self.started = self.clock() - event.elapsed
        elif event is not None:
            phase = "scoring" if isinstance(event, ScoringProgress) else "generating"
            if event.session_index != self.stage.session_index:
                self.candidates.clear()
                self.scoring = None
            self.stage = RunProgress(phase, event.session_index, self.stage.sessions_total,
                                     self.stage.sessions_completed, self.clock() - self.started)
            if isinstance(event, TurnProgress):
                self.candidates[event.label or "1"] = asdict(event)
            else:
                self.scoring = asdict(event)
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            **asdict(self.stage), "elapsed": max(0.0, self.clock() - self.started),
            "candidates": list(self.candidates.values()), "scoring": self.scoring,
            "candidates_total": self.candidates_total,
        }


def format_duration(seconds: float) -> str:
    """Format an elapsed duration as a short, human-readable Chinese label."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}分{sec:02d}秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}时{minutes:02d}分"


def _bar(ratio: float, width: int = 20) -> str:
    filled = int(round(min(1.0, max(0.0, ratio)) * width))
    return "█" * filled + "░" * (width - filled)


def _percent(ratio: float) -> int:
    return int(round(min(1.0, max(0.0, ratio)) * 100))


@dataclass(frozen=True)
class TurnProgress:
    """One in-session progress tick for a live progress bar."""

    session_index: int
    turn_index: int
    total_turns: int
    elapsed: float
    eta: float
    label: str = ""

    def render(self) -> str:
        total = max(1, self.total_turns)
        ratio = min(1.0, max(0.0, self.turn_index / total))
        eta = "—" if self.turn_index <= 0 else format_duration(self.eta)
        if self.turn_index >= self.total_turns:
            eta = "无"
        prefix = f"Session {self.session_index}"
        if self.label:
            prefix += f" 候选 {self.label}"
        return (
            f"{prefix} [{_bar(ratio)}] {_percent(ratio):3d}%  "
            f"已用 {format_duration(self.elapsed)}  预计剩余 {eta}"
        )


@dataclass(frozen=True)
class ScoringProgress:
    """One aggregated RFT scoring tick for a live progress bar.

    ``instruments_*`` count judge instruments over every candidate that entered
    this scoring phase, so the bar keeps advancing while candidates are scored
    concurrently. When a judge does not report per-instrument steps,
    ``instruments_total`` stays 0 and the bar falls back to candidate counts.
    """

    session_index: int
    instruments_done: int
    instruments_total: int
    candidates_scored: int
    candidates_total: int
    elapsed: float
    eta: float
    last_instrument: str = ""
    label: str = "评分"

    def render(self) -> str:
        if self.instruments_total > 0:
            done, total, unit = self.instruments_done, self.instruments_total, "量表"
        else:
            done, total, unit = self.candidates_scored, self.candidates_total, "候选"
        total = max(1, total)
        ratio = min(1.0, max(0.0, done / total))
        eta = "—" if done <= 0 else format_duration(self.eta)
        if done >= total:
            eta = "无"
        text = (
            f"Session {self.session_index} {self.label} [{_bar(ratio)}] "
            f"{_percent(ratio):3d}%  {unit} {done}/{total}"
        )
        if self.instruments_total > 0:
            text += f"  候选 {self.candidates_scored}/{self.candidates_total}"
            if self.last_instrument:
                text += f"  最近 {self.last_instrument}"
        return text + f"  已用 {format_duration(self.elapsed)}  预计剩余 {eta}"


__all__ = ["PHASE_LABELS", "RunProgress", "ScoringProgress", "SimulationProgressTracker", "TurnProgress", "format_duration"]
