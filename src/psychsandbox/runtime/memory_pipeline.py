from __future__ import annotations

from typing import Any

from ..domain.models import StrictModel
from ..domain import (
    ClinicalSummary,
    ExtractedClientInfo,
    UnlockedClientInfo,
    Message,
    SessionChecklist,
    SessionPlan,
    StaticTraits,
)
from ..prompts import render_prompt
from .evidence import is_grounded, prune_leaves, string_leaves


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
            "dialogue": [message.model_dump(mode="json") for message in dialogue],
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
        allowed = []
        leaves = set(string_leaves(raw.model_dump(exclude={"field_evidence", "source_session"})))
        for item in raw.field_evidence:
            if ((item.field_path, item.value) in leaves
                    and is_grounded(item.evidence, dialogue, role="client")
                    and (item.kind == "fact" or item.field_path.startswith("theory."))):
                item.source_session = session_number
                allowed.append(item)
        accepted = {(item.field_path, item.value) for item in allowed}
        values = prune_leaves(raw.model_dump(exclude={"field_evidence", "source_session"}), accepted)
        return ExtractedClientInfo.model_validate({
            **values, "source_session": session_number, "field_evidence": allowed,
        })


class ClientMergeAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def merge(
        self,
        history: UnlockedClientInfo,
        current: ExtractedClientInfo,
        therapy_select: list[str],
    ) -> UnlockedClientInfo:
        history_dump = history.model_dump(mode="json")
        merge_payload = {
            "history_profile": history_dump,
            "current_profile": current.model_dump(mode="json"),
            "client_id": history.client_id,
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
        merged.client_id = history.client_id
        merged.updated_session = current.source_session
        merged.facts = list(history.facts)
        leaves = set(string_leaves(merged.model_dump(exclude={"field_evidence", "facts"})))
        merged.field_evidence = [
            item for item in history.field_evidence + current.field_evidence
            if (item.field_path, item.value) in leaves
        ]
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
        *,
        memory_items: dict[str, Any] | None = None,
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
            "dialogue": [message.model_dump(mode="json") for message in dialogue],
            "plan": plan.model_dump(mode="json"),
            "session_checklist": checklist.model_dump(mode="json"),
            "memory_items": memory_items or {},
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
    allowed_theory = set(string_leaves(history.theory)) | set(string_leaves(current.theory))
    updates["theory"] = _merge_known_tree(
        history.theory, prune_leaves(merged.theory, allowed_theory)
    )
    return merged.model_copy(update=updates)


def _merge_known_tree(history: Any, current: Any) -> Any:
    """Retain omitted historical leaves while merging authorized new values."""
    if isinstance(history, dict) and isinstance(current, dict):
        return {key: _merge_known_tree(history.get(key), current[key]) if key in current else value
                for key, value in history.items()} | {
                    key: value for key, value in current.items() if key not in history
                }
    if isinstance(history, list) and isinstance(current, list):
        return history + [value for value in current if value not in history]
    return current if current is not None else history
