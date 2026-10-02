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


class DerivationType(StrEnum):
    DIRECT = "direct"
    STRUCTURED_MAPPING = "structured_mapping"
    MODEL_HYPOTHESIS = "model_hypothesis"


class TrustTier(StrEnum):
    ROUTINE = "routine"
    BASIC = "basic"
    MODERATE = "moderate"
    SENSITIVE = "sensitive"
    DEEP = "deep"

    @property
    def threshold(self) -> float:
        return {
            TrustTier.ROUTINE: 0.25,
            TrustTier.BASIC: 0.30,
            TrustTier.MODERATE: 0.40,
            TrustTier.SENSITIVE: 0.55,
            TrustTier.DEEP: 0.70,
        }[self]


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


class ClientSimulationConfig(StrictModel):
    """Private synthetic controls, never case evidence or counselor memory."""

    schema_version: Literal["1"] = "1"
    traits: BigFive = Field(default_factory=BigFive)
    origin: Literal["neutral_default", "synthetic_configuration"] = "neutral_default"
    source_ids: list[str] = Field(default_factory=list)
    uncertainty: float = Field(default=1.0, ge=0, le=1)

    def modifiers(self) -> dict[str, float]:
        weight = 1.0 - self.uncertainty
        centered = {
            key: (value - 0.5) * weight
            for key, value in self.traits.model_dump().items()
        }
        return {
            "expression_length": round(0.2 * centered["extraversion"], 4),
            "interaction_initiation": round(0.2 * centered["extraversion"], 4),
            "abstract_reflection": round(0.2 * centered["openness"], 4),
            "conflict_softening": round(0.2 * centered["agreeableness"], 4),
            "threat_sensitivity": round(0.1 * centered["neuroticism"], 4),
            "recovery_rate": round(-0.1 * centered["neuroticism"], 4),
        }


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


class EvidenceNode(StrictModel):
    evidence_id: str
    source_path: str
    source_text: str
    source_start: int = Field(default=0, ge=0)
    source_end: int = Field(default=0, ge=0)
    kind: str
    therapy: str
    provenance: str = "psycheval"
    five_ps_roles: list[str] = Field(default_factory=list)
    needs_review: bool = False

    @model_validator(mode="after")
    def valid_source_offsets(self) -> EvidenceNode:
        if self.source_end < self.source_start:
            raise ValueError("evidence source_end must not precede source_start")
        return self


class FormulationItem(StrictModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)
    derivation: DerivationType = DerivationType.DIRECT


class CCRT(StrictModel):
    domain: str = "therapist"
    wish: str = ""
    expected_response: str = ""
    self_response: str = ""
    source_ids: list[str] = Field(default_factory=list)
    derivation: DerivationType = DerivationType.STRUCTURED_MAPPING


class EvidenceBackedPattern(StrictModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)
    derivation: DerivationType = DerivationType.STRUCTURED_MAPPING


class ClientExpressionStyle(StrictModel):
    """Source-backed client-only speaking guidance without case-event content."""

    verbal_style: list[EvidenceBackedPattern] = Field(default_factory=list)
    interaction_style: list[EvidenceBackedPattern] = Field(default_factory=list)
    affective_expression: list[EvidenceBackedPattern] = Field(default_factory=list)


class FivePsCoverageStatus(StrEnum):
    SUPPORTED = "supported"
    SOURCE_ABSENT = "source_absent"
    UNCERTAIN = "uncertain"


