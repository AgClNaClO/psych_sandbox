from __future__ import annotations

from statistics import mean

from ..domain import (
    ClientBehaviorType,
    ClientSimulationReport,
    ClientTurnSignal,
    EvaluationMetric,
    SessionRecord,
)


class ClientSimulationEvaluator:
    """Auditable client-side realism and disclosure checks."""

    async def evaluate(self, session: SessionRecord) -> ClientSimulationReport:
        client_messages = [
            item for item in session.messages if item.role == "client"
        ]
        client_text = "\n".join(item.content for item in client_messages)
        records = [
            item for item in session.turn_records if item.get("client_turn_signal")
        ]
        signals = [
            ClientTurnSignal.model_validate(item["client_turn_signal"])
            for item in records
        ]
        leak_events = [
            item.get("client_leakage", {}) for item in records
        ]
        exposed_leaks = [
            event for event in leak_events
            if event.get("exposed_to_counselor", False)
        ]
        blocked_records = [
            (record, signal)
            for record, signal in zip(records, signals, strict=False)
            if record.get("disclosure_decision", {}).get("blocked")
        ]
        blocked_handled = sum(
            signal.behavior
            in {
                ClientBehaviorType.RESISTANCE,
                ClientBehaviorType.REQUEST,
                ClientBehaviorType.SIMPLE_RESPONSE,
            }
            for _, signal in blocked_records
        )
        resistance_patterns = {
            signal.resistance_pattern
            for signal in signals
            if signal.behavior is ClientBehaviorType.RESISTANCE
        }
        signal_emotion_matches = sum(
            signal.reaction.value
            in record.get("client_generation", {}).get("expressed_emotions", [])
            or signal.reaction.value == "no_reaction"
            for record, signal in zip(records, signals, strict=False)
        )
        insight_early = any(
            signal.behavior in {
                ClientBehaviorType.INSIGHT,
                ClientBehaviorType.DISCUSSING_PLANS,
            }
            for signal in signals[:2]
        )
        artificial_terms = [
            item
            for item in ("认知重构", "自动思维记录表", "作为一个模型", "系统提示词")
            if item in client_text
        ]
        metrics = [
            EvaluationMetric(
                name="client_persona_consistency",
                score=2 if not client_text.strip() else 6 if artificial_terms else 9,
                evidence=artificial_terms or [client_text[:160]],
                reason="检查角色破坏、模型自述和明显治疗术语模仿。",
                violations=[
                    f"artificial_language:{item}" for item in artificial_terms
                ],
            ),
            EvaluationMetric(
                name="client_disclosure_pacing",
                score=2 if exposed_leaks else 8 if session.newly_unlocked_fact_ids else 7,
                evidence=session.newly_unlocked_fact_ids,
                reason="结合门控结果和实际解锁事实检查披露节奏。",
                violations=["premature_disclosure"] if exposed_leaks else [],
            ),
            EvaluationMetric(
                name="client_resistance_quality",
                score=(
                    6
                    if not blocked_records
                    else min(
                        10,
                        4
                        + 4 * blocked_handled / len(blocked_records)
                        + min(2, len(resistance_patterns)),
                    )
                ),
                evidence=[
                    item.value for item in resistance_patterns if item is not None
                ],
                reason=(
                    "敏感内容被阻断时应保护披露边界；可表现为请求、简短回应或"
                    "与人物状态一致的阻抗，不要求每次都防御。"
                ),
            ),
            EvaluationMetric(
                name="client_emotional_authenticity",
                score=(
                    7
                    if not signals
                    else round(5 + 5 * signal_emotion_matches / len(signals), 3)
                ),
                evidence=[item.reaction.value for item in signals],
                reason="检查内部反应与外显情绪信号是否一致。",
            ),
            EvaluationMetric(
                name="client_behavioral_realism",
                score=5 if artificial_terms or insight_early else 9,
                evidence=[item.behavior.value for item in signals],
                reason="检查治疗语言模仿及过早进入领悟或行动计划。",
                violations=["premature_insight_or_plan"] if insight_early else [],
            ),
            EvaluationMetric(
                name="client_premature_disclosure",
                score=0 if exposed_leaks else 10,
                evidence=[
                    fact_id
                    for event in leak_events
                    for attempt in event.get("attempts", [])
                    for fact_id in attempt.get("leaked_fact_ids", [])
                ],
                reason="检查未授权事实是否进入咨询师可见对话。",
                violations=["exposed_private_memory"] if exposed_leaks else [],
            ),
            EvaluationMetric(
                name="client_signal_utterance_consistency",
                score=(
                    7
                    if not signals
                    else round(5 + 5 * signal_emotion_matches / len(signals), 3)
                ),
                evidence=[item.behavior.value for item in signals],
                reason="检查结构化反应信号与最终回答的兼容字段是否一致。",
            ),
            EvaluationMetric(
                name="client_premature_resolution",
                score=4 if insight_early else 9,
                evidence=[item.behavior.value for item in signals[:2]],
                reason="初始轮次不应快速完成领悟、计划或自我治愈。",
                violations=["premature_insight_or_plan"] if insight_early else [],
            ),
        ]
        red_flags = list(
            dict.fromkeys(
                violation
                for metric in metrics
                for violation in metric.violations
            )
        )
        return ClientSimulationReport(
            session_index=session.session_index,
            metrics=metrics,
            overall_score=round(mean(item.score for item in metrics), 3),
            red_flags=red_flags,
        )
