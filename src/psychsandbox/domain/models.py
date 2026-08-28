from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CounselorAction(StrEnum):
    LOOKUP_SKILLS = "lookup_skills"
    RESPOND_WITHOUT_SKILL = "respond_without_skill"
    END_SESSION = "end_session"


class SkillStatus(StrEnum):
    CANDIDATE = "candidate"
    REPLAYED = "replayed"
    EXPERT_REVIEWED = "expert_reviewed"
    APPROVED = "approved"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class ClientReactionType(StrEnum):
    UNDERSTOOD = "understood"
    HOPEFUL = "hopeful"
    GAINED_CLARITY = "gained_clarity"
    CHALLENGED = "challenged"
    SCARED = "scared"
    MISUNDERSTOOD = "misunderstood"
    NO_REACTION = "no_reaction"


class ReactionIntensity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ClientBehaviorType(StrEnum):
    SIMPLE_RESPONSE = "simple_response"
    REQUEST = "request"
    RECOUNTING = "recounting"
    COGNITIVE_EXPLORATION = "cognitive_exploration"
    AFFECTIVE_EXPLORATION = "affective_exploration"
    INSIGHT = "insight"
    DISCUSSING_PLANS = "discussing_plans"
    RESISTANCE = "resistance"


class ResistancePatternType(StrEnum):
    MINIMAL_TALK = "minimal_talk"
    IRRELEVANT_TALK = "irrelevant_talk"
    SUPERFICIAL = "superficial"
    INTELLECTUALIZING = "intellectualizing"
    HOSTILITY = "hostility"
    DEFENSIVENESS = "defensiveness"
    COMPLIANCE_WITHOUT_ENGAGEMENT = "compliance_without_engagement"


class TrustChange(StrEnum):
    SIGNIFICANT_DECREASE = "significant_decrease"
    SLIGHT_DECREASE = "slight_decrease"
    UNCHANGED = "unchanged"
    SLIGHT_INCREASE = "slight_increase"
    SIGNIFICANT_INCREASE = "significant_increase"


class RuptureState(StrEnum):
    NONE = "none"
    EMERGING = "emerging"
    ACTIVE = "active"
    REPAIRING = "repairing"


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


class ClientRelationalProfile(StrictModel):
    """Theory-grounded simulation parameters, never clinical diagnoses."""

    attachment_pattern: Literal[
        "secure", "anxious", "avoidant", "disorganized", "unspecified"
    ] = "unspecified"
    core_belief_theme: str = ""
    expected_counselor_response: str = ""
    self_response_pattern: str = ""
    therapy_triggers: list[str] = Field(default_factory=list)
    coping_patterns: list[str] = Field(default_factory=list)
    preferred_resistance_patterns: list[ResistancePatternType] = Field(
        default_factory=list
    )
    emotional_range: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)


class FivePsFormulation(StrictModel):
    """Auditable 5Ps case formulation used by the private client model.

    Empty lists are allowed for legacy records, but newly converted cases should
    populate every section and retain the source fields used for the derivation.
    """

    presenting_problem: str = ""
    predisposing_factors: list[str] = Field(default_factory=list)
    precipitating_factors: list[str] = Field(default_factory=list)
    perpetuating_factors: list[str] = Field(default_factory=list)
    protective_factors: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)

    def covered_sections(self) -> list[str]:
        sections = {
            "presenting": bool(self.presenting_problem.strip()),
            "predisposing": bool(self.predisposing_factors),
            "precipitating": bool(self.precipitating_factors),
            "perpetuating": bool(self.perpetuating_factors),
            "protective": bool(self.protective_factors),
        }
        return [name for name, covered in sections.items() if covered]


class ClientState(StrictModel):
    """Simulation variables only; these are not clinical scale scores."""

    valence: float = Field(default=0.4, ge=0, le=1)
    arousal: float = Field(default=0.6, ge=0, le=1)
    distress: float = Field(default=0.6, ge=0, le=1)
    trust: float = Field(default=0.25, ge=0, le=1)
    resistance: float = Field(default=0.4, ge=0, le=1)
    hope: float = Field(default=0.35, ge=0, le=1)
    topic_readiness: dict[str, float] = Field(default_factory=dict)
    fatigue: float = Field(default=0.1, ge=0, le=1)
    rupture_state: RuptureState = RuptureState.NONE


