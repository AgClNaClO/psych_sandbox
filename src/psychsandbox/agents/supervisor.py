from __future__ import annotations

from ..evaluation.client_realism import ClientSimulationEvaluator
from ..evaluation.psycheval_supervisor import PsychEvalSupervisor
from ..evaluation.rule_session import RuleSessionEvaluator


class SupervisorAgent(RuleSessionEvaluator):
    """Deterministic per-session safety/leakage rule checks.

    This is the in-loop session guard only. Longitudinal clinical evaluation
    is delegated to :class:`PsychEvalSupervisor`, which runs once after all
    sessions complete and applies the official PsychEval rating instruments
    (Counselor-Level and Client-Level). The rule evaluator does not plan the
    next session; planning is handled by the progress-driven ``PlanBuilder``.
    """


__all__ = [
    "ClientSimulationEvaluator",
    "PsychEvalSupervisor",
    "SupervisorAgent",
]