// made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { writeFileSync } from 'node:fs';
import { referenceLog } from '../src/viewer/cosmos/referenceCalibration.js';
const url = process.env.LEAP_TEST_URL || 'http://127.0.0.1:5057';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1900, height: 990 } });
  const page = await context.newPage(), errors = [], commands = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (/Diagram .*failed|THREE.WebGLProgram: Shader Error/.test(message.text())) errors.push(message.text()); });
  await page.route('**/api/viewer/config', async route => { const response = await route.fetch(); await route.fulfill({ response, json: { ...await response.json(), pointing_strategy: 'legacy', legacy_mode: 'SUN_POINTING' } }); });
  // Flight commands are intercepted: this test never commands the running simulator.
  await page.route('**/update/**', route => { commands.push(route.request().postDataJSON()); return route.fulfill({ json: { status: 'success' } }); });
  await page.route('**/*.glb', async route => { await new Promise(resolve => setTimeout(resolve, 3000)); await route.continue(); });
  let sequence = 0;
  await page.route('**/api/latest', async route => {
    const headers = { ...route.request().headers() }; delete headers['if-none-match'];
    const response = await route.fetch({ headers }); const data = await response.json();
    const angle = sequence * .004, c = Math.cos(angle), s = Math.sin(angle);
    Object.assign(data, { telemetry_sequence: ++sequence, telemetry_session_id: 'react-browser-check', mode: 'RW',
      timestamp: new Date(Date.parse('2026-10-01T15:00:00Z') + sequence * 250).toISOString(),
      rw_torques_mnm: [Math.sin(angle), Math.cos(angle), -Math.sin(angle), -Math.cos(angle)], mtr_torque_nm: [1e-6, -2e-6, 3e-6],
      body_to_ecef_matrix: [[c, -s, 0], [s, c, 0], [0, 0, 1]], estimated_rw_torques_mnm: [Math.sin(angle), Math.cos(angle), -Math.sin(angle), -Math.cos(angle)], mtr_torque_nm: [1e-6, -2e-6, 3e-6],
      body_to_ecef_matrix: [[c, -s, 0], [s, c, 0], [0, 0, 1]] });
    await route.fulfill({ response, json: data });
  });
  // Force slow GPU readback to check the existing atomic diagram presentation.
  await page.addInitScript(() => {
    const original = WebGL2RenderingContext.prototype.clientWaitSync;
    const started = new WeakMap();
    WebGL2RenderingContext.prototype.clientWaitSync = function (sync, ...args) {
      if (!started.has(sync)) started.set(sync, performance.now());
      if (performance.now() - started.get(sync) < 90) return this.TIMEOUT_EXPIRED;
      return original.call(this, sync, ...args);
    };
  });
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('.launch-logo')?.complete && document.querySelector('.launch-logo')?.naturalWidth > 0);
  assert(await page.locator('.launch-screen').isVisible());
  assert.equal(await page.locator('.launch-credit').innerText(), 'made by chirag malik');
  const logoBounds = await page.locator('.launch-logo').boundingBox();
  assert(logoBounds.x < 1900 * .15 && logoBounds.x + logoBounds.width < 1900 / 2);
  await page.screenshot({path: path.join(tmpdir(), 'leap-loading-screen-verified.png')});
  await page.waitForFunction(() => window.spacecraftRenderAsset && window.cosmicExplorer?.ready, { timeout: 30000 });
  await page.waitForFunction(() => !document.querySelector('.launch-screen'));
  await page.waitForFunction(() => window.missionCameraState && !missionCameraState().transitioning);
  assert.equal(await page.locator('.startup-error').count(), 0);
  assert.equal(await page.locator('#set-preset').inputValue(), 'ultra');
  assert.equal(await page.locator('#set-sharp').inputValue(), '170');
  assert.equal(await page.locator('#set-clouds').inputValue(), '0.3');
  assert.equal(await page.locator('#set-stream-on').isChecked(), false);
  const glass = await page.evaluate(() => {
    document.documentElement.style.setProperty('--glass-tint', '120 10 10');
    const card = getComputedStyle(document.querySelector('.mission-card.glass')).backgroundImage;
    const settings = getComputedStyle(document.querySelector('#settings-panel')).backgroundImage;
    document.documentElement.style.removeProperty('--glass-tint');
    return {card, settings};
  });
  assert(glass.card.includes('120, 10, 10') && glass.settings.includes('120, 10, 10'));

  for (const sensor of ['Sun', 'Gyro', 'Mag']) assert(await page.locator('#set-show' + sensor).isChecked());

  const nightTint = () => page.evaluate(() => {
    let tint;
    scene.traverse(object => { if (!tint && object.material?.uniforms?.moonTint) tint = object.material.uniforms.moonTint.value.length(); });
    return tint;
  });
  const overviewNightTint = await nightTint();
  const overview = await page.locator('#mission-page-overview .mission-card').first().boundingBox();
  assert.equal(overview.x, 18); assert.equal(overview.y, 88); assert.equal(overview.width, 330);
  await page.screenshot({ path: path.join(tmpdir(), 'leap-react-overview-verified.png') });
  const polarFrames = await page.evaluate(() => {
    const aurora = scene.getObjectByName('earth-auroral-curtains');
    const earth = scene.getObjectByName('earth-surface');
    const polar = camera.clone(), origin = earth.getWorldPosition(camera.position.clone());
    polar.position.copy(origin).add(camera.position.clone().set(0,0,1.6e7));
    polar.up.set(0,1,0); polar.lookAt(origin);
    const previous = aurora.material.uniforms.time.value;
    const frames = [20,28].map(time => {
      aurora.material.uniforms.time.value = time;
      renderer.render(scene,polar);
      return renderer.domElement.toDataURL();
    });
    aurora.material.uniforms.time.value = previous;
    return {frames,vertices:aurora.geometry.attributes.position.count};
  });
  assert.equal(polarFrames.vertices, 4246);
  assert.notEqual(polarFrames.frames[0],polarFrames.frames[1], 'aurora must visibly evolve in a fixed camera');
  writeFileSync(path.join(tmpdir(),'leap-aurora-polar-verified.png'),Buffer.from(polarFrames.frames[0].split(',')[1],'base64'));

  const rendererIdentity = await page.evaluate(() => { window.testRenderer = window.renderer; return renderer.domElement.isConnected; });
  assert(rendererIdentity);
  for (const tab of ['sensors', 'overview', 'pointing', 'overview', 'sensors']) {
    await page.click('#mission-tab-' + tab);
    await page.waitForFunction(() => !missionCameraState().transitioning);
    assert.equal(await page.evaluate(() => renderer === window.testRenderer), true);
    assert.equal(await page.locator('#mission-tab-' + tab).getAttribute('aria-selected'), 'true');
    const tint = await nightTint();
    assert(tab === 'overview' ? Math.abs(tint - overviewNightTint) < .001 : tint > overviewNightTint * 6, `night tint ${tab}: ${tint}`);
  }
  await page.waitForFunction(() => document.querySelector('[data-globe="gps"]').dataset.telemetrySequence && document.querySelector('[data-globe="estimate"]').dataset.telemetrySequence);
  const diagram = await page.evaluate(() => new Promise(resolve => {
    let count = 0, minGps = Infinity, minCad = Infinity; const updates = new Set();
    function sample() {
      for (const kind of ['gps', 'estimate']) {
        const canvas = document.querySelector('[data-globe="' + kind + '"]');
        const rgba = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let filled = 0; for (let index = 3; index < rgba.length; index += 4) if (rgba[index]) filled++;
        if (kind === 'gps') { minGps = Math.min(minGps, filled); updates.add(canvas.dataset.telemetrySequence); } else minCad = Math.min(minCad, filled);
      }
      if (++count < 90) setTimeout(sample, 16); else resolve({ minGps, minCad, updates: updates.size });
    } sample();
  }));
  assert(diagram.minGps > 1000 && diagram.minCad > 100 && diagram.updates >= 2, JSON.stringify(diagram));
  assert.equal(await page.evaluate(() => renderer.getContext().getError()), 0);
  assert.equal(await page.evaluate(() => renderer.getRenderTarget()), null);
  console.log('PASS: preserved layout, tab flights and atomic diagrams', diagram);
  await page.click('#settings-toggle'); await page.waitForTimeout(550);
  assert.equal(await page.locator('#settings-toggle').getAttribute('aria-expanded'), 'true');
  await page.evaluate(async () => {
    setSettingsOpen(false);
    await new Promise(resolve => setTimeout(resolve,60));
    setSettingsOpen(true);
  });
  await page.waitForFunction(() => !document.querySelector('#settings-panel').getAnimations().length);
  assert.equal(await page.locator('#settings-panel').evaluate(el => getComputedStyle(el).opacity),'1');

  const settingsText = await page.locator('#settings-panel').innerText();
  assert(!/[\u00c3\u00c2\u00e2\u00f0]/.test(settingsText), settingsText);
  for (const tab of ['1', '3', '0', '2']) {
    await page.click('[data-settings-tab="' + tab + '"]');
    await page.waitForTimeout(25);
  }
  await page.waitForTimeout(160);
  await page.waitForFunction(() => !document.querySelector('[data-settings-page="2"]').getAnimations().length);
  assert.equal(await page.locator('[data-settings-page="2"]').evaluate(element => getComputedStyle(element).opacity), '1');
  await page.click('[data-settings-tab="2"]');
  assert.equal(await page.locator('[data-settings-page="2"]').isVisible(), true);
  assert((await page.locator('#mount-select option').count()) > 0);
  await page.keyboard.press('Escape'); await page.waitForTimeout(350);
  assert.equal(await page.locator('#settings-panel').isVisible(), false);
  await page.click('#mission-tab-pointing'); await page.waitForTimeout(1100);
  await page.screenshot({path: path.join(tmpdir(), 'leap-pointing-actuators-verified.png')});
  assert(await page.locator('[data-chart="wheels"]').isVisible());
  assert(await page.locator('[data-chart="torquers"]').isVisible());
  assert.equal(await page.locator('[data-legend="wheels"] span').count(), 4);
  assert.equal(await page.locator('[data-legend="torquers"] span').count(), 3);
  await page.waitForFunction(() => Number(document.querySelector('[data-chart="wheels"]').dataset.samples) >= 2);
  await page.locator('#mission-control-slot .glass-select-trigger').click();
  await page.locator('.mode-menu [data-value="NADIR"]').click();
  await page.waitForTimeout(100); assert(commands.some(command => command.mode === 'NADIR'));
  await page.locator('#mission-camera-slot .glass-select-trigger').click();
  await page.locator('.camera-menu [data-value="payload"]').click();
  assert.equal(await page.locator('#cameraSelect').inputValue(), 'payload');
  assert(!commands.some(command => command.mode === 'payload'));
  await page.click('#mission-tab-overview'); await page.waitForTimeout(1100);
  // made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
  for (const time of [89, 94, 97, 99]) {
    await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(time));
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => cosmicExplorer.orbit.visible && cosmicExplorer.orbit.geometry === cosmicExplorer.nativeAssets.orbit.geometry && !cosmicExplorer.drawnLabels.includes('Earth') && !cosmicExplorer.drawnLabels.includes('Moon')));
  }
  await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.distance-scale')).opacity) === 1);
  assert((await page.locator('.distance-scale').innerText()).length > 0);
  await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(92));
  await page.waitForTimeout(650);
  assert.equal(await page.locator('.context-card').evaluate(element => Number(getComputedStyle(element).opacity)), 1);
  await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(94));
  await page.waitForTimeout(100);
  const diagramFade = await page.locator('.context-card').evaluate(element => Number(getComputedStyle(element).opacity));
  assert(diagramFade > 0 && diagramFade < 1, 'diagram should fade instead of snapping');
  await page.waitForTimeout(650);
  assert.equal(await page.locator('.context-card').evaluate(element => Number(getComputedStyle(element).opacity)), 0);
  assert(await page.evaluate(() => cosmicExplorer.backgroundMaterial.uniforms.blend.value === 0));
  await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(101));
  try { await page.waitForFunction(() => cosmicExplorer.backgroundMaterial.uniforms.blend.value > .99, null, { timeout: 15000 }); } catch(error) { console.log('VIDEO_DIAGNOSTIC', await page.evaluate(() => ({ blend:cosmicExplorer.backgroundMaterial.uniforms.blend.value, ready:cosmicExplorer.video.readyState, seeking:cosmicExplorer.video.seeking, time:cosmicExplorer.video.currentTime, target:cosmicExplorer.desiredVideoTime, presented:cosmicExplorer.presentedTime, error:cosmicExplorer.video.error?.message, enabled:cosmicExplorer.enabled, ref:cosmicExplorer.referenceTime }))); throw error; }
  const automaticTurn = await page.evaluate(() => {
    const sun = cosmicExplorer.nativeAssets.earth.material.uniforms.sunDir.value;
    const radial = sun.clone().normalize().negate(), before = radial.clone(), up = radial.clone().set(0, 0, 1);
    cosmicExplorer.cameraOrbit(radial, up);
    return Math.acos(Math.min(1, Math.max(-1, before.dot(radial))));
  });
  assert(automaticTurn <= Math.PI / 2 + .001);
  await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(146));
  await page.waitForFunction(() => document.body.classList.contains('cosmic-cinema'));
  await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.mission-header')).opacity) === 0);
  assert.equal(await page.locator('.mission-header').evaluate(element => Number(getComputedStyle(element).opacity)), 0);
  assert.equal(await page.locator('.context-card').evaluate(element => Number(getComputedStyle(element).opacity)), 0);
  await page.evaluate(distance => cosmicExplorer.setDistance(distance), 10 ** referenceLog(144));
  await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.mission-header')).opacity) === 1);
  await page.click('#mission-tab-sensors'); await page.waitForTimeout(1100);
  assert.equal(await page.evaluate(() => missionCameraState().overview), false);
  const chartDraws = await page.evaluate(() => new Promise(resolve => {
    const canvas = document.querySelector('[data-chart=gyro]'), ctx = canvas.getContext('2d');
    const clear = ctx.clearRect; let count = 0;
    ctx.clearRect = function (...args) { count++; return clear.apply(this, args); };
    setTimeout(() => { ctx.clearRect = clear; resolve(count); }, 1200);
  }));
  assert(chartDraws >= 1 && chartDraws <= 2, 'active charts must be limited to 1 Hz');
  await page.click('.mission-clear');
  await page.waitForTimeout(650);
  assert.equal(await page.locator('.mission-tabs').evaluate(el => getComputedStyle(el).opacity), '0');
  assert.equal(await page.locator('.mission-clear').getAttribute('aria-pressed'), 'true');
  for (const selector of ['.mission-clock', '#fullscreen-toggle', '#axis-toggle', '#settings-toggle']) {
    assert.equal(await page.locator(selector).evaluate(el => getComputedStyle(el).opacity), '1');
  }
  const beforeClearSequence = sequence;
  await page.waitForTimeout(2200);
  assert(sequence - beforeClearSequence <= 3, 'eye mode should poll telemetry at most once per second');
  assert.equal(await page.locator('#mission-page-sensors').getAttribute('hidden'), null,
    'eye mode must retain panel layout while stopping subscriptions');
  await page.click('.mission-clear');
  await page.waitForTimeout(90);
  const restoring = await page.locator('#mission-page-sensors .rail-left').evaluate(el => ({
    opacity: Number(getComputedStyle(el).opacity), animations: el.getAnimations().length
  }));
  assert(restoring.opacity > 0 && restoring.opacity < 1 && restoring.animations > 0,
    'telemetry must animate back after eye mode');
  await page.waitForTimeout(650);
  assert.equal(await page.locator('.mission-tabs').evaluate(el => getComputedStyle(el).opacity), '1');
  assert.deepEqual(errors, []);
  console.log('PASS: settings, legacy commands, payload camera, orbit/video handoff and HUD slide');
  await context.close();
  const custom = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const customPage = await custom.newPage();
  await customPage.route('**/api/viewer/config', async route => { const response = await route.fetch(); await route.fulfill({ response, json: { ...await response.json(), pointing_strategy: 'custom' } }); });
  let status = 'red', commandSequence = 0;
  await customPage.route('**/api/latest', async route => {
    const headers = { ...route.request().headers() }; delete headers['if-none-match'];
    const response = await route.fetch({ headers });
    await route.fulfill({ response, json: { ...await response.json(), telemetry_sequence: ++commandSequence,
      mode: 'CUSTOM', custom_target_quaternion: [1,0,0,0], custom_pointing_error_deg: 12,
      custom_pointing_status: status } });
  });
  await customPage.goto(url); await customPage.waitForFunction(() => Boolean(window.renderer));
  assert.equal(await customPage.locator('#modeSelect').count(), 0);
  assert.equal(await customPage.locator('#cameraSelect').count(), 1);
  await customPage.click('#mission-tab-pointing');
  assert.equal(await customPage.locator('.quaternion-lights i').count(), 4);
  for (const color of ['red', 'green', 'yellow', 'blue']) {
    status = color;
    await customPage.waitForFunction(color => document.querySelector('.quaternion-lights .lit')?.dataset.color === color, color);
  }
  assert.equal(await customPage.evaluate(() => MissionDashboard.latest.custom_pointing_error_deg), 12);
  assert.equal(await customPage.evaluate(() => MissionDashboard.samples.at(-1).pointingError), 12);

  await custom.close(); console.log('PASS: YAML custom strategy preserves API-only quaternion control');
  const legacy = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const legacyPage = await legacy.newPage();
  await legacyPage.route('**/api/viewer/config', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), spacecraft_model_url: '/assets/models/P-30XL.glb', spacecraft_com: [0, 0, 0] } });
  });
  await legacyPage.route('**/api/latest', async route => {
    const headers = { ...route.request().headers() }; delete headers['if-none-match'];
    const response = await route.fetch({ headers });
    await route.fulfill({ response, json: { ...await response.json(), spacecraft_model_url: '/assets/models/P-30XL.glb', center_of_mass_body_m: [0, 0, 0] } });
  });
  await legacyPage.goto(url);
  await legacyPage.waitForFunction(() => window.spacecraftRenderAsset?.scene.scale.x === .001);
  const extent = await legacyPage.evaluate(() => {
    const root = spacecraftRenderAsset.scene; root.updateWorldMatrix(true, true);
    const inverseParent = root.parent.matrixWorld.clone().invert(); let box;
    root.traverse(node => {
      if (!node.isMesh) return;
      node.geometry.computeBoundingBox();
      const part = node.geometry.boundingBox.clone().applyMatrix4(node.matrixWorld.clone().premultiply(inverseParent));
      if (box) box.union(part); else box = part;
    });
    return { size: Math.max(box.max.x-box.min.x, box.max.y-box.min.y, box.max.z-box.min.z), center: box.min.clone().add(box.max).multiplyScalar(.5).length() };
  });
  assert(extent.size > .1 && extent.size < 3, 'legacy model must be expressed in metres');
  assert(extent.center < .001, 'legacy export origin must be centered on the satellite');
  await legacy.close(); console.log('PASS: legacy model units and origin');

  const firmwareContext = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const firmwarePage = await firmwareContext.newPage();
  await firmwarePage.route('**/api/viewer/config', async route => { const response=await route.fetch(); await route.fulfill({response,json:{...await response.json(),pointing_strategy:'firmware_sitl'}}); });
  await firmwarePage.goto(url); await firmwarePage.waitForFunction(() => Boolean(window.renderer));
  await firmwarePage.click('#mission-tab-pointing');
  assert.equal(await firmwarePage.locator('#modeSelect').count(), 0);
  assert.equal(await firmwarePage.locator('.quaternion-lights i').count(), 4);
  assert((await firmwarePage.locator('.custom-pointing').innerText()).includes('Firmware SITL'));
  await firmwareContext.close(); console.log('PASS: firmware SITL controls and status lights');
} finally { await browser.close(); }
