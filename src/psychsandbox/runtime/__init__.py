from .disclosure import DisclosureGate
from .dialogue_guard import BoundarySignal, DialogueLoopGuard
from .leakage import PrematureDisclosureGuard
from .planning import PlanBuilder
from .safety import SafetyStateMachine
from .state import StateUpdater
from .storage import SQLiteStore

__all__ = [
    "CounselingSandbox",
    "BoundarySignal",
    "DisclosureGate",
    "DialogueLoopGuard",
    "PlanBuilder",
    "PrematureDisclosureGuard",
    "SafetyStateMachine",
    "SQLiteStore",
    "StateUpdater",
]


def __getattr__(name: str):
    if name == "CounselingSandbox":
        from .orchestrator import CounselingSandbox

        return CounselingSandbox
    raise AttributeError(name)
