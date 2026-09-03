from __future__ import annotations

from pathlib import Path

from ..domain import (
    CounselingCase,
    RFTConfig,
    RewardSignal,
    RolloutReward,
    SessionEvaluationReport,
    SessionMemory,
    SessionRecord,
)
from ..model_client import ModelGateway
from .safety_gate import SessionSafetyGate
from .session_supervisor import SessionSupervisorEvaluator


# Fixed standardization statistics from PsychAgent's ``src/rft/reward.py``.
# Counselor scales use absolute 0-10 scores; client scales use the delta
# against the previous winner's snapshot. Symptom scales are negated so that
# higher is always better.
REWARD_STD_MEAN: dict[str, dict[str, dict[str, float]]] = {
    "counselor": {
        "RRO": {"mean": 7.637, "std": 1.073},
        "HTAIS": {"mean": 6.404, "std": 1.07},
        "WAI": {"mean": 7.257, "std": 1.461},
        "CUSTOM_DIM": {"mean": 7.363, "std": 0.957},
        "CTRS": {"mean": 9.19, "std": 0.89},
        "EFT_TFS": {"mean": 3.144, "std": 1.948},
        "TES": {"mean": 7.362, "std": 1.346},
        "MITI": {"mean": 5.881, "std": 1.112},
        "PSC": {"mean": 7.269, "std": 1.119},
    },
    "client": {
        "RRO": {"mean": 0.211, "std": 1.262},
        "PANAS": {"mean": 0.442, "std": 0.94},
        "SCL_90": {"mean": -0.14, "std": 0.892},
        "SRS": {"mean": 0.225, "std": 1.507},
        "BDI_II": {"mean": -0.446, "std": 1.39},
        "SFBT": {"mean": 0.158, "std": 1.568},
        "CCT": {"mean": 0.136, "std": 1.016},
        "STAI": {"mean": 0.279, "std": 1.741},
        "IPO": {"mean": -0.085, "std": 2.464},
    },
}

# Symptom scales whose negative delta indicates improvement, so the delta
# z-score is inverted (mirroring ``NEGATIVE_DELTA_CLIENT_METRICS``).
NEGATIVE_DELTA_CLIENT_METRICS: frozenset[str] = frozenset({"SCL_90", "BDI_II", "IPO"})

# Project instrument keys -> PsychAgent canonical metric names. The reward uses
# the official 8-method list; SCL-90 is reported by the PsychEval supervisor but
# is not part of the PsychAgent RFT reward, so it is intentionally absent.
_METRIC_ALIASES: dict[str, str] = {
    "wai": "WAI",
    "htais": "HTAIS",
    "custom_dim": "CUSTOM_DIM",
    "rro": "RRO",
    "rro_client": "RRO",
    "ctrs": "CTRS",
    "tes": "TES",
    "psc": "PSC",
    "miti": "MITI",
    "eft_tfs": "EFT_TFS",
    "panas": "PANAS",
    "srs": "SRS",
    "bdi_ii": "BDI_II",
    "cct": "CCT",
    "ipo": "IPO",
    "stai": "STAI",
    "sfbt": "SFBT",
}

_REWARD_COUNSELOR_METRICS: frozenset[str] = frozenset(
    {"RRO", "CUSTOM_DIM", "HTAIS", "WAI", "CTRS", "EFT_TFS", "TES", "MITI", "PSC"}
)
_REWARD_CLIENT_METRICS: frozenset[str] = frozenset(
    {"RRO", "PANAS", "SRS", "BDI_II", "SFBT", "CCT", "STAI", "IPO"}
)


def _canonical_metric(name: str) -> str:
    return _METRIC_ALIASES.get(name, str(name).strip().upper().replace("-", "_"))


def _clip(value: float, lower: float = -3.0, upper: float = 3.0) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


