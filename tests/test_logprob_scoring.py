"""Contracts for the probability-weighted (logprob) scoring path.

The path adapts Eq. 8 of Zhang et al., *Mechanistic control of large language
models as simulated participants via linear representation* (npj Artificial
Intelligence, DOI 10.1038/s44387-026-00160-9): a judge's numeric token
distribution is aggregated as a probability-weighted expectation, and a
judgement whose total in-band mass stays below the floor is a refusal. These
tests are offline; the endpoint capability itself is probed with
``psych-sandbox probe logprob-scoring``.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from tenacity import wait_none

from psychsandbox.domain import (
    LogprobScoringConfig,
    SandboxConfig,
    ScaleItem,
    ScaleItems,
)
from psychsandbox.evaluation import instrument_registry
from psychsandbox.evaluation.psycheval_supervisor import PsychEvalSupervisor
from psychsandbox.evaluation.scoring_probe import (
    PROBE_FIXTURE_DIALOGUE,
    probe_instrument_rating,
    write_probe_record,
)
from psychsandbox.logprob import (
    LogprobRefusalError,
    LogprobScoringUnsupported,
    build_rating_prompt,
    logprob_band,
    parse_integer_token,
    rating_from_choice,
    rating_from_top_logprobs,
)
from psychsandbox.model_client import ModelGateway, OpenAICompatibleGateway
from psychsandbox.runtime import CounselingSandbox
from tests.deterministic_gateway import DeterministicGateway


def _token(token: str, probability: float) -> SimpleNamespace:
    return SimpleNamespace(token=token, logprob=math.log(probability))


def _choice(*pairs, top: bool = True) -> SimpleNamespace:
    content = [SimpleNamespace(top_logprobs=[_token(t, p) for t, p in pairs] if top else None)]
    return SimpleNamespace(logprobs=SimpleNamespace(content=content))


def test_weighted_expectation_ignores_out_of_band_tokens():
    rating = rating_from_top_logprobs(
        [_token("3", 0.5), _token("5", 0.25), _token("9", 0.25)], band=(0, 6)
    )

    assert rating.mass == pytest.approx(0.75)
    assert rating.value == pytest.approx(2.75 / 0.75)
    assert dict(rating.distribution) == {3: pytest.approx(0.5), 5: pytest.approx(0.25)}
    assert rating.as_record()["distribution"] == {"3": 0.5, "5": 0.25}


def test_uniform_distribution_returns_the_middle_of_the_band():
    pairs = [(str(value), 1 / 7) for value in range(7)]

    rating = rating_from_top_logprobs([_token(t, p) for t, p in pairs], band=(0, 6))

    assert rating.mass == pytest.approx(1.0)
    assert rating.value == pytest.approx(3.0)


def test_mass_floor_boundary_is_exclusive_below_the_floor():
    accepted = rating_from_top_logprobs([_token("4", 0.25)], band=(0, 6))
    assert accepted.mass == pytest.approx(0.25)

    with pytest.raises(LogprobRefusalError) as error:
        rating_from_top_logprobs([_token("4", 0.24)], band=(0, 6))
    assert error.value.mass == pytest.approx(0.24)
    assert error.value.mass_floor == pytest.approx(0.25)
    assert error.value.band == (0, 6)
    assert dict(error.value.distribution) == {4: pytest.approx(0.24)}
    assert "0.2400" in str(error.value)



def test_custom_mass_floor_can_reject_a_usable_distribution():
    with pytest.raises(LogprobRefusalError):
        rating_from_top_logprobs([_token("3", 0.5), _token("5", 0.25)], band=(0, 6), mass_floor=0.9)


def test_duplicate_and_noisy_tokens_are_handled():
    rating = rating_from_top_logprobs(
        [
            _token("4", 0.2),
            _token(" 4", 0.2),
            _token("4.0", 0.3),
            _token("10", 0.1),
            _token("yes", 0.1),
            _token("5", 0.1),
        ],
        band=(0, 6),
    )

    assert dict(rating.distribution) == {4: pytest.approx(0.4), 5: pytest.approx(0.1)}
    assert rating.value == pytest.approx((4 * 0.4 + 5 * 0.1) / 0.5)


@pytest.mark.parametrize(
    ("token", "expected"),
    [("4", 4), (" 4 ", 4), ("+4", 4), ("-3", -3), ("4.0", None), ("", None), ("四", None), ("４", None)],
)
def test_integer_token_parsing_is_ascii_and_whole_number_only(token, expected):
    assert parse_integer_token(token) == expected


def test_missing_logprob_payload_is_reported_as_unsupported():
    with pytest.raises(LogprobScoringUnsupported):
        rating_from_choice(SimpleNamespace(logprobs=None), band=(0, 6))
    with pytest.raises(LogprobScoringUnsupported):
        rating_from_choice(SimpleNamespace(logprobs=SimpleNamespace(content=[])), band=(0, 6))
    with pytest.raises(LogprobScoringUnsupported):  # top_logprobs not requested
        rating_from_choice(_choice(top=False), band=(0, 6))


def test_malformed_logprob_entries_are_reported_as_unsupported():
    with pytest.raises(LogprobScoringUnsupported):
        rating_from_top_logprobs([SimpleNamespace(token=None, logprob=0.0)], band=(0, 6))
    with pytest.raises(LogprobScoringUnsupported):
        rating_from_top_logprobs([SimpleNamespace(token="4", logprob="high")], band=(0, 6))


@pytest.mark.parametrize(
    ("scale", "expected"),
    [((1.0, 5.0), (1, 5)), ((0.0, 6.0), (0, 6)), ((1.0, 7.0), (1, 7))],
)
def test_logprob_band_reads_integer_instrument_scales(scale, expected):
    assert logprob_band(scale) == expected


@pytest.mark.parametrize("scale", [(0.0, 100.0), (0.5, 4.5), (1.0, 20.0)])
def test_logprob_band_rejects_scales_a_single_token_cannot_cover(scale):
    with pytest.raises(ValueError, match="logprob scoring"):
        logprob_band(scale)


def test_rating_prompt_renders_every_placeholder():
    template = (
        "{{instrument}}|{{rating_low}}-{{rating_high}}|{{instrument_prompt}}|"
        "[来访者背景信息]{{intake_form}}|{{diag}}"
    )

    rendered = build_rating_prompt(
        template,
        instrument="wai",
        instrument_prompt="官方口径",
        band=(1, 5),
        intake="背景",
        dialogue="对话",
    )

    assert rendered == "wai|1-5|官方口径|[来访者背景信息]背景|对话"


def test_rating_prompt_rejects_unknown_placeholders():
    with pytest.raises(ValueError, match="unresolved placeholder"):
        build_rating_prompt(
            "{{instrument}} {{unknown}}",
            instrument="wai",
            instrument_prompt="x",
            band=(1, 5),
            intake="i",
            dialogue="d",
        )


class FakeCompletions:
    """Offline stand-in for ``client.chat.completions``."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _logprob_gateway(tmp_path: Path, result) -> tuple[OpenAICompatibleGateway, FakeCompletions]:
    completions = FakeCompletions(result)
    gateway = object.__new__(OpenAICompatibleGateway)
    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    gateway.models = {"supervisor": "ecnu-plus"}
    gateway.max_tokens = 2048
    gateway.max_attempts = 3
    gateway.diagnostic_dir = tmp_path / "diagnostics"
    return gateway, completions


