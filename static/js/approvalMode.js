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
 *   `#approval-mode-btn`      the composer chip, at the bottom right of the
 *                             composer (`B1706`). It names the mode in one
 *                             word and opens `#approval-mode-menu`: the
 *                             setting's name, both modes with one line each,
 *                             a check (`aria-checked`) on the one this chat is
 *                             in. `.active` is Auto (`.tool-chip`'s on-state).
 *                             Hidden entirely when the person may not use Auto.
 *   `#chat-auto-approve-badge`  the chat header, beside the chat's name.
 *                             Shown only while Auto is on.
 *
 * One API: `GET`/`POST /api/session/{sid}/approval-mode`.
 *
 * `B1706`: the chip was an on/off switch beside Plan / Web / Shell. The owner
 * asked for a mode selector at the bottom of the composer, so it is one control
 * that says which mode the chat is in and offers both. Its words are the
 * server's — the setting's name, each mode's name, chip word and one line
 * (`setting_label`, `modes` from `GET`) — and its menu is the model picker's
 * (`.model-picker-menu`, `.model-switch-item`, `pickerKeys.js`), dismissed
 * through the one Escape stack (`escMenuStack.js`): one popover pattern, not a
 * second (`Law 14`).
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

import { bindMenuDismiss } from './escMenuStack.js';   // `B1706`
import { whenShut } from './motion.js';   // `B1706`
import { handlePickerKeydown } from './pickerKeys.js';   // `B1706`

// `B1005`'s shape in the browser: every refusal the server can give is shown as
// the server's own sentence, because the server is the only thing that knows
// which of the four it was (`Law 10`, Doc 2 § 5 rule 7).
const MODE_MANUAL = 'manual';
const MODE_AUTO = 'auto';

/** A menu item: one mode, named by `data-approval-choice`. */
const ITEM = '.approval-mode-item';

let _state = { sid: null, mode: MODE_MANUAL, maySet: false, warning: null, words: null };
let _ui = null;
let _busy = false;
/** The open menu's dismiss (`bindMenuDismiss`), or null while it is shut. */
let _dismiss = null;
/** Whether the chip was last drawn shown — the strip is told when it changes. */
let _chipShown = null;

/** The modules this one needs, resolved late so a harness can supply them. */
function _deps() {
  return _ui || (typeof window !== 'undefined' ? window.uiModule : null);
}

/** The chip, its menu and the header badge, or nulls. */
function _nodes() {
  const doc = typeof document !== 'undefined' ? document : null;
  if (!doc) return {};
  return {
    wrap: doc.getElementById('approval-mode-wrap'),
    chip: doc.getElementById('approval-mode-btn'),
    label: doc.getElementById('approval-mode-label'),
    menu: doc.getElementById('approval-mode-menu'),
    title: doc.getElementById('approval-mode-menu-title'),
    options: doc.getElementById('approval-mode-options'),
    badge: doc.getElementById('chat-auto-approve-badge'),
  };
}

function _items(nodes) {
  return nodes.options ? [...nodes.options.querySelectorAll(ITEM)] : [];
}

function _choiceOf(item) {
  return item ? item.getAttribute('data-approval-choice') : null;
}

/**
 * `B1706`. The menu's words a `GET` answered with — the setting's name, and
 * each mode's name, chip word and one line — or null when it carried none (an
 * older server, a stub). With none, the chip is not drawn: a menu of blank
 * rows is a dead control (`Law 15`), and this module will not write words of
 * its own in their place.
 */
function _wordsOf(data) {
  const said = (obj, key) => (obj && typeof obj[key] === 'string' && obj[key]) || null;
  const setting = said(data, 'setting_label');
  const modes = {};
  for (const m of (data && Array.isArray(data.modes) ? data.modes : [])) {
    const mode = said(m, 'mode');
    const label = said(m, 'label');
    const short = said(m, 'short_label');
    if (mode && label && short) modes[mode] = { label, short, description: said(m, 'description') || '' };
  }
  return setting && modes[MODE_MANUAL] && modes[MODE_AUTO] ? { setting, modes } : null;
}

/**
 * Draw both surfaces from one state. Called after every read and every write,
 * so the chip, its menu and the badge cannot disagree about whether this chat
 * asks.
 */
export function render() {
  const n = _nodes();
  const auto = _state.mode === MODE_AUTO;
  const words = _state.words;
  // Hidden, not disabled: a control an admin has not granted is not a
  // control this person has (`Law 15` — no dead switch to discover).
  const shown = !!(_state.maySet && words);
  const current = words ? words.modes[_state.mode] : null;
  // The wrap goes too, or an empty box keeps its gap in the row.
  if (n.wrap) n.wrap.style.display = shown ? '' : 'none';
  if (n.chip) {
    n.chip.style.display = shown ? '' : 'none';
    n.chip.classList.toggle('active', auto);
    if (current) {
      // The word on the chip is the mode; the name says which setting it is,
      // and keeps the visible word in it (WCAG 2.5.3).
      const name = `${words.setting}: ${current.label}`;
      n.chip.setAttribute('aria-label', name);
      n.chip.title = name;
    }
  }
  if (n.label) n.label.textContent = current ? current.short : '';
  if (n.title) n.title.textContent = words ? words.setting : '';
  for (const item of _items(n)) {
    const mode = _choiceOf(item);
    const said = words ? words.modes[mode] : null;
    item.style.display = said ? '' : 'none';
    item.setAttribute('aria-checked', mode === _state.mode ? 'true' : 'false');
    const name = item.querySelector('.approval-mode-item-name');
    const line = item.querySelector('.approval-mode-item-desc');
    if (name) name.textContent = said ? said.label : '';
    if (line) line.textContent = said ? said.description : '';
  }
  if (!shown) closeMenu();
  if (n.badge) {
    // The header badge says the state and nothing else; it is only ever there
    // when there is something to say.
    n.badge.hidden = !auto;
  }
  if (_chipShown !== null && _chipShown !== shown) {
    // The bottom row's right side grew or shrank: the strip's overflow
    // re-measures what Plan / Web / Shell have left (`initToolbarOverflow`),
    // the way the summoned agent's chip tells it (`summon.js`).
    try { document.dispatchEvent(new CustomEvent('overflow-state-change')); } catch (_) {}
  }
  _chipShown = shown;
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
  // The privilege and the menu's words are the person's and the install's, not
  // the chat's, so they carry over; the mode and the warning are read afresh.
  _state = { sid: sessionId || null, mode: MODE_MANUAL, maySet: _state.maySet, warning: null,
             words: _state.words };
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
          words: _wordsOf(data),
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
    words: _state.words,
  };
  render();
  return true;
}

