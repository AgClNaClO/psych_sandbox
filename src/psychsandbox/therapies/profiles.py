from __future__ import annotations

from dataclasses import dataclass

from ..domain import SessionStage


@dataclass(frozen=True, slots=True)
class TherapyProfile:
    """Phase-one therapy adapter metadata.

    This intentionally keeps the adapter declarative. Skill catalog access and
    evaluation remain independent modules and consume the same therapy ID.
    """

    therapy_id: str
    display_name: str
    counselor_role: str
    conceptualization_focus: str
    therapy_metric: str
    stage_goals: dict[SessionStage, tuple[str, ...]]

    def system_prompt(self) -> str:
        return (
            f'你是研究沙盒中的{self.display_name}咨询师智能体，并非真实医疗服务。\n'
            f'本流派的概念化焦点是：{self.conceptualization_focus}。\n'
            '只能使用 unlocked_client_info、session_memory、当前对话和程序观察结果中的信息；\n'
            '不得猜测或暗示未披露档案，不得诊断、提供药物剂量或承诺疗效。\n'
            '高风险时停止普通咨询。对来访者说的话必须使用自然、口语化、简洁的中文：\n'
            '- 用简短直接的句子，不要长篇大论\n'
            '- 避免任何专业术语（如\u201c认知重构\u201d\u201c行为激活\u201d等）\n'
            '- 不要用\u201c我注意到\u201d\u201c我观察到\u201d等元认知表述\n'
            '- 不要复述来访者的话，而是自然回应\n'
            '- 每次1-3句即可，给来访者留出表达空间。'
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


BEHAVIORAL = TherapyProfile(
    therapy_id="behavioral",
    display_name="行为取向（BT）",
    counselor_role="behavioral counselor",
    conceptualization_focus="可观察的目标行为、前因、功能、后果以及维持行为的强化循环",
    therapy_metric="miti_lite",
    stage_goals={
        SessionStage.CONCEPTUALIZATION: (
            "建立合作关系并操作化目标行为",
            "识别行为发生的前因、功能和后果",
        ),
        SessionStage.INTERVENTION: (
            "设计可分级实施的行为练习",
            "调整回避与强化循环并追踪结果",
        ),
        SessionStage.CONSOLIDATION: (
            "巩固有效行为和自我监测方法",
            "形成维持与复发预防计划",
        ),
    },
)


PSYCHODYNAMIC = TherapyProfile(
    therapy_id="psychodynamic",
    display_name="心理动力学取向（PDT）",
    counselor_role="psychodynamic counselor",
    conceptualization_focus="核心冲突、客体关系、情感、防御机制和关系中的重复模式",
    therapy_metric="psc_lite",
    stage_goals={
        SessionStage.CONCEPTUALIZATION: (
            "建立稳定的治疗框架和联盟",
            "识别核心冲突、关系模式与主要防御",
        ),
        SessionStage.INTERVENTION: (
            "在可承受范围内深化情感体验",
            "探索当下关系中的重复模式与防御功能",
        ),
        SessionStage.CONSOLIDATION: (
            "整合对冲突和关系模式的新理解",
            "准备处理分离、结束与模式复现",
        ),
    },
)


POSTMODERN = TherapyProfile(
    therapy_id="postmodern",
    display_name="后现代取向（PMT）",
    counselor_role="postmodern counselor",
    conceptualization_focus="问题外化、例外事件、优势资源、偏好故事与来访者定义的改变",
    therapy_metric="eft_tfs_lite",
    stage_goals={
        SessionStage.CONCEPTUALIZATION: (
            "建立平等合作的关系",
            "澄清来访者希望改变的方向并将人与问题分开",
        ),
        SessionStage.INTERVENTION: (
            "寻找例外、资源和已经发生的微小改变",
            "扩展更有力量的偏好故事与可行下一步",
        ),
        SessionStage.CONSOLIDATION: (
            "见证并巩固来访者的能力和新叙事",
            "形成由来访者定义的维持方案",
        ),
    },
)


_PROFILES = {
    BEHAVIORAL.therapy_id: BEHAVIORAL,
    CBT.therapy_id: CBT,
    HUMANISTIC_EXISTENTIAL.therapy_id: HUMANISTIC_EXISTENTIAL,
    PSYCHODYNAMIC.therapy_id: PSYCHODYNAMIC,
    POSTMODERN.therapy_id: POSTMODERN,
}


_ALIASES = {
    "bt": "behavioral",
    "cbt": "cbt",
    "het": "humanistic_existential",
    "pdt": "psychodynamic",
    "pmt": "postmodern",
    "behavioral": "behavioral",
    "humanistic_existential": "humanistic_existential",
    "psychodynamic": "psychodynamic",
    "postmodern": "postmodern",
}


def normalize_therapy_id(therapy_id: str) -> str:
    normalized = str(therapy_id).strip().lower().replace("-", "_")
    try:
        return _ALIASES[normalized]
    except KeyError as exc:
        supported = ", ".join(("bt", "cbt", "het", "pdt", "pmt"))
        raise ValueError(
            f"Unsupported therapy {therapy_id!r}; supported codes: {supported}"
        ) from exc


def get_therapy_profile(therapy_id: str) -> TherapyProfile:
    therapy_id = normalize_therapy_id(therapy_id)
    try:
        return _PROFILES[therapy_id]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROFILES))
        raise ValueError(
            f"Unsupported therapy {therapy_id!r}; supported: {supported}"
        ) from exc


def list_therapy_profiles() -> list[TherapyProfile]:
    return list(_PROFILES.values())
