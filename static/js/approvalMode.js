// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * This chat's approval mode — `D-2026-10-09-01` §2.
 *
 * Two settings, one chat: **Manual approve** (today's ladder, a stop condition
 * raises a card) and **Auto** (the step runs). The mode lives on the server, on
 * the chat's own row, so this module holds no state of its own beyond what it
 * last read — nothing in `localStorage`, deliberately. A mode cached in the
 * browser is a mode that survives into another chat and another device, which
 * is the one thing the ruling says it must never do.
 *
 * Two surfaces, one state:
 *
 *   `#approval-mode-btn`      the composer chip, beside Plan / Web / Shell.
 *                             `aria-pressed` is the mode; `.active` is the
 *                             on-state (`.tool-indicator`'s red). Hidden
 *                             entirely when the person may not use Auto.
 *   `#chat-auto-approve-badge`  the chat header, beside the chat's name.
 *                             Shown only while Auto is on.
 *
 * One API: `GET`/`POST /api/session/{sid}/approval-mode`.
 *
 * Turning it on is one deliberate act: `B1703` / `D-2026-10-30-01`, the
 * person accepts a warning that names the risk — what the agent reads can steer
 * what it does next — with *Proceed to auto-approve*, and the server records
 * who accepted it. The words are the server's (`AUTO_WARNING` in
 * `src/approval_mode.py`), read from `GET …/approval-mode` with their id and
 * the two controls' labels, and the id goes back with the write
 * (`accept_warning`): this module holds no copy of them, so the page cannot
 * show one warning while the server records another (`Law 7`, `Law 10`). Short
 * and plain, not a wall (Doc 2 § 5). Turning it off is a click, with no
 * question: putting a gate back is never the move that needs confirming.
 */

// `B1005`'s shape in the browser: every refusal the server can give is shown as
// the server's own sentence, because the server is the only thing that knows
// which of the four it was (`Law 10`, Doc 2 § 5 rule 7).
const MODE_MANUAL = 'manual';
const MODE_AUTO = 'auto';

let _state = { sid: null, mode: MODE_MANUAL, maySet: false, warning: null };
let _ui = null;
let _busy = false;

/** The modules this one needs, resolved late so a harness can supply them. */
function _deps() {
  return _ui || (typeof window !== 'undefined' ? window.uiModule : null);
}

/** `#approval-mode-btn` and `#chat-auto-approve-badge`, or nulls. */
function _nodes() {
  const doc = typeof document !== 'undefined' ? document : null;
  if (!doc) return { chip: null, badge: null };
  return {
    chip: doc.getElementById('approval-mode-btn'),
    badge: doc.getElementById('chat-auto-approve-badge'),
  };
}

/**
 * Draw both surfaces from one state. Called after every read and every write,
 * so the chip and the badge cannot disagree about whether this chat asks.
 */
export function render() {
  const { chip, badge } = _nodes();
  const auto = _state.mode === MODE_AUTO;
  if (chip) {
    // Hidden, not disabled: a control an admin has not granted is not a
    // control this person has (`Law 15` — no dead switch to discover).
    chip.style.display = _state.maySet ? '' : 'none';
    chip.classList.toggle('active', auto);
    chip.setAttribute('aria-pressed', auto ? 'true' : 'false');
    chip.title = auto
      ? 'Auto-approve is on for this chat — click to turn it off'
      : 'Auto-approve';
  }
  if (badge) {
    // The header badge says the state and nothing else; it is only ever there
    // when there is something to say.
    badge.hidden = !auto;
  }
}

/** This chat's mode, as this module last read it. */
export function currentMode() {
  return _state.mode;
}

export function isAuto() {
  return _state.mode === MODE_AUTO;
}

/**
 * Read the mode for one chat from the server and draw it.
 *
 * A chat with no id yet (the welcome screen, before the first message) has no
 * row to read, so it is Manual approve and the chip is drawn as the server's
 * default rather than left showing the previous chat's state — which is the
 * leak this function exists to prevent on every chat switch.
 */
export async function load(sessionId) {
  _state = { sid: sessionId || null, mode: MODE_MANUAL, maySet: _state.maySet, warning: null };
  if (!sessionId) {
    render();
    return _state;
  }
  try {
    const res = await fetch(
      `/api/session/${encodeURIComponent(sessionId)}/approval-mode`,
      { credentials: 'same-origin' },
    );
    if (res.ok) {
      const data = await res.json();
      // Guarded against a stale answer: the person may have switched chats
      // while this was in flight, and drawing the old chat's mode onto the new
      // one is exactly the cross-chat leak the ruling forbids.
      if (_state.sid === sessionId) {
        _state = {
          sid: sessionId,
          mode: data && data.auto ? MODE_AUTO : MODE_MANUAL,
          maySet: !!(data && data.may_set),
          warning: _warningOf(data),
        };
      }
    }
  } catch (_) {
    // An unreachable server is Manual approve: the safe reading of "I do not
    // know whether this chat asks" is that it does.
  }
  render();
  return _state;
}

