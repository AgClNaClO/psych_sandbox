from __future__ import annotations

import asyncio

import pytest

from psychsandbox.domain import LogprobScoringConfig
from psychsandbox.evaluation import psycheval_supervisor as scoring
from psychsandbox.evaluation.psycheval_supervisor import PsychEvalSupervisor, instrument_registry
from psychsandbox.logprob import LogprobScoringUnsupported
from tests.test_logprob_scoring import ScriptedSupervisorGateway


@pytest.mark.parametrize("therapy,requests", [
    ("behavioral", 15), ("cbt", 17), ("humanistic_existential", 24),
    ("psychodynamic", 18), ("postmodern", 12),
])
@pytest.mark.parametrize("logprobs", [False, True])
def test_parallel_scoring_matches_serial_formulas_order_and_audits(root, monkeypatch, therapy, requests, logprobs):
    class YieldingGateway(ScriptedSupervisorGateway):
        active = peak = 0

        async def complete_structured(self, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0)
                assert kwargs["input_payload"] == {}
                assert kwargs["system_prompt"].count("UNIQUE_INTAKE_MARKER") == 1
                assert kwargs["system_prompt"].count("UNIQUE_DIALOGUE_MARKER") == 1
                return await super().complete_structured(**kwargs)
            finally:
                self.active -= 1

        async def complete_item_ratings(self, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0)
                return await super().complete_item_ratings(**kwargs)
            finally:
                self.active -= 1

    def perform():
        gateway = YieldingGateway(probabilities={2: .4, 4: .6})
        supervisor = PsychEvalSupervisor(gateway, root / "prompts/eval",
            logprob_scoring=LogprobScoringConfig(enabled=logprobs))
        ticks = []
        groups = asyncio.run(supervisor._score_instruments(
            therapy, "UNIQUE_INTAKE_MARKER", "UNIQUE_DIALOGUE_MARKER",
            on_step=lambda done, total, key: ticks.append((done, total, key)),
        ))
        assert len(gateway.rating_calls or gateway.structured_calls) == requests
        assert [done for done, _, _ in ticks] == list(range(1, 10))
        assert len({key for _, _, key in ticks}) == 9
        assert gateway.active == 0
        return [[score.model_dump() for score in group] for group in groups], gateway.peak

    parallel, peak = perform()

    async def serial(coroutines):
        return [await coroutine for coroutine in coroutines]

    monkeypatch.setattr(scoring, "gather_and_drain", serial)
    sequential, serial_peak = perform()
    assert parallel == sequential
    assert peak > 1 and serial_peak == 1


def test_subprompts_run_together_and_failure_cancels_remaining_files(root):
    started = set()
    stopped = set()
    all_started = asyncio.Event()
    supervisor = PsychEvalSupervisor(ScriptedSupervisorGateway(), root / "prompts/eval")
    instrument = instrument_registry("cbt")["ctrs"]

    async def collect(relative, intake, dialogue, *, records):
        started.add(relative)
        if len(started) == len(instrument.prompt_files):
            all_started.set()
        try:
            await asyncio.wait_for(all_started.wait(), 2)
            if relative == instrument.prompt_files[0]:
                raise LogprobScoringUnsupported("missing item distribution")
            await asyncio.Event().wait()
        finally:
            stopped.add(relative)

    supervisor._collect_items = collect
    with pytest.raises(LogprobScoringUnsupported, match="missing item distribution"):
        asyncio.run(supervisor._score(instrument, "intake", "dialogue"))
    assert started == stopped == set(instrument.prompt_files)


def test_whole_scoring_pass_drains_other_instruments_on_failure(root):
    supervisor = PsychEvalSupervisor(ScriptedSupervisorGateway(), root / "prompts/eval")
    running = 0
    ready = asyncio.Event()

    async def collect(relative, intake, dialogue, *, records=None):
        nonlocal running
        running += 1
        if running == 24:
            ready.set()
        try:
            await asyncio.wait_for(ready.wait(), 2)
            if relative == "wai/wai.txt":
                raise ValueError("invalid scale JSON")
            await asyncio.Event().wait()
        finally:
            running -= 1

    supervisor._collect_items = collect
    with pytest.raises(ValueError, match="invalid scale JSON"):
        asyncio.run(supervisor._score_instruments("humanistic_existential", "i", "d"))
    assert running == 0
