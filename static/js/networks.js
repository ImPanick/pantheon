// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P17-09`. The panel for `src/networks.py`.
//
// That module has been enforcing since `P16-16` — it is consulted inside
// `check_outbound_url` and `outbound_fetch` BEFORE DNS — and it had no panel, no
// route of its own and no validation. `grep networks` returned nothing in this
// directory. The only way to declare one was a hand-built JSON body to
// `POST /api/auth/settings` or editing `data/settings.json`, and a malformed
// CIDR was accepted, logged to a file nobody watches, and silently dropped by
// `Network.__init__`. An allowlist the operator has no supported way to write is
// not operator-set, which is the premise `P17-02` is named after.
//
// **Every rule lives in Python.** Validation and "which network claims this
// address" both go to `POST /api/auth/networks/check`, because a CIDR matcher
// written here would be the same rule in two languages — which is `Law 13`, and
// is exactly how `B65` hid: a rule that reads one language cannot see what lives
// in the other.

import { invalidateSettings } from './appConfig.js';
import uiModule from './ui.js';   // `B730`: the shared empty state
// `B1475`. The rows are drawn by the one editor both network lists use.
import { EMPTY_ROW, renderRows, rowsToValue, showProblems as _showProblems, valueToRows } from './networkRows.js';

let _rows = [];
let _loaded = false;

const $ = (id) => document.getElementById(id);

/** The on-screen rows as the shape the API and the setting both use. */
function toValue() {
  return rowsToValue(_rows);
}

function fromValue(list) {
  return valueToRows(list);
}

function render() {
  renderRows($('networks-list'), _rows, {
    emptyText: 'No networks declared. With none declared this changes nothing — '
      + 'every path runs exactly as it does today.',
  });
}

function showProblems(problems) {
  _showProblems($('networks-problems'), problems);
}

function flashSaved() {
  const el = $('networks-saved');
  if (!el) return;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 2400);
}

async function check(probe) {
  const res = await fetch('/api/auth/networks/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ networks: toValue(), probe: probe || '' }),
  });
  if (!res.ok) throw new Error(`check failed (${res.status})`);
  return res.json();
}

async function save() {
  const value = toValue();
  // Ask first, so a refusal reads as "here is what is wrong" rather than as a
  // failed save. The server validates again on the way in regardless — this is
  // the courtesy, not the control.
  const verdict = await check('');
  showProblems(verdict.problems);
  if (verdict.problems && verdict.problems.length) return false;

  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ networks: value }),
  });
  if (!res.ok) {
    let detail = `Save failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = String(body.detail);
    } catch (_) { /* a non-JSON error body is still an error; keep the status */ }
    showProblems([detail]);
    return false;
  }
  // The shared settings snapshot is now a lie. Anything that reads it next —
  // including this panel on the next open — would get the pre-save value.
  invalidateSettings();
  flashSaved();
  return true;
}

async function runProbe() {
  const input = $('networks-probe');
  const out = $('networks-probe-result');
  if (!input || !out) return;
  const probe = input.value.trim();
  if (!probe) { out.hidden = true; return; }
  try {
    const verdict = await check(probe);
    showProblems(verdict.problems);
    out.textContent = verdict.matched
      ? `${probe} is in ${verdict.matched}.`
      : `${probe} is in no declared network — a run scoped to any of these would refuse it.`;
    out.classList.toggle('networks-probe-hit', !!verdict.matched);
    out.hidden = false;
  } catch (e) {
    out.textContent = String(e.message || e);
    out.classList.remove('networks-probe-hit');
    out.hidden = false;
  }
}

// ── the agent ───────────────────────────────────────────────────────────────
//
// Two fields and two buttons. The token is a password input and is never read
// back into it after a save: `scrub_settings` masks it for a non-admin, and
// re-populating a field from a GET is how a masked value gets written back over
// the real one.

async function saveAgent() {
  const url = ($('netagent-url')?.value || '').trim();
  const token = ($('netagent-token')?.value || '').trim();
  const out = $('netagent-result');
  const body = { netagent_url: url };
  // Only send the token when something was typed. An empty box means "leave it
  // alone", not "clear it" — clearing is what the Remove path would be for, and
  // silently wiping a credential because a field rendered blank is a support
  // ticket that looks like the agent going down on its own.
  if (token) body.netagent_token = token;

  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Save failed (${res.status})`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = String(err.detail);
    } catch (_) { /* a non-JSON error body is still an error; keep the status */ }
    if (out) { out.textContent = detail; out.classList.remove('networks-probe-hit'); out.hidden = false; }
    return false;
  }
  invalidateSettings();
  if ($('netagent-token')) $('netagent-token').value = '';
  await checkAgent();
  return true;
}