/**
 * `B1703`. The warning a `GET` answered with — its words, its id and the two
 * controls' labels — or null when the answer carried none (an older server, a
 * stub): then Auto is not offered, because there is nothing to accept.
 */
function _warningOf(data) {
  const said = (key) => (data && typeof data[key] === 'string' && data[key]) || null;
  const text = said('warning');
  const id = said('warning_id');
  const proceed = said('proceed_label');
  const keep = said('keep_asking_label');
  return text && id && proceed && keep ? { text, id, proceed, keep } : null;
}

/** The warning for this chat, read again from the server when this module
 *  has none for it yet (a chip pressed before the read landed). */
async function _warningFor(sessionId) {
  if (_state.sid === sessionId && _state.warning) return _state.warning;
  try {
    const res = await fetch(
      `/api/session/${encodeURIComponent(sessionId)}/approval-mode`,
      { credentials: 'same-origin' },
    );
    if (!res.ok) return null;
    const warning = _warningOf(await res.json());
    if (_state.sid === sessionId) _state.warning = warning;
    return warning;
  } catch (_) {
    return null;
  }
}

/** POST the mode and draw the server's answer, or show why it refused.
 *  `accept` is the warning's id the person accepted — `B1703`: Auto is
 *  refused without it — and nothing for Manual, which never asks. */
async function _write(sessionId, mode, accept) {
  const ui = _deps();
  const body = accept ? { mode, accept_warning: accept } : { mode };
  const res = await fetch(
    `/api/session/${encodeURIComponent(sessionId)}/approval-mode`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    let sentence = 'That did not save. Try again.';
    try {
      const body = await res.json();
      if (body && body.detail) sentence = String(body.detail);
    } catch (_) { /* the default sentence stands */ }
    if (ui && ui.showToast) ui.showToast(sentence, 6000);
    return false;
  }
  const data = await res.json();
  _state = {
    sid: sessionId,
    mode: data && data.auto ? MODE_AUTO : MODE_MANUAL,
    maySet: _state.maySet,
    warning: _state.sid === sessionId ? _state.warning : null,
  };
  render();
  return true;
}

/**
 * The chip's click: turn Auto on (after its warning is accepted) or off (at
 * once).
 *
 * The server decides, every time. This asks first because the person is about
 * to take on a risk and should read what it is — and `B1703`, the server
 * refuses Auto without the id of the warning they accepted, so the dialog is
 * the only way on, not a courtesy in front of it (`P2-18`). With no dialog to
 * show, or no warning to show in it, nothing is sent: Auto is never turned on
 * without the person having read the server's words.
 */
export async function toggle(sessionId) {
  const sid = sessionId || _state.sid;
  const ui = _deps();
  if (!sid) {
    if (ui && ui.showToast) ui.showToast('Send a message first — Auto-approve is set per chat.');
    return false;
  }
  if (_busy) return false;
  _busy = true;
  try {
    if (_state.mode === MODE_AUTO) return await _write(sid, MODE_MANUAL);
    const warning = await _warningFor(sid);
    if (!warning || !ui || !ui.styledConfirm) {
      if (ui && ui.showToast) {
        ui.showToast('Auto-approve could not show its warning, so it stays off. Try again.', 6000);
      }
      return false;
    }
    const yes = await ui.styledConfirm(warning.text, {
      title: 'Auto-approve', confirmText: warning.proceed, cancelText: warning.keep, danger: true,
    });
    if (yes !== true) return false;
    const ok = await _write(sid, MODE_AUTO, warning.id);
    if (ok && ui && ui.showToast) {
      ui.showToast('Auto-approve is on for this chat.');
    }
    return ok;
  } finally {
    _busy = false;
  }
}

/**
 * Wire both surfaces once. `getSessionId` is supplied by the caller rather
 * than read from a global, so the chat module stays the one thing that knows
 * which chat is open (`Law 7`).
 */
export function init(getSessionId) {
  const { chip, badge } = _nodes();
  const sid = () => (typeof getSessionId === 'function' ? getSessionId() : _state.sid);
  if (chip && !chip._pantheonApprovalMode) {
    chip._pantheonApprovalMode = true;
    chip.addEventListener('click', () => { toggle(sid()); });
  }
  if (badge && !badge._pantheonApprovalMode) {
    badge._pantheonApprovalMode = true;
    // The badge is a way out as well as a statement: a person who notices it
    // should not have to find the chip to act on it.
    badge.addEventListener('click', () => { toggle(sid()); });
  }
  render();
}

const approvalModeModule = { init, load, render, toggle, currentMode, isAuto };
export default approvalModeModule;

if (typeof window !== 'undefined') {
  // The same door `fx8-mobile` drives, and the same door the desktop chip
  // drives: one API, so a phone control and a desktop chip cannot end up
  // meaning two different things.
  window.approvalModeModule = approvalModeModule;
}