def test_gateway_requests_logprobs_without_structured_output(tmp_path):
    gateway, completions = _logprob_gateway(
        tmp_path, SimpleNamespace(choices=[_choice(("3", 0.5), ("5", 0.5))])
    )

    rating = asyncio.run(
        gateway.complete_numeric_rating(
            role="supervisor",
            system_prompt="只输出一个整数",
            user_prompt="评分",
            band=(1, 5),
            temperature=0.7,
            top_logprobs=20,
            max_tokens=16,
        )
    )

    assert rating.value == pytest.approx(4.0)
    assert rating.mass == pytest.approx(1.0)
    request = completions.calls[0]
    assert request["logprobs"] is True
    assert request["top_logprobs"] == 20
    assert request["max_tokens"] == 16
    assert request["temperature"] == 0.7
    assert request["model"] == "ecnu-plus"
    # JSON-schema constrained decoding would distort the rating distribution.
    assert "response_format" not in request


def test_gateway_reports_an_endpoint_without_logprobs(tmp_path):
    gateway, completions = _logprob_gateway(
        tmp_path, SimpleNamespace(choices=[SimpleNamespace(logprobs=None)])
    )

    with pytest.raises(LogprobScoringUnsupported):
        asyncio.run(
            gateway.complete_numeric_rating(
                role="supervisor", system_prompt="s", user_prompt="u", band=(1, 5)
            )
        )
    assert len(completions.calls) == 1  # a missing payload is not a transport retry


