// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1258`. How the LLM is served — the instance's part of it, in one editor
// both windows mount: Settings → Forge (its home) and the Forge's own Settings
// tab. One module, so there is one way to set it (`Law 7`).
//
// The Hugging Face token has its own route, `GET`/`PUT /api/cookbook/hf-token`
// (the operator's, `require_operator`). It used to ride the Forge's whole-state
// save (`POST /api/cookbook/state`) from the browser's `_envState`, so a Forge
// open in another tab could write it back, and a person had to be in the Forge
// to set it. The route stores it encrypted where it always was and answers
// only whether one is stored and its first and last four characters — the
// token itself never comes back to a browser.

const ROUTE = '/api/cookbook/hf-token';
const CHANGED = 'pantheon:hf-token-changed';

/** What the stored token means, in a person's words. */
export function describeHfToken(state) {
  if (!state) return 'Pantheon could not say whether a token is stored.';
  if (state.configured) {
    return `Stored (${state.masked || 'set'}). Downloads of gated and private models use it.`;
  }
  if (state.from_environment) {
    return 'None stored here: the HF_TOKEN environment variable is used.';
  }
  return 'None stored. Public models download without one; a gated or private model needs one.';
}

export async function readHfToken() {
  try {
    const res = await fetch(ROUTE, { credentials: 'same-origin' });
    return res.ok ? await res.json() : null;
  } catch (_) {
    return null;
  }
}

/** `{ok, state}` or `{ok: false, error}` — the server's sentence when it gave one. */
export async function saveHfToken(token) {
  let res;
  try {
    res = await fetch(ROUTE, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: String(token || '') }),
    });
  } catch (_) {
    return { ok: false, error: "Pantheon's server did not answer. Nothing was changed." };
  }
  let body = {};
  try { body = await res.json(); } catch (_) { /* keep the status */ }
  if (!res.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : '';
    return { ok: false, error: detail || `Not saved (HTTP ${res.status}). Nothing was changed.` };
  }
  return { ok: true, state: body };
}

function _node(tag, attrs = {}, text = '') {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'className') n.className = v;
    else n.setAttribute(k, v);
  }
  if (text) n.textContent = text;
  return n;
}

/**
 * Draw the token editor into `host`. `inputId` names the field so its label
 * can point at it; each window passes its own. Answers `{ refresh }`.
 */
export function mountHfToken(host, { inputId = 'hf-token-input' } = {}) {
  if (!host) return { refresh: async () => null };
  while (host.firstChild) host.removeChild(host.firstChild);

  const row = _node('div', { className: 'settings-row' });
  const label = _node('label', { className: 'settings-label', for: inputId }, 'Hugging Face token');
  const input = _node('input', {
    type: 'password', id: inputId, className: 'settings-input', autocomplete: 'off',
    spellcheck: 'false', placeholder: 'hf_…',
  });
  const save = _node('button', { type: 'button', className: 'admin-btn-sm' }, 'Save');
  const remove = _node('button', { type: 'button', className: 'admin-btn-sm' }, 'Remove');
  remove.hidden = true;
  row.append(label, input, save, remove);
  const said = _node('div', { className: 'admin-toggle-sub', role: 'status', 'aria-live': 'polite' });
  host.append(row, said);

  let state = null;
  function draw(next, note = '', error = false) {
    state = next;
    remove.hidden = !(state && state.configured);
    input.placeholder = state && state.configured
      ? `Stored (${state.masked || 'set'}) — type a new one to replace it`
      : 'hf_…';
    said.textContent = note ? `${note} ${describeHfToken(state)}` : describeHfToken(state);
    said.style.color = error ? 'var(--red)' : '';
  }

  async function put(token, done) {
    save.disabled = true;
    remove.disabled = true;
    const out = await saveHfToken(token);
    save.disabled = false;
    remove.disabled = false;
    if (!out.ok) {
      said.textContent = out.error;
      said.style.color = 'var(--red)';
      return;
    }
    input.value = '';
    draw(out.state, done);
    try { document.dispatchEvent(new CustomEvent(CHANGED, { detail: out.state })); } catch (_) {}
  }

  save.addEventListener('click', () => {
    const token = input.value.trim();
    if (!token) {
      said.textContent = 'Type a token to save it, or Remove to clear the stored one.';
      said.style.color = 'var(--red)';
      return;
    }
    put(token, 'Saved.');
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); save.click(); }
  });
  remove.addEventListener('click', () => put('', 'Removed.'));
  // The other window's copy saved: draw what it kept.
  document.addEventListener(CHANGED, (e) => { if (e.detail && e.detail !== state) draw(e.detail); });

  async function refresh() {
    const next = await readHfToken();
    draw(next);
    return next;
  }
  refresh();
  return { refresh };
}

export default { mountHfToken, readHfToken, saveHfToken, describeHfToken };
