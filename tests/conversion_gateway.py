"""Test-only extractive gateway with observable concurrency and optional latency."""
import asyncio

from psychsandbox.model_client import ModelGateway


class ConversionGateway(ModelGateway):
    provider_name = "conversion-test-double"

    def __init__(self, delay=0.001, fail_text="", entered=None):
        self.models = {"profile": "conversion-test-double"}
        self.delay = delay
        self.fail_text = fail_text
        self.entered = entered
        self.requests = []
        self.active = 0
        self.peak = 0

    async def complete_structured(self, **kwargs):
        payload = kwargs["input_payload"]
        self.requests.append(dict(payload))
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.entered and self.active >= 4:
            self.entered.set()
        try:
            await asyncio.sleep(self.delay)
            text = payload["source_text"]
            if text == self.fail_text:
                raise RuntimeError("test-only extraction failure")
            kind = {"growth": "event", "language": "case_fact",
                    "core_demands": "client_goal", "five_ps": "case_fact"}[payload["purpose"]]
            return kwargs["output_schema"].model_validate({"spans": [{
                "start": 0, "end": len(text), "text": text, "kind": kind,
                "trust_tier": "sensitive", "activation_tags": [],
            }]})
        finally:
            self.active -= 1
