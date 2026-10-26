// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/githubToken.js — `B927`. The skill importer's GitHub token, set in
// the MCP & Integrations room beside the other integration secrets.
//
// Unauthenticated api.github.com allows 60 lookups an hour, and a skill import
// lists folders through it; with a token it is 5,000. Until this panel the only
// ways to set one were `data/settings.json` and `PANTHEON_GITHUB_TOKEN`, and
// the import's own sentence told a person to set an environment variable.
//
// Write-only, the way the network agent's token is (`networks.js:saveAgent`):
// the field is never filled from the server, which answers only *whether* a
// token is set and where it came from (`GET /api/skills/github-token`). An empty
// box means "leave it alone"; Remove is the one way to clear it. Admin-only: the
// card stays hidden unless that route answers, and it answers admins only.

const $ = (id) => document.getElementById(id);

function _say(text, ok) {
  const out = $('github-token-state');
  if (!out) return;
  out.textContent = text;
  out.classList.toggle('is-ok', !!ok);
}

function _describe(state) {
  if (!state || !state.configured) {
    return `No token: imports get GitHub's ${state?.rate_without ?? 60} lookups an hour.`;
  }
  const rate = Number(state.rate_with ?? 5000).toLocaleString('en-US');
  if (state.source === 'environment') {
    return `A token is set by ${state.env_var || 'PANTHEON_GITHUB_TOKEN'} on the server: imports get ${rate} lookups an hour. One saved here takes its place.`;
  }
  return `A token is saved: imports get ${rate} lookups an hour.`;
}

/** Ask the server and draw the card. Resolves to the state, or null when the
 *  viewer is not an admin (the card stays hidden). */
export async function refresh() {
  const card = $('github-token-card');
  if (!card) return null;
  let res;
  try {
    res = await fetch('/api/skills/github-token', { credentials: 'same-origin' });
  } catch (_) {
    card.hidden = true;   // offline: nothing to say that the room does not
    return null;
  }
  if (!res.ok) { card.hidden = true; return null; }
  const state = await res.json().catch(() => null);
  card.hidden = false;
  const rateLine = $('github-token-rate');
  if (rateLine && state) {
    rateLine.textContent = `Skill imports ask GitHub for each folder they list. Without a token GitHub allows ${state.rate_without} lookups an hour; with one, ${Number(state.rate_with).toLocaleString('en-US')}. A token with no scopes (public read) is enough.`;
  }
  const remove = $('github-token-remove');
  if (remove) remove.hidden = !(state && state.configured && state.source === 'settings');
  _say(_describe(state), !!(state && state.configured));
  return state;
}

async function _write(value) {
  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ github_token: value }),
  });
  if (!res.ok) {
    let detail = `Not saved (${res.status}).`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = String(err.detail);
    } catch (_) { /* a non-JSON refusal still has its status */ }
    _say(detail, false);
    return false;
  }
  return true;
}

export async function save() {
  const input = $('github-token-input');
  const value = (input?.value || '').trim();
  if (!value) {
    _say('Paste a token first. An empty box leaves the saved one alone.', false);
    return false;
  }
  if (!(await _write(value))) return false;
  if (input) input.value = '';   // never kept on the page once saved
  await refresh();
  return true;
}

export async function remove() {
  if (!(await _write(''))) return false;
  await refresh();
  return true;
}

let _wired = false;

/** Called by the MCP & Integrations room when it is first shown. */
export function mount() {
  if (!_wired) {
    _wired = true;
    $('github-token-save')?.addEventListener('click', () => { save(); });
    $('github-token-remove')?.addEventListener('click', () => { remove(); });
    $('github-token-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); save(); }
    });
  }
  return refresh();
}

/** Bring the card into view and put the cursor in its box — the door the
 *  Skills room's import line opens after a rate limit. */
export function focusCard() {
  const card = $('github-token-card');
  if (!card || card.hidden) return false;
  card.scrollIntoView?.({ block: 'nearest' });
  $('github-token-input')?.focus();
  return true;
}
