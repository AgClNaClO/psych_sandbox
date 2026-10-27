"""科研 Web 工作台事件系统 (EventHub)

遵循持久化优先原则：
所有事件先写入 SQLite 表 events（单调自增序号 seq），再推送到订阅者。
支持按 stream:seq 断线重放、客户端去重及快照无缝衔接。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

from .db import db_transaction, get_connection
from .models import WorkbenchEvent
from ..domain import utc_now


class EventHub:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

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

        return event

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
        """顺序读取持久事件；线程、进程与分页都不能跳过尚未重放的序号。"""
        loop = asyncio.get_running_loop()
        last_yielded_seq = after_seq
        last_ping_time = loop.time()

        while True:
            new_events = await asyncio.to_thread(
                self.get_events, stream, after_seq=last_yielded_seq, limit=200
            )
            for ev in new_events:
                last_yielded_seq = ev.seq
                yield ev
            if new_events:
                last_ping_time = loop.time()
                # Drain every page before waiting for new events.
                continue
            if loop.time() - last_ping_time >= 10.0:
                yield WorkbenchEvent(
                    stream=stream, seq=last_yielded_seq, type="ping",
                    payload={"timestamp": utc_now()},
                )
                last_ping_time = loop.time()
            await asyncio.sleep(0.5)


def get_event_hub(db_path: str | None = None) -> EventHub:
    # No process-global DB binding: app instances and tests remain isolated.
    return EventHub(db_path)
