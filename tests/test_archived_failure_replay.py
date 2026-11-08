"""Optional offline replay of retained local failures; no remote model calls."""
import asyncio
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from psychsandbox.datasets import CaseRepository
from psychsandbox.domain import CounselingCase, SessionRecord, SessionMemory, SessionPlan, ClientState, RFTConfig, RolloutSelection
from psychsandbox.evaluation.safety_gate import SessionSafetyGate
from psychsandbox.runtime.rollout import SessionRolloutRunner
from psychsandbox.runtime.memory_pipeline import _SessionSummaryWrapper
from tests.test_model_client import _gateway


def test_retained_failures_replay_without_api(tmp_path):
    root = Path(__file__).resolve().parents[1]
    runtime = root / 'runs/runtime'
    db_path = runtime / 'psychsandbox.sqlite3'
    if not db_path.exists():
        pytest.skip('Retained production artifacts are optional')
    db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    try:
        for rid, expected in [('run-8b9eda344107', [True, True, False]),
                              ('run-8f5de508160b', [True, True, True]),
                              ('run-ce05e55a22b8', [True, True, True])]:
            dirs = list(runtime.glob('*' + rid))
            if not dirs:
                pytest.skip('Retained failures not present')
            row = db.execute('select case_id from experiment_runs where run_id=?', (rid,)).fetchone()
            case = CounselingCase.model_validate_json(db.execute('select case_json from cases where case_id=?', row).fetchone()[0])
            batch = next(p.parent for p in dirs[0].glob('rollouts/*/selection.json')
                         if all(c['status'] == 'rejected' for c in json.loads(p.read_text('utf-8'))['candidates']))
            context = json.loads((batch / 'input.json').read_text('utf-8'))
            memory = SessionMemory.model_validate(context['memory_before'])
            actual = []
            for path in sorted(batch.glob('candidate-*.json')):
                session = SessionRecord.model_validate(json.loads(path.read_text('utf-8'))['session'])
                actual.append(SessionSafetyGate().evaluate(session, case, memory).passed)
            assert actual == expected
        rid = 'run-492d3dbccb98'
        directory = next(runtime.glob('*' + rid))
        batch = next(directory.glob('rollouts/s008__*'))
        context = json.loads((batch / 'input.json').read_text('utf-8'))
        def batches(run_id):
            return [RolloutSelection.model_validate_json(r[0]) for r in db.execute(
                'select selection_json from rollout_batches where run_id=?', (run_id,))]
        def candidates(batch_id):
            return [json.loads(r[0]) for r in db.execute(
                'select candidate_json from rollout_candidates where batch_id=?', (batch_id,))]
        case = CounselingCase.model_validate_json(db.execute("select case_json from cases where case_id='psycheval-bt-030'").fetchone()[0])
        previous = SessionRecord.model_validate_json(db.execute('select session_json from sessions where run_id=? and session_index=7', (rid,)).fetchone()[0])
        store = SimpleNamespace(load_rollout_batches=batches, load_rollout_candidates=candidates)
        runner = SessionRolloutRunner(RFTConfig.model_validate(context['config']), None, store, directory)
        async def forbidden(*args):
            pytest.fail('Replay must not generate or score')
        session, memory = asyncio.run(runner.run(run_id=rid,
            plan=SessionPlan.model_validate(context['plan']), memory=SessionMemory.model_validate(context['memory_before']),
            state=ClientState.model_validate(context['initial_state']), case=case, previous=previous,
            generate=forbidden, notify=lambda _: None))
        assert session.rollout_selection.winner_index == 3
        assert session.session_index == 8
        diagnostics = [json.loads(p.read_text('utf-8')) for p in directory.glob('diagnostics/**/*.json')]
        failure = next(d for d in diagnostics if 'engagement_assessment' in d.get('error', ''))
        gateway, transport = _gateway(tmp_path, [failure['raw_response']])
        result = asyncio.run(gateway.complete_structured(role='summarizer', system_prompt='summary',
            input_payload={}, output_schema=_SessionSummaryWrapper, temperature=0))
        assert result.session_summary.session_index == 8
        assert len(transport.calls) == 1
        cases = CaseRepository.from_project(root).list()
        assert len(cases) == 341
        assert all(any(c.isalnum() for c in n.source_text) for case in cases for n in case.profile.evidence_nodes)
    finally:
        db.close()
