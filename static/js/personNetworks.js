// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1475`, `D-2026-10-25-04` §5. Settings → My networks: the networks a person
// declares for their own runs, each with a login from their own vault the agent
// may sign in with there.
//
// Paths (`check-unreachable.py`): GET and PUT /api/networks/mine,
// POST /api/networks/mine/check, and GET /api/vault/mine for the logins.
//
// **Every rule lives in Python** (`src/person_networks.py`, which asks
// `src/networks.py`): what is wrong with a list, and which network claims an
// address, are both asked of the server about what is on screen.

import { EMPTY_ROW, renderRows, rowsToValue, showProblems, valueToRows } from './networkRows.js';

let _rows = [];
let _logins = [];
let _wired = false;

const $ = (id) => document.getElementById(id);

function render() {
  renderRows($('my-networks-list'), _rows, {
    emptyText: 'None yet. Your runs see the install’s networks only.',
    logins: _logins,
  });
}

function _value() {
  return rowsToValue(_rows, { withLogin: true });
}

async function _detail(res) {
  try {
    const body = await res.json();
    if (body && body.detail) return String(body.detail);
  } catch (_) { /* a non-JSON error body is still an error; keep the status */ }
  return `The server answered ${res.status}.`;
}

async function check(probe) {
  const res = await fetch('/api/networks/mine/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ networks: _value(), probe: probe || '' }),
  });
  if (!res.ok) throw new Error(await _detail(res));
  return res.json();
}

async function save() {
  const res = await fetch('/api/networks/mine', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ networks: _value() }),
  });
  if (!res.ok) {
    showProblems($('my-networks-problems'), [await _detail(res)]);
    return false;
  }
  showProblems($('my-networks-problems'), []);
  _apply(await res.json());
  const saved = $('my-networks-saved');
  if (saved) {
    saved.hidden = false;
    setTimeout(() => { saved.hidden = true; }, 2400);
  }
  return true;
}

async function runProbe() {
  const input = $('my-networks-probe');
  const out = $('my-networks-probe-result');
  if (!input || !out) return;
  const probe = input.value.trim();
  if (!probe) { out.hidden = true; return; }
  try {
    const verdict = await check(probe);
    showProblems($('my-networks-problems'), verdict.problems);
    out.textContent = verdict.matched
      ? `${probe} is in ${verdict.matched}.`
      : `${probe} is in none of yours.`;
    out.classList.toggle('networks-probe-hit', !!verdict.matched);
  } catch (e) {
    out.textContent = String(e.message || e);
    out.classList.remove('networks-probe-hit');
  }
  out.hidden = false;
}

function _apply(state) {
  const on = !!(state && state.enabled);
  const off = $('my-networks-off');
  if (off) {
    off.textContent = on ? '' : String(state && state.off ? state.off : '');
    off.hidden = on;
  }
  // Off, the saved list is kept and still shown, read-only: nothing is lost,
  // and the person can see what will apply when it is turned back on.
  const body = $('my-networks-body');
  if (body) body.classList.toggle('my-networks-readonly', !on);
  for (const id of ['my-networks-add', 'my-networks-save']) {
    const el = $(id);
    if (el) el.disabled = !on;
  }
  const taken = Array.isArray(state && state.install) ? state.install : [];
  const install = $('my-networks-install');
  if (install) {
    install.textContent = taken.length
      ? `Your admin's networks, which your runs also see: ${taken.join(', ')}.`
      : '';
    install.hidden = !taken.length;
  }
  _rows = valueToRows(state && state.networks);
  render();
}

async function _loadLogins() {
  try {
    const res = await fetch('/api/vault/mine');
    if (!res.ok) return [];
    const vault = await res.json();
    return (Array.isArray(vault.items) ? vault.items : [])
      .filter((it) => it && it.kind !== 'note')
      .map((it) => ({ id: it.id, label: it.label }));
  } catch (_) {
    return [];
  }
}

export async function open() {
  if (!_wired) {
    _wired = true;
    $('my-networks-add')?.addEventListener('click', () => {
      _rows.push({ ...EMPTY_ROW });
      render();
    });
    $('my-networks-save')?.addEventListener('click', () => { save(); });
    $('my-networks-probe-go')?.addEventListener('click', () => { runProbe(); });
    $('my-networks-probe')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runProbe(); }
    });
  }
  _logins = await _loadLogins();
  try {
    const res = await fetch('/api/networks/mine');
    if (!res.ok) throw new Error(await _detail(res));
    _apply(await res.json());
  } catch (e) {
    showProblems($('my-networks-problems'), [String(e.message || e)]);
  }
}

export const _test = { getRows: () => _rows, setRows: (r) => { _rows = r; }, value: _value, apply: _apply };
