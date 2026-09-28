"""Bounded, layered counselor read view over the four-field ``SessionMemory``.

The stored memory stays append-only and auditable; this module decides what the
counselor actually reads each turn. Both modes drop management fields
(``migration_warnings``) and the audit-only recap logs (``safety_notes`` and
``relationship_events``), which are rule-gate reasons and simulator trust deltas
rather than clinical material.

``full`` mode keeps the historical behaviour (every remaining field).
``recap_window`` mode injects the current focus plus the newest
``recent_sessions`` recaps and one archive line per older session, and always
stays inside ``max_chars``, so a 100-session course cannot grow the per-turn
prompt without bound. The switch mirrors PsychAgent's ``memory_mode`` so both
strategies can be compared without code changes.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain import MemoryViewConfig, SessionMemory

BUDGET_KEY = "view_budget"

#: Audit-only recap logs never enter the model-facing view.
AUDIT_ONLY_RECAP_KEYS = ("safety_notes", "relationship_events")

#: Head-room for the ``view_budget`` block itself.
_BUDGET_SLACK = 64


class MemoryViewBuilder:
    """Assemble the counselor-visible memory for one turn."""

    def __init__(self, config: MemoryViewConfig | None = None) -> None:
        self.config = config or MemoryViewConfig()

    def build(self, memory: SessionMemory) -> dict:
        view = self._dump(memory)
        if self.config.mode == "full":
            return view
        return self._windowed(view)

    @staticmethod
    def _dump(memory: SessionMemory) -> dict:
        """Full memory minus management fields, audit-only logs and language style."""

        view = memory.model_dump(mode="json", exclude={"migration_warnings": True})
        # ``completed_sessions`` is derived from the recaps, so re-attach it.
        view["completed_sessions"] = len(view.get("session_recaps", []))
        traits = view.get("known_background", {}).get("static_traits")
        if isinstance(traits, dict):
            # The private expression style drives the simulated client only.
            traits.pop("language_features", None)
        for recap in view.get("session_recaps", []):
            for key in AUDIT_ONLY_RECAP_KEYS:
                recap.pop(key, None)
        return view

    # ------------------------------------------------------------------ window
    def _windowed(self, view: dict) -> dict:
        config = self.config
        recaps = list(view.get("session_recaps", []))
        recent = recaps[-config.recent_sessions:]
        archive = [self._archive_line(item) for item in recaps[: len(recaps) - len(recent)]]
        records = list(view.get("checklist", {}).get("per_session", []))
        focus, dropped_focus = self._focus(view, recent)
        dropped_sessions = 0
        dropped_archive = 0
        while True:
            window = self._compose(
                view, recent, records[-len(recent):] if recent else [], archive, focus,
                dropped_sessions, dropped_archive, dropped_focus,
            )
            if self._size(window) + _BUDGET_SLACK <= config.max_chars:
                window[BUDGET_KEY]["chars"] = self._payload_size(window)
                return window
            if archive:
                archive = archive[1:]
                dropped_archive += 1
            elif len(recent) > 1:
                recent = recent[1:]
                dropped_sessions += 1
            else:
                window[BUDGET_KEY]["chars"] = self._payload_size(window)
                window[BUDGET_KEY]["truncated"] = True
                return window
    def _focus(self, view: dict, recent: list[dict]) -> tuple[dict, int]:
        config = self.config
        homework = [
            item for item in view.get("last_homework", []) if item.get("status") == "open"
        ]
        open_items = list(view.get("checklist", {}).get("open_items", []))
        pending = list(view.get("checklist", {}).get("pending_verification", []))
        dropped = (
            max(0, len(homework) - config.focus_items_max)
            + max(0, len(open_items) - config.focus_items_max)
            + max(0, len(pending) - config.focus_items_max)
        )
        focus = {
            "last_homework": homework[: config.focus_items_max],
            "open_items": open_items[: config.focus_items_max],
            "pending_verification": pending[: config.focus_items_max],
            "recent_risk": next(
                (item.get("risk") for item in reversed(recent) if item.get("risk")), None
            ),
            "last_session": self._last_session(recent),
        }
        return self._clip_tree(focus), dropped

    @staticmethod
    def _last_session(recent: list[dict]) -> dict | None:
        if not recent:
            return None
        newest = recent[-1]
        return {
            "session_index": newest.get("session_index"),
            "clinical_summary": newest.get("clinical_summary", ""),
            "client_closing": newest.get("client_closing", ""),
            "homework": list(newest.get("homework", [])),
        }

    def _archive_line(self, recap: dict) -> str:
        text = str(recap.get("clinical_summary") or recap.get("summary") or "").strip()
        text = " ".join(text.split())[: self.config.archive_line_chars]
        return f"S{recap.get('session_index')}: {text}"

    def _compose(
        self,
        view: dict,
        recent: list[dict],
        records: list[dict],
        archive: list[str],
        focus: dict,
        dropped_sessions: int,
        dropped_archive: int,
        dropped_focus: int,
    ) -> dict:
        return {
            BUDGET_KEY: {
                "mode": "recap_window",
                "limit": self.config.max_chars,
                "chars": 0,
                "truncated": bool(dropped_sessions or dropped_archive or dropped_focus),
                "dropped_sessions": dropped_sessions,
                "dropped_archive_lines": dropped_archive,
                "dropped_focus_items": dropped_focus,
            },
            "case_id": view.get("case_id", ""),
            "completed_sessions": view.get("completed_sessions", 0),
            "known_background": view.get("known_background", {}),
            "current_focus": focus,
            "recent_session_recaps": [self._clip_tree(item) for item in recent],
            "recent_checklist_records": [self._clip_tree(item) for item in records],
            "earlier_session_archive": list(archive),
        }

    # ----------------------------------------------------------------- helpers
    def _clip(self, value: Any) -> Any:
        if isinstance(value, str):
            return value[: self.config.per_field_chars]
        return value

    def _clip_tree(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._clip_tree(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._clip_tree(item) for item in value]
        return self._clip(value)

    @staticmethod
    def _size(window: dict) -> int:
        return len(json.dumps(window, ensure_ascii=False))

    @staticmethod
    def _payload_size(window: dict) -> int:
        payload = {key: item for key, item in window.items() if key != BUDGET_KEY}
        return len(json.dumps(payload, ensure_ascii=False))


__all__ = ["BUDGET_KEY", "MemoryViewBuilder"]

