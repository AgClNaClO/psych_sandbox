"""Probability-weighted numeric scoring for LLM judges (paper Eq. 8).

Adapted from Zhang et al., *Mechanistic control of large language models as
simulated participants via linear representation* (npj Artificial Intelligence,
DOI 10.1038/s44387-026-00160-9), section "通过 logprob 参数聚合 EMS 得分": the
judge's distribution over integer rating tokens is aggregated as
``sum(i * p_i) / sum(p_i)``, and a judgement whose total in-band probability
mass falls below the refusal floor (0.25 in the paper) is discarded instead of
being replaced by a zero score or a mean.

Only the pure math, the two explicit failures and the prompt rendering live
here. Whether an endpoint returns logprobs at all is a gateway concern; this
module assumes the payload already exists and reports what it contains.

The rating bands used by this repository's PsychEval instruments are all
single-digit (1-5, 1-7, 0-6, 0-4, 0-3, 0-2), so the first generated token
distribution is the whole distribution over ratings. :func:`logprob_band`
rejects wider bands instead of silently aggregating a partial distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Any, Iterable, Mapping


DEFAULT_MASS_FLOOR = 0.25
DEFAULT_TOP_LOGPROBS = 20
DEFAULT_MAX_TOKENS = 16
DEFAULT_TEMPERATURE = 0.7

RatingBand = tuple[int, int]


class LogprobScoringUnsupported(RuntimeError):
    """The endpoint did not return the logprob payload the score needs."""


class LogprobRefusalError(RuntimeError):
    """The judgement is a refusal: total in-band probability mass is too low.

    Carries the observed ``mass`` and ``distribution`` so that callers and
    diagnostic records can report what the judge actually produced instead of
    substituting a score.
    """

    def __init__(
        self,
        *,
        mass: float,
        band: RatingBand,
        distribution: Mapping[int, float],
        mass_floor: float,
    ) -> None:
        self.mass = mass
        self.band = band
        self.distribution = dict(distribution)
        self.mass_floor = mass_floor
        super().__init__(
            f"logprob judgement refused: in-band probability mass {mass:.4f} "
            f"is below the floor {mass_floor:.4f} for band {band}"
        )


@dataclass(frozen=True, slots=True)
class NumericRating:
    """One judge call scored as a probability-weighted integer rating."""

    value: float
    mass: float
    band: RatingBand
    distribution: Mapping[int, float]

    def as_record(self) -> dict[str, Any]:
        """JSON-friendly view for diagnostics and probe artifacts."""
        return {
            "value": self.value,
            "mass": self.mass,
            "band": list(self.band),
            "distribution": {
                str(token): probability
                for token, probability in sorted(self.distribution.items())
            },
        }


def _field(source: Any, name: str) -> Any:
    """Read ``name`` from an SDK object or a plain mapping."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def logprob_band(scale: tuple[float, float]) -> RatingBand:
    """Return the integer rating band of an instrument's raw score range."""
    low, high = scale
    if float(low).is_integer() and float(high).is_integer():
        band = (int(low), int(high))
    else:
        raise ValueError(f"logprob scoring requires an integer rating band, got {scale!r}")
    if band[1] - band[0] + 1 > 10:
        raise ValueError(
            f"logprob scoring requires single-digit ratings, got band {band}; "
            "a wider band cannot be read from one token distribution"
        )
    return band


def parse_integer_token(token: str) -> int | None:
    """Return the integer a rating token spells, or ``None`` for other tokens."""
    candidate = token.strip()
    if not candidate:
        return None
    digits = candidate[1:] if candidate[0] in "+-" else candidate
    if not digits.isascii() or not digits.isdigit():
        return None
    return int(candidate)


