import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSignal } from './signal.mjs';

test('attach adopts the source position and energy; stale samples hide', () => {
  let now = 0;
  const signal = createSignal(() => now);
  assert.equal(signal.current().visible, false);
  assert.equal(signal.sample({ playing: true, playhead_seconds: 87.25, level: .68 }), true);
  assert.deepEqual(signal.current(), { visible: true, level: .68, playhead_seconds: 87.25 });
  now = 751;
  assert.deepEqual(signal.current(), { visible: false, level: 0, playhead_seconds: null });
});

test('pause hides, a new verified sample can resume, invalid input does not refresh', () => {
  let now = 0;
  const signal = createSignal(() => now);
  signal.sample({ playing: false, playhead_seconds: 42, level: .9 });
  assert.equal(signal.current().visible, false);
  signal.sample({ playing: true, playhead_seconds: 63, level: .3 });
  now = 700;
  for (const value of [null, {}, { playing: true, playhead_seconds: -1, level: 0 },
      { playing: true, playhead_seconds: 63, level: Infinity },
      { playing: true, playhead_seconds: 63, level: 2 }]) assert.equal(signal.sample(value), false);
  now = 800;
  assert.equal(signal.current().visible, false);
});
