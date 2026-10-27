// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1475`. The rows of a network list — name, ranges, hosts, trust, on — drawn
// once for both lists that have them: the install's (Settings → Networks,
// `networks.js`) and a person's own (Settings → My networks,
// `personNetworks.js`), which adds a column for the vault login it links.
// One editor, so the two cannot come to disagree about what a network is.
//
// **Every rule lives in Python** (`src/networks.py`): this file shapes what is
// on screen into the value the API takes and back, and nothing more — no CIDR
// matching, no validation (`Law 13`).
import uiModule from './ui.js';

// `D-2026-10-25-03`. Two trust levels: trusted (the agent's own connections may
// go there) and untrusted (listed, never connected to). The retired "limited"
// always behaved as trusted, so a saved one reads as that.
export const TRUST_LEVELS = ['trusted', 'untrusted'];
export const trustOf = (t) => (t === 'untrusted' ? 'untrusted' : 'trusted');
export const EMPTY_ROW = { name: '', cidrs: '', hosts: '', trust: 'trusted', enabled: true, login: '' };

/** The on-screen rows as the shape the API and the setting both use. A row's
 *  `login` is sent only by a list that has the column (`withLogin`). */
export function rowsToValue(rows, { withLogin = false } = {}) {
  const split = (s) => String(s || '').split(/[\s,]+/).filter(Boolean);
  return rows.map((r) => {
    const out = {
      name: String(r.name || '').trim(),
      cidrs: split(r.cidrs),
      hosts: split(r.hosts).map((h) => h.toLowerCase()),
      trust: trustOf(r.trust),
      enabled: r.enabled !== false,
    };
    if (r.notes) out.notes = String(r.notes);
    if (withLogin && r.login) out.login = String(r.login);
    return out;
  });
}

export function valueToRows(list) {
  return (Array.isArray(list) ? list : []).map((n) => ({
    name: n && n.name ? String(n.name) : '',
    cidrs: Array.isArray(n && n.cidrs) ? n.cidrs.join(' ') : '',
    hosts: Array.isArray(n && n.hosts) ? n.hosts.join(' ') : '',
    trust: trustOf(n && n.trust),
    enabled: !(n && n.enabled === false),
    notes: n && n.notes ? String(n.notes) : '',
    login: n && n.login ? String(n.login) : '',
    loginMissing: !!(n && n.login_missing),
  }));
}

function _cell(label, flex) {
  const cell = document.createElement('label');
  cell.className = 'networks-cell';
  cell.style.flex = flex;
  const cap = document.createElement('span');
  cap.className = 'networks-cell-label';
  cap.textContent = label;
  cell.appendChild(cap);
  return cell;
}

function _rowEl(rows, row, i, opts, redraw) {
  const wrap = document.createElement('div');
  wrap.className = 'networks-row';

  const text = (label, key, placeholder, flex) => {
    const cell = _cell(label, flex);
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'settings-select';
    input.value = row[key] || '';
    input.placeholder = placeholder;
    input.addEventListener('input', () => { row[key] = input.value; });
    cell.appendChild(input);
    return cell;
  };
  wrap.appendChild(text('Name', 'name', 'home', '1 1 120px'));
  wrap.appendChild(text('CIDRs', 'cidrs', '192.168.1.0/24', '2 1 180px'));
  wrap.appendChild(text('Hosts', 'hosts', 'nas.local printer.local', '2 1 180px'));

  const trustCell = _cell('Trust', '0 0 120px');
  const trust = document.createElement('select');
  trust.className = 'settings-select';
  trust.title = 'Trusted: the agent may connect there (a page fetch, a reach check). Untrusted: listed, never connected to.';
  for (const level of TRUST_LEVELS) {
    const opt = document.createElement('option');
    opt.value = level;
    opt.textContent = level;
    if (row.trust === level) opt.selected = true;
    trust.appendChild(opt);
  }
  trust.addEventListener('change', () => { row.trust = trust.value; });
  trustCell.appendChild(trust);
  wrap.appendChild(trustCell);

  if (Array.isArray(opts.logins)) {
    // `B1475`. A login from the person's own vault the agent signs in with
    // there. Chosen by name; the value never reaches this page.
    const loginCell = _cell('Login', '1 1 150px');
    const sel = document.createElement('select');
    sel.className = 'settings-select networks-login';
    sel.title = 'A login from your vault the agent may sign in with on this network. It never sees the password.';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = row.loginMissing ? '(its login was removed)' : 'None';
    sel.appendChild(none);
    for (const item of opts.logins) {
      const opt = document.createElement('option');
      opt.value = String(item.id);
      opt.textContent = String(item.label || item.id);
      if (String(row.login || '') === String(item.id)) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener('change', () => { row.login = sel.value; row.loginMissing = false; });
    loginCell.appendChild(sel);
    wrap.appendChild(loginCell);
  }

  const onCell = _cell('On', '0 0 auto');
  onCell.classList.add('networks-cell-switch');
  const sw = document.createElement('label');
  sw.className = 'admin-switch';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = row.enabled !== false;
  cb.addEventListener('change', () => { row.enabled = cb.checked; });
  const slider = document.createElement('span');
  slider.className = 'admin-slider';
  sw.append(cb, slider);
  onCell.appendChild(sw);
  wrap.appendChild(onCell);

  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'memory-toolbar-btn networks-remove';
  del.textContent = 'Remove';
  del.title = 'Remove this network';
  del.addEventListener('click', () => {
    rows.splice(i, 1);
    redraw();
  });
  wrap.appendChild(del);
  return wrap;
}

/** Draw `rows` into `host`. `opts.emptyText` is said when there are none;
 *  `opts.logins` (`[{id, label}]`) adds the login column. */
export function renderRows(host, rows, opts = {}) {
  if (!host) return;
  const redraw = () => renderRows(host, rows, opts);
  host.textContent = '';
  if (rows.length === 0) {
    // `B730`: the shared empty state; the *Add* button under the list is the
    // way in, so the state names it rather than drawing a second one.
    uiModule.renderEmptyState(host, {
      kind: 'empty', title: opts.emptyText || 'No networks declared.', icon: null,
      message: opts.emptyHint || '',
    });
    return;
  }
  rows.forEach((row, i) => host.appendChild(_rowEl(rows, row, i, opts, redraw)));
}

/** Every problem, one line each — a form that reports one typo per round trip
 *  is a form people give up on (`validate_networks`). */
export function showProblems(box, problems) {
  if (!box) return;
  box.textContent = '';
  if (!problems || problems.length === 0) {
    box.hidden = true;
    return;
  }
  for (const p of problems) {
    const line = document.createElement('div');
    line.className = 'networks-problem';
    line.textContent = p;
    box.appendChild(line);
  }
  box.hidden = false;
}
