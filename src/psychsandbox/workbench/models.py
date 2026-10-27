"""科研 Web 工作台 Pydantic 数据契约与模型定义"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from ..domain import utc_now
from ..therapies import normalize_therapy_id


class TherapyRequest(BaseModel):
    therapy: str

    @field_validator("therapy")
    @classmethod
    def normalize_therapy(cls, value: str) -> str:
        return normalize_therapy_id(value)


class SimulationJobPayload(BaseModel):
    case_id: str = Field(min_length=1)
    therapy: str | None = None
    session_count: int = Field(default=1, ge=1, le=100, strict=True)
    seed: int | None = None
    resume_run_id: str | None = None


# ==========================================
# 任务与调度 (Jobs)
# ==========================================

JobStatus = Literal["queued", "running", "succeeded", "failed", "stopped", "cancelled"]
JobLane = Literal["long", "short"]
JobKind = Literal["simulation", "validation_replay", "validation_simulation", "course_reply", "course_close", "holistic_rescore"]


class JobCreateRequest(BaseModel):
    kind: JobKind
    lane: JobLane = "long"
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    course_id: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_worker_contract(self):
        if self.kind not in ("simulation", "course_reply", "course_close"):
            raise ValueError("This job kind is not implemented by the workbench worker")
        expected_lane = "long" if self.kind == "simulation" else "short"
        if self.lane != expected_lane:
            raise ValueError(f"{self.kind} requires the {expected_lane} lane")
        if self.kind == "simulation":
            payload = SimulationJobPayload.model_validate(self.payload)
            if payload.therapy is not None:
                normalize_therapy_id(payload.therapy)
        elif not self.payload.get("course_id") or not self.payload.get("operation_id"):
            raise ValueError("Course jobs require course_id and operation_id")
        return self


class JobResponse(BaseModel):
    job_id: str
    kind: str
    lane: str
    status: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    stop_requested: bool = False
    cancel_requested: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None
    run_id: str | None = None
    course_id: str | None = None
    created_at: str
    updated_at: str


# ==========================================
# 事件流 (Events)
# ==========================================

class WorkbenchEvent(BaseModel):
    stream: str
    seq: int
    type: str
    schema_version: int = 1
    payload: dict[str, Any]
    created_at: str = Field(default_factory=utc_now)


# ==========================================
# 人工疗程与聊天 (Courses & Interactive)
# ==========================================

CourseStatus = Literal["active", "closed"]
InputMode = Literal["natural", "roleplay"]
CourseSessionStatus = Literal["open", "closing", "closed", "close_failed"]


class CourseCreateRequest(TherapyRequest):
    title: str
    input_mode: InputMode = "natural"
    roleplay_card: str | None = None
    skill_release_id: str | None = None


class CourseResponse(BaseModel):
    course_id: str
    therapy: str
    title: str
    input_mode: str
    roleplay_card: str | None = None
    status: str
    close_reason: str | None = None
    skill_release_id: str | None = None
    prompt_tree_version: str | None = None
    config_hash: str | None = None
    version: int
    created_at: str
    updated_at: str
    completed_sessions: int = 0
    current_session: int = 1


class CourseMessageResponse(BaseModel):
    message_id: str
    course_id: str
    session_index: int
    role: str
    source: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SendMessageRequest(BaseModel):
    message_id: str
    operation_id: str
    expected_version: int
    content: str = Field(min_length=1)
    source: Literal["participant_natural", "participant_roleplay"] = "participant_natural"


class OperationResponse(BaseModel):
    operation_id: str
    course_id: str
    session_index: int
    kind: str
    status: str
    expected_version: int
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class CloseStepRecord(BaseModel):
    step_name: str
    status: str
    input_summary: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    created_at: str


class CourseSessionDetailResponse(BaseModel):
    course_id: str
    course_version: int = 1
    session_index: int
    status: str
    plan: dict[str, Any]
    memory_before: dict[str, Any]
    memory_after: dict[str, Any] | None = None
    next_plan: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    close_reason: str | None = None
    created_at: str
    closed_at: str | None = None
    messages: list[CourseMessageResponse] = Field(default_factory=list)
    close_steps: list[CloseStepRecord] = Field(default_factory=list)
    active_operation: OperationResponse | None = None
    last_operation: OperationResponse | None = None


# ==========================================
# 技能实验室与演化 (Skills & Evolution)
# ==========================================

class SkillReleaseResponse(BaseModel):
    release_id: str
    therapy: str
    name: str
    description: str
    tree_hash: str
    parent_release_id: str | None = None
    overlay_skills: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: str
    is_active: bool = False


class SkillProposalCreateRequest(TherapyRequest):
    base_release_id: str | None = None
    title: str
    target_skill_id: str | None = None
    parent_meta_id: str
    stage: str
    content: dict[str, Any]
    justification: str
    author: str


class SkillProposalResponse(BaseModel):
    proposal_id: str
    therapy: str
    base_release_id: str
    title: str
    target_skill_id: str | None = None
    parent_meta_id: str
    stage: str
    content: dict[str, Any]
    status: str
    justification: str
    author: str
    validation_summary: dict[str, Any]
    created_at: str
    updated_at: str


class ExpertReviewCreateRequest(BaseModel):
    reviewer_id: str
    reviewer_name: str
    verdict: Literal["approve", "reject", "revise"]
    rationale: str
    checklist: dict[str, bool] = Field(default_factory=dict)


class ExpertReviewResponse(BaseModel):
    review_id: str
    proposal_id: str
    reviewer_id: str
    reviewer_name: str
    verdict: str
    rationale: str
    checklist: dict[str, bool]
    created_at: str


class ReplayValidationResponse(BaseModel):
    validation_id: str
    proposal_id: str
    replay_type: str
    status: str
    candidate_outputs: dict[str, Any]
    baseline_outputs: dict[str, Any]
    diff_summary: str
    error: str | None = None
    created_at: str


# ==========================================
# 训练数据导出与评测比较 (Export & Analytics)
# ==========================================

class ExportFileRequest(BaseModel):
    output_filename: str = Field(default="export.jsonl", min_length=1, max_length=200)

    @field_validator("output_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        # Reject POSIX/Windows paths, ADS and Windows device names on every host.
        import re
        if not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]+\.jsonl', value) or value != value.strip():
            raise ValueError("output_filename must be a plain .jsonl filename")
        if value.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError("Reserved output filename")
        return value


class ExportSFTRequest(ExportFileRequest):
    run_ids: list[str] | None = None
    include_interactive: bool = False
    output_filename: str = "sft_export.jsonl"
    protocol_version: str = "v1"


class ExportDPORequest(ExportFileRequest):
    run_ids: list[str] | None = None
    output_filename: str = "dpo_export.jsonl"
    protocol_version: str = "v1"


class ExportAuditResponse(BaseModel):
    export_id: str
    export_type: str
    criteria: dict[str, Any]
    output_path: str
    row_count: int
    split_info: dict[str, Any]
    sha256: str
    created_by: str
    created_at: str


class MetricStats(BaseModel):
    metric_name: str
    count: int
    mean: float | None = None
    std: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    uncertainty_note: str | None = None


class ExperimentComparisonRow(BaseModel):
    run_id: str
    case_id: str
    therapy: str
    status: str
    sessions_completed: int
    model_supervisor_score: float | None = None
    human_feedback_score: float | None = None
    auto_sim_score: float | None = None
    cost_estimate_cny: float | None = None
    latency_sec_avg: float | None = None
    failure_rate: float = 0.0
    created_at: str


# ==========================================
# 只读投影视图 (Projections)
# ==========================================

class CaseSummary(BaseModel):
    case_id: str
    therapy: str
    title: str
    client_name: str
    client_gender: str
    client_age: int | None = None
    client_occupation: str | None = None
    summary: str
    available_sessions: int


class RunSummaryProjection(BaseModel):
    run_id: str
    case_id: str
    therapy: str
    provider: str
    seed: int
    status: str
    completed_sessions: int
    created_at: str
    completed_at: str | None = None
    has_html_report: bool = False
    holistic_score: float | None = None


class RunDetailProjection(BaseModel):
    run_id: str
    case_id: str
    therapy: str
    provider: str
    seed: int
    status: str
    created_at: str
    completed_at: str | None = None
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    holistic_report: dict[str, Any] | None = None
    rft_batches: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
