from __future__ import annotations

from ..domain import CounselingCase, SessionEvaluationReport, SessionRecord
from .psycheval_supervisor import PsychEvalSupervisor


class SessionSupervisorEvaluator(PsychEvalSupervisor):
    """Per-session LLM-as-judge that reuses the PsychEval instruments.

    This is the in-loop, per-session reward/audit scorer for RFT candidate
    ranking (PsychAgent §3.3). It shares the instrument registry and scoring of
    :class:`PsychEvalSupervisor` (the post-trajectory holistic supervisor), so
    per-session RFT reward and the final holistic score use the same
    psychometric instruments. It never plans the next session.
    """

    async def evaluate(
        self, session: SessionRecord, case: CounselingCase
    ) -> SessionEvaluationReport:
        return await super().evaluate_session(session, case)


__all__ = ["SessionSupervisorEvaluator"]
