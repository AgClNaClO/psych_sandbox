import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { experimentApi } from '../src/services/skillExperiment.ts';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test('experiment mutations use their own namespace and pin a version', async () => {
  let capturedUrl = '', body: Record<string, unknown> = {};
  globalThis.fetch = async (url, options) => {
    capturedUrl = String(url);
    body = JSON.parse(String(options?.body));
    return new Response('{}');
  };
  await experimentApi.job('exp-0123456789ab', 'replay', 2, { message_count: 4 });
  assert.equal(capturedUrl, '/api/skill-experiments/exp-0123456789ab/jobs');
  assert.deepEqual(body, { kind: 'replay', version: 2, message_count: 4 });
  await experimentApi.select('exp-0123456789ab', 0);
  assert.equal(capturedUrl, '/api/skill-experiments/exp-0123456789ab/versions/0/select');
  assert.ok(!capturedUrl.includes('/skills/releases'));
});

test('disabled experiment errors remain visible instead of using production endpoints', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: '实验未启用' }), { status: 403 });
  await assert.rejects(experimentApi.list(), /实验未启用/);
});
