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
    SessionEvaluationReport,
    SessionRecord,
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
    # Raw rating range of the official prompt items. PsychEval instruments do
    # not share one range (WAI is 1-5, TES is 1-7, PSC/CTRS are 0-6, SCL-90/SRS
    # are 0-4, BDI-II is 0-3, CCT is 0-2), so each instrument carries its own.
    scale: tuple[float, float] = (1.0, 5.0)


_RRO_CLIENT_FACTORS: dict[str, tuple[int, ...]] = {
    "Client Realism": (1, 8, 9, 10, 12, 20, 17, 16, 22),
    "Client Genuineness": (4, 11, 18, 24),
}
_RRO_COUNSELOR_FACTORS: dict[str, tuple[int, ...]] = {
    "Counselor Realism": (2, 6, 15, 21, 23, 19),
    "Counselor Genuineness": (3, 5, 7, 13, 14),
}
_RRO_REVERSE_SCORED: frozenset[int] = frozenset({2, 7, 16, 17, 18, 19, 24})

# PANAS is the only instrument whose score is not a simple item average: the
# official ``panas.py`` averages the 10 positive and 10 negative affects
# separately and returns ``(positive - negative + 10) / 2``.
_PANAS_POSITIVE: frozenset[str] = frozenset(
    {
        "interested", "excited", "strong", "enthusiastic", "proud",
        "alert", "inspired", "determined", "attentive", "active",
    }
)
_PANAS_NEGATIVE: frozenset[str] = frozenset(
    {
        "distressed", "upset", "guilty", "scared", "hostile",
        "irritable", "ashamed", "nervous", "jittery", "afraid",
    }
)


def _shared_counselor_instruments() -> dict[str, Instrument]:
    base = "custom_dim"
    return {
        "wai": Instrument("wai", "counselor", "therapy_shared", "higher_better", ("wai/wai.txt",)),
        "htais": Instrument("htais", "counselor", "therapy_shared", "higher_better", ("HTAIS/HTAIS.txt",)),
        "custom_dim": Instrument(
            "custom_dim",
            "counselor",
            "therapy_shared",
            "higher_better",
            (
                f"{base}/Ethics.txt",
                f"{base}/Interaction.txt",
                f"{base}/Intervention.txt",
                f"{base}/Perception.txt",
            ),
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
                scale=(0.0, 6.0),
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
                scale=(1.0, 7.0),
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
                scale=(0.0, 6.0),
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
        "scl90": Instrument("scl90", "client", "therapy_shared", "lower_better", ("SCL_90/SCL_90.txt",), scale=(0.0, 4.0)),
        "panas": Instrument("panas", "client", "therapy_shared", "higher_better", ("panas/panas.txt",)),
        "srs": Instrument("srs", "client", "therapy_shared", "higher_better", ("srs/srs.txt",), scale=(0.0, 4.0)),
    }


def _specific_client_instruments(therapy: str) -> dict[str, Instrument]:
    if therapy == "cbt":
        return {
            "bdi_ii": Instrument("bdi_ii", "client", "therapy_specific", "lower_better", ("BDI_II/BDI_II.txt",), scale=(0.0, 3.0)),
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
                scale=(0.0, 2.0),
            ),
        }
    if therapy == "psychodynamic":
        return {
            "ipo": Instrument("ipo", "client", "therapy_specific", "lower_better", ("IPO/IPO.txt",)),
        }
    if therapy == "behavioral":
        return {
            "stai": Instrument("stai", "client", "therapy_specific", "higher_better", ("stai/STAI.txt",), scale=(0.0, 4.0)),
        }
    if therapy == "postmodern":
        return {
            "sfbt": Instrument("sfbt", "client", "therapy_specific", "higher_better", ("sfbt/SFBT.txt",), scale=(0.0, 4.0)),
        }
    return {}


