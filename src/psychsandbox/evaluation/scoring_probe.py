"""Endpoint feasibility probe for the probability-weighted scoring path.

The probe exercises the same batch-JSON per-item path as production. All
required items must pass JSON/byte alignment and the original numeric-mass
gate. Each invocation records the conditional item distributions or an explicit
failure; fixture dialogue is synthetic capability input, not research data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import write_json
from ..domain import LogprobScoringConfig
from ..logprob import LogprobRefusalError, LogprobScoringUnsupported, logprob_band
from ..model_client import ModelGateway
from .psycheval_supervisor import Instrument, PsychEvalSupervisor


PROBE_FIXTURE_DIALOGUE = (
    "咨询师：我们今天可以从最近让你感到困扰的一件事说起，你愿意的话就慢慢讲。\n"
    "来访者：最近睡不好，脑子里总在想工作上的事，白天也没什么力气。\n"
    "咨询师：听起来这些担心一直占着你的精力。我们能不能先一起看看，"
    "最让你放不下的具体是哪一部分？\n"
    "来访者：可能是担心自己做不好、被领导否定吧。\n"
    "咨询师：明白了。我们先记下这一点，再一起看看还有没有别的可能。"
)

PROBE_FIXTURE_NOTE = "固定合成对话，只用于探测端点能力，不是研究数据。"


async def probe_instrument_rating(
    gateway: ModelGateway,
    prompts_dir: Path,
    *,
    instrument: Instrument,
    intake: str,
    dialogue: str,
    config: LogprobScoringConfig,
    dialogue_source: str = "fixture",
) -> dict[str, Any]:
    """Run one logprob judgement and describe how the endpoint responded.

    Returns a JSON-friendly record. A missing logprob payload and a low-mass
    refusal are captured as ``supported``/``accepted`` flags plus the observed
    numbers, so a probe of an unsupported endpoint produces an artifact instead
    of an exception; the scoring path itself still fails loudly.
    """
    # A probe exists to test the capability, so it runs even when a run keeps the
    # mode disabled in its config.
    effective = config.model_copy(update={"enabled": True})
    supervisor = PsychEvalSupervisor(
        gateway,
        prompts_dir,
        temperature=effective.temperature,
        logprob_scoring=effective,
    )
    record: dict[str, Any] = {
        "kind": "logprob-scoring-probe",
        "instrument": {
            "key": instrument.key,
            "level": instrument.level,
            "category": instrument.category,
            "prompt_files": list(instrument.prompt_files),
        },
        "band": list(logprob_band(instrument.scale)),
        "request": {
            "model_role": "supervisor",
            "temperature": effective.temperature,
            "top_logprobs": effective.top_logprobs,
            "max_tokens": effective.max_tokens,
            "mass_floor": effective.mass_floor,
        },
        "dialogue_source": dialogue_source,
        "dialogue_note": PROBE_FIXTURE_NOTE if dialogue_source == "fixture" else "",
        "supported": False,
        "accepted": False,
        "mass": None,
        "distribution": None,
        "rating": None,
        "error": None,
    }
    record["scoring_method"] = effective.method
    record["items"] = {}
    try:
        score = await supervisor.score_instrument_items(instrument, intake, dialogue)
    except (LogprobScoringUnsupported, LogprobRefusalError, ValueError, RuntimeError) as exc:
        record["supported"] = getattr(exc, "supported", isinstance(exc, LogprobRefusalError))
        record["items"] = getattr(exc, "records", {})
        record["error"] = ("unsupported: " if not record["supported"] else "scoring_failed: ") + str(exc)
        if isinstance(exc, LogprobRefusalError):
            record["mass"] = exc.mass
            record["distribution"] = {str(k): v for k, v in exc.distribution.items()}
        record["mass"] = record["mass"] if record["mass"] is not None else min(
            (item["mass"] for item in record["items"].values() if "mass" in item), default=None)
    else:
        record["supported"] = True
        record["accepted"] = True
        record["items"] = score.item_logprobs
        record["mass"] = min(item["mass"] for item in score.item_logprobs.values())
        record["rating"] = {"value": score.score, "scale": [0, 10]}
    return record


def write_probe_record(directory: Path, record: dict[str, Any]) -> Path:
    """Persist one probe record inside its own invocation directory."""
    path = Path(directory) / "probe.json"
    write_json(path, record)
    return path


__all__ = [
    "PROBE_FIXTURE_DIALOGUE",
    "PROBE_FIXTURE_NOTE",
    "probe_instrument_rating",
    "write_probe_record",
]
