from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from ..domain import (
    CCRT,
    DerivationType,
    DisclosureItem,
    EvidenceBackedPattern,
    EvidenceNode,
    ClientExpressionStyle,
    FivePsCoverage,
    FivePsCoverageStatus,
    FivePsFormulation,
    FormulationItem,
    InteractionPrior,
    SessionPlan,
    TrustTier,
)


PROFILE_SCHEMA_VERSION = "4"
ATOMIZER_PROMPT_VERSION = "psycheval_extract_only_v2"


@dataclass(frozen=True, slots=True)
class AtomicSpan:
    start: int
    end: int
    text: str
    kind: str = "formative_event"
    activation_tags: tuple[str, ...] = ()
    trust_tier: TrustTier = TrustTier.SENSITIVE
    five_ps_roles: tuple[str, ...] = ()
    needs_review: bool = False


@dataclass(slots=True)
class CompiledProfileParts:
    evidence_nodes: list[EvidenceNode]
    disclosure_items: list[DisclosureItem]
    formulation_5ps: FivePsFormulation
    interaction_prior: InteractionPrior
    expression_style: ClientExpressionStyle


def stable_evidence_id(case_id: str, source_path: str, start: int, end: int) -> str:
    digest = hashlib.sha256(
        f"{case_id}\0{source_path}\0{start}\0{end}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{case_id}:evidence:{digest}"


class PsychEvalProfileCompiler:
    """Compile PsychEval facts into auditable runtime projections.

    The compiler never invents case content. Model-produced atomic spans must be
    validated before being passed here; missing spans fall back to one complete
    source item.
    """

    def compile(
        self,
        *,
        case_id: str,
        info: dict[str, Any],
        therapy_code: str,
        plans: list[SessionPlan],
        free_text_spans: dict[str, list[AtomicSpan]] | None = None,
    ) -> CompiledProfileParts:
        nodes: list[EvidenceNode] = []
        disclosures: list[DisclosureItem] = []
        free_text_spans = free_text_spans or {}

        routine_specs = (
            ("client_info.static_traits.name", info.get("static_traits", {}).get("name"), "name", ("称呼", "名字")),
            ("client_info.static_traits.age", info.get("static_traits", {}).get("age"), "age", ("年龄", "多大")),
            ("client_info.static_traits.gender", info.get("static_traits", {}).get("gender"), "gender", ("性别",)),
            ("client_info.static_traits.occupation", info.get("static_traits", {}).get("occupation"), "occupation", ("工作", "职业")),
            ("client_info.static_traits.educational_background", info.get("static_traits", {}).get("educational_background"), "education", ("学习", "学历")),
            ("client_info.static_traits.marital_status", info.get("static_traits", {}).get("marital_status"), "marital_status", ("婚姻", "伴侣")),
            ("client_info.main_problem", info.get("main_problem"), "presenting_problem", ("困扰", "怎么了", "为什么来")),
            ("client_info.topic", info.get("topic"), "topic", ("想谈", "主题")),
        )
        for path, value, kind, tags in routine_specs:
            node = self._add_scalar_node(nodes, case_id, therapy_code, path, value, kind)
            if node:
                disclosures.append(_routine_disclosure(node, kind, tags))

        language_path = "client_info.static_traits.language_features"
        language_text = str(info.get("static_traits", {}).get("language_features") or "").strip()
        for span in free_text_spans.get(language_path, []):
            nodes.append(self._node(case_id, therapy_code, language_path, language_text, span.start, span.end, span.kind, span.five_ps_roles, span.needs_review))

        demand_path = "client_info.core_demands"
        demand_text = str(info.get("core_demands") or "").strip()
        for span in free_text_spans.get(demand_path, []):
            node = self._node(case_id, therapy_code, demand_path, demand_text, span.start, span.end, span.kind, span.five_ps_roles, span.needs_review)
            nodes.append(node)
            if span.kind == "client_goal":
                disclosures.append(_routine_disclosure(node, "client_goal", ("目标", "希望", "期待")))

        for field, category, tags in (
            ("family_status", "family_status", ("家庭", "家人")),
            ("social_status", "social_status", ("支持", "朋友", "社交")),
            ("medical_history", "medical_history", ("病史", "就医", "用药")),
        ):
            path = f"client_info.static_traits.{field}"
            text = str(info.get("static_traits", {}).get(field) or "").strip()
            for span in free_text_spans.get(path, []):
                node = self._node(
                    case_id, therapy_code, path, text, span.start, span.end,
                    span.kind, span.five_ps_roles, span.needs_review,
                )
                nodes.append(node)
                disclosures.append(
                    DisclosureItem(
                        item_id=node.evidence_id,
                        evidence_ids=[node.evidence_id],
                        content=node.source_text,
                        category=category,
                        activation_tags=list(tags),
                        activation_examples=[f"方便说说你的{tags[0]}情况吗？"],
                        trust_tier=span.trust_tier,
                        generates_discomfort=span.trust_tier in {
                            TrustTier.SENSITIVE, TrustTier.DEEP
                        },
                    )
                )

        for index, value in enumerate(info.get("growth_experiences", []) or []):
            text = str(value).strip()
            if not text:
                continue
            path = f"client_info.growth_experiences[{index}]"
            spans = free_text_spans.get(path) or [
                AtomicSpan(
                    start=0,
                    end=len(text),
                    text=text,
                    activation_tags=tuple(_activation_tags(text, ["经历", "成长", "过去"])),
                    trust_tier=_growth_tier(text),
                    needs_review=True,
                )
            ]
            for span in spans:
                node = self._node(
                    case_id, therapy_code, path, text, span.start, span.end, span.kind,
                    span.five_ps_roles,
                    span.needs_review,
                )
                nodes.append(node)
                disclosures.append(
                    DisclosureItem(
                        item_id=node.evidence_id,
                        evidence_ids=[node.evidence_id],
                        content=span.text,
                        category="growth_experience",
                        activation_tags=list(span.activation_tags) or _activation_tags(
                            span.text, ["经历", "成长", "过去"]
                        ),
                        activation_examples=[
                            "这段经历当时是怎样的？",
                            "这件事后来怎样影响了你？",
                        ],
                        trust_tier=span.trust_tier,
                        generates_discomfort=span.trust_tier in {
                            TrustTier.SENSITIVE, TrustTier.DEEP
                        },
                        session_scope=_session_scope(span.text, plans),
                    )
                )

        for spec in _therapy_specs(therapy_code):
            for path, text, kind in _iter_spec_values(info, spec):
                node = self._node(
                    case_id, therapy_code, path, text, 0, len(text), kind
                )
                nodes.append(node)
                tier = _structured_tier(path, text)
                disclosures.append(
                    DisclosureItem(
                        item_id=node.evidence_id,
                        evidence_ids=[node.evidence_id],
                        content=text,
                        category=spec[1],
                        activation_tags=_activation_tags(text, list(spec[3])),
                        activation_examples=list(spec[4]),
                        trust_tier=tier,
                        generates_discomfort=tier in {
                            TrustTier.SENSITIVE, TrustTier.DEEP
                        },
                        session_scope=_session_scope(text, plans),
                    )
                )

        nodes = _deduplicate_nodes(nodes)
        disclosures = _deduplicate_disclosures(disclosures)
        formulation = _build_five_ps(info, therapy_code, nodes)
        interaction = _build_interaction_prior(info, therapy_code, nodes)
        expression = _build_expression_style(nodes)
        return CompiledProfileParts(nodes, disclosures, formulation, interaction, expression)

    @staticmethod
    def _node(
        case_id: str,
        therapy_code: str,
        source_path: str,
        source_text: str,
        start: int,
        end: int,
        kind: str,
        five_ps_roles: tuple[str, ...] = (),
        needs_review: bool = False,
    ) -> EvidenceNode:
        return EvidenceNode(
            evidence_id=stable_evidence_id(case_id, source_path, start, end),
            source_path=source_path,
            source_text=source_text[start:end],
            source_start=start,
            source_end=end,
            kind=kind,
            therapy=therapy_code,
            five_ps_roles=list(five_ps_roles),
            needs_review=needs_review,
        )

    def _add_scalar_node(
        self,
        nodes: list[EvidenceNode],
        case_id: str,
        therapy_code: str,
        source_path: str,
        value: Any,
        kind: str,
    ) -> EvidenceNode | None:
        text = str(value or "").strip()
        if text:
            node = self._node(case_id, therapy_code, source_path, text, 0, len(text), kind)
            nodes.append(node)
            return node
        return None


def _routine_disclosure(
    node: EvidenceNode, category: str, activation_tags: tuple[str, ...]
) -> DisclosureItem:
    return DisclosureItem(
        item_id=node.evidence_id,
        evidence_ids=[node.evidence_id],
        content=node.source_text,
        category=category,
        activation_tags=list(activation_tags),
        activation_examples=[f"请问你的{activation_tags[0]}是什么？"],
        trust_tier=TrustTier.ROUTINE,
    )


# parent field, disclosure category, fields, activation fallbacks, examples
TherapySpec = tuple[str, str, tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]


def _therapy_specs(therapy: str) -> tuple[TherapySpec, ...]:
    return {
        "bt": ((
            "target_behavior", "bt_target_behavior",
            (("behavior", "target_behavior"), ("antecedent", "antecedent"),
             ("core_reason", "core_reason"), ("function", "function"),
             ("consequence", "consequence")),
            ("行为", "前因", "回避", "后果"),
            ("这种行为通常在什么情况下出现？",),
        ),),
        "cbt": ((
            "special_situations", "cbt_special_situation",
            (("event", "trigger"), ("automatic_thoughts", "automatic_thought"),
             ("conditional_assumptions", "intermediate_belief"),
             ("compensatory_strategies", "coping_pattern")),
            ("情境", "想法", "应对"),
            ("当时发生了什么？", "那一刻你脑中出现了什么？"),
        ),),
        "het": (
            ("existentialism_topic", "het_existential_topic",
             (("theme", "existential_theme"), ("manifestations", "manifestation"),
              ("outcomes", "outcome")),
             ("意义", "体验", "生活"), ("这种体验对你意味着什么？",)),
            ("contact_model", "het_contact_model",
             (("mode", "contact_mode"), ("manifestations", "manifestation")),
             ("关系", "需要", "接触"), ("和别人接触时通常会怎样？",)),
        ),
        "pdt": (
            ("core_conflict", "pdt_core_conflict",
             (("wish", "wish"), ("fear", "fear"), ("defense_goal", "defense_goal")),
             ("愿望", "害怕", "冲突"), ("一方面你希望什么，另一方面又担心什么？",)),
            ("object_relations", "pdt_object_relation",
             (("self_representation", "self_representation"),
              ("object_representation", "object_representation"),
              ("linking_affect", "linking_affect")),
             ("自己", "他人", "关系"), ("在这种关系里你怎么看自己和对方？",)),
            ("behavioral_response_patterns", "pdt_response_pattern",
             (("trigger_condition", "trigger"), ("interpretation", "interpretation"),
              ("defense_mechanism", "defense"),
              ("response_instruction", "response_pattern")),
             ("触发", "关系", "反应"), ("类似情形出现时你通常怎样回应？",)),
        ),
        "pmt": (
            ("exception_events", "pmt_exception_event",
             (("target_problem", "target_problem"), ("unique_outcome", "exception"),
              ("reason", "supporting_factor")),
             ("例外", "不同", "改变"), ("有没有问题没有控制你的时候？",)),
            ("force_field", "pmt_force_field",
             (("positive_force", "protective_force"),
              ("negative_force", "perpetuating_force")),
             ("资源", "力量", "阻碍"), ("哪些力量在帮助或阻碍改变？",)),
        ),
    }[therapy]


def _iter_spec_values(
    info: dict[str, Any], spec: TherapySpec
) -> Iterable[tuple[str, str, str]]:
    parent, _, fields, _, _ = spec
    raw = info.get(parent)
    records = raw if isinstance(raw, list) else [raw]
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        parent_path = f"client_info.{parent}"
        if isinstance(raw, list):
            parent_path += f"[{index}]"
        for field, kind in fields:
            value = record.get(field)
            values = value if isinstance(value, list) else [value]
            for value_index, item in enumerate(values):
                text = str(item or "").strip()
                if not text:
                    continue
                path = f"{parent_path}.{field}"
                if isinstance(value, list):
                    path += f"[{value_index}]"
                yield path, text, kind


def _deduplicate_nodes(nodes: list[EvidenceNode]) -> list[EvidenceNode]:
    return list({item.evidence_id: item for item in nodes}.values())


def _deduplicate_disclosures(items: list[DisclosureItem]) -> list[DisclosureItem]:
    return list({item.item_id: item for item in items}.values())


def _nodes_for(nodes: list[EvidenceNode], prefix: str) -> list[EvidenceNode]:
    return [item for item in nodes if item.source_path.startswith(prefix)]


def _formulation_items(
    nodes: Iterable[EvidenceNode], *, derivation: DerivationType = DerivationType.DIRECT
) -> list[FormulationItem]:
    return [
        FormulationItem(
            text=node.source_text,
            source_ids=[node.evidence_id],
            derivation=derivation,
        )
        for node in nodes
        if node.source_text.strip()
    ]


def _build_five_ps(
    info: dict[str, Any], therapy: str, nodes: list[EvidenceNode]
) -> FivePsFormulation:
    presenting = _formulation_items(_nodes_for(nodes, "client_info.main_problem"))
    growth_nodes = _nodes_for(nodes, "client_info.growth_experiences")
    # Growth material is only a candidate pool. Its 5Ps role must be selected
    # explicitly by the extractive classifier; being historical alone does not
    # prove a predisposing causal role.
    growth: list[EvidenceNode] = []
    precipitating_prefixes: dict[str, tuple[str, ...]] = {
        "bt": ("client_info.target_behavior",),
        "cbt": ("client_info.special_situations",),
        "het": (),
        "pdt": ("client_info.behavioral_response_patterns",),
        "pmt": (),
    }
    precipitating_kinds = {"antecedent", "trigger"}
    precipitating_nodes = [
        node for node in nodes
        if node.kind in precipitating_kinds
        and any(node.source_path.startswith(prefix) for prefix in precipitating_prefixes[therapy])
    ]
    perpetuating_kinds = {
        "core_reason", "function", "consequence", "automatic_thought",
        "intermediate_belief", "coping_pattern", "contact_mode", "manifestation",
        "defense_goal", "interpretation", "defense", "response_pattern",
        "perpetuating_force",
    }
    perpetuating_nodes = [node for node in nodes if node.kind in perpetuating_kinds]
    protective_kinds = {"protective_force", "exception", "supporting_factor"}
    protective_nodes = [node for node in nodes if node.kind in protective_kinds]
    formulation = FivePsFormulation(
        presenting_problem=presenting,
        predisposing_factors=_formulation_items(growth),
        precipitating_factors=_formulation_items(precipitating_nodes),
        perpetuating_factors=_formulation_items(
            perpetuating_nodes, derivation=DerivationType.STRUCTURED_MAPPING
        ),
        protective_factors=_formulation_items(protective_nodes),
    )
    role_fields = {
        "presenting": formulation.presenting_problem,
        "predisposing": formulation.predisposing_factors,
        "precipitating": formulation.precipitating_factors,
        "perpetuating": formulation.perpetuating_factors,
        "protective": formulation.protective_factors,
    }
    for role, field in role_fields.items():
        extra = [node for node in nodes if role in node.five_ps_roles]
        if extra:
            existing = {source for item in field for source in item.source_ids}
            field.extend(_formulation_items(
                (node for node in extra if node.evidence_id not in existing),
                derivation=DerivationType.STRUCTURED_MAPPING,
            ))
    uncertain_roles = {"predisposing"} if any(node.needs_review for node in growth_nodes) else set()
    formulation.coverage = {
        role: FivePsCoverage(
            status=(
                FivePsCoverageStatus.SUPPORTED if items
                else FivePsCoverageStatus.UNCERTAIN if role in uncertain_roles
                else FivePsCoverageStatus.SOURCE_ABSENT
            ),
            source_ids=list(dict.fromkeys(source for item in items for source in item.source_ids)),
            reason=(
                "由已有证据支持" if items
                else "抽取失败，保留原文等待复核" if role in uncertain_roles
                else "原始资料中没有足够的可引用证据"
            ),
        )
        for role, items in role_fields.items()
    }
    return formulation


def _build_expression_style(nodes: list[EvidenceNode]) -> ClientExpressionStyle:
    prefix = "client_info.static_traits.language_features"
    values: dict[str, list[EvidenceBackedPattern]] = {
        "verbal_style": [], "interaction_style": [], "affective_expression": []
    }
    for node in _nodes_for(nodes, prefix):
        if node.kind in values:
            values[node.kind].append(
                EvidenceBackedPattern(text=node.source_text, source_ids=[node.evidence_id])
            )
    return ClientExpressionStyle(**values)


def _pattern(nodes: list[EvidenceNode], prefix: str, kind: str) -> EvidenceBackedPattern | None:
    matches = [item for item in nodes if item.source_path.startswith(prefix) and item.kind == kind]
    if not matches:
        return None
    return EvidenceBackedPattern(
        text="；".join(item.source_text for item in matches),
        source_ids=[item.evidence_id for item in matches],
    )


def _build_interaction_prior(
    info: dict[str, Any], therapy: str, nodes: list[EvidenceNode]
) -> InteractionPrior:
    coping: list[EvidenceBackedPattern] = []
    emotional: list[EvidenceBackedPattern] = []
    misattunement: list[EvidenceBackedPattern] = []
    therapist_pattern: CCRT | None = None

    language = _pattern(nodes, "client_info.static_traits.language_features", "language_observation")
    if language:
        emotional.append(language)

    if therapy == "pdt":
        wish = _pattern(nodes, "client_info.core_conflict", "wish")
        fear = _pattern(nodes, "client_info.core_conflict", "fear")
        other = _pattern(nodes, "client_info.object_relations", "object_representation")
        response = _pattern(nodes, "client_info.behavioral_response_patterns", "response_pattern")
        sources = [item for item in (wish, fear, other, response) if item]
        if wish or fear or other or response:
            therapist_pattern = CCRT(
                wish=wish.text if wish else "",
                expected_response=other.text if other else (fear.text if fear else ""),
                self_response=response.text if response else "",
                source_ids=list(dict.fromkeys(
                    source_id for item in sources for source_id in item.source_ids
                )),
            )
        for kind in ("defense", "response_pattern"):
            item = _pattern(nodes, "client_info.behavioral_response_patterns", kind)
            if item:
                coping.append(item)
        if fear:
            misattunement.append(fear)
    elif therapy == "cbt":
        for kind in ("intermediate_belief", "coping_pattern"):
            item = _pattern(nodes, "client_info.special_situations", kind)
            if item:
                coping.append(item)
    elif therapy == "het":
        for kind in ("contact_mode", "manifestation"):
            item = _pattern(nodes, "client_info.contact_model", kind)
            if item:
                coping.append(item)
    elif therapy == "bt":
        item = _pattern(nodes, "client_info.target_behavior", "function")
        if item:
            coping.append(item)
    elif therapy == "pmt":
        item = _pattern(nodes, "client_info.force_field", "protective_force")
        if item:
            coping.append(item)
        negative = _pattern(nodes, "client_info.force_field", "perpetuating_force")
        if negative:
            misattunement.append(negative)

    source_ids = list(dict.fromkeys(
        source_id
        for item in coping + emotional + misattunement
        for source_id in item.source_ids
    ))
    if therapist_pattern:
        source_ids = list(dict.fromkeys(source_ids + therapist_pattern.source_ids))
    return InteractionPrior(
        therapist_pattern=therapist_pattern,
        coping_patterns=coping,
        emotional_access=emotional,
        expected_misattunement=misattunement,
        source_ids=source_ids,
    )


def _growth_tier(text: str) -> TrustTier:
    if any(term in text for term in ("自杀", "性关系", "虐待", "创伤", "抛弃")):
        return TrustTier.DEEP
    if any(term in text for term in ("羞耻", "失败", "离开", "去世", "批评", "孤单", "愧疚")):
        return TrustTier.SENSITIVE
    return TrustTier.MODERATE


def _structured_tier(path: str, text: str) -> TrustTier:
    if any(term in path for term in ("fear", "object_relations", "linking_affect")):
        return TrustTier.SENSITIVE
    if any(term in text for term in ("自杀", "性关系", "虐待", "创伤")):
        return TrustTier.DEEP
    if any(term in path for term in ("antecedent", "event", "positive_force", "unique_outcome")):
        return TrustTier.BASIC
    return TrustTier.MODERATE


def _activation_tags(text: str, fallback: list[str]) -> list[str]:
    terms = (
        "父亲", "母亲", "父母", "家庭", "小时候", "学校", "同学", "朋友",
        "伴侣", "工作", "实习", "失败", "关系", "声音", "睡眠", "外婆",
        "焦虑", "抑郁", "意义", "离开", "批评", "支持", "改变",
    )
    found = [term for term in terms if term in text]
    return list(dict.fromkeys(found + fallback))[:12]


def _session_scope(content: str, plans: list[SessionPlan]) -> list[int]:
    probes = [part for part in (content[:12], content[:8], content[:4]) if len(part) >= 4]
    matched: list[int] = []
    for plan in plans:
        planning_text = " ".join(plan.persona_links + plan.case_materials)
        if any(probe in planning_text or planning_text.find(probe) >= 0 for probe in probes):
            matched.append(plan.session_index)
    return matched
