from .client_realism import ClientSimulationEvaluator
from .longitudinal import LongitudinalEvaluator
from .psycheval_supervisor import PsychEvalSupervisor
from .rule_session import RuleSessionEvaluator

__all__ = [
    "ClientSimulationEvaluator",
    "LongitudinalEvaluator",
    "PsychEvalSupervisor",
    "RuleSessionEvaluator",
    "SupervisorAgent",
]


def __getattr__(name: str):
    if name == "SupervisorAgent":
        from ..agents.supervisor import SupervisorAgent

        return SupervisorAgent
    raise AttributeError(name)
