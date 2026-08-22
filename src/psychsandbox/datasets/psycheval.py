from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from ..domain import (
    AtomicSkill,
    BigFive,
    ClientProfile,
    ClientRelationalProfile,
    ClientState,
    CounselingCase,
    FivePsFormulation,
    HiddenFact,
    MetaSkill,
    ResistancePatternType,
    SessionPlan,
    SessionStage,
    StaticTraits,
)
from ..skills import SkillRegistry
from ..therapies import normalize_therapy_id


PSYCHEVAL_REPOSITORY = "https://github.com/ECNU-ICALK/PsychEval.git"
PSYCHEVAL_REVISION = "e04df535749e5bca76fcc45d9a85f3f46a082d91"

_RAW_THERAPY_MAP = {
    "bt": "behavioral",
    "cbt": "cbt",
    "het": "humanistic_existential",
    "pdt": "psychodynamic",
    "pmt": "postmodern",
}

_FACT_TOPIC_TERMS = (
    "父亲", "母亲", "父母", "家庭", "小时候", "小学", "中学", "大学",
    "老师", "同学", "朋友", "伴侣", "婚姻", "孩子", "上司", "领导",
    "实习", "工作", "考试", "毕业", "失业", "睡眠", "争吵", "批评",
    "失败", "拒绝", "离开", "生病", "医院", "焦虑", "抑郁",
)


def _fact_activation_tags(content: str, fallback: list[str]) -> list[str]:
    """Create fact-specific, auditable tags without inventing case content."""

    specific = [term for term in _FACT_TOPIC_TERMS if term in content]
    quoted = [
        value.strip()
        for value in re.findall(r"[“\"]([^”\"]{2,12})[”\"]", content)
        if value.strip()
    ]
    return list(dict.fromkeys(specific + quoted + fallback))[:12]


def _disclosure_layers(content: str) -> list[str]:
    """Split a source fact into cumulative disclosure depths."""

    clauses = [
        item.strip()
        for item in re.split(r"(?<=[。！？；])", content)
        if item.strip()
    ]
    if len(clauses) <= 1:
        clauses = [
            item.strip()
            for item in re.split(r"[；;]", content)
            if item.strip()
        ]
    if len(clauses) <= 1:
        return [content]
    boundaries = sorted({1, min(2, len(clauses)), len(clauses)})
    return ["".join(clauses[:end]) for end in boundaries]


def _situation_layers(situation: dict[str, Any]) -> list[str]:
    fields = (
        ("event", "事件"),
        ("automatic_thoughts", "当时的想法"),
        ("conditional_assumptions", "背后的假设"),
        ("compensatory_strategies", "应对方式"),
    )
    parts = [
        f"{label}：{str(situation.get(key, '')).strip()}"
        for key, label in fields
        if str(situation.get(key, "")).strip()
    ]
    return ["；".join(parts[:end]) for end in range(1, len(parts) + 1)]


def _text_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _display_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_text_items(value))
    if isinstance(value, dict):
        return "、".join(
            f"{key}：{_display_value(item)}"
            for key, item in value.items()
            if _display_value(item)
        )
    return str(value or "").strip()


def _structured_layers(
    item: dict[str, Any], fields: tuple[tuple[str, str], ...]
) -> list[str]:
    parts = [
        f"{label}：{text}"
        for key, label in fields
        if (text := _display_value(item.get(key)))
    ]
    return ["；".join(parts[:end]) for end in range(1, len(parts) + 1)]


def _append_structured_fact(
    facts: list[HiddenFact],
    *,
    case_id: str,
    fact_key: str,
    index: int,
    item: dict[str, Any],
    fields: tuple[tuple[str, str], ...],
    category: str,
    source_field: str,
    topics: list[str],
    activation_examples: list[str],
    minimum_trust: float = 0.32,
    minimum_topic_readiness: float = 0.28,
) -> None:
    layers = _structured_layers(item, fields)
    if not layers:
        return
    facts.append(
        HiddenFact(
            fact_id=f"{case_id}:{fact_key}:{index}",
            content=layers[-1],
            category=category,
            minimum_trust=minimum_trust,
            minimum_topic_readiness=minimum_topic_readiness,
            required_topics=topics,
            sensitivity=min(0.86, 0.44 + index * 0.05),
            activation_tags=_fact_activation_tags(layers[0], topics),
            activation_examples=activation_examples,
            negative_examples=["能介绍一下你的基本情况吗？"],
            topic_key=f"{fact_key}_{index}",
            disclosure_layers=layers,
            source_field=source_field,
            generates_discomfort=index >= 2,
        )
    )


def fetch_psycheval(destination: Path, revision: str = PSYCHEVAL_REVISION) -> Path:
    """Fetch the five supported therapy datasets and evaluation prompts."""

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not (destination / ".git").exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--sparse",
                PSYCHEVAL_REPOSITORY,
                str(destination),
            ],
            check=True,
        )
    subprocess.run(
        [
            "git", "-C", str(destination), "sparse-checkout", "set",
            "data/bt", "data/cbt", "data/het", "data/pdt", "data/pmt",
            "eval/prompts_cn",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(destination), "checkout", "--detach", revision],
        check=True,
    )
    return destination


