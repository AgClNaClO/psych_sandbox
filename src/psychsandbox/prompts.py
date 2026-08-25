"""Jinja2 prompt rendering and loading for the generation-prompt assets.

The generation prompts (counselor plan/act/review, simulated-client planning and
utterance, and post-session memory extraction/merge/summary) are maintained as
Jinja2 templates under the repo ``prompts/`` tree. Consumer modules render them
through :func:`render_prompt`, so the template is the single source of truth for
how user/business data becomes a system prompt.  Results are cached so repeated
renders reuse the compiled template.

The eval-scale prompts under ``prompts/eval/`` are plain text (non-template); use
:func:`load_prompt` for those.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Root of the versioned prompt-tree that ships with the repository.
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Bump whenever the content of any consumed generation-prompt file changes.
PROMPT_TREE_VERSION = "2026-08-25"


@lru_cache(maxsize=None)
def _env() -> Environment:
    """A shared Jinja2 environment rooted at ``prompts/``.

    ``StrictUndefined`` surfaces missing template variables immediately instead
    of silently rendering them empty, matching the "Pydantic input -> render" so
    a rendering-time typo is a loud error rather than a silent prompt bug.
    """
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


@lru_cache(maxsize=None)
def load_template(relative: str):
    """Return the compiled Jinja2 template for a prompt asset under ``prompts/``."""
    return _env().get_template(relative)


def render_prompt(relative: str, **context) -> str:
    """Render a prompt template under ``prompts/`` with ``context``.

    ``relative`` is a forward-slash path rooted at ``prompts``, for example
    ``"simclient/utterance_system.jinja2"``. Returns the rendered text.
    """
    return load_template(relative).render(**context)


@lru_cache(maxsize=None)
def load_prompt(relative: str) -> str:
    """Return the exact UTF-8 text of a plain-text prompt asset under ``prompts/``.

    Intended for non-template assets (e.g. PsychEval scale prompts under
    ``prompts/eval/``). For generation prompts use :func:`render_prompt`.
    """
    return (PROMPTS_DIR / relative).read_text(encoding="utf-8")


__all__ = [
    "PROJECT_ROOT",
    "PROMPTS_DIR",
    "PROMPT_TREE_VERSION",
    "load_prompt",
    "load_template",
    "render_prompt",
]