def test_gateway_does_not_retry_a_refused_judgement(tmp_path):
    gateway, completions = _logprob_gateway(
        tmp_path, SimpleNamespace(choices=[_choice(("5", 0.1))])
    )

    with pytest.raises(LogprobRefusalError):
        asyncio.run(
            gateway.complete_numeric_rating(
                role="supervisor", system_prompt="s", user_prompt="u", band=(1, 5)
            )
        )
    assert len(completions.calls) == 1


def test_gateway_without_choices_is_unsupported(tmp_path):
    gateway, _ = _logprob_gateway(tmp_path, SimpleNamespace(choices=[]))

    with pytest.raises(LogprobScoringUnsupported, match="no choices"):
        asyncio.run(
            gateway.complete_numeric_rating(
                role="supervisor", system_prompt="s", user_prompt="u", band=(1, 5)
            )
        )


def test_rating_transport_shares_the_retry_budget_and_archives_failures(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "psychsandbox.model_client.TRANSPORT_RETRY_WAIT", wait_none()
    )
    gateway, _ = _logprob_gateway(tmp_path, SimpleNamespace(choices=[]))
    gateway.max_attempts = 4
    calls = []

    async def failing(**request):
        calls.append(request)
        raise RuntimeError("upstream 500")

    gateway.client.chat.completions.create = failing

    with pytest.raises(RuntimeError, match="upstream 500"):
        asyncio.run(
            gateway.complete_numeric_rating(
                role="supervisor", system_prompt="s", user_prompt="u", band=(1, 5)
            )
        )

    assert len(calls) == 4
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in gateway.diagnostic_dir.glob("*.json")
    ]
    assert [record["kind"] for record in records] == ["api_error"]
    assert records[0]["output_schema"] == "NumericRating"
    assert records[0]["request"]["band"] == [1, 5]


class _StubGateway(ModelGateway):
    """A gateway that only implements structured output, like a test double."""

    provider_name = "stub"

    async def complete_structured(self, **kwargs):  # pragma: no cover - unused contract
        raise NotImplementedError


def test_base_gateway_refuses_logprob_scoring():
    gateway = _StubGateway()

    with pytest.raises(RuntimeError, match="does not support logprob scoring"):
        asyncio.run(
            gateway.complete_numeric_rating(
                role="supervisor", system_prompt="s", user_prompt="u", band=(1, 5)
            )
        )




class ScriptedSupervisorGateway(ModelGateway):
    """Offline supervisor double: item-level JSON plus a scripted distribution."""

    provider_name = "logprob-test"

    def __init__(
        self,
        *,
        item_score: float = 5.0,
        labels: list[str] | None = None,
        probabilities: dict[int, float] | None = None,
        rating_error: Exception | None = None,
    ) -> None:
        self.item_score = item_score
        self.labels = labels or [str(index) for index in range(1, 4)]
        self.probabilities = probabilities or {3: 0.5, 5: 0.5}
        self.rating_error = rating_error
        self.structured_calls: list[dict] = []
        self.rating_calls: list[dict] = []

    async def complete_structured(self, **kwargs):
        self.structured_calls.append(kwargs)
        return ScaleItems(
            items=[ScaleItem(item=label, score=self.item_score) for label in self.labels]
        )

    async def complete_numeric_rating(self, **kwargs):
        self.rating_calls.append(kwargs)
        if self.rating_error is not None:
            raise self.rating_error
        return rating_from_top_logprobs(
            [
                _token(str(token), probability)
                for token, probability in self.probabilities.items()
            ],
            band=kwargs["band"],
            mass_floor=kwargs["mass_floor"],
        )