class HiddenFact(StrictModel):
    fact_id: str
    content: str
    category: str = "background"
    minimum_trust: float = Field(default=0.35, ge=0, le=1)
    required_topics: list[str] = Field(default_factory=list)
    sensitivity: float = Field(default=0.5, ge=0, le=1)
    activation_tags: list[str] = Field(default_factory=list)
    activation_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    topic_key: str = ""
    disclosure_layers: list[str] = Field(default_factory=list)
    disclosure_level: int = Field(default=1, ge=1)
    minimum_topic_readiness: float = Field(default=0, ge=0, le=1)
    source_field: str = ""
    generates_discomfort: bool | None = None

    @model_validator(mode="after")
    def fill_compatibility_fields(self) -> HiddenFact:
        if not self.activation_tags:
            self.activation_tags = list(self.required_topics)
        if not self.topic_key:
            self.topic_key = self.category
        if not self.disclosure_layers:
            self.disclosure_layers = [self.content]
        self.disclosure_level = min(self.disclosure_level, len(self.disclosure_layers))
        if self.generates_discomfort is None:
            self.generates_discomfort = self.sensitivity >= 0.6
        return self


class BlockedMemorySignal(StrictModel):
    fact_id: str
    category: str
    sensitivity: float = Field(ge=0, le=1)
    activation_evidence: list[str] = Field(default_factory=list)
    reason: str = "insufficient_trust"


class DisclosureDecision(StrictModel):
    retrieved: list[HiddenFact] = Field(default_factory=list)
    blocked: list[BlockedMemorySignal] = Field(default_factory=list)
    activated_fact_ids: list[str] = Field(default_factory=list)
    activation_evidence: dict[str, list[str]] = Field(default_factory=dict)
    ambiguous_fact_ids: list[str] = Field(default_factory=list)


class ClientTurnSignal(StrictModel):
    reaction: ClientReactionType = ClientReactionType.NO_REACTION
    intensity: ReactionIntensity = ReactionIntensity.LOW
    behavior: ClientBehaviorType = ClientBehaviorType.SIMPLE_RESPONSE
    resistance_pattern: ResistancePatternType | None = None
    retrieved_fact_ids: list[str] = Field(default_factory=list)
    blocked_fact_ids: list[str] = Field(default_factory=list)
    trust_change: TrustChange = TrustChange.UNCHANGED
    rationale: str = ""

    @model_validator(mode="after")
    def resistance_requires_pattern(self) -> ClientTurnSignal:
        if (
            self.behavior is ClientBehaviorType.RESISTANCE
            and self.resistance_pattern is None
        ):
            self.resistance_pattern = ResistancePatternType.MINIMAL_TALK
        if self.behavior is not ClientBehaviorType.RESISTANCE:
            self.resistance_pattern = None
        return self


class ClientUtterance(StrictModel):
    utterance: str
    disclosed_fact_ids: list[str] = Field(default_factory=list)


class ClientProfile(StrictModel):
    client_id: str
    static_traits: StaticTraits
    main_problem: str
    topic: str
    core_demands: str
    growth_experiences: list[str] = Field(default_factory=list)
    formulation_5ps: FivePsFormulation = Field(default_factory=FivePsFormulation)
    theory: dict[str, Any] = Field(default_factory=dict)
    personality: BigFive = Field(default_factory=BigFive)
    relational: ClientRelationalProfile = Field(default_factory=ClientRelationalProfile)
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
    disclosure_level: int = Field(default=1, ge=1)


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
    selection_hint: str = ""


class AtomicSkill(StrictModel):
    skill_id: str
    name: str
    description: str
    therapy: str
    stages: list[SessionStage]
    meta_skill_id: str
    paths: dict[str, str] = Field(default_factory=dict)
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
    strategy: str = ""
    completion_threshold: float = Field(default=0.7, ge=0, le=1)


class ExtractedClientInfo(StrictModel):
    """Counselor-visible client information extracted from one session (E.7).

    Mirrors the structure of ``ClientProfile`` but contains only what was
    actually revealed in the current dialogue. Empty values mean "not
    mentioned"; unknown facts must never be invented.
    """

    static_traits: StaticTraits = Field(default_factory=StaticTraits)
    main_problem: str = ""
    topic: str = ""
    core_demands: str = ""
    growth_experiences: list[str] = Field(default_factory=list)
    theory: dict[str, Any] = Field(default_factory=dict)
    source_session: int = Field(default=1, ge=1)


class MergedClientProfile(StrictModel):
    """Counselor's longitudinal, deduplicated memory of a client (E.8).

    This is the merge of previously-known plus newly-extracted information,
    controlled by ground truth so that hallucinated or contradicting entries
    are dropped. It never contains facts the counselor has not observed.
    """

    client_id: str
    static_traits: StaticTraits = Field(default_factory=StaticTraits)
    main_problem: str = ""
    topic: str = ""
    core_demands: str = ""
    growth_experiences: list[str] = Field(default_factory=list)
    theory: dict[str, Any] = Field(default_factory=dict)
    updated_session: int = Field(default=1, ge=1)


