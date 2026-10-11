"""Exact dialogue grounding shared by memory and session review."""
from typing import Any

from ..domain import DialogueEvidence, Message
from .leakage import normalize_disclosure_text


def is_grounded(evidence: DialogueEvidence, messages: list[Message], *, role: str | None = None) -> bool:
    quote = normalize_disclosure_text(evidence.quote)
    return (len(quote) >= 2 and (role is None or evidence.role == role)
            and any(message.role == evidence.role
                    and message.turn_index == evidence.turn_index
                    and quote in normalize_disclosure_text(message.content)
                    for message in messages))


def string_leaves(value: Any, path: str = ""):
    """Paths deliberately omit list indices so deduplication preserves provenance."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from string_leaves(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for child in value:
            yield from string_leaves(child, path)
    elif isinstance(value, str) and value:
        yield path, value


def prune_leaves(value: Any, allowed: set[tuple[str, str]], path: str = "") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            kept = prune_leaves(child, allowed, f"{path}.{key}" if path else key)
            if kept not in (None, {}, []):
                result[key] = kept
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            kept = prune_leaves(child, allowed, path)
            if kept not in (None, {}, []) and kept not in result:
                result.append(kept)
        return result
    return value if isinstance(value, str) and (path, value) in allowed else None
