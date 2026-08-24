"""Runtime loader for the generation-prompt assets shipped under ``prompts/``.

Phase-1 generation prompts (counselor plan/act/review, simulated-client planning
and utterance, and post-session memory extraction/merge/summary) are maintained
as versioned text files in the repo ``prompts/`` tree rather than embedded Python
string constants.  Consumer modules import them through :func:`load_prompt` so the
file is the single source of truth at runtime.

Results are cached so every consumer sees the same immutable string object, which
keeps identity comparisons against module-level exports working (for example the
``ClientAgent`` prompt re-export tests in ``tests/test_components.py``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Root of the versioned prompt-tree that ships with the repository.
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Bump whenever the content of any consumed generation-prompt file changes.
PROMPT_TREE_VERSION = "2026-08-24"


@lru_cache(maxsize=None)
def load_prompt(relative: str) -> str:
    """Return the exact UTF-8 text of a prompt asset under ``prompts/``.

    ``relative`` is a forward-slash path rooted at the ``prompts`` directory,
    for example ``"counselor/planner_system.txt"``.
    """
    return (PROMPTS_DIR / relative).read_text(encoding="utf-8")


__all__ = [
    "PROJECT_ROOT",
    "PROMPTS_DIR",
    "PROMPT_TREE_VERSION",
    "load_prompt",
]