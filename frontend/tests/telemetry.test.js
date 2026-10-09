/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {Vector3} from 'three';
import {interpolateOrbitalPosition} from '../src/viewer/coordinates.js';
import { History, derive } from '../src/services/dashboardData.js';
import { createTelemetryStore } from '../src/services/telemetryStore.js';
import { formatTelemetry } from '../src/services/formatTelemetry.js';
const base = {
  timestamp: '2026-10-01T15:00:00Z',
  telemetry_session_id: 'test',
  telemetry_sequence: 1,
  mode: 'NADIR',
  nadir_pointing_error_deg: .25,
  latitude_deg: 12,
  altitude_m: 510000,
  truth_pos_eci_x: 0,
  truth_pos_eci_y: 0,
  truth_pos_eci_z: 0,
  gps_pos_eci_x: 3,
  gps_pos_eci_y: 4,
  gps_pos_eci_z: 0
};
test('React migration preserves unit conversion and pointing metrics', () => {
  assert.equal(derive(base).gpsError, 5);
  assert.equal(derive(base).pointingError, .25);
  assert.equal(formatTelemetry(base, derive(base), {
    'data-value': 'altitude_m',
    'data-unit': ' km',
    'data-digits': 3
  }), '510.000 km');
  assert.equal(formatTelemetry({
    gps_latency_s: .012
  }, {}, {
    'data-value': 'gps_latency_s',
    'data-unit': ' ms',
    'data-digits': 0
  }), '12 ms');
  assert.equal(formatTelemetry({
    mode: 'CUSTOM',
    custom_pointing_error_deg: 1
  }, {
    pointingError: 1
  }, {}, 'mission-mode-error'), 'Custom quaternion error 1.000°');
});
/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
test('Store deduplicates receipts, preserves snapshots and bounds chart history', () => {
  const store = createTelemetryStore();
  let notifications = 0;
  const unsubscribe = store.subscribe(() => notifications++);
  assert(store.accept(base, 10));
  const first = store.getSnapshot();
  assert.equal(store.accept(base, 11), false);
  assert.equal(notifications, 1);
  for (let index = 1; index < 1000; index++) store.accept({
    ...base,
    telemetry_sequence: index + 1,
    timestamp: new Date(Date.parse(base.timestamp) + index * 250).toISOString()
  }, index);
  assert(store.getSnapshot().samples.length <= 121);
  assert.equal(first.samples.length, 1);
  assert.equal(first.data, base);
  unsubscribe();
  const count = notifications;
  store.accept({
    ...base,
    telemetry_sequence: 1001
  }, 2000);
  assert.equal(notifications, count);
});
test('History resets on simulation rewind and separates telemetry sessions', () => {
  const history = new History();
  history.add(base);
  history.add({
    ...base,
    telemetry_sequence: 2,
    timestamp: '2026-10-01T15:01:00Z'
  });
  history.add({
    ...base,
    telemetry_sequence: 3,
    timestamp: '2026-10-01T15:00:00Z'
  });
  assert.equal(history.samples.length, 1);
  history.add({
    ...base,
    telemetry_session_id: 'new-run'
  });
  assert.equal(history.samples.length, 1);
});

test('actuator charts preserve four wheel channels and convert magnetic torque to microN m', () => {
  const data = derive({rw_torques_mnm: [1, -2, 3, -4], mtr_torque_nm: [1e-6, -2e-6, 3e-6]});
  assert.deepEqual(data.reactionWheels, [1, -2, 3, -4]);
  assert.deepEqual(data.magnetorquers, [1, -2, 3]);
  assert.equal(derive({}).reactionWheels, null);
  assert.equal(derive({rw_torques_mnm: [1, 2, 3]}).reactionWheels, null);
  assert.equal(derive({mtr_torque_nm: [NaN, 0, 0]}).magnetorquers, null);
});

test('position smoothing stays outside Earth across large and antipodal telemetry jumps', () => {
  const radius = 6871000;
  const position = new Vector3(radius, 0, 0);
  const target = new Vector3(-radius, 0, 0);
  interpolateOrbitalPosition(position, target, .5);
  assert(Math.abs(position.length() - radius) < 1e-6);
  assert(Math.abs(position.x) < 1e-6);
  for (let index = 0; index < 100; index++) {
    interpolateOrbitalPosition(position, target, .1);
    assert(Math.abs(position.length() - radius) < 1e-6);
  }
  interpolateOrbitalPosition(position, target, 1);
  assert(position.distanceTo(target) < 1e-6);
  const close = new Vector3(radius + 1000, 0, 0);
  interpolateOrbitalPosition(close, new Vector3(radius + 2000, 0, 0), .5);
  assert.equal(close.length(), radius + 1500);
});

test('chart averages reduce spikes without changing original telemetry', async () => {
  const { averageChartSamples } = await import('../src/components/LiveChart/drawChart.js');
  const samples = [0, 250, 500, 750, 1000].map((t, i) => ({ t, d: {}, gyroError: [i%2 ? 10 : -10, 0, 0], pointingError: i }));
  const averaged = averageChartSamples(samples);
  assert.equal(averaged.length, 2);
  assert.equal(averaged[0].gyroError[0], 0);
  assert.equal(averaged[0].pointingError, 1.5);
  assert.equal(samples[0].gyroError[0], -10);
});
