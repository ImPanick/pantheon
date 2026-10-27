// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P27-03`. Settings → Vault: each person's own logins, keys and secret notes,
// which the agent uses by name and never sees (`src/vault.py`).
//
// Drawn from `GET /api/vault/mine`, which never carries a password or a
// secret — only that one is set. A secret is typed into a password field, sent
// once, and the field is emptied whatever the answer. *Reveal* asks for the
// person's Pantheon password again and shows the values in the row for thirty
// seconds; nothing here keeps them after. Refusals are the server's sentences
// (`routes/vault_mine_routes.py`).

const $ = (id) => document.getElementById(id);
const BASE = '/api/vault/mine';
const REVEAL_MS = 30_000;
const USE_WORDS = { ask: 'Asks each time', chat: 'Asks once per chat', allowed: 'Agents may use it' };
let _wired = false;
let _editing = null;
let _agentNames = {};   // `P27-09`: id → name, for the grants list

function _say(text, { error = false } = {}) {
  const out = $('vault-settings-result');
  if (!out) return;
  out.textContent = text || '';
  out.hidden = !text;
  out.classList.toggle('git-settings-error', !!error);
}

// Every path is spelled whole where it is called, so `check-unreachable.py`
// sees each route's caller (`P27-10`: four of these read as callerless while
// they were `BASE` plus a tail).
async function _call(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    return { ok: false, sentence: "Pantheon's server did not answer. Nothing was changed." };
  }
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) return { ok: false, sentence: (data && data.detail) || 'That was not done.' };
  return { ok: true, data };
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _btn(label, cls, onClick) {
  const b = _el('button', `memory-toolbar-btn ${cls || ''}`.trim(), label);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

/** A password nobody has to think of: 24 characters from a 64-symbol set. */
export function generatePassword(length = 24) {
  const set = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.!@#%+=';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => set[b % set.length]).join('');
}

function _drawLock(data) {
  const state = $('vault-lock-state');
  if (state) {
    state.textContent = data.locked
      ? 'Locked. The agent cannot use anything in it until you unlock it.'
      : (data.idle_minutes ? `Unlocked. It locks ${data.idle_minutes} minutes after you last used it.`
        : 'Unlocked, and stays so. Everything in it is encrypted at rest with your own key.');
  }
  const idle = $('vault-idle');
  if (idle) idle.value = String(data.idle_minutes || 0);
  const unlockRow = $('vault-unlock-row');
  if (unlockRow) unlockRow.hidden = !data.locked;
  const lockNow = $('vault-lock-now');
  if (lockNow) lockNow.hidden = !!data.locked || !data.idle_minutes;
}

let _services = [];   // `P27-05`: the services Pantheon can make an agent account on

/** `P27-05`. From an admin login: make an account for the agent on the
 *  service, with the role picked here. The press of *Make it* is the yes. */
function _agentAccountInto(row, item) {
  if (row.querySelector('.vault-agent-account')) return;
  const box = _el('div', 'vault-agent-account git-settings-row');
  const svc = document.createElement('select');
  svc.setAttribute('aria-label', 'Service');
  _services.forEach((s) => { const o = document.createElement('option'); o.value = s.id; o.textContent = s.label; svc.appendChild(o); });
  const role = document.createElement('select');
  role.setAttribute('aria-label', 'Role');
  const fillRoles = () => {
    role.textContent = '';
    const s = _services.find((x) => x.id === svc.value);
    (s ? s.roles : []).forEach((r) => { const o = document.createElement('option'); o.value = r; o.textContent = r; role.appendChild(o); });
  };
  svc.addEventListener('change', fillRoles);
  fillRoles();
  const user = document.createElement('input');
  user.type = 'text';
  user.value = 'pantheon-agent';
  user.spellcheck = false;
  user.setAttribute('aria-label', 'User name for the agent');
  const label = (t, el) => { const l = _el('label', 'git-settings-field'); l.appendChild(_el('span', '', t)); l.appendChild(el); return l; };
  box.appendChild(label('Service', svc));
  box.appendChild(label('Role', role));
  box.appendChild(label('Its user name', user));
  const go = _btn('Make it', 'vault-agent-account-go', async () => {
    go.disabled = true;
    _say(`Making ${user.value} on ${item.addresses[0] || 'the service'}…`);
    const r = await _call('POST', `/api/vault/mine/items/${encodeURIComponent(item.id)}/agent-account`,
      { template: svc.value, role: role.value, username: user.value });
    go.disabled = false;
    if (!r.ok) { _say(r.sentence, { error: true }); return; }
    _say(`Made “${r.data.label}” with the role ${role.value}. Its password is in your vault; nobody typed it.`);
    box.remove();
    await _refresh();
  });
  box.appendChild(go);
  box.appendChild(_btn('Cancel', '', () => box.remove()));
  box.appendChild(_el('p', 'admin-toggle-sub vault-agent-account-note',
    `Pantheon signs in to the service as “${item.label}”, creates the user with this role, and keeps its new password here. A service not listed: make the account in its own admin page and add it as a login.`));
  row.appendChild(box);
  svc.focus();
}

/** `P27-04`. Test a login from the workstation: does each name resolve on
 *  your network, does it answer, which certificate it shows — and from the
 *  answer, map a name or trust a certificate (`D-2026-10-24-03`). */
async function _testInto(row, item) {
  row.querySelector('.vault-test')?.remove();
  const box = _el('div', 'vault-test');
  box.appendChild(_el('p', 'admin-toggle-sub', 'Testing from your workstation…'));
  row.appendChild(box);
  const r = await _call('POST', `/api/vault/mine/items/${encodeURIComponent(item.id)}/test`);
  box.textContent = '';
  if (!r.ok) { box.appendChild(_el('p', 'admin-toggle-sub git-settings-error', r.sentence)); return; }
  (r.data.results || []).forEach((res) => {
    const host = res.host;
    const part = _el('div', 'vault-test-result');
    part.appendChild(_el('div', 'vault-test-origin', res.origin));
    const lines = [];
    if (res.mapped_to) lines.push(`${host} is mapped to ${res.mapped_to} for you.`);
    else if ((res.dns || []).length) lines.push(`${host} resolves on your network (${res.dns.join(', ')}); nothing needs mapping.`);
    else lines.push(`${host} does not resolve on your network.`);
    if (res.http) lines.push(`It answered HTTP ${res.http}.`);
    else if (res.http_error || res.tls_error) lines.push(`It did not answer: ${res.http_error || res.tls_error}`);
    lines.forEach((t) => part.appendChild(_el('p', 'vault-test-line', t)));
    if (!(res.dns || []).length || res.mapped_to) {
      const map = _el('div', 'git-settings-row vault-test-map');
      const ip = document.createElement('input');
      ip.type = 'text';
      ip.value = res.mapped_to || '';
      ip.placeholder = '10.0.0.5';
      ip.setAttribute('aria-label', `The address ${host} is at`);
      const field = _el('label', 'git-settings-field');
      field.appendChild(_el('span', '', `Map ${host} to`));
      field.appendChild(ip);
      map.appendChild(field);
      map.appendChild(_btn(res.mapped_to ? 'Change' : 'Map it', 'vault-map-btn', async () => {
        const m = { ...(item.mapped || {}), [host]: ip.value.trim() };
        const u = await _call('PUT', `/api/vault/mine/items/${encodeURIComponent(item.id)}`, { mapped: m });
        if (!u.ok) { _say(u.sentence, { error: true }); return; }
        item.mapped = u.data.mapped;
        _say(`${host} now reaches ${ip.value.trim()} for you — in your browser and your commands. Testing again…`);
        await _testInto(row, item);
      }));
      if (res.mapped_to) {
        map.appendChild(_btn('Unmap', 'vault-unmap-btn', async () => {
          const m = { ...(item.mapped || {}) };
          delete m[host];
          const u = await _call('PUT', `/api/vault/mine/items/${encodeURIComponent(item.id)}`, { mapped: m });
          if (!u.ok) { _say(u.sentence, { error: true }); return; }
          item.mapped = u.data.mapped;
          await _testInto(row, item);
        }));
      }
      part.appendChild(map);
    }
    const c = res.cert;
    if (c) {
      const facts = [`Certificate ${c.sha256}`, c.subject || '', c.self_signed ? 'signed by itself' : '',
        c.pinned ? 'trusted: you pinned it' : (c.trusted ? 'trusted' : 'not trusted')].filter(Boolean);
      part.appendChild(_el('p', 'vault-test-cert', facts.join(' · ')));
      if (c.changed) {
        part.appendChild(_el('p', 'vault-test-line git-settings-error',
          'This is not the certificate you pinned. It is refused until you look and trust it again.'));
      }
      if (!c.trusted && !c.pinned) {
        part.appendChild(_btn('Trust this certificate', 'vault-pin-btn', async () => {
          const u = await _call('POST', `/api/vault/mine/items/${encodeURIComponent(item.id)}/pin`, { origin: res.origin, sha256: c.sha256 });
          if (!u.ok) { _say(u.sentence, { error: true }); return; }
          _say(`Trusted for ${res.origin} only — this exact certificate, in your browser and your commands.`);
          await _testInto(row, item);
        }));
      } else if (c.pinned) {
        part.appendChild(_btn('Forget the pin', 'vault-unpin-btn', async () => {
          const u = await _call('POST', `/api/vault/mine/items/${encodeURIComponent(item.id)}/pin`, { origin: res.origin, remove: true });
          if (!u.ok) { _say(u.sentence, { error: true }); return; }
          await _testInto(row, item);
        }));
      }
    }
    box.appendChild(part);
  });
  box.appendChild(_btn('Close', '', () => box.remove()));
}

function _revealInto(row, item) {
  if (row.querySelector('.vault-reveal')) return;
  const box = _el('div', 'vault-reveal git-settings-row');
  const pw = document.createElement('input');
  pw.type = 'password';
  pw.autocomplete = 'current-password';
  pw.placeholder = 'Your Pantheon password';
  pw.setAttribute('aria-label', 'Your Pantheon password');
  const go = _btn('Show', 'vault-reveal-go', async () => {
    const password = pw.value;
    pw.value = '';
    const r = await _call('POST', `/api/vault/mine/items/${encodeURIComponent(item.id)}/reveal`, { password });
    if (!r.ok) { _say(r.sentence, { error: true }); return; }
    box.textContent = '';
    const shown = _el('dl', 'vault-shown');
    [['User name', r.data.username], ['Secret', r.data.secret], ['One-time-code secret', r.data.totp],
      ['Notes', r.data.notes]].forEach(([k, v]) => {
      if (!v) return;
      shown.appendChild(_el('dt', '', k));
      shown.appendChild(_el('dd', 'vault-shown-value', v));
    });
    box.appendChild(shown);
    _say(`Shown for ${REVEAL_MS / 1000} seconds.`);
    setTimeout(() => { box.remove(); }, REVEAL_MS);
  });
  box.appendChild(pw);
  box.appendChild(go);
  box.appendChild(_btn('Cancel', '', () => box.remove()));
  row.appendChild(box);
  pw.focus();
}

// ── `P27-10`: bring logins in, take them out ───────────────────────────────

function _sayTransfer(text, { error = false } = {}) {
  const out = $('vault-transfer-result');
  if (!out) return;
  out.textContent = text || '';
  out.hidden = !text;
  out.classList.toggle('git-settings-error', !!error);
}

/** What an import did, in sentences — names, never values. */
export function transferReport(r) {
  const n = (r.imported || []).length;
  const parts = [n ? `Brought in ${n} item${n === 1 ? '' : 's'}.` : 'Nothing new was brought in.'];
  const already = (r.already || []).length;
  if (already) parts.push(`${already} ${already === 1 ? 'was' : 'were'} already in your vault.`);
  const left = r.left_out || [];
  if (left.length) {
    parts.push(`Left out: ${left.slice(0, 8).map((x) => `“${x.name}” (${x.why})`).join('; ')}${left.length > 8 ? `; and ${left.length - 8} more` : ''}.`);
  }
  const said = r.said || [];
  if (said.length) {
    parts.push(said.slice(0, 8).map((x) => `“${x.name}”: ${x.said}.`).join(' ') + (said.length > 8 ? ` And ${said.length - 8} more notes.` : ''));
  }
  if (n) parts.push('Each asks you before an agent signs in with it; change that on its row.');
  return parts.join(' ');
}

async function _import() {
  const input = $('vault-import-file');
  const file = input && input.files && input.files[0];
  if (!file) { _sayTransfer('Pick a file first: a Bitwarden or Vaultwarden export, or a Pantheon export.', { error: true }); return; }
  let text;
  try { text = await file.text(); } catch (_) { _sayTransfer('That file could not be read.', { error: true }); return; }
  const pass = $('vault-import-passphrase');
  const passphrase = pass ? pass.value : '';
  if (pass) pass.value = '';
  _sayTransfer(`Bringing in ${file.name}…`);
  const r = await _call('POST', '/api/vault/mine/import', passphrase ? { text, passphrase } : { text });
  if (!r.ok) { _sayTransfer(r.sentence, { error: true }); return; }
  input.value = '';
  _sayTransfer(transferReport(r.data));
  await _refresh();
}

async function _importServer() {
  _sayTransfer("Reading the server's Bitwarden…");
  const r = await _call('POST', '/api/vault/mine/import', { source: 'server-bitwarden' });
  if (!r.ok) { _sayTransfer(r.sentence, { error: true }); return; }
  _sayTransfer(transferReport(r.data));
  await _refresh();
}

async function _export() {
  const a = $('vault-export-passphrase');
  const b = $('vault-export-passphrase-again');
  const pw = $('vault-export-password');
  const passphrase = a.value;
  const again = b.value;
  const password = pw.value;
  pw.value = '';
  if (passphrase !== again) { _sayTransfer('The two passphrases are not the same. Nothing was exported.', { error: true }); return; }
  _sayTransfer('Sealing your vault…');
  const r = await _call('POST', '/api/vault/mine/export', { passphrase, password });
  a.value = '';
  b.value = '';
  if (!r.ok) { _sayTransfer(r.sentence, { error: true }); return; }
  const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `pantheon-vault-${r.data.made}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
  _sayTransfer(`Exported ${r.data.items} item${r.data.items === 1 ? '' : 's'}, sealed with your passphrase. Keep the passphrase somewhere other than the file.`);
}

/** Draw what the server holds. */
export function draw(data) {
  if (data && Array.isArray(data.services)) _services = data.services;
  const fromServer = $('vault-import-server');
  if (fromServer) fromServer.hidden = !(data && data.server_bitwarden);
  _drawLock(data || {});
  const list = $('vault-items-list');
  if (!list) return;
  list.textContent = '';
  const items = (data && data.items) || [];
  if (!items.length) {
    list.appendChild(_el('p', 'git-hosts-empty',
      'Nothing yet. Add a login and the agent can sign in with it by name — in its browser or a command — without ever seeing the password.'));
    return;
  }
  items.forEach((it) => {
    const row = _el('div', 'git-host-row vault-item');
    row.dataset.id = it.id;
    row.appendChild(_el('span', 'git-host-name', it.label));
    row.appendChild(_el('span', 'git-host-user', [
      it.kind !== 'login' ? it.kind : '',
      it.username ? `as ${it.username}` : '',
      (it.addresses || []).join(', '),
    ].filter(Boolean).join(' · ')));
    const facts = [USE_WORDS[it.use] || USE_WORDS.ask];
    if (it.agent_account) facts.push('agent account');
    if ((it.agents || []).length) facts.push(`only ${it.agents.map((a) => _agentNames[a] || a).join(', ')}`);
    Object.entries(it.mapped || {}).forEach(([h, ip]) => facts.push(`${h} → ${ip}`));
    if (Object.keys(it.pins || {}).length) facts.push('certificate pinned');
    if (it.has_totp) facts.push('one-time codes');
    if (it.last_used_at) facts.push(`used ${String(it.last_used_at).slice(0, 10)}${it.last_used_by ? ` by ${it.last_used_by}` : ''}`);
    row.appendChild(_el('span', 'git-host-since', facts.join(' · ')));
    row.appendChild(_btn('Reveal', 'vault-reveal-btn', () => _revealInto(row, it)));
    if (it.kind === 'login' && (it.addresses || []).length) {
      row.appendChild(_btn('Test', 'vault-test-btn', () => _testInto(row, it)));
    }
    if (it.kind === 'login' && !it.agent_account && _services.length) {
      row.appendChild(_btn('Agent account…', 'vault-agent-account-btn', () => _agentAccountInto(row, it)));
    }
    row.appendChild(_btn('Edit', 'vault-edit-btn', () => _startEdit(it)));
    row.appendChild(_btn('Remove', 'vault-remove-btn', async () => {
      const r = await _call('DELETE', `/api/vault/mine/items/${encodeURIComponent(it.id)}`);
      if (!r.ok) { _say(r.sentence, { error: true }); return; }
      _say(`Removed “${it.label}”.`);
      await _refresh();
    }));
    list.appendChild(row);
  });
}

function _startEdit(it) {
  _editing = it.id;
  $('vault-kind').value = it.kind;
  $('vault-label').value = it.label;
  $('vault-addresses').value = (it.addresses || []).join(' ');
  $('vault-username').value = it.username || '';
  $('vault-secret').value = '';
  $('vault-secret').placeholder = it.has_secret ? 'Leave empty to keep it' : 'Password or key';
  $('vault-totp').value = '';
  $('vault-totp').placeholder = it.has_totp ? 'Leave empty to keep it' : 'Optional';
  $('vault-use').value = it.use || 'ask';
  $('vault-agent-account').checked = !!it.agent_account;
  _pickAgents(it.agents || []);
  $('vault-save').textContent = 'Save changes';
  $('vault-cancel-edit').hidden = false;
  $('vault-label').focus();
}

function _resetForm() {
  _editing = null;
  ['vault-label', 'vault-addresses', 'vault-username', 'vault-secret', 'vault-totp', 'vault-notes']
    .forEach((id) => { if ($(id)) $(id).value = ''; });
  if ($('vault-secret')) $('vault-secret').placeholder = 'Password or key';
  if ($('vault-totp')) $('vault-totp').placeholder = 'Optional';
  if ($('vault-agent-account')) $('vault-agent-account').checked = false;
  _pickAgents([]);
  if ($('vault-save')) $('vault-save').textContent = 'Add to vault';
  if ($('vault-cancel-edit')) $('vault-cancel-edit').hidden = true;
}

async function _save() {
  const body = {
    kind: $('vault-kind').value,
    label: $('vault-label').value,
    addresses: $('vault-addresses').value,
    username: $('vault-username').value,
    use: $('vault-use').value,
    agent_account: $('vault-agent-account').checked,
    agents: _pickedAgents(),
  };
  const secret = $('vault-secret').value;
  const totp = $('vault-totp').value;
  const notes = $('vault-notes').value;
  $('vault-secret').value = '';   // never kept here, whatever the answer
  $('vault-totp').value = '';
  if (!_editing || secret) body.secret = secret;
  if (!_editing || totp) body.totp = totp;
  if (!_editing || notes) body.notes = notes;
  const r = _editing
    ? await _call('PUT', `/api/vault/mine/items/${encodeURIComponent(_editing)}`, body)
    : await _call('POST', '/api/vault/mine/items', body);
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  _say(_editing ? `Saved “${r.data.label}”.`
    : `Kept “${r.data.label}”. Ask the agent to sign in with it by that name.`);
  _resetForm();
  await _refresh();
}

async function _lock(body) {
  const r = await _call('PUT', '/api/vault/mine/lock', body);
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
  _say(body.locked === true ? 'Locked.' : body.locked === false ? 'Unlocked.' : 'Saved.');
}

/** `P27-09`. The person's agents, to grant a login to some of them only. */
async function _loadAgents() {
  const sel = $('vault-agents');
  if (!sel || sel.dataset.loaded) return;
  let list = [];
  try {
    const res = await fetch('/api/agents', { credentials: 'same-origin' });
    if (res.ok) { const d = await res.json(); list = (d && d.agents) || []; }
  } catch (_) { list = []; }
  sel.textContent = '';
  const chat = document.createElement('option');
  chat.value = 'chat';
  chat.textContent = 'The chat itself (no agent)';
  sel.appendChild(chat);
  _agentNames = { chat: 'the chat' };
  list.forEach((a) => {
    if (!a || !a.id) return;
    const o = document.createElement('option');
    o.value = a.id;
    o.textContent = a.name || a.id;
    _agentNames[a.id] = a.name || a.id;
    sel.appendChild(o);
  });
  sel.dataset.loaded = '1';
}

function _pickedAgents() {
  const sel = $('vault-agents');
  return sel ? Array.from(sel.options).filter((o) => o.selected).map((o) => o.value) : [];
}

function _pickAgents(ids) {
  const sel = $('vault-agents');
  if (!sel) return;
  Array.from(sel.options).forEach((o) => { o.selected = ids.includes(o.value); });
}

async function _refresh() {
  const r = await _call('GET', BASE);
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
}

export async function open() {
  if (!_wired) {
    _wired = true;
    const on = (id, fn) => { const n = $(id); if (n) n.addEventListener('click', fn); };
    on('vault-save', _save);
    on('vault-cancel-edit', () => { _resetForm(); _say(''); });
    on('vault-generate', () => {
      const s = $('vault-secret');
      s.value = generatePassword();
      s.type = 'text';
      setTimeout(() => { s.type = 'password'; }, 8000);
      _say('A new password is in the field for eight seconds of view; set it on the service too.');
    });
    on('vault-import', _import);
    on('vault-import-server', _importServer);
    on('vault-export', _export);
    on('vault-lock-now', () => _lock({ locked: true }));
    on('vault-unlock', () => {
      const pw = $('vault-unlock-password');
      const password = pw.value;
      pw.value = '';
      _lock({ locked: false, password });
    });
    const idle = $('vault-idle');
    if (idle) idle.addEventListener('change', () => _lock({ idle_minutes: Number(idle.value) || 0 }));
  }
  _say('');
  _sayTransfer('');
  await _loadAgents();
  _resetForm();
  await _refresh();
}

export default { open, draw, generatePassword, transferReport };
