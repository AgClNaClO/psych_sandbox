import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { api, ApiError, isVersionConflict, subscribeSSE } from '../src/services/api.ts';

const originalFetch = globalThis.fetch;
const originalEventSource = globalThis.EventSource;

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.EventSource = originalEventSource;
});

test('version conflicts retain HTTP status and busy conflicts are not retried', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Course version conflict' }), { status: 409 });
  await assert.rejects(api.getCourses(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.ok(isVersionConflict(error));
    return true;
  });
  assert.equal(isVersionConflict(new ApiError(409, 'Operation active')), false);
  assert.equal(isVersionConflict(new ApiError(400, 'Version conflict')), false);
});

test('SSE handles stopped/cancelled jobs, deduplicates replay, and reports reconnection', () => {
  class FakeEventSource {
    static current: FakeEventSource;
    onopen?: () => void;
    onerror?: (error: Event) => void;
    onmessage?: (event: MessageEvent) => void;
    listeners = new Map<string, (event: MessageEvent) => void>();
    closed = false;
    constructor(publicUrl: string) {
      assert.match(publicUrl, /stream=job%3Atest/);
      FakeEventSource.current = this;
    }
    addEventListener(type: string, handler: (event: MessageEvent) => void) { this.listeners.set(type, handler); }
    close() { this.closed = true; }
    emit(type: string, seq: number) {
      this.listeners.get(type)?.({ data: '{}', lastEventId: String(seq) } as MessageEvent);
    }
  }
  globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  const events: string[] = [];
  let disconnected = false;
  const close = subscribeSSE('job:test', (event) => events.push(event.type), () => { disconnected = true; });
  const source = FakeEventSource.current;
  source.emit('job_stopped', 1);
  source.emit('job_stopped', 1);
  source.emit('job_cancelled', 2);
  assert.deepEqual(events, ['job_stopped', 'job_cancelled']);
  source.onerror?.(new Event('error'));
  assert.equal(disconnected, true);
  close();
  assert.equal(source.closed, true);
});
