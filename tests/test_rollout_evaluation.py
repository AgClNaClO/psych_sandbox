from __future__ import annotations

import asyncio

import pytest

from psychsandbox.domain import (
    RFTConfig,
    RolloutReward,
    ScaleScore,
    SessionEvaluationReport,
    SessionMemory,
    SessionRecord,
    UnlockedClientInfo,
)
from psychsandbox.evaluation.rollout import (
    NEGATIVE_DELTA_CLIENT_METRICS,
    REWARD_STD_MEAN,
    SessionRolloutEvaluator,
    compute_rollout_reward,
)


def _scale(name: str, level: str, score: float) -> ScaleScore:
    return ScaleScore(
        name=name,
        level=level,
        category="therapy_shared",
        direction="higher_better",
        score=score,
    )


def report_for(counselor: float, client: dict[str, float] | None = None) -> SessionEvaluationReport:
    client = client if client is not None else {"srs": 6.0, "bdi_ii": 5.0}
    return SessionEvaluationReport(
        session_index=1,
        therapy="cbt",
        counselor_shared=[_scale("wai", "counselor", counselor)],
        counselor_specific=[_scale("ctrs", "counselor", counselor)],
        client_shared=[_scale(name, "client", score) for name, score in client.items()],
        client_specific=[],
        counselor_overall=counselor,
        client_overall=sum(client.values()) / len(client),
    )


def _clip(value: float) -> float:
    return max(-3.0, min(3.0, value))


def _counselor_z(metric: str, value: float) -> float:
    stats = REWARD_STD_MEAN["counselor"][metric]
    return _clip((value - stats["mean"]) / stats["std"])


def _client_delta_z(metric: str, delta: float) -> float:
    stats = REWARD_STD_MEAN["client"][metric]
    z_value = _clip((delta - stats["mean"]) / stats["std"])
    return -z_value if metric in NEGATIVE_DELTA_CLIENT_METRICS else z_value


def test_first_session_reward_uses_counselor_z_scores_and_skips_client():
    report = report_for(8.0, {"srs": 6.0, "bdi_ii": 5.0})
    reward = compute_rollout_reward(report, None, RFTConfig())
    assert reward.counselor_snapshot == {"WAI": 8.0, "CTRS": 8.0}
    assert reward.client_snapshot == {"SRS": 6.0, "BDI_II": 5.0}
    assert {s.metric for s in reward.signals} == {"WAI", "CTRS"}
    assert all(s.side == "counselor" for s in reward.signals)
    assert {s.skipped_reason for s in reward.skipped if s.side == "client"} == {
        "missing_previous_reward"
    }
    expected = (_counselor_z("WAI", 8.0) + _counselor_z("CTRS", 8.0)) / 2
    assert reward.total == pytest.approx(expected)
    assert reward.baseline_session_index is None


def test_subsequent_reward_standardizes_client_delta_and_negates_symptom_scales():
    previous = RolloutReward(
        total=0.0,
        client_snapshot={"SRS": 6.0, "BDI_II": 5.0},
    )
    report = report_for(8.0, {"srs": 7.0, "bdi_ii": 4.0})
    reward = compute_rollout_reward(report, previous, RFTConfig(), baseline_session_index=1)
    srs = next(s for s in reward.signals if s.metric == "SRS")
    bdi = next(s for s in reward.signals if s.metric == "BDI_II")
    assert srs.delta == 1.0
    assert bdi.delta == -1.0
    assert srs.standardized == pytest.approx(_client_delta_z("SRS", 1.0))
    assert bdi.standardized == pytest.approx(_client_delta_z("BDI_II", -1.0))
    # BDI-II improved (negative delta), so its symptom scale z-score is negated
    # and becomes positive.
    assert _client_delta_z("BDI_II", -1.0) > 0
    assert reward.client_snapshot == {"SRS": 7.0, "BDI_II": 4.0}
    assert reward.baseline_session_index == 1


@pytest.mark.parametrize("value", [0, -1, 0.5, "1", None])
def test_invalid_baseline_session_index_is_rejected(value):
    report = report_for(8.0)
    if value is None:
        # None is allowed; verify it does not raise.
        compute_rollout_reward(report, None, RFTConfig(), baseline_session_index=value)
        return
    with pytest.raises(ValueError):
        compute_rollout_reward(report, None, RFTConfig(), baseline_session_index=value)


def test_previous_metric_missing_from_report_is_not_scored():
    previous = RolloutReward(
        total=0.0, client_snapshot={"SRS": 6.0, "STAI": 4.0},
    )
    report = report_for(8.0, {"srs": 7.0})  # "stai" is absent from the report
    reward = compute_rollout_reward(report, previous, RFTConfig())
    client_metrics = {s.metric for s in reward.signals if s.side == "client"}
    assert client_metrics == {"SRS"}  # STAI absent from the report is simply not scored


class _ScaleItemsGateway:
    """Return a fixed ScaleItems payload for every instrument prompt."""

    def __init__(self, score: float = 4.0):
        self.score = score
        self.calls: list[dict] = []

    async def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        from psychsandbox.domain import ScaleItem, ScaleItems

        return ScaleItems(items=[ScaleItem(item=str(i), score=self.score) for i in range(1, 16)])


def test_session_rollout_evaluator_attaches_report_and_safety_verdict(root, sample_case):
    from pathlib import Path

    gateway = _ScaleItemsGateway()
    evaluator = SessionRolloutEvaluator(gateway, Path(root) / "prompts" / "eval", temperature=0.0)
    session = SessionRecord.model_validate({
        "session_id": "s-1",
        "session_index": 1,
        "plan": {
            "session_index": 1, "therapy": "cbt", "stage": "core_intervention",
            "objectives": ["共同选择下一步"],
        },
        "initial_state": {},
        "final_state": {},
        "messages": [
            {"session_index": 1, "turn_index": 0, "role": "counselor", "content": "可以从你愿意说的地方开始。"},
            {"session_index": 1, "turn_index": 1, "role": "client", "content": "我最近压力很大。"},
        ],
        "turn_records": [],
        "summary": "",
        "end_reason": "max_turns",
    })
    memory = SessionMemory(
        case_id=sample_case.case_id,
        unlocked_client_info=UnlockedClientInfo(
            client_id=sample_case.profile.client_id
        ),
    )
    report = asyncio.run(evaluator.evaluate(session, sample_case, memory))
    assert report.counselor_overall > 0
    assert session.safety_verdict is not None
    assert session.safety_verdict.passed is True
    assert gateway.calls
