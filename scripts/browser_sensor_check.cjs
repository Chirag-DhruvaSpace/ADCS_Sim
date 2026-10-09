const { chromium } = require(require('path').join(process.env.TEMP, 'leap-viewer-check/node_modules/playwright'));
const { spawn } = require('child_process');
const assert = require('assert');
const server = spawn('.venv/Scripts/python.exe', ['scripts/viewer_test_server.py'], {stdio: 'ignore', windowsHide: true});
(async () => {
  let browser;
  try {
    browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true});
    const page = await browser.newPage({viewport:{width:1366,height:768}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    for (let i=0;i<30;i++) {
      try { await page.goto('http://127.0.0.1:5057', {waitUntil:'domcontentloaded'}); break; }
      catch(e) { if (i===29) throw e; await page.waitForTimeout(500); }
    }
    await page.click('#mission-tab-sensors');
    assert(await page.locator('#mission-page-sensors').isVisible());
    assert(!await page.locator('#mission-page-overview').isVisible());
    await page.waitForFunction(() => window.renderer, {timeout:30000});
    await page.waitForFunction(() => document.querySelector('#sen-est').textContent.includes('belief quat'));
    assert(await page.evaluate(() => !window.satelliteGroup.parent.getObjectByName('osculating-orbit').visible));
    assert(await page.locator('#mission-sun-cells tr').count() > 0);
    await page.click('#settings-toggle');
    await page.click('[data-settings-tab="2"]');
    assert(await page.evaluate(() => {
      const scene=document.querySelector('#threeContainer').getBoundingClientRect();
      const settings=document.querySelector('#settings-panel').getBoundingClientRect();
      return Math.abs(scene.width - innerWidth) < 2 && settings.right <= innerWidth && settings.width < 450;
    }));
    await page.waitForFunction(() => document.querySelector('#mount-select').options.length === 8);
    await page.selectOption('#mount-select', 'Gyroscope');
    await page.locator('#mount-position input').nth(0).fill('0.1');
    await page.click('#mount-apply');
    await page.waitForFunction(() => document.querySelector('#mount-status').textContent.includes('next simulation tick'));
    await page.uncheck('#set-showSun');
    await page.check('#set-showSun');
    await page.screenshot({path:'validation/results/sensor_viewer.png'});
    await page.click('#settings-close');
    await page.mouse.move(700,400);
    await page.mouse.wheel(0,12500);
    await page.waitForTimeout(1200);
    assert(await page.evaluate(() => window.satelliteGroup.parent.getObjectByName('osculating-orbit').visible));
    await page.screenshot({path:'validation/results/orbit_viewer.png'});
    await page.setViewportSize({width:390,height:844});
    await page.click('#settings-toggle');
    await page.waitForTimeout(250);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert(await page.evaluate(() => {
      const scene=document.querySelector('#threeContainer').getBoundingClientRect();
      const settings=document.querySelector('#settings-panel').getBoundingClientRect();
      return settings.left >= 0 && settings.right <= innerWidth && settings.bottom <= innerHeight;
    }));
    await page.screenshot({path:'validation/results/viewer_mobile.png',fullPage:true});
    console.log(JSON.stringify({errors, sensorPanel:await page.locator('#mission-page-sensors').evaluate(e => ({height:e.clientHeight,content:e.scrollHeight,width:e.clientWidth})), settingsTabs:await page.locator('[data-settings-tab]').count()}));
    assert.deepStrictEqual(errors, []);
  } finally {
    if(browser) await browser.close();
    server.kill();
  }
})().catch(e => {console.error(e); process.exitCode=1;});
