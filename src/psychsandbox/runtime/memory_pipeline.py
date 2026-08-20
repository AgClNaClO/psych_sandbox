from __future__ import annotations

from typing import Any

from ..domain.models import StrictModel
from ..domain import (
    ClientProfile,
    ClinicalSummary,
    ExtractedClientInfo,
    MergedClientProfile,
    Message,
    SessionPlan,
    StaticTraits,
)

# Prompts mirror the PsychEval E.7/E.8/E.9 designs while staying compatible with
# the sandbox gateway contract (system prompt + JSON input payload).

MEMORY_EXTRACTION_SYSTEM = """你是专业的心理咨询督导及数据结构化专家。
你的任务是：从【当前Session对话】中提取来访者画像信息，并进行格式标准化与去重。
绝对禁止补充对话中未提及的信息。

强约束过滤器：
1. 现实-治疗隔离墙：只提取来访者在现实生活中、咨询室外独立发生的客观事实；
   拦截咨询师布置的家庭作业、治疗计划、现场互动或因咨询师建议产生的行为。
2. 事实-愿望隔离墙：只提取已发生（过去时）或正在持续（一般现在时）的状态；
   拦截未来的计划、愿望与假设性讨论。

字段提取规则：
- static_traits：提取本轮对话提及的现实背景（姓名、年龄、性别、职业、学历、婚姻、
  家庭现状、既往病史）。未提及则填空字符串。
- main_problem / topic / core_demands：仅当 current_session_number=1 时提取，
  否则为空字符串。topic 从[人际关系、婚姻关系、家庭关系、情绪管理、个人成长、
  社会事件、职业发展、自我探索、学业压力]中只选一个。
- growth_experiences：对来访者有影响深远的既往事件（原生家庭、霸凌、创伤、重大成败），
  与治疗过程中发生的事件无关；列表输出。
- theory：仅提取 theory_select 中存在的流派字段；不存在的流派字段保持空。
输出只返回一个 JSON 对象，键名为 client_info_get，必须可被 json.loads 解析。"""


CLIENT_MERGE_SYSTEM = """你是专业的"来访者档案记忆管理器"。
任务：将"历史档案(history_profile)"与"当前会话提取信息(current_profile)"合并，
同时利用"全局背景信息(global_profile)"作为严格过滤器和验证器。

根本原则：
1. 禁止越界填充：global_profile 中有、但 history 与 current 均未提及的信息，
   绝对不能写入结果；咨询师不知道就是不知道。
2. 事实门控：判断 current/history 信息是否在 global 语义真值范围内。
   允许模糊匹配（昵称、泛指学历/职业）；只有根本性事实冲突才删除 current。
3. 细节合并：current/history 与 global 不矛盾的新细节应当被合并，而非丢弃。

合并策略：
- static_traits：History 或 Current 提及且与 Global 相符才写入；冲突时保留更可信一方。
- main_problem / core_demands：history 非空则保持 history；为空则用 current。
- topic：history 非空则锁定；否则 current 若与 global 目标范围一致才采用。
- growth_experiences：用 global 做实体对齐；重复提及只补细节，新知加入，
  与 global 严重冲突或不存在的丢弃。
- theory：仅合并 theory_select 中存在的流派字段；不存在的流派保留 history 原样。
- client_id：必须使用 global_profile 中的 client_id。
输出只返回一个 JSON 对象，键名为 client_info_merge。"""


DIALOGUE_SUMMARY_SYSTEM = """你是专家级 AI 临床督导，负责案例概念化与治疗规划。
任务：接收一个完整的心理咨询会话记录，生成结构化、富有洞察力的分析报告。

核心原则：
1. 督导视角下的临床现实性原则：最终写入报告的每一句分析和结论，都必须在当前
   session 对话中有明确证据支撑，不能透露出咨询师的未知信息。
2. 禁止超前分析：不得做出只有在后期才能得出的诊断性判断或干预性结论。
3. 循证分析：引用当前对话关键句作为证据。
4. theory_select 决定使用的流派框架；不存在的流派字段保持空。
输出只返回一个 JSON 对象（键名 session_summary），必须可被 json.loads 解析。"""


class _ClientInfoGet(StrictModel):
    client_info_get: ExtractedClientInfo


class _ClientInfoMerge(StrictModel):
    client_info_merge: MergedClientProfile


class _SessionSummaryWrapper(StrictModel):
    session_summary: ClinicalSummary


class MemoryExtractionAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def extract(
        self,
        dialogue: list[Message],
        theory_select: list[str],
        session_number: int,
    ) -> ExtractedClientInfo:
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=MEMORY_EXTRACTION_SYSTEM,
            input_payload={
                "current_session_number": session_number,
                "current_session_theory": theory_select,
                "current_session_dialogue": _format_dialogue(dialogue),
            },
            output_schema=_ClientInfoGet,
            temperature=0.1,
        )
        raw = _ClientInfoGet.model_validate(result).client_info_get
        raw.source_session = session_number
        return raw


class ClientMergeAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def merge(
        self,
        history: MergedClientProfile | None,
        current: ExtractedClientInfo,
        global_profile: ClientProfile,
        therapy_select: list[str],
    ) -> MergedClientProfile:
        history_dump = (
            history.model_dump(mode="json")
            if history
            else _empty_merged(global_profile.client_id, current.source_session)
        )
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=CLIENT_MERGE_SYSTEM,
            input_payload={
                "history_profile": history_dump,
                "current_profile": current.model_dump(mode="json"),
                "global_profile": _profile_for_global(global_profile),
                "session_number": current.source_session,
                "theory_select": therapy_select,
            },
            output_schema=_ClientInfoMerge,
            temperature=0.1,
        )
        return _ClientInfoMerge.model_validate(result).client_info_merge


class DialogueSummaryAgent:
    def __init__(self, gateway):
        self.gateway = gateway

    async def summarize(
        self,
        session_index: int,
        dialogue: list[Message],
        plan: SessionPlan,
        theory_select: list[str],
    ) -> ClinicalSummary:
        result = await self.gateway.complete_structured(
            role="summarizer",
            system_prompt=DIALOGUE_SUMMARY_SYSTEM,
            input_payload={
                "theory_select": theory_select,
                "session_index": session_index,
                "session_focus": {
                    "stage_title": plan.stage.value,
                    "objective": plan.objectives,
                },
                "session_dialogue": _format_dialogue(dialogue),
                "plan": plan.model_dump(mode="json"),
            },
            output_schema=_SessionSummaryWrapper,
            temperature=0.1,
        )
        summary = _SessionSummaryWrapper.model_validate(result).session_summary
        summary.session_index = session_index
        return summary


def _format_dialogue(dialogue: list[Message]) -> str:
    lines: list[str] = []
    for message in dialogue:
        label = "咨询师" if message.role == "counselor" else "来访者"
        lines.append(f"{label}：{message.content}")
    return "\n".join(lines)


def _empty_merged(client_id: str, updated_session: int) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "static_traits": StaticTraits().model_dump(mode="json"),
        "main_problem": "",
        "topic": "",
        "core_demands": "",
        "growth_experiences": [],
        "theory": {},
        "updated_session": updated_session,
    }


def _profile_for_global(profile: ClientProfile) -> dict[str, Any]:
    return {
        "client_id": profile.client_id,
        "static_traits": profile.static_traits.model_dump(mode="json"),
        "main_problem": profile.main_problem,
        "topic": profile.topic,
        "core_demands": profile.core_demands,
        "growth_experiences": profile.growth_experiences,
        "theory": profile.theory,
    }