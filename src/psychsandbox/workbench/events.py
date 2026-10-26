"""科研 Web 工作台事件系统 (EventHub)

遵循持久化优先原则：
所有事件先写入 SQLite 表 events（单调自增序号 seq），再推送到订阅者。
支持按 stream:seq 断线重放、客户端去重及快照无缝衔接。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any, AsyncGenerator

from .db import db_transaction, get_connection
from .models import WorkbenchEvent
from ..domain import utc_now


class EventHub:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path
        self._listeners: dict[str, set[asyncio.Queue[WorkbenchEvent]]] = {}
        self._lock = asyncio.Lock()

    def emit(
        self,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        schema_version: int = 1,
    ) -> WorkbenchEvent:
        """同步持久化写入事件，并调度异步通知"""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM events WHERE stream = ?",
                    (stream,),
                )
                next_seq = cur.fetchone()["next_seq"]
                now = utc_now()
                payload_str = json.dumps(payload, ensure_ascii=False)
                cur.execute(
                    """INSERT INTO events
                    (stream, seq, type, schema_version, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (stream, next_seq, event_type, schema_version, payload_str, now),
                )
                event = WorkbenchEvent(
                    stream=stream,
                    seq=next_seq,
                    type=event_type,
                    schema_version=schema_version,
                    payload=payload,
                    created_at=now,
                )
        finally:
            conn.close()

        # 内存通知队列（若在 asyncio 事件循环中）
        self._dispatch_memory(stream, event)
        return event

    def _dispatch_memory(self, stream: str, event: WorkbenchEvent) -> None:
        queues = self._listeners.get(stream, set())
        for q in list(queues):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def get_events(
        self, stream: str, after_seq: int = 0, limit: int = 200
    ) -> list[WorkbenchEvent]:
        """按 stream 和 after_seq 获取已持久化的事件列表"""
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT stream, seq, type, schema_version, payload_json, created_at
                FROM events
                WHERE stream = ? AND seq > ?
                ORDER BY seq ASC LIMIT ?""",
                (stream, after_seq, limit),
            )
            rows = cur.fetchall()
            return [
                WorkbenchEvent(
                    stream=r["stream"],
                    seq=r["seq"],
                    type=r["type"],
                    schema_version=r["schema_version"],
                    payload=json.loads(r["payload_json"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    async def subscribe(
        self, stream: str, after_seq: int = 0
    ) -> AsyncGenerator[WorkbenchEvent, None]:
        """订阅指定 stream 的事件流：支持跨进程 SQLite 持久化事件与实时推送"""
        q: asyncio.Queue[WorkbenchEvent] = asyncio.Queue()
        async with self._lock:
            if stream not in self._listeners:
                self._listeners[stream] = set()
            self._listeners[stream].add(q)

        loop = asyncio.get_event_loop()
        last_yielded_seq = after_seq
        last_ping_time = loop.time()

        try:
            while True:
                # 1. 优先拉取 SQLite 中新增事件（支持独立 Worker 跨进程写入）
                new_events = self.get_events(stream, after_seq=last_yielded_seq, limit=200)
                if new_events:
                    for ev in new_events:
                        if ev.seq > last_yielded_seq:
                            last_yielded_seq = ev.seq
                            yield ev
                    last_ping_time = loop.time()

                # 2. 等待内存队列唤醒（同进程 emit），最多等待 0.5 秒
                try:
                    mem_event = await asyncio.wait_for(q.get(), timeout=0.5)
                    if mem_event.seq > last_yielded_seq:
                        last_yielded_seq = mem_event.seq
                        yield mem_event
                        last_ping_time = loop.time()
                except asyncio.TimeoutError:
                    pass

                # 3. 每 10 秒发送心跳保活包
                now_time = loop.time()
                if now_time - last_ping_time >= 10.0:
                    yield WorkbenchEvent(
                        stream=stream,
                        seq=last_yielded_seq,
                        type="ping",
                        payload={"timestamp": utc_now()},
                    )
                    last_ping_time = now_time
        finally:
            async with self._lock:
                if stream in self._listeners and q in self._listeners[stream]:
                    self._listeners[stream].remove(q)
                    if not self._listeners[stream]:
                        del self._listeners[stream]


_GLOBAL_EVENT_HUB: EventHub | None = None


def get_event_hub(db_path: str | None = None) -> EventHub:
    global _GLOBAL_EVENT_HUB
    if _GLOBAL_EVENT_HUB is None or (_GLOBAL_EVENT_HUB.db_path != db_path and db_path is not None):
        _GLOBAL_EVENT_HUB = EventHub(db_path)
    return _GLOBAL_EVENT_HUB
