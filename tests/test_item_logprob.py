from __future__ import annotations

import asyncio
import json
import math
from types import SimpleNamespace as NS

import pytest

from psychsandbox.domain import LogprobScoringConfig, SandboxConfig, ScaleScore
from psychsandbox.evaluation.item_logprob import BatchScoringError, ratings_from_choice
from psychsandbox.evaluation.psycheval_supervisor import PsychEvalSupervisor, instrument_registry
from psychsandbox.logprob import LogprobScoringUnsupported, logprob_band, rating_from_top_logprobs
from tests.test_logprob_scoring import ScriptedSupervisorGateway, _logprob_gateway


def choice(text, *, byte_tokens=False, probabilities=None):
    probabilities = probabilities or {2: 0.4, 4: 0.6}
    tokens = []
    for char in text:
        for piece in ([bytes([b]) for b in char.encode()] if byte_tokens else [char.encode()]):
            tokens.append(NS(token=char, bytes=list(piece), logprob=math.log(probabilities.get(int(char), .1))
                             if char.isascii() and char.isdigit() else 0.0,
                             top_logprobs=[NS(token=str(k), logprob=math.log(v)) for k, v in probabilities.items()]))
    return NS(finish_reason="stop", message=NS(content=text), logprobs=NS(content=tokens))


def batch(payload=None, **kwargs):
    return choice(json.dumps(payload or {"items": [{"item": "1", "score": 2}]},
                             ensure_ascii=False), **kwargs)


def score(response, ids=("1",), band=(0, 6)):
    return ratings_from_choice(response, expected_ids=ids, band=band)


def test_score_path_ignores_numbers_in_ids_and_escaped_evidence():
    response = batch({"items": [{"evidence_pos": ['中文 9，\"score\":9'],
                                  "score": 2, "item": "1"}]}, byte_tokens=True)
    result = score(response)
    assert result.items.items[0].score == pytest.approx(3.2)
    assert result.records["1"]["mass"] == pytest.approx(1)
    assert result.records["1"]["sampled_score"] == 2


def test_reordered_items_are_scored_by_id():
    result = score(batch({"items": [{"item": "2", "score": 4}, {"item": "1", "score": 2}]}), ids=("1", "2"))
    assert set(result.records) == {"1", "2"}
    assert all(item.score == pytest.approx(3.2) for item in result.items.items)


@pytest.mark.parametrize("text", [
    '{"items":[{"item":"1","score":2,"score":4}]}',
    '{"items":[{"item":"1","score":2}],"items":[]}',
    '{"items":[{"item":"1","score":2},{"item":"1","score":4}]}',
    '{"items":[]}', '{"items":[{"item":"2","score":2}]}',
    '{"items":[{"item":"1","score":2.0}]}',
    '{"items":[{"item":"1","score":"2"}]}',
    '{"items":[{"item":"1","score":true}]}',
    '{"items":[{"item":"1","score":9}]}',
    '{"items":[{"item":"1","score":NaN}]}',
    '{"items":[{"item":"1","score":2}]} trailing',
    '{"items":[{"item":"1","score":2}',
])
def test_invalid_json_and_item_contracts_fail_without_score(text):
    with pytest.raises(BatchScoringError):
        score(choice(text))


def test_merged_score_token_is_not_scored_as_an_integer():
    response = batch()
    tokens = response.logprobs.content
    index = response.message.content.index('2')
    tokens[index].bytes += tokens[index + 1].bytes
    tokens[index].token += tokens[index + 1].token
    del tokens[index + 1]
    with pytest.raises(BatchScoringError) as error:
        score(response)
    assert "JSON syntax" in error.value.records["1"]["error"]


def test_missing_top_logprobs_fails_even_with_sampled_score():
    response = batch()
    response.logprobs.content[response.message.content.index('2')].top_logprobs = []
    with pytest.raises(BatchScoringError):
        score(response)


@pytest.mark.parametrize("field,value", [("token", "wrong"), ("logprob", math.nan), ("logprob", .1)])
def test_sampled_score_metadata_must_be_valid_even_when_in_top(field, value):
    response = batch()
    setattr(response.logprobs.content[response.message.content.index('2')], field, value)
    with pytest.raises(BatchScoringError):
        score(response)


def test_missing_sampled_candidate_is_added_exactly_once():
    response = batch(probabilities={4: .6})
    result = score(response)
    assert result.records["1"]["mass"] == pytest.approx(.7)
    assert result.items.items[0].score == pytest.approx(2.6 / .7)


def test_refusal_retains_each_items_diagnostic_and_invalidates_batch():
    with pytest.raises(BatchScoringError) as error:
        score(batch(probabilities={2: .1}))
    record = error.value.records["1"]
    assert record["accepted"] is False
    assert record["mass"] == pytest.approx(.1)
    assert error.value.supported is True


@pytest.mark.parametrize("attribute,value", [("finish_reason", "length"), ("logprobs", None)])
def test_truncation_and_missing_payload_fail(attribute, value):
    response = batch()
    setattr(response, attribute, value)
    with pytest.raises(BatchScoringError):
        score(response)


