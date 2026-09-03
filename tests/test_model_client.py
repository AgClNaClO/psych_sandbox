from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
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


def test_embedding_gateway_uses_separate_config_batches_and_response_indices(monkeypatch):
    import openai

    requests = []
    clients = []

    class FakeEmbeddingClient:
        def __init__(self, **kwargs):
            self.config = kwargs
            self.closed = False
            self.embeddings = self
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def create(self, **kwargs):
            requests.append(kwargs)
            rows = [SimpleNamespace(index=index, embedding=[float(text), 1.])
                    for index, text in enumerate(kwargs["input"])]
            return SimpleNamespace(data=list(reversed(rows)))

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeEmbeddingClient)
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-embedding-key")
    monkeypatch.setenv("MODEL_API_KEY", "dummy-chat-key")
    gateway = object.__new__(OpenAICompatibleGateway)
    vectors = asyncio.run(gateway.embed_texts([str(i) for i in range(65)]))
    assert vectors == [[float(i), 1.] for i in range(65)]
    assert [len(request["input"]) for request in requests] == [64, 1]
    assert all(request["model"] == "test-embedding" for request in requests)
    assert all(request["encoding_format"] == "float" for request in requests)
    assert clients[0].config["api_key"] == "dummy-embedding-key"
    assert clients[0].config["base_url"] == "https://embedding.example.test/v1"
    assert clients[0].closed
    identity = gateway.embedding_identity
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://other.example.test/v1")
    assert identity != gateway.embedding_identity


def test_large_query_requires_explicit_embedding_config(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "https://chat.example.test/v1")
    for name in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    gateway = object.__new__(OpenAICompatibleGateway)
    assert asyncio.run(gateway.embed_texts([])) == []
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    with pytest.raises(RuntimeError, match="EMBEDDING_BASE_URL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))


ECNU_BASE_URL = "https://chat.ecnu.edu.cn/open/api/v1"


@pytest.fixture
def embedding_gateway(monkeypatch):
    import openai

    clients, requests = [], []

    class FakeEmbeddingClient:
        def __init__(self, **kwargs):
            self.config = kwargs
            self.embeddings = self
            self.closed = False
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def create(self, **kwargs):
            requests.append(kwargs)
            rows = [SimpleNamespace(index=i, embedding=[float(len(text))])
                    for i, text in enumerate(kwargs["input"])]
            return SimpleNamespace(data=list(reversed(rows)))

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeEmbeddingClient)
    monkeypatch.setenv("MODEL_BASE_URL", ECNU_BASE_URL)
    monkeypatch.setenv("MODEL_API_KEY", "dummy-chat-key")
    for name in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return object.__new__(OpenAICompatibleGateway), clients, requests


@pytest.mark.parametrize("base_url", [
    ECNU_BASE_URL, ECNU_BASE_URL + "/",
    "https://CHAT.ECNU.EDU.CN:443/open/api/v1/",
])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_ecnu_embedding_defaults(monkeypatch, embedding_gateway, base_url, blank):
    gateway, clients, requests = embedding_gateway
    monkeypatch.setenv("MODEL_BASE_URL", base_url)
    if blank is not None:
        for name in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"):
            monkeypatch.setenv(name, blank)
    assert gateway.embedding_model == "ecnu-embedding-small"
    assert asyncio.run(gateway.embed_texts(["公开话语"])) == [[4.]]
    assert clients[0].config["base_url"] == ECNU_BASE_URL
    assert clients[0].config["api_key"] == "dummy-chat-key"
    assert clients[0].closed
    assert requests == [{
        "model": "ecnu-embedding-small", "input": ["公开话语"], "encoding_format": "float",
    }]


@pytest.mark.parametrize("model", [None, "explicit-embedding-model"])
@pytest.mark.parametrize("key", [None, "dummy-explicit-key"])
@pytest.mark.parametrize("endpoint", [None, ECNU_BASE_URL + "/"])
def test_ecnu_explicit_embedding_fields_take_priority(
    monkeypatch, embedding_gateway, model, key, endpoint,
):
    gateway, clients, requests = embedding_gateway
    for name, value in [("EMBEDDING_MODEL", model), ("EMBEDDING_API_KEY", key),
                        ("EMBEDDING_BASE_URL", endpoint)]:
        if value is not None:
            monkeypatch.setenv(name, value)
    asyncio.run(gateway.embed_texts(["公开话语"]))
    assert requests[0]["model"] == (model or "ecnu-embedding-small")
    assert clients[0].config["api_key"] == (key or "dummy-chat-key")
    assert clients[0].config["base_url"] == ECNU_BASE_URL


