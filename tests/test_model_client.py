from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from pydantic import BaseModel

from psychsandbox.model_client import (
    OpenAICompatibleGateway,
    _json_object_roles,
    _lenient_parse,
    _structured_output_roles,
)


class ExampleOutput(BaseModel):
    value: int


class FakeCompletions:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = next(self.responses)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def _gateway(tmp_path, responses: list[str]) -> tuple[
    OpenAICompatibleGateway, FakeCompletions
]:
    completions = FakeCompletions(responses)
    gateway = object.__new__(OpenAICompatibleGateway)
    gateway.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    gateway.models = {
        "client": "ecnu-plus",
        "counselor": "ecnu-plus",
        "supervisor": "ecnu-plus",
        "summarizer": "ecnu-plus",
    }
    gateway.json_schema_roles = {
        "client", "counselor", "supervisor", "summarizer"
    }
    gateway.max_tokens = 2048
    gateway.diagnostic_dir = tmp_path / "diagnostics"
    return gateway, completions


def test_api_gateway_uses_json_schema(tmp_path):
    gateway, completions = _gateway(tmp_path, ['{"value": 7}'])

    result = asyncio.run(
        gateway.complete_structured(
            role="counselor",
            system_prompt="Return JSON.",
            input_payload={"subject": "test"},
            output_schema=ExampleOutput,
            temperature=0.1,
        )
    )

    assert result.value == 7
    request = completions.calls[0]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["name"] == "ExampleOutput"
    assert request["response_format"]["json_schema"]["schema"]["required"] == ["value"]
    assert request["max_tokens"] == 2048


def test_api_gateway_uses_json_object_for_non_schema_role(tmp_path):
    gateway, completions = _gateway(tmp_path, ['{"value": 3}'])
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {"counselor"}

    result = asyncio.run(
        gateway.complete_structured(
            role="counselor",
            system_prompt="Return JSON.",
            input_payload={"subject": "test"},
            output_schema=ExampleOutput,
            temperature=0.1,
        )
    )

    assert result.value == 3
    request = completions.calls[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "json_schema" not in request["response_format"]


def test_non_schema_role_retries_with_low_temp_and_json_schema(tmp_path):
    invalid = "这不是 JSON"
    gateway, completions = _gateway(tmp_path, [invalid, '{"value": 5}'])
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {"counselor"}

    result = asyncio.run(
        gateway.complete_structured(
            role="counselor",
            system_prompt="Return JSON.",
            input_payload={"subject": "test"},
            output_schema=ExampleOutput,
            temperature=0.8,
        )
    )

    assert result.value == 5
    first_request = completions.calls[0]
    second_request = completions.calls[1]
    assert first_request["response_format"] == {"type": "json_object"}
    assert first_request["temperature"] == 0.8
    assert second_request["response_format"]["type"] == "json_schema"
    assert second_request["temperature"] == 0.1
    retry_payload = json.loads(second_request["messages"][1]["content"])
    assert retry_payload["invalid_previous_output"] == invalid


def test_api_gateway_retries_with_invalid_output_and_writes_diagnostic(tmp_path):
    invalid = '{"value": 1'
    gateway, completions = _gateway(tmp_path, [invalid, '{"value": 2}'])

    result = asyncio.run(
        gateway.complete_structured(
            role="counselor",
            system_prompt="Return JSON.",
            input_payload={"subject": "test"},
            output_schema=ExampleOutput,
            temperature=0.1,
        )
    )

    assert result.value == 2
    retry_payload = json.loads(completions.calls[1]["messages"][1]["content"])
    assert retry_payload["invalid_previous_output"] == invalid
    assert "validation_error" in retry_payload
    diagnostics = list(gateway.diagnostic_dir.glob("*.json"))
    assert len(diagnostics) == 1
    diagnostic = json.loads(diagnostics[0].read_text(encoding="utf-8"))
    assert diagnostic["raw_response"] == invalid


class SingleStringField(BaseModel):
    content: str


class MultiField(BaseModel):
    content: str
    count: int


def test_lenient_parse_wraps_single_required_string_field():
    result = _lenient_parse(SingleStringField, "这是纯文本")
    assert result is not None
    assert result.content == "这是纯文本"


def test_lenient_parse_rejects_schema_with_multiple_required_fields():
    assert _lenient_parse(MultiField, "这是纯文本") is None


def test_lenient_parse_rejects_empty_text():
    assert _lenient_parse(SingleStringField, "   ") is None


def test_ecnu_auto_structured_output_is_model_aware():
    roles = _structured_output_roles(
        mode="auto",
        base_url="https://chat.ecnu.edu.cn/open/api/v1",
        models={
            "client": "ecnu-plus",
            "counselor": "ecnu-max",
            "supervisor": "ecnu-turbo",
        },
    )

    assert roles == {"client", "supervisor"}


def test_ecnu_auto_json_object_roles_fill_the_remainder():
    json_schema_roles = {"client", "supervisor"}
    roles = _json_object_roles(
        mode="auto",
        models={
            "client": "ecnu-plus",
            "counselor": "ecnu-max",
            "supervisor": "ecnu-turbo",
            "summarizer": "ecnu-max",
        },
        json_schema_roles=json_schema_roles,
    )

    assert roles == {"counselor", "summarizer"}


def test_json_object_roles_empty_when_strict_mode_or_off():
    models = {"client": "ecnu-plus", "counselor": "ecnu-max"}

    assert _json_object_roles(
        mode="json_schema", models=models, json_schema_roles={"client", "counselor"}
    ) == set()
    assert _json_object_roles(
        mode="off", models=models, json_schema_roles=set()
    ) == set()


def test_explicit_json_schema_mode_applies_to_all_models():
    roles = _structured_output_roles(
        mode="json_schema",
        base_url="https://example.com/v1",
        models={"client": "model-a", "counselor": "model-b"},
    )

    assert roles == {"client", "counselor"}
