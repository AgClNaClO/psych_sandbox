"""Exact JSON-path/UTF-8 alignment for conditional item-token expectations.

No constrained decoding or text repair is permitted: either the original JSON
and every required score position are supported by logprobs, or scoring fails.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..domain import ScaleItems
from ..logprob import (
    LogprobRefusalError, LogprobScoringUnsupported, RatingBand, _field,
    logprob_band, numeric_distribution, rating_from_top_logprobs,
)

SCORING_METHOD = "item_logprob_v2"


class BatchScoringError(LogprobScoringUnsupported):
    def __init__(self, message: str, *, records: dict | None = None, supported=False):
        super().__init__(message)
        self.records = records or {}
        self.supported = supported


@dataclass(frozen=True)
class BatchItemRatings:
    items: ScaleItems
    records: dict[str, dict[str, Any]]


def json_spans(text: str) -> tuple[Any, dict[tuple, tuple[int, int]]]:
    """Parse strict JSON and retain scalar character spans by structural path."""
    decoder = json.JSONDecoder(parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError(f"non-JSON constant {value}")))
    spans: dict[tuple, tuple[int, int]] = {}

    def whitespace(pos):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        return pos

    def value(pos, path):
        pos = whitespace(pos)
        start = pos
        if pos >= len(text):
            raise ValueError("truncated JSON")
        if text[pos] == "{":
            result = {}
            pos = whitespace(pos + 1)
            if pos < len(text) and text[pos] == "}":
                return result, pos + 1
            while True:
                if pos >= len(text) or text[pos] != '"':
                    raise ValueError("expected object key")
                key, pos = decoder.raw_decode(text, pos)
                if key in result:
                    raise ValueError(f"duplicate JSON key {key!r}")
                pos = whitespace(pos)
                if pos >= len(text) or text[pos] != ":":
                    raise ValueError("expected colon")
                result[key], pos = value(pos + 1, (*path, key))
                pos = whitespace(pos)
                if pos < len(text) and text[pos] == "}":
                    return result, pos + 1
                if pos >= len(text) or text[pos] != ",":
                    raise ValueError("expected object separator")
                pos = whitespace(pos + 1)
        if text[pos] == "[":
            result = []
            pos = whitespace(pos + 1)
            if pos < len(text) and text[pos] == "]":
                return result, pos + 1
            while True:
                entry, pos = value(pos, (*path, len(result)))
                result.append(entry)
                pos = whitespace(pos)
                if pos < len(text) and text[pos] == "]":
                    return result, pos + 1
                if pos >= len(text) or text[pos] != ",":
                    raise ValueError("expected array separator")
                pos = whitespace(pos + 1)
        result, end = decoder.raw_decode(text, pos)
        spans[path] = (start, end)
        return result, end

    result, end = value(0, ())
    if whitespace(end) != len(text):
        raise ValueError("unexpected text after JSON")
    return result, spans


def ratings_from_choice(choice: Any, *, expected_ids: tuple[str, ...],
                        band: RatingBand, mass_floor: float = 0.25) -> BatchItemRatings:
    logprob_band(band)
    if _field(choice, "finish_reason") != "stop":
        raise BatchScoringError("batch response did not finish normally")
    text = _field(_field(choice, "message"), "content")
    tokens = _field(_field(choice, "logprobs"), "content")
    if not isinstance(text, str) or not tokens:
        raise BatchScoringError("batch response has no content/logprobs payload")
    try:
        data, spans = json_spans(text)
        raw = ScaleItems.model_validate(data)
        if not isinstance(data, dict) or set(data) != {"items"}:
            raise ValueError("expected exactly one items envelope")
        ids = [item.item for item in raw.items]
        if len(set(ids)) != len(ids) or len(ids) != len(expected_ids) or set(ids) != set(expected_ids):
            raise ValueError("missing, unexpected or duplicate item IDs")
    except (ValueError, TypeError, RecursionError) as exc:
        raise BatchScoringError(f"invalid item JSON: {exc}", supported=True) from exc

    positions = []
    pieces = []
    offset = 0
    for token in tokens:
        byte_values = _field(token, "bytes")
        try:
            piece = bytes(byte_values) if byte_values is not None else _field(token, "token").encode("utf-8")
        except (ValueError, TypeError, AttributeError) as exc:
            raise BatchScoringError("invalid token bytes", supported=True) from exc
        positions.append((offset, offset + len(piece), token, piece))
        pieces.append(piece)
        offset += len(piece)
    encoded = text.encode("utf-8")
    # Some compatible endpoints include an EOS token in logprobs but omit it
    # from message.content. Only known terminal markers after exact content are
    # transport metadata; never trim arbitrary text or a prefix mismatch.
    terminal_markers = {marker.encode("utf-8") for marker in (
        "<｜end▁of▁sentence｜>", "<|im_end|>", "<|endoftext|>", "<|eot_id|>")}
    while pieces and b"".join(pieces) != encoded and pieces[-1] in terminal_markers:
        pieces.pop()
        positions.pop()
    if b"".join(pieces) != encoded:
        raise BatchScoringError("token bytes do not reconstruct response content", supported=True)

    records: dict[str, dict] = {}
    failed = False
    for index, item in enumerate(raw.items):
        record: dict[str, Any] = {"method": SCORING_METHOD, "sampled_score": item.score}
        records[item.item] = record
        try:
            start, end = spans[("items", index, "score")]
            literal = text[start:end]
            if not re.fullmatch(r"[0-9]", literal) or not band[0] <= int(literal) <= band[1]:
                raise LogprobScoringUnsupported("score must be an in-band single-digit JSON integer")
            begin, finish = len(text[:start].encode("utf-8")), len(text[:end].encode("utf-8"))
            matches = [(i, token, piece) for i, (a, b, token, piece) in enumerate(positions)
                       if a <= begin and b >= finish]
            if len(matches) != 1:
                raise LogprobScoringUnsupported("score is split across tokens")
            token_index, token, piece = matches[0]
            if piece.strip(b" \t\r\n") != literal.encode("ascii"):
                raise LogprobScoringUnsupported("score token contains JSON syntax or other content")
            record.update(token_index=token_index, byte_span=[begin, finish])
            top = _field(token, "top_logprobs")
            if not top:
                raise LogprobScoringUnsupported("score position has no top_logprobs")
            candidates = list(top)
            sampled = _field(token, "token")
            if not isinstance(sampled, str) or sampled.encode("utf-8") != piece:
                raise LogprobScoringUnsupported("sampled score token text disagrees with bytes")
            numeric_distribution([token], band=band)
            if not any(_field(entry, "token") == sampled for entry in candidates):
                candidates.append(token)
            # Validate the entire observed distribution, including non-numeric tokens.
            numeric_distribution(candidates, band=band)
            candidates = [entry for entry in candidates
                          if re.fullmatch(r"[ \t\r\n]*[0-9][ \t\r\n]*", str(_field(entry, "token")))]
            rating = rating_from_top_logprobs(candidates, band=band, mass_floor=mass_floor)
            record.update(rating.as_record(), accepted=True)
            item.score = rating.value
        except (LogprobScoringUnsupported, LogprobRefusalError, KeyError) as exc:
            failed = True
            record.update(accepted=False, error=str(exc))
            if isinstance(exc, LogprobRefusalError):
                record.update(mass=exc.mass, band=list(exc.band),
                              distribution={str(k): v for k, v in exc.distribution.items()})
    if failed:
        raise BatchScoringError("one or more required items failed logprob scoring",
                                records=records, supported=True)
    return BatchItemRatings(raw, records)
