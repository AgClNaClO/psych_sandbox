from __future__ import annotations

from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientProfile,
    ClientState,
    ClientTurnSignal,
    CounselorTurn,
    RuptureState,
    TrustChange,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


class StateUpdater:
    TRUST_DELTAS = {
        TrustChange.SIGNIFICANT_DECREASE: -0.12,
        TrustChange.SLIGHT_DECREASE: -0.06,
        TrustChange.UNCHANGED: 0.0,
        TrustChange.SLIGHT_INCREASE: 0.03,
        TrustChange.SIGNIFICANT_INCREASE: 0.06,
    }

    RESPECT_MARKERS = ("按你的节奏", "先不谈", "可以停", "可以换", "不着急")
    PRESSURE_MARKERS = ("必须", "一定要", "直接告诉", "别回避", "为什么不")

    def update(
        self,
        state: ClientState,
        counselor: CounselorTurn,
        client: ClientGeneration,
        signal: ClientTurnSignal | None = None,
        profile: ClientProfile | None = None,
    ) -> tuple[ClientState, dict[str, dict[str, float]]]:
        signal = signal or ClientTurnSignal()
        response = counselor.response
        respected = any(term in response for term in self.RESPECT_MARKERS)
        pressured = any(term in response for term in self.PRESSURE_MARKERS)
        # The planner has already interpreted the interaction into trust_change.
        # Marker detection remains an auditable feature and rupture/readiness cue,
        # but must not count the same counselor behavior a second time.
        trust_delta = self.TRUST_DELTAS[signal.trust_change]
        trust_delta *= self._attachment_multiplier(profile, trust_delta)
        rule = {
            "trust": trust_delta,
            "distress": 0.0,
            "hope": 0.0,
        }
        resistance_target = (
            0.8 if signal.behavior is ClientBehaviorType.RESISTANCE else 0.25
        )
        model = {
            "trust": 0.0,
            "resistance": 0.08 * (resistance_target - state.resistance),
            "hope": 0.05 * client.goal_progress_signal,
            "distress": -0.04 * client.goal_progress_signal,
        }
        topic_readiness = dict(state.topic_readiness)
        if profile is not None:
            fact_topics = {
                fact.fact_id: fact.topic_key for fact in profile.hidden_facts
            }
            for fact_id in signal.blocked_fact_ids:
                topic = fact_topics.get(fact_id)
                if not topic:
                    continue
                current = topic_readiness.get(topic, state.trust)
                topic_readiness[topic] = _clamp(
                    current + (-0.08 if pressured else -0.02)
                )
            for fact_id in signal.retrieved_fact_ids:
                topic = fact_topics.get(fact_id)
                if topic:
                    current = topic_readiness.get(topic, state.trust)
                    topic_readiness[topic] = _clamp(current + 0.02)
        rupture_state = self._rupture_state(
            state.rupture_state, pressured, respected, trust_delta
        )
        updated = state.model_copy(
            update={
                "trust": _clamp(state.trust + rule["trust"] + model["trust"]),
                "distress": _clamp(state.distress + rule["distress"] + model["distress"]),
                "resistance": _clamp(state.resistance + model["resistance"]),
                "hope": _clamp(state.hope + rule["hope"] + model["hope"]),
                "valence": _clamp(state.valence + 0.03 * client.goal_progress_signal),
                "arousal": _clamp(state.arousal - 0.02 * client.goal_progress_signal),
                "fatigue": _clamp(
                    state.fatigue
                    + 0.025
                    + (0.025 if signal.behavior is ClientBehaviorType.RESISTANCE else 0)
                ),
                "topic_readiness": topic_readiness,
                "rupture_state": rupture_state,
            }
        )
        return updated, {
            "rule_delta": rule,
            "model_signal_delta": model,
            "interaction_features": {
                "respected_boundary": float(respected),
                "pressured_disclosure": float(pressured),
            },
        }

    @staticmethod
    def _attachment_multiplier(
        profile: ClientProfile | None, delta: float
    ) -> float:
        if profile is None:
            return 1.0
        pattern = profile.relational.attachment_pattern
        if pattern == "anxious" and delta < 0:
            return 1.25
        if pattern == "avoidant":
            return 0.65 if delta > 0 else 1.15
        if pattern == "disorganized":
            return 0.7 if delta > 0 else 1.2
        return 1.0

    @staticmethod
    def _rupture_state(
        current: RuptureState,
        pressured: bool,
        respected: bool,
        trust_delta: float,
    ) -> RuptureState:
        if pressured or trust_delta <= -0.08:
            return RuptureState.ACTIVE
        if trust_delta < 0:
            return RuptureState.EMERGING
        if current in {RuptureState.ACTIVE, RuptureState.EMERGING} and respected:
            return RuptureState.REPAIRING
        if current is RuptureState.REPAIRING and trust_delta > 0:
            return RuptureState.NONE
        return current
