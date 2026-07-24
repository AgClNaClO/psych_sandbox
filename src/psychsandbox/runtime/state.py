from __future__ import annotations

from ..domain import ClientGeneration, ClientState, CounselorTurn


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


class StateUpdater:
    def update(
        self,
        state: ClientState,
        counselor: CounselorTurn,
        client: ClientGeneration,
    ) -> tuple[ClientState, dict[str, dict[str, float]]]:
        supportive = any(
            word in counselor.response for word in ("理解", "听起来", "谢谢", "一起", "愿意")
        )
        rule = {
            "trust": 0.04 if supportive else -0.01,
            "distress": -0.025 if supportive else 0.01,
            "hope": 0.025 if supportive else 0.0,
        }
        model = {
            "trust": 0.06 * (client.cooperation - 0.5),
            "resistance": 0.08 * (client.resistance - state.resistance),
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
