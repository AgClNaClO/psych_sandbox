"""Additive API adapter. Disabled by default, no storage created on import."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .skill_experiment import (
    CreateExperiment, ExperimentStore, JobRequest, import_source, source_sessions,
)


def experiment_router(project_root: Path, base: Path, source_db: Path, assets_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/skill-experiments", tags=["isolated skill experiments"])
    store = ExperimentStore(base)

    def require_enabled():
        if os.getenv("PSYCHSANDBOX_SKILL_EXPERIMENT", "").lower() not in {"1", "true", "yes"}:
            raise HTTPException(403, "技能进化试验未启用；请设置 PSYCHSANDBOX_SKILL_EXPERIMENT=1 后启动工作台")

    def invoke(function, *args):
        require_enabled()
        try:
            return function(*args)
        except FileNotFoundError:
            raise HTTPException(404, "实验或来源文件不存在") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.get("/status")
    def status():
        enabled = os.getenv("PSYCHSANDBOX_SKILL_EXPERIMENT", "").lower() in {"1", "true", "yes"}
        return {"enabled": enabled, "isolated": True}

    @router.get("/sources")
    def sources():
        return invoke(source_sessions, source_db)

    @router.get("")
    def experiments():
        return invoke(store.list)

    @router.post("")
    def create(request: CreateExperiment):
        require_enabled()
        from ..skills import SkillRegistry
        source = invoke(import_source, source_db, request)
        registry = SkillRegistry.from_psychagent_assets(assets_dir)
        return invoke(store.create, source, registry)

    @router.get("/{experiment_id}")
    def detail(experiment_id: str):
        return invoke(store.read, experiment_id)

    @router.post("/{experiment_id}/jobs", status_code=202)
    def start(experiment_id: str, request: JobRequest):
        job = invoke(store.enqueue, experiment_id, request)
        try:
            store.launch(experiment_id, job["id"], project_root)
        except OSError:
            raise HTTPException(503, "独立实验进程启动失败，详见后端日志") from None
        return job

    @router.post("/{experiment_id}/candidates/{candidate_id}/apply")
    def apply(experiment_id: str, candidate_id: str):
        return invoke(store.apply, experiment_id, candidate_id)

    @router.post("/{experiment_id}/recover")
    def recover(experiment_id: str):
        return invoke(store.recover, experiment_id)

    @router.post("/{experiment_id}/versions/{number}/select")
    def select(experiment_id: str, number: int):
        return invoke(store.select, experiment_id, number)

    return router
