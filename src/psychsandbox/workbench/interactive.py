"""科研 Web 工作台人工多会谈聊天引擎 (Interactive Engine)

核心原则：
1. 独立人工记录，不复用完整模拟器，不伪造模拟状态；
2. 仅复用咨询师引擎 (CounselorAgent) 与会后记忆整理能力；
3. 区分自然输入与角色扮演，角色卡不作为已知事实；
4. 严格幂等调用、版本乐观锁与单会谈串行生成；
5. 会后整理严格按步骤执行并支持失败恢复；
6. 人工数据默认不进入经验池与训练集。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[3] / ".env"
if env_path.exists():
    load_dotenv(env_path)

from .db import db_transaction, get_connection, utc_now
from .models import (
    CourseResponse,
    CourseSessionDetailResponse,
    CourseMessageResponse,
    OperationResponse,
    CloseStepRecord,
)
from .events import get_event_hub
from .job_manager import JobManager
from ..agents.counselor import CounselorAgent
from ..domain import (
    ClinicalSummary,
    CounselorTurn,
    CounselorSessionReview,
    ExtractedClientInfo,
    LongitudinalReport,
    Message,
    RiskAssessment,
    RiskLevel,
    SessionChecklist,
    SessionMemory,
    SessionPlan,
    SessionRecord,
    SessionStage,
    UnlockedClientInfo,
    utc_now,
)
from ..therapies import get_therapy_profile, normalize_therapy_id
from ..runtime.planning import PlanBuilder
from ..runtime.memory import MemoryConsolidator
from ..runtime.memory_pipeline import (
    ClientMergeAgent,
    DialogueSummaryAgent,
    MemoryExtractionAgent,
)
from ..runtime.safety import SafetyStateMachine
from ..skills import SkillCatalog, SkillRegistry


class VersionConflictError(Exception):
    """乐观锁版本冲突"""
    pass


class OperationBusyError(Exception):
    """当前会谈已有正在执行的操作"""
    pass


class SessionClosedError(Exception):
    """会谈已关闭，无法继续发送"""
    pass


class InteractiveSessionView:
    """供会后整理 (Consolidator 与 review_session) 使用的受控鸭子类型视图，避免伪造 ClientState"""
    def __init__(
        self,
        session_index: int,
        plan: SessionPlan,
        summary: str,
        clinical_summary: ClinicalSummary,
        messages: list[Message],
        end_reason: str = "participant_ended",
    ):
        self.session_index = session_index
        self.plan = plan
        self.summary = summary
        self.clinical_summary = clinical_summary
        self.messages = messages
        self.end_reason = end_reason
        self.interventions_used: list[str] = []
        self.risk_events: list[Any] = []
        self.safety_verdict = None
        self.turn_records: list[dict[str, Any]] = []
        self.decisions: list[Any] = []
        self.counselor_review = None


class CourseManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path
        self.events = get_event_hub(db_path)

    def _enqueue_operation(self, conn, course_id: str, operation_id: str, kind: str) -> None:
        JobManager(self.db_path).enqueue_job(
            kind=kind, lane="short", course_id=course_id,
            payload={"course_id": course_id, "operation_id": operation_id},
            connection=conn,
        )

    @staticmethod
    def _existing_operation(cur, course_id: str, session_index: int, operation_id: str, kind: str):
        cur.execute("SELECT * FROM course_operations WHERE operation_id = ?", (operation_id,))
        row = cur.fetchone()
        if row is None:
            return None
        if (row["course_id"], row["session_index"], row["kind"]) != (course_id, session_index, kind):
            raise VersionConflictError("Operation id is already bound to another request")
        return OperationResponse(
            **{key: row[key] for key in (
                "operation_id", "course_id", "session_index", "kind", "status",
                "expected_version", "error", "created_at", "updated_at",
            )},
            payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
        )

    @staticmethod
    def _check_session(cur, course_id: str, session_index: int, *, closing: bool = False) -> None:
        cur.execute(
            "SELECT status FROM course_sessions WHERE course_id = ? AND session_index = ?",
            (course_id, session_index),
        )
        row = cur.fetchone()
        allowed = ("open", "close_failed") if closing else ("open",)
        if row is None or row["status"] not in allowed:
            raise SessionClosedError(f"Session {session_index} is not open")
        cur.execute(
            """SELECT 1 FROM course_operations WHERE course_id = ?
            AND session_index = ? AND status IN ('pending', 'running')""",
            (course_id, session_index),
        )
        if cur.fetchone():
            raise OperationBusyError("Another operation is currently active in this session")

    def create_course(
        self,
        therapy: str,
        title: str,
        input_mode: Literal["natural", "roleplay"] = "natural",
        roleplay_card: str | None = None,
        skill_release_id: str | None = None,
    ) -> CourseResponse:
        norm_therapy = normalize_therapy_id(therapy)
        course_id = f"course-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT INTO courses
                    (course_id, therapy, title, input_mode, roleplay_card, status,
                     skill_release_id, version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'active', ?, 1, ?, ?)""",
                    (course_id, norm_therapy, title, input_mode, roleplay_card, skill_release_id, now, now),
                )
            # 自动初始化第 1 次会谈
            self.create_session(course_id, session_index=1)
            return self.get_course(course_id)
        finally:
            conn.close()

    def get_course(self, course_id: str) -> CourseResponse | None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM courses WHERE course_id = ?", (course_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM course_sessions WHERE course_id = ? AND status = 'closed'",
                (course_id,),
            )
            completed_cnt = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COALESCE(MAX(session_index), 1) AS cur_idx FROM course_sessions WHERE course_id = ?",
                (course_id,),
            )
            cur_idx = cur.fetchone()["cur_idx"]

            return CourseResponse(
                course_id=row["course_id"],
                therapy=row["therapy"],
                title=row["title"],
                input_mode=row["input_mode"],
                roleplay_card=row["roleplay_card"],
                status=row["status"],
                close_reason=row["close_reason"],
                skill_release_id=row["skill_release_id"],
                prompt_tree_version=row["prompt_tree_version"],
                config_hash=row["config_hash"],
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                completed_sessions=completed_cnt,
                current_session=cur_idx,
            )
        finally:
            conn.close()

    def list_courses(self) -> list[CourseResponse]:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT course_id FROM courses ORDER BY created_at DESC")
            ids = [r["course_id"] for r in cur.fetchall()]
            return [self.get_course(cid) for cid in ids if cid]
        finally:
            conn.close()

    def create_session(self, course_id: str, session_index: int | None = None) -> CourseSessionDetailResponse:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM courses WHERE course_id = ?", (course_id,))
            c_row = cur.fetchone()
            if not c_row:
                raise ValueError(f"Course {course_id} not found")
            if c_row["status"] == "closed":
                raise ValueError("Cannot create session in a closed course")

            if session_index is None:
                cur.execute(
                    "SELECT COALESCE(MAX(session_index), 0) + 1 AS next_idx FROM course_sessions WHERE course_id = ?",
                    (course_id,),
                )
                session_index = cur.fetchone()["next_idx"]

            therapy = c_row["therapy"]
            profile = get_therapy_profile(therapy)
            stages = list(profile.stage_goals.keys())
            first_stage = stages[0] if stages else SessionStage.INITIAL

            # 如果有前一场会谈，读取其 next_plan 与 memory_after
            plan: SessionPlan
            memory: SessionMemory
            if session_index > 1:
                cur.execute(
                    "SELECT next_plan_json, memory_after_json FROM course_sessions WHERE course_id = ? AND session_index = ?",
                    (course_id, session_index - 1),
                )
                prev = cur.fetchone()
                if prev and prev["next_plan_json"] and prev["memory_after_json"]:
                    plan = SessionPlan.model_validate_json(prev["next_plan_json"])
                    memory = SessionMemory.model_validate_json(prev["memory_after_json"])
                else:
                    plan = SessionPlan(
                        therapy=therapy,
                        stage=first_stage,
                        session_index=session_index,
                        objectives=list(profile.stage_goals.get(first_stage, []))[:2],
                    )
                    memory = SessionMemory(case_id=course_id, known_background=UnlockedClientInfo(client_id=course_id))
            else:
                plan = SessionPlan(
                    therapy=therapy,
                    stage=first_stage,
                    session_index=1,
                    objectives=list(profile.stage_goals.get(first_stage, []))[:2],
                )
                memory = SessionMemory(case_id=course_id, known_background=UnlockedClientInfo(client_id=course_id))

            now = utc_now()
            with db_transaction(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM course_sessions WHERE course_id = ? AND session_index = ?",
                    (course_id, session_index),
                )
                if cur.fetchone():
                    return self.get_session_detail(course_id, session_index)
                cur.execute("SELECT status FROM courses WHERE course_id = ?", (course_id,))
                if cur.fetchone()["status"] != "active":
                    raise ValueError("Cannot create session in a closed course")
                cur.execute(
                    """SELECT session_index, status FROM course_sessions WHERE course_id = ?
                    ORDER BY session_index DESC LIMIT 1""", (course_id,),
                )
                last = cur.fetchone()
                if last and last["status"] != "closed":
                    raise ValueError("Close the current session before starting the next one")
                if session_index != (last["session_index"] + 1 if last else 1):
                    raise ValueError("Sessions must advance exactly one boundary")
                cur.execute(
                    """INSERT INTO course_sessions
                    (course_id, session_index, status, plan_json, memory_before_json, created_at)
                    VALUES (?, ?, 'open', ?, ?, ?)""",
                    (course_id, session_index, plan.model_dump_json(), memory.model_dump_json(), now),
                )
                if session_index > 1:
                    cur.execute(
                        "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                        (now, course_id),
                    )
            return self.get_session_detail(course_id, session_index)
        finally:
            conn.close()

    def get_session_detail(self, course_id: str, session_index: int) -> CourseSessionDetailResponse | None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM course_sessions WHERE course_id = ? AND session_index = ?",
                (course_id, session_index),
            )
            s_row = cur.fetchone()
            if not s_row:
                return None

            cur.execute("SELECT version FROM courses WHERE course_id = ?", (course_id,))
            c_row = cur.fetchone()
            course_version = c_row["version"] if c_row else 1

            # 消息
            cur.execute(
                "SELECT * FROM course_messages WHERE course_id = ? AND session_index = ? ORDER BY created_at ASC",
                (course_id, session_index),
            )
            msgs = [
                CourseMessageResponse(
                    message_id=r["message_id"],
                    course_id=r["course_id"],
                    session_index=r["session_index"],
                    role=r["role"],
                    source=r["source"],
                    content=r["content"],
                    metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
                    created_at=r["created_at"],
                )
                for r in cur.fetchall()
            ]

            # 整理步骤
            cur.execute(
                "SELECT * FROM course_close_steps WHERE course_id = ? AND session_index = ? ORDER BY created_at ASC",
                (course_id, session_index),
            )
            steps = [
                CloseStepRecord(
                    step_name=r["step_name"],
                    status=r["status"],
                    input_summary=json.loads(r["input_summary_json"]),
                    output=json.loads(r["output_json"]) if r["output_json"] else None,
                    error=r["error"],
                    created_at=r["created_at"],
                )
                for r in cur.fetchall()
            ]

            # 活跃与最近操作
            cur.execute(
                "SELECT * FROM course_operations WHERE course_id = ? AND session_index = ? ORDER BY created_at DESC",
                (course_id, session_index),
            )
            op_rows = cur.fetchall()
            active_op: OperationResponse | None = None
            last_op: OperationResponse | None = None
            if op_rows:
                last_r = op_rows[0]
                last_op = OperationResponse(
                    operation_id=last_r["operation_id"],
                    course_id=last_r["course_id"],
                    session_index=last_r["session_index"],
                    kind=last_r["kind"],
                    status=last_r["status"],
                    expected_version=last_r["expected_version"],
                    payload=json.loads(last_r["payload_json"]) if last_r["payload_json"] else {},
                    result=json.loads(last_r["result_json"]) if last_r["result_json"] else None,
                    error=last_r["error"],
                    created_at=last_r["created_at"],
                    updated_at=last_r["updated_at"],
                )
                for r in op_rows:
                    if r["status"] in ("pending", "running"):
                        active_op = OperationResponse(
                            operation_id=r["operation_id"],
                            course_id=r["course_id"],
                            session_index=r["session_index"],
                            kind=r["kind"],
                            status=r["status"],
                            expected_version=r["expected_version"],
                            payload=json.loads(r["payload_json"]) if r["payload_json"] else {},
                            result=json.loads(r["result_json"]) if r["result_json"] else None,
                            error=r["error"],
                            created_at=r["created_at"],
                            updated_at=r["updated_at"],
                        )
                        break

            return CourseSessionDetailResponse(
                course_id=s_row["course_id"],
                course_version=course_version,
                session_index=s_row["session_index"],
                status=s_row["status"],
                plan=json.loads(s_row["plan_json"]),
                memory_before=json.loads(s_row["memory_before_json"]),
                memory_after=json.loads(s_row["memory_after_json"]) if s_row["memory_after_json"] else None,
                next_plan=json.loads(s_row["next_plan_json"]) if s_row["next_plan_json"] else None,
                review=json.loads(s_row["review_json"]) if s_row["review_json"] else None,
                close_reason=s_row["close_reason"],
                created_at=s_row["created_at"],
                closed_at=s_row["closed_at"],
                messages=msgs,
                close_steps=steps,
                active_operation=active_op,
                last_operation=last_op,
            )
        finally:
            conn.close()

    def reset_session_lock(self, course_id: str, session_index: int) -> int:
        """重置会话中卡死或残留的 pending/running 操作，恢复会话可交互状态"""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """UPDATE course_operations
                    SET status = 'cancelled', error = 'User reset operation lock', updated_at = ?
                    WHERE course_id = ? AND session_index = ? AND status IN ('pending', 'running')""",
                    (utc_now(), course_id, session_index),
                )
                affected = cur.rowcount
                cur.execute(
                    """UPDATE course_sessions SET status = 'close_failed'
                    WHERE course_id = ? AND session_index = ? AND status = 'closing'""",
                    (course_id, session_index),
                )
                cur.execute(
                    """UPDATE jobs SET cancel_requested = 1,
                    status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                    updated_at = ? WHERE course_id = ? AND status IN ('queued', 'running')
                    AND json_extract(payload_json, '$.operation_id') IN (
                        SELECT operation_id FROM course_operations WHERE course_id = ?
                        AND session_index = ? AND status = 'cancelled')""",
                    (utc_now(), course_id, course_id, session_index),
                )
                if affected:
                    cur.execute(
                        "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                        (utc_now(), course_id),
                    )
            if affected > 0:
                self.events.emit(
                    f"course:{course_id}",
                    "operation_failed",
                    {"course_id": course_id, "error": "操作锁已由用户手动重置解除"},
                )
            return affected
        finally:
            conn.close()

    def submit_user_message(
        self,
        course_id: str,
        session_index: int,
        message_id: str,
        operation_id: str,
        expected_version: int,
        content: str,
        source: Literal["participant_natural", "participant_roleplay"] = "participant_natural",
    ) -> tuple[CourseMessageResponse, OperationResponse]:
        """幂等保存用户消息与待处理回复操作"""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                # 优先检查幂等性
                cur.execute("SELECT * FROM course_messages WHERE message_id = ?", (message_id,))
                existing_msg = cur.fetchone()
                cur.execute("SELECT * FROM course_operations WHERE operation_id = ?", (operation_id,))
                existing_op = cur.fetchone()
                if existing_msg or existing_op:
                    if not (
                        existing_msg and existing_op
                        and (existing_msg["course_id"], existing_msg["session_index"], existing_msg["content"], existing_msg["source"])
                        == (course_id, session_index, content, source)
                        and (existing_op["course_id"], existing_op["session_index"], existing_op["kind"])
                        == (course_id, session_index, "message")
                        and json.loads(existing_op["payload_json"]).get("user_message_id") == message_id
                    ):
                        raise VersionConflictError("Message or operation id is already bound to another request")
                if existing_msg and existing_op:
                    return (
                        CourseMessageResponse(
                            message_id=existing_msg["message_id"],
                            course_id=existing_msg["course_id"],
                            session_index=existing_msg["session_index"],
                            role=existing_msg["role"],
                            source=existing_msg["source"],
                            content=existing_msg["content"],
                            metadata=json.loads(existing_msg["metadata_json"]),
                            created_at=existing_msg["created_at"],
                        ),
                        OperationResponse(
                            operation_id=existing_op["operation_id"],
                            course_id=existing_op["course_id"],
                            session_index=existing_op["session_index"],
                            kind=existing_op["kind"],
                            status=existing_op["status"],
                            expected_version=existing_op["expected_version"],
                            payload=json.loads(existing_op["payload_json"]),
                            result=json.loads(existing_op["result_json"]) if existing_op["result_json"] else None,
                            error=existing_op["error"],
                            created_at=existing_op["created_at"],
                            updated_at=existing_op["updated_at"],
                        ),
                    )

                # 检查会谈与版本
                cur.execute("SELECT version, status FROM courses WHERE course_id = ?", (course_id,))
                c_row = cur.fetchone()
                if not c_row:
                    raise SessionClosedError(f"Course {course_id} not found")
                if c_row["status"] == "closed":
                    raise SessionClosedError("Course is closed")
                if c_row["version"] != expected_version:
                    raise VersionConflictError(
                        f"Course version mismatch: current {c_row['version']} != expected {expected_version}"
                    )

                cur.execute(
                    "SELECT status FROM course_sessions WHERE course_id = ? AND session_index = ?",
                    (course_id, session_index),
                )
                s_row = cur.fetchone()
                if not s_row or s_row["status"] != "open":
                    raise SessionClosedError(f"Session {session_index} is not open")

                # 检查是否已有活跃操作
                cur.execute(
                    """SELECT operation_id FROM course_operations
                    WHERE course_id = ? AND session_index = ? AND status IN ('pending', 'running')""",
                    (course_id, session_index),
                )
                if cur.fetchone():
                    raise OperationBusyError("Another operation is currently active in this session")

                now = utc_now()
                # 写入消息
                cur.execute(
                    """INSERT INTO course_messages
                    (message_id, course_id, session_index, role, source, content, metadata_json, created_at)
                    VALUES (?, ?, ?, 'participant', ?, ?, '{}', ?)""",
                    (message_id, course_id, session_index, source, content, now),
                )

                # 写入待处理操作
                op_payload = {"user_message_id": message_id}
                cur.execute(
                    """INSERT INTO course_operations
                    (operation_id, course_id, session_index, kind, status, expected_version, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, 'message', 'pending', ?, ?, ?, ?)""",
                    (operation_id, course_id, session_index, expected_version, json.dumps(op_payload), now, now),
                )

                # 递增 course version
                cur.execute(
                    "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                    (now, course_id),
                )
                self._enqueue_operation(conn, course_id, operation_id, "course_reply")

            msg_res = CourseMessageResponse(
                message_id=message_id,
                course_id=course_id,
                session_index=session_index,
                role="participant",
                source=source,
                content=content,
                metadata={},
                created_at=now,
            )
            op_res = OperationResponse(
                operation_id=operation_id,
                course_id=course_id,
                session_index=session_index,
                kind="message",
                status="pending",
                expected_version=expected_version,
                payload=op_payload,
                created_at=now,
                updated_at=now,
            )

            self.events.emit(
                f"course:{course_id}",
                "message_submitted",
                {"message": msg_res.model_dump(), "operation_id": operation_id},
            )
            return msg_res, op_res
        finally:
            conn.close()

    def submit_opening(
        self,
        course_id: str,
        session_index: int,
        operation_id: str,
        expected_version: int,
    ) -> OperationResponse:
        """提交开场请求操作"""
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                existing = self._existing_operation(cur, course_id, session_index, operation_id, "opening")
                if existing:
                    return existing
                cur.execute("SELECT version, status FROM courses WHERE course_id = ?", (course_id,))
                c_row = cur.fetchone()
                if not c_row or c_row["status"] == "closed":
                    raise SessionClosedError("Course is closed")
                if c_row["version"] != expected_version:
                    raise VersionConflictError("Course version conflict")

                self._check_session(cur, course_id, session_index)
                cur.execute(
                    "SELECT 1 FROM course_messages WHERE course_id = ? AND session_index = ? LIMIT 1",
                    (course_id, session_index),
                )
                if cur.fetchone():
                    raise SessionClosedError("Opening is only allowed before the first message")

                cur.execute(
                    """SELECT operation_id FROM course_operations
                    WHERE course_id = ? AND session_index = ? AND status IN ('pending', 'running')""",
                    (course_id, session_index),
                )
                if cur.fetchone():
                    raise OperationBusyError("Operation active")

                now = utc_now()
                cur.execute(
                    """INSERT INTO course_operations
                    (operation_id, course_id, session_index, kind, status, expected_version, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, 'opening', 'pending', ?, '{}', ?, ?)""",
                    (operation_id, course_id, session_index, expected_version, now, now),
                )
                cur.execute(
                    "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                    (now, course_id),
                )
                self._enqueue_operation(conn, course_id, operation_id, "course_reply")

            op_res = OperationResponse(
                operation_id=operation_id,
                course_id=course_id,
                session_index=session_index,
                kind="opening",
                status="pending",
                expected_version=expected_version,
                payload={},
                created_at=now,
                updated_at=now,
            )
            self.events.emit(
                f"course:{course_id}",
                "opening_requested",
                {"operation_id": operation_id, "session_index": session_index},
            )
            return op_res
        finally:
            conn.close()

    def submit_close_session(
        self,
        course_id: str,
        session_index: int,
        operation_id: str,
        expected_version: int,
    ) -> OperationResponse:
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                existing = self._existing_operation(cur, course_id, session_index, operation_id, "close_session")
                if existing:
                    return existing
                cur.execute("SELECT version, status FROM courses WHERE course_id = ?", (course_id,))
                c_row = cur.fetchone()
                if not c_row or c_row["status"] == "closed":
                    raise SessionClosedError("Course is closed")
                if c_row["version"] != expected_version:
                    raise VersionConflictError("Version conflict")
                self._check_session(cur, course_id, session_index, closing=True)

                cur.execute(
                    "UPDATE course_sessions SET status = 'closing' WHERE course_id = ? AND session_index = ?",
                    (course_id, session_index),
                )
                now = utc_now()
                cur.execute(
                    """INSERT INTO course_operations
                    (operation_id, course_id, session_index, kind, status, expected_version, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, 'close_session', 'pending', ?, '{}', ?, ?)""",
                    (operation_id, course_id, session_index, expected_version, now, now),
                )
                cur.execute(
                    "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                    (now, course_id),
                )
                self._enqueue_operation(conn, course_id, operation_id, "course_close")

            op_res = OperationResponse(
                operation_id=operation_id,
                course_id=course_id,
                session_index=session_index,
                kind="close_session",
                status="pending",
                expected_version=expected_version,
                payload={},
                created_at=now,
                updated_at=now,
            )
            self.events.emit(
                f"course:{course_id}",
                "close_requested",
                {"operation_id": operation_id, "session_index": session_index},
            )
            return op_res
        finally:
            conn.close()

    def close_course(self, course_id: str, reason: str = "participant_closed_course") -> CourseResponse:
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute("SELECT status FROM courses WHERE course_id = ?", (course_id,))
                row = cur.fetchone()
                if row is None:
                    raise SessionClosedError("Course not found")
                if row["status"] == "closed":
                    return self.get_course(course_id)
                cur.execute(
                    """SELECT 1 FROM course_operations WHERE course_id = ?
                    AND status IN ('pending', 'running') LIMIT 1""", (course_id,),
                )
                if cur.fetchone():
                    raise OperationBusyError("Wait for the active operation before closing the course")
                cur.execute(
                    """UPDATE courses
                    SET status = 'closed', close_reason = ?, version = version + 1, updated_at = ?
                    WHERE course_id = ?""",
                    (reason, now, course_id),
                )
            self.events.emit(
                f"course:{course_id}",
                "course_closed",
                {"course_id": course_id, "reason": reason},
            )
            return self.get_course(course_id)
        finally:
            conn.close()


