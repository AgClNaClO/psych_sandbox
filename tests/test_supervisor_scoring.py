from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from psychsandbox.domain import ScaleItem, ScaleItems, ScaleScore
from psychsandbox.evaluation.psycheval_supervisor import (
    Instrument,
    PsychEvalSupervisor,
    _specific_client_instruments,
)


def test_stai_is_higher_better():
    instruments = _specific_client_instruments("behavioral")
    assert instruments["stai"].direction == "higher_better"


@pytest.mark.parametrize(
    ("direction", "scale", "values", "expected"),
    [
        ("higher_better", (1.0, 5.0), [3.0], 5.0),
        # Lower-better symptom scales stay raw (higher = worse), matching the
        # official eval methods; the RFT reward inverts their delta, not this.
        ("lower_better", (0.0, 4.0), [2.0], 5.0),
        ("lower_better", (0.0, 3.0), [3.0], 10.0),
    ],
)
def test_normalize_returns_raw_without_inversion(direction, scale, values, expected):
    instrument = Instrument("x", "client", "therapy_shared", direction, ("p",), scale=scale)
    assert PsychEvalSupervisor._normalize(instrument, values) == pytest.approx(expected)


def test_overall_is_direction_aware():
    scores = [
        ScaleScore(
            name="wai", level="counselor", category="therapy_shared",
            direction="higher_better", score=8.0,
        ),
        ScaleScore(
            name="scl90", level="client", category="therapy_shared",
            direction="lower_better", score=3.0,
        ),
    ]
    # wai 8.0 + (10 - scl90 3.0) = 15.0 -> 7.5
    assert PsychEvalSupervisor._overall(scores) == pytest.approx(7.5)


_PANAS_ORDER = [
    "Interested", "Excited", "Strong", "Enthusiastic", "Proud",
    "Alert", "Inspired", "Determined", "Attentive", "Active",
    "Distressed", "Upset", "Guilty", "Scared", "Hostile",
    "Irritable", "Ashamed", "Nervous", "Jittery", "Afraid",
]


class PanasGateway:
    def __init__(self, positive_score: float, negative_score: float) -> None:
        self._scores = {
            name: positive_score if index < 10 else negative_score
            for index, name in enumerate(_PANAS_ORDER)
        }

    async def complete_structured(self, **kwargs):
        return ScaleItems(
            items=[
                ScaleItem(item=name, score=self._scores[name])
                for name in _PANAS_ORDER
            ]
        )


def _panas_supervisor(root: Path, gateway: PanasGateway) -> PsychEvalSupervisor:
    return PsychEvalSupervisor(gateway, Path(root) / "prompts" / "eval")


@pytest.mark.parametrize(
    ("positive", "negative", "expected"),
    [
        # (positive - negative + 10) / 2 with each item mapped (score - 1) * 2.5
        (5, 1, 10.0),
        (5, 5, 5.0),
        (1, 5, 0.0),
    ],
)
def test_panas_uses_affect_balance(root, positive, negative, expected):
    supervisor = _panas_supervisor(root, PanasGateway(positive, negative))
    instrument = Instrument(
        "panas", "client", "therapy_shared", "higher_better", ("panas/panas.txt",)
    )
    result = asyncio.run(supervisor._score_panas(instrument, "", ""))
    assert result.score == pytest.approx(expected)
    assert len(result.item_scores) == 20
