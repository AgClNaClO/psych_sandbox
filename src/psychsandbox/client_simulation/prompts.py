"""Template-based prompts for the two-stage simulated-client pipeline.

These are Jinja2 template paths under ``prompts/simclient/``.  The templates are
rendered at each call site with the validated, Pydantic-typed payload
(see ``agents/client.py`` and ``prompt_pipeline.py``).
"""

from __future__ import annotations

CLIENT_PROMPT_VERSION = "psycheval_patientact_v4"

# Jinja2 template paths (rooted at the repo ``prompts/`` directory).
CLIENT_PLANNER_TEMPLATE = "simclient/planner_system.jinja2"
CLIENT_UTTERANCE_TEMPLATE = "simclient/utterance_system.jinja2"

__all__ = [
    "CLIENT_PLANNER_TEMPLATE",
    "CLIENT_PROMPT_VERSION",
    "CLIENT_UTTERANCE_TEMPLATE",
]
