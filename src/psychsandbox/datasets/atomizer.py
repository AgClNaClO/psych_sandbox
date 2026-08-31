from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..domain.models import StrictModel, TrustTier
from ..model_client import ModelGateway
from .profile_compiler import ATOMIZER_PROMPT_VERSION, AtomicSpan


class ExtractedSpan(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    kind: Literal[
        "event", "emotion", "belief", "meaning", "coping", "consequence", "resource",
        "verbal_style", "interaction_style", "affective_expression",
        "conditional_observation", "case_fact", "client_goal", "treatment_instruction",
    ] = "event"
    activation_tags: list[str] = Field(default_factory=list)
    trust_tier: TrustTier = TrustTier.SENSITIVE
    five_ps_roles: list[Literal[
        "presenting", "predisposing", "precipitating", "perpetuating", "protective"
    ]] = Field(default_factory=list)


class ExtractedSpans(StrictModel):
    spans: list[ExtractedSpan]


class AtomizationAudit(StrictModel):
    cache_hit: bool = False
    fallback: bool = False
    validation_failed: bool = False
    needs_review: bool = False
    reason: str = ""


ATOMIZER_SYSTEM_PROMPT = """你是 PsychEval 来访者资料的有来源抽取器。你只能切分输入原文，不能改写、概括、解释或补充。
每个 span 必须是原文中一个连续、完整、可单独披露的语义事实，并返回 Python 风格的 start（含）和 end（不含）。
text 必须是 source_text 中逐字连续出现的原文。start/end 请尽量准确，但程序会依据 text 重新定位。
只要 source_text 含有有意义文本，spans 就不得为空；所有 spans 合起来必须覆盖全部有意义文本。
activation_tags 必须逐字出现在该 span 中；不确定时返回空列表，不要概括或改写标签。
purpose=growth 时 kind 只能是 event/emotion/belief/meaning/coping/consequence/resource。
purpose=language 时，把内容分为 verbal_style/interaction_style/affective_expression/conditional_observation/case_fact；只有前三类是纯表达风格。包含具体人物、事件、症状、经历、目标或关系事实的内容不能标成纯风格。
purpose=core_demands 时 kind 只能是 client_goal 或 treatment_instruction；来访者想获得的改变是 client_goal，指定咨询技术、疗程或咨询师动作是 treatment_instruction。
purpose=five_ps 时 kind 只能是 case_fact，并仅对原文字面支持的 5Ps 角色填写 five_ps_roles。
five_ps_roles 只能从 presenting/predisposing/precipitating/perpetuating/protective 中选择；只有原文字面证据足够时才选择，可以为空，不能推断因果、支持、动机或依恋。
trust_tier 只能是 routine、basic、moderate、sensitive、deep：常规摄入 routine；一般事实 basic；想法和应对 moderate；羞耻、失败和关系伤害 sensitive；创伤或最脆弱材料 deep。
spans 按位置升序、不得重叠，并应覆盖全部有意义的原文内容。只输出符合 schema 的 JSON。"""


class ExtractiveAtomizer:
    def __init__(self, gateway: ModelGateway, cache_dir: Path):
        self.gateway = gateway
        self.cache_dir = cache_dir

    async def atomize(
        self, *, source_path: str, source_text: str,
        purpose: Literal["growth", "language", "core_demands", "five_ps"] = "growth",
    ) -> tuple[list[AtomicSpan], AtomizationAudit]:
        cache_path = self.cache_dir / f"{self._cache_key(source_path, source_text, purpose)}.json"
        if cache_path.exists():
            try:
                cached = ExtractedSpans.model_validate_json(
                    cache_path.read_text(encoding="utf-8")
                )
                return self._validate(source_text, cached, purpose), AtomizationAudit(cache_hit=True)
            except Exception:
                pass
        try:
            validation_error = ""
            previous_output: dict | None = None
            repair_temperatures = (0.0, 0.1, 0.2)
            allowed_kinds = {
                "growth": "event/emotion/belief/meaning/coping/consequence/resource",
                "language": (
                    "verbal_style/interaction_style/affective_expression/"
                    "conditional_observation/case_fact"
                ),
                "core_demands": "client_goal/treatment_instruction",
                "five_ps": "case_fact",
            }
            for semantic_attempt, temperature in enumerate(repair_temperatures):
                payload = {
                    "source_path": source_path,
                    "source_text": source_text,
                    "purpose": purpose,
                    "profile_schema_version": "4",
                }
                if validation_error:
                    payload.update({
                        "atomizer_repair_instruction": (
                            "上次输出通过了 JSON schema，但没有通过逐字原文校验。"
                            "请根据 validation_error 重新切分完整原文；不得改写、遗漏或补写。"
                            "spans 不得为空，且必须覆盖全部有意义原文。"
                            f"当前 purpose={purpose}，kind 只能是 "
                            f"{allowed_kinds[purpose]}；不得使用其他 kind。"
                        ),
                        "validation_error": validation_error,
                        "invalid_previous_spans": previous_output,
                    })
                result = await self.gateway.complete_structured(
                    role="profile",
                    system_prompt=ATOMIZER_SYSTEM_PROMPT,
                    input_payload=payload,
                    output_schema=ExtractedSpans,
                    temperature=temperature,
                )
                parsed = ExtractedSpans.model_validate(result)
                try:
                    spans = self._validate(source_text, parsed, purpose)
                except ValueError as exc:
                    if semantic_attempt < len(repair_temperatures) - 1:
                        validation_error = str(exc)
                        previous_output = parsed.model_dump(mode="json")
                        continue
                    raise
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
                return spans, AtomizationAudit()
            raise RuntimeError("atomizer semantic retry loop ended unexpectedly")
        except Exception as exc:
            return [self._fallback(source_text, purpose)], AtomizationAudit(
                fallback=True,
                validation_failed=not isinstance(exc, (RuntimeError, KeyError)),
                needs_review=True,
                reason=f"{type(exc).__name__}: {str(exc)[:240]}",
            )

    def _cache_key(self, source_path: str, source_text: str, purpose: str) -> str:
        models = getattr(self.gateway, "models", {})
        model = models.get("profile", getattr(self.gateway, "provider_name", "unknown"))
        material = "\0".join(
            (source_path, source_text, purpose, ATOMIZER_PROMPT_VERSION, "4", str(model))
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate(source: str, output: ExtractedSpans, purpose: str) -> list[AtomicSpan]:
        if not output.spans:
            raise ValueError("atomizer returned no spans")
        # Models are good at selecting verbatim text but unreliable at counting
        # Unicode code points.  Treat returned text and order as authoritative,
        # then derive character offsets deterministically from the source.
        ordered = list(output.spans)
        previous_end = 0
        uncovered: list[str] = []
        result: list[AtomicSpan] = []
        allowed = {
            "growth": {"event", "emotion", "belief", "meaning", "coping", "consequence", "resource"},
            "language": {"verbal_style", "interaction_style", "affective_expression", "conditional_observation", "case_fact"},
            "core_demands": {"client_goal", "treatment_instruction"},
            "five_ps": {"case_fact"},
        }[purpose]
        for item in ordered:
            if item.kind not in allowed:
                raise ValueError(f"invalid {purpose} span kind: {item.kind}")
            start = source.find(item.text, previous_end)
            if start < 0:
                raise ValueError("atomizer text is not an exact source span")
            end = start + len(item.text)
            activation_tags = tuple(
                tag for tag in item.activation_tags if tag and tag in item.text
            )
            if purpose == "language" and item.kind in {
                "verbal_style", "interaction_style", "affective_expression"
            } and _looks_like_case_fact(item.text):
                raise ValueError("factual language_features content cannot enter expression style")
            uncovered.append(source[previous_end:start])
            previous_end = end
            result.append(
                AtomicSpan(
                    start=start,
                    end=end,
                    text=item.text,
                    kind=item.kind,
                    activation_tags=activation_tags,
                    trust_tier=item.trust_tier,
                    five_ps_roles=tuple(item.five_ps_roles),
                    needs_review=False,
                )
            )
        uncovered.append(source[previous_end:])
        residue = "".join(uncovered)
        if re.sub(r"[\s，。！？；、,:：;（）()\-—]+", "", residue):
            raise ValueError("atomizer omitted meaningful source content")
        return result

    @staticmethod
    def _fallback(source: str, purpose: str) -> AtomicSpan:
        kind = {
            "growth": "event",
            "language": "case_fact",
            "core_demands": "treatment_instruction",
            "five_ps": "case_fact",
        }[purpose]
        return AtomicSpan(
            start=0,
            end=len(source),
            text=source,
            kind=kind,
            trust_tier=TrustTier.SENSITIVE,
            needs_review=True,
        )


def _looks_like_case_fact(text: str) -> bool:
    factual_markers = (
        "父亲", "母亲", "父母", "家人", "伴侣", "老师", "同学", "领导",
        "小时候", "去年", "最近", "曾经", "发生", "离职", "失业", "去世",
        "焦虑", "抑郁", "失眠", "自杀", "创伤", "诊断", "治疗", "药",
        "希望咨询", "咨询师", "疗程",
    )
    return any(marker in text for marker in factual_markers) or bool(re.search(r"\d", text))
