import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getReplayMessages } from '../src/utils/replay.ts';

test('replay follows simulation chronology and keeps text attached to its speaker', () => {
  const turns = [
    { turn_index: 1, counselor_response: '你好，环境还适应吗？', client_utterance: '环境还行。' },
    { turn_index: 2, counselor_response: '  我们可以慢慢来。\n你想从哪里说起？', client_utterance: '最近心里很乱。' },
  ];
  assert.deepEqual(turns.flatMap(getReplayMessages), [
    { role: 'counselor', content: '你好，环境还适应吗？' },
    { role: 'participant', content: '环境还行。' },
    { role: 'counselor', content: '  我们可以慢慢来。\n你想从哪里说起？' },
    { role: 'participant', content: '最近心里很乱。' },
  ]);
});

test('a turn stopped before the client reply keeps the counselor message alone', () => {
  assert.deepEqual(getReplayMessages({ turn_index: 3, counselor_response: '我们先暂停。' }), [
    { role: 'counselor', content: '我们先暂停。' },
  ]);
  assert.deepEqual(getReplayMessages({ turn_index: 4, counselor_response: ' \n', client_utterance: '继续。' }), [
    { role: 'participant', content: '继续。' },
  ]);
  assert.deepEqual(getReplayMessages({ turn_index: 5 }), []);
});
