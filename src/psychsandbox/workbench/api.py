"""科研 Web 工作台 FastAPI 核心后端路由与服务

提供完整的 REST API 与 SSE 实时事件流，涵盖：
1. 实验台：流派/案例选择、任务调度、会谈边界续跑/停止、回放与报告下载；
2. 人工聊天：多会谈连续对话、开场触发、幂等发送、防双标签冲突、会后整理重试；
3. 技能实验室：不可变发布、提案、固定上下文对比、专家审核与防冒充、回滚；
4. 评测中心：实验指标多源横向对比、SFT/DPO 严格合规导出与审计留痕。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[3] / ".env"
if env_path.exists():
    load_dotenv(env_path)

from fastapi import FastAPI, HTTPException, Header, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..artifacts import find_run_dir
from ..config import default_config
from ..datasets import CaseRepository
from ..domain import SandboxConfig
from ..runtime.storage import SQLiteStore
from ..therapies import normalize_therapy_id
from .db import init_db
from .events import get_event_hub
from .evolution import EvolutionValidationError, SkillEvolutionLab
from .export import DataExporter, ExperimentAnalytics
from .interactive import (
    CourseManager,
    OperationBusyError,
    SessionClosedError,
    VersionConflictError,
)
from .job_manager import JobManager
from .models import (
    CourseCreateRequest,
    CourseResponse,
    CourseSessionDetailResponse,
    ExpertReviewCreateRequest,
    ExportAuditResponse,
    ExportDPORequest,
    ExportSFTRequest,
    JobCreateRequest,
    JobResponse,
    OperationResponse,
    SendMessageRequest,
    SkillProposalCreateRequest,
    SkillProposalResponse,
    SkillReleaseResponse,
)
from .projections import (
    get_run_detail,
    list_case_summaries,
    list_experiment_runs,
    list_therapy_definitions,
)


def create_app(
    db_path: str | None = None,
    sim_db_path: Path | None = None,
    trace_dir: Path | None = None,
    assets_dir: Path | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    init_db(db_path)
    config = default_config()
    sim_store_path = sim_db_path or config.database_path
    sim_store = SQLiteStore(sim_store_path)
    trace_directory = trace_dir or config.trace_dir
    assets_directory = assets_dir or (config.project_root / "assets" / "skills" / "sect")
    case_repo = CaseRepository(config.processed_dataset_dir)

    job_mgr = JobManager(db_path)
    event_hub = get_event_hub(db_path)
    course_mgr = CourseManager(db_path)
    evolution_lab = SkillEvolutionLab(db_path, assets_dir=assets_directory)
    exporter = DataExporter(sim_store, workbench_db_path=db_path)
    analytics = ExperimentAnalytics(sim_store, wb_db_path=db_path)

    app = FastAPI(title="PsychSandbox Scientific Workbench", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ====================================================
    # 1. 实验台与仿真任务
    # ====================================================

    @app.get("/api/therapies")
    def get_therapies():
        return list_therapy_definitions()

    @app.get("/api/cases")
    def get_cases():
        return list_case_summaries(case_repo)

    @app.get("/api/runs")
    def get_runs():
        return list_experiment_runs(sim_store, trace_directory)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        detail = get_run_detail(sim_store, trace_directory, run_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Run not found")
        return detail

    @app.get("/api/runs/{run_id}/report", response_class=HTMLResponse)
    def get_run_html_report(run_id: str):
        try:
            r_dir = find_run_dir(trace_directory, run_id)
            html_file = r_dir / "report.html"
            if not html_file.exists():
                raise HTTPException(status_code=404, detail="HTML report not found")
            return html_file.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Failed to find run directory: {exc}")

    @app.post("/api/jobs", response_model=JobResponse)
    def create_job(req: JobCreateRequest):
        job = job_mgr.enqueue_job(
            kind=req.kind,
            lane=req.lane,
            payload=req.payload,
            run_id=req.run_id,
            course_id=req.course_id,
            max_attempts=req.max_attempts,
        )
        event_hub.emit("jobs", "job_enqueued", {"job_id": job.job_id, "kind": job.kind, "lane": job.lane})
        return job

    @app.get("/api/jobs", response_model=list[JobResponse])
    def list_jobs(lane: str | None = None, limit: int = 50):
        return job_mgr.list_jobs(lane=lane, limit=limit)

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str):
        job = job_mgr.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        ok = job_mgr.request_stop(job_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Cannot request stop for this job (not running)")
        event_hub.emit(f"job:{job_id}", "stop_requested", {"job_id": job_id})
        return {"status": "stop_requested", "job_id": job_id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        ok = job_mgr.request_cancel(job_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Cannot cancel this job")
        event_hub.emit(f"job:{job_id}", "cancel_requested", {"job_id": job_id})
        return {"status": "cancelled_or_cancel_requested", "job_id": job_id}

    # ====================================================
    # 2. 人工聊天交互
    # ====================================================

    @app.post("/api/courses", response_model=CourseResponse)
    def create_course(req: CourseCreateRequest):
        course = course_mgr.create_course(
            therapy=req.therapy,
            title=req.title,
            input_mode=req.input_mode,
            roleplay_card=req.roleplay_card,
            skill_release_id=req.skill_release_id,
        )
        return course

    @app.get("/api/courses", response_model=list[CourseResponse])
    def list_courses():
        return course_mgr.list_courses()

    @app.get("/api/courses/{course_id}", response_model=CourseResponse)
    def get_course(course_id: str):
        c = course_mgr.get_course(course_id)
        if not c:
            raise HTTPException(status_code=404, detail="Course not found")
        return c

    @app.post("/api/courses/{course_id}/sessions", response_model=CourseSessionDetailResponse)
    def start_next_session(course_id: str):
        try:
            return course_mgr.create_session(course_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/courses/{course_id}/sessions/{session_index}", response_model=CourseSessionDetailResponse)
    def get_session(course_id: str, session_index: int):
        s = course_mgr.get_session_detail(course_id, session_index)
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        return s

    @app.post("/api/courses/{course_id}/sessions/{session_index}/opening", response_model=OperationResponse)
    def trigger_opening(
        course_id: str,
        session_index: int,
        operation_id: str = Query(...),
        expected_version: int = Query(...),
    ):
        try:
            op = course_mgr.submit_opening(course_id, session_index, operation_id, expected_version)
            job_mgr.enqueue_job(
                kind="course_reply",
                lane="short",
                payload={"course_id": course_id, "operation_id": operation_id},
                course_id=course_id,
            )
            return op
        except VersionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except OperationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except SessionClosedError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/api/courses/{course_id}/sessions/{session_index}/messages")
    def send_user_message(course_id: str, session_index: int, req: SendMessageRequest):
        try:
            msg, op = course_mgr.submit_user_message(
                course_id=course_id,
                session_index=session_index,
                message_id=req.message_id,
                operation_id=req.operation_id,
                expected_version=req.expected_version,
                content=req.content,
                source=req.source,
            )
            job_mgr.enqueue_job(
                kind="course_reply",
                lane="short",
                payload={"course_id": course_id, "operation_id": req.operation_id},
                course_id=course_id,
            )
            return {"message": msg, "operation": op}
        except VersionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except OperationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except SessionClosedError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/api/courses/{course_id}/sessions/{session_index}/close", response_model=OperationResponse)
    def close_current_session(
        course_id: str,
        session_index: int,
        operation_id: str = Query(...),
        expected_version: int = Query(...),
    ):
        try:
            op = course_mgr.submit_close_session(course_id, session_index, operation_id, expected_version)
            job_mgr.enqueue_job(
                kind="course_close",
                lane="short",
                payload={"course_id": course_id, "operation_id": operation_id},
                course_id=course_id,
            )
            return op
        except VersionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    @app.post("/api/courses/{course_id}/sessions/{session_index}/reset-lock")
    def reset_session_lock(course_id: str, session_index: int):
        affected = course_mgr.reset_session_lock(course_id, session_index)
        return {"status": "ok", "unlocked_operations": affected}

    @app.post("/api/courses/{course_id}/close", response_model=CourseResponse)
    def close_course(course_id: str, reason: str = "participant_closed_course"):
        return course_mgr.close_course(course_id, reason=reason)

    # ====================================================
    # 3. 技能实验室与演化
    # ====================================================

    @app.get("/api/skills/releases", response_model=list[SkillReleaseResponse])
    def list_releases(therapy: str | None = None):
        return evolution_lab.list_releases(therapy=therapy)

    @app.get("/api/skills/releases/{release_id}", response_model=SkillReleaseResponse)
    def get_release(release_id: str):
        rel = evolution_lab.get_release(release_id)
        if not rel:
            raise HTTPException(status_code=404, detail="Skill release not found")
        return rel

    @app.post("/api/skills/releases/{release_id}/rollback", response_model=SkillReleaseResponse)
    def rollback_release(release_id: str, therapy: str = Query(...)):
        try:
            return evolution_lab.rollback_release(therapy, release_id)
        except EvolutionValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/skills/proposals", response_model=list[SkillProposalResponse])
    def list_proposals(therapy: str | None = None):
        return evolution_lab.list_proposals(therapy=therapy)

    @app.post("/api/skills/proposals", response_model=SkillProposalResponse)
    def submit_proposal(req: SkillProposalCreateRequest):
        base_id = req.base_release_id
        if not base_id:
            active_rel = evolution_lab.get_active_release(req.therapy)
            base_id = active_rel.release_id if active_rel else "base_tree"
        try:
            return evolution_lab.submit_proposal(
                therapy=req.therapy,
                base_release_id=base_id,
                title=req.title,
                target_skill_id=req.target_skill_id,
                parent_meta_id=req.parent_meta_id,
                stage=req.stage,
                content=req.content,
                justification=req.justification,
                author=req.author,
            )
        except EvolutionValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/skills/proposals/{proposal_id}", response_model=SkillProposalResponse)
    def get_proposal(proposal_id: str):
        p = evolution_lab.get_proposal(proposal_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return p

    @app.post("/api/skills/proposals/{proposal_id}/reviews")
    def review_proposal(proposal_id: str, req: ExpertReviewCreateRequest):
        try:
            return evolution_lab.submit_expert_review(
                proposal_id=proposal_id,
                reviewer_id=req.reviewer_id,
                reviewer_name=req.reviewer_name,
                verdict=req.verdict,
                rationale=req.rationale,
                checklist=req.checklist,
            )
        except EvolutionValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/skills/proposals/{proposal_id}/publish", response_model=SkillReleaseResponse)
    def publish_proposal(
        proposal_id: str, published_by: str = Query(...), release_name: str = Query(...)
    ):
        try:
            return evolution_lab.publish_approved_proposal(
                proposal_id=proposal_id, published_by=published_by, release_name=release_name
            )
        except EvolutionValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/skills/tree/{therapy}")
    def get_skill_tree(therapy: str):
        try:
            norm = normalize_therapy_id(therapy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        raw_tree = evolution_lab.load_raw_skill_tree(norm)
        if not raw_tree:
            raise HTTPException(status_code=404, detail=f"Therapy skill tree not found for {norm}")
        active_rel = evolution_lab.get_active_release(norm)
        overlay = active_rel.overlay_skills if active_rel else {}
        return {
            "therapy": norm,
            "raw_tree": raw_tree,
            "overlay_skills": overlay,
            "active_release": active_rel,
        }

    # ====================================================
    # 4. 评测中心与数据导出
    # ====================================================

    @app.get("/api/analytics/comparisons")
    def get_comparisons():
        return analytics.get_comparison_rows()

    @app.post("/api/exports/sft", response_model=ExportAuditResponse)
    def export_sft(req: ExportSFTRequest):
        target = Path("runs/exports") / req.output_filename
        return exporter.export_sft(
            output_path=target,
            run_ids=req.run_ids,
            protocol_version=req.protocol_version,
            include_interactive=req.include_interactive,
        )

    @app.post("/api/exports/dpo", response_model=ExportAuditResponse)
    def export_dpo(req: ExportDPORequest):
        target = Path("runs/exports") / req.output_filename
        return exporter.export_dpo(
            output_path=target,
            run_ids=req.run_ids,
            protocol_version=req.protocol_version,
        )

    @app.get("/api/exports/audits", response_model=list[ExportAuditResponse])
    def list_export_audits():
        return exporter.list_audits()

    # ====================================================
    # 5. SSE 事件流
    # ====================================================

    @app.get("/api/events")
    async def sse_events(
        stream: str = Query("jobs"),
        after_seq: int = Query(0),
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ):
        start_seq = after_seq
        if last_event_id and last_event_id.isdigit():
            start_seq = max(start_seq, int(last_event_id))

        async def event_generator() -> AsyncGenerator[str, None]:
            # 立即发送握手事件，通知客户端 SSE 通道已连通
            yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
            async for ev in event_hub.subscribe(stream, after_seq=start_seq):
                if ev.type == "ping":
                    yield ": ping\n\nevent: ping\ndata: {}\n\n"
                    continue
                data_str = json.dumps(ev.payload, ensure_ascii=False)
                yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {data_str}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ====================================================
    # 6. 前端静态资源托管（若已打包构建）
    # ====================================================
    f_dir = frontend_dir or (config.project_root / "src" / "psychsandbox" / "workbench" / "frontend_dist")
    if f_dir.exists():
        app.mount("/", StaticFiles(directory=str(f_dir), html=True), name="frontend")

    return app
