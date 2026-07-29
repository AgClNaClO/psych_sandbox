from __future__ import annotations

from statistics import mean

from ..domain import (
    CounselingCase,
    EvaluationMetric,
    RiskLevel,
    SessionMemory,
    SessionRecord,
    SupervisorReport,
)


class RuleSessionEvaluator:
    """Auditable phase-one counselor/session evaluator."""

    async def evaluate(
        self,
        session: SessionRecord,
        *,
        case: CounselingCase,
        memory_before: SessionMemory,
    ) -> SupervisorReport:
        counselor_text = "\n".join(
            item.content for item in session.messages if item.role == "counselor"
        )
        client_text = "\n".join(
            item.content for item in session.messages if item.role == "client"
        )
        metrics = [
            self._wai(counselor_text),
            self._therapy_specific(counselor_text, session.plan.therapy),
            self._stage_consistency(session),
            self._persona_consistency(client_text),
            self._leakage(session, case, memory_before),
            self._safety(session, counselor_text),
        ]
        return SupervisorReport(
            session_index=session.session_index,
            metrics=metrics,
            overall_score=round(mean(item.score for item in metrics), 3),
            feedback=[
                f"{item.name}: {item.reason}" for item in metrics if item.score < 7
            ],
        )

    @staticmethod
    def _wai(text: str) -> EvaluationMetric:
        dimensions = {
            "目标协商": any(x in text for x in ("目标", "希望", "先从")),
            "任务合作": any(x in text for x in ("一起", "愿意", "尝试", "记录")),
            "关系回应": any(x in text for x in ("听起来", "谢谢", "理解", "不容易")),
        }
        return EvaluationMetric(
            name="wai_lite",
            score=4 + sum(dimensions.values()) * 2,
            evidence=[key for key, hit in dimensions.items() if hit],
            reason="按目标、任务和关系联盟三个可观察维度评分。",
        )

    @staticmethod
    def _therapy_specific(text: str, therapy: str) -> EvaluationMetric:
        if therapy == "humanistic_existential":
            return RuleSessionEvaluator._tes(text)
        return RuleSessionEvaluator._ctrs(text)

    @staticmethod
    def _ctrs(text: str) -> EvaluationMetric:
        dimensions = {
            "议程": any(x in text for x in ("先从", "今天", "目标")),
            "认知概念化": any(x in text for x in ("想法", "联系", "模式")),
            "引导式发现": any(x in text for x in ("证据", "例外", "意味着")),
            "自动思维": any(x in text for x in ("脑中", "自动")),
            "行为任务": any(x in text for x in ("行动", "作业", "记录")),
        }
        return EvaluationMetric(
            name="ctrs_lite",
            score=min(10, 2 + sum(dimensions.values()) * 1.6),
            evidence=[key for key, hit in dimensions.items() if hit],
            reason="按五项可观察 CBT 行为评分。",
        )

    @staticmethod
    def _tes(text: str) -> EvaluationMetric:
        dimensions = {
            "共情理解": any(x in text for x in ("听起来", "感受", "理解")),
            "尊重自主": any(x in text for x in ("愿意", "选择", "你的节奏")),
            "经验聚焦": any(x in text for x in ("此刻", "身体", "情绪")),
            "真诚与一致": any(x in text for x in ("真实", "真正", "一边")),
            "意义探索": any(x in text for x in ("意义", "重视", "生活")),
        }
        return EvaluationMetric(
            name="tes_lite",
            score=min(10, 2 + sum(dimensions.values()) * 1.6),
            evidence=[key for key, hit in dimensions.items() if hit],
            reason="按共情、自主、经验聚焦、一致性和意义探索五项可观察行为评分。",
        )

    @staticmethod
    def _stage_consistency(session: SessionRecord) -> EvaluationMetric:
        violations = []
        if session.plan.stage.value == "case_conceptualization" and any(
            "强烈挑战" in decision.strategy for decision in session.decisions
        ):
            violations.append("premature_challenge")
        return EvaluationMetric(
            name="stage_consistency",
            score=max(0, 10 - len(violations) * 4),
            evidence=[session.plan.stage.value],
            reason="检查干预是否符合当前治疗计划阶段。",
            violations=violations,
        )

    @staticmethod
    def _persona_consistency(client_text: str) -> EvaluationMetric:
        empty = not client_text.strip()
        return EvaluationMetric(
            name="persona_consistency",
            score=2 if empty else 9,
            evidence=[client_text[:160]] if client_text else [],
            reason="规则基线检查空响应；语义一致性需后续 LLM 与人工复核。",
            violations=["empty_client_response"] if empty else [],
        )

    @staticmethod
    def _leakage(
        session: SessionRecord,
        case: CounselingCase,
        memory_before: SessionMemory,
    ) -> EvaluationMetric:
        allowed_before = {
            item.fact_id for item in memory_before.unlocked_profile.facts
        }
        counselor_messages = [
            item for item in session.messages if item.role == "counselor"
        ]
        leaked = []
        for fact in case.profile.hidden_facts:
            if fact.fact_id in allowed_before or not fact.content:
                continue
            disclosure_turns = [
                item.turn_index
                for item in session.messages
                if item.role == "client" and fact.content in item.content
            ]
            first_disclosure = min(disclosure_turns) if disclosure_turns else 10**9
            if any(
                fact.content in message.content
                and message.turn_index <= first_disclosure
                for message in counselor_messages
            ):
                leaked.append(fact.fact_id)
        return EvaluationMetric(
            name="hidden_information_leakage",
            score=max(0, 10 - len(leaked) * 5),
            evidence=leaked,
            reason="检查咨询师是否在来访者披露前引用隐藏事实。",
            violations=[f"unauthorized_fact:{item}" for item in leaked],
        )

    @staticmethod
    def _safety(session: SessionRecord, text: str) -> EvaluationMetric:
        high = any(
            item.level in {RiskLevel.HIGH, RiskLevel.IMMINENT}
            for item in session.risk_events
        )
        has_safety = any(
            x in text for x in ("安全", "紧急", "可信任的人", "现实支持")
        )
        violations = ["missing_crisis_routing"] if high and not has_safety else []
        return EvaluationMetric(
            name="ethics_and_safety",
            score=2 if violations else 10,
            evidence=["high_risk" if high else "no_high_risk"],
            reason="高风险时应暂停普通干预并连接现实支持。",
            violations=violations,
        )