def _supervisor(root, gateway, **kwargs) -> PsychEvalSupervisor:
    return PsychEvalSupervisor(gateway, Path(root) / "prompts" / "eval", **kwargs)


def _enabled(**overrides) -> LogprobScoringConfig:
    return LogprobScoringConfig(enabled=True, **overrides)


def _wai():
    return instrument_registry("cbt")["wai"]


def test_default_scoring_keeps_the_item_average(root):
    gateway = ScriptedSupervisorGateway(item_score=5.0)

    score = asyncio.run(_supervisor(root, gateway)._score(_wai(), "背景", "对话"))

    assert score.score == pytest.approx(10.0)
    assert score.item_scores == {"1": 5.0, "2": 5.0, "3": 5.0}
    assert gateway.rating_calls == []


def test_disabled_config_keeps_the_item_average(root):
    gateway = ScriptedSupervisorGateway(item_score=5.0)
    supervisor = _supervisor(root, gateway, logprob_scoring=LogprobScoringConfig(enabled=False))

    score = asyncio.run(supervisor._score(_wai(), "背景", "对话"))

    assert supervisor.logprob_scoring is None
    assert score.score == pytest.approx(10.0)
    assert gateway.rating_calls == []


def test_enabled_scoring_uses_the_weighted_rating_and_keeps_item_audit(root):
    gateway = ScriptedSupervisorGateway(item_score=5.0, probabilities={3: 0.5, 5: 0.5})
    supervisor = _supervisor(root, gateway, logprob_scoring=_enabled())

    score = asyncio.run(supervisor._score(_wai(), "背景标记INT", "对话标记DLG"))

    # Weighted rating 4.0 on the 1-5 band instead of the 5.0 item average.
    assert score.score == pytest.approx(7.5)
    assert score.item_scores == {"1": 5.0, "2": 5.0, "3": 5.0}
    assert len(gateway.structured_calls) == 1
    call = gateway.rating_calls[0]
    assert call["role"] == "supervisor"
    assert call["band"] == (1, 5)
    assert call["temperature"] == pytest.approx(0.7)
    assert call["top_logprobs"] == 20
    assert call["max_tokens"] == 16
    assert call["mass_floor"] == pytest.approx(0.25)
    assert "WAI" in call["system_prompt"]
    assert "只输出一个阿拉伯数字" in call["system_prompt"]
    # Intake and dialogue are carried once, not appended twice.
    assert call["system_prompt"].count("背景标记INT") == 1
    assert call["system_prompt"].count("对话标记DLG") == 1


@pytest.mark.parametrize(
    "error",
    [
        LogprobRefusalError(mass=0.1, band=(1, 5), distribution={3: 0.1}, mass_floor=0.25),
        LogprobScoringUnsupported("no payload"),
        RuntimeError("This gateway does not support logprob scoring"),
    ],
)
def test_scoring_failures_propagate_instead_of_falling_back(root, error):
    gateway = ScriptedSupervisorGateway(rating_error=error)
    supervisor = _supervisor(root, gateway, logprob_scoring=_enabled())

    with pytest.raises(type(error)):
        asyncio.run(supervisor._score(_wai(), "背景", "对话"))


def test_rating_scoring_requires_the_optional_mode(root):
    supervisor = _supervisor(root, ScriptedSupervisorGateway())

    with pytest.raises(RuntimeError, match="not enabled"):
        asyncio.run(supervisor.score_instrument_rating(_wai(), "背景", "对话"))


_PANAS_ORDER = [
    "Interested", "Excited", "Strong", "Enthusiastic", "Proud",
    "Alert", "Inspired", "Determined", "Attentive", "Active",
    "Distressed", "Upset", "Guilty", "Scared", "Hostile",
    "Irritable", "Ashamed", "Nervous", "Jittery", "Afraid",
]


