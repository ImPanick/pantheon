// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/turnSheet.js
//
// `D-2026-10-09-01` §4 — every control that decides what a turn does, reachable
// on a phone with one thumb.
//
// **What was wrong, measured 2026-10-09 in Chromium at 390×844 and 360×800 with
// touch emulation.** The chat bar is `container-type: inline-size` and its
// container query dropped the Agent/Chat toggle below a 340 px bar
// (`static/style.css`, "progressive shrinkage… sacrifice chrome before the
// typing area") with nothing put in its place. At a 360 px viewport the bar
// measures exactly 340 px, so `.mode-toggle` resolved to `display: none`: the
// composer row held `^`, Plan, Web, Shell and send, and the mode could not be
// reached AT ALL — not from the bar, not from the `^` menu (its items are
// Attach files / Documents / RAG / Workspace / Prompt), not from a slash
// command (`/toggle` offers web, bash, rag, research, doc, sidebar — no mode)
// and not from the palette. At 390×844 the toggle was on screen but 34 px tall
// and the model picker 22 px, both under the 44 px a thumb needs.
//
// **The shape, and why this one.** The `^` button is NOT a second overflow to
// hang this off: it is the composer's *add* menu, and it already absorbs the
// Plan / Web / Shell chips when the bar is tight (`initToolbarOverflow`). What
// was missing is a place for what the turn *is*. So the control the container
// query drops is REPLACED rather than merely removed: `#turn-chip` takes the
// segmented toggle's place on a narrow bar, says the mode without anything
// being opened, and opens one sheet holding the mode, the chat's approval mode
// (`D-2026-10-09-01` §2), the model, the context reading, Plan, Web, Shell and
// the persona — each row with its current value, so the sheet answers as well
// as changes. The chip is 44 px and narrower than the toggle it replaces
// (measured: 124.5 px → ~76 px), so the row gains room and the typing area,
// which is on its own line above, is untouched.
//
// **One source of truth** (`Law 7`). This module keeps no state. Every row
// reads the composer's own controls and every change CLICKS them, so the
// handlers that already own the state machine run exactly once — the mode's
// persistence and its research/workspace side effects, the per-mode tool
// preferences, Plan's status pill. A row whose control the page is not showing
// (Shell in Chat mode, a tool an admin switched off) is not drawn.

import { bindMenuDismiss } from './escMenuStack.js';

/** The composer controls each row drives. `btn` is clicked; `on` reads it. */
export const SWITCH_ROWS = [
  { row: 'turn-row-plan', btn: 'plan-toggle-btn' },
  { row: 'turn-row-web', btn: 'web-toggle-btn' },
  { row: 'turn-row-shell', btn: 'bash-toggle-btn' },
];

/** The chat's approval mode (`D-2026-10-09-01` §2) is the lane `fx8-approval`
 *  built: `#approval-mode-btn` in the composer, `window.approvalModeModule`
 *  behind it (`static/js/approvalMode.js`, which says in as many words that it
 *  is "the same door `fx8-mobile` drives"). The chip is `display: none` until
 *  an admin has granted the person `can_auto_approve`, so a row here follows
 *  it: no dead switch to discover (`Law 15`).
 *
 *  The other spellings are kept as a fallback only — the first control found
 *  is the one driven, and with none of them on the page the row stays hidden
 *  rather than inventing an approval state. */
export const APPROVAL_CONTROLS = [
  '#approval-mode-btn',
  '#chat-approval-toggle',
  '[data-approval-mode]',
];

function _el(doc, id) { return doc.getElementById(id) || null; }

/** Rendered, as far as a shim-able check can tell: not `hidden`, not
 *  `display: none`, not a chip the feature table took away (`SET-M-4`). */
export function isRendered(node) {
  if (!node) return false;
  if (node.hidden) return false;
  if (node.style && node.style.display === 'none') return false;
  try {
    const off = typeof window !== 'undefined' && window.__pantheonFeatureHiddenIds;
    if (off && node.id && off.has(node.id)) return false;
  } catch (_) { /* no window: a node sandbox */ }
  return true;
}

