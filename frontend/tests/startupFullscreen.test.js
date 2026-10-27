import {test} from 'node:test';
import assert from 'node:assert/strict';
import {startupFullscreen} from '../src/services/startupFullscreen.js';

test('startup retries denied fullscreen on a gesture and respects later exit', async () => {
  const doc = new EventTarget();
  let requests = 0;
  doc.documentElement = {requestFullscreen() {
    requests++;
    if (requests === 1) return Promise.reject(new Error('Activation required'));
    doc.fullscreenElement = doc.documentElement;
    doc.dispatchEvent(new Event('fullscreenchange'));
    return Promise.resolve();
  }};
  startupFullscreen(doc);
  await Promise.resolve();
  assert.equal(requests, 1);
  doc.dispatchEvent(new Event('click'));
  await Promise.resolve();
  assert.equal(requests, 2);
  doc.fullscreenElement = null;
  doc.dispatchEvent(new Event('click'));
  assert.equal(requests, 2);
});

test('cleanup cancels gesture retries after a denied startup request', async () => {
  const doc = new EventTarget();
  let requests = 0;
  doc.documentElement = {requestFullscreen() {
    requests++;
    return Promise.reject(new Error('Activation required'));
  }};
  const cleanup = startupFullscreen(doc);
  await Promise.resolve();
  cleanup();
  doc.dispatchEvent(new Event('click'));
  assert.equal(requests, 1);
});