def test_composite_instruments_keep_their_official_formulas(root):
    panas_gateway = ScriptedSupervisorGateway(item_score=5.0, labels=list(_PANAS_ORDER))
    panas = asyncio.run(
        _supervisor(root, panas_gateway, logprob_scoring=_enabled())._score(
            instrument_registry("cbt")["panas"], "背景", "对话"
        )
    )
    rro_gateway = ScriptedSupervisorGateway(item_score=5.0)
    counselor, client = asyncio.run(
        _supervisor(root, rro_gateway, logprob_scoring=_enabled())._score_rro("背景", "对话")
    )

    assert panas.score == pytest.approx(5.0)  # (10 - 10 + 10) / 2 for flat item scores
    assert 0.0 <= counselor.score <= 10.0
    assert 0.0 <= client.score <= 10.0
    assert panas_gateway.rating_calls == []
    assert rro_gateway.rating_calls == []


def _probe_record(root, gateway, **overrides):
    return asyncio.run(
        probe_instrument_rating(
            gateway,
            Path(root) / "prompts" / "eval",
            instrument=instrument_registry("cbt")["wai"],
            intake="背景",
            dialogue=PROBE_FIXTURE_DIALOGUE,
            config=LogprobScoringConfig(**overrides),
        )
    )


def test_probe_records_a_supported_endpoint(root, tmp_path):
    gateway = ScriptedSupervisorGateway(item_score=5.0, probabilities={3: 0.5, 5: 0.5})

    record = _probe_record(root, gateway)

    assert record["supported"] is True
    assert record["accepted"] is True
    assert record["band"] == [1, 5]
    assert record["mass"] == pytest.approx(1.0)
    assert record["rating"]["value"] == pytest.approx(4.0)
    assert record["distribution"] == {"3": pytest.approx(0.5), "5": pytest.approx(0.5)}
    assert record["dialogue_note"]  # the fixture is labelled, not passed off as data
    assert record["request"]["top_logprobs"] == 20
    path = write_probe_record(tmp_path / "invocation", record)
    assert path.name == "probe.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["rating"]["value"] == pytest.approx(4.0)


def test_probe_records_an_endpoint_without_logprobs(root):
    gateway = ScriptedSupervisorGateway(rating_error=LogprobScoringUnsupported("no payload"))

    record = _probe_record(root, gateway)

    assert record["supported"] is False
    assert record["accepted"] is False
    assert record["rating"] is None
    assert "unsupported" in record["error"]


def test_probe_records_a_refused_judgement(root):
    gateway = ScriptedSupervisorGateway(
        rating_error=LogprobRefusalError(
            mass=0.1, band=(1, 5), distribution={3: 0.1}, mass_floor=0.25
        )
    )

    record = _probe_record(root, gateway)

    assert record["supported"] is True
    assert record["accepted"] is False
    assert record["rating"] is None
    assert record["mass"] == pytest.approx(0.1)
    assert record["distribution"]["3"] == pytest.approx(0.1)
    assert "refused" in record["error"]


def test_probe_uses_its_own_config_not_a_disabled_block(root):
    gateway = ScriptedSupervisorGateway(item_score=5.0)

    record = _probe_record(root, gateway, top_logprobs=5, max_tokens=4, temperature=0.2)

    assert record["accepted"] is True
    assert gateway.rating_calls[0]["top_logprobs"] == 5
    assert gateway.rating_calls[0]["max_tokens"] == 4
    assert gateway.rating_calls[0]["temperature"] == pytest.approx(0.2)



def test_probe_cli_keeps_one_directory_per_invocation(
    monkeypatch, tmp_path, root, repository, sample_case
):
    from psychsandbox import cli

    gateway = ScriptedSupervisorGateway(item_score=5.0)
    monkeypatch.setattr(cli, "create_gateway", lambda **_kwargs: gateway)
    monkeypatch.setattr(cli.CaseRepository, "from_project", lambda _root: repository)
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runtime"))
    args = cli.build_parser().parse_args(
        [
            "probe", "logprob-scoring",
            "--case", sample_case.case_id,
            "--instrument", "wai",
            "--json",
        ]
    )

    assert asyncio.run(cli._probe(args, Path(root))) == 0
    assert asyncio.run(cli._probe(args, Path(root))) == 0

    directories = sorted((tmp_path / "runtime").glob("*__probe-logprob-scoring__*"))
    assert len(directories) == 2
    for directory in directories:
        metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        assert metadata["status"] == "completed"
        assert metadata["instrument"] == "wai"
        assert metadata["dialogue_source"] == "fixture"
        assert (directory / "probe.json").is_file()