// A click this sheet makes itself is not an outside click. The rows drive the
// composer's own buttons, which sit OUTSIDE the sheet, and the dismissal
// wrapper's outside-click listener is on `document` in the capture phase — so
// without this the first row tapped closed the sheet under the thumb (measured
// 2026-10-09: tapping Chat switched the mode and shut the sheet, so Agent could
// not be tapped back). The dispatch is synchronous, so the flag is still up
// while that listener runs.
let _driving = 0;

function _click(node) {
  if (!node) return false;
  _driving += 1;
  try {
    if (typeof node.click === 'function') node.click();
    else node.dispatchEvent(new Event('click'));
  } finally {
    _driving -= 1;
  }
  return true;
}

/** True while a row is clicking a composer control on the sheet's behalf. */
export function isDriving() { return _driving > 0; }

/** The approval control, when this person has one. A control the page is not
 *  showing is a control an admin has not granted, so it is not offered here
 *  either. */
export function approvalControl(doc) {
  for (const sel of APPROVAL_CONTROLS) {
    const found = doc.querySelector(sel);
    if (found && isRendered(found)) return found;
  }
  return null;
}

/** `'auto'` / `'manual'` for a control, read from the module that owns the
 *  state where there is one and from the control itself otherwise. */
function _approvalOf(ctl) {
  try {
    const mod = typeof window !== 'undefined' && window.approvalModeModule;
    if (mod && typeof mod.isAuto === 'function') return mod.isAuto() ? 'auto' : 'manual';
  } catch (_) { /* fall through to the control */ }
  if (ctl.getAttribute('aria-pressed') === 'true') return 'auto';
  if (ctl.classList && ctl.classList.contains('active')) return 'auto';
  return ctl.getAttribute('data-approval-mode') === 'auto' ? 'auto' : 'manual';
}

/** What the turn is, read off the composer — never off a copy. */
export function readTurn(doc) {
  const agent = _el(doc, 'mode-agent-btn');
  const pill = _el(doc, 'chat-context-pill');
  const pillLabel = _el(doc, 'chat-context-pill-label');
  const persona = _el(doc, 'character-indicator-btn');
  const personaName = _el(doc, 'character-indicator-name');
  const model = _el(doc, 'model-picker-label');
  const hint = _el(doc, 'agent-limits-hint');
  const out = {
    mode: agent && agent.classList.contains('active') ? 'agent' : 'chat',
    model: model ? String(model.textContent || '').trim() : '',
    // `Law 10`: no reading yet is not 0%.
    context: isRendered(pill) && pillLabel ? String(pillLabel.textContent || '').trim() : null,
    persona: isRendered(persona) && personaName
      ? String(personaName.textContent || '').trim() : null,
    limits: hint && !hint.hidden ? String(hint.textContent || '').trim() : '',
    approval: null,
    switches: {},
  };
  for (const { row, btn } of SWITCH_ROWS) {
    const node = _el(doc, btn);
    out.switches[row] = {
      available: isRendered(node),
      on: !!(node && node.classList.contains('active')),
    };
  }
  const ctl = approvalControl(doc);
  if (ctl) out.approval = _approvalOf(ctl);
  return out;
}

function _seg(doc, segId, onId, offId, on) {
  const seg = _el(doc, segId);
  const yes = _el(doc, onId);
  const no = _el(doc, offId);
  if (seg) seg.classList.toggle('mode-chat', !on);
  if (yes) {
    yes.classList.toggle('active', on);
    yes.setAttribute('aria-checked', String(on));
  }
  if (no) {
    no.classList.toggle('active', !on);
    no.setAttribute('aria-checked', String(!on));
  }
}

