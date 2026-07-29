from __future__ import annotations

from dataclasses import dataclass

from ..domain import SessionStage


@dataclass(frozen=True, slots=True)
class TherapyProfile:
    """Phase-one therapy adapter metadata.

    This intentionally keeps the adapter declarative. Skill retrieval and
    evaluation remain independent services and consume the same therapy ID.
    """

    therapy_id: str
    display_name: str
    counselor_role: str
    conceptualization_focus: str
    therapy_metric: str
    stage_goals: dict[SessionStage, tuple[str, ...]]

    def system_prompt(self) -> str:
        return (
            f"你是研究沙盒中的{self.display_name}咨询师智能体，并非真实医疗服务。\n"
            f"本流派的概念化焦点是：{self.conceptualization_focus}。\n"
            "只能使用 unlocked_profile、session_memory、当前对话和候选技能中的信息；\n"
            "不得猜测或暗示未披露档案，不得诊断、提供药物剂量或承诺疗效。\n"
            "高风险时停止普通咨询。输出严格 JSON，只给简短、可审计的结构化判断。"
        )


CBT = TherapyProfile(
    therapy_id="cbt",
    display_name="认知行为取向（CBT）",
    counselor_role="CBT counselor",
    conceptualization_focus="自动思维、条件假设、核心信念及其与情绪和行为的循环",
    therapy_metric="ctrs_lite",
    stage_goals={
        SessionStage.CONCEPTUALIZATION: (
            "建立合作关系",
            "形成初步认知行为概念化",
            "共同确认可观察目标",
        ),
        SessionStage.INTERVENTION: (
            "识别并检验关键自动思维",
            "设计低风险的行为尝试",
        ),
        SessionStage.CONSOLIDATION: (
            "总结已掌握的认知与行为技能",
            "形成复发预防计划",
        ),
    },
)


HUMANISTIC_EXISTENTIAL = TherapyProfile(
    therapy_id="humanistic_existential",
    display_name="人本—存在取向",
    counselor_role="humanistic-existential counselor",
    conceptualization_focus="主观体验、一致性、自我接纳、选择与意义",
    therapy_metric="tes_lite",
    stage_goals={
        SessionStage.CONCEPTUALIZATION: (
            "建立真诚、安全且尊重自主性的关系",
            "澄清来访者此刻最重要的主观体验",
        ),
        SessionStage.INTERVENTION: (
            "加深情绪与需要的觉察",
            "探索选择、责任和个人意义",
        ),
        SessionStage.CONSOLIDATION: (
            "整合对自我和经验的新理解",
            "确认可由来访者自主选择的下一步",
        ),
    },
)


_PROFILES = {
    CBT.therapy_id: CBT,
    HUMANISTIC_EXISTENTIAL.therapy_id: HUMANISTIC_EXISTENTIAL,
}


def get_therapy_profile(therapy_id: str) -> TherapyProfile:
    try:
        return _PROFILES[therapy_id]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROFILES))
        raise ValueError(
            f"Unsupported therapy {therapy_id!r}; supported: {supported}"
        ) from exc


def list_therapy_profiles() -> list[TherapyProfile]:
    return list(_PROFILES.values())
