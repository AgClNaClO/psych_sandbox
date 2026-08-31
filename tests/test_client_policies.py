from __future__ import annotations

import asyncio

from psychsandbox.agents import ClientAgent
from psychsandbox.client_simulation import ClientPolicyInput
from psychsandbox.client_simulation.policies import FaithfulPatientActPolicy
from psychsandbox.domain import (
    ClientBehaviorType,
    ClientReactionType,
    DisclosureDecision,
    ReactionIntensity,
    ResistancePatternType,
    TrustChange,
)
from psychsandbox.model_client import ModelGateway


class FaithfulGateway(ModelGateway):
    provider_name = "faithful-test"

    def __init__(self, *, resistance: bool):
        self.resistance = resistance
        self.steps: list[str] = []

    async def complete_structured(self, **kwargs):
        step = kwargs["input_payload"]["decision_step"]
        self.steps.append(step)
        schema = kwargs["output_schema"]
        if step == "reaction":
            return schema(
                reaction=ClientReactionType.CHALLENGED,
                intensity=ReactionIntensity.MODERATE,
            )
        if step == "behavior":
            return schema(
                behavior=(
                    ClientBehaviorType.RESISTANCE
                    if self.resistance else ClientBehaviorType.SIMPLE_RESPONSE
                )
            )
        if step == "resistance":
            return schema(resistance_pattern=ResistancePatternType.DEFENSIVENESS)
        return schema(trust_change=TrustChange.SLIGHT_DECREASE)


def _input(sample_case):
    return ClientPolicyInput(
        profile=sample_case.profile,
        state=sample_case.profile.initial_state,
        counselor_message="我们可以慢一点。",
        recent_messages=[],
        disclosure=DisclosureDecision(),
        recent_signals=[],
        turn_index=1,
    )


def test_faithful_policy_runs_conditional_resistance_stage(sample_case):
    gateway = FaithfulGateway(resistance=True)
    signal = asyncio.run(
        FaithfulPatientActPolicy(ClientAgent(gateway)).plan_turn(_input(sample_case))
    )

    assert gateway.steps == ["reaction", "behavior", "resistance", "trust"]
    assert signal.resistance_pattern is ResistancePatternType.DEFENSIVENESS
    assert signal.policy == "faithful_patientact"
    assert signal.planning_model_calls == 4


def test_faithful_policy_skips_resistance_stage_for_other_behaviors(sample_case):
    gateway = FaithfulGateway(resistance=False)
    signal = asyncio.run(
        FaithfulPatientActPolicy(ClientAgent(gateway)).plan_turn(_input(sample_case))
    )

    assert gateway.steps == ["reaction", "behavior", "trust"]
    assert signal.resistance_pattern is None
    assert signal.planning_model_calls == 3
