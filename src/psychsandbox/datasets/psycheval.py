from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

from ..domain import (
    AtomicSkill,
    BigFive,
    ClientProfile,
    ClientState,
    CounselingCase,
    FivePsFormulation,
    HiddenFact,
    MetaSkill,
    SessionPlan,
    SessionStage,
    StaticTraits,
)
from ..skills import SkillRegistry


PSYCHEVAL_REPOSITORY = "https://github.com/ECNU-ICALK/PsychEval.git"
PSYCHEVAL_REVISION = "e04df535749e5bca76fcc45d9a85f3f46a082d91"


def fetch_psycheval(destination: Path, revision: str = PSYCHEVAL_REVISION) -> Path:
    """Fetch only CBT data and evaluation prompts from the official repository."""

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
        ["git", "-C", str(destination), "sparse-checkout", "set", "data/cbt", "eval/prompts_cn"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(destination), "checkout", "--detach", revision],
        check=True,
    )
    return destination


class PsychEvalAdapter:
    def __init__(self, revision: str = PSYCHEVAL_REVISION):
        self.revision = revision

    def convert_case(self, raw: dict[str, Any], source_path: str = "") -> CounselingCase:
        client_id = str(raw["client_id"])
        case_id = f"psycheval-cbt-{client_id.zfill(3)}"
        info = raw["client_info"]
        static = info.get("static_traits", {})
        hidden = self._hidden_facts(case_id, info)
        personality = self._deterministic_personality(case_id)
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
            formulation_5ps=self._five_ps(info),
            theory={
                "cbt": {
                    "core_beliefs": info.get("core_beliefs", []),
                    "special_situations": info.get("special_situations", []),
                },
                "_personality_source": "deterministic_simulation_prior",
                "_source_path": source_path,
            },
            personality=personality,
            initial_state=ClientState(
                valence=0.3,
                arousal=0.68,
                distress=0.7,
                trust=0.22,
                resistance=0.45,
                hope=0.35,
            ),
            language_style=str(static.get("language_features", "")),
            opening=opening,
            hidden_facts=hidden,
        )
        plans = self._session_plans(raw)
        return CounselingCase(
            case_id=case_id,
            therapy="cbt",
            profile=profile,
            global_plan=plans,
            reference_sessions=reference_sessions,
            source="PsychEval",
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
                            therapy="cbt",
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
                            therapy="cbt",
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
                    therapy="cbt",
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
    def _five_ps(info: dict[str, Any]) -> FivePsFormulation:
        """Derive an auditable 5Ps scaffold from fields PsychEval actually ships."""

        growth = [
            str(item).strip()
            for item in info.get("growth_experiences", [])
            if str(item).strip()
        ]
        situations = [
            item for item in info.get("special_situations", [])
            if isinstance(item, dict)
        ]
        events = [
            str(item.get("event", "")).strip()
            for item in situations
            if str(item.get("event", "")).strip()
        ]
        perpetuating: list[str] = []
        for item in situations:
            for key, label in (
                ("automatic_thoughts", "自动思维"),
                ("conditional_assumptions", "条件假设"),
                ("compensatory_strategies", "应对/维持策略"),
            ):
                value = str(item.get(key, "")).strip()
                if value:
                    perpetuating.append(f"{label}：{value}")
        protective = []
        if str(info.get("core_demands", "")).strip():
            protective.append("能够表达求助目标并主动参与咨询")
        family = str(info.get("static_traits", {}).get("family_status", "")).strip()
        if family:
            protective.append(f"可进一步核实的家庭/支持资源：{family}")
        return FivePsFormulation(
            presenting_problem=str(info.get("main_problem", "")).strip(),
            predisposing_factors=growth,
            precipitating_factors=events[:3],
            perpetuating_factors=list(dict.fromkeys(perpetuating))[:8],
            protective_factors=protective,
            source_fields=[
                "client_info.main_problem",
                "client_info.growth_experiences",
                "client_info.special_situations",
                "client_info.core_demands",
                "client_info.static_traits.family_status",
            ],
        )

    @staticmethod
    def _hidden_facts(case_id: str, info: dict[str, Any]) -> list[HiddenFact]:
        facts: list[HiddenFact] = []
        for index, content in enumerate(info.get("growth_experiences", []), start=1):
            facts.append(
                HiddenFact(
                    fact_id=f"{case_id}:growth:{index}",
                    content=str(content),
                    category="growth_experience",
                    minimum_trust=min(0.75, 0.3 + index * 0.08),
                    required_topics=["经历", "家庭", "成长", "过去", "影响"],
                    sensitivity=min(0.9, 0.45 + index * 0.08),
                    activation_tags=["经历", "家庭", "成长", "小时候", "过去", "影响"],
                    generates_discomfort=True,
                )
            )
        for index, situation in enumerate(info.get("special_situations", []), start=1):
            content = str(situation.get("event", "")).strip()
            if content:
                facts.append(
                    HiddenFact(
                        fact_id=f"{case_id}:situation:{index}",
                        content=content,
                        category="cbt_special_situation",
                        minimum_trust=min(0.7, 0.28 + index * 0.06),
                        required_topics=["情境", "发生", "当时", "想法", "困扰"],
                        sensitivity=min(0.85, 0.4 + index * 0.06),
                        activation_tags=["情境", "发生", "当时", "想法", "困扰"],
                        generates_discomfort=index >= 3,
                    )
                )
        return facts

    @staticmethod
    def _opening(sessions: list[dict[str, Any]], fallback: str) -> str:
        if sessions:
            for item in sessions[0].get("session_dialogue", []):
                if str(item.get("role", "")).lower() == "client":
                    text = str(item.get("text", "")).strip()
                    if len(text) >= 8:
                        return text
        return fallback or "最近有些事情让我很困扰，我想找个人谈一谈。"

    @staticmethod
    def _deterministic_personality(case_id: str) -> BigFive:
        digest = hashlib.sha256(case_id.encode()).digest()
        values = [0.3 + byte / 255 * 0.4 for byte in digest[:5]]
        return BigFive(
            openness=values[0],
            conscientiousness=values[1],
            extraversion=values[2],
            agreeableness=values[3],
            neuroticism=values[4],
        )


def convert_psycheval(
    source_dir: Path,
    output_dir: Path,
    *,
    therapy: str = "cbt",
    revision: str = PSYCHEVAL_REVISION,
) -> dict[str, Any]:
    if therapy != "cbt":
        raise ValueError("Phase 1 converter currently supports therapy='cbt' only")
    source = source_dir / "data" / therapy
    files = sorted(source.glob("*.json"), key=lambda path: int(path.stem))
    if not files:
        raise FileNotFoundError(f"No PsychEval files found under {source}")
    adapter = PsychEvalAdapter(revision)
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
    def __init__(self, processed_dir: Path, legacy_profile_dir: Path | None = None):
        self.processed_dir = processed_dir
        self.legacy_profile_dir = legacy_profile_dir
        self._index: dict[str, CounselingCase] | None = None

    def list(self, therapy: str | None = None) -> list[CounselingCase]:
        self._ensure_index()
        assert self._index is not None
        return sorted(
            [
                item
                for item in self._index.values()
                if therapy is None or item.therapy == therapy
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
                        case = CounselingCase.model_validate_json(line)
                        self._index[case.case_id] = case


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
