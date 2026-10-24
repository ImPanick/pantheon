// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P25-02`. Settings → Git: who a person's commits say they are, and a token
// per host for the pushes, pulls and clones the agent makes as them.
//
// Everything is the person's own and drawn from `GET /api/git`, which never
// carries a token — only the host, the user name and since when. A token is
// typed into a password field, sent once with `PUT /api/git`, and the field is
// emptied whatever the answer: nothing here keeps it. Refusals are the
// server's sentences (`routes/git_routes.py`).

const $ = (id) => document.getElementById(id);
let _wired = false;

function _say(text, { error = false } = {}) {
  const out = $('git-settings-result');
  if (!out) return;
  out.textContent = text || '';
  out.hidden = !text;
  out.classList.toggle('git-settings-error', !!error);
}

async function _call(method, body) {
  let res;
  try {
    res = await fetch('/api/git', {
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
  if (!res.ok) return { ok: false, sentence: (data && data.detail) || 'That was not saved.' };
  return { ok: true, data };
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/** Draw what the server holds. */
export function draw(data) {
  const ident = (data && data.identity) || null;
  if ($('git-identity-name')) $('git-identity-name').value = ident ? ident.name : '';
  if ($('git-identity-email')) $('git-identity-email').value = ident ? ident.email : '';
  const known = $('git-known-hosts');
  if (known) {
    known.textContent = '';
    ((data && data.known_hosts) || []).forEach((h) => {
      const o = document.createElement('option');
      o.value = h.host;
      o.label = h.label;
      known.appendChild(o);
    });
  }
  const list = $('git-hosts-list');
  if (!list) return;
  list.textContent = '';
  const hosts = (data && data.hosts) || [];
  if (!hosts.length) {
    list.appendChild(_el('p', 'git-hosts-empty',
      'No tokens yet. Pulls and clones of public repositories work without one; a push needs one.'));
    return;
  }
  hosts.forEach((h) => {
    const row = _el('div', 'git-host-row');
    row.dataset.host = h.host;
    row.appendChild(_el('span', 'git-host-name', h.host));
    row.appendChild(_el('span', 'git-host-user', `as ${h.username}`));
    row.appendChild(_el('span', 'git-host-since', h.since ? `set ${String(h.since).slice(0, 10)}` : 'set'));
    const replace = _el('button', 'memory-toolbar-btn git-host-replace', 'Replace');
    replace.type = 'button';
    replace.addEventListener('click', () => {
      if ($('git-host-name')) $('git-host-name').value = h.host;
      if ($('git-host-user')) $('git-host-user').value = h.username;
      if ($('git-host-token')) $('git-host-token').focus();
      _say(`Paste the new token for ${h.host}, then Add.`);
    });
    const forget = _el('button', 'memory-toolbar-btn git-host-forget', 'Forget');
    forget.type = 'button';
    forget.addEventListener('click', async () => {
      const r = await _call('PUT', { hosts: { [h.host]: null } });
      if (!r.ok) { _say(r.sentence, { error: true }); return; }
      draw(r.data);
      _say(`Forgot the token for ${h.host}.`);
    });
    row.appendChild(replace);
    row.appendChild(forget);
    list.appendChild(row);
  });
}

async function _saveIdentity() {
  const r = await _call('PUT', { identity: { name: $('git-identity-name').value, email: $('git-identity-email').value } });
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
  _say('Saved. Your next commit carries this name and email.');
}

async function _addHost() {
  const host = ($('git-host-name').value || '').trim();
  const token = $('git-host-token').value;
  const username = ($('git-host-user').value || '').trim();
  $('git-host-token').value = '';   // never kept here, whatever the answer
  const r = await _call('PUT', { hosts: { [host || '']: { username, token } } });
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
  $('git-host-name').value = '';
  $('git-host-user').value = '';
  _say(`Kept. The agent's pushes and pulls to ${host.replace(/^https?:\/\//, '').split('/')[0]} use it, as you.`);
}

export async function open() {
  if (!_wired) {
    _wired = true;
    const save = $('git-identity-save');
    if (save) save.addEventListener('click', _saveIdentity);
    const add = $('git-host-add');
    if (add) add.addEventListener('click', _addHost);
  }
  _say('');
  const r = await _call('GET');
  if (!r.ok) { _say(r.sentence, { error: true }); return; }
  draw(r.data);
}

export default { open, draw };
