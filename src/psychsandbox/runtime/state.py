from __future__ import annotations

from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientState,
    ClientTurnSignal,
    CounselorTurn,
    TrustChange,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


class StateUpdater:
    TRUST_DELTAS = {
        TrustChange.SIGNIFICANT_DECREASE: -0.10,
        TrustChange.SLIGHT_DECREASE: -0.05,
        TrustChange.UNCHANGED: 0.0,
        TrustChange.SLIGHT_INCREASE: 0.05,
        TrustChange.SIGNIFICANT_INCREASE: 0.10,
    }

    def update(
        self,
        state: ClientState,
        counselor: CounselorTurn,
        client: ClientGeneration,
        signal: ClientTurnSignal | None = None,
    ) -> tuple[ClientState, dict[str, dict[str, float]]]:
        del counselor
        signal = signal or ClientTurnSignal()
        trust_delta = self.TRUST_DELTAS[signal.trust_change]
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
        updated = state.model_copy(
            update={
                "trust": _clamp(state.trust + rule["trust"] + model["trust"]),
                "distress": _clamp(state.distress + rule["distress"] + model["distress"]),
                "resistance": _clamp(state.resistance + model["resistance"]),
                "hope": _clamp(state.hope + rule["hope"] + model["hope"]),
                "valence": _clamp(state.valence + 0.03 * client.goal_progress_signal),
                "arousal": _clamp(state.arousal - 0.02 * client.goal_progress_signal),
            }
        )
        return updated, {"rule_delta": rule, "model_signal_delta": model}
