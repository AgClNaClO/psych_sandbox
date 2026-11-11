"""Shared model request slots and payload-free, per-HTTP-attempt telemetry."""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import time
import weakref
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import runtime_root


DEFAULT_MODEL_CONCURRENCY = 5
_local_limits: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
current_request: ContextVar[RequestTiming | None] = ContextVar("request_timing", default=None)


def model_concurrency() -> int:
    raw = os.getenv("MODEL_MAX_CONCURRENCY", str(DEFAULT_MODEL_CONCURRENCY))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("MODEL_MAX_CONCURRENCY must be an integer from 1 to 32") from exc
    if not 1 <= value <= 32:
        raise RuntimeError("MODEL_MAX_CONCURRENCY must be an integer from 1 to 32")
    return value


class RequestSlots:
    """One pool per project, endpoint and model, including separate workers.

    Locks belong to open handles, so cancellation and process exit release them.
    Credentials are neither stored nor used to split a user's model allowance.
    """

    def __init__(self, endpoint: str, model: str, limit: int):
        identity = json.dumps([endpoint.rstrip("/").lower(), model.strip().lower()])
        digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
        project = Path(__file__).resolve().parents[2]
        self.directory = runtime_root(project) / ".model-request-slots" / digest
        self.limit = limit

    @asynccontextmanager
    async def acquire(self):
        loop_limits = _local_limits.setdefault(asyncio.get_running_loop(), {})
        key = (self.directory, self.limit)
        semaphore = loop_limits.setdefault(key, asyncio.Semaphore(self.limit))
        async with semaphore:
            self.directory.mkdir(parents=True, exist_ok=True)
            while True:
                for index in range(self.limit):
                    handle = (self.directory / f"{index}.lock").open("a+b")
                    try:
                        handle.seek(0, 2)
                        if not handle.tell():
                            handle.write(b"0")
                            handle.flush()
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError as exc:
                        handle.close()
                        if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise
                        continue
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                        handle.close()
                    return
                await asyncio.sleep(0.025)


@dataclass
class RequestTiming:
    slots: RequestSlots
    started: float = field(default_factory=time.monotonic)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    queue_seconds: float = 0.0
    response_seconds: float = 0.0
    retry_wait_seconds: float = 0.0
    last_finished: float | None = None

    def begin_attempt(self, started: float) -> None:
        if self.last_finished is not None:
            # Includes SDK and outer backoff, plus preparation between attempts.
            self.retry_wait_seconds += started - self.last_finished

    def finish_attempt(self, queued: float, sending: float | None, **metadata) -> None:
        finished = time.monotonic()
        queue = (sending if sending is not None else finished) - queued
        response = finished - sending if sending is not None else 0.0
        self.queue_seconds += queue
        self.response_seconds += response
        self.last_finished = finished
        self.attempts.append({
            "index": len(self.attempts) + 1,
            "sent": sending is not None,
            "queue_seconds": queue, "response_seconds": response, **metadata,
        })

    def summary(self) -> dict:
        total = time.monotonic() - self.started
        sent = sum(attempt["sent"] for attempt in self.attempts)
        return {
            "total_seconds": total, "queue_seconds": self.queue_seconds,
            "response_seconds": self.response_seconds,
            "retry_wait_seconds": self.retry_wait_seconds,
            "overhead_seconds": max(0.0, total - self.queue_seconds
                                    - self.response_seconds - self.retry_wait_seconds),
            "http_attempts": sent,
            "retries": max(0, sent - 1), "attempts": self.attempts,
        }


def instrumented_http_client(**kwargs):
    """Keep SDK defaults and retries, timing each actual HTTP send separately."""
    from openai import DefaultAsyncHttpxClient

    class InstrumentedClient(DefaultAsyncHttpxClient):
        async def send(self, request, **options):
            timing = current_request.get()
            if timing is None:
                return await super().send(request, **options)
            queued = time.monotonic()
            timing.begin_attempt(queued)
            sending = None
            metadata: dict[str, Any] = {"outcome": "cancelled"}
            try:
                async with timing.slots.acquire():
                    sending = time.monotonic()
                    response = await super().send(request, **options)
                    metadata = {
                        "outcome": "success" if response.status_code < 400 else "error",
                        "status_code": response.status_code,
                    }
                    return response
            except Exception as exc:
                metadata = {"outcome": "error", "error_type": type(exc).__name__}
                raise
            finally:
                timing.finish_attempt(queued, sending, **metadata)

    return InstrumentedClient(**kwargs)
