from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ..domain import (
    CounselingCase,
    HolisticEvaluationReport,
    RunResult,
    ScaleItems,
    ScaleScore,
)
from ..model_client import ModelGateway


@dataclass(frozen=True, slots=True)
class Instrument:
    """A PsychEval rating instrument backed by one or more official prompts."""

    key: str
    level: Literal["counselor", "client"]
    category: Literal["therapy_shared", "therapy_specific"]
    direction: Literal["higher_better", "lower_better"]
    prompt_files: tuple[str, ...]


def _shared_counselor_instruments() -> dict[str, Instrument]:
    base = "custom_dim"
    return {
        "wai": Instrument("wai", "counselor", "therapy_shared", "higher_better", ("wai/wai.txt",)),
        "htais": Instrument("htais", "counselor", "therapy_shared", "higher_better", ("HTAIS/HTAIS.txt",)),
        "rro": Instrument("rro", "counselor", "therapy_shared", "higher_better", ("RRO/RRO.txt",)),
        "custom_clinical_perception": Instrument(
            "custom_clinical_perception", "counselor", "therapy_shared", "higher_better",
            (f"{base}/Perception.txt",),
        ),
        "custom_intervention_strategy": Instrument(
            "custom_intervention_strategy", "counselor", "therapy_shared", "higher_better",
            (f"{base}/Intervention.txt",),
        ),
        "custom_therapeutic_depth": Instrument(
            "custom_therapeutic_depth", "counselor", "therapy_shared", "higher_better",
            (f"{base}/Interaction.txt",),
        ),
        "custom_ethics_safety": Instrument(
            "custom_ethics_safety", "counselor", "therapy_shared", "higher_better",
            (f"{base}/Ethics.txt",),
        ),
    }


def _specific_counselor_instruments(therapy: str) -> dict[str, Instrument]:
    if therapy == "cbt":
        return {
            "ctrs": Instrument(
                "ctrs", "counselor", "therapy_specific", "higher_better",
                (
                    "ctrs/collaboration.txt",
                    "ctrs/focus.txt",
                    "ctrs/guided_discovery.txt",
                    "ctrs/interpersonal_effectiveness.txt",
                    "ctrs/strategy.txt",
                    "ctrs/understanding.txt",
                ),
            ),
        }
    if therapy == "humanistic_existential":
        return {
            "tes": Instrument(
                "tes", "counselor", "therapy_specific", "higher_better",
                (
                    "tes/acceptance of feelings.txt",
                    "tes/attuned to client's inner world.txt",
                    "tes/concern.txt",
                    "tes/expressiveness.txt",
                    "tes/resonate or capture client feelings.txt",
                    "tes/responsiveness.txt",
                    "tes/understanding cognitive framework.txt",
                    "tes/understanding feelings.txt",
                    "tes/warmth.txt",
                ),
            ),
        }
    if therapy == "psychodynamic":
        return {
            "psc": Instrument(
                "psc", "counselor", "therapy_specific", "higher_better",
                (
                    "psc/deepening and regulating emotions.txt",
                    "psc/empathy.txt",
                    "psc/facilitating patient engagement.txt",
                    "psc/flexibility and rigidity.txt",
                    "psc/patterns in relationships.txt",
                    "psc/transference.txt",
                    "psc/understanding and tracking.txt",
                ),
            ),
        }
    if therapy == "behavioral":
        return {
            "miti": Instrument(
                "miti", "counselor", "therapy_specific", "higher_better",
                (
                    "miti/cultivating change talk.txt",
                    "miti/empathy.txt",
                    "miti/partnership.txt",
                    "miti/softening sustain talk.txt",
                ),
            ),
        }
    if therapy == "postmodern":
        return {
            "eft_tfs": Instrument(
                "eft_tfs", "counselor", "therapy_specific", "higher_better",
                ("eft_tfs/EFT_TFS.txt",),
            ),
        }
    return {}


def _shared_client_instruments() -> dict[str, Instrument]:
    return {
        "scl90": Instrument("scl90", "client", "therapy_shared", "lower_better", ("SCL_90/SCL_90.txt",)),
        "panas": Instrument("panas", "client", "therapy_shared", "higher_better", ("panas/panas.txt",)),
        "rro_client": Instrument("rro_client", "client", "therapy_shared", "higher_better", ("RRO/RRO.txt",)),
        "srs": Instrument("srs", "client", "therapy_shared", "higher_better", ("srs/srs.txt",)),
    }


def _specific_client_instruments(therapy: str) -> dict[str, Instrument]:
    if therapy == "cbt":
        return {
            "bdi_ii": Instrument("bdi_ii", "client", "therapy_specific", "lower_better", ("BDI_II/BDI_II.txt",)),
        }
    if therapy == "humanistic_existential":
        return {
            "cct": Instrument(
                "cct", "client", "therapy_specific", "higher_better",
                (
                    "cct/current focus.txt",
                    "cct/non critical.txt",
                    "cct/real connection.txt",
                    "cct/self awareness.txt",
                    "cct/self exploration.txt",
                ),
            ),
        }
    if therapy == "psychodynamic":
        return {
            "ipo": Instrument("ipo", "client", "therapy_specific", "lower_better", ("IPO/IPO.txt",)),
        }
    if therapy == "behavioral":
        return {
            "stai": Instrument("stai", "client", "therapy_specific", "lower_better", ("stai/STAI.txt",)),
        }
    if therapy == "postmodern":
        return {
            "sfbt": Instrument("sfbt", "client", "therapy_specific", "higher_better", ("sfbt/SFBT.txt",)),
        }
    return {}


