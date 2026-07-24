from __future__ import annotations

import pytest
from pydantic import ValidationError

from psychsandbox.domain import BigFive, ClientState, HiddenFact, RiskLevel, SessionStage


@pytest.mark.parametrize(
    "field",
    ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"],
)
def test_big_five_bounds(field):
    with pytest.raises(ValidationError):
        BigFive(**{field: 1.1})


@pytest.mark.parametrize(
    "field",
    ["valence", "arousal", "distress", "trust", "resistance", "hope"],
)
def test_state_bounds(field):
    with pytest.raises(ValidationError):
        ClientState(**{field: -0.1})


def test_hidden_fact_trust_bounds():
    with pytest.raises(ValidationError):
        HiddenFact(fact_id="x", content="x", minimum_trust=2)


def test_risk_levels_are_complete():
    assert [x.value for x in RiskLevel] == ["low", "medium", "high", "imminent"]


def test_stages_are_three_phase():
    assert len(SessionStage) == 3