class PsychEvalSupervisor:
    """The clinical supervisor: a holistic, PsychEval-aligned LLM-as-judge.

    ``evaluate`` runs once after every session in a trajectory completes and
    produces a Counselor-Level (clinical proficiency) plus Client-Level
    (simulation fidelity) report over the full trajectory. ``evaluate_session``
    is the per-session variant reused for RFT reward, so session scoring and the
    final holistic score share one instrument set. The supervisor only scores;
    it never plans the next session (planning is a separate consolidation
    concern, per PsychAgent §3.3 / PsychEval §5).
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
        counselor_shared, counselor_specific, client_shared, client_specific = (
            await self._score_instruments(result.therapy, intake, dialogue)
        )
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

    async def evaluate_session(
        self, session: SessionRecord, case: CounselingCase
    ) -> SessionEvaluationReport:
        """Score a single session with the same PsychEval instruments.

        This is the per-session LLM-as-judge used for RFT reward and session
        audit; it shares the instrument set of the holistic supervisor but is a
        ranking signal, not the clinical supervisor itself.
        """
        dialogue = self._format_session_dialogue(session)
        intake = self._format_intake(case)
        counselor_shared, counselor_specific, client_shared, client_specific = (
            await self._score_instruments(session.plan.therapy, intake, dialogue)
        )
        counselor_overall = self._overall(counselor_shared + counselor_specific)
        client_overall = self._overall(client_shared + client_specific)
        return SessionEvaluationReport(
            session_index=session.session_index,
            therapy=session.plan.therapy,
            counselor_shared=counselor_shared,
            counselor_specific=counselor_specific,
            client_shared=client_shared,
            client_specific=client_specific,
            counselor_overall=counselor_overall,
            client_overall=client_overall,
        )

    async def _score_instruments(
        self, therapy: str, intake: str, dialogue: str
    ) -> tuple[list[ScaleScore], list[ScaleScore], list[ScaleScore], list[ScaleScore]]:
        counselor_shared = [
            await self._score(instrument, intake, dialogue)
            for instrument in _shared_counselor_instruments().values()
        ]
        counselor_specific = [
            await self._score(instrument, intake, dialogue)
            for instrument in _specific_counselor_instruments(therapy).values()
        ]
        client_shared = [
            await self._score(instrument, intake, dialogue)
            for instrument in _shared_client_instruments().values()
        ]
        client_specific = [
            await self._score(instrument, intake, dialogue)
            for instrument in _specific_client_instruments(therapy).values()
        ]
        # RRO is a single 24-item prompt that decomposes into counselor- and
        # client-side factor scores (matching PsychEval's factor structure).
        rro_counselor, rro_client = await self._score_rro(intake, dialogue)
        counselor_shared.append(rro_counselor)
        client_shared.append(rro_client)
        return counselor_shared, counselor_specific, client_shared, client_specific

    async def _collect_items(
        self, relative: str, intake: str, dialogue: str
    ) -> list[tuple[str, float]]:
        """Render one prompt and return ``(item_label, score)`` pairs."""
        path = self._resolve_prompt(relative)
        if path is None:
            return []
        template = path.read_text(encoding="utf-8")
        system_prompt = (
            template.replace("{{intake_form}}", intake).replace("{{diag}}", dialogue)
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
        return [
            (item.item.strip(), float(item.score))
            for item in raw.items
            if item.item.strip()
        ]

    async def _score(
        self,
        instrument: Instrument,
        intake: str,
        dialogue: str,
    ) -> ScaleScore:
        if instrument.key == "panas":
            return await self._score_panas(instrument, intake, dialogue)
        values: list[float] = []
        item_scores: dict[str, float] = {}
        for relative in instrument.prompt_files:
            for label, score in await self._collect_items(relative, intake, dialogue):
                values.append(score)
                item_scores.setdefault(label, score)
        return ScaleScore(
            name=instrument.key,
            level=instrument.level,
            category=instrument.category,
            direction=instrument.direction,
            score=self._normalize(instrument, values),
            item_scores=item_scores,
        )

    async def _score_panas(
        self, instrument: Instrument, intake: str, dialogue: str
    ) -> ScaleScore:
        """Score PANAS with the official positive/negative affect balance.

        Each item is 1-5 and mapped to ``(score - 1) * 2.5``; the 10 positive
        and 10 negative affects are averaged separately and combined as
        ``(positive - negative + 10) / 2`` (matching ``panas.py``).
        """
        item_scores: dict[str, float] = {}
        for relative in instrument.prompt_files:
            for label, score in await self._collect_items(relative, intake, dialogue):
                item_scores.setdefault(label.strip().lower(), score)

        def side_average(names: frozenset[str]) -> float | None:
            values = [
                (item_scores[name] - 1.0) * 2.5
                for name in names
                if name in item_scores
            ]
            return sum(values) / len(values) if values else None

        positive = side_average(_PANAS_POSITIVE)
        negative = side_average(_PANAS_NEGATIVE)
        if positive is None or negative is None:
            score = 0.0
        else:
            score = round(min(10.0, max(0.0, (positive - negative + 10.0) / 2.0)), 3)
        return ScaleScore(
            name=instrument.key,
            level=instrument.level,
            category=instrument.category,
            direction=instrument.direction,
            score=score,
            item_scores=item_scores,
        )

    async def _score_rro(
        self, intake: str, dialogue: str
    ) -> tuple[ScaleScore, ScaleScore]:
        """Score the 24-item RRO once and split it into counselor/client factors.

        PsychEval's RRO decomposes its 24 items into four factors (Client
        Realism, Client Genuineness, Counselor Realism, Counselor Genuineness)
        with reverse scoring on items {2, 7, 16, 17, 18, 19, 24}; the counselor
        and client sides each average their two factors.
        """
        item_scores: dict[int, float] = {}
        for label, score in await self._collect_items("RRO/RRO.txt", intake, dialogue):
            if label.isdigit():
                item_scores[int(label)] = score
        counselor_score = self._rro_side_score(item_scores, _RRO_COUNSELOR_FACTORS)
        client_score = self._rro_side_score(item_scores, _RRO_CLIENT_FACTORS)
        shared_item_scores = {str(key): value for key, value in item_scores.items()}
        counselor = ScaleScore(
            name="rro",
            level="counselor",
            category="therapy_shared",
            direction="higher_better",
            score=counselor_score,
            item_scores=shared_item_scores,
        )
        client = ScaleScore(
            name="rro_client",
            level="client",
            category="therapy_shared",
            direction="higher_better",
            score=client_score,
            item_scores=shared_item_scores,
        )
        return counselor, client

    @staticmethod
    def _rro_side_score(
        item_scores: dict[int, float], factors: dict[str, tuple[int, ...]]
    ) -> float:
        factor_means: list[float] = []
        for numbers in factors.values():
            values: list[float] = []
            for number in numbers:
                if number not in item_scores:
                    continue
                value = (min(5.0, max(1.0, float(item_scores[number]))) - 1.0) / 4.0 * 10.0
                if number in _RRO_REVERSE_SCORED:
                    value = 10.0 - value
                values.append(value)
            if values:
                factor_means.append(sum(values) / len(values))
        if not factor_means:
            return 0.0
        return round(sum(factor_means) / len(factor_means), 3)

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
    def _normalize(instrument: Instrument, values: list[float]) -> float:
        if not values:
            return 0.0
        # Each PsychEval instrument uses its own raw range (1-5, 1-7, 0-6,
        # 0-4, 0-3, 0-2); map the item average onto 0-10 exactly like the
        # official eval methods. Symptom scales (direction="lower_better") are
        # kept raw (higher = worse); the RFT reward inverts their delta, not
        # this summary.
        low, high = instrument.scale
        span = high - low
        if span <= 0:
            return 0.0
        clamped = [min(high, max(low, float(value))) for value in values]
        average = sum(clamped) / len(clamped)
        return round((average - low) / span * 10.0, 3)

    @staticmethod
    def _overall(scores: list[ScaleScore]) -> float:
        if not scores:
            return 0.0
        # The 0-10 report summary is higher-is-better, so lower_better symptom
        # scales are inverted before averaging to keep the summary consistent.
        adjusted = [
            (10.0 - item.score) if item.direction == "lower_better" else item.score
            for item in scores
        ]
        return round(sum(adjusted) / len(adjusted), 3)

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
    def _format_session_dialogue(session: SessionRecord) -> str:
        parts: list[str] = []
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