/**
 * Put this chat in `mode`: Manual approve at once, Auto-approve after its
 * warning is accepted. A menu item's click (`B1706`), the badge's, and the
 * phone sheet's Approval row all come here.
 *
 * The server decides, every time. This asks first because the person is about
 * to take on a risk and should read what it is — and `B1703`, the server
 * refuses Auto without the id of the warning they accepted, so the dialog is
 * the only way on, not a courtesy in front of it (`P2-18`). With no dialog to
 * show, or no warning to show in it, nothing is sent: Auto is never turned on
 * without the person having read the server's words. Choosing the mode the
 * chat is already in asks nothing and sends nothing.
 */
export async function choose(mode, sessionId) {
  const wanted = mode === MODE_AUTO ? MODE_AUTO : MODE_MANUAL;
  const sid = sessionId || _state.sid;
  const ui = _deps();
  if (sid === _state.sid && wanted === _state.mode) return true;
  if (!sid) {
    if (ui && ui.showToast) ui.showToast('Send a message first — Auto-approve is set per chat.');
    return false;
  }
  if (_busy) return false;
  _busy = true;
  try {
    if (wanted === MODE_MANUAL) return await _write(sid, MODE_MANUAL);
    const warning = await _warningFor(sid);
    if (!warning || !ui || !ui.styledConfirm) {
      if (ui && ui.showToast) {
        ui.showToast('Auto-approve could not show its warning, so it stays off. Try again.', 6000);
      }
      return false;
    }
    const yes = await ui.styledConfirm(warning.text, {
      title: 'Auto-approve', confirmText: warning.proceed, cancelText: warning.keep, danger: true,
      // `B1704`: opens on *Keep asking me*, so a reflexive Enter accepts nothing.
      focusCancel: true,
    });
    // Declined: nothing is sent, and the menu's check stays on Manual approve,
    // because the state it is drawn from never moved.
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

/** The other mode: Auto off at once, or on after its warning. The header
 *  badge's click — a way out, as well as a statement. */
export async function toggle(sessionId) {
  return choose(_state.mode === MODE_AUTO ? MODE_MANUAL : MODE_AUTO, sessionId);
}

// ── `B1706`: the chip's menu ────────────────────────────────────────────────

export function isMenuOpen() {
  const { menu } = _nodes();
  return !!(menu && !menu.classList.contains('hidden') && !menu.classList.contains('closing'));
}

/** Shut the menu: through its dismissal when it is open, so its Escape-stack
 *  entry goes with it. Focus that was in the menu returns to the chip. */
export function closeMenu() {
  if (_dismiss) { const d = _dismiss; _dismiss = null; d(); return true; }
  return false;
}

function _shut(n) {
  _dismiss = null;
  const doc = typeof document !== 'undefined' ? document : null;
  const focused = doc ? doc.activeElement : null;
  const held = !!(focused && n.menu && typeof n.menu.contains === 'function' && n.menu.contains(focused));
  if (n.chip) {
    n.chip.setAttribute('aria-expanded', 'false');
    if (held && typeof n.chip.focus === 'function') n.chip.focus({ preventScroll: true });
  }
  _items(n).forEach((item) => item.classList.remove('kb-active'));
  if (!n.menu) return;
  // The model picker's close (`B1638`): one answer, run once, and a menu
  // opened again before it runs keeps its `closing` taken away.
  n.menu.classList.add('closing');
  whenShut(n.menu, () => {
    if (!n.menu.classList.contains('closing')) return;
    n.menu.classList.remove('closing');
    n.menu.classList.add('hidden');
  }, 200);
}

/**
 * Open the menu under the chip, with the mode this chat is in highlighted and
 * focused — so Arrow keys walk from it and Enter or Space chooses (the model
 * picker's keys, `pickerKeys.js`, with the focus moving because there is no
 * box to type in). Escape, the phone's Back and a click outside close it
 * through the one Escape stack (`bindMenuDismiss`), and the focus returns to
 * the chip.
 */
export function openMenu() {
  const n = _nodes();
  if (!n.chip || !n.menu || n.chip.style.display === 'none') return false;
  if (isMenuOpen()) return true;
  render();
  n.menu.classList.remove('closing', 'hidden');
  // `aria-expanded` and nothing painted: `.input-icon-btn.expanded`'s `--fg`
  // on its 9% tint misses 4.5:1 on two palettes, and the open menu is the cue.
  n.chip.setAttribute('aria-expanded', 'true');
  const items = _items(n).filter((item) => item.style.display !== 'none');
  items.forEach((item) => item.classList.remove('kb-active'));
  const start = items.find((item) => item.getAttribute('aria-checked') === 'true') || items[0];
  if (start) {
    start.classList.add('kb-active');
    // `preventScroll`: the menu is placed where it is seen, and `.chat-container`
    // is `overflow: hidden` over wider content, which a focus that scrolls
    // would slide sideways.
    try { start.focus({ preventScroll: true }); } catch (_) { /* not focusable in this harness */ }
  }
  // Bound after the focus moved, so the wrapper sees a menu that has taken
  // the focus itself and leaves the keys to `pickerKeys.js`. The chip counts
  // as inside: a press on it is its own toggle, not an outside click that the
  // chip's handler would then answer by opening the menu straight back.
  const inside = n.wrap || n.menu;
  _dismiss = bindMenuDismiss(n.menu, () => _shut(n),
    (ev) => !(inside && typeof inside.contains === 'function' && inside.contains(ev.target)));
  return true;
}

export function toggleMenu() {
  return isMenuOpen() ? (closeMenu(), false) : openMenu();
}

/** The menu's keys: the model picker's, plus Tab, which leaves a menu by
 *  closing it — onto the chip (Shift+Tab) or past it (Tab). */
function _onMenuKey(e) {
  const n = _nodes();
  if (!n.options) return;
  if (e.key === 'Tab') {
    closeMenu();
    if (e.shiftKey && e.preventDefault) e.preventDefault();
    return;
  }
  handlePickerKeydown(e, n.options, ITEM, closeMenu, { roving: true });
}

/**
 * Wire both surfaces once. `getSessionId` is supplied by the caller rather
 * than read from a global, so the chat module stays the one thing that knows
 * which chat is open (`Law 7`).
 */
export function init(getSessionId) {
  const n = _nodes();
  const sid = () => (typeof getSessionId === 'function' ? getSessionId() : _state.sid);
  if (n.chip && !n.chip._pantheonApprovalMode) {
    n.chip._pantheonApprovalMode = true;
    n.chip.addEventListener('click', () => { toggleMenu(); });
  }
  if (n.options && !n.options._pantheonApprovalMode) {
    n.options._pantheonApprovalMode = true;
    n.options.addEventListener('keydown', _onMenuKey);
    for (const item of _items(n)) {
      item.addEventListener('click', () => {
        const mode = _choiceOf(item);
        closeMenu();
        choose(mode, sid());
      });
    }
  }
  if (n.badge && !n.badge._pantheonApprovalMode) {
    n.badge._pantheonApprovalMode = true;
    // The badge is a way out as well as a statement: a person who notices it
    // should not have to find the chip to act on it.
    n.badge.addEventListener('click', () => { toggle(sid()); });
  }
  render();
}

const approvalModeModule = {
  init, load, render, choose, toggle, currentMode, isAuto,
  openMenu, closeMenu, toggleMenu, isMenuOpen,
};
export default approvalModeModule;

if (typeof window !== 'undefined') {
  // The same door `fx8-mobile` drives, and the same door the desktop chip
  // drives: one API, so a phone control and a desktop chip cannot end up
  // meaning two different things.
  window.approvalModeModule = approvalModeModule;
}
