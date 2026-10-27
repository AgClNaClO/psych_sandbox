"""科研 Web 工作台任务管理器 (JobManager)

职责：
- 区分 long lane（长仿真）与 short lane（人工交互）；
- 实现认领、租约、心跳和 attempt 栅栏隔离；
- 防止迟到的失效 worker 结果覆盖新 attempt；
- 支持会谈边界停止 (stop_requested) 与取消 (cancel_requested)；
- 短事务保证高并发安全。
"""
from __future__ import annotations

import json
import uuid
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import db_transaction, get_connection
from .models import JobKind, JobLane, JobResponse
from ..domain import utc_now


def _to_job_response(row: Any) -> JobResponse:
    return JobResponse(
        job_id=row["job_id"],
        kind=row["kind"],
        lane=row["lane"],
        status=row["status"],
        payload=json.loads(row["payload_json"]),
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        heartbeat_at=row["heartbeat_at"],
        stop_requested=bool(row["stop_requested"]),
        cancel_requested=bool(row["cancel_requested"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        run_id=row["run_id"],
        course_id=row["course_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class JobManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

    def enqueue_job(
        self,
        kind: JobKind,
        lane: JobLane,
        payload: dict[str, Any],
        run_id: str | None = None,
        course_id: str | None = None,
        max_attempts: int = 3,
        job_id: str | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> JobResponse:
        operation_id = payload.get("operation_id") if kind in ("course_reply", "course_close") else None
        jid = job_id or (f"job-operation-{operation_id}" if operation_id else f"job-{uuid.uuid4().hex[:12]}")
        now = utc_now()
        conn = connection or get_connection(self.db_path)
        try:
            with (closing(conn.cursor()) if connection else db_transaction(conn)) as cur:
                cur.execute(
                    """INSERT INTO jobs
                    (job_id, kind, lane, status, payload_json, attempt, max_attempts,
                     stop_requested, cancel_requested, run_id, course_id, created_at, updated_at)
                    VALUES (?, ?, ?, 'queued', ?, 0, ?, 0, 0, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO NOTHING""",
                    (
                        jid,
                        kind,
                        lane,
                        json.dumps(payload, ensure_ascii=False),
                        max_attempts,
                        run_id,
                        course_id,
                        now,
                        now,
                    ),
                )
            cur = conn.cursor()
            cur.execute("SELECT * FROM jobs WHERE job_id = ?", (jid,))
            job = _to_job_response(cur.fetchone())
            if job.kind != kind or job.course_id != course_id or job.payload != payload:
                raise ValueError("Job id is already bound to another request")
            return job
        finally:
            if connection is None:
                conn.close()

    def claim_job(
        self, lane: JobLane, worker_id: str, lease_seconds: int = 60
    ) -> JobResponse | None:
        """从指定 lane 中原子认领一个处于 queued 状态的任务"""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """SELECT job_id, attempt FROM jobs
                    WHERE lane = ? AND status = 'queued'
                    ORDER BY created_at ASC LIMIT 1""",
                    (lane,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                jid = row["job_id"]
                now = datetime.now(timezone.utc)
                now_str = now.isoformat()
                expires_str = (now + timedelta(seconds=lease_seconds)).isoformat()

                cur.execute(
                    """UPDATE jobs
                    SET status = 'running',
                        attempt = attempt + 1,
                        lease_owner = ?,
                        lease_expires_at = ?,
                        heartbeat_at = ?,
                        updated_at = ?
                    WHERE job_id = ? AND status = 'queued'""",
                    (worker_id, expires_str, now_str, now_str, jid),
                )
                if cur.rowcount == 0:
                    return None

                cur.execute("SELECT * FROM jobs WHERE job_id = ?", (jid,))
                return _to_job_response(cur.fetchone())
        finally:
            conn.close()

    def bind_run(self, job_id: str, attempt: int, worker_id: str, run_id: str) -> bool:
        """Persist run identity before execution so retries resume the same trajectory."""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs SET run_id = ?, updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (run_id, utc_now(), job_id, attempt, worker_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def heartbeat(
        self, job_id: str, attempt: int, worker_id: str, lease_seconds: int = 60
    ) -> tuple[bool, bool, bool]:
        """更新租约心跳。返回 (lease_valid, stop_requested, cancel_requested)"""
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        expires_str = (now + timedelta(seconds=lease_seconds)).isoformat()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs
                    SET lease_expires_at = ?,
                        heartbeat_at = ?,
                        updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (expires_str, now_str, now_str, job_id, attempt, worker_id),
                )
                if cur.rowcount == 0:
                    return False, False, False

                cur.execute(
                    "SELECT stop_requested, cancel_requested FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                row = cur.fetchone()
                return (
                    True,
                    bool(row["stop_requested"]),
                    bool(row["cancel_requested"]),
                )
        finally:
            conn.close()

    def complete_job(
        self, job_id: str, attempt: int, worker_id: str, result: dict[str, Any]
    ) -> bool:
        """带栅栏原子提交任务成功。迟到 worker 将被拒绝。"""
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs
                    SET status = 'succeeded',
                        result_json = ?,
                        updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (json.dumps(result, ensure_ascii=False), now, job_id, attempt, worker_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def mark_stopped_job(
        self, job_id: str, attempt: int, worker_id: str, result: dict[str, Any] | None = None
    ) -> bool:
        """带栅栏原子标记任务在会谈边界已停止"""
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs
                    SET status = 'stopped',
                        result_json = ?,
                        updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (json.dumps(result, ensure_ascii=False) if result else None, now, job_id, attempt, worker_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def fail_job(
        self,
        job_id: str,
        attempt: int,
        worker_id: str,
        error: str,
        retryable: bool = True,
    ) -> bool:
        """带栅栏标记任务失败或重新排队"""
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute("SELECT attempt, max_attempts FROM jobs WHERE job_id = ?", (job_id,))
                row = cur.fetchone()
                if not row:
                    return False
                cur_attempt = row["attempt"]
                max_attempts = row["max_attempts"]

                if retryable and cur_attempt < max_attempts:
                    target_status = "queued"
                else:
                    target_status = "failed"

                cur.execute(
                    """UPDATE jobs
                    SET status = ?,
                        error = ?,
                        updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (target_status, error, now, job_id, attempt, worker_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def request_stop(self, job_id: str) -> bool:
        """请求在会谈边界停止"""
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs
                    SET stop_requested = 1, updated_at = ?
                    WHERE job_id = ? AND status IN ('running', 'queued')""",
                    (now, job_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def request_cancel(self, job_id: str) -> bool:
        """请求取消任务"""
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                # 若还在 queued，直接变为 cancelled
                cur.execute(
                    """UPDATE jobs
                    SET status = 'cancelled', cancel_requested = 1, updated_at = ?
                    WHERE job_id = ? AND status = 'queued'""",
                    (now, job_id),
                )
                if cur.rowcount > 0:
                    return True
                # 若已经在 running，设置 cancel_requested 标志供 worker 退出
                cur.execute(
                    """UPDATE jobs
                    SET cancel_requested = 1, updated_at = ?
                    WHERE job_id = ? AND status = 'running'""",
                    (now, job_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def mark_cancelled_job(self, job_id: str, attempt: int, worker_id: str) -> bool:
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE jobs
                    SET status = 'cancelled', updated_at = ?
                    WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running'""",
                    (now, job_id, attempt, worker_id),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def reap_stale_jobs(self) -> int:
        """回收租约过期的任务（崩溃 worker 产生）"""
        now_str = datetime.now(timezone.utc).isoformat()
        conn = get_connection(self.db_path)
        try:
            reaped = 0
            with db_transaction(conn) as cur:
                cur.execute(
                    """SELECT job_id, attempt, max_attempts FROM jobs
                    WHERE status = 'running' AND lease_expires_at < ?""",
                    (now_str,),
                )
                stale = cur.fetchall()
                for row in stale:
                    jid = row["job_id"]
                    att = row["attempt"]
                    max_att = row["max_attempts"]
                    next_status = "queued" if att < max_att else "failed"
                    err = "Lease expired without heartbeat" if next_status == "failed" else None
                    cur.execute(
                        """UPDATE jobs
                        SET status = ?, error = COALESCE(?, error), updated_at = ?
                        WHERE job_id = ? AND status = 'running'""",
                        (next_status, err, utc_now(), jid),
                    )
                    reaped += cur.rowcount
            return reaped
        finally:
            conn.close()

    def get_job(self, job_id: str) -> JobResponse | None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            return _to_job_response(row) if row else None
        finally:
            conn.close()

    def list_jobs(self, lane: JobLane | None = None, limit: int = 50) -> list[JobResponse]:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            if lane:
                cur.execute(
                    "SELECT * FROM jobs WHERE lane = ? ORDER BY created_at DESC LIMIT ?",
                    (lane, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                )
            return [_to_job_response(r) for r in cur.fetchall()]
        finally:
            conn.close()
