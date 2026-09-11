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

const _EMPTY = { name: '', cidrs: '', hosts: '', trust: 'limited', enabled: true };

let _rows = [];
let _loaded = false;

const $ = (id) => document.getElementById(id);

/** The on-screen rows as the shape the API and the setting both use. */
function toValue() {
  const split = (s) => String(s || '').split(/[\s,]+/).filter(Boolean);
  return _rows.map((r) => ({
    name: String(r.name || '').trim(),
    cidrs: split(r.cidrs),
    hosts: split(r.hosts).map((h) => h.toLowerCase()),
    trust: r.trust || 'limited',
    enabled: r.enabled !== false,
  }));
}

function fromValue(list) {
  return (Array.isArray(list) ? list : []).map((n) => ({
    name: n && n.name ? String(n.name) : '',
    cidrs: Array.isArray(n && n.cidrs) ? n.cidrs.join(' ') : '',
    hosts: Array.isArray(n && n.hosts) ? n.hosts.join(' ') : '',
    trust: (n && n.trust) || 'limited',
    enabled: !(n && n.enabled === false),
  }));
}

function render() {
  const host = $('networks-list');
  if (!host) return;
  host.textContent = '';
  if (_rows.length === 0) {
    const none = document.createElement('div');
    none.className = 'admin-toggle-sub';
    none.style.cssText = 'padding:10px 0;opacity:0.65;';
    none.textContent = 'No networks declared. With none declared this changes nothing — '
      + 'every path runs exactly as it does today.';
    host.appendChild(none);
    return;
  }
  _rows.forEach((row, i) => host.appendChild(rowEl(row, i)));
}

function rowEl(row, i) {
  const wrap = document.createElement('div');
  wrap.className = 'networks-row';

  const mk = (label, key, placeholder, width) => {
    const cell = document.createElement('label');
    cell.className = 'networks-cell';
    cell.style.flex = width;
    const cap = document.createElement('span');
    cap.className = 'networks-cell-label';
    cap.textContent = label;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'settings-select';
    input.value = row[key] || '';
    input.placeholder = placeholder;
    input.addEventListener('input', () => { row[key] = input.value; });
    cell.append(cap, input);
    return cell;
  };

  wrap.appendChild(mk('Name', 'name', 'home', '1 1 120px'));
  wrap.appendChild(mk('CIDRs', 'cidrs', '192.168.1.0/24', '2 1 180px'));
  wrap.appendChild(mk('Hosts', 'hosts', 'nas.local printer.local', '2 1 180px'));

  const trustCell = document.createElement('label');
  trustCell.className = 'networks-cell';
  trustCell.style.flex = '0 0 120px';
  const trustCap = document.createElement('span');
  trustCap.className = 'networks-cell-label';
  trustCap.textContent = 'Trust';
  const trust = document.createElement('select');
  trust.className = 'settings-select';
  for (const level of ['untrusted', 'limited', 'trusted']) {
    const opt = document.createElement('option');
    opt.value = level;
    opt.textContent = level;
    if (row.trust === level) opt.selected = true;
    trust.appendChild(opt);
  }
  trust.addEventListener('change', () => { row.trust = trust.value; });
  trustCell.append(trustCap, trust);
  wrap.appendChild(trustCell);

  const onCell = document.createElement('label');
  onCell.className = 'networks-cell networks-cell-switch';
  onCell.style.flex = '0 0 auto';
  const onCap = document.createElement('span');
  onCap.className = 'networks-cell-label';
  onCap.textContent = 'On';
  const sw = document.createElement('label');
  sw.className = 'admin-switch';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = row.enabled !== false;
  cb.addEventListener('change', () => { row.enabled = cb.checked; });
  const slider = document.createElement('span');
  slider.className = 'admin-slider';
  sw.append(cb, slider);
  onCell.append(onCap, sw);
  wrap.appendChild(onCell);

  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'memory-toolbar-btn networks-remove';
  del.textContent = 'Remove';
  del.title = 'Remove this network';
  del.addEventListener('click', () => {
    _rows.splice(i, 1);
    render();
  });
  wrap.appendChild(del);
  return wrap;
}

function showProblems(problems) {
  const box = $('networks-problems');
  if (!box) return;
  box.textContent = '';
  if (!problems || problems.length === 0) {
    box.hidden = true;
    return;
  }
  // Every problem, not the first — a form that reports one typo per round trip
  // is a form people give up on. Same reasoning as `validate_networks`.
  for (const p of problems) {
    const line = document.createElement('div');
    line.className = 'networks-problem';
    line.textContent = p;
    box.appendChild(line);
  }
  box.hidden = false;
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
      _rows.push({ ..._EMPTY });
      render();
    });
    $('networks-save')?.addEventListener('click', () => { save(); });
    $('networks-probe-go')?.addEventListener('click', () => { runProbe(); });
    $('networks-probe')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runProbe(); }
    });
    $('netagent-save')?.addEventListener('click', () => { saveAgent(); });
    $('netagent-check')?.addEventListener('click', () => { checkAgent(); });

    try {
      const res = await fetch('/api/auth/settings');
      const settings = res.ok ? await res.json() : {};
      if ($('netagent-url')) $('netagent-url').value = settings.netagent_url || '';
    } catch (_) { /* an unreadable settings response leaves the field empty, which is honest */ }
  }
  render();
}

export const _test = { toValue, fromValue, setRows: (r) => { _rows = r; }, getRows: () => _rows };