def test_probe_cli_reports_an_unsupported_endpoint(
    monkeypatch, tmp_path, root, repository, sample_case
):
    from psychsandbox import cli

    gateway = ScriptedSupervisorGateway(rating_error=LogprobScoringUnsupported("no payload"))
    monkeypatch.setattr(cli, "create_gateway", lambda **_kwargs: gateway)
    monkeypatch.setattr(cli.CaseRepository, "from_project", lambda _root: repository)
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runtime"))
    args = cli.build_parser().parse_args(
        ["probe", "logprob-scoring", "--case", sample_case.case_id, "--instrument", "wai"]
    )

    assert asyncio.run(cli._probe(args, Path(root))) == 1
    directory = next((tmp_path / "runtime").glob("*__probe-logprob-scoring__*"))
    metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "inconclusive"
    assert metadata["supported"] is False
    assert (directory / "probe.json").is_file()


def test_probe_cli_rejects_an_unknown_instrument(
    monkeypatch, tmp_path, root, repository, sample_case
):
    from psychsandbox import cli

    monkeypatch.setattr(cli.CaseRepository, "from_project", lambda _root: repository)
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runtime"))
    args = cli.build_parser().parse_args(
        ["probe", "logprob-scoring", "--case", sample_case.case_id, "--instrument", "not-a-scale"]
    )

    with pytest.raises(ValueError, match="unknown instrument"):
        asyncio.run(cli._probe(args, Path(root)))
    assert not list((tmp_path / "runtime").glob("*__probe-logprob-scoring__*"))




def test_runtime_config_exposes_the_scoring_block(root):
    from psychsandbox.config import default_config

    block = default_config(Path(root)).logprob_scoring

    assert block.enabled is True
    assert SandboxConfig(project_root=Path(root)).logprob_scoring.enabled is True
    assert block.mass_floor == pytest.approx(0.25)
    assert (block.top_logprobs, block.max_tokens, block.temperature) == (20, 16, 0.7)


def test_cli_flag_enables_the_scoring_block(root):
    from psychsandbox import cli

    args = cli.build_parser().parse_args(
        ["--root", str(root), "simulate", "--case", "psycheval-cbt-001", "--logprob-scoring"]
    )

    assert cli._config(args).logprob_scoring.enabled is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"mass_floor": 0.0},
        {"mass_floor": 1.5},
        {"top_logprobs": 21},
        {"max_tokens": 0},
        {"temperature": 3.0},
    ],
)
def test_scoring_config_validates_its_budget(overrides):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LogprobScoringConfig(**overrides)

class ItemAverageOnlyGateway(DeterministicGateway):
    """Offline double that stays item-average only: no logprob capability."""

    complete_numeric_rating = ModelGateway.complete_numeric_rating


def test_default_config_fails_loudly_without_substituting_item_averages(
    root, tmp_path, repository
):
    config = SandboxConfig(
        project_root=root,
        max_turns_per_session=1,
        database_path=tmp_path / "default-logprob.sqlite3",
        trace_dir=tmp_path / "default-logprob-traces",
    )
    sandbox = CounselingSandbox(
        config, gateway=ItemAverageOnlyGateway(), repository=repository
    )
    messages: list[str] = []
    try:
        result = asyncio.run(
            sandbox.run_case(
                "psycheval-cbt-001", session_count=1, progress_callback=messages.append
            )
        )
        assert config.logprob_scoring.enabled is True
        assert result.holistic_report is None
        assert sandbox.store.load_holistic_report(result.run_id) is None
        assert any("整体督导评估失败" in message for message in messages)
    finally:
        sandbox.store.close()