class PsychEvalAdapter:
    def __init__(
        self,
        revision: str = PSYCHEVAL_REVISION,
        *,
        therapy_code: str = "cbt",
        source_name: str = "PsychEval",
    ):
        if therapy_code not in _RAW_THERAPY_MAP:
            supported = ", ".join(sorted(_RAW_THERAPY_MAP))
            raise ValueError(
                f"Unsupported raw therapy {therapy_code!r}; supported: {supported}"
            )
        self.revision = revision
        self.therapy_code = therapy_code
        self.therapy_id = _RAW_THERAPY_MAP[therapy_code]
        self.source_name = source_name

    def convert_case(self, raw: dict[str, Any], source_path: str = "") -> CounselingCase:
        client_id = str(raw["client_id"])
        case_id = f"psycheval-{self.therapy_code}-{client_id.zfill(3)}"
        info = raw["client_info"]
        static = info.get("static_traits", {})
        hidden = self._hidden_facts(case_id, info, self.therapy_code)
        personality = BigFive()
        reference_sessions = raw.get("sessions", [])
        opening = self._opening(reference_sessions, info.get("main_problem", ""))
        profile = ClientProfile(
            client_id=client_id,
            static_traits=StaticTraits(
                name=str(static.get("name", "")),
                age=str(static.get("age", "")),
                gender=str(static.get("gender", "")),
                occupation=str(static.get("occupation", "")),
                educational_background=str(static.get("educational_background", "")),
                marital_status=str(static.get("marital_status", "")),
                family_status=str(static.get("family_status", "")),
                social_status=str(static.get("social_status", "")),
                medical_history=str(static.get("medical_history", "")),
                language_features=str(static.get("language_features", "")),
            ),
            main_problem=str(info.get("main_problem", "")),
            topic=str(info.get("topic", "")),
            core_demands=str(info.get("core_demands", "")),
            growth_experiences=[str(item) for item in info.get("growth_experiences", [])],
            formulation_5ps=self._five_ps(info, self.therapy_code),
            theory={
                self.therapy_code: {
                    key: value
                    for key, value in info.items()
                    if key
                    not in {
                        "static_traits",
                        "main_problem",
                        "topic",
                        "core_demands",
                        "growth_experiences",
                    }
                },
                "_personality_source": "unspecified_neutral_prior",
                "_source_path": source_path,
            },
            personality=personality,
            relational=self._relational_profile(info, hidden, self.therapy_code),
            initial_state=self._initial_state(info),
            language_style=str(static.get("language_features", "")),
            opening=opening,
            hidden_facts=hidden,
        )
        plans = self._session_plans(raw)
        return CounselingCase(
            case_id=case_id,
            therapy=self.therapy_id,
            profile=profile,
            global_plan=plans,
            reference_sessions=reference_sessions,
            source=self.source_name,
            source_revision=self.revision,
        )

    def extract_skills(
        self, raw_cases: Iterable[dict[str, Any]]
    ) -> SkillRegistry:
        meta: dict[str, MetaSkill] = {}
        atomic: dict[str, AtomicSkill] = {}
        for raw in raw_cases:
            for session in raw.get("sessions", []):
                stage = _map_stage(
                    session.get("session_goals", {}).get("overall_stage", "")
                )
                for bundle in session.get("suggest_skills", []):
                    meta_text = str(bundle.get("meta_skill", "")).strip()
                    meta_name = meta_text.split(":", 1)[0] or "未命名元技能"
                    meta_id = _derived_meta_id(meta_text)
                    meta.setdefault(
                        meta_id,
                        MetaSkill(
                            meta_skill_id=meta_id,
                            name=meta_name,
                            description=meta_text,
                            therapy=self.therapy_id,
                            stages=[stage],
                            source="PsychEval",
                        ),
                    )
                    if stage not in meta[meta_id].stages:
                        meta[meta_id].stages.append(stage)
                    for item in bundle.get("micro_skills", []):
                        skill_id = str(item.get("skill_id", "")).strip()
                        if not skill_id:
                            continue
                        candidate = AtomicSkill(
                            skill_id=skill_id,
                            name=str(item.get("skill_name", "")),
                            description=str(item.get("skill_description", "")),
                            therapy=self.therapy_id,
                            stages=[stage],
                            meta_skill_id=meta_id,
                            when_to_use=str(item.get("when_to_use", "")),
                            triggers=_trigger_phrases(str(item.get("trigger", ""))),
                            intervention_type=_intervention_type(
                                str(item.get("skill_name", "")),
                                str(item.get("skill_description", "")),
                            ),
                            source="PsychEval",
                        )
                        if skill_id not in atomic:
                            atomic[skill_id] = candidate
                        elif stage not in atomic[skill_id].stages:
                            atomic[skill_id].stages.append(stage)
        return SkillRegistry(list(meta.values()), list(atomic.values()))

    def _session_plans(self, raw: dict[str, Any]) -> list[SessionPlan]:
        plans: list[SessionPlan] = []
        for session in raw.get("sessions", []):
            index = int(session.get("session_number", len(plans) + 1))
            goals = session.get("session_goals", {})
            focus = goals.get("session_focus", {})
            objectives = focus.get("objective", [])
            if isinstance(objectives, str):
                objectives = [objectives]
            content = _global_content(raw.get("global_plan", []), index)
            suggested = session.get("suggest_skills", [])
            target_atomic = [
                str(skill.get("skill_id"))
                for bundle in suggested
                for skill in bundle.get("micro_skills", [])
                if skill.get("skill_id") is not None
            ]
            target_meta = [
                _derived_meta_id(str(bundle.get("meta_skill", "")))
                for bundle in suggested
            ]
            plans.append(
                SessionPlan(
                    session_index=index,
                    therapy=self.therapy_id,
                    stage=_map_stage(goals.get("overall_stage", "")),
                    objectives=[str(item) for item in objectives],
                    persona_links=[str(item) for item in content.get("persona_links", [])],
                    case_materials=[
                        str(item)
                        for item in content.get(
                            "case_material",
                            content.get("case_materials", []),
                        )
                    ],
                    target_meta_skill_ids=list(dict.fromkeys(target_meta)),
                    target_atomic_skill_ids=list(dict.fromkeys(target_atomic)),
                    forbidden_actions=[
                        "医学诊断",
                        "使用未披露档案",
                        "危机时继续普通干预",
                    ],
                )
            )
        return plans

    @staticmethod
    def _five_ps(info: dict[str, Any], therapy_code: str = "cbt") -> FivePsFormulation:
        """Derive an auditable 5Ps scaffold from fields PsychEval actually ships."""

        growth = _text_items(info.get("growth_experiences", []))
        precipitating: list[str] = []
        perpetuating: list[str] = []
        protective: list[str] = []
        source_fields = [
            "client_info.main_problem",
            "client_info.growth_experiences",
            "client_info.core_demands",
            "client_info.static_traits.family_status",
        ]

        if therapy_code == "cbt":
            situations = [
                item for item in info.get("special_situations", [])
                if isinstance(item, dict)
            ]
            precipitating.extend(
                str(item.get("event", "")).strip()
                for item in situations
                if str(item.get("event", "")).strip()
            )
            for item in situations:
                for key, label in (
                    ("automatic_thoughts", "自动思维"),
                    ("conditional_assumptions", "条件假设"),
                    ("compensatory_strategies", "应对/维持策略"),
                ):
                    if value := _display_value(item.get(key)):
                        perpetuating.append(f"{label}：{value}")
            source_fields.append("client_info.special_situations")
        elif therapy_code == "bt":
            behaviors = [
                item for item in info.get("target_behavior", [])
                if isinstance(item, dict)
            ]
            for item in behaviors:
                precipitating.extend(_text_items(item.get("antecedent")))
                for key, label in (
                    ("core_reason", "行为维持原因"),
                    ("function", "行为功能"),
                    ("consequence", "行为后果"),
                ):
                    if value := _display_value(item.get(key)):
                        perpetuating.append(f"{label}：{value}")
            source_fields.append("client_info.target_behavior")
        elif therapy_code == "het":
            topics = [
                item for item in info.get("existentialism_topic", [])
                if isinstance(item, dict)
            ]
            contacts = [
                item for item in info.get("contact_model", [])
                if isinstance(item, dict)
            ]
            for item in topics:
                precipitating.extend(_text_items(item.get("manifestations")))
                perpetuating.extend(
                    f"存在主题结果：{value}" for value in _text_items(item.get("outcomes"))
                )
            for item in contacts:
                if mode := _display_value(item.get("mode")):
                    perpetuating.append(f"接触模式：{mode}")
                perpetuating.extend(
                    f"接触模式表现：{value}"
                    for value in _text_items(item.get("manifestations"))
                )
            source_fields.extend(
                ["client_info.existentialism_topic", "client_info.contact_model"]
            )
        elif therapy_code == "pdt":
            patterns = [
                item for item in info.get("behavioral_response_patterns", [])
                if isinstance(item, dict)
            ]
            precipitating.extend(
                str(item.get("trigger_condition", "")).strip()
                for item in patterns
                if str(item.get("trigger_condition", "")).strip()
            )
            conflict = info.get("core_conflict", {})
            if isinstance(conflict, dict):
                perpetuating.extend(
                    f"防御目标：{value}"
                    for value in _text_items(conflict.get("defense_goal"))
                )
            for item in patterns:
                for key, label in (
                    ("interpretation", "关系解释"),
                    ("defense_mechanism", "防御机制"),
                    ("response_instruction", "反应模式"),
                ):
                    if value := _display_value(item.get(key)):
                        perpetuating.append(f"{label}：{value}")
            source_fields.extend(
                [
                    "client_info.core_conflict",
                    "client_info.object_relations",
                    "client_info.behavioral_response_patterns",
                ]
            )
        elif therapy_code == "pmt":
            force_field = info.get("force_field", {})
            if isinstance(force_field, dict):
                precipitating.extend(_text_items(force_field.get("negative_force")))
                perpetuating.extend(
                    f"问题维持力量：{value}"
                    for value in _text_items(force_field.get("negative_force"))
                )
                protective.extend(_text_items(force_field.get("positive_force")))
            for event in info.get("exception_events", []):
                if isinstance(event, dict):
                    protective.extend(_text_items(event.get("unique_outcome")))
            source_fields.extend(
                ["client_info.exception_events", "client_info.force_field"]
            )

        if str(info.get("core_demands", "")).strip():
            protective.append("能够表达求助目标并主动参与咨询")
        family = str(info.get("static_traits", {}).get("family_status", "")).strip()
        if family:
            protective.append(f"可进一步核实的家庭/支持资源：{family}")
        return FivePsFormulation(
            presenting_problem=str(info.get("main_problem", "")).strip(),
            predisposing_factors=growth,
            precipitating_factors=list(dict.fromkeys(precipitating))[:6],
            perpetuating_factors=list(dict.fromkeys(perpetuating))[:8],
            protective_factors=list(dict.fromkeys(protective))[:8],
            source_fields=source_fields,
        )

    @staticmethod
    def _hidden_facts(
        case_id: str, info: dict[str, Any], therapy_code: str = "cbt"
    ) -> list[HiddenFact]:
        facts: list[HiddenFact] = []
        for index, content in enumerate(info.get("growth_experiences", []), start=1):
            text = str(content).strip()
            if not text:
                continue
            topic_key = f"growth_{index}"
            facts.append(
                HiddenFact(
                    fact_id=f"{case_id}:growth:{index}",
                    content=text,
                    category="growth_experience",
                    minimum_trust=0.38,
                    minimum_topic_readiness=0.35,
                    required_topics=["经历", "成长", "过去"],
                    sensitivity=min(0.85, 0.48 + index * 0.06),
                    activation_tags=_fact_activation_tags(
                        text, ["经历", "成长", "过去"]
                    ),
                    activation_examples=[
                        "这段经历当时是怎样的？",
                        "这件事后来怎样影响了你？",
                    ],
                    negative_examples=["能介绍一下你的基本情况吗？"],
                    topic_key=topic_key,
                    disclosure_layers=_disclosure_layers(text),
                    source_field=f"client_info.growth_experiences[{index - 1}]",
                    generates_discomfort=True,
                )
            )
        for index, situation in enumerate(info.get("special_situations", []), start=1):
            event = str(situation.get("event", "")).strip()
            if event:
                layers = _situation_layers(situation)
                content = layers[-1]
                topic_key = f"cbt_situation_{index}"
                facts.append(
                    HiddenFact(
                        fact_id=f"{case_id}:situation:{index}",
                        content=content,
                        category="cbt_special_situation",
                        minimum_trust=0.3,
                        minimum_topic_readiness=0.25,
                        required_topics=["情境", "发生", "当时"],
                        sensitivity=min(0.82, 0.42 + index * 0.06),
                        activation_tags=_fact_activation_tags(
                            event, ["情境", "发生", "当时"]
                        ),
                        activation_examples=[
                            "当时具体发生了什么？",
                            "那一刻你脑中闪过了什么？",
                        ],
                        negative_examples=["最近还有别的困扰吗？"],
                        topic_key=topic_key,
                        disclosure_layers=layers,
                        source_field=f"client_info.special_situations[{index - 1}]",
                        generates_discomfort=index >= 3,
                    )
                )
        if therapy_code == "bt":
            for index, item in enumerate(info.get("target_behavior", []), start=1):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="target_behavior",
                        index=index,
                        item=item,
                        fields=(
                            ("behavior", "目标行为"),
                            ("antecedent", "发生前因"),
                            ("core_reason", "核心原因"),
                            ("function", "行为功能"),
                            ("consequence", "行为后果"),
                        ),
                        category="bt_target_behavior",
                        source_field=f"client_info.target_behavior[{index - 1}]",
                        topics=["行为", "发生", "回避", "后果"],
                        activation_examples=[
                            "这种行为通常在什么情况下发生？",
                            "它当时帮助你避开了什么，又带来了什么影响？",
                        ],
                    )
        elif therapy_code == "het":
            for index, item in enumerate(info.get("existentialism_topic", []), start=1):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="existential_topic",
                        index=index,
                        item=item,
                        fields=(
                            ("theme", "存在主题"),
                            ("manifestations", "具体体验"),
                            ("outcomes", "带来的影响"),
                        ),
                        category="het_existential_topic",
                        source_field=f"client_info.existentialism_topic[{index - 1}]",
                        topics=["体验", "意义", "选择", "生活"],
                        activation_examples=[
                            "这段体验对你意味着什么？",
                            "当你面对这件事时，最深的感受是什么？",
                        ],
                    )
            for index, item in enumerate(info.get("contact_model", []), start=1):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="contact_model",
                        index=index,
                        item=item,
                        fields=(
                            ("mode", "接触模式"),
                            ("manifestations", "个人表现"),
                        ),
                        category="het_contact_model",
                        source_field=f"client_info.contact_model[{index - 1}]",
                        topics=["关系", "需要", "感受", "接触"],
                        activation_examples=[
                            "在关系里你通常怎样照顾自己的需要？",
                            "当你想靠近或拒绝别人时，会发生什么？",
                        ],
                    )
        elif therapy_code == "pdt":
            conflict = info.get("core_conflict", {})
            if isinstance(conflict, dict):
                _append_structured_fact(
                    facts,
                    case_id=case_id,
                    fact_key="core_conflict",
                    index=1,
                    item=conflict,
                    fields=(
                        ("wish", "核心愿望"),
                        ("fear", "核心恐惧"),
                        ("defense_goal", "防御目标"),
                    ),
                    category="pdt_core_conflict",
                    source_field="client_info.core_conflict",
                    topics=["愿望", "害怕", "冲突", "关系"],
                    activation_examples=[
                        "你一方面最希望得到什么，另一方面又最担心什么？",
                        "这种矛盾在关系中通常怎样出现？",
                    ],
                    minimum_trust=0.4,
                    minimum_topic_readiness=0.35,
                )
            for index, item in enumerate(info.get("object_relations", []), start=1):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="object_relation",
                        index=index,
                        item=item,
                        fields=(
                            ("self_representation", "自我感受"),
                            ("object_representation", "对他人的感受"),
                            ("linking_affect", "连接情感"),
                        ),
                        category="pdt_object_relation",
                        source_field=f"client_info.object_relations[{index - 1}]",
                        topics=["自己", "他人", "关系", "感受"],
                        activation_examples=[
                            "在这种关系里，你觉得自己和对方分别是什么样的？",
                            "这会让你产生怎样的感受？",
                        ],
                        minimum_trust=0.38,
                    )
            for index, item in enumerate(
                info.get("behavioral_response_patterns", []), start=1
            ):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="response_pattern",
                        index=index,
                        item=item,
                        fields=(
                            ("trigger_condition", "触发条件"),
                            ("interpretation", "内在解释"),
                            ("defense_mechanism", "防御方式"),
                            ("response_instruction", "反应模式"),
                        ),
                        category="pdt_response_pattern",
                        source_field=(
                            f"client_info.behavioral_response_patterns[{index - 1}]"
                        ),
                        topics=["触发", "关系", "反应", "模式"],
                        activation_examples=[
                            "类似情形出现时，你通常会怎样理解和回应？",
                            "这种反应是否也在其他关系中出现过？",
                        ],
                        minimum_trust=0.42,
                    )
        elif therapy_code == "pmt":
            for index, item in enumerate(info.get("exception_events", []), start=1):
                if isinstance(item, dict):
                    _append_structured_fact(
                        facts,
                        case_id=case_id,
                        fact_key="exception_event",
                        index=index,
                        item=item,
                        fields=(
                            ("target_problem", "相关问题"),
                            ("unique_outcome", "例外时刻"),
                            ("reason", "促成因素"),
                        ),
                        category="pmt_exception_event",
                        source_field=f"client_info.exception_events[{index - 1}]",
                        topics=["例外", "改变", "做到", "不同"],
                        activation_examples=[
                            "有没有哪一次问题没有像平时那样控制你？",
                            "那次你做了什么不同的事情？",
                        ],
                    )
            force_field = info.get("force_field", {})
            if isinstance(force_field, dict):
                _append_structured_fact(
                    facts,
                    case_id=case_id,
                    fact_key="force_field",
                    index=1,
                    item=force_field,
                    fields=(
                        ("positive_force", "支持改变的力量"),
                        ("negative_force", "阻碍改变的力量"),
                    ),
                    category="pmt_force_field",
                    source_field="client_info.force_field",
                    topics=["资源", "力量", "阻碍", "改变"],
                    activation_examples=[
                        "什么力量曾帮助你撑过来？",
                        "哪些事情在推动改变，哪些又在阻碍改变？",
                    ],
                    minimum_trust=0.3,
                )
        return facts

    @staticmethod
    def _opening(sessions: list[dict[str, Any]], fallback: str) -> str:
        if sessions:
            for item in sessions[0].get("session_dialogue", []):
                if str(item.get("role", "")).lower() == "client":
                    text = str(item.get("text", "")).strip()
                    name_only = any(
                        term in text for term in ("叫我", "称呼我", "名字是")
                    )
                    if len(text) >= 8 and not name_only:
                        return text
        return fallback or "最近有些事情让我很困扰，我想找个人谈一谈。"

    @staticmethod
    def _initial_state(info: dict[str, Any]) -> ClientState:
        text = " ".join(
            str(value)
            for value in (
                info.get("main_problem", ""),
                info.get("core_demands", ""),
                info.get("static_traits", {}).get("medical_history", ""),
            )
        )
        anxious = any(term in text for term in ("焦虑", "紧张", "担心", "失眠"))
        depressed = any(term in text for term in ("抑郁", "低落", "无力", "疲惫"))
        return ClientState(
            valence=0.28 if depressed else 0.38,
            arousal=0.7 if anxious else 0.56,
            distress=0.72 if anxious or depressed else 0.6,
            trust=0.25,
            resistance=0.4,
            hope=0.4 if str(info.get("core_demands", "")).strip() else 0.32,
        )

    @staticmethod
    def _relational_profile(
        info: dict[str, Any], hidden: list[HiddenFact], therapy_code: str = "cbt"
    ) -> ClientRelationalProfile:
        beliefs = _text_items(info.get("core_beliefs", []))
        coping = [
            str(item.get("compensatory_strategies", "")).strip()
            for item in info.get("special_situations", [])
            if isinstance(item, dict)
            and str(item.get("compensatory_strategies", "")).strip()
        ]
        if therapy_code == "bt":
            for item in info.get("target_behavior", []):
                if not isinstance(item, dict):
                    continue
                beliefs.extend(_text_items(item.get("core_reason")))
                coping.extend(_text_items(item.get("function")))
        elif therapy_code == "het":
            for item in info.get("existentialism_topic", []):
                if not isinstance(item, dict):
                    continue
                beliefs.extend(_text_items(item.get("theme")))
                beliefs.extend(_text_items(item.get("outcomes")))
            for item in info.get("contact_model", []):
                if not isinstance(item, dict):
                    continue
                coping.extend(_text_items(item.get("mode")))
                coping.extend(_text_items(item.get("manifestations")))
        elif therapy_code == "pdt":
            conflict = info.get("core_conflict", {})
            if isinstance(conflict, dict):
                beliefs.extend(_text_items(conflict.get("wish")))
                beliefs.extend(_text_items(conflict.get("fear")))
                coping.extend(_text_items(conflict.get("defense_goal")))
            for item in info.get("object_relations", []):
                if not isinstance(item, dict):
                    continue
                beliefs.extend(_text_items(item.get("self_representation")))
                beliefs.extend(_text_items(item.get("object_representation")))
            for item in info.get("behavioral_response_patterns", []):
                if not isinstance(item, dict):
                    continue
                coping.extend(_text_items(item.get("defense_mechanism")))
                coping.extend(_text_items(item.get("response_instruction")))
        elif therapy_code == "pmt":
            force_field = info.get("force_field", {})
            if isinstance(force_field, dict):
                beliefs.extend(_text_items(force_field.get("negative_force")))
                coping.extend(_text_items(force_field.get("positive_force")))
            for item in info.get("exception_events", []):
                if isinstance(item, dict):
                    coping.extend(_text_items(item.get("unique_outcome")))
        coping_text = " ".join(coping)
        preferred: list[ResistancePatternType] = []
        resistance_cues = (
            (("分析", "反思", "想清楚", "讲道理"), ResistancePatternType.INTELLECTUALIZING),
            (("回避", "逃避", "放弃", "沉默", "不愿"), ResistancePatternType.MINIMAL_TALK),
            (("顺从", "听从", "言听计从", "讨好"), ResistancePatternType.COMPLIANCE_WITHOUT_ENGAGEMENT),
            (("证明", "否认", "争辩", "反驳"), ResistancePatternType.DEFENSIVENESS),
        )
        for cues, pattern in resistance_cues:
            if any(cue in coping_text for cue in cues):
                preferred.append(pattern)

        generic_tags = {
            "影响", "关系", "事情", "感觉", "问题",
            "经历", "成长", "过去", "情境", "发生", "当时",
        }
        triggers = [
            tag
            for fact in sorted(hidden, key=lambda item: item.sensitivity, reverse=True)
            if fact.sensitivity >= 0.6
            for tag in fact.activation_tags
            if tag not in generic_tags
        ]
        emotion_source = " ".join(
            [
                str(info.get("main_problem", "")),
                _display_value(
                    {
                        key: value
                        for key, value in info.items()
                        if key not in {"static_traits", "main_problem"}
                    }
                ),
            ]
        )
        emotions = [
            term
            for term in (
                "焦虑", "紧张", "担心", "害怕", "低落", "无助",
                "愤怒", "烦躁", "羞耻", "内疚", "悲伤", "孤独",
            )
            if term in emotion_source
        ]
        return ClientRelationalProfile(
            core_belief_theme="；".join(beliefs[:3]),
            self_response_pattern="；".join(coping[:3]),
            therapy_triggers=list(dict.fromkeys(triggers))[:5],
            coping_patterns=list(dict.fromkeys(coping))[:5],
            preferred_resistance_patterns=list(dict.fromkeys(preferred))[:3],
            emotional_range=emotions[:6],
            source_fact_ids=[item.fact_id for item in hidden],
            confidence=0.6 if beliefs or coping else 0,
        )


