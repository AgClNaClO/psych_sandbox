import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { JobItem, RunDetail, SimulationProgress } from '../src/types.ts';
import { newerProgress, progressView } from '../src/utils/progress.ts';

const progress: SimulationProgress = { phase: 'generating', session_index: 4, sessions_total: 7,
  sessions_completed: 3, elapsed: 120, updated_at: '', attempt: 1, revision: 5,
  candidates_total: 3, candidates: [], scoring: null };
const job = { job_id: 'job-one', attempt: 1, status: 'running', payload: { session_count: 7 } } as JobItem;

test('generation and scoring stay visible together while candidates overlap', () => {
  const overlapping = { ...progress,
    candidates: [{ session_index: 4, turn_index: 2, total_turns: 20, elapsed: 5, eta: 45, label: '2/3' }],
    scoring: { session_index: 4, instruments_done: 1, instruments_total: 9,
      candidates_scored: 0, candidates_total: 1, elapsed: 2, eta: 16, label: '评分', last_instrument: 'wai' } };
  for (const phase of ['generating', 'scoring']) {
    const view = progressView(job, null, { ...overlapping, phase });
    assert.equal(view.title, '对话生成与候选评估');
    assert.equal(view.showGeneration, true);
    assert.equal(view.showScoring, true);
  }
  const finished = progressView(job, null, { ...overlapping, phase: 'consolidating' });
  assert.equal(finished.showGeneration, false);
  assert.equal(finished.showScoring, false);
});

test('poll snapshots and replay cannot replace a newer attempt or newer live progress', () => {
  assert.equal(newerProgress(progress, { ...progress, revision: 4 }), progress);
  assert.equal(newerProgress({ ...progress, attempt: 2, revision: 1 }, progress)?.attempt, 2);
  assert.equal(progressView({ ...job, attempt: 2 }, null, progress).progress, null);
  assert.equal(progressView(job, null, progress).completed, 3);
});

test('queued, stopped and failed states remain visible without pretending to reach 100 percent', () => {
  assert.equal(progressView({ ...job, status: 'queued' }, null).title, '排队等待执行');
  assert.equal(progressView({ ...job, status: 'stopped' }, null, progress).completed, 3);
  assert.equal(progressView({ ...job, status: 'failed' }, null, progress).running, false);
  assert.equal(progressView({ ...job, status: 'failed' }, null, progress).error, true);
  assert.equal(progressView({ ...job, stop_requested: true }, null, progress).title, '等待当前会谈提交后停止');
});

test('legacy jobs do not show an invented turn count or total', () => {
  const view = progressView({ ...job, payload: {} });
  assert.equal(view.total, null);
  assert.equal(view.progress, null);
  assert.equal(view.title, '实验进行中');
});

test('a new queued experiment never inherits the count of an unrelated historical run', () => {
  const history = { run_id: 'older-run', sessions: [{}, {}, {}], requested_sessions: 3, status: 'completed' } as RunDetail;
  assert.equal(progressView({ ...job, run_id: null, status: 'queued' }, history).completed, 0);
  assert.equal(progressView({ ...job, run_id: 'older-run', status: 'succeeded' }, { ...history, status: 'safety_hold' }).title, '安全暂停');
});
