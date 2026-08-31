from __future__ import annotations

from copy import deepcopy
from math import isfinite
from statistics import mean

from ..domain import (
    RFTConfig,
    RolloutAssessment,
    RolloutReward,
    SessionMemory,
    SessionRecord,
)
from ..model_client import ModelGateway
from ..prompts import render_prompt


SESSION_JUDGE_TEMPLATE = "rft/session_judge.jinja2"
COUNSELOR_DIMENSIONS = (
    "counselor_alliance",
    "counselor_strategy",
    "counselor_goal_alignment",
    "counselor_safety",
)
CLIENT_DIMENSIONS = (
    "client_engagement",
    "client_understanding",
    "client_agency",
)
DIMENSIONS = COUNSELOR_DIMENSIONS + CLIENT_DIMENSIONS + ("simulation_fidelity",)


def _validated_assessment(value: object) -> RolloutAssessment:
    # Revalidate even model instances: model_copy/model_construct can bypass
    # Pydantic validation, including for nested scores and evidence.
    if isinstance(value, RolloutAssessment):
        value = value.model_dump()
    assessment = RolloutAssessment.model_validate(value, strict=True)
    for name in DIMENSIONS:
        dimension = getattr(assessment, name)
        if not dimension.reason.strip():
            raise ValueError(f"{name}: reason must not be blank")
        if any(not item.quote.strip() for item in dimension.evidence):
            raise ValueError(f"{name}: evidence quote must not be blank")
    if not assessment.safety_reason.strip():
        raise ValueError("safety_reason must not be blank")
    return assessment


def _public_memory(memory: SessionMemory) -> dict:
    """Whitelist disclosed context, without IDs or internal assessments.

    Opaque summaries, evolving profiles, supervisor feedback, risk/state
    histories and skill histories are deliberately not judge inputs. Facts
    already admitted to unlocked_client_info are the disclosure boundary.
    """
    profile = memory.unlocked_client_info
    return deepcopy({
        "unlocked_client_info": {
            "static_traits": profile.static_traits.model_dump(
                mode="json", exclude={"language_features"}
            ),
            "main_problem": profile.main_problem,
            "topic": profile.topic,
            "core_demands": profile.core_demands,
            "growth_experiences": list(profile.growth_experiences),
            "facts": [{"content": fact.content} for fact in profile.facts],
            "theory": deepcopy(profile.theory),
        },
        "unresolved_topics": memory.unresolved_topics,
        "homework": memory.homework,
        "last_client_closing": memory.last_client_closing,
    })


class SessionRolloutEvaluator:
    """Judge one complete session using only public, attributable evidence."""

    def __init__(self, gateway: ModelGateway, config: RFTConfig) -> None:
        self.gateway = gateway
        self.config = config

    async def evaluate(
        self, session: SessionRecord, memory_before: SessionMemory
    ) -> RolloutAssessment:
        dialogue = [
            {"message_index": index, "role": message.role, "content": message.content}
            for index, message in enumerate(session.messages)
            if message.role in {"client", "counselor"}
        ]
        # Snapshot the exact sources before awaiting a shared gateway; neither
        # filtered positions nor turn_index identify an evidence source.
        sources = {
            item["message_index"]: (item["role"], item["content"])
            for item in dialogue
        }
        if not any(role == "client" for role, _ in sources.values()):
            raise ValueError("session must contain client evidence")
        result = await self.gateway.complete_structured(
            role="supervisor",
            system_prompt=render_prompt(SESSION_JUDGE_TEMPLATE),
            input_payload={
                "dialogue": dialogue,
                "plan": {
                    "stage": session.plan.stage.value,
                    "objectives": list(session.plan.objectives),
                    "therapy": session.plan.therapy,
                },
                "memory": _public_memory(memory_before),
            },
            output_schema=RolloutAssessment,
            temperature=self.config.judge_temperature,
        )
        assessment = _validated_assessment(result)
        for name in DIMENSIONS:
            dimension = getattr(assessment, name)
            has_client_evidence = False
            for evidence in dimension.evidence:
                source = sources.get(evidence.message_index)
                if source is None:
                    raise ValueError(f"{name}: message_index is not a dialogue source")
                role, content = source
                if evidence.quote not in content:
                    raise ValueError(f"{name}: quote is not an exact source substring")
                has_client_evidence |= role == "client"
            if name in CLIENT_DIMENSIONS and not has_client_evidence:
                raise ValueError(f"{name}: at least one client evidence quote is required")
        return assessment


def compute_rollout_reward(
    assessment: RolloutAssessment,
    previous: RolloutReward | None,
    config: RFTConfig,
    *,
    baseline_session_index: int | None = None,
) -> RolloutReward:
    """Compute a research ranking signal, without eligibility/safety filtering.

    The caller supplies the previous winner's session index explicitly.
    previous.baseline_session_index identifies that winner's own baseline,
    so it must never be reused or incremented to infer the current baseline.
    With no previous reward, client scores are stored but do not affect total.
    """
    assessment = _validated_assessment(assessment)
    if baseline_session_index is not None and (
        type(baseline_session_index) is not int or baseline_session_index < 1
    ):
        raise ValueError("baseline_session_index must be a positive integer or None")
    counselor_score = mean(getattr(assessment, name).score for name in COUNSELOR_DIMENSIONS)
    snapshot = {name: getattr(assessment, name).score for name in CLIENT_DIMENSIONS}
    if previous is None:
        return RolloutReward(
            total=counselor_score,
            counselor_score=counselor_score,
            client_snapshot=snapshot,
        )

    previous = RolloutReward.model_validate(previous.model_dump(), strict=True)
    if set(previous.client_snapshot) != set(CLIENT_DIMENSIONS):
        raise ValueError("previous client_snapshot must contain exactly the three client dimensions")
    if any(
        not isfinite(value) or not 0 <= value <= 10
        for value in previous.client_snapshot.values()
    ):
        raise ValueError("previous client_snapshot scores must be finite and within 0-10")
    delta = mean(snapshot[name] - previous.client_snapshot[name] for name in CLIENT_DIMENSIONS)
    gain = 5 + delta / 2
    total = config.counselor_weight * counselor_score + (1 - config.counselor_weight) * gain
    return RolloutReward(
        total=total,
        counselor_score=counselor_score,
        client_snapshot=snapshot,
        client_delta=delta,
        client_gain_score=gain,
        baseline_session_index=baseline_session_index,
    )
