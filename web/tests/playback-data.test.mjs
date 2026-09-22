import assert from 'node:assert/strict';
import test from 'node:test';
import { inputsAtTime } from '../src/playback-data.ts';

const report = (id, measured, arrived) => ({
  observation_id: id, sensor_id: 'sensor_a', measured_at_ms: measured,
  arrived_at_ms: arrived, position_m: [1, 2], position_cov_m2: [[4, 0], [0, 4]],
});
const request = (time, observations) => ({
  type: 'step', schema_version: 1, step_id: time / 500, time_ms: time, observations,
});
const recorded = {
  requests: [request(0, []), request(500, [report('late', 0, 450)]),
    request(1000, []), request(1500, [report('future', 1500, 1500)])],
  outputs: [0, 500, 1000, 1500].map(time_ms => ({ time_ms, tracks: [] })),
};

test('playback separates measurement, arrival and confirmed delivery without future inputs', () => {
  const view = inputsAtTime(recorded, 500);
  assert.equal(view.confirmed, true);
  assert.deepEqual(view.history, [{ observation: report('late', 0, 450), givenAt: 500 }]);
  assert.equal(view.batch.length, 1);
  assert.equal(inputsAtTime(recorded, 0).history.length, 0);
  assert.equal(inputsAtTime(recorded, 1500).history.length, 2);
});

test('empty input steps preserve previously received history', () => {
  const view = inputsAtTime(recorded, 1000);
  assert.equal(view.confirmed, true);
  assert.deepEqual(view.batch, []);
  assert.equal(view.history.length, 1);
});

test('failed or pending responses cannot turn prewritten requests into received inputs', () => {
  const interrupted = { ...recorded, outputs: recorded.outputs.slice(0, 1) };
  for (const time of [500, 1000, 1500]) {
    const view = inputsAtTime(interrupted, time);
    assert.equal(view.confirmed, false);
    assert.deepEqual(view.batch, []);
    assert.deepEqual(view.history, []);
    assert.equal(view.request.time_ms, time);
  }
});
