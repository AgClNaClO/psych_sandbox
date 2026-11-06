import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { RunDetail } from '../src/types.ts';
import { getSessionResumePayload } from '../src/utils/simulation.ts';

const failedRun: RunDetail = {
  run_id: 'run-failed', case_id: 'original-case', therapy: 'bt', seed: 0,
  provider: 'api', status: 'failed', created_at: '', completed_at: null,
  requested_sessions: 7,
  sessions: [1, 2, 3].map((session_index) => ({ session_index, turns: [] })),
  config: { session_count: 1, max_turns_per_session: 42, rft: { enabled: true, candidates: 3 } },
};

test('failed/stopped runs resume the original total and identity without overriding saved settings', () => {
  for (const status of ['failed', 'stopped']) {
    assert.deepEqual(getSessionResumePayload({ ...failedRun, status }), {
      resume_run_id: 'run-failed', case_id: 'original-case', therapy: 'bt', seed: 0, session_count: 7,
    });
  }
  assert.equal(getSessionResumePayload({ ...failedRun, sessions: [] })?.session_count, 7);
  assert.equal(getSessionResumePayload({ ...failedRun, requested_sessions: 3 })?.session_count, 3);
});

test('missing/invalid recovery metadata and closed or unavailable runs cannot be resumed', () => {
  for (const requested_sessions of [undefined, null, 0, 2, 101, 3.5]) {
    assert.equal(getSessionResumePayload({ ...failedRun, requested_sessions }), null);
  }
  for (const status of ['running', 'completed', 'safety_hold', 'deleting']) {
    assert.equal(getSessionResumePayload({ ...failedRun, status }), null);
  }
  assert.equal(getSessionResumePayload({ ...failedRun, sessions: [
    { session_index: 1, turns: [], longitudinal_report: { stage_action: 'close' } },
  ] }), null);
});
