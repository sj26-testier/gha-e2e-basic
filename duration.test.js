import assert from 'node:assert/strict';
import test from 'node:test';
import { formatDuration } from './duration.js';

test('formats seconds below a minute', () => {
  assert.equal(formatDuration(0), '0:00');
  assert.equal(formatDuration(59), '0:59');
});

test('carries minutes and pads remaining seconds', () => {
  assert.equal(formatDuration(60), '1:00');
  assert.equal(formatDuration(125), '2:05');
  assert.equal(formatDuration(3605), '60:05');
});

test('rejects negative and fractional durations', () => {
  assert.throws(() => formatDuration(-1), RangeError);
  assert.throws(() => formatDuration(1.5), RangeError);
});
