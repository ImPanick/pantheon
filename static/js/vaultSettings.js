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

function _say(text, { error = false } = {}) {
  const out = $('vault-settings-result');
  if (!out) return;
  out.textContent = text || '';
  out.hidden = !text;
  out.classList.toggle('git-settings-error', !!error);
}

async function _call(method, path, body) {
  let res;
  try {
    res = await fetch(BASE + (path || ''), {
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
    const r = await _call('POST', `/items/${encodeURIComponent(item.id)}/reveal`, { password });
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

/** Draw what the server holds. */
export function draw(data) {
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
    if (it.has_totp) facts.push('one-time codes');
    if (it.last_used_at) facts.push(`used ${String(it.last_used_at).slice(0, 10)}${it.last_used_by ? ` by ${it.last_used_by}` : ''}`);
    row.appendChild(_el('span', 'git-host-since', facts.join(' · ')));
    row.appendChild(_btn('Reveal', 'vault-reveal-btn', () => _revealInto(row, it)));
    row.appendChild(_btn('Edit', 'vault-edit-btn', () => _startEdit(it)));
    row.appendChild(_btn('Remove', 'vault-remove-btn', async () => {
      const r = await _call('DELETE', `/items/${encodeURIComponent(it.id)}`);
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
    ? await _call('PUT', `/items/${encodeURIComponent(_editing)}`, body)
    : await _call('POST', '/items', body);
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  _say(_editing ? `Saved “${r.data.label}”.`
    : `Kept “${r.data.label}”. Ask the agent to sign in with it by that name.`);
  _resetForm();
  await _refresh();
}

async function _lock(body) {
  const r = await _call('PUT', '/lock', body);
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
  _say(body.locked === true ? 'Locked.' : body.locked === false ? 'Unlocked.' : 'Saved.');
}

async function _refresh() {
  const r = await _call('GET');
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
  _resetForm();
  await _refresh();
}

export default { open, draw, generatePassword };
