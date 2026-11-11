from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from tenacity import wait_none

from psychsandbox.model_client import (
    DEFAULT_MAX_ATTEMPTS,
    ECNU_EMBEDDING_MAX_BATCH,
    OpenAICompatibleGateway,
    _json_object_roles,
    _lenient_parse,
    _max_attempts_from_env,
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
    gateway.max_attempts = DEFAULT_MAX_ATTEMPTS
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
    gateway.max_attempts = DEFAULT_MAX_ATTEMPTS
    gateway.diagnostic_dir = None
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
    gateway = object.__new__(OpenAICompatibleGateway)
    gateway.max_attempts = DEFAULT_MAX_ATTEMPTS
    gateway.diagnostic_dir = None
    return gateway, clients, requests


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
    ([str(i) for i in range(65)], [32, 32, 1]),
    (["中" * 128] * 65, [32, 32, 1]),
    (["短句"] * 100, [32, 32, 32, 4]),
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
    # The measured ChatECNU endpoint answers HTTP 500 from the 33rd input on.
    assert all(len(request["input"]) <= ECNU_EMBEDDING_MAX_BATCH for request in requests)
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


@pytest.mark.parametrize("response_format", ["json_object", None])
def test_non_schema_role_retries_with_original_temp_and_format(tmp_path, response_format):
    invalid = "这不是 JSON"
    gateway, completions = _gateway(tmp_path, [invalid, '{"value": 5}'])
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {"counselor"} if response_format else set()

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
    expected_format = {"type": response_format} if response_format else None
    assert first_request.get("response_format") == expected_format
    assert first_request["temperature"] == 0.8
    assert second_request.get("response_format") == expected_format
    assert second_request["temperature"] == 0.8
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


@pytest.mark.parametrize("malformed_repair", [
    '{"session_summary":{"session_index":1,"important_results":["能描述感受"]}',
    '{"session_summary":{"session_index":1,"session_summary_abstract":"重复' + "重复" * 100,
], ids=["unclosed-object", "unterminated-repetition"])
def test_summary_recovers_after_repair_fails_without_reusing_bad_output(tmp_path, malformed_repair):
    from psychsandbox.runtime.memory_pipeline import DialogueSummaryAgent
    from tests.test_session_controls import record

    invalid = json.dumps({"session_summary": {
        "session_index": 1, "goal_assessment": {"objective_recap_note": None},
    }}, ensure_ascii=False)
    valid = {"session_summary": {
        "session_index": 1, "important_results": ["能描述感受"],
        "pending_items": ["继续核对感受"],
    }}
    gateway, completions = _gateway(tmp_path, [invalid, malformed_repair, json.dumps(valid)])
    gateway.models["summarizer"] = "ecnu-max"
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {"summarizer"}
    session = record()

    summary = asyncio.run(DialogueSummaryAgent(gateway).summarize(
        1, session.messages, session.plan, [session.plan.therapy],
    ))

    assert summary.important_results == ["能描述感受"]
    assert summary.pending_items == ["继续核对感受"]
    assert len(completions.calls) == 3
    assert all(call["response_format"] == {"type": "json_object"} for call in completions.calls)
    first, repair, regeneration = [json.loads(call["messages"][1]["content"]) for call in completions.calls]
    assert repair["invalid_previous_output"] == invalid
    assert "invalid_previous_output" not in regeneration
    assert regeneration["dialogue"] == first["dialogue"]
    assert regeneration["plan"] == first["plan"]
    assert regeneration["memory_items"] == first["memory_items"]
    prompt = completions.calls[0]["messages"][0]["content"]
    example = json.loads(prompt.split("【输出结构示例（空值仅展示类型；按本场证据填写）】\n", 1)[1].splitlines()[0])
    assert example["session_summary"]["important_results"] == []
    assert set(example["session_summary"]["goal_assessment"]) == {
        "objective_recap", "completion_status", "evidence_and_analysis",
    }
    assert "pending_items" in example["session_summary"]
    diagnostics = [json.loads(path.read_text(encoding="utf-8")) for path in gateway.diagnostic_dir.glob("*.json")]
    assert sorted(record["attempt"] for record in diagnostics) == [1, 2]
    assert {record["raw_response"] for record in diagnostics} == {invalid, malformed_repair}


@pytest.mark.parametrize("reason", ["length", "oversized"])
def test_retry_regenerates_instead_of_sending_partial_previous_output(tmp_path, reason):
    invalid = '{"value":' if reason == "length" else json.dumps({"value": "x" * 12001})
    gateway, completions = _gateway(tmp_path, [invalid, '{"value":7}'])
    original_create = completions.create

    async def create(**request):
        result = await original_create(**request)
        result.choices[0].finish_reason = "length" if reason == "length" and len(completions.calls) == 1 else "stop"
        return result

    completions.create = create
    result = asyncio.run(gateway.complete_structured(
        role="counselor", system_prompt="JSON", input_payload={"subject": "保留原始输入"},
        output_schema=ExampleOutput, temperature=0,
    ))
    assert result.value == 7
    retry = json.loads(completions.calls[1]["messages"][1]["content"])
    assert "invalid_previous_output" not in retry
    assert retry["subject"] == "保留原始输入"
    assert "重新生成" in retry["repair_instruction"]
    diagnostic = json.loads(next(gateway.diagnostic_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert diagnostic["raw_response"] == invalid
    if reason == "length":
        assert "finish_reason=length" in diagnostic["error"]


def test_token_limited_response_cannot_pass_validation_or_lenient_fallback(tmp_path):
    raw = '{"content":"表面完整但已达到输出上限"}'
    gateway, completions = _gateway(tmp_path, [raw] * 3)
    original_create = completions.create

    async def create(**request):
        result = await original_create(**request)
        result.choices[0].finish_reason = "length"
        return result

    completions.create = create
    with pytest.raises(ValueError, match="finish_reason=length"):
        asyncio.run(gateway.complete_structured(
            role="client", system_prompt="JSON", input_payload={},
            output_schema=SingleStringField, temperature=0,
        ))
    assert len(completions.calls) == 3
    diagnostics = [json.loads(path.read_text(encoding="utf-8")) for path in gateway.diagnostic_dir.glob("*.json")]
    assert {record["attempt"] for record in diagnostics} == {1, 2, 3}
    assert all(record["request"]["finish_reason"] == "length" for record in diagnostics)


@pytest.mark.parametrize("field", [
    "homework", "important_information", "important_methods",
    "important_results", "completed_items", "pending_items",
])
def test_summary_scalar_text_is_preserved_verbatim_as_one_array_item(tmp_path, field):
    from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper

    text = '保留原话：“我愿意试试”；不按标点拆分。\n也不删除第二行。'
    raw = json.dumps({"session_summary": {"session_index": 5, field: text}}, ensure_ascii=False)
    gateway, completions = _gateway(tmp_path, [raw])
    result = asyncio.run(gateway.complete_structured(
        role="summarizer", system_prompt="JSON", input_payload={},
        output_schema=_SessionSummaryWrapper, temperature=0,
    ))
    assert getattr(result.session_summary, field) == [text]
    assert len(completions.calls) == 1
    diagnostic = json.loads(next(gateway.diagnostic_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert diagnostic["raw_response"] == raw
    assert diagnostic["error"] == f"local_repair: wrapped string as single-item array: session_summary.{field}"


@pytest.mark.parametrize("defect", [
    {"important_results": "结果", "unknown": "不得丢弃的内容"},
    {"important_results": "结果", "goal_assessment": {"objective_recap_note": None}},
    {"important_results": "结果", "homework_assignments": "缺少作业证据"},
    {"important_results": [42]},
])
def test_summary_array_repair_does_not_bypass_other_schema_errors(tmp_path, defect):
    from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper

    raw = json.dumps({"session_summary": {"session_index": 5, **defect}}, ensure_ascii=False)
    gateway, completions = _gateway(tmp_path, [raw] * 3)
    with pytest.raises(ValueError, match="failed _SessionSummaryWrapper"):
        asyncio.run(gateway.complete_structured(
            role="summarizer", system_prompt="JSON", input_payload={},
            output_schema=_SessionSummaryWrapper, temperature=0,
        ))
    assert len(completions.calls) == 3
    records = [json.loads(path.read_text(encoding="utf-8")) for path in gateway.diagnostic_dir.glob("*.json")]
    assert len(records) == 3
    assert all(record["raw_response"] == raw for record in records)


@pytest.mark.parametrize("existing", ["absent", "identical", "conflicting"])
def test_summary_repairs_known_sibling_nesting_only_without_conflicts(tmp_path, existing):
    from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper

    siblings = {
        "client_state_analysis": {"affective_state": "能描述感受"},
        "important_information": ["来访者描述本周困扰"],
        "important_methods": ["开放询问"],
        "important_results": "能描述感受",
        "completed_items": ["核对状态"],
        "pending_items": ["继续探索"],
        "item_updates": [{"item_id": "topic-1", "status": "open", "evidence": "仍需跟进"}],
        "homework": [], "homework_assignments": [],
    }
    summary = {"session_index": 5, "goal_assessment": {
        "objective_recap": "澄清感受", "completion_status": "部分完成",
        "evidence_and_analysis": "能描述感受", **siblings,
    }}
    if existing != "absent":
        summary.update(siblings)
    if existing == "conflicting":
        summary["pending_items"] = ["冲突的待办，不能自动取舍"]
    raw = json.dumps({"session_summary": summary}, ensure_ascii=False)
    gateway, completions = _gateway(tmp_path, [raw] * 3)
    call = gateway.complete_structured(
        role="summarizer", system_prompt="JSON", input_payload={},
        output_schema=_SessionSummaryWrapper, temperature=0,
    )
    if existing == "conflicting":
        with pytest.raises(ValueError, match="goal_assessment.pending_items"):
            asyncio.run(call)
        assert len(completions.calls) == 3
        return
    result = asyncio.run(call)
    actual = result.session_summary.model_dump(mode="json", exclude_unset=True)
    for name, value in siblings.items():
        assert actual[name] == ([value] if isinstance(value, str) else value)
    assert actual["goal_assessment"] == {
        "objective_recap": "澄清感受", "completion_status": "部分完成",
        "evidence_and_analysis": "能描述感受",
    }
    assert len(completions.calls) == 1
    diagnostic = json.loads(next(gateway.diagnostic_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert diagnostic["raw_response"] == raw
    assert diagnostic["error"].startswith("local_repair:")
    assert "session_summary.item_updates" in diagnostic["error"]


def _structured_output_regressions():
    """Synthetic versions of the seven observed failures; no private dialogue."""
    from psychsandbox.domain import CounselorActorOutput, CounselorPlanning
    from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper

    planning = CounselorPlanning(
        reasoning_summary="依据公开对话规划", current_goal="澄清当前感受",
        plan_steps=["开放询问"], action="lookup_skills",
        selected_meta_skill_ids=["psychagent:cbt:meta:17"],
        selection_evidence=[{
            "skill_id": "psychagent:cbt:meta:17", "evidence_quote": "我想聊聊",
            "reason": "来访者愿意探索",
        }],
    ).model_dump(mode="json")
    actor = CounselorActorOutput.model_validate({
        "decision": {"assessment": "有探索意愿", "state_observation": "愿意交流", "strategy": "开放询问"},
        "response": "你想先从哪里聊起？",
    }).model_dump(mode="json")
    summary = _SessionSummaryWrapper.model_validate({
        "session_summary": {"session_index": 2, "goal_assessment": {"completion_status": "部分完成"}},
    }).model_dump(mode="json")

    for field in ["completion_status_note", "objective_notes"]:
        invalid = json.loads(json.dumps(summary))
        invalid["session_summary"]["goal_assessment"][field] = "模型生成的额外内容"
        yield pytest.param("summarizer", _SessionSummaryWrapper, json.dumps(invalid), summary,
                           field, id=f"summary-extra-{field}")
    invalid = json.loads(json.dumps(summary))
    invalid["session_summary"]["pending_items"] = ["已有待办"]
    invalid["session_summary"]["goal_assessment"]["pending_items"] = ["冲突的待办"]
    yield pytest.param("summarizer", _SessionSummaryWrapper, json.dumps(invalid), summary,
                       "goal_assessment.pending_items", id="summary-wrong-nesting")
    invalid = json.loads(json.dumps(summary))
    invalid["session_summary"]["goal_assessment"]["objective_recap_note"] = None
    yield pytest.param("summarizer", _SessionSummaryWrapper, json.dumps(invalid), summary,
                       "extra_forbidden", id="summary-null-extra")
    yield pytest.param("summarizer", _SessionSummaryWrapper, json.dumps(summary) + "}", summary,
                       "Extra data", id="summary-extra-brace")
    missing_response = {key: value for key, value in actor.items() if key != "response"}
    yield pytest.param("counselor", CounselorActorOutput, json.dumps(missing_response), actor,
                       "response", id="actor-missing-response")
    malformed = json.dumps(planning, ensure_ascii=False).replace('"reason": "来访者愿意探索"}', '"reason": "来访者愿意探索"')
    yield pytest.param("counselor", CounselorPlanning, malformed, planning,
                       "delimiter", id="planner-unclosed-evidence")
    yield pytest.param("counselor", CounselorPlanning, json.dumps({"type": "json_object", **planning}), planning,
                       "extra_forbidden", id="planner-extra-type")
    translated = {"决策": {"评估": "有探索意愿", "状态观察": "愿意交流", "策略": "开放询问"},
                  "回应": actor["response"], "查询评估": "不需要", "查询拒绝原因": ""}
    yield pytest.param("counselor", CounselorActorOutput, json.dumps(translated), actor,
                       "Field required", id="actor-translated-keys")


@pytest.mark.parametrize("role,schema,invalid,valid,error_fragment", list(_structured_output_regressions()))
@pytest.mark.parametrize("repaired", [True, False], ids=["repair-succeeds", "repair-fails"])
def test_structured_output_repair_keeps_strict_contract(
    tmp_path, role, schema, invalid, valid, error_fragment, repaired,
):
    responses = [invalid, json.dumps(valid)] if repaired else [invalid] * 3
    gateway, completions = _gateway(tmp_path, responses)
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {role}
    payload = {"subject": "公开测试话语"}
    call = gateway.complete_structured(
        role=role, system_prompt="按公开证据完成任务。", input_payload=payload,
        output_schema=schema, temperature=0.9 if role == "counselor" else 0,
    )
    if repaired:
        assert asyncio.run(call).model_dump(mode="json") == valid
    else:
        with pytest.raises(ValueError, match=f"failed {schema.__name__}"):
            asyncio.run(call)

    assert payload == {"subject": "公开测试话语"}
    assert len(completions.calls) == (2 if repaired else 3)
    first, second = completions.calls[:2]
    assert first["response_format"] == {"type": "json_object"}
    assert all(request["response_format"] == {"type": "json_object"} for request in completions.calls)
    assert second["temperature"] == first["temperature"]
    system_prompt = first["messages"][0]["content"]
    assert system_prompt.startswith("按公开证据完成任务。")
    assert "不得翻译成中文" in system_prompt
    assert json.dumps(schema.model_json_schema()["required"], ensure_ascii=False) in system_prompt
    assert "additionalProperties=false" in system_prompt
    retry = json.loads(second["messages"][1]["content"])
    assert retry["invalid_previous_output"] == invalid
    assert error_fragment in retry["validation_error"]
    assert "返回完整的 JSON 对象" in retry["repair_instruction"]
    if not repaired:
        regeneration = json.loads(completions.calls[2]["messages"][1]["content"])
        assert "invalid_previous_output" not in regeneration
        assert regeneration["subject"] == payload["subject"]
        assert regeneration["output_schema"] == schema.model_json_schema()
        assert "重新生成" in regeneration["repair_instruction"]
    diagnostics = [json.loads(p.read_text(encoding="utf-8")) for p in gateway.diagnostic_dir.glob("*.json")]
    assert len(diagnostics) == (1 if repaired else 3)
    assert {record["attempt"] for record in diagnostics} == ({1} if repaired else {1, 2, 3})
    assert all(record["raw_response"] == invalid for record in diagnostics)


@pytest.mark.parametrize("defect", [None, "nonempty", "missing", "invalid"])
def test_structured_gateway_repairs_only_empty_unknown_fields(tmp_path, defect):
    from psychsandbox.domain import ScaleItems

    valid = {"items": [{"item": "1", "score": 4}]}
    raw = {"items": [{"item": "1", "score": 4, "generated_note": ""}], "footer": ""}
    if defect == "nonempty":
        raw["items"][0]["generated_note"] = "额外说明"
    elif defect == "missing":
        del raw["items"][0]["score"]
    elif defect == "invalid":
        raw["items"][0]["score"] = "four"
    original = json.dumps(raw, ensure_ascii=False)
    gateway, completions = _gateway(tmp_path, [original, json.dumps(valid)])

    result = asyncio.run(gateway.complete_structured(
        role="supervisor", system_prompt="JSON", input_payload={},
        output_schema=ScaleItems, temperature=0,
    ))

    assert result.model_dump(mode="json", exclude_unset=True) == valid
    assert len(completions.calls) == (1 if defect is None else 2)
    record = json.loads(next(gateway.diagnostic_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert record["raw_response"] == original
    if defect is None:
        assert record["error"].startswith("local_repair:")
        assert "items.0.generated_note" in record["error"]
        assert "footer" in record["error"]
    else:
        assert not record["error"].startswith("local_repair:")


class FailingTransport:
    """Always-failing ``client.chat.completions`` double."""

    def __init__(self, error: Exception):
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


def _fast_transport_retries(monkeypatch):
    """Skip the real backoff so exhausted-budget tests stay quick."""
    monkeypatch.setattr(
        "psychsandbox.model_client.TRANSPORT_RETRY_WAIT", wait_none()
    )


def _failing_gateway(tmp_path, attempts):
    gateway, _ = _gateway(tmp_path, [])
    gateway.max_attempts = attempts
    transport = FailingTransport(RuntimeError("upstream 500"))
    gateway.client.chat.completions = transport
    return gateway, transport


def _failing_call(gateway):
    return asyncio.run(
        gateway.complete_structured(
            role="counselor",
            system_prompt="Return JSON.",
            input_payload={"subject": "test"},
            output_schema=ExampleOutput,
            temperature=0.4,
        )
    )


def test_transport_budget_defaults_to_three_attempts(tmp_path, monkeypatch):
    _fast_transport_retries(monkeypatch)
    monkeypatch.delenv("MODEL_MAX_ATTEMPTS", raising=False)
    gateway, transport = _failing_gateway(tmp_path, _max_attempts_from_env())

    with pytest.raises(RuntimeError, match="upstream 500"):
        _failing_call(gateway)

    assert DEFAULT_MAX_ATTEMPTS == 3
    assert len(transport.calls) == 3
    assert list(gateway.diagnostic_dir.glob("*.json"))


def test_transport_budget_follows_model_max_attempts(tmp_path, monkeypatch):
    _fast_transport_retries(monkeypatch)
    monkeypatch.setenv("MODEL_MAX_ATTEMPTS", "5")
    gateway, transport = _failing_gateway(tmp_path, _max_attempts_from_env())

    with pytest.raises(RuntimeError, match="upstream 500"):
        _failing_call(gateway)

    assert len(transport.calls) == 5


def test_exhausted_transport_archives_request_metadata_only(tmp_path, monkeypatch):
    _fast_transport_retries(monkeypatch)
    gateway, _ = _failing_gateway(tmp_path, 2)

    with pytest.raises(RuntimeError, match="upstream 500"):
        _failing_call(gateway)

    records = list(gateway.diagnostic_dir.glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["kind"] == "api_error"
    assert (record["role"], record["model"]) == ("counselor", "ecnu-plus")
    assert record["output_schema"] == "ExampleOutput"
    assert (record["attempt"], record["max_attempts"]) == (2, 2)
    assert record["error_type"] == "RuntimeError"
    assert record["request"] == {"temperature": 0.4, "response_format": "json_schema"}
    # Prompts and credentials must never reach the diagnostic record.
    assert set(record) == {
        "kind", "timestamp", "role", "model", "output_schema", "attempt",
        "max_attempts", "error_type", "status_code", "request_id", "error", "request",
    }


class FlakyEmbeddings:
    """Embedding transport double: fail ``failures`` calls, then answer."""

    def __init__(self, error: Exception, failures: int):
        self.error = error
        self.failures = failures
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise self.error
        rows = [
            SimpleNamespace(index=index, embedding=[float(len(text))])
            for index, text in enumerate(kwargs["input"])
        ]
        return SimpleNamespace(data=rows)


def _flaky_embedding_gateway(monkeypatch, tmp_path, transport, attempts):
    """Bare gateway whose embedding endpoint is ``transport``."""
    import openai

    class EmbeddingOnlyClient:
        def __init__(self, **kwargs):
            self.embeddings = transport

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", EmbeddingOnlyClient)
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "dummy-embedding-key")
    gateway = object.__new__(OpenAICompatibleGateway)
    gateway.max_attempts = attempts
    gateway.diagnostic_dir = tmp_path / "diagnostics"
    return gateway


def test_embedding_transient_failure_recovers_within_budget(tmp_path, monkeypatch):
    _fast_transport_retries(monkeypatch)
    transport = FlakyEmbeddings(RuntimeError("embedding 500"), failures=1)
    gateway = _flaky_embedding_gateway(monkeypatch, tmp_path, transport, attempts=3)

    assert asyncio.run(gateway.embed_texts(["公开话语", "短句"])) == [[4.], [2.]]

    assert len(transport.calls) == 2
    assert not list(gateway.diagnostic_dir.glob("*.json"))
    assert (gateway.diagnostic_dir / "request_metrics.jsonl").is_file()


def test_exhausted_embedding_transport_archives_request_metadata_only(tmp_path, monkeypatch):
    _fast_transport_retries(monkeypatch)
    transport = FlakyEmbeddings(RuntimeError("embedding 500"), failures=9)
    gateway = _flaky_embedding_gateway(monkeypatch, tmp_path, transport, attempts=2)

    with pytest.raises(RuntimeError, match="embedding 500"):
        asyncio.run(gateway.embed_texts(["公开话语"]))

    assert len(transport.calls) == 2
    records = list(gateway.diagnostic_dir.glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["kind"] == "api_error"
    assert (record["role"], record["model"]) == ("embedding", "test-embedding")
    assert record["output_schema"] == "Embedding"
    assert (record["attempt"], record["max_attempts"]) == (2, 2)
    assert record["error_type"] == "RuntimeError"
    assert record["request"] == {
        "response_format": "embeddings", "model": "test-embedding",
        "batch_index": 0, "batch_size": 1,
    }
    # Prompts, skill texts and credentials must never reach the record.
    assert set(record) == {
        "kind", "timestamp", "role", "model", "output_schema", "attempt",
        "max_attempts", "error_type", "status_code", "request_id", "error", "request",
    }


@pytest.mark.parametrize("value", ["0", "-2", "many"])
def test_model_max_attempts_rejects_a_non_positive_integer(monkeypatch, value):
    monkeypatch.setenv("MODEL_MAX_ATTEMPTS", value)

    with pytest.raises(RuntimeError, match="MODEL_MAX_ATTEMPTS"):
        _max_attempts_from_env()


def test_parallel_api_diagnostics_keep_candidate_scope_and_request_metadata(tmp_path):
    from psychsandbox.model_client import model_diagnostic_scope

    gateway, _ = _gateway(tmp_path, [])
    gateway.models.update(counselor="A", supervisor="B")
    gateway.json_schema_roles = {"supervisor"}
    gateway.json_object_roles = {"counselor"}
    first_started, second_started = asyncio.Event(), asyncio.Event()

    class InterleavedCompletions:
        def __init__(self):
            self.counts = {}

        async def create(self, **request):
            model = request["model"]
            self.counts[model] = self.counts.get(model, 0) + 1
            if self.counts[model] > 1:
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
    gateway, completions = _gateway(tmp_path, [raw] * 3)
    with pytest.raises(ValueError, match="failed ScaleItems"):
        asyncio.run(gateway.complete_structured(
            role="supervisor", system_prompt="JSON", input_payload={},
            output_schema=ScaleItems, temperature=0,
        ))
    assert len(completions.calls) == 3


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