def numeric_distribution(
    top_logprobs: Iterable[Any], *, band: RatingBand
) -> dict[int, float]:
    """Probability mass of every in-band integer token in ``top_logprobs``.

    Out-of-band tokens keep their probability in the response but contribute no
    mass here, exactly like the paper's ``sum p_i`` gate over rating values.
    """
    low, high = band
    distribution: dict[int, float] = {}
    for entry in top_logprobs:
        token = _field(entry, "token")
        logprob = _field(entry, "logprob")
        if token is None or logprob is None:
            raise LogprobScoringUnsupported(
                "logprob entry lacks a token or logprob field; "
                "cannot aggregate a numeric distribution"
            )
        try:
            probability = exp(min(0.0, float(logprob)))
        except (TypeError, ValueError) as exc:
            raise LogprobScoringUnsupported(
                f"logprob entry carries a non-numeric logprob: {logprob!r}"
            ) from exc
        value = parse_integer_token(str(token))
        if value is None or value < low or value > high:
            continue
        distribution[value] = distribution.get(value, 0.0) + probability
    return distribution


def rating_from_top_logprobs(
    top_logprobs: Iterable[Any],
    *,
    band: RatingBand,
    mass_floor: float = DEFAULT_MASS_FLOOR,
) -> NumericRating:
    """Aggregate one position's token distribution into a numeric rating."""
    distribution = numeric_distribution(top_logprobs, band=band)
    mass = sum(distribution.values())
    if mass < mass_floor:
        raise LogprobRefusalError(
            mass=mass,
            band=band,
            distribution=distribution,
            mass_floor=mass_floor,
        )
    value = sum(token * probability for token, probability in distribution.items()) / mass
    return NumericRating(value=value, mass=mass, band=band, distribution=distribution)


def rating_from_choice(
    choice: Any,
    *,
    band: RatingBand,
    mass_floor: float = DEFAULT_MASS_FLOOR,
) -> NumericRating:
    """Score a chat completion choice from its first generated token.

    A response without a ``top_logprobs`` payload is reported as unsupported so
    that the caller fails loudly instead of scoring a single sampled token as if
    it carried the whole distribution.
    """
    logprobs = _field(choice, "logprobs")
    content = _field(logprobs, "content")
    if not content:
        raise LogprobScoringUnsupported(
            "the response carried no logprobs payload; "
            "verify the endpoint before enabling logprob scoring"
        )
    top_logprobs = _field(content[0], "top_logprobs")
    if not top_logprobs:
        raise LogprobScoringUnsupported(
            "the first generated token carried no top_logprobs; "
            "request top_logprobs explicitly before enabling logprob scoring"
        )
    return rating_from_top_logprobs(top_logprobs, band=band, mass_floor=mass_floor)


def build_rating_prompt(
    template: str,
    *,
    instrument: str,
    instrument_prompt: str,
    band: RatingBand,
    intake: str,
    dialogue: str,
) -> str:
    """Render the logprob rating prompt asset.

    Every placeholder must be resolved: a leftover ``{{`` means the asset and
    this module drifted apart, which would send an unrendered instruction to the
    judge.
    """
    rendered = template
    for placeholder, value in (
        ("{{instrument}}", instrument),
        ("{{instrument_prompt}}", instrument_prompt),
        ("{{rating_low}}", str(band[0])),
        ("{{rating_high}}", str(band[1])),
        ("{{intake_form}}", intake),
        ("{{diag}}", dialogue),
    ):
        rendered = rendered.replace(placeholder, value)
    if "{{" in rendered:
        raise ValueError(
            "logprob rating prompt still contains an unresolved placeholder; "
            "check the asset against build_rating_prompt"
        )
    return rendered


__all__ = [
    "DEFAULT_MASS_FLOOR",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOP_LOGPROBS",
    "LogprobRefusalError",
    "LogprobScoringUnsupported",
    "NumericRating",
    "RatingBand",
    "build_rating_prompt",
    "logprob_band",
    "numeric_distribution",
    "parse_integer_token",
    "rating_from_choice",
    "rating_from_top_logprobs",
]