/** Draw the chip and every sheet row from `readTurn`. Safe to call often. */
export function paint(doc) {
  const turn = readTurn(doc);
  const chipMode = _el(doc, 'turn-chip-mode');
  const chipFlag = _el(doc, 'turn-chip-approval');
  const chip = _el(doc, 'turn-chip');
  const modeWord = turn.mode === 'agent' ? 'Agent' : 'Chat';
  if (chipMode) chipMode.textContent = modeWord;
  if (chipFlag) chipFlag.hidden = turn.approval !== 'auto';
  if (chip) {
    // The chip's own words are the state; the label adds what the words alone
    // do not say — that this opens the rest, and that Auto is on.
    chip.setAttribute('aria-label', turn.approval === 'auto'
      ? `This turn: ${modeWord} mode, Auto approval`
      : `This turn: ${modeWord} mode`);
  }

  // The Mode row follows the controls it drives, like every other row here
  // (`fx8-census`, 2026-10-09 — it was the one row that did not, which is why
  // `#turn-row-mode` was markup nothing read and
  // `tests/test_orphan_ids_in_markup.py` reported it as a new orphan).
  //
  // What can take a mode away is the visibility table: `agent` is a `chip`
  // entry with `composer: ['mode-agent-btn']` and privilege `can_use_agent`
  // (`ui_visibility.js`), and the applier writes `display: none` on that one
  // button — the composer keeps Chat. So this mirrors the composer rather than
  // hiding the whole row: the option whose button is gone goes with it, and
  // the row goes only when BOTH are gone. Hiding the row on Agent alone would
  // strand a phone in Agent mode with no way back to Chat, which is the owner's
  // original complaint rebuilt, and nothing client-side forces Chat when the
  // privilege is withdrawn (the fall-back is the server's 409).
  //
  // The container query that drops `.mode-toggle` on a narrow bar does NOT
  // hide anything here: that is a stylesheet `display`, and `isRendered` reads
  // the inline one, the `hidden` attribute and the feature table — which is
  // the whole reason the chip and this sheet exist.
  const agentOn = isRendered(_el(doc, 'mode-agent-btn'));
  const chatOn = isRendered(_el(doc, 'mode-chat-btn'));
  const rowAgent = _el(doc, 'turn-mode-agent');
  const rowChat = _el(doc, 'turn-mode-chat');
  if (rowAgent) rowAgent.hidden = !agentOn;
  if (rowChat) rowChat.hidden = !chatOn;
  const modeRow = _el(doc, 'turn-row-mode');
  if (modeRow) modeRow.hidden = !agentOn && !chatOn;

  _seg(doc, 'turn-mode-seg', 'turn-mode-agent', 'turn-mode-chat', turn.mode === 'agent');

  const help = _el(doc, 'turn-mode-help');
  if (help) {
    // The sentence the desktop shows beside the toggle (`P7-10`), which the
    // bar drops below 660 px. Read from it, never written twice.
    const say = turn.mode === 'agent' ? turn.limits : '';
    help.textContent = say;
    help.hidden = !say;
  }

  const approvalRow = _el(doc, 'turn-row-approval');
  if (approvalRow) {
    approvalRow.hidden = turn.approval === null;
    if (turn.approval !== null) {
      _seg(doc, 'turn-approval-seg', 'turn-approval-auto', 'turn-approval-manual',
        turn.approval === 'auto');
    }
  }

  const modelValue = _el(doc, 'turn-value-model');
  if (modelValue) modelValue.textContent = turn.model || 'Select model';
  const modelRow = _el(doc, 'turn-row-model');
  if (modelRow) modelRow.hidden = !isRendered(_el(doc, 'model-picker-wrap'));

  const ctxValue = _el(doc, 'turn-value-context');
  if (ctxValue) ctxValue.textContent = turn.context || 'Not measured yet';
  const ctxRow = _el(doc, 'turn-row-context');
  if (ctxRow) ctxRow.disabled = !turn.context;

  const personaValue = _el(doc, 'turn-value-persona');
  if (personaValue) personaValue.textContent = turn.persona || 'None';

  for (const { row } of SWITCH_ROWS) {
    const node = _el(doc, row);
    if (!node) continue;
    const state = turn.switches[row];
    node.hidden = !state.available;
    node.classList.toggle('on', state.on);
    node.setAttribute('aria-checked', String(state.on));
  }
  return turn;
}

let _close = null;

export function isOpen(doc) {
  const layer = _el(doc, 'turn-sheet-layer');
  return !!(layer && !layer.classList.contains('hidden'));
}