NON_OFFICIAL_ENDPOINTS = [
    "https://other.example.test/v1",
    "http://chat.ecnu.edu.cn/open/api/v1",
    "https://chat.ecnu.edu.cn:444/open/api/v1",
    "https://chat.ecnu.edu.cn/v1",
    ECNU_BASE_URL + "/other",
    ECNU_BASE_URL + "//",
    ECNU_BASE_URL + "?target=other",
    ECNU_BASE_URL + "#other",
    "https://chat.ecnu.edu.cn.evil.test/open/api/v1",
    "https://chat.ecnu.edu.cn@evil.test/open/api/v1",
    "https://user@chat.ecnu.edu.cn/open/api/v1",
    "https://evil.test/chat.ecnu.edu.cn/open/api/v1",
    "https://chat.ecnu.edu.cn/open/api/../api/v1",
]


@pytest.mark.parametrize("endpoint", NON_OFFICIAL_ENDPOINTS)
def test_non_ecnu_chat_requires_independent_embedding_config(
    monkeypatch, embedding_gateway, endpoint,
):
    gateway, clients, _ = embedding_gateway
    monkeypatch.setenv("MODEL_BASE_URL", endpoint)
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    with pytest.raises(RuntimeError, match="EMBEDDING_BASE_URL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_BASE_URL", ECNU_BASE_URL)
    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients == []


@pytest.mark.parametrize("endpoint", NON_OFFICIAL_ENDPOINTS)
def test_ecnu_chat_key_never_inherits_to_other_embedding_endpoints(
    monkeypatch, embedding_gateway, endpoint,
):
    gateway, clients, requests = embedding_gateway
    monkeypatch.setenv("EMBEDDING_BASE_URL", endpoint)
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_MODEL", "explicit-embedding")
    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients == []
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-independent-key")
    asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients[0].config["api_key"] == "dummy-independent-key"
    assert clients[0].config["base_url"] == endpoint
    assert requests[0]["model"] == "explicit-embedding"


def test_non_ecnu_chat_cannot_supply_embedding_model_or_key(monkeypatch, embedding_gateway):
    gateway, clients, requests = embedding_gateway
    monkeypatch.setenv("MODEL_BASE_URL", "https://other.example.test/v1")
    monkeypatch.setenv("EMBEDDING_BASE_URL", ECNU_BASE_URL)
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_MODEL", "ecnu-embedding-small")
    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-ecnu-key")
    asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients[0].config["api_key"] == "dummy-ecnu-key"
    assert requests[0]["model"] == "ecnu-embedding-small"


def test_ecnu_missing_chat_key_does_not_create_embedding_client(monkeypatch, embedding_gateway):
    gateway, clients, _ = embedding_gateway
    monkeypatch.delenv("MODEL_API_KEY")
    assert asyncio.run(gateway.embed_texts([])) == []
    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients == []


@pytest.mark.parametrize("missing", ["EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"])
def test_other_same_endpoint_still_requires_all_embedding_fields(
    monkeypatch, embedding_gateway, missing,
):
    gateway, clients, _ = embedding_gateway
    endpoint = "https://other.example.test/v1"
    monkeypatch.setenv("MODEL_BASE_URL", endpoint)
    for name, value in [("EMBEDDING_MODEL", "other-embedding"),
                        ("EMBEDDING_BASE_URL", endpoint), ("EMBEDDING_API_KEY", "dummy-key")]:
        if name != missing:
            monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=missing):
        asyncio.run(gateway.embed_texts(["公开话语"]))
    assert clients == []


def test_embedding_identity_uses_resolved_endpoint_and_model(monkeypatch, embedding_gateway):
    gateway, _, _ = embedding_gateway
    implicit = gateway.embedding_identity
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://CHAT.ECNU.EDU.CN:443/open/api/v1/")
    monkeypatch.setenv("EMBEDDING_MODEL", "ecnu-embedding-small")
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-explicit-key")
    assert gateway.embedding_identity == implicit
    monkeypatch.setenv("EMBEDDING_MODEL", "other-embedding")
    other_model = gateway.embedding_identity
    assert other_model != implicit
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://other.example.test/v1")
    assert gateway.embedding_identity != other_model


