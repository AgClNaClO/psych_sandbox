from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStage(StrEnum):
    CONCEPTUALIZATION = "case_conceptualization"
    INTERVENTION = "core_intervention"
    CONSOLIDATION = "consolidation"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IMMINENT = "imminent"


class SkillStatus(StrEnum):
    CANDIDATE = "candidate"
    REPLAYED = "replayed"
    EXPERT_REVIEWED = "expert_reviewed"
    APPROVED = "approved"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class StaticTraits(StrictModel):
    name: str = ""
    age: str | int = ""
    gender: str = ""
    occupation: str = ""
    educational_background: str = ""
    marital_status: str = ""
    family_status: str = ""
    social_status: str = ""
    medical_history: str = ""
    language_features: str = ""


class BigFive(StrictModel):
    openness: float = Field(default=0.5, ge=0, le=1)
    conscientiousness: float = Field(default=0.5, ge=0, le=1)
    extraversion: float = Field(default=0.5, ge=0, le=1)
    agreeableness: float = Field(default=0.5, ge=0, le=1)
    neuroticism: float = Field(default=0.5, ge=0, le=1)


class ClientState(StrictModel):
    """Simulation variables only; these are not clinical scale scores."""

    valence: float = Field(default=0.4, ge=0, le=1)
    arousal: float = Field(default=0.6, ge=0, le=1)
    distress: float = Field(default=0.6, ge=0, le=1)
    trust: float = Field(default=0.25, ge=0, le=1)
    resistance: float = Field(default=0.4, ge=0, le=1)
    hope: float = Field(default=0.35, ge=0, le=1)


class HiddenFact(StrictModel):
    fact_id: str
    content: str
    category: str = "background"
    minimum_trust: float = Field(default=0.35, ge=0, le=1)
    required_topics: list[str] = Field(default_factory=list)
    sensitivity: float = Field(default=0.5, ge=0, le=1)


class ClientProfile(StrictModel):
    client_id: str
    static_traits: StaticTraits
    main_problem: str
    topic: str
    core_demands: str
    growth_experiences: list[str] = Field(default_factory=list)
    theory: dict[str, Any] = Field(default_factory=dict)
    personality: BigFive = Field(default_factory=BigFive)
    initial_state: ClientState = Field(default_factory=ClientState)
    language_style: str = ""
    opening: str = ""
    hidden_facts: list[HiddenFact] = Field(default_factory=list)

    @field_validator("hidden_facts")
    @classmethod
    def unique_hidden_ids(cls, facts: list[HiddenFact]) -> list[HiddenFact]:
        ids = [item.fact_id for item in facts]
        if len(ids) != len(set(ids)):
            raise ValueError("hidden fact IDs must be unique")
        return facts


class UnlockedFact(StrictModel):
    fact_id: str
    content: str
    evidence_session: int = Field(ge=1)
    evidence_turn: int = Field(ge=0)
    disclosure_method: Literal["explicit", "confirmed_inference"] = "explicit"


class UnlockedClientProfile(StrictModel):
    client_id: str
    public_background: dict[str, Any] = Field(default_factory=dict)
    facts: list[UnlockedFact] = Field(default_factory=list)
    confirmed_goals: list[str] = Field(default_factory=list)
    expressed_problems: list[str] = Field(default_factory=list)
    theory: dict[str, Any] = Field(default_factory=dict)


class MetaSkill(StrictModel):
    meta_skill_id: str
    name: str
    description: str
    therapy: str
    stages: list[SessionStage]
    source: str = "local"


class AtomicSkill(StrictModel):
    skill_id: str
    name: str
    description: str
    therapy: str
    stages: list[SessionStage]
    meta_skill_id: str
    when_to_use: str = ""
    triggers: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    intervention_type: str = "supportive_exploration"
    source: str = "local"
    version: int = Field(default=1, ge=1)
    status: SkillStatus = SkillStatus.APPROVED


class SkillVersion(StrictModel):
    skill_id: str
    version: str
    status: SkillStatus
    content: dict[str, Any]
    source_trajectory_ids: list[str] = Field(default_factory=list)
    parent_version: str | None = None
    review_note: str = ""
    created_at: str = Field(default_factory=utc_now)


class SkillCandidate(StrictModel):
    meta_skills: list[MetaSkill] = Field(default_factory=list)
    atomic_skills: list[AtomicSkill] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)


class SessionPlan(StrictModel):
    session_index: int = Field(ge=1)
    therapy: str = "cbt"
    stage: SessionStage
    objectives: list[str]
    persona_links: list[str] = Field(default_factory=list)
    case_materials: list[str] = Field(default_factory=list)
    target_meta_skill_ids: list[str] = Field(default_factory=list)
    target_atomic_skill_ids: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    completion_threshold: float = Field(default=0.7, ge=0, le=1)


