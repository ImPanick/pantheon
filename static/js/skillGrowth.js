// SPDX-License-Identifier: AGPL-3.0-or-later
// skillGrowth.js — the Skills window's *Growth* view (`P13-08`).
//
// What the system learned this week and whether it held up, as a dated list a
// person reads, sorts and acts on: each skill that formed, got stronger or
// weaker, was published or sent back to draft, was tested, used, or removed —
// and why, when something said why. The rows are `GET /api/skills/growth`'s;
// the words in them (`said`, `why`, `sentence`) are the server's, written once
// beside the change they describe, so this file draws and sorts and decides
// nothing about what a change means (`Law 7`).
//
// A table, not a chart: the row's `Verify:` is *a cold reader can say which
// skills got better this week, and why, from the page alone* — a reading task,
// not a viewing one (`Law 15`).

/** The columns, in order. `key` is the row field a header sorts by. */
export const GROWTH_COLUMNS = Object.freeze([
  Object.freeze({ key: 'at', label: 'When' }),
  Object.freeze({ key: 'skill', label: 'Skill' }),
  Object.freeze({ key: 'said', label: 'What happened' }),
  Object.freeze({ key: 'why', label: 'Why' }),
]);

/** The periods the view offers, in days; the server holds 1–90. */
export const GROWTH_PERIODS = Object.freeze([7, 30, 90]);

/** `rows` sorted by `key`, newest or A→Z first when `dir` is `desc`/`asc`.
 *  A copy; ties keep the server's order (newest first). */
export function sortGrowthRows(rows, key = 'at', dir = 'desc') {
  const sign = dir === 'asc' ? 1 : -1;
  const value = (r) => {
    const v = r && r[key];
    return v === null || v === undefined ? '' : String(v).toLowerCase();
  };
  return (Array.isArray(rows) ? rows : [])
    .map((r, i) => [r, i])
    .sort((a, b) => {
      const x = value(a[0]);
      const y = value(b[0]);
      if (x < y) return -sign;
      if (x > y) return sign;
      return a[1] - b[1];
    })
    .map(([r]) => r);
}

/** When a row happened, as a person reads a date: the day and the time, in
 *  their own locale and time zone. The full timestamp is the cell's title. */
export function growthWhen(iso) {
  const d = new Date(iso || '');
  if (Number.isNaN(d.getTime())) return '';
  const day = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return `${day}, ${time}`;
}

function _text(doc, tag, text, className) {
  const el = doc.createElement(tag);
  if (className) el.className = className;
  el.textContent = text == null ? '' : String(text);
  return el;
}

/**
 * Draw `data` (`GET /api/skills/growth`'s answer) into `host`.
 *
 * `state` is `{ key, dir }`, the sort; a header press calls `onSort(key)`. A
 * skill still there is a button that calls `onOpen(name)` — the way to act on
 * a row: open the skill, then publish, test, fix or delete it on its card. A
 * removed one is its name and nothing to press. Text only, never markup.
 */
export function renderGrowth(host, data, { state = { key: 'at', dir: 'desc' }, onSort, onOpen } = {}) {
  if (!host) return 0;
  const doc = host.ownerDocument || document;
  const rows = sortGrowthRows((data && data.rows) || [], state.key, state.dir);
  host.replaceChildren();
  if (!rows.length) {
    host.appendChild(_text(doc, 'p', 'Nothing to list for this period. A skill appears here when '
      + 'it forms, is tested, is used in a chat, or changes.', 'skills-growth-empty'));
    return 0;
  }
  const table = doc.createElement('table');
  table.className = 'skills-growth-table';
  const head = doc.createElement('thead');
  const hr = doc.createElement('tr');
  for (const col of GROWTH_COLUMNS) {
    const th = doc.createElement('th');
    th.setAttribute('scope', 'col');
    const on = state.key === col.key;
    th.setAttribute('aria-sort', on ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none');
    const btn = _text(doc, 'button', col.label + (on ? (state.dir === 'asc' ? ' ↑' : ' ↓') : ''),
      'skills-growth-sort');
    btn.type = 'button';
    btn.dataset.sort = col.key;
    btn.title = `Sort by ${col.label.toLowerCase()}`;
    if (onSort) btn.addEventListener('click', () => onSort(col.key));
    th.appendChild(btn);
    hr.appendChild(th);
  }
  head.appendChild(hr);
  table.appendChild(head);
  const body = doc.createElement('tbody');
  for (const r of rows) {
    const tr = doc.createElement('tr');
    tr.dataset.change = r.change || '';
    const when = _text(doc, 'td', growthWhen(r.at));
    if (r.at) when.title = r.at;
    tr.appendChild(when);
    const name = doc.createElement('td');
    if (r.exists && onOpen) {
      const open = _text(doc, 'button', r.skill, 'skills-growth-open');
      open.type = 'button';
      open.title = `Open ${r.skill}`;
      open.addEventListener('click', () => onOpen(r.skill));
      name.appendChild(open);
    } else {
      name.textContent = r.skill || '';
      if (!r.exists) name.title = 'This skill is gone.';
    }
    tr.appendChild(name);
    tr.appendChild(_text(doc, 'td', r.said));
    tr.appendChild(_text(doc, 'td', r.why || '—'));
    body.appendChild(tr);
  }
  table.appendChild(body);
  host.appendChild(table);
  return rows.length;
}

/** Ask the server for `days` days of growth. Resolves to the answer, or to
 *  `{ rows: [], sentence }` saying why there is none. */
export async function fetchGrowth(days = 7, fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(`/api/skills/growth?days=${encodeURIComponent(days)}`,
      { credentials: 'same-origin' });
    if (!res.ok) {
      return { rows: [], sentence: `Couldn't load what your skills did (the server answered ${res.status}).` };
    }
    return await res.json();
  } catch (_) {
    return { rows: [], sentence: "Couldn't reach Pantheon to load what your skills did." };
  }
}