class SessionRolloutEvaluator:
    """Per-session judge for RFT candidate ranking.

    A single LLM-as-judge evaluation (the PsychEval instruments) feeds the
    candidate reward signal only; the clinical supervisor scores once after
    the full trajectory via :class:`PsychEvalSupervisor`. A deterministic
    disclosure/safety gate decides eligibility and never contributes a score.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        prompts_dir: Path,
        temperature: float,
    ) -> None:
        self.supervisor = SessionSupervisorEvaluator(
            gateway, prompts_dir, temperature=temperature
        )
        self.safety_gate = SessionSafetyGate()

    async def evaluate(
        self,
        session: SessionRecord,
        case: CounselingCase,
        memory_before: SessionMemory,
    ) -> SessionEvaluationReport:
        report = await self.supervisor.evaluate(session, case)
        session.safety_verdict = self.safety_gate.evaluate(session, case, memory_before)
        return report


def compute_rollout_reward(
    report: SessionEvaluationReport,
    previous: RolloutReward | None,
    config: RFTConfig,
    *,
    baseline_session_index: int | None = None,
) -> RolloutReward:
    """Compute the session reward with PsychAgent's fixed z-score statistics.

    Counselor scales are standardized on their absolute 0-10 score; client
    scales are standardized on their delta against the previous winner's
    snapshot, with symptom scales (SCL-90, BDI-II, IPO) negated so that higher
    is better. The final score is the arithmetic mean of all available z-values
    (0.0 when none), matching ``src/rft/reward.py``. ``config`` is kept in the
    signature for call-site compatibility but does not influence the reward.
    """
    if baseline_session_index is not None and (
        type(baseline_session_index) is not int or baseline_session_index < 1
    ):
        raise ValueError("baseline_session_index must be a positive integer or None")

    counselor_snapshot = {
        _canonical_metric(score.name): float(score.score)
        for score in report.counselor_shared + report.counselor_specific
    }
    client_snapshot = {
        _canonical_metric(score.name): float(score.score)
        for score in report.client_shared + report.client_specific
    }

    prev_client: dict[str, float] = {}
    if previous is not None:
        previous = RolloutReward.model_validate(previous.model_dump(), strict=True)
        prev_client = previous.client_snapshot

    signals: list[RewardSignal] = []
    skipped: list[RewardSignal] = []

    for metric, value in counselor_snapshot.items():
        if metric not in _REWARD_COUNSELOR_METRICS:
            continue
        stats = REWARD_STD_MEAN["counselor"].get(metric)
        if not stats:
            skipped.append(
                RewardSignal(
                    side="counselor",
                    metric=metric,
                    raw_value=value,
                    standardized=0.0,
                    skipped_reason="missing_std_stats",
                )
            )
            continue
        z_value = _clip((value - stats["mean"]) / stats["std"])
        signals.append(
            RewardSignal(
                side="counselor",
                metric=metric,
                raw_value=value,
                standardized=z_value,
            )
        )

    for metric, value in client_snapshot.items():
        if metric not in _REWARD_CLIENT_METRICS:
            continue
        previous_value = prev_client.get(metric)
        if previous_value is None:
            skipped.append(
                RewardSignal(
                    side="client",
                    metric=metric,
                    raw_value=value,
                    standardized=0.0,
                    skipped_reason="missing_previous_reward",
                )
            )
            continue
        stats = REWARD_STD_MEAN["client"].get(metric)
        if not stats:
            skipped.append(
                RewardSignal(
                    side="client",
                    metric=metric,
                    raw_value=value,
                    previous_value=previous_value,
                    delta=value - previous_value,
                    standardized=0.0,
                    skipped_reason="missing_std_stats",
                )
            )
            continue
        delta = value - previous_value
        z_value = _clip((delta - stats["mean"]) / stats["std"])
        if metric in NEGATIVE_DELTA_CLIENT_METRICS:
            z_value = -z_value
        signals.append(
            RewardSignal(
                side="client",
                metric=metric,
                raw_value=value,
                previous_value=previous_value,
                delta=delta,
                standardized=z_value,
            )
        )

    z_values = [signal.standardized for signal in signals]
    total = sum(z_values) / len(z_values) if z_values else 0.0
    return RolloutReward(
        total=total,
        counselor_snapshot=counselor_snapshot,
        client_snapshot=client_snapshot,
        signals=signals,
        skipped=skipped,
        baseline_session_index=baseline_session_index,
    )