class GoalAssessment(StrictModel):
    objective_recap: str = ""
    completion_status: str = ""
    evidence_and_analysis: str = ""


class ClientStateAnalysis(StrictModel):
    affective_state: str = ""
    behavioral_patterns: str = ""
    therapeutic_alliance: str = ""
    unresolved_points_or_tensions: str = ""
    cognitive_patterns: str = ""
    subconscious_manifestation: str = ""
    personal_agency: str = ""
    existentialism_topic: str = ""
    target_behavior: str = ""


class ClinicalSummary(StrictModel):
    """Structured clinical summary bridging consecutive sessions (E.9).

    This is the counselor's long-term memory written by an external clinical
    supervisor.  Every field must be grounded in the current session dialogue;
    forward-looking diagnostic conclusions are forbidden.
    """

    session_index: int = Field(ge=1)
    session_summary_abstract: str = ""
    goal_assessment: GoalAssessment = Field(default_factory=GoalAssessment)
    client_state_analysis: ClientStateAnalysis = Field(default_factory=ClientStateAnalysis)
    homework: list[str] = Field(default_factory=list)


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
    relationship_events: list[str] = Field(default_factory=list)
    between_session_context: list[str] = Field(default_factory=list)
    last_client_closing: str = ""
    evolving_profile: MergedClientProfile | None = None


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


class SkillSelectionEvidence(StrictModel):
    skill_id: str
    evidence_quote: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=1, max_length=160)

    @field_validator("evidence_quote", "reason", mode="before")
    @classmethod
    def strip_evidence(cls, value):
        return value.strip() if isinstance(value, str) else value


class CounselorDecision(StrictModel):
    assessment: str
    state_observation: str
    selected_meta_skill_ids: list[str] = Field(default_factory=list)
    selected_atomic_skill_ids: list[str] = Field(default_factory=list)
    skill_evidence: list[SkillSelectionEvidence] = Field(default_factory=list)
    strategy: str
    goal_progress: float = Field(default=0, ge=0, le=1)
    risk_level: RiskLevel = RiskLevel.LOW
    end_session: bool = False


class CounselorPlanning(StrictModel):
    """Auditable planning summary; never a dump of private model reasoning."""

    reasoning_summary: str
    current_goal: str
    plan_steps: list[str] = Field(min_length=1, max_length=6)
    action: CounselorAction
    selected_meta_skill_ids: list[str] = Field(default_factory=list, max_length=3)
    action_input: str = ""
    selection_evidence: list[SkillSelectionEvidence] = Field(default_factory=list, max_length=3)


class CounselorObservation(StrictModel):
    action: CounselorAction
    status: Literal["skills_found", "no_skills_requested", "invalid_selection"]
    selected_meta_skill_ids: list[str] = Field(default_factory=list)
    atomic_skills: list[AtomicSkill] = Field(default_factory=list)
    note: str = ""
    candidate_count: int = 0
    vector_filtered: bool = False
    embedding_model: str = ""
    similarity_scores: dict[str, float] = Field(default_factory=dict)


class SkillQueryAttempt(StrictModel):
    attempt: int = Field(ge=1, le=2)
    planning: CounselorPlanning
    candidate_skill_ids: list[str] = Field(default_factory=list)
    returned_skill_ids: list[str] = Field(default_factory=list)
    selected_atomic_skill_ids: list[str] = Field(default_factory=list)
    assessment: str
    rejection_reason: str = ""
    selection_warnings: list[str] = Field(default_factory=list)
    vector_filtered: bool = False
    embedding_model: str = ""
    similarity_scores: dict[str, float] = Field(default_factory=dict)


class CounselorTurn(StrictModel):
    decision: CounselorDecision
    response: str
    planning: CounselorPlanning | None = None
    observation: CounselorObservation | None = None
    skill_queries: list[SkillQueryAttempt] = Field(default_factory=list, max_length=2)


class CounselorActorOutput(StrictModel):
    """Minimal actor output; planning/observation are supplied out-of-band.

    The actor produces the auditable decision, candidate assessment and verbatim
    client-facing response.  ``planning`` and ``observation`` are already known
    from the planner and the skill-catalog ReAct observation, so asking the
    model to echo them (including the full atomic-skill payloads) needlessly
    bloats the JSON and can exceed ``max_tokens`` mid-string.
    """

    decision: CounselorDecision
    response: str
    query_assessment: Literal["suitable", "unsuitable", "needs_clarification", "not_needed"] = "not_needed"
    query_rejection_reason: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> CounselorActorOutput:
        if self.query_assessment == "unsuitable" and not self.query_rejection_reason.strip():
            raise ValueError("unsuitable query results require a concrete rejection reason")
        return self


