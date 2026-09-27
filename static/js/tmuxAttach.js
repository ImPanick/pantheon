// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B909` — "Open this session in a terminal".
//
// The command that attaches to a tmux session is not built here. Where it has
// to be typed, and as whom, depends on two facts only the server has: whether
// Pantheon runs in a container (then the session is inside it, under the app's
// uid, and root's `tmux attach` finds nothing) and that uid. So the server
// builds it once (`src/tmux_attach.py`, `GET /api/shell/tmux-attach`) and this
// module asks for it and lays out the answer.
//
// Every string goes in through `textContent`. The server quotes the session
// name for a shell; it is still a name somebody chose — an adopted session is
// whatever its launcher called it — and it is on its way into the page.
//
// Two callers are meant to share this: the Forge's task menu
// (`cookbookRunning.js`), and `P4-15`'s attach affordance for the agent's own
// shell once `B908` gives that shell a session. Neither builds a command.

import uiModule from './ui.js';

/**
 * Ask the server how to attach to `session` (on `host`, for a remote task).
 *
 * Returns a handle at once — `{ value, error, ready }` — so a click that comes
 * after the answer can copy synchronously, inside its own gesture (`B59`: an
 * `await` before the copy ends the gesture). `ready` never rejects; a failure
 * lands in `error`.
 */
export function prefetchTmuxAttach(session, { host = '' } = {}) {
  const handle = { value: null, error: null, ready: null };
  const params = new URLSearchParams();
  params.set('session', String(session ?? ''));
  if (host) params.set('host', String(host));
  handle.ready = fetch(`/api/shell/tmux-attach?${params.toString()}`, { credentials: 'same-origin' })
    .then(async (res) => {
      let body = null;
      try { body = await res.json(); } catch (_) { /* not JSON: reported below by status */ }
      if (!res.ok || !body || typeof body.command !== 'string') {
        throw new Error((body && typeof body.detail === 'string' && body.detail) || `the server answered ${res.status}`);
      }
      return body;
    })
    .then(
      (value) => { handle.value = value; return value; },
      (err) => { handle.error = err instanceof Error ? err : new Error(String(err)); return null; },
    );
  return handle;
}

/**
 * Copy the command the server put first. Call it straight from the click
 * handler: it copies only if the answer is already here, and reports whether
 * it did, rather than waiting and copying outside the gesture.
 */
export function copyTmuxAttach(handle) {
  const command = handle && handle.value && handle.value.command;
  if (typeof command !== 'string' || !command) return false;
  uiModule.copyToClipboard(command);
  return true;
}

function _line(className, text) {
  const node = document.createElement('div');
  node.className = className;
  node.textContent = text;
  return node;
}

function _commandRow(command) {
  const row = document.createElement('div');
  row.className = 'tmux-attach-row';
  const code = document.createElement('code');
  code.className = 'tmux-attach-cmd';
  code.textContent = command;
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'tmux-attach-copy';
  copy.textContent = 'Copy';
  copy.addEventListener('click', (e) => {
    e.stopPropagation();
    uiModule.copyToClipboard(command);
  });
  row.appendChild(code);
  row.appendChild(copy);
  return row;
}

function _fill(body, box, handle) {
  body.replaceChildren();
  const value = handle.value;
  if (!value) {
    const why = (handle.error && handle.error.message) || 'no answer';
    body.appendChild(_line('tmux-attach-note tmux-attach-error',
      `Could not get the command from the server (${why}). Try again in a moment.`));
    return;
  }
  box.dataset.where = String(value.where || '');
  if (value.note) body.appendChild(_line('tmux-attach-note', value.note));
  body.appendChild(_commandRow(value.command));
  const other = value.alternative;
  if (other && typeof other.command === 'string' && other.command) {
    if (other.note) body.appendChild(_line('tmux-attach-note', other.note));
    body.appendChild(_commandRow(other.command));
  }
  if (value.detach) body.appendChild(_line('tmux-attach-note', value.detach));
}

/**
 * The panel: what to run, where, and how to leave without stopping it. Drawn
 * at once — with the answer if it is here, or saying it is on its way and
 * filling in when it lands. The caller decides where it goes.
 */
export function renderTmuxAttach(handle) {
  const box = document.createElement('div');
  box.className = 'tmux-attach';
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Open this session in a terminal');

  const head = document.createElement('div');
  head.className = 'tmux-attach-head';
  const title = document.createElement('span');
  title.textContent = 'Open this session in a terminal';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'tmux-attach-close';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '×';
  close.addEventListener('click', (e) => {
    e.stopPropagation();
    box.remove();
  });
  head.appendChild(title);
  head.appendChild(close);
  box.appendChild(head);

  const body = document.createElement('div');
  body.className = 'tmux-attach-body';
  body.setAttribute('aria-live', 'polite');
  box.appendChild(body);

  if (handle.value || handle.error) {
    _fill(body, box, handle);
  } else {
    body.appendChild(_line('tmux-attach-note', 'Asking the server for the command…'));
    handle.ready.then(() => _fill(body, box, handle));
  }
  return box;
}