class SessionMemory(StrictModel):
    case_id: str
    completed_sessions: int = Field(default=0, ge=0)
    summaries: list[str] = Field(default_factory=list)
    unlocked_profile: UnlockedClientProfile
    confirmed_goals: list[str] = Field(default_factory=list)
    unresolved_topics: list[str] = Field(default_factory=list)
    homework: list[str] = Field(default_factory=list)
    interventions_used: list[str] = Field(default_factory=list)
    risk_history: list[str] = Field(default_factory=list)
    supervisor_feedback: list[str] = Field(default_factory=list)


class Message(StrictModel):
    session_index: int = Field(ge=1)
    turn_index: int = Field(ge=0)
    role: Literal["client", "counselor", "system"]
    content: str
    created_at: str = Field(default_factory=utc_now)


class RiskAssessment(StrictModel):
    level: RiskLevel
    categories: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    ordinary_intervention_allowed: bool = True
    requires_immediate_stop: bool = False


class CounselorDecision(StrictModel):
    assessment: str
    state_observation: str
    selected_meta_skill_ids: list[str] = Field(default_factory=list)
    selected_atomic_skill_ids: list[str] = Field(default_factory=list)
    strategy: str
    goal_progress: float = Field(default=0, ge=0, le=1)
    risk_level: RiskLevel = RiskLevel.LOW
    end_session: bool = False


class CounselorTurn(StrictModel):
    decision: CounselorDecision
    response: str


class ClientGeneration(StrictModel):
    utterance: str
    expressed_emotions: list[str] = Field(default_factory=list)
    disclosed_fact_ids: list[str] = Field(default_factory=list)
    cooperation: float = Field(default=0.5, ge=0, le=1)
    resistance: float = Field(default=0.5, ge=0, le=1)
    goal_progress_signal: float = Field(default=0, ge=-1, le=1)


class EvaluationMetric(StrictModel):
    name: str
    score: float = Field(ge=0, le=10)
    evidence: list[str] = Field(default_factory=list)
    reason: str
    violations: list[str] = Field(default_factory=list)
    evaluator: Literal["rule", "llm", "human"] = "rule"


class SupervisorReport(StrictModel):
    session_index: int
    metrics: list[EvaluationMetric]
    overall_score: float = Field(ge=0, le=10)
    feedback: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class SessionRecord(StrictModel):
    session_id: str
    session_index: int
    plan: SessionPlan
    initial_state: ClientState
    final_state: ClientState
    messages: list[Message]
    decisions: list[CounselorDecision] = Field(default_factory=list)
    turn_records: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    newly_unlocked_fact_ids: list[str] = Field(default_factory=list)
    interventions_used: list[str] = Field(default_factory=list)
    risk_events: list[RiskAssessment] = Field(default_factory=list)
    next_session_plan: SessionPlan | None = None
    supervisor_report: SupervisorReport | None = None
    llm_supervisor_report: SupervisorReport | None = None
    evaluation_errors: list[str] = Field(default_factory=list)
    end_reason: str


class CounselingCase(StrictModel):
    case_id: str
    therapy: str
    profile: ClientProfile
    global_plan: list[SessionPlan]
    reference_sessions: list[dict[str, Any]] = Field(default_factory=list)
    source: str
    source_revision: str = ""


class Trajectory(StrictModel):
    trajectory_id: str
    run_id: str
    case_id: str
    session_index: int
    model_config_snapshot: dict[str, Any]
    memory_before: SessionMemory
    plan: SessionPlan
    session: SessionRecord
    reward: float = Field(ge=0, le=10)
    safety_passed: bool
    created_at: str = Field(default_factory=utc_now)


class RunResult(StrictModel):
    run_id: str
    case_id: str
    therapy: str
    seed: int
    sessions: list[SessionRecord]
    final_memory: SessionMemory
    created_at: str = Field(default_factory=utc_now)


class MemoryRecord(StrictModel):
    run_id: str
    session_index: int
    memory: SessionMemory


class SandboxConfig(StrictModel):
    project_root: Path
    provider: Literal["mock", "api", "local"] = "mock"
    seed: int = 42
    max_turns_per_session: int = Field(default=8, ge=1, le=50)
    database_path: Path | None = None
    trace_dir: Path | None = None
    processed_dataset_dir: Path | None = None
    local_model_name: str = ""
    local_device: str = "auto"
    temperature_client: float = Field(default=0.8, ge=0, le=2)
    temperature_counselor: float = Field(default=0.4, ge=0, le=2)
    temperature_supervisor: float = Field(default=0.1, ge=0, le=2)

    def model_post_init(self, __context: Any) -> None:
        if self.database_path is None:
            self.database_path = self.project_root / "runs" / "psychsandbox.sqlite3"
        if self.trace_dir is None:
            self.trace_dir = self.project_root / "runs"
        if self.processed_dataset_dir is None:
            self.processed_dataset_dir = self.project_root / "data" / "processed" / "psycheval"