async function checkAgent() {
  const out = $('netagent-result');
  if (!out) return;
  try {
    const res = await fetch('/api/auth/networks/agent');
    const verdict = await res.json();
    if (!verdict.configured) {
      out.textContent = verdict.detail || 'No agent configured.';
    } else if (verdict.reachable) {
      out.textContent = `Reachable — agent version ${verdict.version}.`;
    } else {
      out.textContent = verdict.detail || 'Not reachable.';
    }
    out.classList.toggle('networks-probe-hit', !!verdict.reachable);
    out.hidden = false;
  } catch (e) {
    out.textContent = String(e.message || e);
    out.classList.remove('networks-probe-hit');
    out.hidden = false;
  }
}

// ── devices ─────────────────────────────────────────────────────────────────

function _ago(seconds) {
  if (seconds === null || seconds === undefined) return 'never seen';
  const days = Math.floor(seconds / 86400);
  if (days >= 1) return days === 1 ? '1 day' : `${days} days`;
  const hours = Math.floor(seconds / 3600);
  if (hours >= 1) return hours === 1 ? '1 hour' : `${hours} hours`;
  const mins = Math.max(1, Math.floor(seconds / 60));
  return mins === 1 ? '1 minute' : `${mins} minutes`;
}

function deviceRow(device) {
  const row = document.createElement('div');
  row.className = 'networks-row device-row';

  const name = document.createElement('input');
  name.type = 'text';
  name.className = 'settings-select';
  name.value = device.name || '';
  name.placeholder = 'name this device';
  name.style.flex = '1 1 150px';
  // Saved on blur rather than on every keystroke: a name is a deliberate act and
  // one request per character is a request per character.
  name.addEventListener('blur', async () => {
    if ((device.name || '') === name.value) return;
    await fetch('/api/auth/networks/devices/name', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac: device.mac, name: name.value }),
    });
    device.name = name.value;
  });
  row.appendChild(name);

  const addr = document.createElement('span');
  addr.className = 'device-cell device-address';
  addr.textContent = device.address || '—';
  if (device.previous_addresses && device.previous_addresses.length) {
    addr.title = `was ${device.previous_addresses.join(', ')}`;
  }
  row.appendChild(addr);

  const mac = document.createElement('span');
  mac.className = 'device-cell device-mac';
  // The stored MAC is bare hex; shown in the spelling people read it in.
  mac.textContent = (device.mac || '').replace(/(..)(?=.)/g, '$1:');
  row.appendChild(mac);

  const vendor = document.createElement('span');
  vendor.className = 'device-cell device-vendor';
  const v = device.vendor || {};
  // An unknown vendor is a normal answer and is rendered as one — saying where
  // the answer came from is the point, so "not in the shipped table" reads
  // differently from "randomised address, nobody assigned it".
  vendor.textContent = v.vendor || (v.locally_administered ? 'randomised / virtual' : 'unknown');
  if (!v.vendor) vendor.classList.add('device-vendor-unknown');
  if (v.detail) vendor.title = v.detail;
  row.appendChild(vendor);

  const age = document.createElement('span');
  age.className = 'device-cell device-age';
  age.textContent = device.is_new ? 'new' : _ago(device.age_seconds);
  if (device.is_new) age.classList.add('device-new');
  row.appendChild(age);

  if (device.kind && device.kind !== 'device') {
    const kind = document.createElement('span');
    kind.className = 'device-cell device-kind';
    kind.textContent = device.kind;
    row.appendChild(kind);
  }
  return row;
}