class PsychEvalSupervisor:
    """External LLM supervisor aligning with the PsychEval holistic framework.

    This runs after every session in a trajectory completes and produces a
    Counselor-Level (clinical proficiency) plus Client-Level (simulation
    fidelity) report. It intentionally does not feed back into session
    planning: planning is a separate consolidation concern in the paper.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        prompts_dir: Path,
        *,
        temperature: float = 0.1,
    ):
        self.gateway = gateway
        self.prompts_dir = Path(prompts_dir)
        self.temperature = temperature

    async def evaluate(
        self, result: RunResult, case: CounselingCase
    ) -> HolisticEvaluationReport:
        dialogue = self._format_dialogue(result)
        intake = self._format_intake(case)

        counselor_shared = [
            await self._score(instrument, intake, dialogue)
            for instrument in _shared_counselor_instruments().values()
        ]
        counselor_specific = [
            await self._score(instrument, intake, dialogue)
            for instrument in _specific_counselor_instruments(result.therapy).values()
        ]
        client_shared = [
            await self._score(instrument, intake, dialogue)
            for instrument in _shared_client_instruments().values()
        ]
        client_specific = [
            await self._score(instrument, intake, dialogue)
            for instrument in _specific_client_instruments(result.therapy).values()
        ]

        counselor_overall = self._overall(counselor_shared + counselor_specific)
        client_overall = self._overall(client_shared + client_specific)
        return HolisticEvaluationReport(
            run_id=result.run_id,
            case_id=result.case_id,
            therapy=result.therapy,
            counselor_shared=counselor_shared,
            counselor_specific=counselor_specific,
            client_shared=client_shared,
            client_specific=client_specific,
            counselor_overall=counselor_overall,
            client_overall=client_overall,
        )

    async def _score(
        self,
        instrument: Instrument,
        intake: str,
        dialogue: str,
    ) -> ScaleScore:
        item_scores: dict[str, float] = {}
        for relative in instrument.prompt_files:
            path = self._resolve_prompt(relative)
            if path is None:
                continue
            template = path.read_text(encoding="utf-8")
            system_prompt = (
                template.replace("{{intake_form}}", intake)
                .replace("{{diag}}", dialogue)
            )
            if not _has_intake_and_dialogue(system_prompt):
                system_prompt = (
                    system_prompt
                    + f"\n\n[来访者背景信息]：\n{intake}\n\n[咨询对话]：\n{dialogue}"
                )
            raw = cast(
                ScaleItems,
                await self.gateway.complete_structured(
                    role="supervisor",
                    system_prompt=system_prompt,
                    input_payload={"intake_form": intake, "dialogue": dialogue},
                    output_schema=ScaleItems,
                    temperature=self.temperature,
                ),
            )
            for item in raw.items:
                key = item.item.strip()
                if key:
                    item_scores.setdefault(key, float(item.score))
        return ScaleScore(
            name=instrument.key,
            level=instrument.level,
            category=instrument.category,
            direction=instrument.direction,
            score=self._normalize(instrument, item_scores),
            item_scores=item_scores,
        )

    def _resolve_prompt(self, relative: str) -> Path | None:
        direct = self.prompts_dir / relative
        if direct.exists():
            return direct
        # The official repository contains curly quotes in some filenames.
        # Fall back to a normalized basename match within the same directory.
        parent = direct.parent
        if not parent.exists():
            return None
        wanted = _normalize_quote(direct.name)
        for candidate in parent.iterdir():
            if candidate.is_file() and _normalize_quote(candidate.name) == wanted:
                return candidate
        return None

    @staticmethod
    def _normalize(instrument: Instrument, item_scores: dict[str, float]) -> float:
        if not item_scores:
            return 0.0
        # Official prompts ask for 1-5 ratings; map to a 0-10 summary.
        values = [
            min(5.0, max(1.0, float(value))) for value in item_scores.values()
        ]
        average = sum(values) / len(values)
        normalized = round((average - 1.0) / 4.0 * 10.0, 3)
        if instrument.direction == "lower_better":
            return round(10.0 - normalized, 3)
        return normalized

    @staticmethod
    def _overall(scores: list[ScaleScore]) -> float:
        if not scores:
            return 0.0
        # All scores are normalized so higher is better.
        return round(sum(item.score for item in scores) / len(scores), 3)

    @staticmethod
    def _format_dialogue(result: RunResult) -> str:
        parts: list[str] = []
        for session in result.sessions:
            parts.append(f"第{session.session_index}次会谈：")
            for message in session.messages:
                if message.role not in {"client", "counselor"}:
                    continue
                label = "来访者" if message.role == "client" else "咨询师"
                parts.append(f"{label}：{message.content}")
        return "\n".join(parts)

    @staticmethod
    def _format_intake(case: CounselingCase) -> str:
        profile = case.profile
        traits = profile.static_traits
        lines = [
            f"姓名：{traits.name or '来访者'}",
            f"年龄：{traits.age}",
            f"性别：{traits.gender}",
            f"职业：{traits.occupation}",
            f"教育背景：{traits.educational_background}",
            f"婚姻状况：{traits.marital_status}",
            f"家庭状况：{traits.family_status}",
            f"社会状况：{traits.social_status}",
            f"主诉：{profile.main_problem}",
            f"咨询主题：{profile.topic}",
            f"核心诉求：{profile.core_demands}",
        ]
        if profile.growth_experiences:
            lines.append("成长经历：" + "；".join(profile.growth_experiences))
        return "\n".join(line for line in lines if line)


def _has_intake_and_dialogue(prompt: str) -> bool:
    return "来访者背景信息" in prompt and "咨询对话" in prompt


def _normalize_quote(name: str) -> str:
    return (
        name.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


__all__ = ["PsychEvalSupervisor"]
