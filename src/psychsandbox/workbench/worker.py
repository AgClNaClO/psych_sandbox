"""科研 Web 工作台独立 Worker 调度器

支持参数：
--lane long: 执行长仿真任务、仿真验证、整体督导重评
--lane short: 执行人工交互回复生成、会后整理分步工作流、固定上下文单轮回放
保持单进程互斥，严格租约心跳，双重栅栏防覆盖。
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sys
import traceback
import time
import uuid
from typing import Any, Callable

from dotenv import load_dotenv

# 优先加载项目根目录下的 .env 配置
env_path = Path(__file__).resolve().parents[3] / ".env"
if env_path.exists():
    load_dotenv(env_path)

from .db import db_transaction, get_connection, init_db, utc_now
from .job_manager import JobManager
from .evolution import SkillEvolutionLab
from .models import JobLane, JobResponse, SimulationJobPayload
from .events import get_event_hub
from .interactive import CourseManager, InteractiveRunner
from ..runtime import CounselingSandbox
from ..runtime.progress import RunProgress, ScoringProgress, SimulationProgressTracker, TurnProgress
from ..runtime.storage import SQLiteStore
from ..runtime.run_management import available_run_dir
from ..visualization import generate_run_report
from ..domain import SandboxConfig
from ..model_client import create_gateway
from ..agents.counselor import CounselorAgent
from ..config import default_config
from ..skills import SkillCatalog, SkillRegistry
from ..therapies import normalize_therapy_id


class WorkbenchWorker:
    def __init__(
        self,
        lane: JobLane,
        db_path: str | None = None,
        gateway_factory: Callable[[], Any] | None = None,
        lease_seconds: int = 60,
        heartbeat_interval: float = 10.0,
    ):
        self.lane = lane
        self.db_path = db_path
        self.worker_id = f"worker-{lane}-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.job_manager = JobManager(db_path)
        self.event_hub = get_event_hub(db_path)
        self.gateway_factory = gateway_factory or create_gateway
        self._running = False
        self._current_job: JobResponse | None = None
        self._stop_requested_for_job = False
        self._cancel_requested_for_job = False

    async def start(self) -> None:
        init_db(self.db_path)
        self._running = True
        print(f"[{self.worker_id}] 启动，正在监听 lane={self.lane}...")

        while self._running:
            try:
                # 1. 尝试回收过期任务
                self.job_manager.reap_stale_jobs()

                # 2. 认领任务
                job = self.job_manager.claim_job(
                    self.lane, self.worker_id, lease_seconds=self.lease_seconds
                )
                if not job:
                    await asyncio.sleep(1.0)
                    continue

                print(f"[{self.worker_id}] 认领到任务 job_id={job.job_id}, kind={job.kind}, attempt={job.attempt}")
                self._current_job = job
                self._stop_requested_for_job = job.stop_requested
                self._cancel_requested_for_job = job.cancel_requested

                # 3. 启动心跳协程并执行任务
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(job.job_id, job.attempt)
                )
                execution_task = asyncio.create_task(self._execute_job(job))

                done, pending = await asyncio.wait(
                    [heartbeat_task, execution_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if execution_task in done:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                else:
                    # 心跳协程先结束说明租约丢失或被取消
                    execution_task.cancel()
                    try:
                        await execution_task
                    except asyncio.CancelledError:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[{self.worker_id}] 调度循环异常: {exc}", file=sys.stderr)
                await asyncio.sleep(2.0)
            finally:
                self._current_job = None

    def stop(self) -> None:
        self._running = False

    async def _heartbeat_loop(self, job_id: str, attempt: int) -> None:
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            valid, stop_req, cancel_req = self.job_manager.heartbeat(
                job_id, attempt, self.worker_id, lease_seconds=self.lease_seconds
            )
            if not valid:
                print(f"[{self.worker_id}] 任务 {job_id} 租约失效或已被抢占，退出执行")
                break
            if stop_req:
                self._stop_requested_for_job = True
            if cancel_req:
                self._cancel_requested_for_job = True
                print(f"[{self.worker_id}] 任务 {job_id} 收到取消请求")
                break

    async def _execute_job(self, job: JobResponse) -> None:
        kind = job.kind
        try:
            if kind == "simulation":
                await self._run_simulation_job(job)
            elif kind in ("course_reply", "course_close"):
                await self._run_course_job(job)
            else:
                raise ValueError(f"Unknown job kind: {kind}")
        except asyncio.CancelledError:
            if self.job_manager.mark_cancelled_job(job.job_id, job.attempt, self.worker_id):
                if job.course_id and job.payload.get("operation_id"):
                    self._fail_course_operation(job.course_id, job.payload["operation_id"], "Job cancelled", job)
                self.event_hub.emit(f"job:{job.job_id}", "job_cancelled", {"job_id": job.job_id})
            raise
        except Exception as exc:
            traceback.print_exc()
            if self.job_manager.fail_job(
                job.job_id, job.attempt, self.worker_id, str(exc),
                retryable=job.kind == "simulation" and not isinstance(exc, (ValueError, KeyError)),
            ):
                current = self.job_manager.get_job(job.job_id)
                self.event_hub.emit(
                    f"job:{job.job_id}", "job_requeued" if current.status == "queued" else "job_failed",
                    {"job_id": job.job_id, "error": str(exc)},
                )

    def _release_ids(self, job, lab):
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute("SELECT payload_json FROM jobs WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status = 'running' AND lease_expires_at > ?", (job.job_id, job.attempt, self.worker_id, utc_now()))
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("Job lease lost before skill resolution")
                cur.execute("SELECT release_ids_json FROM job_skill_snapshots WHERE job_id = ?", (job.job_id,))
                snapshot = cur.fetchone()
                if snapshot:
                    return json.loads(snapshot["release_ids_json"])
                release_ids = [r.release_id for r in lab.list_releases() if r.is_active]
                cur.execute("INSERT INTO job_skill_snapshots VALUES (?, ?)", (job.job_id, json.dumps(release_ids)))
                return release_ids
        finally:
            conn.close()

    async def _run_simulation_job(self, job: JobResponse) -> None:
        payload = job.payload
        requested = SimulationJobPayload.model_validate(payload)
        case_id = payload["case_id"]
        therapy = payload.get("therapy")
        session_count = payload.get("session_count", 1)
        seed = payload.get("seed")
        resume_run_id = payload.get("resume_run_id")
        run_id = resume_run_id or job.run_id or payload.get("run_id")
        if run_id and not self.job_manager.bind_run(job.job_id, job.attempt, self.worker_id, run_id):
            return

        config = default_config()
        values = config.model_dump()
        overrides = requested.model_dump(exclude_none=True, exclude_unset=True)
        for key in ("max_turns_per_session", "session_turn_limits"):
            if key in overrides:
                values[key] = overrides[key]
        if "rft" in overrides:
            values["rft"] = {**values["rft"], **overrides["rft"]}
        # Resume/retry uses the original experiment settings even if YAML changed.
        if run_id:
            with closing(SQLiteStore(config.database_path)) as store:
                try:
                    saved = store.load_run_metadata(run_id)["config"]
                except KeyError:
                    saved = None
            if saved:
                for key, fallback in (("max_turns_per_session", 8), ("session_turn_limits", []), ("rft", {})):
                    original = saved.get(key, fallback)
                    changed = (any(original.get(field) != value for field, value in overrides[key].items())
                               if key == "rft" and key in overrides else values[key] != original)
                    if key in overrides and changed:
                        raise ValueError(f"Resume must preserve the original {key}")
                    values[key] = original
        config = SandboxConfig.model_validate(values)
        gateway = self.gateway_factory()
        sandbox = CounselingSandbox(config, gateway=gateway)

        lab = SkillEvolutionLab(self.db_path, sandbox.config.project_root / "assets/skills/sect")
        registry = lab.runtime_registry(sandbox.config.project_root, self._release_ids(job, lab))
        sandbox.registry = registry
        sandbox.skill_catalog = SkillCatalog(registry)
        sandbox.counselor.skill_catalog = sandbox.skill_catalog

        tracker = SimulationProgressTracker(session_count, candidates_total=config.rft.candidates if config.rft.enabled else 1)
        last_progress_at = 0.0
        revision = 0

        def status_cb(event: RunProgress | TurnProgress | ScoringProgress | None):
            nonlocal last_progress_at, revision
            previous_phase = tracker.stage.phase
            new_candidate = isinstance(event, TurnProgress) and (event.label or "1") not in tracker.candidates
            snapshot = tracker.update(event)
            now = time.monotonic()
            finished_tick = (isinstance(event, TurnProgress) and event.turn_index >= event.total_turns
                             or isinstance(event, ScoringProgress) and event.candidates_scored >= event.candidates_total)
            changed_phase = snapshot["phase"] != previous_phase
            if (event is not None and not isinstance(event, RunProgress) and not finished_tick
                    and not changed_phase and not new_candidate and now - last_progress_at < 0.3):
                return
            revision += 1
            snapshot.update(attempt=job.attempt, revision=revision, updated_at=utc_now())
            self.event_hub.emit(
                f"job:{job.job_id}", "simulation_status",
                {"job_id": job.job_id, "run_id": run_id, "attempt": job.attempt, "progress": snapshot},
                job_fence=(job.job_id, job.attempt, self.worker_id),
            )
            last_progress_at = now

        def progress_cb(msg: str):
            nonlocal run_id
            if run_id is None and sandbox.run_dir is not None:
                run_id = json.loads((sandbox.run_dir / "run.json").read_text(encoding="utf-8"))["run_id"]
                if not self.job_manager.bind_run(job.job_id, job.attempt, self.worker_id, run_id):
                    raise RuntimeError("Job lease was lost before run initialization")
            self.event_hub.emit(
                f"job:{job.job_id}",
                "simulation_progress",
                {"message": msg, "job_id": job.job_id, "run_id": run_id},
            )

        def should_stop() -> bool:
            return self._stop_requested_for_job or self._cancel_requested_for_job

        try:
            try:
                existing = sandbox.store.load_run_metadata(run_id) if run_id else None
            except KeyError:
                existing = None
            if existing is not None:
                resume_run_id = run_id
            if existing and (existing["case_id"] != case_id
                             or (therapy and existing["therapy"] != normalize_therapy_id(therapy))
                             or (seed is not None and seed != existing["seed"])):
                raise ValueError("Retry/resume must preserve the original case, therapy and seed")
            if (existing and job.attempt > 1 and existing["status"] == "completed"):
                result = sandbox.store.load_run(run_id)
            else:
                result = await sandbox.run_case(
                    case_id=case_id, therapy=therapy, session_count=session_count,
                    seed=seed, resume_run_id=resume_run_id, run_id=run_id,
                    progress_callback=progress_cb, should_stop=should_stop,
                    turn_progress=status_cb, status_progress=status_cb,
                )
        finally:
            sandbox.store.close()

        # Match CLI reporting; reacquire the run lock and honor deletion journals.
        status_cb(RunProgress("report", len(result.sessions), session_count,
                              len(result.sessions), tracker.snapshot()["elapsed"]))
        with available_run_dir(config.trace_dir, result.run_id) as report_dir:
            generate_run_report(result, report_dir / "report.html")

        res_dict = {
            "run_id": result.run_id,
            "case_id": result.case_id,
            "sessions_completed": len(result.sessions),
            "status": "stopped" if should_stop() else "completed",
        }

        if should_stop():
            if self.job_manager.mark_stopped_job(job.job_id, job.attempt, self.worker_id, res_dict):
                self.event_hub.emit(f"job:{job.job_id}", "job_stopped", res_dict)
        else:
            if self.job_manager.complete_job(job.job_id, job.attempt, self.worker_id, res_dict):
                self.event_hub.emit(f"job:{job.job_id}", "job_succeeded", res_dict)

    def _fail_course_operation(self, course_id: str, operation_id: str, error: str, job: JobResponse) -> None:
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute("SELECT 1 FROM jobs WHERE job_id = ? AND attempt = ? AND lease_owner = ? AND status IN ('running', 'cancelled')", (job.job_id, job.attempt, self.worker_id))
                if cur.fetchone() is None:
                    return
                cur.execute(
                    """UPDATE course_operations
                    SET status = 'failed', error = ?, updated_at = ?
                    WHERE operation_id = ? AND course_id = ? AND status IN ('pending', 'running')""",
                    (error, utc_now(), operation_id, course_id),
                )
                if cur.rowcount:
                    cur.execute(
                        """UPDATE course_sessions SET status = 'close_failed'
                        WHERE course_id = ? AND status = 'closing' AND session_index = (
                            SELECT session_index FROM course_operations WHERE operation_id = ?
                            AND kind = 'close_session')""", (course_id, operation_id),
                    )
        except Exception as db_err:
            print(f"[{self.worker_id}] 释放操作锁失败: {db_err}")
        finally:
            conn.close()
        self.event_hub.emit(
            f"course:{course_id}",
            "operation_failed",
            {"course_id": course_id, "operation_id": operation_id, "error": error},
        )

    async def _run_course_job(self, job: JobResponse) -> None:
        payload = job.payload
        course_id = job.course_id or payload.get("course_id")
        operation_id = payload.get("operation_id")

        try:
            gateway = self.gateway_factory()
            config = default_config()
            lab = SkillEvolutionLab(self.db_path, config.project_root / "assets/skills/sect")
            release_ids = self._release_ids(job, lab)
            course = CourseManager(self.db_path).get_course(course_id)
            if course.skill_release_id:
                release = lab.get_release(course.skill_release_id)
                if not release or release.therapy != course.therapy:
                    raise ValueError("Course skill release must match its therapy")
                release_ids = [course.skill_release_id]
            counselor = CounselorAgent(
                gateway=gateway,
                skill_catalog=SkillCatalog(lab.runtime_registry(config.project_root, release_ids)),
                temperature=config.temperature_counselor,
                skill_selection=config.skill_selection,
                memory_view=config.memory_view,
                control_temperature=config.temperature_control,
            )
            runner = InteractiveRunner(counselor=counselor, gateway=gateway, db_path=self.db_path)

        except Exception as exc:
            if course_id and operation_id:
                self._fail_course_operation(course_id, operation_id, str(exc), job)
            raise

        await runner.execute_operation(course_id=course_id, operation_id=operation_id,
                                       job_fence=(job.job_id, job.attempt, self.worker_id))
        if self.job_manager.complete_job(
            job.job_id, job.attempt, self.worker_id, {"course_id": course_id, "operation_id": operation_id}
        ):
            self.event_hub.emit(
                f"job:{job.job_id}", "job_succeeded",
                {"course_id": course_id, "operation_id": operation_id},
            )


def main():
    parser = argparse.ArgumentParser(description="PsychSandbox Workbench Worker")
    parser.add_argument("--lane", choices=["long", "short"], default="long", help="Lane to process")
    parser.add_argument("--db", type=str, default=None, help="Database path")
    args = parser.parse_args()

    worker = WorkbenchWorker(lane=args.lane, db_path=args.db)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal():
        print("收到终止信号，正在优雅关闭 Worker...")
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, AttributeError):
            pass

    try:
        loop.run_until_complete(worker.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