def test_only_recognized_terminal_eos_can_be_excluded():
    response = batch()
    marker = '<｜end▁of▁sentence｜>'
    response.logprobs.content.append(NS(token=marker, bytes=list(marker.encode())))
    assert score(response).items.items[0].score == pytest.approx(3.2)
    response.logprobs.content[-1] = NS(token='extra', bytes=list(b'extra'))
    with pytest.raises(BatchScoringError, match="reconstruct"):
        score(response)


@pytest.mark.parametrize("number", [math.nan, math.inf, .1, "bad"])
def test_invalid_logprobs_are_not_clamped(number):
    with pytest.raises(LogprobScoringUnsupported):
        rating_from_top_logprobs([NS(token="2", logprob=number)], band=(0, 6))


def test_negative_infinity_is_zero_and_duplicate_token_is_not_double_counted():
    token = NS(token="2", logprob=math.log(.4))
    result = rating_from_top_logprobs([token, token, NS(token="3", logprob=-math.inf)], band=(0, 6))
    assert result.mass == pytest.approx(.4)


def test_excess_or_conflicting_probability_mass_fails():
    for entries in ([NS(token="2", logprob=0), NS(token="4", logprob=0)],
                    [NS(token="2", logprob=0), NS(token="2", logprob=-1)]):
        with pytest.raises(LogprobScoringUnsupported):
            rating_from_top_logprobs(entries, band=(0, 6))


@pytest.mark.parametrize("band", [(10, 11), (-1, 5), (4, 4), (6, 0), (math.inf, 6)])
def test_strict_single_digit_band(band):
    with pytest.raises(ValueError):
        logprob_band(band)


def test_batch_gateway_contract(tmp_path):
    gateway, completions = _logprob_gateway(tmp_path, NS(choices=[batch()]))
    result = asyncio.run(gateway.complete_item_ratings(role="supervisor", system_prompt="JSON",
                         input_payload={}, expected_ids=("1",), band=(0, 6)))
    assert result.items.items[0].score == pytest.approx(3.2)
    request = completions.calls[0]
    assert request["temperature"] == 0
    assert request["max_tokens"] == 8192
    assert request["top_logprobs"] == 20
    assert request["logprobs"] is True
    assert "response_format" not in request and "tools" not in request


@pytest.mark.parametrize("therapy", ["cbt", "behavioral", "humanistic_existential", "psychodynamic", "postmodern"])
def test_full_therapy_batches_cover_every_item_and_preserve_formula(root, therapy):
    gateway = ScriptedSupervisorGateway(probabilities={2: .4, 4: .6})
    supervisor = PsychEvalSupervisor(gateway, root / 'prompts/eval', logprob_scoring=LogprobScoringConfig(enabled=True))
    groups = asyncio.run(supervisor._score_instruments(therapy, "背景", "对话"))
    scores = [item for group in groups for item in group]
    assert all(item.item_logprobs for item in scores)
    assert gateway.structured_calls == []
    assert all(len(item.item_scores) == len(item.item_logprobs) for item in scores)
    assert next(item for item in scores if item.name == 'panas').score == 5
    assert len(next(item for item in scores if item.name == 'custom_dim').item_scores) == 65
    assert len(next(item for item in scores if item.name == 'scl90').item_scores) == 90


def test_stale_catalog_rejected_before_judgement(root, tmp_path):
    import shutil
    shutil.copytree(root / 'prompts/eval', tmp_path / 'eval')
    path = tmp_path / 'eval/wai/wai.txt'
    path.write_text('changed prompt', encoding='utf-8')
    gateway = ScriptedSupervisorGateway()
    supervisor = PsychEvalSupervisor(gateway, tmp_path / 'eval', logprob_scoring=LogprobScoringConfig(enabled=True))
    with pytest.raises(ValueError, match='stale'):
        asyncio.run(supervisor._score(instrument_registry('cbt')['wai'], 'i', 'd'))
    assert gateway.rating_calls == []


def test_legacy_scale_scores_load_without_audit():
    score = ScaleScore(name="wai", level="counselor", category="therapy_shared",
                       direction="higher_better", score=5, item_scores={"1": 3})
    assert score.item_logprobs == {}


def test_default_temperatures_and_explicit_override(root):
    from psychsandbox.config import default_config
    for config in (SandboxConfig(project_root=root), default_config(root)):
        assert (config.temperature_client, config.temperature_counselor, config.temperature_supervisor,
                config.temperature_client_planner, config.temperature_control) == (.7, .9, 0, 0, 0)
        assert config.rft.judge_temperature == config.logprob_scoring.temperature == 0
    assert SandboxConfig(project_root=root, temperature_control=.2).temperature_control == .2


