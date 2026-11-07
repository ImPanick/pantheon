// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/settings/push.js — Settings → Reminders → "Push to your devices".
//
// `B1832`. Turns Web Push on or off for the browser this page is open in, lists
// the person's devices, removes one, and sends a test. The server half is
// `routes/push_routes.py` / `src/web_push.py`; the notification itself, and
// its Approve and Deny, are `static/sw.js`.
//
// Push needs a secure page (https, or localhost) and a service worker. A phone
// on the LAN at http://192.168.x.x is neither, so the state line says so and
// names the fix rather than leaving a button that fails.
import { byId } from './dom.js';

const API = {
  key: '/api/push/key',
  devices: '/api/push/subscriptions',
  test: '/api/push/test',
};

function keyBytes(base64url) {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}

function sameKey(buffer, bytes) {
  if (!buffer) return false;
  const a = new Uint8Array(buffer);
  return a.length === bytes.length && a.every((v, i) => v === bytes[i]);
}

export function deviceLabel(ua = navigator.userAgent || '') {
  const browser = /Edg\//.test(ua) ? 'Edge'
    : /SamsungBrowser\//.test(ua) ? 'Samsung Internet'
    : /Firefox\//.test(ua) ? 'Firefox'
    : /Chrome\//.test(ua) ? 'Chrome'
    : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const system = /iPhone/.test(ua) ? 'iPhone'
    : /iPad/.test(ua) ? 'iPad'
    : /Android/.test(ua) ? (/Mobile/.test(ua) ? 'Android phone' : 'Android tablet')
    : /Windows/.test(ua) ? 'Windows'
    : /Mac OS X|Macintosh/.test(ua) ? 'Mac'
    : /Linux/.test(ua) ? 'Linux' : 'Device';
  return `${browser} on ${system}`;
}

/** Why this browser cannot take push, in words with the fix — or `''`. */
export function pushBlocker(env = {}) {
  const {
    secure = window.isSecureContext,
    hasWorker = 'serviceWorker' in navigator,
    hasPush = 'PushManager' in window,
    permission = (typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'),
    ua = navigator.userAgent || '',
    standalone = !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true,
    origin = location.origin,
  } = env;
  if (!secure) {
    return `Push needs a secure address, and ${origin} is not one. Open Pantheon over https `
      + '(docs/setup.md, "Reach Pantheon from your phone") or on localhost.';
  }
  if (/iPhone|iPad/.test(ua) && !standalone) {
    return 'On iPhone and iPad, add Pantheon to the Home Screen first (Share, then Add to Home Screen), then open it from there and turn push on.';
  }
  if (!hasWorker || !hasPush || permission === 'unsupported') {
    return 'This browser cannot receive push notifications.';
  }
  if (permission === 'denied') {
    return 'Notifications are blocked for this site. Allow them in the browser\'s site settings, then come back.';
  }
  return '';
}

async function json(res) {
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) throw new Error(data.detail || `Pantheon answered ${res.status}`);
  return data;
}

async function currentSubscription() {
  if (pushBlocker()) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

async function turnOn() {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error('Notifications were not allowed.');
  const { public_key: key } = await json(await fetch(API.key));
  const serverKey = keyBytes(key);
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  // A subscription made for another key (the data volume was reset) cannot
  // carry this server's pushes, so it is replaced.
  if (sub && !sameKey(sub.options && sub.options.applicationServerKey, serverKey)) {
    await sub.unsubscribe().catch(() => {});
    sub = null;
  }
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey });
  }
  await json(await fetch(API.devices, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ subscription: sub.toJSON(), label: deviceLabel() }),
  }));
}

/** This browser stops receiving pushes, and the server forgets it. */
export async function turnOffHere() {
  const sub = await currentSubscription().catch(() => null);
  if (!sub) return false;
  const endpoint = sub.endpoint;
  await sub.unsubscribe().catch(() => {});
  await fetch(API.devices, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint }),
  }).catch(() => {});
  return true;
}

function say(text, tone = '') {
  const msg = byId('set-push-msg');
  if (!msg) return;
  msg.textContent = text;
  msg.dataset.tone = tone;
}

