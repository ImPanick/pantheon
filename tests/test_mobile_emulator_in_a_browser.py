# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the actual Pantheon app and UI against explicit device/stream fixtures.

This verifies browser behavior, not Android, scrcpy, or KVM. The transport
fixture is labelled as such in every screenshot; no Android UI is invented.
Set PANTHEON_TEST_SCREENSHOTS to retain screenshots for review.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from workstation import protocol as P
from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")
ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const BASE = process.argv[2], devices = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
    localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    localStorage.setItem('pantheon-cockpit-workspace', JSON.stringify({ layout: 'one', off: false, width: '64%' }));
  });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push(String(e.message || e)));
  page.setDefaultTimeout(20000);
  const state = { available: true, state: 'off', mode: 'android', device: 'galaxy_z_fold6',
    isolation: 'per_user_vm', edition: 'standard', google_play: false, preview_available: true,
    devices, posture: 'open', rotation: 0, screen_is_active: true, boot_phase: 'off',
    license: { accepted: true }, install: { state: 'idle' } };
  let holder = 'agent', streamReady = false, refuseRotate = false;
  let stateGate = null, screenGate = null, controlGate = null, onHandBack = null;
  const controlRequests = [];
  const defer = () => {
    let seen, release;
    return { seen: new Promise(r => seen = r), wait: new Promise(r => release = r),
      arrived: () => seen(), release: () => release() };
  };
  const shape = () => {
    const d = devices.find(d => d.id === state.device);
    const active = state.screen_is_active || state.mode === 'mobile_view';
    let w = active && state.posture === 'closed' && d.cover_width ? d.cover_width : d.width, h = d.height;
    if (active && state.rotation % 2) [w, h] = [h, w];
    const scale = Math.min(1280 / w, 1100 / h, 1);
    state.screen = [Math.floor(w * scale / 2) * 2, Math.floor(h * scale / 2) * 2];
    state.stream_ready = streamReady;
    return state;
  };
  await page.route('**/api/workstation/phone', async route => {
    const req = route.request();
    if (req.method() === 'GET' && stateGate) {
      const gate = stateGate, snapshot = structuredClone(shape()); stateGate = null;
      gate.arrived(); await gate.wait; await route.fulfill({ json: snapshot }); return;
    }
    if (req.method() === 'POST') {
      const b = req.postDataJSON(); requests.push(b);
      if (b.action === 'rotate' && refuseRotate) {
        await route.fulfill({ status: 503, json: { detail: 'Rotation refused by test device.' } }); return;
      }
      if (b.action === 'start' || b.action === 'install') { state.state = 'starting'; state.boot_phase = 'emulator'; }
      if (b.action === 'install' && b.accept_license) state.license.accepted = true;
      if (b.action === 'preview') { state.mode = 'mobile_view'; state.state = 'on'; }
      if (b.action === 'edition') {
        state.edition = b.edition; state.google_play = b.edition === 'google_play';
        state.license.accepted = false; state.state = 'off'; streamReady = false;
      }
      if (b.action === 'stop') { state.state = 'off'; streamReady = false; }
      if (b.action === 'device' || b.action === 'install') {
        state.device = b.device; state.rotation = 0;
        state.posture = devices.find(d => d.id === b.device).foldable ? 'open' : null;
      }
      if (b.action === 'rotate') state.rotation = (state.rotation + 1) % 4;
      if (b.action === 'posture') state.posture = b.posture;
    }
    await route.fulfill({ json: shape() });
  });
  await page.route('**/api/workstation/phone/screen', async route => {
    const snapshot = { kind: streamReady ? 'kasmvnc' : null, holder,
      client: streamReady ? '/api/workstation/desktop/client/phone-test.html' : null };
    if (screenGate) {
      const gate = screenGate; screenGate = null;
      gate.arrived(); await gate.wait;
    }
    await route.fulfill({ json: snapshot });
  });
  await page.route(/\/api\/workstation(\/phone)?\/control(\?.*)?$/, async route => {
    holder = route.request().postDataJSON().holder;
    controlRequests.push(holder);
    const snapshot = { holder };
    if (holder === 'person' && controlGate) {
      const gate = controlGate; controlGate = null;
      gate.arrived(); await gate.wait;
    }
    if (holder === 'agent' && onHandBack) { onHandBack(); onHandBack = null; }
    await route.fulfill({ json: snapshot });
  });
  const files = [];
  await page.route('**/api/workstation/phone/files*', async route => {
    const req = route.request();
    files.push({ type: req.headers()['content-type'], data: req.postDataBuffer().toString() });
    await route.fulfill({ json: { ok: true, name: 'selected.txt', bytes: 12,
      destination: '/sdcard/Download/Pantheon/test-fixture/selected.txt', sha256: 'fixture' } });
  });
  await page.route('**/api/documents/library?**', route => route.fulfill({ json: {
    documents: [{ id: 'owned-document-fixture', title: '<img src=x onerror=alert(1)> Document' }],
  } }));
  await page.route('**/api/workstation/desktop/client/phone-test.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><body style="margin:0;background:#101010;color:white;font:20px monospace;display:grid;place-content:center;height:100vh;text-align:center"><p>Stream fixture</p><p>Android is not running<br>in this UI test</p><button id="target" style="font:inherit;padding:20px">Touch target</button><script>document.getElementById("target").onclick=()=>document.getElementById("target").textContent="Tapped";</script></body></html>',
  }));
  const creds = { username: 'mobile-uplift', password: 'mobile-uplift-test-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
  const shot = async name => {
    if (!process.env.PANTHEON_TEST_SCREENSHOTS) return;
    fs.mkdirSync(process.env.PANTHEON_TEST_SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: path.join(process.env.PANTHEON_TEST_SCREENSHOTS, name + '.png') });
  };
  const poll = async () => page.evaluate(async () => (await import('/static/js/phoneWindow.js'))._test.tick());
  const settled = () => page.waitForFunction(() => !document.querySelector('.phw-moving'));
  const fits = async () => {
    const result = await page.evaluate(() => {
      const b = document.querySelector('.phw-bezel').getBoundingClientRect();
      const s = document.querySelector('.phw-stage').getBoundingClientRect();
      return { fits: b.left >= s.left && b.right <= s.right && b.top >= s.top && b.bottom <= s.bottom,
        width: b.width, height: b.height };
    });
    assert.equal(result.fits, true, JSON.stringify(result)); return result;
  };
  assert.deepEqual(await page.locator('.ck-surf').evaluateAll(bs => bs.map(b => b.getAttribute('aria-label'))),
    ['Documents', 'Workstation', 'Browser', 'Mobile Emulator']);
  await page.locator('[data-surf="phone"]').click();
  await page.waitForSelector('.ck-pane[data-pane="phone"] > .phw-modal');
  await page.waitForSelector('.phw-bezel[data-state="off"]');
  assert.match(await page.locator('.phw-runtime').innerText(), /Generic Android/);
  assert.equal(await page.locator('.phw-tools').isVisible(), false);
  assert.equal(await page.locator('.phw-side-power').isEnabled(), true);
  await fits(); await shot('mobile-workspace-off');

  // Physical Power starts Android; the real UI can mount a stream during boot.
  await page.locator('.phw-side-power').click();
  await page.waitForSelector('.phw-bezel[data-state="starting"]');
  streamReady = true; state.boot_phase = 'android';
  await poll();
  await page.waitForSelector('.phw-live-frame');
  assert.equal(await page.locator('.phw-bezel').getAttribute('data-state'), 'starting');
  assert.equal(requests[0].action, 'start');
  await shot('mobile-boot-stream-fixture');
  state.state = 'on'; state.boot_phase = 'ready'; await poll();
  await page.locator('.phw-take').click();
  await page.waitForSelector('.phw-holding');
  const tap = async () => {
    const target = page.frameLocator('.phw-live-frame').locator('#target');
    await target.click(); assert.equal(await target.innerText(), 'Tapped');
  };
  await tap();

  // Primary hardware controls send Android keys, without stopping the process.
  // `PHW-CTL`: volume and power are the keys on the phone's edge; the nav bar
  // under the screen carries only Back, Home and Recent apps.
  assert.equal(await page.locator('.phw-nav [data-key="power"]').count(), 0);
  for (const key of ['volume_down', 'volume_up', 'power']) {
    const button = page.locator(`.phw-side[data-key="${key}"]`);
    assert.equal(await button.isVisible(), true);
    const sent = page.waitForResponse(response => response.url().endsWith('/api/workstation/phone')
      && response.request().method() === 'POST' && response.request().postDataJSON().button === key);
    await button.click();
    await sent;
    await poll();
    assert.deepEqual(requests.at(-1), { action: 'button', button: key });
    assert.equal(state.state, 'on');
  }

  const open = await fits();
  await page.locator('.phw-fold').click();
  await page.waitForSelector('.phw-moving');
  const folding = await page.locator('.phw-fold-leaf').evaluate(n => n.getAnimations().map(a => a.effect.getKeyframes()));
  assert.match(JSON.stringify(folding), /rotateY/);
  await page.waitForTimeout(260); await shot('mobile-fold-animation-fixture');
  await settled(); const closed = await fits();
  assert.ok(closed.width < open.width);
  await page.waitForSelector('.phw-live-frame'); await tap();
  await page.locator('.phw-fold').click(); await settled(); await fits();

  state.screen_is_active = false; state.posture = 'closed'; await poll(); await settled();
  await page.waitForFunction(() => {
    const frame = document.querySelector('.phw-live-frame');
    return frame && parseFloat(frame.style.width) > frame.parentElement.clientWidth && parseFloat(frame.style.left) < 0;
  }, null, { timeout: 5000 });
  assert.equal(await page.locator('.phw-live-frame').evaluate(frame =>
    parseFloat(frame.style.width) > frame.parentElement.clientWidth && parseFloat(frame.style.left) < 0), true);
  state.screen_is_active = true; state.posture = 'open'; await poll(); await settled();

  for (let r = 1; r <= 4; r++) {
    await page.locator('.phw-rotate').click();
    await page.waitForSelector('.phw-moving');
    if (r === 4) {
      const keys = await page.locator('.phw-bezel').evaluate(n => n.getAnimations()
        .map(a => a.effect.getKeyframes()).find(keys => keys.some(k => k.transform)));
      assert.equal(keys[0].transform, 'rotate(-90deg)');
    }
    await settled(); await fits();
    await page.waitForSelector('.phw-live-frame'); await tap();
    if (r === 1) await shot('mobile-rotation-fixture');
  }
  const before = await page.locator('.phw-bezel').getAttribute('style');
  refuseRotate = true;
  await page.locator('.phw-rotate').click();
  await page.waitForFunction(() => document.querySelector('.phw-status').textContent.includes('Rotation refused'));
  await poll();
  assert.match(await page.locator('.phw-status').innerText(), /Rotation refused/);
  assert.equal(await page.locator('.phw-bezel').getAttribute('style'), before);
  refuseRotate = false;

  // A delayed poll cannot undo a newer acknowledged rotation.
  const gate = stateGate = defer();
  const stale = poll(); await gate.seen;
  await page.locator('.phw-rotate').click();
  await page.waitForFunction(() => document.querySelector('.phw-profile').textContent.includes('Rotation 90'));
  gate.release(); await stale; await settled();
  assert.match(await page.locator('.phw-profile').innerText(), /Rotation 90/);

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('.phw-rotate').click(); await poll();
  assert.equal(await page.locator('.phw-moving').count(), 0);
  for (const d of devices) {
    await page.locator('.phw-device').selectOption(d.id);
    await page.waitForFunction(id => document.querySelector('.phw-bezel').dataset.device === id, d.id);
    await fits();
  }
  // A screen response belonging to a closed window cannot enter its replacement.
  const screenWait = screenGate = defer();
  const oldWindow = poll(); await screenWait.seen;
  await page.locator('.ck-pane[data-pane="phone"] .act-close').click();
  await page.waitForFunction(() => !document.querySelector('.phw-modal'));
  await page.locator('[data-surf="phone"]').click();
  await page.waitForSelector('.phw-bezel[data-state="on"]');
  screenWait.release(); await oldWindow; await poll();
  assert.equal(await page.evaluate(async () => (await import('/static/js/phoneWindow.js'))._test.state().holder), 'agent');
  const takeoverWait = controlGate = defer(), cleanup = defer();
  await page.locator('.phw-take').click(); await takeoverWait.seen;
  await page.locator('.ck-pane[data-pane="phone"] .act-close').click();
  await page.waitForFunction(() => !document.querySelector('.phw-modal'));
  onHandBack = cleanup.arrived;
  takeoverWait.release(); await cleanup.seen;
  assert.equal(holder, 'agent');
  assert.deepEqual(controlRequests.slice(-2), ['person', 'agent']);
  await page.locator('[data-surf="phone"]').click();
  await page.waitForSelector('.phw-bezel[data-state="on"]');

  // Selecting Play is explicit, including when the SDK is already present.
  await page.getByLabel('Android image', { exact: true }).selectOption('google_play');
  await page.waitForFunction(() => document.querySelector('.phw-runtime').textContent.includes('Google Play developer'));
  const beforeConsent = requests.length;
  await page.locator('.phw-power').click();
  await page.waitForSelector('.phw-license:not([hidden])');
  assert.match(await page.locator('.phw-license').innerText(), /proprietary Google Play/);
  assert.equal(requests.length, beforeConsent);
  await page.locator('.phw-license-accept').click();
  await page.waitForSelector('.phw-bezel[data-state="starting"]');
  assert.equal(requests.at(-1).accept_license, true);
  state.state = 'on'; streamReady = true; await poll();
  await page.locator('.phw-transfer > summary').click();
  await page.locator('.phw-transfer input[type="file"]').setInputFiles({
    name: 'selected.txt', mimeType: 'application/octet-stream', buffer: Buffer.from('selected file'),
  });
  await page.waitForFunction(() => document.querySelector('.phw-transfer').textContent.includes('Checksum verified'));
  assert.equal(files[0].type, 'application/octet-stream'); assert.equal(files[0].data, 'selected file');
  await page.locator('.phw-doc-find').click();
  await page.waitForSelector('.phw-doc-select:not([hidden])');
  assert.equal(await page.locator('.phw-doc-select img').count(), 0);
  await page.locator('.phw-doc-send').click();
  await page.waitForFunction(() => document.querySelector('.phw-doc-send').disabled === false);
  assert.equal(JSON.parse(files[1].data).document_id, 'owned-document-fixture');
  await shot('mobile-play-transfer-fixture');

  state.mode = null; state.state = 'unavailable'; streamReady = false;
  state.why = 'No KVM is available on this test workstation.';
  state.why_not_android = 'No KVM is available on this test workstation.';
  await poll();
  assert.equal(await page.locator('.phw-stage').isVisible(), false);
  assert.equal(await page.locator('.phw-power').isEnabled(), false);
  await shot('mobile-android-blocker');
  await page.locator('.phw-preview').click();
  await page.waitForFunction(() => document.querySelector('.phw-runtime').textContent.includes('Browser preview'));
  assert.equal(requests.at(-1).action, 'preview');
  assert.match(await page.locator('.phw-runtime').innerText(), /Browser preview · Web only/);
  assert.match(await page.locator('.phw-runtime').innerText(), /No KVM/);
  assert.equal(await page.locator('.phw-power').getAttribute('aria-label'), 'Close preview');
  assert.equal(await page.locator('.phw-transfer').isVisible(), false);
  assert.equal(await page.locator('.phw-side[data-key="volume_up"]').isEnabled(), false);
  assert.equal(await page.locator('.phw-nav [data-key="recents"]').isVisible(), false);
  await shot('mobile-browser-preview-labelled');

  // Float and close use the existing window, including handing control back.
  await page.locator('.ck-pane[data-pane="phone"] .act-pop').click();
  await page.waitForSelector('body > .phw-modal');
  await page.locator('.phw-modal .close-btn').click();
  await page.waitForFunction(() => !document.querySelector('.phw-modal'));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true);
  await page.evaluate(() => document.querySelector('[data-open-phone]').click());
  await page.waitForSelector('.phw-modal .phw-runtime'); await poll(); await fits();
  assert.equal(await page.locator('.phw-power').isVisible(), true);
  await shot('mobile-narrow-browser-preview');
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ surfaces: 4, devices: devices.length, earlyStream: true,
    foldAnimation: true, rotationWrap: true, transformedTouch: true, reducedMotion: true,
    fallbackLabel: true, staleRequests: true, pendingTakeoverCleanup: true, legacyCrop: true, errors }));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_the_workspace_device_boot_controls_and_motion_in_a_browser(app_url, tmp_path):
    devices = [{"id": key, **value, "look": P.PHONE_LOOKS[key], "installed": True,
                "foldable": value["kind"] == "foldable", "android": "Android 15"}
               for key, value in P.PHONE_DEVICES.items()]
    script = tmp_path / "mobile.cjs"
    script.write_text(SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(devices)],
                          cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    result = json.loads(proc.stdout)
    assert result["devices"] == len(P.PHONE_DEVICES) and result["surfaces"] == 4
    assert result["earlyStream"] and result["transformedTouch"] and result["foldAnimation"]