class CounselorSessionReview(StrictModel):
    """Counselor self-review used to decide whether and how to replan."""

    goals_achieved: bool
    goal_progress: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=6)
    unmet_objectives: list[str] = Field(default_factory=list)
    improvement_areas: list[str] = Field(default_factory=list)
    replanning_required: bool
    revised_strategy: str = ""
    next_objectives: list[str] = Field(default_factory=list, max_length=8)
    target_meta_skill_ids: list[str] = Field(default_factory=list, max_length=3)


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


class LongitudinalReport(StrictModel):
    """Session-to-session progress signal for planning, not a clinical outcome."""

    session_index: int = Field(ge=1)
    state_deltas: dict[str, float] = Field(default_factory=dict)
    supervisor_score_delta: float | None = None
    trend: Literal["baseline", "improving", "stable", "worsening", "mixed"]
    stage_action: Literal["continue", "advance", "regress", "hold", "close"]
    evidence: list[str] = Field(default_factory=list)


class ClientSimulationReport(StrictModel):
    session_index: int
    metrics: list[EvaluationMetric]
    overall_score: float = Field(ge=0, le=10)
    red_flags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class ScaleItem(StrictModel):
    """Single item rating returned by a PsychEval instrument prompt."""

    item: str
    score: float
    evidence_pos: list[str] = Field(default_factory=list)
    evidence_neg: list[str] = Field(default_factory=list)
    thought: str = ""


