from __future__ import annotations

from typing import Any

from ..domain.models import StrictModel
from ..domain import (
    ClientProfile,
    ClinicalSummary,
    ExtractedClientInfo,
    UnlockedClientInfo,
    Message,
    SessionChecklist,
    SessionPlan,
    StaticTraits,
)
from ..prompts import render_prompt


# Prompts mirror the PsychEval E.7/E.8/E.9 designs while staying compatible with
# the sandbox gateway contract (system prompt + JSON input payload).  They are
# Jinja2 templates under ``prompts/memory/``.

MEMORY_EXTRACTION_TEMPLATE = "memory/extraction_system.jinja2"
CLIENT_MERGE_TEMPLATE = "memory/merge_system.jinja2"
DIALOGUE_SUMMARY_TEMPLATE = "memory/summary_system.jinja2"


class _ClientInfoGet(StrictModel):
    client_info_get: ExtractedClientInfo


class _ClientInfoMerge(StrictModel):
    client_info_merge: UnlockedClientInfo


class _SessionSummaryWrapper(StrictModel):
    session_summary: ClinicalSummary


class MemoryExtractionAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def extract(
        self,
        dialogue: list[Message],
        theory_select: list[str],
        session_number: int,
    ) -> ExtractedClientInfo:
        extraction_payload = {
            "current_session_number": session_number,
            "current_session_theory": theory_select,
            "current_session_dialogue": _format_dialogue(dialogue),
        }
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=render_prompt(MEMORY_EXTRACTION_TEMPLATE, **extraction_payload),
            input_payload=extraction_payload,
            output_schema=_ClientInfoGet,
            temperature=0.1,
        )
        raw = _ClientInfoGet.model_validate(result).client_info_get
        raw.source_session = session_number
        # PsychEval language_features controls the private client actor; it is
        # never a counselor-memory field, even if an extractor tries to infer it.
        raw.static_traits.language_features = ""
        return raw


class ClientMergeAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def merge(
        self,
        history: UnlockedClientInfo,
        current: ExtractedClientInfo,
        global_profile: ClientProfile,
        therapy_select: list[str],
    ) -> UnlockedClientInfo:
        history_dump = history.model_dump(mode="json")
        merge_payload = {
            "history_profile": history_dump,
            "current_profile": current.model_dump(mode="json"),
            "global_profile": _profile_for_global(global_profile),
            "session_number": current.source_session,
            "theory_select": therapy_select,
        }
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=render_prompt(CLIENT_MERGE_TEMPLATE, **merge_payload),
            input_payload=merge_payload,
            output_schema=_ClientInfoMerge,
            temperature=0.1,
        )
        merged = _ClientInfoMerge.model_validate(result).client_info_merge
        merged = _prevent_global_backfill(merged, history, current)
        merged.facts = history.facts
        return merged


class DialogueSummaryAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def summarize(
        self,
        session_index: int,
        dialogue: list[Message],
        plan: SessionPlan,
        theory_select: list[str],
        session_checklist: SessionChecklist | None = None,
    ) -> ClinicalSummary:
        checklist = session_checklist or SessionChecklist()
        summary_payload = {
            "theory_select": theory_select,
            "session_index": session_index,
            "session_focus": {
                "stage_title": plan.stage.value,
                "objective": plan.objectives,
            },
            "session_dialogue": _format_dialogue(dialogue),
            "plan": plan.model_dump(mode="json"),
            "session_checklist": checklist.model_dump(mode="json"),
        }
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=render_prompt(DIALOGUE_SUMMARY_TEMPLATE, **summary_payload),
            input_payload=summary_payload,
            output_schema=_SessionSummaryWrapper,
            temperature=0.1,
        )
        summary = _SessionSummaryWrapper.model_validate(result).session_summary
        summary.session_index = session_index
        checklist_fields = (
            "completed_items",
            "important_information",
            "important_methods",
            "important_results",
            "pending_items",
        )
        return summary.model_copy(update={
            field: list(dict.fromkeys(
                getattr(checklist, field) + getattr(summary, field)
            ))
            for field in checklist_fields
        })


def _format_dialogue(dialogue: list[Message]) -> str:
    lines: list[str] = []
    for message in dialogue:
        label = "咨询师" if message.role == "counselor" else "来访者"
        lines.append(f"{label}：{message.content}")
    return "\n".join(lines)


def _profile_for_global(profile: ClientProfile) -> dict[str, Any]:
    traits = profile.static_traits.model_dump(mode="json")
    traits.pop("language_features", None)
    return {
        "client_id": profile.client_id,
        "static_traits": traits,
        "main_problem": profile.main_problem,
        "topic": profile.topic,
        "core_demands": profile.core_demands,
        "growth_experiences": profile.growth_experiences,
        "theory": profile.theory,
    }


def _prevent_global_backfill(
    merged: UnlockedClientInfo,
    history: UnlockedClientInfo,
    current: ExtractedClientInfo,
) -> UnlockedClientInfo:
    """Reject values that the merge model could only have copied from global truth."""

    updates: dict[str, Any] = {}
    for field in ("main_problem", "topic", "core_demands"):
        allowed = {str(getattr(history, field) or ""), str(getattr(current, field) or "")}
        if str(getattr(merged, field) or "") not in allowed:
            updates[field] = getattr(history, field) or getattr(current, field) or ""
    allowed_growth = list(dict.fromkeys(
        list(history.growth_experiences) + list(current.growth_experiences)
    ))
    updates["growth_experiences"] = [
        item for item in merged.growth_experiences if item in allowed_growth
    ]
    trait_updates = {}
    for field in StaticTraits.model_fields:
        if field == "language_features":
            trait_updates[field] = ""
            continue
        allowed = {
            str(getattr(history.static_traits, field) or ""),
            str(getattr(current.static_traits, field) or ""),
        }
        value = str(getattr(merged.static_traits, field) or "")
        trait_updates[field] = value if value in allowed else (
            getattr(history.static_traits, field)
            or getattr(current.static_traits, field)
            or ""
        )
    updates["static_traits"] = StaticTraits(**trait_updates)
    allowed_theory_keys = set(history.theory) | set(current.theory)
    updates["theory"] = {
        key: value for key, value in merged.theory.items() if key in allowed_theory_keys
    }
    return merged.model_copy(update=updates)
