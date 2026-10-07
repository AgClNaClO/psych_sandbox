"""Live progress ticks for the CLI bars.

Two shapes are rendered here: one bar per candidate session while it is being
generated (:class:`TurnProgress`) and one aggregated bar for the RFT scoring
phase (:class:`ScoringProgress`). Both expose ``label`` plus ``render()``, which
is the small contract the CLI renderer relies on.
"""
from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["ScoringProgress", "TurnProgress", "format_duration"]