async function loadDevices() {
  const host = $('devices-list');
  const summary = $('devices-summary');
  if (!host) return;
  host.textContent = '';
  let state;
  try {
    const res = await fetch('/api/auth/networks/devices');
    if (!res.ok) throw new Error(`devices unavailable (${res.status})`);
    state = await res.json();
  } catch (e) {
    if (summary) { summary.textContent = String(e.message || e); summary.hidden = false; }
    return;
  }

  if (summary) {
    const parts = [`${state.count} known`];
    if (state.new && state.new.length) parts.push(`${state.new.length} new`);
    const r = state.refreshed;
    if (r && r.error) parts.push(r.error);
    else if (r) parts.push(`${r.seen} seen just now`);
    else parts.push('no agent configured — showing what is remembered');
    const table = state.vendor_table || {};
    if (!table.imported) parts.push('vendor names: shipped seed only');
    summary.textContent = parts.join(' · ');
    summary.hidden = false;
  }

  if (!state.devices || state.devices.length === 0) {
    const none = document.createElement('div');
    none.className = 'admin-toggle-sub';
    none.style.cssText = 'padding:10px 0;opacity:0.65;';
    none.textContent = 'Nothing remembered yet. Start the agent, allow a network, '
      + 'and press Refresh.';
    host.appendChild(none);
    return;
  }
  for (const device of state.devices) host.appendChild(deviceRow(device));
}

// ── host commands ───────────────────────────────────────────────────────────
//
// Two lists rendered side by side, and the page says which one is the boundary.
// The agent's list is fetched read-only from `/guard` through Pantheon, because
// a boundary nobody can read is a boundary nobody can check — and showing it
// beside the editable one is the clearest way to say that only one of them can
// be edited.

const _lines = (value) => String(value || '').split('\n').map((s) => s.trim()).filter(Boolean);

