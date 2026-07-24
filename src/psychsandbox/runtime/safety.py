from __future__ import annotations

import re

from ..domain import RiskAssessment, RiskLevel


class SafetyStateMachine:
    """Conservative research-only risk routing, not a diagnostic instrument."""

    _self_harm = ("自杀", "不想活", "结束生命", "伤害自己", "割腕", "跳楼")
    _other_harm = ("杀了他", "伤害别人", "报复他", "弄死")
    _means = ("刀", "药", "绳", "枪", "楼顶", "桥上")
    _immediacy = ("现在", "今晚", "马上", "已经", "正在", "计划好了")
    _despair = ("活着没意义", "没有希望", "撑不下去", "消失就好了")

    def assess_input(self, text: str) -> RiskAssessment:
        normalized = re.sub(r"\s+", "", text.lower())
        categories: list[str] = []
        evidence: list[str] = []
        self_hits = [x for x in self._self_harm if x in normalized]
        other_hits = [x for x in self._other_harm if x in normalized]
        means_hits = [x for x in self._means if x in normalized]
        immediate_hits = [x for x in self._immediacy if x in normalized]
        despair_hits = [x for x in self._despair if x in normalized]
        if self_hits:
            categories.append("self_harm")
        if other_hits:
            categories.append("harm_to_others")
        evidence.extend(self_hits + other_hits + means_hits + immediate_hits + despair_hits)
        if (self_hits or other_hits) and means_hits and immediate_hits:
            level = RiskLevel.IMMINENT
        elif self_hits or other_hits:
            level = RiskLevel.HIGH
        elif despair_hits:
            level = RiskLevel.MEDIUM
            categories.append("despair")
        else:
            level = RiskLevel.LOW
        return RiskAssessment(
            level=level,
            categories=list(dict.fromkeys(categories)),
            evidence=list(dict.fromkeys(evidence)),
            ordinary_intervention_allowed=level in {RiskLevel.LOW, RiskLevel.MEDIUM},
            requires_immediate_stop=level is RiskLevel.IMMINENT,
        )

    def assess_output(self, text: str, input_risk: RiskAssessment) -> RiskAssessment:
        violations = []
        if any(x in text for x in ("你患有", "确诊为", "药量", "剂量", "停药")):
            violations.append("diagnosis_or_medication")
        if input_risk.level in {RiskLevel.HIGH, RiskLevel.IMMINENT} and any(
            x in text for x in ("思维记录表", "行为实验", "家庭作业")
        ):
            violations.append("ordinary_cbt_during_crisis")
        return RiskAssessment(
            level=input_risk.level if not violations else RiskLevel.HIGH,
            categories=violations,
            evidence=violations,
            ordinary_intervention_allowed=not violations and input_risk.ordinary_intervention_allowed,
            requires_immediate_stop=input_risk.requires_immediate_stop or bool(violations),
        )
