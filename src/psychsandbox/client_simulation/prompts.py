"""File-driven prompts for the two-stage simulated-client pipeline."""

from __future__ import annotations

from ..prompts import load_prompt


CLIENT_PROMPT_VERSION = "psycheval_patientact_v4"


CLIENT_PLANNER_SYSTEM = load_prompt("simclient/planner_system.txt")


CLIENT_UTTERANCE_SYSTEM = load_prompt("simclient/utterance_system.txt")


__all__ = [
    "CLIENT_PLANNER_SYSTEM",
    "CLIENT_PROMPT_VERSION",
    "CLIENT_UTTERANCE_SYSTEM",
]
