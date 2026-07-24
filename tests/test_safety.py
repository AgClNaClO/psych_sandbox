from __future__ import annotations

import pytest

from psychsandbox.domain import RiskLevel
from psychsandbox.runtime import SafetyStateMachine


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今天有点难过", RiskLevel.LOW),
        ("最近压力很大", RiskLevel.LOW),
        ("我觉得活着没意义", RiskLevel.MEDIUM),
        ("我真的撑不下去了", RiskLevel.MEDIUM),
        ("我想自杀", RiskLevel.HIGH),
        ("我想伤害自己", RiskLevel.HIGH),
        ("我想伤害别人", RiskLevel.HIGH),
        ("我今晚已经准备在楼顶结束生命", RiskLevel.IMMINENT),
        ("我现在拿着刀想伤害自己", RiskLevel.IMMINENT),
    ],
)
def test_input_risk_levels(text, expected):
    assert SafetyStateMachine().assess_input(text).level is expected


def test_imminent_stops():
    result = SafetyStateMachine().assess_input("我现在拿着刀想自杀")
    assert result.requires_immediate_stop
    assert not result.ordinary_intervention_allowed


def test_diagnosis_output_blocked():
    machine = SafetyStateMachine()
    low = machine.assess_input("我很焦虑")
    result = machine.assess_output("你患有抑郁症", low)
    assert result.requires_immediate_stop
    assert "diagnosis_or_medication" in result.categories


def test_cbt_homework_blocked_during_crisis():
    machine = SafetyStateMachine()
    high = machine.assess_input("我想自杀")
    result = machine.assess_output("请完成思维记录表作为家庭作业", high)
    assert "ordinary_cbt_during_crisis" in result.categories