@pytest.mark.parametrize("texts, sizes", [
    (["中" * 4096, "文" * 4096, "尾"], [2, 1]),
    (["a" * 8192, "🙂" * 8192], [1, 1]),
    (["中" * 3000] * 5, [2, 2, 1]),
    ([str(i) for i in range(65)], [64, 1]),
    (["中" * 128] * 65, [64, 1]),
])
@pytest.mark.parametrize("explicit", [False, True])
def test_ecnu_embedding_batches_obey_character_and_item_limits(
    monkeypatch, embedding_gateway, texts, sizes, explicit,
):
    gateway, clients, requests = embedding_gateway
    if explicit:
        monkeypatch.setenv("MODEL_BASE_URL", "https://other.example.test/v1")
        monkeypatch.setenv("EMBEDDING_BASE_URL", ECNU_BASE_URL)
        monkeypatch.setenv("EMBEDDING_MODEL", "ecnu-embedding-small")
        monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-ecnu-key")
    vectors = asyncio.run(gateway.embed_texts(texts))
    assert vectors == [[float(len(text))] for text in texts]
    assert [len(request["input"]) for request in requests] == sizes
    assert all(sum(map(len, request["input"])) <= 8192 for request in requests)
    assert [text for request in requests for text in request["input"]] == texts
    assert clients[0].closed


def test_ecnu_oversized_single_input_fails_before_any_request(embedding_gateway):
    gateway, clients, requests = embedding_gateway
    with pytest.raises(ValueError, match=r"index 64.*8192"):
        asyncio.run(gateway.embed_texts(["公开话语"] * 64 + ["中" * 8193]))
    assert clients == []
    assert requests == []


def test_other_embedding_service_retains_original_length_behavior(monkeypatch, embedding_gateway):
    gateway, _, requests = embedding_gateway
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://other.example.test/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "other-embedding")
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-independent-key")
    texts = ["中" * 8193, "文" * 8193]
    assert asyncio.run(gateway.embed_texts(texts)) == [[8193.], [8193.]]
    assert len(requests) == 1
    assert requests[0]["input"] == texts


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


def test_parallel_api_diagnostics_keep_candidate_scope_and_request_metadata(tmp_path):
    from psychsandbox.model_client import model_diagnostic_scope

    gateway, _ = _gateway(tmp_path, [])
    gateway.models.update(counselor="A", supervisor="B")
    gateway.json_schema_roles = {"supervisor"}
    gateway.json_object_roles = {"counselor"}
    first_started, second_started = asyncio.Event(), asyncio.Event()

    class InterleavedCompletions:
        async def create(self, **request):
            if request["temperature"] == 0.1:
                text = '{"value": 2}'
            else:
                if request["model"] == "A":
                    first_started.set()
                    await second_started.wait()
                else:
                    await first_started.wait()
                    second_started.set()
                text = '{"value":'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    gateway.client.chat.completions = InterleavedCompletions()

    async def call(role, temperature):
        with model_diagnostic_scope(tmp_path / role):
            return await gateway.complete_structured(
                role=role, system_prompt="JSON", input_payload={},
                output_schema=ExampleOutput, temperature=temperature,
            )

    async def scenario():
        return await asyncio.gather(call("counselor", 0.8), call("supervisor", 0.4))

    assert [r.value for r in asyncio.run(scenario())] == [2, 2]
    for role, temperature, response_format in [("counselor", 0.8, "json_object"), ("supervisor", 0.4, "json_schema")]:
        paths = list((tmp_path / role).glob("*.json"))
        assert len(paths) == 1
        assert json.loads(paths[0].read_text(encoding="utf-8"))["request"] == {
            "temperature": temperature, "response_format": response_format,
        }
    assert not gateway.diagnostic_dir.exists()


class SingleStringField(BaseModel):
    content: str


@pytest.mark.parametrize("payload", [
    {"items": "not-a-list"},
    {"items": [{"item": 1, "score": 4.0}]},
    {"items": [{"item": "1", "score": "four"}]},
])
def test_scale_raw_json_is_validated_before_gateway_coercion(tmp_path, payload):
    from psychsandbox.domain import ScaleItems

    raw = json.dumps(payload)
    gateway, completions = _gateway(tmp_path, [raw, raw])
    with pytest.raises(ValueError, match="failed ScaleItems"):
        asyncio.run(gateway.complete_structured(
            role="supervisor", system_prompt="JSON", input_payload={},
            output_schema=ScaleItems, temperature=0,
        ))
    assert len(completions.calls) == 2


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