export function closeSheet(doc) {
  if (_close) { const f = _close; _close = null; f(); return true; }
  const layer = _el(doc, 'turn-sheet-layer');
  if (!layer || layer.classList.contains('hidden')) return false;
  layer.classList.add('hidden');
  const chip = _el(doc, 'turn-chip');
  if (chip) chip.setAttribute('aria-expanded', 'false');
  return true;
}

export function openSheet(doc) {
  const layer = _el(doc, 'turn-sheet-layer');
  const sheet = _el(doc, 'turn-sheet');
  if (!layer || !sheet) return false;
  if (isOpen(doc)) return true;
  paint(doc);
  layer.classList.remove('hidden');
  const chip = _el(doc, 'turn-chip');
  if (chip) chip.setAttribute('aria-expanded', 'true');
  // One Escape stack, one back stack: `bindMenuDismiss` registers the dismiss
  // so Escape, the phone's Back (backStack asks `dismissTopMenu` first) and a
  // tap outside the panel all close exactly this layer (`fx-back.md`).
  _close = bindMenuDismiss(sheet, () => {
    _close = null;
    layer.classList.add('hidden');
    if (chip) chip.setAttribute('aria-expanded', 'false');
    // Two anchors count as inside (`bindMenuDismiss` asks for exactly this
    // override): a click the sheet made on the composer's own control, and the
    // chip itself — the outside-click listener runs in the capture phase, so
    // without the second one a press on the chip closed the sheet before the
    // chip's own handler ran and that handler then opened it straight back.
  }, (ev) => !_driving && !sheet.contains(ev.target) && !(chip && chip.contains(ev.target)));
  return true;
}

export function toggleSheet(doc) {
  return isOpen(doc) ? (closeSheet(doc), false) : (openSheet(doc), true);
}

/** Set the mode by clicking the composer's own button, so `initModeToggle`'s
 *  `setMode` — persistence, the research unset, the workspace chip — runs. */
export function setMode(doc, mode) {
  const btn = _el(doc, mode === 'agent' ? 'mode-agent-btn' : 'mode-chat-btn');
  // The same refusal `flipSwitch` makes, and for the same reason: a control
  // the page is not showing is a control an admin has not granted, so pressing
  // its row must not click it (`fx8-census`, 2026-10-09).
  if (!isRendered(btn)) return false;
  _click(btn);
  paint(doc);
  return true;
}

/** Press the chat's own approval control, when the mode asked for is not the
 *  one it is already in.
 *
 *  Handed off like the model picker rather than driven in place: turning Auto
 *  on asks first — one sentence saying what is given up (`D-2026-10-09-01`
 *  §2) — and a question put over the sheet, with the sheet's own outside-tap
 *  dismissal underneath it, is two layers answering the same tap. The chip
 *  carries the answer afterwards, which is where a person cannot miss it. */
export function setApproval(doc, mode) {
  const ctl = approvalControl(doc);
  if (!ctl) return false;
  if (_approvalOf(ctl) === mode) { closeSheet(doc); return true; }
  closeSheet(doc);
  setTimeout(() => { _click(ctl); paint(doc); }, 0);
  return true;
}

export function flipSwitch(doc, rowId) {
  const entry = SWITCH_ROWS.find((r) => r.row === rowId);
  if (!entry) return false;
  const btn = _el(doc, entry.btn);
  if (!isRendered(btn)) return false;
  _click(btn);
  paint(doc);
  return true;
}

/** Hand off to a control that already exists, closing the sheet first so the
 *  menu it opens is not drawn underneath it.
 *
 *  The click is made on the NEXT task, not in this one. The tap that reached
 *  the row is still propagating, and the menus it hands off to each close
 *  themselves on a document click landing outside them — so opening the model
 *  picker inside the row's own handler opened it and then the same tap closed
 *  it again (measured 2026-10-09: the sheet closed, the picker did not appear).
 *  `initOverflowMenu` defers its own outside-click listener for the same
 *  reason. */