async function saveHostLists() {
  const out = $('host-exec-result');
  const body = {
    host_exec_allowlist: _lines($('host-exec-allowlist')?.value),
    host_exec_denylist: _lines($('host-exec-denylist')?.value),
  };
  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Save failed (${res.status})`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = String(err.detail);
    } catch (_) { /* a non-JSON error body is still an error; keep the status */ }
    if (out) { out.textContent = detail; out.classList.remove('networks-probe-hit'); out.hidden = false; }
    return false;
  }
  invalidateSettings();
  if (out) {
    const n = body.host_exec_allowlist.length;
    out.textContent = n
      ? `Saved. Only these ${n} program${n === 1 ? '' : 's'} may run on the host.`
      : 'Saved. No allowlist, so the denylist and the agent\'s own list decide.';
    out.classList.add('networks-probe-hit');
    out.hidden = false;
  }
  return true;
}

async function showGuard() {
  const host = $('host-exec-guard');
  if (!host) return;
  if (!host.hidden) { host.hidden = true; return; }
  host.textContent = '';
  try {
    const res = await fetch('/api/auth/networks/guard');
    if (!res.ok) throw new Error(`unavailable (${res.status})`);
    const data = await res.json();
    const intro = document.createElement('div');
    intro.className = 'admin-toggle-sub';
    intro.style.cssText = 'margin-bottom:8px;line-height:1.5;';
    intro.textContent = `${data.count} rules, compiled into the agent on your machine. `
      + 'Read-only from here — there is no setting, flag or request that widens them.';
    host.appendChild(intro);
    for (const rule of data.rules || []) {
      const row = document.createElement('div');
      row.className = 'host-guard-row';
      const name = document.createElement('span');
      name.className = 'host-guard-name';
      name.textContent = rule.name;
      const why = document.createElement('span');
      why.className = 'host-guard-why';
      why.textContent = rule.why;
      row.append(name, why);
      host.appendChild(row);
    }
    host.hidden = false;
  } catch (e) {
    host.textContent = String(e.message || e);
    host.hidden = false;
  }
}

// ── each person's networks (`B1475`) ───────────────────────────────────────
//
// The switch, and every person's networks, read-only. The server sends of a
// linked vault login only `login_linked` — never which item, its name or
// anything in it (`person_networks.everyone`), so there is nothing here to
// leak (`D-2026-10-25-04` §5).

function personRow(person, net) {
  const row = document.createElement('div');
  row.className = 'networks-row networks-person-row';
  const cell = (cls, text) => {
    const el = document.createElement('span');
    el.className = `device-cell ${cls}`;
    el.textContent = text;
    row.appendChild(el);
    return el;
  };
  const who = cell('networks-person-account', person.person || person.account);
  who.title = person.account;
  cell('networks-person-name', net.name || '');
  const where = [...(net.cidrs || []), ...(net.hosts || [])].join(' ') || 'nothing';
  cell('networks-person-where', where);
  cell('networks-person-trust', net.trust === 'untrusted' ? 'untrusted' : 'trusted');
  if (net.enabled === false) cell('networks-person-off', 'off');
  if (net.login_linked) {
    const badge = cell('networks-person-login', 'login linked');
    badge.title = 'A login from their vault is linked. Which one, and what is in it, is theirs.';
  }
  return row;
}

async function loadPeople() {
  const host = $('networks-people');
  const box = $('networks-per-person');
  if (!host) return;
  host.textContent = '';
  let state;
  // `B730`. Both states through the shared shape: a read that failed says so
  // with *Try again* (it was a bare line of text); none declared says so.
  try {
    const res = await fetch('/api/networks/people');
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error((body && body.detail) || `The server answered ${res.status}.`);
    }
    state = await res.json();
  } catch (e) {
    uiModule.renderEmptyState(host, {
      kind: 'error', title: "Could not load everyone's networks",
      reason: String(e.message || e), onRetry: () => loadPeople(),
    });
    return;
  }
  if (box) box.checked = !!state.enabled;
  const people = Array.isArray(state.people) ? state.people : [];
  if (!people.length) {
    uiModule.renderEmptyState(host, {
      kind: 'empty', icon: null,
      title: state.enabled
        ? 'Nobody has declared a network of their own yet.'
        : 'Nobody has declared a network of their own.',
    });
    return;
  }
  for (const person of people) {
    for (const net of person.networks || []) host.appendChild(personRow(person, net));
  }
}

async function savePerPerson(on) {
  const out = $('networks-people-result');
  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ networks_per_person: !!on }),
  });
  if (out) {
    out.textContent = res.ok
      ? (on ? 'On. Each person declares their own networks in Settings → My networks.'
        : 'Off. Only the networks above apply; what people saved is kept.')
      : `Not saved (${res.status}).`;
    out.classList.toggle('networks-probe-hit', res.ok);
    out.hidden = false;
  }
  if (res.ok) invalidateSettings();
  await loadPeople();
}

export async function open() {
  if (!_loaded) {
    try {
      const res = await fetch('/api/auth/settings');
      const settings = res.ok ? await res.json() : {};
      _rows = fromValue(settings && settings.networks);
    } catch (_) {
      _rows = [];
    }
    _loaded = true;

    $('networks-add')?.addEventListener('click', () => {
      _rows.push({ ...EMPTY_ROW });
      render();
    });
    $('networks-save')?.addEventListener('click', () => { save(); });
    $('networks-probe-go')?.addEventListener('click', () => { runProbe(); });
    $('networks-probe')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runProbe(); }
    });
    $('netagent-save')?.addEventListener('click', () => { saveAgent(); });
    $('netagent-check')?.addEventListener('click', () => { checkAgent(); });
    $('devices-refresh')?.addEventListener('click', () => { loadDevices(); });
    $('host-exec-save')?.addEventListener('click', () => { saveHostLists(); });
    $('host-exec-show-guard')?.addEventListener('click', () => { showGuard(); });
    $('networks-per-person')?.addEventListener('change', (e) => { savePerPerson(e.target.checked); });

    try {
      const res = await fetch('/api/auth/settings');
      const settings = res.ok ? await res.json() : {};
      if ($('netagent-url')) $('netagent-url').value = settings.netagent_url || '';
      if ($('host-exec-allowlist')) $('host-exec-allowlist').value = (settings.host_exec_allowlist || []).join('\n');
      if ($('host-exec-denylist')) $('host-exec-denylist').value = (settings.host_exec_denylist || []).join('\n');
    } catch (_) { /* an unreadable settings response leaves the field empty, which is honest */ }
  }
  render();
  loadDevices();
  loadPeople();
}

export const _test = { toValue, fromValue, setRows: (r) => { _rows = r; }, getRows: () => _rows };