def convert_psycheval(
    source_dir: Path,
    output_dir: Path,
    *,
    therapy: str = "cbt",
    revision: str = PSYCHEVAL_REVISION,
) -> dict[str, Any]:
    if therapy not in _RAW_THERAPY_MAP:
        supported = ", ".join(sorted(_RAW_THERAPY_MAP))
        raise ValueError(f"Unsupported therapy {therapy!r}; supported: {supported}")
    source = source_dir / "data" / therapy
    files = sorted(source.glob("*.json"), key=lambda path: int(path.stem))
    if not files:
        raise FileNotFoundError(f"No PsychEval files found under {source}")
    adapter = PsychEvalAdapter(revision, therapy_code=therapy)
    raw_cases = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in files
    ]
    cases = [
        adapter.convert_case(raw, str(path.relative_to(source_dir)))
        for raw, path in zip(raw_cases, files, strict=True)
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    split_counts = {"train": 0, "validation": 0, "test": 0}
    handles = {
        name: (output_dir / f"{name}.jsonl").open("w", encoding="utf-8")
        for name in split_counts
    }
    all_handle = (output_dir / "all.jsonl").open("w", encoding="utf-8")
    try:
        for case in cases:
            line = case.model_dump_json()
            split = _case_split(case.case_id)
            handles[split].write(line + "\n")
            all_handle.write(line + "\n")
            split_counts[split] += 1
    finally:
        for handle in handles.values():
            handle.close()
        all_handle.close()
    registry = adapter.extract_skills(raw_cases)
    registry.save(output_dir / "skills.json")
    manifest = {
        "source": PSYCHEVAL_REPOSITORY,
        "revision": revision,
        "license": "CC BY-NC 4.0",
        "therapy": therapy,
        "case_count": len(cases),
        "meta_skill_count": len(registry.meta_skills),
        "atomic_skill_count": len(registry.atomic_skills),
        "split_counts": split_counts,
        "source_digest": _files_digest(files),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


class CaseRepository:
    def __init__(
        self,
        processed_dir: Path,
        legacy_profile_dir: Path | None = None,
        raw_data_dir: Path | None = None,
    ):
        self.processed_dir = processed_dir
        self.legacy_profile_dir = legacy_profile_dir
        if raw_data_dir is None and processed_dir.parent.name == "processed":
            candidate = processed_dir.parent.parent
            if any((candidate / code).is_dir() for code in _RAW_THERAPY_MAP):
                raw_data_dir = candidate
        self.raw_data_dir = raw_data_dir
        self._index: dict[str, CounselingCase] | None = None

    @classmethod
    def from_project(cls, project_root: Path) -> "CaseRepository":
        """Create a repository using the checkout's canonical resource layout."""

        return cls(
            project_root / "data" / "processed" / "psycheval",
            project_root / "assets" / "profiles",
            project_root / "data",
        )

    def list(self, therapy: str | None = None) -> list[CounselingCase]:
        self._ensure_index()
        assert self._index is not None
        normalized_therapy = normalize_therapy_id(therapy) if therapy else None
        return sorted(
            [
                item
                for item in self._index.values()
                if normalized_therapy is None or item.therapy == normalized_therapy
            ],
            key=lambda item: item.case_id,
        )

    def get(self, case_id: str) -> CounselingCase:
        self._ensure_index()
        assert self._index is not None
        if case_id in self._index:
            return self._index[case_id]
        if self.legacy_profile_dir:
            path = self.legacy_profile_dir / f"{case_id}.json"
            if path.exists():
                return _legacy_case(path)
        available = ", ".join(sorted(self._index)[:10])
        raise FileNotFoundError(f"Unknown case {case_id!r}; examples: {available}")

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        self._index = {}
        path = self.processed_dir / "all.jsonl"
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        case = _upgrade_case_for_simulation(
                            CounselingCase.model_validate_json(line)
                        )
                        self._index[case.case_id] = case
        if self.raw_data_dir:
            for therapy_code in _RAW_THERAPY_MAP:
                therapy_dir = self.raw_data_dir / therapy_code
                if not therapy_dir.is_dir():
                    continue
                adapter = PsychEvalAdapter(
                    revision="",
                    therapy_code=therapy_code,
                    source_name="PsychAgent bundled data",
                )
                files = sorted(
                    therapy_dir.glob("*.json"),
                    key=lambda item: int(item.stem),
                )
                for raw_path in files:
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    case = adapter.convert_case(
                        raw,
                        str(raw_path.relative_to(self.raw_data_dir.parent)),
                    )
                    self._index.setdefault(case.case_id, case)


def _upgrade_case_for_simulation(case: CounselingCase) -> CounselingCase:
    """Apply schema-v2 defaults to previously converted PsychEval records."""

    if case.therapy != "cbt":
        return case

    profile = case.profile
    cbt = profile.theory.get("cbt", {})
    situations = cbt.get("special_situations", [])
    upgraded: list[HiddenFact] = []
    for fact in profile.hidden_facts:
        try:
            index = int(fact.fact_id.rsplit(":", 1)[-1]) - 1
        except ValueError:
            index = -1
        if fact.category == "cbt_special_situation" and 0 <= index < len(situations):
            situation = situations[index]
            layers = _situation_layers(situation)
            activation_source = str(situation.get("event", fact.content))
            source_field = f"client_info.special_situations[{index}]"
            fallback = ["情境", "发生", "当时"]
            topic_key = f"cbt_situation_{index + 1}"
            readiness = 0.25
        else:
            layers = _disclosure_layers(fact.content)
            activation_source = fact.content
            source_field = (
                f"client_info.growth_experiences[{index}]"
                if index >= 0
                else fact.source_field
            )
            fallback = ["经历", "成长", "过去"]
            topic_key = f"growth_{index + 1}" if index >= 0 else fact.topic_key
            readiness = 0.35
        upgraded.append(
            fact.model_copy(
                update={
                    "content": layers[-1],
                    "activation_tags": _fact_activation_tags(
                        activation_source, fallback
                    ),
                    "topic_key": topic_key,
                    "disclosure_layers": layers,
                    "minimum_topic_readiness": (
                        fact.minimum_topic_readiness or readiness
                    ),
                    "source_field": fact.source_field or source_field,
                }
            )
        )
    source_info = {
        "main_problem": profile.main_problem,
        "core_demands": profile.core_demands,
        "static_traits": profile.static_traits.model_dump(mode="json"),
        "core_beliefs": cbt.get("core_beliefs", []),
        "special_situations": situations,
    }
    legacy_prior = profile.theory.get("_personality_source") == "deterministic_simulation_prior"
    theory = dict(profile.theory)
    if legacy_prior:
        theory["_personality_source"] = "unspecified_neutral_prior"
    migrated_profile = profile.model_copy(
        update={
            "hidden_facts": upgraded,
            "theory": theory,
            "personality": BigFive() if legacy_prior else profile.personality,
            "relational": (
                PsychEvalAdapter._relational_profile(source_info, upgraded)
                if profile.relational.confidence <= 0.45
                and not profile.relational.preferred_resistance_patterns
                and not profile.relational.therapy_triggers
                else profile.relational
            ),
            "initial_state": (
                PsychEvalAdapter._initial_state(source_info)
                if legacy_prior
                else profile.initial_state
            ),
        }
    )
    return case.model_copy(update={"profile": migrated_profile})


def _legacy_case(path: Path) -> CounselingCase:
    raw = json.loads(path.read_text(encoding="utf-8"))
    traits = raw["static_traits"]
    therapy = str(raw.get("therapy", "cbt"))
    formulation = raw.get("formulation_5ps") or {
        "presenting_problem": raw["main_problem"],
        "predisposing_factors": raw.get("growth_experiences", []),
        "precipitating_factors": raw.get("precipitating_factors", []),
        "perpetuating_factors": raw.get("perpetuating_factors", []),
        "protective_factors": (
            raw.get("protective_factors", [])
            or ["能够表达求助目标并主动参与咨询"]
        ),
        "source_fields": ["local_profile"],
    }
    profile = ClientProfile(
        client_id=raw["case_id"],
        static_traits=StaticTraits(
            name=traits.get("name", ""),
            age=traits.get("age", ""),
            gender=traits.get("gender", ""),
            occupation=traits.get("occupation", ""),
            educational_background=traits.get("education", ""),
            family_status=traits.get("family_status", ""),
            medical_history=traits.get("medical_history", ""),
            language_features=traits.get("language_style", ""),
        ),
        main_problem=raw["main_problem"],
        topic=raw["topic"],
        core_demands=raw["core_demands"],
        growth_experiences=raw.get("growth_experiences", []),
        formulation_5ps=FivePsFormulation.model_validate(formulation),
        theory={therapy: raw.get("therapy_parameters", {})},
        personality=BigFive.model_validate(raw["personality"]),
        initial_state=ClientState.model_validate(raw["initial_state"]),
        language_style=traits.get("language_style", ""),
        opening=raw["opening"],
        hidden_facts=[HiddenFact.model_validate(item) for item in raw["hidden_facts"]],
    )
    session_count = int(raw.get("session_count", 3))
    stage_objectives = raw.get("stage_objectives", {})

    def stage_for(index: int) -> SessionStage:
        if index <= min(2, session_count):
            return SessionStage.CONCEPTUALIZATION
        if index >= max(3, session_count - 1):
            return SessionStage.CONSOLIDATION
        return SessionStage.INTERVENTION

    plans = [
        SessionPlan(
            session_index=index,
            therapy=therapy,
            stage=stage_for(index),
            objectives=stage_objectives.get(
                stage_for(index).value,
                ["建立合作关系", "澄清困扰", "共同确定一个可观察的下一步"],
            ),
            forbidden_actions=["医学诊断", "使用未披露档案", "过早挑战"],
        )
        for index in range(1, session_count + 1)
    ]
    return CounselingCase(
        case_id=raw["case_id"],
        therapy=therapy,
        profile=profile,
        global_plan=plans,
        source="local_demo",
    )


def _map_stage(text: str) -> SessionStage:
    lowered = text.lower()
    if any(term in lowered for term in ["核心", "干预", "intervention"]):
        return SessionStage.INTERVENTION
    if any(term in lowered for term in ["巩固", "结束", "consolidation", "termination"]):
        return SessionStage.CONSOLIDATION
    return SessionStage.CONCEPTUALIZATION


def _global_content(global_plan: list[dict[str, Any]], session_index: int) -> dict[str, Any]:
    key = f"第{session_index}次_session_content"
    for stage in global_plan:
        content = stage.get("content", {})
        if key in content:
            return content[key]
    return {}


def _derived_meta_id(text: str) -> str:
    return "psycheval:meta:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _trigger_phrases(text: str) -> list[str]:
    parts = [
        part.strip()
        for part in text.replace("；", "，").replace("。", "，").split("，")
        if part.strip()
    ]
    return parts[:8]


def _intervention_type(name: str, description: str) -> str:
    text = name + description
    mapping = [
        ("共情", "empathic_reflection"),
        ("开放", "open_question"),
        ("澄清", "clarification"),
        ("苏格拉底", "socratic_question"),
        ("认知", "cognitive_restructuring"),
        ("作业", "behavioral_suggestion"),
        ("总结", "session_summary"),
        ("正常化", "normalization"),
        ("情绪", "emotion_labeling"),
    ]
    return next((value for term, value in mapping if term in text), "supportive_exploration")


def _case_split(case_id: str) -> str:
    value = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % 100
    if value < 70:
        return "train"
    if value < 85:
        return "validation"
    return "test"


def _files_digest(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
