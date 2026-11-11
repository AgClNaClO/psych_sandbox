"""Ordered async results with cancellation that drains every child task."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from typing import TypeVar


T = TypeVar("T")


async def gather_and_drain(coroutines: Iterable[Awaitable[T]]) -> list[T]:
    """Preserve input order and the original exception, never orphan work."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