export function handOff(doc, id) {
  closeSheet(doc);
  const target = _el(doc, id);
  if (!target) return false;
  setTimeout(() => _click(target), 0);
  return true;
}

export function initTurnSheet(doc) {
  const d = doc || (typeof document !== 'undefined' ? document : null);
  if (!d) return null;
  const chip = _el(d, 'turn-chip');
  if (!chip) return null;

  // Tapping the chip must not take the focus off the message box, or the
  // phone keyboard collapses under the sheet — the same reason
  // `#overflow-plus-btn` prevents its own pointerdown.
  chip.addEventListener('pointerdown', (e) => { if (e.preventDefault) e.preventDefault(); });
  chip.addEventListener('click', (e) => { if (e.stopPropagation) e.stopPropagation(); toggleSheet(d); });

  const close = _el(d, 'turn-sheet-close');
  if (close) close.addEventListener('click', () => closeSheet(d));

  const agent = _el(d, 'turn-mode-agent');
  const chat = _el(d, 'turn-mode-chat');
  if (agent) agent.addEventListener('click', () => setMode(d, 'agent'));
  if (chat) chat.addEventListener('click', () => setMode(d, 'chat'));

  const manual = _el(d, 'turn-approval-manual');
  const auto = _el(d, 'turn-approval-auto');
  if (manual) manual.addEventListener('click', () => setApproval(d, 'manual'));
  if (auto) auto.addEventListener('click', () => setApproval(d, 'auto'));

  for (const { row } of SWITCH_ROWS) {
    const node = _el(d, row);
    if (node) node.addEventListener('click', () => flipSwitch(d, row));
  }

  const model = _el(d, 'turn-row-model');
  if (model) model.addEventListener('click', () => handOff(d, 'model-picker-btn'));
  const ctx = _el(d, 'turn-row-context');
  if (ctx) ctx.addEventListener('click', () => handOff(d, 'chat-context-pill'));
  const persona = _el(d, 'turn-row-persona');
  if (persona) persona.addEventListener('click', () => handOff(d, 'overflow-preset-btn'));

  // The composer's controls change from a dozen places (a slash command, the
  // tour, a 409 falling back to Chat, Nobody mode, the feature table). The
  // page is read rather than told, the way `backStack.js` reads its windows.
  const watch = ['mode-agent-btn', 'mode-chat-btn', 'plan-toggle-btn', 'web-toggle-btn',
    'bash-toggle-btn', 'character-indicator-btn', 'character-indicator-name',
    'model-picker-label', 'chat-context-pill', 'chat-context-pill-label',
    // The sibling lane's chip (`D-2026-10-09-01` §2). Absent until it merges;
    // `_el` answers null and nothing here minds.
    'agent-limits-hint', 'approval-mode-btn'];
  // Pressed anywhere — the chip on the bar, the palette, the tour, a `/toggle
  // mode` — the control's own handler runs first (this listener is added after
  // `app.js` bound them) and the chip is redrawn from what it left behind.
  for (const id of watch) {
    const node = _el(d, id);
    if (node && node.tagName === 'BUTTON') node.addEventListener('click', () => paint(d));
  }
  // And for a change nobody clicked: a 409 writing `.active` straight onto the
  // buttons, `applyModeToToggles` half a second after a mode change, the
  // context wheel filling in when a turn ends.
  if (typeof MutationObserver !== 'undefined') {
    const obs = new MutationObserver(() => paint(d));
    for (const id of watch) {
      const node = _el(d, id);
      if (node) {
        obs.observe(node, {
          attributes: true, childList: true, characterData: true, subtree: true,
          attributeFilter: ['class', 'style', 'hidden', 'aria-pressed'],
        });
      }
    }
  }
  d.addEventListener('overflow-state-change', () => paint(d));

  paint(d);
  return { paint: () => paint(d), open: () => openSheet(d), close: () => closeSheet(d) };
}

export default { initTurnSheet, paint, readTurn, openSheet, closeSheet, toggleSheet,
  setMode, setApproval, flipSwitch, handOff, isOpen, isDriving, isRendered,
  approvalControl, SWITCH_ROWS, APPROVAL_CONTROLS };
