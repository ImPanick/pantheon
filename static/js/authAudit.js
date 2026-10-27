// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/authAudit.js — `B684`. The auth audit log's reader.
//
// `P11-08` writes a `kind="auth"` row for every sign-in, sign-up, role and
// privilege change and every refusal of one, and nothing read them: usage,
// receipts and the metrics export all filter other kinds, so "who logged in,
// who changed a role, what was refused" was answerable only with SQL against
// `data/app.db` — in the one place a person reaches for after something has
// gone wrong. This draws `GET /api/diagnostics/auth-events`: failures first by
// default (the successful sign-ins are the noise), filtered by outcome, and by
// an account that either acted or was acted on — an admin action names two
// people and only one of them is in the indexed column.
//
// Text only: every value here is server-derived, and an account name is
// exactly the string a hostile sign-up would choose.

import uiModule from './ui.js';

const $ = (id) => document.getElementById(id);

function _cell(tr, text, cls) {
  const td = document.createElement('td');
  td.textContent = String(text ?? '');
  if (cls) td.className = cls;
  tr.appendChild(td);
}

function _when(ts) {
  return ts ? String(ts).replace('T', ' ').replace(/\.\d+Z?$|Z$/, '') : '';
}

function _detail(d) {
  if (!d || typeof d !== 'object') return '';
  return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ');
}

/** Ask and draw. Resolves to the server's answer, or null. */
export async function load() {
  const body = $('auth-audit-body');
  if (!body) return null;
  const outcome = $('auth-audit-outcome')?.value || 'all';
  const party = ($('auth-audit-party')?.value || '').trim();
  const limit = $('auth-audit-limit')?.value || '100';
  const qs = new URLSearchParams({ outcome, limit });
  if (party) qs.set('party', party);
  body.textContent = 'Loading…';
  let res, data;
  // `B730`. Three states in the one shape (`ui.renderEmptyState`): it broke —
  // the server's words and *Try again*; nothing matched the filter — and the
  // way back to everything; nothing recorded at all.
  const broke = (reason) => {
    uiModule.renderEmptyState(body, {
      kind: 'error', className: 'usage-empty', title: 'Could not load the audit log',
      reason, onRetry: () => load(),
    });
  };
  try {
    res = await fetch(`/api/diagnostics/auth-events?${qs}`, { credentials: 'same-origin' });
    data = await res.json().catch(() => ({}));
  } catch (_) {
    broke('Could not reach this Pantheon.');
    return null;
  }
  if (!res.ok) {
    broke(String((data && data.detail) || `The server answered ${res.status}.`));
    return null;
  }
  body.replaceChildren();
  if (data.error) {
    broke(String(data.error));
    return data;
  }
  const events = Array.isArray(data.events) ? data.events : [];
  if (!events.length) {
    const filtered = !!party || outcome !== 'all';
    if (filtered) {
      uiModule.renderEmptyState(body, {
        kind: 'filtered', className: 'usage-empty',
        title: party ? `Nothing recorded for ${party} with this filter` : 'Nothing recorded with this filter',
        action: { label: 'Show every event', onClick: () => {
          if ($('auth-audit-party')) $('auth-audit-party').value = '';
          if ($('auth-audit-outcome')) $('auth-audit-outcome').value = 'all';
          load();
        } },
      });
    } else {
      uiModule.renderEmptyState(body, {
        kind: 'empty', className: 'usage-empty', title: 'Nothing recorded yet',
        message: 'Sign-ins, account and role changes are recorded from this build on.',
      });
    }
    return data;
  }
  const failures = events.filter((e) => e.outcome !== 'ok').length;
  const head = document.createElement('p');
  head.className = 'usage-headline';
  head.textContent = `${events.length} event${events.length === 1 ? '' : 's'}`
    + (failures ? ` · ${failures} refused or failed` : '');
  body.appendChild(head);
  const table = document.createElement('table');
  table.className = 'usage-table auth-audit-table';
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  for (const h of ['When (UTC)', 'What', 'By', 'To', 'Outcome', 'Detail']) {
    const th = document.createElement('th');
    th.textContent = h;
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (const e of events) {
    const tr = document.createElement('tr');
    if (e.outcome !== 'ok') tr.className = 'is-failure';
    _cell(tr, _when(e.ts));
    _cell(tr, e.action);
    _cell(tr, e.actor);
    _cell(tr, e.subject);
    _cell(tr, e.outcome === 'ok' ? 'ok' : 'refused / failed', e.outcome === 'ok' ? '' : 'is-failure');
    _cell(tr, _detail(e.detail));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  body.appendChild(table);
  return data;
}

let _wired = false;

/** Called by Diagnostics when the panel is opened. */
export function open() {
  if (!_wired) {
    _wired = true;
    $('auth-audit-outcome')?.addEventListener('change', () => { load(); });
    $('auth-audit-limit')?.addEventListener('change', () => { load(); });
    let t = null;
    $('auth-audit-party')?.addEventListener('input', () => {
      clearTimeout(t);
      t = setTimeout(() => { load(); }, 300);
    });
  }
  return load();
}
