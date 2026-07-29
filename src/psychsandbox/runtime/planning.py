from __future__ import annotations

from ..domain import LongitudinalReport, SessionPlan, SessionStage, SupervisorReport


class FeedbackPlanBuilder:
    """Build the next plan from source material plus auditable supervision."""

    _ORDER = (
        SessionStage.CONCEPTUALIZATION,
        SessionStage.INTERVENTION,
        SessionStage.CONSOLIDATION,
    )

    def build(
        self,
        current: SessionPlan,
        baseline_next: SessionPlan,
        supervisor: SupervisorReport | None,
        longitudinal: LongitudinalReport,
    ) -> SessionPlan:
        stage = self._target_stage(current.stage, longitudinal.stage_action)
        objectives = list(baseline_next.objectives)
        feedback = supervisor.feedback if supervisor else []
        objectives.extend(f"督导修复：{item}" for item in feedback[:2])
        if longitudinal.stage_action == "hold":
            objectives.insert(0, "暂停普通干预，优先完成安全复核与现实支持连接")
        elif longitudinal.stage_action == "regress":
            objectives.insert(0, "返回概念化，补充信息并修订维持机制")
        elif longitudinal.stage_action == "advance":
            objectives.insert(0, "基于上一会谈达成情况推进到下一治疗阶段")
        elif longitudinal.stage_action == "close":
            objectives = ["确认终止条件、复发预案与支持资源"]
        return baseline_next.model_copy(
            update={
                "therapy": current.therapy,
                "stage": stage,
                "objectives": list(dict.fromkeys(objectives)),
            }
        )

    def _target_stage(self, current: SessionStage, action: str) -> SessionStage:
        index = self._ORDER.index(current)
        if action == "advance":
            return self._ORDER[min(index + 1, len(self._ORDER) - 1)]
        if action == "regress":
            return self._ORDER[max(index - 1, 0)]
        return current
