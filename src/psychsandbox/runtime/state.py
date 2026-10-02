from __future__ import annotations

from dataclasses import asdict, dataclass

from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientProfile,
    ClientReactionType,
    ClientState,
    ClientTurnSignal,
    CounselorTurn,
    RuptureState,
    TrustChange,
    ReactionIntensity,
    ResistancePatternType,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


@dataclass(frozen=True)
class ClientAppraisal:
    """Auditable interaction features, not clinical scores or public evidence."""

    perceived_understanding: float = 0.0
    boundary_pressure: float = 0.0
    threat: float = 0.0
    goal_alignment: float = 0.0
    perceived_control: float = 0.0
    emotional_load: float = 0.0
    rupture_repair_signal: float = 0.0
    avoidance: float = 0.0


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
        # The policy has already interpreted the interaction into trust_change.
        # Marker detection remains an auditable feature and rupture/readiness cue,
        # but must not count the same counselor behavior a second time.
        trust_delta = self.TRUST_DELTAS[signal.trust_change]
        rule = {
            "trust": trust_delta,
            "distress": 0.0,
            "hope": 0.0,
        }
        intensity = {
            ReactionIntensity.LOW: 0.3,
            ReactionIntensity.MODERATE: 0.6,
            ReactionIntensity.HIGH: 1.0,
        }[signal.intensity]
        understanding = (
            intensity if signal.reaction is ClientReactionType.UNDERSTOOD else 0.0
        )
        threat = intensity if signal.reaction in {
            ClientReactionType.SCARED, ClientReactionType.MISUNDERSTOOD
        } else 0.0
        alignment = intensity if signal.reaction in {
            ClientReactionType.GAINED_CLARITY, ClientReactionType.HOPEFUL
        } else 0.0
        avoidance = float(
            signal.behavior is ClientBehaviorType.RESISTANCE
            and signal.resistance_pattern in {
                ResistancePatternType.MINIMAL_TALK,
                ResistancePatternType.IRRELEVANT_TALK,
                ResistancePatternType.SUPERFICIAL,
                ResistancePatternType.INTELLECTUALIZING,
                ResistancePatternType.COMPLIANCE_WITHOUT_ENGAGEMENT,
            }
        )
        costs = [] if profile is None else [
            max(item.emotional_cost, 0.3 if item.generates_discomfort else 0.0)
            for item in profile.disclosure_items
            if item.item_id in client.disclosed_fact_ids
        ]
        appraisal = ClientAppraisal(
            perceived_understanding=understanding,
            boundary_pressure=float(pressured),
            threat=threat,
            goal_alignment=alignment,
            perceived_control=float(respected and not pressured),
            emotional_load=max(costs, default=0.0),
            rupture_repair_signal=float(respected and trust_delta > 0 and not pressured),
            avoidance=avoidance,
        )
        modifiers = profile.simulation_config.modifiers() if profile else {}
        threat_gain = 1 + modifiers.get("threat_sensitivity", 0.0)
        recovery_gain = 1 + modifiers.get("recovery_rate", 0.0)
        resistance_target = (
            0.8 if signal.behavior is ClientBehaviorType.RESISTANCE else 0.25
        )
        model = {
            "trust": 0.0,
            "resistance": (
                0.08 * (resistance_target - state.resistance)
                + 0.03 * appraisal.boundary_pressure
            ),
            "hope": 0.02 * appraisal.goal_alignment - 0.015 * appraisal.threat,
            "distress": (
                0.035 * appraisal.emotional_load
                + 0.03 * appraisal.threat * threat_gain
                + 0.025 * appraisal.boundary_pressure
                - 0.015 * appraisal.perceived_control * recovery_gain
                - 0.01 * appraisal.avoidance
            ),
            "valence": 0.015 * appraisal.perceived_understanding - 0.025 * appraisal.threat,
            "arousal": (
                0.03 * appraisal.emotional_load + 0.035 * appraisal.boundary_pressure
                + 0.025 * appraisal.threat * threat_gain
                - 0.02 * appraisal.perceived_control * recovery_gain
                - 0.01 * appraisal.avoidance
            ),
        }
        rupture_state = self._rupture_state(
            state.rupture_state, pressured, respected, trust_delta
        )
        updated = state.model_copy(
            update={
                "trust": _clamp(state.trust + rule["trust"] + model["trust"]),
                "distress": _clamp(state.distress + rule["distress"] + model["distress"]),
                "resistance": _clamp(state.resistance + model["resistance"]),
                "hope": _clamp(state.hope + rule["hope"] + model["hope"]),
                "valence": _clamp(state.valence + model["valence"]),
                "arousal": _clamp(state.arousal + model["arousal"]),
                "fatigue": _clamp(
                    state.fatigue
                    + 0.025
                    + (0.025 if signal.behavior is ClientBehaviorType.RESISTANCE else 0)
                ),
                "rupture_state": rupture_state,
            }
        )
        return updated, {
            "rule_delta": rule,
            "model_signal_delta": model,
            "interaction_features": {
                "respected_boundary": float(respected),
                "pressured_disclosure": float(pressured),
                **asdict(appraisal),
            },
        }

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
            return RuptureState.ACTIVE if current is RuptureState.ACTIVE else RuptureState.EMERGING
        if current in {RuptureState.ACTIVE, RuptureState.EMERGING} and respected and trust_delta > 0:
            return RuptureState.REPAIRING
        if current is RuptureState.REPAIRING and trust_delta > 0:
            return RuptureState.NONE
        return current