class ScaleItems(StrictModel):
    """Wrapper for the official `{"items": [...]}` output format."""

    items: list[ScaleItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_items(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"items": data}
        return data


class ScaleScore(StrictModel):
    """Aggregated 0-10 score for one PsychEval instrument.

    ``item_scores`` preserves raw per-item ratings (usually 1-5) keyed by item
    number string, while ``score`` carries the normalized, direction-adjusted
    0-10 summary used for reporting.
    """

    name: str
    level: Literal["counselor", "client"]
    category: Literal["therapy_shared", "therapy_specific"]
    direction: Literal["higher_better", "lower_better"]
    score: float = Field(ge=0, le=10)
    item_scores: dict[str, float] = Field(default_factory=dict)


class HolisticEvaluationReport(StrictModel):
    """Post-trajectory external supervision result aligned with PsychEval.

    This is produced once after all sessions finish, separating evaluation
    (this report) from planning (MemoryConsolidator / PlanBuilder).
    """

    run_id: str
    case_id: str
    therapy: str
    counselor_shared: list[ScaleScore] = Field(default_factory=list)
    counselor_specific: list[ScaleScore] = Field(default_factory=list)
    client_shared: list[ScaleScore] = Field(default_factory=list)
    client_specific: list[ScaleScore] = Field(default_factory=list)
    counselor_overall: float = Field(ge=0, le=10)
    client_overall: float = Field(ge=0, le=10)
    created_at: str = Field(default_factory=utc_now)


class RFTConfig(StrictModel):
    enabled: bool = False
    candidates: int = Field(default=3, ge=2, le=32)
    concurrency: int = Field(default=2, ge=1, le=32)
    judge_concurrency: int = Field(default=2, ge=1, le=16)
    candidate_timeout_sec: float = Field(default=1800, gt=0, allow_inf_nan=False)
    judge_timeout_sec: float = Field(default=180, gt=0, allow_inf_nan=False)
    min_eligible: int = Field(default=2, ge=2, le=32)
    counselor_temperature: float = Field(default=0.9, ge=0, le=2)
    judge_temperature: float = Field(default=0.0, ge=0, le=2)
    counselor_weight: float = Field(default=0.7, gt=0, lt=1)
    min_safety_score: float = Field(default=7, ge=7, le=10)
    min_fidelity_score: float = Field(default=6, ge=0, le=10)

    @model_validator(mode="after")
    def check_candidate_budget(self) -> RFTConfig:
        if self.min_eligible > self.candidates:
            raise ValueError("min_eligible must not exceed candidates")
        return self


class RolloutEvidence(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_index: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=240)


class RolloutDimension(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    score: float = Field(ge=0, le=10, allow_inf_nan=False)
    evidence: list[RolloutEvidence] = Field(min_length=1, max_length=3)
    reason: str = Field(min_length=1, max_length=240)


class RolloutAssessment(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    counselor_alliance: RolloutDimension
    counselor_strategy: RolloutDimension
    counselor_goal_alignment: RolloutDimension
    counselor_safety: RolloutDimension
    client_engagement: RolloutDimension
    client_understanding: RolloutDimension
    client_agency: RolloutDimension
    simulation_fidelity: RolloutDimension
    safety_passed: bool
    safety_reason: str = Field(min_length=1, max_length=300)


class RolloutReward(StrictModel):
    total: float = Field(ge=0, le=10, allow_inf_nan=False)
    counselor_score: float = Field(ge=0, le=10)
    client_snapshot: dict[str, float]
    client_delta: float | None = None
    client_gain_score: float | None = None
    baseline_session_index: int | None = None
    formula_version: str = "session-rft-v1"


class RolloutCandidateSummary(StrictModel):
    index: int = Field(ge=1)
    status: Literal[
        "pending", "generating", "generated", "duplicate", "generation_failed",
        "scoring_failed", "rejected", "eligible", "selected", "cancelled", "safety_hold",
    ] = "pending"
    reason: str = ""
    dialogue_hash: str = ""
    duplicate_of: int | None = None
    assessment: RolloutAssessment | None = None
    reward: RolloutReward | None = None
    artifact_path: str
    turns: int = 0


class RolloutSelection(StrictModel):
    batch_id: str
    session_index: int = Field(ge=1)
    status: Literal["running", "selected", "failed", "safety_hold", "cancelled"] = "running"
    config: RFTConfig
    baseline_client_snapshot: dict[str, float] | None = None
    baseline_session_index: int | None = None
    candidates: list[RolloutCandidateSummary] = Field(default_factory=list)
    winner_index: int | None = None
    reason: str = ""


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
    clinical_summary: ClinicalSummary | None = None
    counselor_review: CounselorSessionReview | None = None
    newly_unlocked_fact_ids: list[str] = Field(default_factory=list)
    interventions_used: list[str] = Field(default_factory=list)
    risk_events: list[RiskAssessment] = Field(default_factory=list)
    next_session_plan: SessionPlan | None = None
    supervisor_report: SupervisorReport | None = None
    llm_supervisor_report: SupervisorReport | None = None
    client_simulation_report: ClientSimulationReport | None = None
    longitudinal_report: LongitudinalReport | None = None
    evaluation_errors: list[str] = Field(default_factory=list)
    rollout_selection: RolloutSelection | None = None
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
    holistic_report: HolisticEvaluationReport | None = None
    created_at: str = Field(default_factory=utc_now)


class MemoryRecord(StrictModel):
    run_id: str
    session_index: int
    memory: SessionMemory


class SkillSelectionConfig(StrictModel):
    vector_threshold: int = Field(default=24, ge=1, le=2000)
    vector_top_k: int = Field(default=12, ge=1, le=2000)

    @model_validator(mode="after")
    def check_vector_budget(self) -> SkillSelectionConfig:
        if self.vector_top_k > self.vector_threshold:
            raise ValueError("vector_top_k must not exceed vector_threshold")
        return self


class SandboxConfig(StrictModel):
    project_root: Path
    seed: int = 42
    session_count: int = Field(default=3, ge=1, le=100)
    max_turns_per_session: int = Field(default=8, ge=1, le=50)
    database_path: Path | None = None
    trace_dir: Path | None = None
    processed_dataset_dir: Path | None = None
    temperature_client: float = Field(default=0.8, ge=0, le=2)
    temperature_client_planner: float = Field(default=0.1, ge=0, le=2)
    temperature_counselor: float = Field(default=0.4, ge=0, le=2)
    temperature_supervisor: float = Field(default=0.1, ge=0, le=2)
    patientact_enabled: bool = True
    client_pullback_after: int = Field(default=2, ge=1, le=10)
    disclosure_leak_retry_limit: int = Field(default=1, ge=0, le=3)
    skill_selection: SkillSelectionConfig = Field(default_factory=SkillSelectionConfig)
    rft: RFTConfig = Field(default_factory=RFTConfig)

    def model_post_init(self, __context: Any) -> None:
        from ..artifacts import latest_data_dir, runtime_root

        if self.database_path is None:
            self.database_path = runtime_root(self.project_root) / "psychsandbox.sqlite3"
        if self.trace_dir is None:
            self.trace_dir = runtime_root(self.project_root)
        if self.processed_dataset_dir is None:
            self.processed_dataset_dir = latest_data_dir(self.project_root, "processed")
