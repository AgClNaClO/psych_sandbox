from __future__ import annotations

import asyncio
import importlib
import json
import sys

import pytest
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic import BaseModel
from tenacity import wait_fixed

from psychsandbox.model_client import OpenAICompatibleGateway, model_diagnostic_scope
from psychsandbox.request_control import RequestSlots, instrumented_http_client, model_concurrency


# Current SDKs can select httpx2; older supported SDKs use httpx.
http = importlib.import_module(next(
    cls.__module__.split(".")[0] for cls in DefaultAsyncHttpxClient.__mro__
    if cls.__module__.split(".")[0] in {"httpx", "httpx2"}
))


class Output(BaseModel):
    value: int


def completion():
    return {
        "id": "local-test", "object": "chat.completion", "created": 0, "model": "ecnu-max",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": '{"value": 7}'}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
    }


def gateway_for(tmp_path, handler, *, sdk_retries=0):
    gateway = object.__new__(OpenAICompatibleGateway)
    gateway.models = {"counselor": "ecnu-max", "supervisor": "ecnu-max"}
    gateway.json_schema_roles = set()
    gateway.json_object_roles = set(gateway.models)
    gateway.max_tokens = 128
    gateway.max_attempts = 1
    gateway.request_limit = model_concurrency()
    gateway.diagnostic_dir = tmp_path / "diagnostics"
    gateway.client = AsyncOpenAI(api_key="PRIVATE_TEST_KEY", base_url="https://mock.example.test/v1",
        max_retries=sdk_retries, http_client=instrumented_http_client(transport=http.MockTransport(handler)))
    return gateway


async def call(gateway, role="counselor"):
    return await gateway.complete_structured(role=role, system_prompt="PRIVATE_TEST_PROMPT",
        input_payload={"sensitive": "PRIVATE_TEST_PAYLOAD"}, output_schema=Output, temperature=0)


def metrics(directory):
    return [json.loads(line) for path in directory.rglob("request_metrics.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_actual_http_requests_share_five_slots_across_gateways_and_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY", "5")
    active = peak = 0
    filled = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 5:
            filled.set()
        try:
            await release.wait()
            return http.Response(200, json=completion())
        finally:
            active -= 1

    async def scenario():
        gateways = [gateway_for(tmp_path, handler) for _ in range(2)]

        async def scoped(index):
            with model_diagnostic_scope(tmp_path / str(index)):
                return await call(gateways[index % 2], "counselor" if index % 2 else "supervisor")

        tasks = [asyncio.create_task(scoped(i)) for i in range(12)]
        try:
            await asyncio.wait_for(filled.wait(), 3)
            await asyncio.sleep(.02)
            assert active == peak == 5
            release.set()
            assert all(result.value == 7 for result in await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for gateway in gateways:
                await gateway.client.close()

    asyncio.run(scenario())
    records = metrics(tmp_path)
    assert len(records) == 12 and active == 0
    assert any(row["queue_seconds"] >= .01 for row in records)
    assert {row["role"] for row in records} == {"counselor", "supervisor"}
    assert all(row["http_attempts"] == 1 and row["outcome"] == "success" for row in records)
    assert all(row["usage"]["total_tokens"] == 16 for row in records)
    assert all("PRIVATE_TEST" not in json.dumps(row) for row in records)


def test_sdk_and_outer_retries_have_separate_response_and_wait_time(tmp_path, monkeypatch):
    monkeypatch.setattr("psychsandbox.model_client.TRANSPORT_RETRY_WAIT", wait_fixed(.025))
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(.005)
        if attempts <= 3:
            return http.Response(429, headers={"retry-after": "0.025"}, json={"error": {"message": "busy"}})
        return http.Response(200, json=completion())

    async def scenario():
        gateway = gateway_for(tmp_path, handler, sdk_retries=1)
        gateway.max_attempts = 2
        try:
            assert (await call(gateway)).value == 7
        finally:
            await gateway.client.close()

    asyncio.run(scenario())
    [record] = metrics(tmp_path)
    assert record["http_attempts"] == attempts == 4
    assert record["transport_attempts"] == 2 and record["retries"] == 3
    assert record["response_seconds"] >= .02
    assert record["retry_wait_seconds"] >= .06
    assert [row["status_code"] for row in record["attempts"]] == [429, 429, 429, 200]
    assert record["total_seconds"] == pytest.approx(sum(record[key] for key in
        ("queue_seconds", "response_seconds", "retry_wait_seconds", "overhead_seconds")), abs=.001)


def test_cancelled_request_is_recorded_and_releases_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY", "1")
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    async def scenario():
        gateway = gateway_for(tmp_path, handler)
        task = asyncio.create_task(call(gateway))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with RequestSlots(str(gateway.client.base_url), "ecnu-max", 1).acquire():
                pass
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await gateway.client.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    [record] = metrics(tmp_path)
    assert record["outcome"] == "cancelled" and record["http_attempts"] == 1


def test_request_slots_are_shared_with_other_processes_and_released_on_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runtime"))
    script = """
import asyncio
from contextlib import AsyncExitStack
from psychsandbox.request_control import RequestSlots
async def main():
    async with AsyncExitStack() as stack:
        for _ in range(5):
            await stack.enter_async_context(RequestSlots('test-process', 'ecnu-max', 5).acquire())
        print('locked', flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
"""

    async def scenario():
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        acquired = asyncio.Event()

        async def acquire():
            async with RequestSlots("test-process", "ecnu-max", 5).acquire():
                acquired.set()

        task = None
        try:
            assert (await asyncio.wait_for(process.stdout.readline(), 10)).strip() == b"locked"
            task = asyncio.create_task(acquire())
            await asyncio.sleep(.075)
            assert not acquired.is_set()
            process.terminate()
            await asyncio.wait_for(process.wait(), 5)
            await asyncio.wait_for(task, 3)
            assert acquired.is_set()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["0", "33", "invalid"])
def test_invalid_shared_request_limit_fails_explicitly(monkeypatch, value):
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY", value)
    with pytest.raises(RuntimeError, match="MODEL_MAX_CONCURRENCY"):
        model_concurrency()