class FivePsCoverage(StrictModel):
    status: FivePsCoverageStatus = FivePsCoverageStatus.SOURCE_ABSENT
    source_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class InteractionPrior(StrictModel):
    """Evidence-backed simulation prior; never a diagnosis or discloseable fact."""

    therapist_pattern: CCRT | None = None
    coping_patterns: list[EvidenceBackedPattern] = Field(default_factory=list)
    emotional_access: list[EvidenceBackedPattern] = Field(default_factory=list)
    expected_misattunement: list[EvidenceBackedPattern] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class FivePsFormulation(StrictModel):
    """Auditable 5Ps case formulation used by the private client model.

    This is a cross-therapy evidence projection, not the canonical therapy
    formulation.
    """

    presenting_problem: list[FormulationItem] = Field(default_factory=list)
    predisposing_factors: list[FormulationItem] = Field(default_factory=list)
    precipitating_factors: list[FormulationItem] = Field(default_factory=list)
    perpetuating_factors: list[FormulationItem] = Field(default_factory=list)
    protective_factors: list[FormulationItem] = Field(default_factory=list)
    coverage: dict[str, FivePsCoverage] = Field(default_factory=dict)

    def covered_sections(self) -> list[str]:
        sections = {
            "presenting": bool(self.presenting_problem),
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
    fatigue: float = Field(default=0.1, ge=0, le=1)
    rupture_state: RuptureState = RuptureState.NONE

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_topic_readiness(cls, value: Any) -> Any:
        if isinstance(value, dict) and "topic_readiness" in value:
            value = dict(value)
            value.pop("topic_readiness", None)
        return value


class DisclosureItem(StrictModel):
    item_id: str
    evidence_ids: list[str]
    content: str
    category: str = "background"
    activation_tags: list[str] = Field(default_factory=list)
    activation_examples: list[str] = Field(default_factory=list)
    trust_tier: TrustTier = TrustTier.MODERATE
    generates_discomfort: bool = False
    emotional_cost: float = Field(default=0.0, ge=0, le=1)
    session_scope: list[int] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    @property
    def fact_id(self) -> str:
        """One-version compatibility alias for pre-v3 callers."""
        return self.item_id


class HiddenFact(StrictModel):
    """Legacy v2 input contract. New profiles use DisclosureItem."""
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

    def to_disclosure_item(self) -> DisclosureItem:
        if self.minimum_trust >= 0.70:
            tier = TrustTier.DEEP
        elif self.minimum_trust >= 0.55:
            tier = TrustTier.SENSITIVE
        elif self.minimum_trust >= 0.40:
            tier = TrustTier.MODERATE
        else:
            tier = TrustTier.BASIC
        return DisclosureItem(
            item_id=self.fact_id,
            evidence_ids=[self.fact_id],
            content=self.content,
            category=self.category,
            activation_tags=self.activation_tags,
            activation_examples=self.activation_examples,
            trust_tier=tier,
            generates_discomfort=bool(self.generates_discomfort),
        )


class BlockedMemorySignal(StrictModel):
    item_id: str
    category: str
    trust_tier: TrustTier
    activation_evidence: list[str] = Field(default_factory=list)
    reason: str = "insufficient_trust"

    @property
    def fact_id(self) -> str:
        """One-version compatibility alias; serialized output uses item_id."""
        return self.item_id

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_signal(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "fact_id" in value and "item_id" not in value:
            value["item_id"] = value.pop("fact_id")
        sensitivity = value.pop("sensitivity", None)
        if "trust_tier" not in value:
            score = float(sensitivity or 0.5)
            value["trust_tier"] = (
                "deep" if score >= 0.8 else
                "sensitive" if score >= 0.6 else
                "moderate" if score >= 0.4 else "basic"
            )
        return value


class DisclosureDecision(StrictModel):
    retrieved: list[DisclosureItem] = Field(default_factory=list)
    blocked: list[BlockedMemorySignal] = Field(default_factory=list)
    activated_fact_ids: list[str] = Field(default_factory=list)
    activation_evidence: dict[str, list[str]] = Field(default_factory=dict)
    ambiguous_fact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_retrieved(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        value["retrieved"] = [
            item.to_disclosure_item() if isinstance(item, HiddenFact) else item
            for item in value.get("retrieved", [])
        ]
        return value


class ClientTurnSignal(StrictModel):
    reaction: ClientReactionType = ClientReactionType.NO_REACTION
    intensity: ReactionIntensity = ReactionIntensity.LOW
    behavior: ClientBehaviorType = ClientBehaviorType.SIMPLE_RESPONSE
    resistance_pattern: ResistancePatternType | None = None
    retrieved_fact_ids: list[str] = Field(default_factory=list)
    blocked_fact_ids: list[str] = Field(default_factory=list)
    trust_change: TrustChange = TrustChange.UNCHANGED
    rationale: str = ""
    policy: str = ""
    planning_model_calls: int = Field(default=0, ge=0)

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
    schema_version: Literal["4"] = "4"
    client_id: str
    static_traits: StaticTraits
    main_problem: str
    topic: str
    core_demands: str
    growth_experiences: list[str] = Field(default_factory=list)
    formulation_5ps: FivePsFormulation = Field(default_factory=FivePsFormulation)
    theory: dict[str, Any] = Field(default_factory=dict)
    evidence_nodes: list[EvidenceNode] = Field(default_factory=list)
    disclosure_items: list[DisclosureItem] = Field(default_factory=list)
    interaction_prior: InteractionPrior = Field(default_factory=InteractionPrior)
    expression_style: ClientExpressionStyle = Field(default_factory=ClientExpressionStyle)
    personality: BigFive = Field(default_factory=BigFive, exclude=True)
    simulation_config: ClientSimulationConfig = Field(default_factory=ClientSimulationConfig)
    relational: ClientRelationalProfile = Field(
        default_factory=ClientRelationalProfile, exclude=True
    )
    initial_state: ClientState = Field(default_factory=ClientState)

    @field_validator("evidence_nodes")
    @classmethod
    def unique_evidence_ids(cls, nodes: list[EvidenceNode]) -> list[EvidenceNode]:
        ids = [item.evidence_id for item in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence node IDs must be unique")
        return nodes

    @field_validator("disclosure_items")
    @classmethod
    def unique_disclosure_ids(
        cls, items: list[DisclosureItem]
    ) -> list[DisclosureItem]:
        ids = [item.item_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("disclosure item IDs must be unique")
        return items

    @model_validator(mode="after")
    def validate_evidence_projections(self) -> ClientProfile:
        evidence_ids = {item.evidence_id for item in self.evidence_nodes}
        if any(
            not item.evidence_ids or not set(item.evidence_ids).issubset(evidence_ids)
            for item in self.disclosure_items
        ):
            raise ValueError("disclosure items must reference existing evidence")
        sections = (
            self.formulation_5ps.presenting_problem,
            self.formulation_5ps.predisposing_factors,
            self.formulation_5ps.precipitating_factors,
            self.formulation_5ps.perpetuating_factors,
            self.formulation_5ps.protective_factors,
        )
        for item in (entry for section in sections for entry in section):
            if (
                not item.source_ids
                or not set(item.source_ids).issubset(evidence_ids)
                or item.derivation is DerivationType.MODEL_HYPOTHESIS
            ):
                raise ValueError("5Ps items require legal evidence and no hypotheses")
        for coverage in self.formulation_5ps.coverage.values():
            if not set(coverage.source_ids).issubset(evidence_ids):
                raise ValueError("5Ps coverage must reference existing evidence")
        style_items = (
            self.expression_style.verbal_style
            + self.expression_style.interaction_style
            + self.expression_style.affective_expression
        )
        if any(
            not item.source_ids or not set(item.source_ids).issubset(evidence_ids)
            for item in style_items
        ):
            raise ValueError("expression style must reference existing evidence")
        return self


class UnlockedFact(StrictModel):
    fact_id: str
    content: str
    evidence_session: int = Field(ge=1)
    evidence_turn: int = Field(ge=0)
    disclosure_method: Literal["explicit", "confirmed_inference"] = "explicit"
    disclosure_level: int = Field(default=1, ge=1, exclude=True)


class UnlockedClientInfo(StrictModel):
    """The counselor's sole structured knowledge, built only from spoken evidence."""

    client_id: str
    static_traits: StaticTraits = Field(default_factory=StaticTraits)
    main_problem: str = ""
    topic: str = ""
    core_demands: str = ""
    growth_experiences: list[str] = Field(default_factory=list)
    theory: dict[str, Any] = Field(default_factory=dict)
    facts: list[UnlockedFact] = Field(default_factory=list)
    updated_session: int = Field(default=0, ge=0)


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


class MemoryItemUpdate(StrictModel):
    """One evidence-bound status change for an already tracked memory item.

    ``item_updates`` lets E.9 retire or keep an open homework/topic item by its
    stable id instead of re-typing its wording, so a paraphrase cannot orphan an
    item. A ``done`` update is only accepted when ``evidence`` really appears in
    the current session dialogue (enforced in ``runtime/memory.py``).
    """

    item_id: str
    status: Literal["open", "done", "dropped"] = "done"
    evidence: str = ""


class HomeworkItem(StrictModel):
    """One assignment with an explicit open/done lifecycle.

    ``last_homework`` keeps the assignment the client still has to work on (the
    one just handed out plus anything from earlier sessions that is not done
    yet); retired items stay in ``SessionRecap.homework`` as immutable history.
    """

    item_id: str
    text: str
    source_session: int = Field(ge=1)
    status: Literal["open", "done", "dropped", "replaced"] = "open"
    completion_evidence: str = ""
    carried_sessions: int = Field(default=0, ge=0)


class ChecklistRecord(StrictModel):
    """The archived working-memory checklist of one finished session."""

    session_index: int = Field(ge=1)
    completed_items: list[str] = Field(default_factory=list)
    important_information: list[str] = Field(default_factory=list)
    important_methods: list[str] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)


class OpenItem(StrictModel):
    """A cross-session item the counselor still has to follow up.

    ``needs_verification`` marks an item that only a session boundary implies
    (for example "the turn budget ran out"), so the read view can ask the next
    session to verify it instead of asserting the client did not finish it.
    """

    item_id: str
    kind: Literal["topic", "goal"] = "topic"
    text: str
    source_session: int = Field(ge=1)
    status: Literal["open", "done", "dropped"] = "open"
    needs_verification: bool = False
    evidence: str = ""
    carried_to_session: int | None = None


class ChecklistMemory(StrictModel):
    """Per-session checklist archive plus the still-open follow-up items."""

    per_session: list[ChecklistRecord] = Field(default_factory=list)
    open_items: list[OpenItem] = Field(default_factory=list)
    pending_verification: list[OpenItem] = Field(default_factory=list)


class RecapRisk(StrictModel):
    """Session-scoped audit record of a non-low risk judgement."""

    session_index: int = Field(ge=1)
    level: RiskLevel = RiskLevel.LOW
    categories: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class SessionRecap(StrictModel):
    """Everything the counselor keeps about one finished session (PsychAgent recap).

    It replaces the historical ``summaries`` + ``clinical_summaries`` pair with a
    single entry per session, and nests the low-signal audit material (risk,
    safety/disclosure reasons, trust deltas) inside the session it belongs to
    instead of accumulating global flat lists.
    """

    session_index: int = Field(ge=1)
    summary: str = ""
    clinical_summary: str = ""
    goal_assessment: GoalAssessment = Field(default_factory=GoalAssessment)
    client_state_analysis: ClientStateAnalysis = Field(default_factory=ClientStateAnalysis)
    homework: list[str] = Field(default_factory=list)
    interventions_used: list[str] = Field(default_factory=list)
    risk: RecapRisk | None = None
    safety_notes: list[str] = Field(default_factory=list)
    relationship_events: list[str] = Field(default_factory=list)
    client_closing: str = ""


class ClinicalSummary(StrictModel):
    """Structured clinical summary bridging consecutive sessions (E.9).

    This is the per-session clinical record produced after every session. Every
    field must be grounded in the current session dialogue; forward-looking
    diagnostic conclusions are forbidden. ``item_updates`` carries the
    evidence-bound retirement decisions for items the counselor already tracks.
    """

    session_index: int = Field(ge=1)
    session_summary_abstract: str = ""
    goal_assessment: GoalAssessment = Field(default_factory=GoalAssessment)
    client_state_analysis: ClientStateAnalysis = Field(default_factory=ClientStateAnalysis)
    homework: list[str] = Field(default_factory=list)
    important_information: list[str] = Field(default_factory=list)
    important_methods: list[str] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    completed_items: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    item_updates: list[MemoryItemUpdate] = Field(default_factory=list)


_LEGACY_MEMORY_KEYS = frozenset({
    "unlocked_client_info",
    "unlocked_profile",
    "summaries",
    "clinical_summaries",
    "completed_sessions",
    "unresolved_topics",
    "homework",
    "interventions_used",
    "risk_history",
    "supervisor_feedback",
    "relationship_events",
    "between_session_context",
    "last_client_closing",
    "confirmed_goals",
    "evolving_profile",
})

_LEGACY_AUDIT_KEYS = (
    "homework",
    "unresolved_topics",
    "interventions_used",
    "risk_history",
    "supervisor_feedback",
    "relationship_events",
    "last_client_closing",
)

_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.IMMINENT: 3,
}


def _legacy_session_number(value: dict[str, Any]) -> int:
    try:
        return max(1, int(value.get("completed_sessions") or 1))
    except (TypeError, ValueError):
        return 1


def _legacy_clinical_by_index(value: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map each legacy E.9 summary to its session index (positional fallback)."""

    by_index: dict[int, dict[str, Any]] = {}
    for position, raw in enumerate(value.get("clinical_summaries") or [], start=1):
        if not isinstance(raw, dict):
            continue
        index = raw.get("session_index")
        by_index[int(index) if isinstance(index, int) and index >= 1 else position] = raw
    return by_index


def _legacy_session_recaps(
    value: dict[str, Any], clinical: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold the flat ``summaries`` + ``clinical_summaries`` pair into recaps."""

    summaries = [str(item) for item in (value.get("summaries") or [])]
    count = max(len(summaries), max(clinical, default=0), _legacy_session_number(value))
    recaps: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        payload = clinical.get(index)
        recap: dict[str, Any] = {
            "session_index": index,
            "summary": summaries[index - 1] if index - 1 < len(summaries) else "",
        }
        if isinstance(payload, dict):
            recap.update({
                "clinical_summary": str(payload.get("session_summary_abstract") or ""),
                "goal_assessment": payload.get("goal_assessment") or {},
                "client_state_analysis": payload.get("client_state_analysis") or {},
                "homework": [str(item) for item in (payload.get("homework") or [])],
            })
        recaps.append(recap)
    return recaps


def _legacy_homework(value: dict[str, Any]) -> list[dict[str, Any]]:
    session = _legacy_session_number(value)
    items: list[dict[str, Any]] = []
    for position, raw in enumerate(value.get("homework") or [], start=1):
        text = str(raw).strip()
        if not text:
            continue
        items.append({
            "item_id": f"homework-s{session}-{position}",
            "text": text,
            "source_session": session,
            "status": "open",
            "carried_sessions": 0,
        })
    return items


def _legacy_checklist(
    value: dict[str, Any], clinical: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Archive legacy E.9 checklist fields and keep legacy topics as open items."""

    session = _legacy_session_number(value)
    fields = (
        "completed_items",
        "important_information",
        "important_methods",
        "important_results",
        "pending_items",
    )
    per_session = [
        {
            "session_index": index,
            **{
                field: [str(item) for item in (payload.get(field) or [])]
                for field in fields
            },
        }
        for index, payload in sorted(clinical.items())
    ]
    open_items = [
        {
            "item_id": f"topic-{position}",
            "kind": "topic",
            "text": str(raw),
            "source_session": session,
            "status": "open",
            "needs_verification": True,
        }
        for position, raw in enumerate(value.get("unresolved_topics") or [], start=1)
        if str(raw).strip()
    ]
    return {
        "per_session": per_session,
        "open_items": open_items,
        "pending_verification": [],
    }


def _legacy_risk_level(levels: list[str]) -> RiskLevel:
    best = RiskLevel.LOW
    for raw in levels:
        try:
            candidate = RiskLevel(raw)
        except ValueError:
            continue
        if _RISK_ORDER[candidate] > _RISK_ORDER[best]:
            best = candidate
    return best


def _fold_legacy_audit(
    value: dict[str, Any], recaps: list[dict[str, Any]]
) -> list[str]:
    """Attach unattributed legacy audit lists to the newest recap."""

    levels = [str(item) for item in (value.get("risk_history") or [])]
    feedback = [str(item) for item in (value.get("supervisor_feedback") or [])]
    events = [str(item) for item in (value.get("relationship_events") or [])]
    interventions = [str(item) for item in (value.get("interventions_used") or [])]
    closing = str(value.get("last_client_closing") or "")
    if not recaps:
        return []
    last = recaps[-1]
    if levels:
        last["risk"] = {
            "session_index": last["session_index"],
            "level": _legacy_risk_level(levels),
            "categories": [],
            "evidence": [f"legacy risk_history: {'、'.join(levels)}"],
        }
    if feedback:
        last["safety_notes"] = list(last.get("safety_notes") or []) + feedback
    if events:
        last["relationship_events"] = list(last.get("relationship_events") or []) + events
    if interventions:
        last["interventions_used"] = list(dict.fromkeys(
            list(last.get("interventions_used") or []) + interventions
        ))
    if closing:
        last["client_closing"] = closing
    if levels or feedback or events or interventions:
        return [
            "legacy flat lists (interventions_used/risk_history/supervisor_feedback/"
            "relationship_events) carried no session index; attached to session "
            f"{last['session_index']}"
        ]
    return []


def _fold_legacy_memory(value: dict[str, Any]) -> dict[str, Any]:
    """Convert one legacy flat memory payload into the four-field structure."""

    value = dict(value)
    warnings = [str(item) for item in (value.get("migration_warnings") or [])]
    if "known_background" not in value:
        legacy_profile = value.get("unlocked_profile")
        if "unlocked_client_info" in value:
            value["known_background"] = value["unlocked_client_info"]
        elif isinstance(legacy_profile, dict):
            value["known_background"] = {
                "client_id": legacy_profile.get("client_id", ""),
                "facts": legacy_profile.get("facts", []),
                "updated_session": value.get("completed_sessions", 0),
            }
            warnings.append(
                "legacy unlocked_profile detected; preloaded background, language "
                "style and core demands were discarded and dialogue replay is required"
            )
    if {"session_recaps", "last_homework", "checklist"}.issubset(value):
        leftover = sorted(set(value) & set(_LEGACY_AUDIT_KEYS))
        if leftover:
            warnings.append(
                "legacy flat keys coexisted with the four-field layout and were "
                "dropped: " + ",".join(leftover)
            )
    else:
        clinical = _legacy_clinical_by_index(value)
        recaps = _legacy_session_recaps(value, clinical)
        warnings.extend(_fold_legacy_audit(value, recaps))
        value.setdefault("session_recaps", recaps)
        value.setdefault("last_homework", _legacy_homework(value))
        value.setdefault("checklist", _legacy_checklist(value, clinical))
    for key in _LEGACY_MEMORY_KEYS | {"migration_warnings"}:
        value.pop(key, None)
    if warnings:
        value["migration_warnings"] = list(dict.fromkeys(warnings))
    return value




class SessionMemory(StrictModel):
    """Cross-session counselor memory.

    Four memory-content fields mirror PsychAgent's thin ``PublicMemory``:
    ``known_background`` (已知背景), ``session_recaps`` (每场回顾),
    ``last_homework`` (上轮作业) and the archived per-session ``checklist``
    (事项清单). ``case_id`` and ``migration_warnings`` are management
    information that never reaches the model.

    ``migrate_legacy_memory_layout`` folds the historical flat layout (14 keys,
    including ``summaries``/``clinical_summaries``/``unresolved_topics``) into
    this structure, so old runs keep loading, resuming and re-rendering.
    """

    case_id: str
    known_background: UnlockedClientInfo
    session_recaps: list[SessionRecap] = Field(default_factory=list)
    last_homework: list[HomeworkItem] = Field(default_factory=list)
    checklist: ChecklistMemory = Field(default_factory=ChecklistMemory)
    migration_warnings: list[str] = Field(default_factory=list)

    @property
    def completed_sessions(self) -> int:
        """Derived progress: one committed recap per finished session."""

        return len(self.session_recaps)

    @property
    def interventions_used(self) -> list[str]:
        """Derived union of the per-session skill IDs, in session order."""

        return list(dict.fromkeys(
            item for recap in self.session_recaps for item in recap.interventions_used
        ))

    @property
    def last_client_closing(self) -> str:
        return self.session_recaps[-1].client_closing if self.session_recaps else ""

    @property
    def homework(self) -> list[str]:
        """Still-open assignments, in the order they were handed out."""

        return [item.text for item in self.last_homework if item.status == "open"]

    @property
    def unresolved_topics(self) -> list[str]:
        """Still-open follow-up items (verified topics and goals)."""

        return [item.text for item in self.checklist.open_items if item.status == "open"]

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_memory_layout(cls, value: Any) -> Any:
        """Fold the pre-4-field flat layout into recaps/homework/checklist."""

        if not isinstance(value, dict) or not (set(value) & _LEGACY_MEMORY_KEYS):
            return value
        return _fold_legacy_memory(value)


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


class SessionChecklist(StrictModel):
    """Model-maintained working memory that is scoped to one session."""

    completed_items: list[str] = Field(default_factory=list)
    important_information: list[str] = Field(default_factory=list)
    important_methods: list[str] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)


class SessionChecklistUpdate(StrictModel):
    """Additive checklist changes selected by the counselor planner."""

    completed_items: list[str] = Field(default_factory=list)
    important_information: list[str] = Field(default_factory=list)
    important_methods: list[str] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    resolved_pending_items: list[str] = Field(default_factory=list)


class CounselorPlanning(StrictModel):
    """Auditable planning summary; never a dump of private model reasoning."""

    reasoning_summary: str
    current_goal: str
    plan_steps: list[str] = Field(min_length=1, max_length=6)
    action: CounselorAction
    selected_meta_skill_ids: list[str] = Field(default_factory=list, max_length=3)
    action_input: str = ""
    selection_evidence: list[SkillSelectionEvidence] = Field(default_factory=list, max_length=3)
    checklist_update: SessionChecklistUpdate = Field(
        default_factory=SessionChecklistUpdate
    )


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


class LongitudinalReport(StrictModel):
    """Session-to-session progress signal for planning, not a clinical outcome."""

    session_index: int = Field(ge=1)
    state_deltas: dict[str, float] = Field(default_factory=dict)
    supervisor_score_delta: float | None = None
    trend: Literal["baseline", "improving", "stable", "worsening", "mixed"]
    stage_action: Literal["continue", "advance", "regress", "hold", "close"]
    evidence: list[str] = Field(default_factory=list)


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
    number string, while ``score`` carries the normalized 0-10 summary mapped
    from the instrument's own raw range. ``direction`` records whether higher
    or lower is better (symptom scales are ``lower_better``); ``score`` stays
    raw and is not direction-adjusted, matching the official eval methods.
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


class SessionEvaluationReport(StrictModel):
    """Per-session external supervision result aligned with PsychEval.

    Scored once per session with the same PsychEval instruments used by the
    final holistic report, so per-session supervision and RFT reward share a
    single LLM-as-judge evaluation. ``counselor_overall``/``client_overall``
    are 0-10 summaries (higher is better) of the counselor- and client-level
    instruments respectively.
    """

    session_index: int = Field(ge=1)
    therapy: str
    counselor_shared: list[ScaleScore] = Field(default_factory=list)
    counselor_specific: list[ScaleScore] = Field(default_factory=list)
    client_shared: list[ScaleScore] = Field(default_factory=list)
    client_specific: list[ScaleScore] = Field(default_factory=list)
    counselor_overall: float = Field(ge=0, le=10)
    client_overall: float = Field(ge=0, le=10)
    created_at: str = Field(default_factory=utc_now)


class SessionSafetyVerdict(StrictModel):
    """Rule-based disclosure-leakage and crisis-safety gate, not a score.

    ``passed`` gates RFT eligibility; it never contributes to the reward.
    """

    session_index: int = Field(ge=1)
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    leaked_fact_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class RFTConfig(StrictModel):
    enabled: bool = False
    candidates: int = Field(default=3, ge=2, le=32)
    concurrency: int = Field(default=2, ge=1, le=32)
    judge_concurrency: int = Field(default=2, ge=1, le=16)
    candidate_timeout_sec: float = Field(default=1800, gt=0, allow_inf_nan=False)
    judge_timeout_sec: float = Field(default=240, gt=0, allow_inf_nan=False)
    min_eligible: int = Field(default=2, ge=2, le=32)
    counselor_temperature: float = Field(default=0.9, ge=0, le=2)
    judge_temperature: float = Field(default=0.0, ge=0, le=2)
    judge_retries: int = Field(default=1, ge=0, le=8)
    resample_limit: int = Field(default=2, ge=0, le=32)

    @model_validator(mode="after")
    def check_candidate_budget(self) -> RFTConfig:
        if self.min_eligible > self.candidates:
            raise ValueError("min_eligible must not exceed candidates")
        return self


class RewardSignal(StrictModel):
    """One z-scored reward signal, mirroring PsychAgent's ``src/rft/reward.py``.

    Counselor metrics are standardized on their absolute score; client metrics
    are standardized on their delta against the previous winner, with symptom
    scales negated so that higher is always better.
    """

    side: Literal["counselor", "client"]
    metric: str
    raw_value: float = Field(allow_inf_nan=False)
    standardized: float = Field(allow_inf_nan=False)
    previous_value: float | None = None
    delta: float | None = None
    skipped_reason: str | None = None


class RolloutReward(StrictModel):
    total: float = Field(allow_inf_nan=False)
    counselor_snapshot: dict[str, float] = Field(default_factory=dict)
    client_snapshot: dict[str, float] = Field(default_factory=dict)
    signals: list[RewardSignal] = Field(default_factory=list)
    skipped: list[RewardSignal] = Field(default_factory=list)
    baseline_session_index: int | None = None
    formula_version: str = "psychagent-rft-v1"


class RolloutCandidateSummary(StrictModel):
    index: int = Field(ge=1)
    status: Literal[
        "pending", "generating", "generated", "duplicate", "generation_failed",
        "scoring_failed", "rejected", "eligible", "selected", "cancelled", "safety_hold",
    ] = "pending"
    reason: str = ""
    dialogue_hash: str = ""
    duplicate_of: int | None = None
    assessment: SessionEvaluationReport | None = None
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
    safety_verdict: SessionSafetyVerdict | None = None
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
    """One committed session plus its selection reward.

    ``reward`` is either the 0-10 counselor overall score (plain run) or the
    RFT z-score average (``--rollouts N``), which is clipped to [-3, 3]. It is
    only an ordering signal for downstream selection/training export, not a
    clinical outcome measure.
    """

    trajectory_id: str
    run_id: str
    case_id: str
    session_index: int
    model_config_snapshot: dict[str, Any]
    memory_before: SessionMemory
    plan: SessionPlan
    session: SessionRecord
    reward: float = Field(ge=-3, le=10)
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


class LogprobScoringConfig(StrictModel):
    """Optional probability-weighted (logprob) scoring for PsychEval scales.

    Mirrors Eq. 8 of Zhang et al., *Mechanistic control of large language
    models as simulated participants via linear representation* (npj Artificial
    Intelligence, DOI 10.1038/s44387-026-00160-9): the judge's numeric token
    distribution is aggregated as ``sum(i * p_i) / sum(p_i)`` and a judgement
    whose total in-band probability mass stays below ``mass_floor`` is reported
    as a refusal instead of being replaced by a zero or an item average.

    Default values are the paper's scoring request (temperature 0.7, max 16
    tokens, top 20 candidates, mass floor 0.25). The path is on by default: it
    needs an endpoint that actually returns ``logprobs``/``top_logprobs``, so
    probe it with ``psych-sandbox probe logprob-scoring`` before a run. An
    endpoint without the payload (or a judgement below the floor) fails loudly
    instead of falling back to an item average, and ``enabled: false`` switches
    the path off again.
    """

    enabled: bool = True
    mass_floor: float = Field(default=0.25, gt=0, le=1)
    top_logprobs: int = Field(default=20, ge=1, le=20)
    max_tokens: int = Field(default=16, ge=1, le=64)
    temperature: float = Field(default=0.7, ge=0, le=2)


class MemoryViewConfig(StrictModel):
    """How much longitudinal memory the counselor actually reads per turn.

    ``full`` keeps the current behaviour: the whole four-field memory minus the
    management fields. ``recap_window`` injects the current focus plus the newest
    ``recent_sessions`` recaps and one archive line per older session, and always
    stays within ``max_chars``, so a 100-session course cannot grow the per-turn
    prompt without bound. It mirrors PsychAgent's switchable ``memory_mode`` so
    the two strategies can be compared without code changes.
    """

    mode: Literal["full", "recap_window"] = "full"
    recent_sessions: int = Field(default=3, ge=1, le=100)
    max_chars: int = Field(default=8000, ge=500, le=200000)
    per_field_chars: int = Field(default=240, ge=20, le=4000)
    archive_line_chars: int = Field(default=80, ge=10, le=1000)
    focus_items_max: int = Field(default=12, ge=1, le=200)


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
    client_policy: Literal[
        "compact_patientact", "faithful_patientact", "simple"
    ] = "compact_patientact"
    session_trust_retention: float = Field(default=0.5, ge=0, le=1)
    client_pullback_after: int = Field(default=2, ge=1, le=10)
    disclosure_leak_retry_limit: int = Field(default=1, ge=0, le=3)
    client_use_memory: bool = True
    client_use_pipeline: bool = True
    client_use_trust_gating: bool = True
    skill_selection: SkillSelectionConfig = Field(default_factory=SkillSelectionConfig)
    rft: RFTConfig = Field(default_factory=RFTConfig)
    logprob_scoring: LogprobScoringConfig = Field(default_factory=LogprobScoringConfig)
    memory_view: MemoryViewConfig = Field(default_factory=MemoryViewConfig)

    @model_validator(mode="after")
    def map_legacy_patientact_switch(self) -> SandboxConfig:
        if not self.patientact_enabled:
            self.client_policy = "simple"
        return self

    def model_post_init(self, __context: Any) -> None:
        from ..artifacts import latest_data_dir, runtime_root

        if self.database_path is None:
            self.database_path = runtime_root(self.project_root) / "psychsandbox.sqlite3"
        if self.trace_dir is None:
            self.trace_dir = runtime_root(self.project_root)
        if self.processed_dataset_dir is None:
            self.processed_dataset_dir = latest_data_dir(self.project_root, "processed")