function when(seconds) {
  if (!seconds) return '';
  try {
    return new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch (_) { return ''; }
}

function renderDevices(devices, hereEndpoint) {
  const list = byId('set-push-devices');
  if (!list) return;
  list.replaceChildren();
  for (const d of devices) {
    const row = document.createElement('div');
    row.className = 'push-device';
    const name = document.createElement('span');
    name.className = 'push-device-name';
    name.textContent = d.label || 'Device';
    if (hereEndpoint && d.endpoint === hereEndpoint) {
      const here = document.createElement('span');
      here.className = 'push-device-here';
      here.textContent = 'this device';
      name.append(' ', here);
    }
    const meta = document.createElement('span');
    meta.className = 'push-device-meta';
    const added = when(d.created_at);
    const last = d.last_status ? (d.last_status >= 200 && d.last_status < 300 ? 'last push delivered' : `last push: ${d.last_status}`) : '';
    meta.textContent = [added && `added ${added}`, last].filter(Boolean).join(' · ');
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'admin-btn-sm';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', `Remove ${d.label || 'device'}`);
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        if (hereEndpoint && d.endpoint === hereEndpoint) {
          await turnOffHere();
        } else {
          await json(await fetch(API.devices, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: d.id }),
          }));
        }
        say('Removed.', 'ok');
      } catch (e) {
        say(e.message, 'error');
      }
      refresh();
    });
    row.append(name, meta, remove);
    list.append(row);
  }
}

let refreshing = null;

async function refreshNow() {
  const state = byId('set-push-state');
  const enable = byId('set-push-enable');
  const test = byId('set-push-test');
  if (!state || !enable || !test) return;
  let devices = [];
  try {
    devices = (await json(await fetch(API.devices))).devices || [];
  } catch (e) {
    state.textContent = e.message;
  }
  const blocker = pushBlocker();
  let sub = null;
  if (!blocker) sub = await currentSubscription().catch(() => null);
  const here = sub && devices.some(d => d.endpoint === sub.endpoint) ? sub.endpoint : '';
  renderDevices(devices, here);
  test.disabled = devices.length === 0;
  if (blocker) {
    state.textContent = blocker;
    enable.hidden = true;
    return;
  }
  enable.hidden = false;
  enable.dataset.on = here ? '1' : '0';
  enable.textContent = here ? 'Turn off for this device' : 'Turn on for this device';
  enable.className = here ? 'admin-btn-sm' : 'admin-btn-add';
  state.textContent = here
    ? 'On for this device. Tool approvals arrive with Approve and Deny.'
    : 'Off for this device.';
}

function refresh() {
  if (!refreshing) refreshing = refreshNow().finally(() => { refreshing = null; });
  return refreshing;
}

export function initPushSettings() {
  const enable = byId('set-push-enable');
  const test = byId('set-push-test');
  if (!enable || !test || enable.dataset.bound === '1') return;
  enable.dataset.bound = '1';
  enable.addEventListener('click', async () => {
    enable.disabled = true;
    say('');
    try {
      if (enable.dataset.on === '1') {
        await turnOffHere();
        say('Push is off for this device.', 'ok');
      } else {
        await turnOn();
        say('Push is on. Send a test to see it.', 'ok');
      }
    } catch (e) {
      say(e.message || String(e), 'error');
    } finally {
      enable.disabled = false;
      refresh();
    }
  });
  test.addEventListener('click', async () => {
    test.disabled = true;
    say('Sending…');
    try {
      const { results = [] } = await json(await fetch(API.test, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      }));
      const ok = results.filter(r => r.ok).length;
      const failed = results.filter(r => !r.ok);
      say(failed.length
        ? `Sent to ${ok} of ${results.length}. ${failed.map(r => `${r.label}: ${r.error || r.status}`).join(' ')}`
        : `Sent to ${ok} ${ok === 1 ? 'device' : 'devices'}.`, failed.length ? 'error' : 'ok');
    } catch (e) {
      say(e.message, 'error');
    } finally {
      refresh();
    }
  });
  refresh();
}
