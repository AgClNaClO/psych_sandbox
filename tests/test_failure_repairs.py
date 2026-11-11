import asyncio

import pytest

from psychsandbox.datasets.profile_compiler import AtomicSpan, PsychEvalProfileCompiler
from psychsandbox.evaluation.safety_gate import SessionSafetyGate
from psychsandbox.domain import DisclosureItem
from tests.test_rollout_runtime import setup as setup, runner_for, run, session_for, Judge
from tests.test_model_client import _gateway
from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper
import json
import os
from pathlib import Path
from psychsandbox.artifacts import write_json


def test_atomic_checkpoint_supports_long_nested_paths(tmp_path):
    parent = tmp_path
    while len(str(parent)) < 260:
        parent = parent / ('nested-' + 'x' * 30)
    target = parent / 'extraction-BranchChoice-1.json'
    write_json(target, {'status': 'rejected'})
    # Windows readers also require extended syntax beyond MAX_PATH.
    readable = Path('\\\\?\\' + str(target.resolve())) if os.name == 'nt' else target
    assert json.loads(readable.read_text('utf-8')) == {'status': 'rejected'}
    write_json(target, {'status': 'accepted'})
    assert json.loads(readable.read_text('utf-8')) == {'status': 'accepted'}
    assert not list(readable.parent.glob('.tmp-*'))


def test_atomic_checkpoint_retries_transient_windows_lock(tmp_path, monkeypatch):
    original = Path.replace
    attempts = []
    def replace(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            error = PermissionError('temporarily locked')
            error.winerror = 5
            raise error
        return original(source, target)
    monkeypatch.setattr(Path, 'replace', replace)
    target = tmp_path / 'checkpoint.json'
    write_json(target, {'selected': 3})
    assert json.loads(target.read_text('utf-8')) == {'selected': 3}
    assert len(attempts) == 2


def test_atomic_checkpoint_permanent_lock_preserves_previous(tmp_path, monkeypatch):
    target = tmp_path / 'checkpoint.json'
    write_json(target, {'selected': 1})
    attempts = []
    def replace(source, destination):
        attempts.append(destination)
        error = PermissionError('permanent lock')
        error.winerror = 5
        raise error
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr('time.sleep', lambda _: None)
    with pytest.raises(PermissionError):
        write_json(target, {'selected': 3})
    assert len(attempts) == 5
    assert json.loads(target.read_text('utf-8')) == {'selected': 1}


@pytest.mark.parametrize('extra', ['', 'substantive', None])
@pytest.mark.parametrize('field', ['engagement_assessment', 'completion_status_note', 'objective_notes'])
def test_summary_empty_extension_repair_is_narrow(tmp_path, extra, field):
    assessment = {'completion_status': '部分完成', field: extra}
    payload = {'session_summary': {'session_index': 8, 'goal_assessment': assessment}}
    gateway, transport = _gateway(tmp_path, [json.dumps(payload)] * 3)
    gateway.json_schema_roles = set()
    gateway.json_object_roles = {'summarizer'}
    async def invoke():
        return await gateway.complete_structured(role='summarizer', system_prompt='summary',
            input_payload={}, output_schema=_SessionSummaryWrapper, temperature=0)
    if extra == '':
        result = asyncio.run(invoke()).session_summary
        assert result.session_index == 8
        assert result.goal_assessment.completion_status == '部分完成'
        assert len(transport.calls) == 1
        assert 'local_repair' in next(gateway.diagnostic_dir.glob('*.json')).read_text('utf-8')
    else:
        with pytest.raises(ValueError):
            asyncio.run(invoke())


@pytest.mark.parametrize('unknown_field', [False, True])
def test_summary_stray_punctuation_repair_preserves_strict_validation(tmp_path, unknown_field):
    summary = {
        'session_index': 1,
        'goal_assessment': {'evidence_and_analysis': '已核对实际发生的事件。'},
        'client_state_analysis': {'affective_state': '能描述感受。'},
        'completed_items': ['确认当前困扰'],
        'pending_items': ['跟进关系中的感受'],
    }
    first_summary = {
        **summary, 'goal_assessment': {**summary['goal_assessment'], 'completion': '部分完成'},
    }
    first = json.dumps({'session_summary': first_summary}, ensure_ascii=False)
    if unknown_field:
        summary['unexpected'] = '有内容的未知字段'
    repaired = {'session_summary': summary}
    malformed = json.dumps(repaired, ensure_ascii=False, separators=(',', ':')).replace(
        '"},"client_state_analysis"', '","},"client_state_analysis"', 1,
    )
    gateway, transport = _gateway(tmp_path, [first, malformed, malformed])

    async def invoke():
        return await gateway.complete_structured(
            role='summarizer', system_prompt='summary', input_payload={},
            output_schema=_SessionSummaryWrapper, temperature=0,
        )

    if unknown_field:
        with pytest.raises(ValueError):
            asyncio.run(invoke())
    else:
        assert asyncio.run(invoke()) == _SessionSummaryWrapper.model_validate(repaired)
    assert len(transport.calls) == (3 if unknown_field else 2)
    records = [json.loads(p.read_text('utf-8')) for p in gateway.diagnostic_dir.glob('*.json')]
    retry = next(record for record in records if record['attempt'] == 2)
    assert retry['raw_response'] == malformed
    assert retry['error'].startswith('local_repair:') is (not unknown_field)


def test_compiler_discards_punctuation_atoms():
    parts = PsychEvalProfileCompiler().compile(
        case_id='case', info={'growth_experiences': ['经历。']}, therapy_code='het', plans=[],
        free_text_spans={'client_info.growth_experiences[0]': [
            AtomicSpan(0, 2, '经历'), AtomicSpan(2, 3, '。'),
        ]},
    )
    assert [n.source_text for n in parts.evidence_nodes] == ['经历']
    assert [n.content for n in parts.disclosure_items] == ['经历']


def test_gate_ignores_legacy_punctuation(setup):
    case, memory, plan, state, *_ = setup
    case.profile.disclosure_items = [DisclosureItem(item_id='bad', evidence_ids=[], content='。', category='growth_experience')]
    session = session_for(1, plan, state, text='你好。')
    assert SessionSafetyGate().evaluate(session, case, memory).passed


def test_deterministic_gate_precedes_judge(setup):
    case, _, plan, *_ = setup
    case.profile.disclosure_items = [DisclosureItem(item_id='secret', evidence_ids=[], content='去年秘密离职', category='growth_experience')]
    judge = Judge()
    async def generate(index, memory, state, checkpoint):
        return session_for(index, plan, state, text='去年秘密离职' if index == 3 else None)
    session, _ = asyncio.run(run(runner_for(setup, judge, resample_limit=0), setup, generate))
    assert len(judge.calls) == 2
    assert session.rollout_selection.winner_index == 2


def test_selected_candidate_reused_without_generation_or_scoring(setup):
    _, _, plan, *_ = setup
    judge = Judge()
    async def generate(index, memory, state, checkpoint):
        return session_for(index, plan, state)
    runner = runner_for(setup, judge)
    first, _ = asyncio.run(run(runner, setup, generate))
    async def forbidden(*args):
        pytest.fail('selected dialogue must not be regenerated')
    second, _ = asyncio.run(run(runner, setup, forbidden))
    assert first.session_id == second.session_id
    assert len(judge.calls) == 3