class InteractiveRunner:
    """执行人工交互中的模型生成与会后整理任务"""

    def __init__(
        self,
        counselor: CounselorAgent,
        gateway: Any,
        db_path: str | None = None,
    ):
        self.counselor = counselor
        self.gateway = gateway
        self.db_path = db_path
        self.events = get_event_hub(db_path)
        self.safety = SafetyStateMachine()
        self.extractor = MemoryExtractionAgent(gateway)
        self.merger = ClientMergeAgent(gateway)
        self.summarizer = DialogueSummaryAgent(gateway)
        self.consolidator = MemoryConsolidator()
        self.plan_builder = PlanBuilder()

    async def execute_operation(self, course_id: str, operation_id: str) -> None:
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as t_cur:
                t_cur.execute(
                    "SELECT * FROM course_operations WHERE operation_id = ? AND course_id = ?",
                    (operation_id, course_id),
                )
                op = t_cur.fetchone()
                if not op or op["status"] not in ("pending", "running"):
                    return
                session_index = op["session_index"]
                kind = op["kind"]
                execution_token = utc_now()
                t_cur.execute(
                    "UPDATE course_operations SET status = 'running', updated_at = ? WHERE operation_id = ?",
                    (execution_token, operation_id),
                )
        finally:
            conn.close()

        try:
            if kind in ("message", "opening"):
                await self._process_reply(course_id, session_index, operation_id, execution_token, is_opening=(kind == "opening"))
            elif kind == "close_session":
                await self._process_close(course_id, session_index, operation_id, execution_token)
        except Exception as exc:
            # 标记 operation failed
            conn = get_connection(self.db_path)
            try:
                with db_transaction(conn) as t_cur:
                    t_cur.execute(
                        """UPDATE course_operations
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE operation_id = ? AND status = 'running' AND updated_at = ?""",
                        (str(exc), utc_now(), operation_id, execution_token),
                    )
                    if t_cur.rowcount and kind == "close_session":
                        t_cur.execute(
                            """UPDATE course_sessions SET status = 'close_failed'
                            WHERE course_id = ? AND session_index = ? AND status = 'closing'""",
                            (course_id, session_index),
                        )
                self.events.emit(
                    f"course:{course_id}",
                    "operation_failed",
                    {"operation_id": operation_id, "error": str(exc)},
                )
            finally:
                conn.close()
            raise

    async def _process_reply(
        self, course_id: str, session_index: int, operation_id: str, execution_token: str, is_opening: bool
    ) -> None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT plan_json, memory_before_json FROM course_sessions WHERE course_id = ? AND session_index = ?",
                (course_id, session_index),
            )
            s_row = cur.fetchone()
            plan = SessionPlan.model_validate_json(s_row["plan_json"])
            memory = SessionMemory.model_validate_json(s_row["memory_before_json"])

            cur.execute(
                "SELECT * FROM course_messages WHERE course_id = ? AND session_index = ? ORDER BY created_at ASC",
                (course_id, session_index),
            )
            msg_rows = cur.fetchall()
            dialogue = [
                {"role": r["role"], "content": r["content"], "source": r["source"]}
                for r in msg_rows
            ]

            last_user_msg = ""
            if not is_opening:
                user_msgs = [m for m in dialogue if m["role"] == "participant"]
                if user_msgs:
                    last_user_msg = user_msgs[-1]["content"]

            counselor_turns_count = sum(1 for m in dialogue if m["role"] == "counselor")
            risk = self.safety.assess_input(last_user_msg)

            # 调用 CounselorAgent
            turn: CounselorTurn = await self.counselor.respond(
                memory=memory,
                plan=plan,
                client_message=last_user_msg,
                recent_messages=dialogue[-8:],
                risk=risk,
                counselor_turn_count=counselor_turns_count,
            )

            # 输出安全校验
            assessment = self.safety.assess_output(turn.response, risk)
            if assessment.categories:
                raise ValueError("Counselor output failed safety checks: " + ", ".join(assessment.categories))
            metadata = {
                "decision": turn.decision.model_dump() if turn.decision else {},
                "input_risk": risk.model_dump(mode="json"),
                "safety_assessment": assessment.model_dump() if assessment else {},
            }

            reply_msg_id = f"cmsg-{uuid.uuid4().hex[:12]}"
            now = utc_now()
            with db_transaction(conn) as t_cur:
                self._check_execution(t_cur, operation_id, execution_token)
                # 写入咨询师消息
                t_cur.execute(
                    """INSERT INTO course_messages
                    (message_id, course_id, session_index, role, source, content, metadata_json, created_at)
                    VALUES (?, ?, ?, 'counselor', 'counselor', ?, ?, ?)""",
                    (reply_msg_id, course_id, session_index, turn.response, json.dumps(metadata), now),
                )
                # 更新操作状态成功
                res_payload = {"reply_message_id": reply_msg_id, "utterance": turn.response}
                t_cur.execute(
                    """UPDATE course_operations
                    SET status = 'succeeded', result_json = ?, updated_at = ?
                    WHERE operation_id = ?""",
                    (json.dumps(res_payload), now, operation_id),
                )
                # 递增版本
                t_cur.execute(
                    "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                    (now, course_id),
                )

            self.events.emit(
                f"course:{course_id}",
                "counselor_replied",
                {
                    "message_id": reply_msg_id,
                    "session_index": session_index,
                    "content": turn.response,
                    "metadata": metadata,
                },
            )
        finally:
            conn.close()

    @staticmethod
    def _check_execution(cur, operation_id: str, execution_token: str) -> None:
        cur.execute(
            "SELECT status, updated_at FROM course_operations WHERE operation_id = ?",
            (operation_id,),
        )
        row = cur.fetchone()
        if not row or row["status"] != "running" or row["updated_at"] != execution_token:
            raise SessionClosedError("Operation was cancelled or replaced")

    async def _process_close(self, course_id: str, session_index: int, operation_id: str, execution_token: str) -> None:
        """执行会后整理闭环工作流"""
        async def run_step(course_id, session_index, name, fn):
            return await self._run_step(course_id, session_index, name, fn, operation_id, execution_token)

        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT plan_json, memory_before_json FROM course_sessions WHERE course_id = ? AND session_index = ?",
                (course_id, session_index),
            )
            s_row = cur.fetchone()
            plan = SessionPlan.model_validate_json(s_row["plan_json"])
            memory = SessionMemory.model_validate_json(s_row["memory_before_json"])

            cur.execute(
                "SELECT role, content FROM course_messages WHERE course_id = ? AND session_index = ? ORDER BY created_at ASC",
                (course_id, session_index),
            )
            dialogue_msgs = [
                Message(
                    session_index=session_index,
                    turn_index=idx + 1,
                    role="counselor" if r["role"] == "counselor" else "client",
                    content=r["content"],
                )
                for idx, r in enumerate(cur.fetchall())
            ]

            # 步骤 1: E.7 提取 (Extract)
            step1_out = await run_step(
                course_id, session_index, "extract",
                lambda: self.extractor.extract(dialogue_msgs, [plan.therapy], session_index),
            )
            extracted: ExtractedClientInfo = (
                ExtractedClientInfo.model_validate(step1_out)
                if isinstance(step1_out, dict) else step1_out
            )

            # 步骤 2: E.8 档案合并 (Merge)
            step2_out = await run_step(
                course_id, session_index, "merge",
                lambda: self.merger.merge(memory.known_background, extracted, [plan.therapy]),
            )
            unlocked: UnlockedClientInfo = (
                UnlockedClientInfo.model_validate(step2_out)
                if isinstance(step2_out, dict) else step2_out
            )
            memory.known_background = unlocked

            # 步骤 3: E.9 临床摘要 (Summary)
            step3_out = await run_step(
                course_id, session_index, "summary",
                lambda: self.summarizer.summarize(session_index, dialogue_msgs, plan, [plan.therapy], SessionChecklist()),
            )
            clinical_summary: ClinicalSummary = (
                ClinicalSummary.model_validate(step3_out)
                if isinstance(step3_out, dict) else step3_out
            )

            # 构造鸭子类型的会谈视图供 Consolidator 与 review 使用，不伪造 ClientState
            dummy_session = InteractiveSessionView(
                session_index=session_index,
                plan=plan,
                summary=clinical_summary.session_summary_abstract,
                clinical_summary=clinical_summary,
                messages=dialogue_msgs,
                end_reason="participant_ended",
            )

            # 步骤 4: 记忆整合 (Consolidate)
            def do_consolidate():
                warnings = []
                new_mem = self.consolidator.consolidate(
                    memory, dummy_session, next_index=session_index + 1, warnings=warnings
                )
                return new_mem.model_dump(mode="json")

            step4_out = await run_step(course_id, session_index, "consolidate", do_consolidate)
            memory_after = SessionMemory.model_validate(step4_out)

            # 步骤 5: 咨询师自评 (Review)
            baseline_next = SessionPlan(
                therapy=plan.therapy,
                stage=plan.stage,
                session_index=session_index + 1,
                objectives=plan.objectives,
            )
            step5_out = await run_step(
                course_id, session_index, "review",
                lambda: self.counselor.review_session(
                    session=dummy_session,
                    memory=memory_after,
                    baseline_next=baseline_next,
                ),
            )
            review_obj = step5_out if isinstance(step5_out, dict) else step5_out.model_dump()

            # 步骤 6: 下一计划 (Plan)
            def do_plan():
                report = LongitudinalReport(
                    session_index=session_index,
                    trend="baseline" if session_index == 1 else "stable",
                    stage_action="continue",
                    evidence=["人工疗程默认推进"],
                )
                rev = (
                    CounselorSessionReview.model_validate(review_obj)
                    if isinstance(review_obj, dict) else review_obj
                )
                next_p = self.plan_builder.build(
                    plan, baseline_next, report, rev
                )
                return next_p.model_dump(mode="json")

            step6_out = await run_step(course_id, session_index, "plan", do_plan)

            now = utc_now()
            with db_transaction(conn) as t_cur:
                self._check_execution(t_cur, operation_id, execution_token)
                # 关闭会谈
                t_cur.execute(
                    """UPDATE course_sessions
                    SET status = 'closed',
                        memory_after_json = ?,
                        next_plan_json = ?,
                        review_json = ?,
                        close_reason = 'participant_ended',
                        closed_at = ?
                    WHERE course_id = ? AND session_index = ?""",
                    (
                        memory_after.model_dump_json(),
                        json.dumps(step6_out),
                        json.dumps(review_obj),
                        now,
                        course_id,
                        session_index,
                    ),
                )
                # 标记 operation 成功
                t_cur.execute(
                    """UPDATE course_operations
                    SET status = 'succeeded', result_json = ?, updated_at = ?
                    WHERE operation_id = ?""",
                    (json.dumps({"closed_session_index": session_index}), now, operation_id),
                )
                # 递增版本
                t_cur.execute(
                    "UPDATE courses SET version = version + 1, updated_at = ? WHERE course_id = ?",
                    (now, course_id),
                )

            self.events.emit(
                f"course:{course_id}",
                "session_closed",
                {
                    "session_index": session_index,
                    "memory_after": memory_after.model_dump(mode="json"),
                    "next_plan": step6_out,
                },
            )
        finally:
            conn.close()

    async def _run_step(
        self, course_id: str, session_index: int, step_name: str, fn: Any,
        operation_id: str, execution_token: str,
    ) -> Any:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            self._check_execution(cur, operation_id, execution_token)
            cur.execute(
                """SELECT status, output_json FROM course_close_steps
                WHERE course_id = ? AND session_index = ? AND step_name = ?""",
                (course_id, session_index, step_name),
            )
            existing = cur.fetchone()
            if existing and existing["status"] == "succeeded" and existing["output_json"]:
                return json.loads(existing["output_json"])
        finally:
            conn.close()

        now = utc_now()
        try:
            res = fn()
            if hasattr(res, "__await__"):
                res = await res
            out_dict = res.model_dump(mode="json") if hasattr(res, "model_dump") else res

            conn = get_connection(self.db_path)
            try:
                with db_transaction(conn) as t_cur:
                    self._check_execution(t_cur, operation_id, execution_token)
                    t_cur.execute(
                        """INSERT OR REPLACE INTO course_close_steps
                        (course_id, session_index, step_name, status, input_summary_json, output_json, error, created_at)
                        VALUES (?, ?, ?, 'succeeded', '{}', ?, NULL, ?)""",
                        (course_id, session_index, step_name, json.dumps(out_dict, ensure_ascii=False), now),
                    )
            finally:
                conn.close()
            return out_dict
        except Exception as exc:
            conn = get_connection(self.db_path)
            try:
                with db_transaction(conn) as t_cur:
                    self._check_execution(t_cur, operation_id, execution_token)
                    t_cur.execute(
                        """INSERT OR REPLACE INTO course_close_steps
                        (course_id, session_index, step_name, status, input_summary_json, output_json, error, created_at)
                        VALUES (?, ?, ?, 'failed', '{}', NULL, ?, ?)""",
                        (course_id, session_index, step_name, str(exc), now),
                    )
            finally:
                conn.close()
            raise
