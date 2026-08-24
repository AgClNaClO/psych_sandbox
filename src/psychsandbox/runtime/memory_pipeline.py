from __future__ import annotations

from typing import Any

from ..domain.models import StrictModel
from ..domain import (
    ClientProfile,
    ClinicalSummary,
    ExtractedClientInfo,
    MergedClientProfile,
    Message,
    SessionPlan,
    StaticTraits,
)
from ..prompts import load_prompt

# Prompts mirror the PsychEval E.7/E.8/E.9 designs while staying compatible with
# the sandbox gateway contract (system prompt + JSON input payload).

MEMORY_EXTRACTION_SYSTEM = load_prompt("memory/extraction_system.txt")


CLIENT_MERGE_SYSTEM = load_prompt("memory/merge_system.txt")


DIALOGUE_SUMMARY_SYSTEM = load_prompt("memory/summary_system.txt")


class _ClientInfoGet(StrictModel):
    client_info_get: ExtractedClientInfo


class _ClientInfoMerge(StrictModel):
    client_info_merge: MergedClientProfile


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
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=MEMORY_EXTRACTION_SYSTEM,
            input_payload={
                "current_session_number": session_number,
                "current_session_theory": theory_select,
                "current_session_dialogue": _format_dialogue(dialogue),
            },
            output_schema=_ClientInfoGet,
            temperature=0.1,
        )
        raw = _ClientInfoGet.model_validate(result).client_info_get
        raw.source_session = session_number
        return raw


class ClientMergeAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def merge(
        self,
        history: MergedClientProfile | None,
        current: ExtractedClientInfo,
        global_profile: ClientProfile,
        therapy_select: list[str],
    ) -> MergedClientProfile:
        history_dump = (
            history.model_dump(mode="json")
            if history
            else _empty_merged(global_profile.client_id, current.source_session)
        )
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=CLIENT_MERGE_SYSTEM,
            input_payload={
                "history_profile": history_dump,
                "current_profile": current.model_dump(mode="json"),
                "global_profile": _profile_for_global(global_profile),
                "session_number": current.source_session,
                "theory_select": therapy_select,
            },
            output_schema=_ClientInfoMerge,
            temperature=0.1,
        )
        return _ClientInfoMerge.model_validate(result).client_info_merge


class DialogueSummaryAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def summarize(
        self,
        session_index: int,
        dialogue: list[Message],
        plan: SessionPlan,
        theory_select: list[str],
    ) -> ClinicalSummary:
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=DIALOGUE_SUMMARY_SYSTEM,
            input_payload={
                "theory_select": theory_select,
                "session_index": session_index,
                "session_focus": {
                    "stage_title": plan.stage.value,
                    "objective": plan.objectives,
                },
                "session_dialogue": _format_dialogue(dialogue),
                "plan": plan.model_dump(mode="json"),
            },
            output_schema=_SessionSummaryWrapper,
            temperature=0.1,
        )
        summary = _SessionSummaryWrapper.model_validate(result).session_summary
        summary.session_index = session_index
        return summary


def _format_dialogue(dialogue: list[Message]) -> str:
    lines: list[str] = []
    for message in dialogue:
        label = "咨询师" if message.role == "counselor" else "来访者"
        lines.append(f"{label}：{message.content}")
    return "\n".join(lines)


def _empty_merged(client_id: str, updated_session: int) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "static_traits": StaticTraits().model_dump(mode="json"),
        "main_problem": "",
        "topic": "",
        "core_demands": "",
        "growth_experiences": [],
        "theory": {},
        "updated_session": updated_session,
    }


def _profile_for_global(profile: ClientProfile) -> dict[str, Any]:
    return {
        "client_id": profile.client_id,
        "static_traits": profile.static_traits.model_dump(mode="json"),
        "main_problem": profile.main_problem,
        "topic": profile.topic,
        "core_demands": profile.core_demands,
        "growth_experiences": profile.growth_experiences,
        "theory": profile.theory,
    }