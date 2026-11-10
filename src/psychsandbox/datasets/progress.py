"""Progress events for explicit dataset conversion, independent of the CLI."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversionProgress:
    therapy: str
    phase: str
    completed: int
    total: int
    elapsed: float = 0.0
    cache_hits: int = 0
    reused: int = 0
    fallbacks: int = 0
    skipped: int = 0

    @property
    def eta(self) -> float | None:
        if self.completed <= 0:
            return None
        return self.elapsed * max(0, self.total - self.completed) / self.completed
