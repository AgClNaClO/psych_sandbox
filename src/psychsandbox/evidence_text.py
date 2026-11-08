"""Shared lexical guard; meaningful text is not necessarily a valid fact."""


def has_semantic_content(text: str) -> bool:
    # Preserve short names, numbers and Chinese negations; no length heuristic.
    return any(character.isalnum() for character in text)