@pytest.mark.parametrize("rft", [False, True])
def test_all_runtime_calls_use_task_temperature(root, tmp_path, repository, rft):
    from psychsandbox.runtime import CounselingSandbox
    from psychsandbox.domain import RFTConfig
    from tests.test_rollout_runtime import RolloutGateway

    class RecordingGateway(RolloutGateway):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def complete_structured(self, **kwargs):
            self.calls.append((kwargs["output_schema"].__name__, kwargs["temperature"]))
            return await super().complete_structured(**kwargs)

    gateway = RecordingGateway()
    config = SandboxConfig(project_root=root, max_turns_per_session=2,
                           trace_dir=tmp_path / 'runs', database_path=tmp_path / 'store.sqlite3',
                           logprob_scoring=LogprobScoringConfig(enabled=False),
                           rft=RFTConfig(enabled=rft, candidates=2, min_eligible=2))
    sandbox = CounselingSandbox(config, gateway=gateway, repository=repository)
    try:
        asyncio.run(sandbox.run_case('psycheval-cbt-001', session_count=1))
        assert gateway.calls
        for schema, temperature in gateway.calls:
            expected = .9 if schema == 'CounselorActorOutput' else .7 if schema == 'ClientUtterance' else 0
            assert temperature == expected, schema
        trace = json.loads((sandbox.run_dir / 'trajectory.jsonl').read_text(encoding='utf-8'))
        assert trace['model_config_snapshot']['temperature_control'] == 0
        assert trace['model_config_snapshot']['scoring_method'] == 'discrete_items_v1'
    finally:
        sandbox.store.close()


def test_rft_resume_rejects_historical_scoring_method(root, tmp_path, repository):
    from tests.test_rollout_runtime import sandbox_for, RolloutGateway

    sandbox = sandbox_for(root, tmp_path, RolloutGateway(), repository)
    try:
        first = asyncio.run(sandbox.run_case('psycheval-cbt-001', session_count=1))
        row = sandbox.store.load_run_metadata(first.run_id)
        saved = row['config']
        saved['logprob_scoring'] = {'enabled': True}  # historical overall-rating method
        sandbox.store.connection.execute('UPDATE experiment_runs SET config_json=? WHERE run_id=?',
                                         (json.dumps(saved), first.run_id))
        sandbox.store.connection.commit()
        sandbox.config.logprob_scoring = LogprobScoringConfig(enabled=True)
        before = (sandbox.run_dir / 'trajectory.jsonl').read_bytes()
        with pytest.raises(ValueError, match='scoring method'):
            asyncio.run(sandbox.run_case(first.case_id, session_count=2, resume_run_id=first.run_id))
        assert (sandbox.run_dir / 'trajectory.jsonl').read_bytes() == before
        assert len(sandbox.store.load_sessions(first.run_id)) == 1
    finally:
        sandbox.store.close()


def test_shared_supervisor_keeps_concurrent_candidate_audits_separate(root):
    class InterleavedGateway(ScriptedSupervisorGateway):
        async def complete_item_ratings(self, **kwargs):
            await asyncio.sleep(0)
            return await super().complete_item_ratings(**kwargs)

    supervisor = PsychEvalSupervisor(InterleavedGateway(), root / 'prompts/eval',
                                    logprob_scoring=LogprobScoringConfig(enabled=True))

    async def scenario():
        registry = instrument_registry('cbt')
        return await asyncio.gather(supervisor._score(registry['ctrs'], 'i', 'candidate A'),
                                    supervisor._score(registry['custom_dim'], 'i', 'candidate B'))

    left, right = asyncio.run(scenario())
    assert len(left.item_logprobs) == 6
    assert len(right.item_logprobs) == 65
    assert all(key.startswith('ctrs/') for key in left.item_logprobs)
    assert all(key.startswith('custom_dim/') for key in right.item_logprobs)


def test_cli_explicitly_disables_default_logprob(root):
    from psychsandbox.cli import build_parser, _config
    args = build_parser().parse_args(['--root', str(root), 'simulate', '--case', 'psycheval-cbt-001',
                                     '--no-logprob-scoring'])
    assert _config(args).logprob_scoring.enabled is False


def test_catalog_covers_exact_prompt_tree_and_registered_bands(root):
    import hashlib
    catalog = json.loads((root / 'prompts/eval/_scoring/item_catalog.json').read_text(encoding='utf-8'))
    files = {p.relative_to(root / 'prompts/eval').as_posix() for p in (root / 'prompts/eval').rglob('*.txt')}
    assert set(catalog) == files
    for source, entry in catalog.items():
        assert len(set(entry['ids'])) == len(entry['ids']) > 0
        assert entry['source'] == 'prompts/eval/' + source
        assert hashlib.sha256((root / entry['source']).read_text(encoding="utf-8").encode("utf-8")).hexdigest() == entry['sha256']
    for therapy in ['cbt', 'behavioral', 'humanistic_existential', 'psychodynamic', 'postmodern']:
        supervisor = PsychEvalSupervisor(ScriptedSupervisorGateway(), root / 'prompts/eval')
        for instrument in instrument_registry(therapy).values():
            for name in instrument.prompt_files:
                source = supervisor._resolve_prompt(name).relative_to(root / 'prompts/eval').as_posix()
                assert tuple(catalog[source]['band']) == instrument.scale
