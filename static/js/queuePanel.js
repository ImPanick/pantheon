// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/queuePanel.js

/**
 * The docked queue panel (P6-04), its sequential-vs-parallel picker (P6-06),
 * and the row vocabulary it borrows from the Tasks activity view (P6-07).
 *
 * ── What this is a clone of, and what the generalisation pass cost ──────────
 * `static/js/research/jobs.js` (382 lines) is the job engine this module was
 * cloned from, as `P6-04` instructs. Re-measured 2026-08-29, scope
 * case-insensitive `research` in that one file: **17 occurrences on 16 lines,
 * across 7 distinct `/api/research/*` endpoints** (`active`, `cancel`,
 * `library`, `result-peek`, `start`, `status`, `stream`). The roadmap's
 * "roughly 16 references across 7 endpoints" is the *line* count; the
 * occurrence count is 17. Both are true, which is why the scope is written in.
 *
 * The generalisation pass replaced all seven endpoints with ONE injected
 * driver: chat.js owns the send path, so "launch" here is a call back into it,
 * not an HTTP POST.
 *
 * **What this file actually reuses, corrected 2026-08-29.** An earlier version of
 * this comment claimed it kept `setRenderCallback` / `_notify`, `startAllQueued` /
 * `startAllQueuedSequential`, and a `Promise.all` of launches. None of the three
 * is true: those identifiers appear in this file only inside the sentence that
 * claimed them, and `chat.js` documents the opposite in as many words — *"the
 * launches are issued one after another on purpose"*, an awaited serial loop. A
 * comment that leads the next reader to a wrong conclusion is the incident Law 3
 * exists for, and a false reuse ledger is worse than none in the run whose whole
 * deliverable is reuse. What is genuinely shared:
 *
 *   - `formatElapsed`, **imported** from `research/jobs.js` rather than copied.
 *     There are already two elapsed formatters in this tree
 *     (`research/jobs.js formatElapsed`, `tasks.js _fmtElapsed`); a third would
 *     be the Law 14 failure this row exists to avoid.
 *   - `dragSort.enable`, the existing drag engine, rather than a second one.
 *   - the queued → running → terminal status vocabulary, which is
 *     `core/database.py`'s and not a new one.
 *
 * What was deliberately NOT cloned is the part that matters: `jobs.js` is a state
 * engine and this file is a view. It holds no items — it reads through
 * `driver.getEntries` and mutates through the driver, so `chat.js` keeps the one
 * queue and the one persistence hook.
 *
 * ── One queue, one row vocabulary, two views (Law 7 / Law 14) ───────────────
 * This module does NOT own the queue. `chat.js` has owned `_queuedAgentRequests`
 * and its persistence since `P6-01`/`P6-02`, and moving the array here would
 * make two stores out of one. The panel reads the queue through the driver and
 * mutates it through the driver — chat.js stays the single source of truth.
 *
 * Rows are rendered with the Tasks activity view's own classes
 * (`task-log-row`, `task-log-status-*`, `task-log-running-elapsed[data-since]`,
 * `task-log-force-run`, `task-log-stop`) so there is exactly one queue-row
 * appearance in the product, styled once in `style.css`. That is `P6-07`: the
 * activity view already renders every status with a shared elapsed timer, a
 * force button and a stop button, so this reuses it rather than inventing a
 * second one. The entries themselves come from `chatModule`'s
 * `getQueueActivityEntries()`, which emits the exact shape `tasks.js`'s
 * `_runToActivityEntry` emits — so pointing the Activity view at the queue is
 * one call there, not a second mapper.
 *
 * ── Status vocabulary (P6-05, documented at core/database.py:810+) ──────────
 * Six values: queued → running → success | error | skipped | aborted.
 * `aborted` is NOT folded into `error` — that is what corrupts error-rate
 * statistics, and it is the whole reason the value exists. A stopped queue
 * item is `aborted`. An item whose chat was deleted under it is `skipped`
 * ("deliberately did not run"), not an error.
 *
 * ── Deliberately absent ────────────────────────────────────────────────────
 * No per-item trust rung. It was removed from `P6-04` on 2026-08-28: it would
 * make this the first trust-ladder UI in the product, selecting from a ladder
 * `P7-05` records as not existing. It arrives once `P7-03`/`P7-04` build the
 * ladder — one control, not two vocabularies.
 *
 * Theme tokens only (D-2026-08-26-03). Nothing here defines `--accent`, and
 * every accent reference in the CSS this module depends on carries the
 * `var(--red)` fallback the rest of `style.css` uses.
 */

import { formatElapsed } from './research/jobs.js?v=20260630researchthumb';
import dragSortModule from './dragSort.js';
import { runStatusLabel, runStatusDotClass } from './runStatus.js';
import { chevronIcon, playIcon, stopIcon } from './icons.js';
import { promptRunMode as openRunModePicker } from './runModePicker.js?v=20260920attachbucket1';

/** Injected by chat.js at init. See the contract in `init()`. */
let _driver = null;
let _els = null;
let _folded = false;
let _wired = false;
let _timer = null;
let _editingId = null;      // the row whose textarea is open — never re-render under it
let _modelChoices = null;   // memoised; the model list is fetched by models.js, not here

/**
 * Launched-but-not-finished parallel runs. A queued item leaves chat.js's array
 * the moment it is sent, so without this the panel would lose sight of exactly
 * the rows `P6-07`'s elapsed timer and stop button exist to serve.
 * `{ id, message, sessionId, status, startedAt, error }`
 */
const _launched = [];

// ── Icons — the same glyphs the surfaces being reused already draw ──────────

const ICON_CHEVRON = chevronIcon({ strokeWidth: 3 });
const ICON_QUEUE = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3.5" cy="6" r="1.5" fill="currentColor" stroke="none"/><circle cx="3.5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="3.5" cy="18" r="1.5" fill="currentColor" stroke="none"/></svg>';
const ICON_PLAY = playIcon({ size: 9 });
const ICON_STOP = stopIcon({ size: 9 });
const ICON_GRIP = '<svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden="true"><circle cx="2.5" cy="2" r="1.1"/><circle cx="7.5" cy="2" r="1.1"/><circle cx="2.5" cy="6" r="1.1"/><circle cx="7.5" cy="6" r="1.1"/><circle cx="2.5" cy="10" r="1.1"/><circle cx="7.5" cy="10" r="1.1"/></svg>';
const ICON_X = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

// The run-mode popover's two glyphs used to be spelled out here as well, byte
// for byte identical to `research/panel.js`'s pair. `P5-17` moved both, and the
// picker itself, into `runModePicker.js`.

// Rows are built with createElement/textContent, never innerHTML from user
// text, so this module needs no escaper of its own — there is no second
// escaping rule to keep in step with `chat.js`'s.

// ── Status vocabulary ───────────────────────────────────────────────────────

/**
 * Map a run status onto the CSS dot the Tasks activity view already ships.
 * `success` is drawn by `.task-log-status-ok`; every other value keeps its own
 * name. `aborted` has its own dot on purpose — see the header.
 *
 * `B78`: this switch WAS a hand-written second copy of the ladder inside
 * `tasks.js` `_renderActivityEntry`, written out longhand because this module
 * cannot import that one (`runStatus.js`'s header says why). Measured, the two
 * copies disagreed on legacy `failed` — `info` here, `error` there — off the
 * same input. Latent rather than visible: no row this panel builds carries
 * `failed` today, because `getQueueActivityEntries` writes only `queued` and
 * `noteLaunched`/`noteLaunchResult` write only `running`/`success`/`error`/
 * `aborted`. Fixed anyway, because the next value either of them learns is the
 * one that has to be learned twice.
 *
 * The `info` fallback stays here and is NOT in the shared function: the
 * Activity view answers an unknown status by text-scanning the row's result,
 * and this panel has no result text to scan. Two honest answers to the same
 * question, so the shared function returns `''` and each caller says its own.
 */
function statusClass(status) {
  return runStatusDotClass(status) || 'info';
}

/**
 * Human label for the six shipped values. Never says "failed" for `aborted`.
 *
 * `B13`: this switch WAS the vocabulary, and the Activity view — rendering the
 * same rows from the same `getQueueActivityEntries` source — had its own, so
 * one message read *Waiting* here and *Queued* there with both panels open.
 * The words moved to `runStatus.js` unchanged; every one of them is still this
 * file's wording, because a queue row is a message and that is the column it
 * asks for. Kept as an exported function rather than inlined at the one call
 * site below: it is part of this module's surface and something else may yet
 * want the panel's word for a row it is about to add.
 */
function statusLabel(status) {
  return runStatusLabel(status, 'message');
}

// ── Element collection ──────────────────────────────────────────────────────

function collectEls() {
  const root = document.getElementById('queue-panel');
  if (!root) return null;
  return {
    root,
    fold: document.getElementById('queue-panel-fold'),
    chevron: document.getElementById('queue-panel-chevron'),
    icon: document.getElementById('queue-panel-icon'),
    count: document.getElementById('queue-panel-count'),
    state: document.getElementById('queue-panel-state'),
    pause: document.getElementById('queue-panel-pause'),
    body: document.getElementById('queue-panel-body'),
    list: document.getElementById('queue-panel-list'),
    run: document.getElementById('queue-panel-run'),
    hint: document.getElementById('queue-panel-hint'),
  };
}

// ── Row rendering — the Tasks activity view's markup, not a second one ──────

function modelChoices() {
  if (_modelChoices) return _modelChoices;
  let items = [];
  try {
    items = (window.modelsModule && window.modelsModule.getCachedItems
      ? window.modelsModule.getCachedItems()
      : []) || [];
  } catch (_) { items = []; }
  const out = [];
  const seen = new Set();
  for (const item of items) {
    const ids = (item.models || []).concat(item.models_extra || []);
    const labels = (item.models_display || []).concat(item.models_extra_display || []);
    ids.forEach((mid, i) => {
      if (!mid) return;
      const key = `${item.endpoint_id || item.url || ''}::${mid}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({
        key,
        model: mid,
        endpointUrl: item.url || '',
        endpointId: item.endpoint_id || '',
        label: String(labels[i] || mid).split('/').pop(),
      });
    });
  }
  // Only memoise once the list is actually populated — models.js fills its
  // cache asynchronously, and caching an empty array here would leave the
  // per-item model picker permanently empty on a cold load.
  if (out.length) _modelChoices = out;
  return out;
}

/** Resolve a stored `{model, endpointId}` back to a choice key. */
function choiceKeyFor(entry) {
  if (!entry || !entry.model) return '';
  const found = modelChoices().find(c => c.model === entry.model
    && (!entry.endpointId || c.endpointId === entry.endpointId));
  return found ? found.key : '';
}

function buildRow(entry) {
  const row = document.createElement('div');
  const cls = statusClass(entry.status);
  row.className = `task-log-row queue-row task-log-row-${cls}`;
  row.dataset.queueId = entry.queueId;
  row.dataset.entryStatus = entry.status || '';
  if (_editingId && _editingId === entry.queueId) row.classList.add('expanded');

  const head = document.createElement('div');
  head.className = 'task-log-row-head';

  if (entry.editable) {
    const grip = document.createElement('span');
    grip.className = 'queue-row-grip';
    grip.title = 'Drag to reorder';
    grip.setAttribute('aria-hidden', 'true');
    grip.innerHTML = ICON_GRIP;
    head.appendChild(grip);
  }

  const dot = document.createElement('span');
  dot.className = `task-log-status task-log-status-${cls}`;
  dot.title = entry.status || '';
  head.appendChild(dot);

  const pos = document.createElement('span');
  pos.className = 'queue-row-pos';
  pos.textContent = entry.position ? `${entry.position}.` : '';
  head.appendChild(pos);

  const name = document.createElement('span');
  name.className = 'task-log-name queue-row-text';
  name.textContent = entry.taskName || '(empty message)';
  name.title = entry.taskName || '';
  head.appendChild(name);

  if (entry.attachmentCount) {
    const clip = document.createElement('span');
    clip.className = 'queued-pill queue-row-attach';
    clip.textContent = `${entry.attachmentCount} file${entry.attachmentCount > 1 ? 's' : ''}`;
    head.appendChild(clip);
  }

  const spacer = document.createElement('span');
  spacer.style.flex = '1';
  head.appendChild(spacer);

  // Right side: the activity view's own "Running <elapsed> [start now] [stop]"
  // cluster. `.task-log-running-elapsed[data-since]` is the shared timer
  // contract — `tick()` below drives it exactly as `_tickActivityTimers` does.
  const right = document.createElement('span');
  right.className = 'task-log-running-inline';
  const label = document.createElement('span');
  label.className = 'task-log-running-label';
  label.textContent = statusLabel(entry.status);
  right.appendChild(label);

  if (entry.ts) {
    const el = document.createElement('span');
    el.className = 'task-log-running-elapsed';
    el.dataset.since = String(new Date(entry.ts).getTime());
    el.textContent = formatElapsed(Date.now() - new Date(entry.ts).getTime());
    right.appendChild(el);
  }

  if (entry.status === 'queued') {
    const force = document.createElement('button');
    force.type = 'button';
    force.className = 'task-log-force-run queue-force-run';
    force.title = 'Send this one now, ahead of the rest';
    force.innerHTML = `${ICON_PLAY}<span>Start now</span>`;
    right.appendChild(force);
  }
  if (entry.status === 'running') {
    const stop = document.createElement('button');
    stop.type = 'button';
    stop.className = 'task-log-stop queue-stop';
    stop.title = 'Stop this run';
    stop.innerHTML = ICON_STOP;
    right.appendChild(stop);
  }
  if (entry.editable) {
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'task-log-stop queue-remove';
    del.title = 'Remove from the queue';
    del.innerHTML = ICON_X;
    right.appendChild(del);
  }
  head.appendChild(right);
  row.appendChild(head);

  // Body + actions carry `.task-log-row-body` / `.task-log-row-actions` so the
  // activity view's existing collapse rule hides them until the row is
  // expanded. No new show/hide CSS, no second expander.
  const body = document.createElement('div');
  body.className = 'task-log-row-body queue-row-editor';
  if (entry.editable) {
    const ta = document.createElement('textarea');
    ta.className = 'queue-row-input';
    ta.rows = 2;
    ta.value = entry.taskName || '';
    ta.setAttribute('aria-label', 'Queued message');
    body.appendChild(ta);
  } else if (entry.result) {
    const p = document.createElement('div');
    p.className = 'queue-row-note';
    p.textContent = entry.result;
    body.appendChild(p);
  }
  row.appendChild(body);

  const actions = document.createElement('div');
  actions.className = 'task-log-row-actions queue-row-actions';
  if (entry.editable) {
    const modeWrap = document.createElement('label');
    modeWrap.className = 'queue-row-field';
    modeWrap.innerHTML = '<span>Mode</span>';
    const mode = document.createElement('select');
    mode.className = 'queue-row-mode';
    for (const [value, text] of [['', 'Same as chat'], ['agent', 'Agent'], ['chat', 'Chat']]) {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = text;
      if ((entry.mode || '') === value) opt.selected = true;
      mode.appendChild(opt);
    }
    modeWrap.appendChild(mode);
    actions.appendChild(modeWrap);

    const modelWrap = document.createElement('label');
    modelWrap.className = 'queue-row-field';
    modelWrap.innerHTML = '<span>Model</span>';
    const model = document.createElement('select');
    model.className = 'queue-row-model';
    const choices = modelChoices();
    const first = document.createElement('option');
    first.value = '';
    first.textContent = choices.length ? 'Same as chat' : 'Same as chat (list still loading)';
    model.appendChild(first);
    const selectedKey = choiceKeyFor(entry);
    for (const c of choices) {
      const opt = document.createElement('option');
      opt.value = c.key;
      opt.textContent = c.label;
      if (c.key === selectedKey) opt.selected = true;
      model.appendChild(opt);
    }
    modelWrap.appendChild(model);
    actions.appendChild(modelWrap);

    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'queue-row-save';
    save.textContent = 'Save';
    actions.appendChild(save);
  }
  row.appendChild(actions);
  return row;
}

// ── Reading the queue ───────────────────────────────────────────────────────

/**
 * Rows for the current chat: the live queue (editable) plus any parallel runs
 * this panel launched and has not yet seen finish.
 */
function entries() {
  if (!_driver) return [];
  let live = [];
  try { live = _driver.getEntries() || []; } catch (_) { live = []; }
  const sid = safeSessionId();
  const launched = _launched
    .filter(l => !sid || l.homeSessionId === sid)
    .map(l => ({
      queueId: l.id,
      taskName: l.message,
      kind: 'llm',
      status: l.status,
      // ISO like every other row, so `ts` has exactly one type in this list.
      ts: new Date(l.startedAt).toISOString(),
      result: l.error || '',
      sessionId: l.sessionId,
      attachmentCount: 0,
      editable: false,
      position: 0,
      mode: l.mode || '',
      model: l.model || '',
      endpointId: l.endpointId || '',
    }));
  return live.concat(launched);
}

function safeSessionId() {
  try { return (_driver && _driver.getSessionId && _driver.getSessionId()) || ''; }
  catch (_) { return ''; }
}

// ── Render ──────────────────────────────────────────────────────────────────

export function render() {
  if (!_els || !_els.root) return;
  const rows = entries();
  // `waiting` drives the Send button, so it must count only rows the drain
  // would actually take. A row whose attachment is still uploading is queued
  // and not sendable; counting it here put a "Send now" button on screen that
  // the drain's own `!it.pendingUpload` filter guaranteed would do nothing.
  const queued = rows.filter(r => r.status === 'queued');
  const waiting = queued.filter(r => r.sendable !== false).length;
  const preparing = queued.length - waiting;
  const running = rows.filter(r => r.status === 'running').length;

  if (!rows.length) {
    _els.root.hidden = true;
    stopTimer();
    return;
  }
  _els.root.hidden = false;

  _els.count.textContent = waiting
    ? `${waiting} waiting`
    : (running ? `${running} sending` : (preparing ? `${preparing} uploading` : ''));

  const paused = !!(_driver && _driver.isPaused && _driver.isPaused());
  // Law 15: the state line says what happens next without anyone being told.
  let state;
  if (paused) state = 'Paused — nothing sends until you press Resume';
  else if (running) state = 'Running now';
  else if (!waiting && preparing) state = 'Attaching files — sends once the upload finishes';
  else if (_driver && _driver.isBusy && _driver.isBusy()) state = 'Sends when this reply finishes';
  else state = 'Sends on the next free moment';
  _els.state.textContent = state;
  _els.state.dataset.queueState = paused ? 'paused' : (running ? 'running' : 'waiting');

  _els.pause.textContent = paused ? 'Resume' : 'Pause';
  _els.pause.setAttribute('aria-pressed', paused ? 'true' : 'false');
  _els.pause.title = paused
    ? 'Start sending queued messages again'
    : 'Hold the queue — queued messages stay put until you press Resume';

  _els.run.hidden = waiting === 0;
  _els.run.textContent = waiting > 1 ? `Send all ${waiting} now` : 'Send now';
  _els.run.title = waiting > 1
    ? 'Choose one after another in this chat, or all at once in new chats'
    : 'Send this queued message now';

  _els.hint.textContent = waiting
    ? 'Drag to reorder · click a row to edit it, or change its mode and model'
    : (preparing
        ? 'A message is waiting on its attachment. It queues normally once the upload lands.'
        : 'These runs keep going even if you switch chats.');

  const list = _els.list;
  // Never re-render out from under an open editor — it would eat the typing.
  //
  // Re-applying the `expanded` class is not enough on its own: the rebuilt row
  // gets a brand-new textarea carrying the *saved* text, so anything typed and
  // not yet saved is silently gone. Any queue event — an item finishing, a
  // status poll, a drag — can trigger this while a row is open. So carry the
  // in-progress value, the caret and the focus across the rebuild.
  const openId = _editingId;
  let draft = null;
  if (openId) {
    const openTa = list.querySelector(
      `[data-queue-id="${CSS.escape(openId)}"] .queue-row-input`);
    if (openTa) {
      draft = {
        value: openTa.value,
        start: openTa.selectionStart,
        end: openTa.selectionEnd,
        focused: document.activeElement === openTa,
      };
    }
  }
  list.innerHTML = '';
  for (const entry of rows) list.appendChild(buildRow(entry));
  if (openId) {
    const reopened = list.querySelector(`[data-queue-id="${CSS.escape(openId)}"]`);
    if (reopened) {
      reopened.classList.add('expanded');
      const ta = reopened.querySelector('.queue-row-input');
      if (ta && draft) {
        ta.value = draft.value;
        if (draft.focused) {
          ta.focus();
          try { ta.setSelectionRange(draft.start, draft.end); } catch (_) { /* detached */ }
        }
      }
    } else _editingId = null;
  }
  tick();
  if (rows.some(r => r.ts)) startTimer();
  enableDrag();
}

/**
 * One interval ticks every `.task-log-running-elapsed[data-since]` in the
 * panel — the same contract, and the same lazily-started/stopped interval
 * shape, the Tasks activity view uses for its running rows.
 */
function startTimer() {
  if (_timer) return;
  _timer = setInterval(() => { if (!tick()) stopTimer(); }, 1000);
}
function stopTimer() {
  if (!_timer) return;
  clearInterval(_timer);
  _timer = null;
}
function tick() {
  if (!_els || !_els.list) return false;
  const els = _els.list.querySelectorAll('.task-log-running-elapsed[data-since]');
  if (!els.length) return false;
  const now = Date.now();
  els.forEach(el => {
    const since = parseInt(el.dataset.since, 10);
    if (since) el.textContent = formatElapsed(now - since);
  });
  return true;
}

// ── Drag-reorder — dragSort.js, not a second drag implementation ────────────

function enableDrag() {
  if (!_els || !_els.list) return;
  const editable = _els.list.querySelectorAll('.queue-row[data-queue-id] .queue-row-grip');
  if (!editable.length) return;
  try {
    dragSortModule.enable('queue-panel-list', '.queue-row', {
      instanceKey: 'queue-panel-list',
      handleSelector: '.queue-row-grip',
      onReorder: (items) => {
        const ids = items.map(el => el.dataset.queueId).filter(Boolean);
        if (_driver && _driver.reorder) _driver.reorder(ids);
        render();
      },
    });
  } catch (_) { /* reorder is a convenience; the queue still works without it */ }
}

// ── Wiring ──────────────────────────────────────────────────────────────────

function rowIdFrom(target) {
  const row = target && target.closest ? target.closest('.queue-row') : null;
  return row ? row.dataset.queueId : '';
}

function commitRow(row) {
  if (!row || !_driver || !_driver.update) return;
  const id = row.dataset.queueId;
  if (!id) return;
  const ta = row.querySelector('.queue-row-input');
  const modeSel = row.querySelector('.queue-row-mode');
  const modelSel = row.querySelector('.queue-row-model');
  const patch = {};
  if (ta) patch.message = ta.value;
  if (modeSel) patch.mode = modeSel.value || '';
  if (modelSel) {
    const choice = modelChoices().find(c => c.key === modelSel.value);
    patch.model = choice ? choice.model : '';
    patch.endpointUrl = choice ? choice.endpointUrl : '';
    patch.endpointId = choice ? choice.endpointId : '';
  }
  _driver.update(id, patch);
}

function wire() {
  if (_wired) return;
  _wired = true;

  _els.fold.addEventListener('click', () => {
    _folded = !_folded;
    _els.root.classList.toggle('queue-panel-folded', _folded);
    _els.body.hidden = _folded;
    _els.fold.setAttribute('aria-expanded', _folded ? 'false' : 'true');
  });

  _els.pause.addEventListener('click', () => {
    if (!_driver || !_driver.setPaused) return;
    const now = !!(_driver.isPaused && _driver.isPaused());
    _driver.setPaused(!now);
    render();
  });

  _els.run.addEventListener('click', () => {
    const waiting = entries().filter(r => r.status === 'queued').length;
    if (!waiting) return;
    if (waiting > 1) { promptRunMode(waiting, _els.run); return; }
    if (_driver && _driver.runSequential) _driver.runSequential();
  });

  // One delegated listener for the whole list. Rows are rebuilt on every
  // render, so per-row listeners would re-attach on each paint.
  _els.list.addEventListener('click', (ev) => {
    const t = ev.target;
    const id = rowIdFrom(t);
    if (!id) return;
    const row = t.closest('.queue-row');
    if (t.closest('.queue-force-run')) {
      ev.stopPropagation();
      if (_driver && _driver.startNow) _driver.startNow(id);
      return;
    }
    if (t.closest('.queue-stop')) {
      ev.stopPropagation();
      if (_driver && _driver.stopRun) _driver.stopRun(id);
      return;
    }
    if (t.closest('.queue-remove')) {
      ev.stopPropagation();
      if (_editingId === id) _editingId = null;
      if (_driver && _driver.remove) _driver.remove(id);
      return;
    }
    if (t.closest('.queue-row-save')) {
      ev.stopPropagation();
      commitRow(row);
      _editingId = null;
      row.classList.remove('expanded');
      render();
      return;
    }
    // Clicks inside the editor must not toggle the row shut under the caret.
    if (t.closest('.queue-row-editor') || t.closest('.queue-row-field') || t.closest('.queue-row-grip')) return;
    const open = row.classList.toggle('expanded');
    if (open) {
      _editingId = id;
      const ta = row.querySelector('.queue-row-input');
      if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    } else {
      commitRow(row);
      if (_editingId === id) _editingId = null;
      render();
    }
  });

  // Enter commits an in-place edit; Shift+Enter keeps its newline; Escape
  // abandons it. Same three keys the composer already teaches.
  _els.list.addEventListener('keydown', (ev) => {
    if (!ev.target.classList || !ev.target.classList.contains('queue-row-input')) return;
    const row = ev.target.closest('.queue-row');
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      commitRow(row);
      _editingId = null;
      render();
    } else if (ev.key === 'Escape') {
      ev.preventDefault();
      _editingId = null;
      render();
    }
  });

  _els.list.addEventListener('change', (ev) => {
    if (!ev.target.classList) return;
    if (ev.target.classList.contains('queue-row-mode') || ev.target.classList.contains('queue-row-model')) {
      commitRow(ev.target.closest('.queue-row'));
    }
  });
}

// ── Sequential vs parallel (P6-06) ─────────────────────────────────────────

/**
 * The queue's run mode, in the queue's words.
 *
 * `P5-17` moved the mechanism to `runModePicker.js`; what stays here is the
 * only part that was ever the queue's — its id, its row order (sequential
 * first, which research reverses), its two titles and the subtitles that are
 * the `Law 15` half of `P6-06`: "Parallel" and "Sequential" name a mechanism,
 * not a consequence, and a first-time user cannot tell from those two words
 * that one of them opens new chats. Those strings are deliberately not shared
 * with the research panel, which opens none.
 */
export function promptRunMode(count, anchorBtn, handlers) {
  const onParallel = (handlers && handlers.onParallel)
    || (() => { if (_driver && _driver.runParallel) _driver.runParallel(); });
  const onSequential = (handlers && handlers.onSequential)
    || (() => { if (_driver && _driver.runSequential) _driver.runSequential(); });
  return openRunModePicker({
    id: 'queue-run-mode-popover',
    anchor: anchorBtn,
    rows: [
      {
        mode: 'sequential',
        title: 'One after another',
        sub: 'Here in this chat, in the order below',
        onSelect: onSequential,
      },
      {
        mode: 'parallel',
        title: 'All at once',
        sub: `Opens ${count} new chats, one per message`,
        onSelect: onParallel,
      },
    ],
  });
}

// ── Launched-run bookkeeping, called by the driver ──────────────────────────

/**
 * A parallel launch got its own session. Track it so its row keeps a live
 * elapsed timer and a working Stop after it has left chat.js's queue.
 * `homeSessionId` is the chat the user launched *from*, so the panel does not
 * follow them into an unrelated conversation.
 */
export function noteLaunched(item, sessionId, homeSessionId) {
  if (!item) return null;
  startLaunchPoll();
  const rec = {
    id: `L${item.id || Math.random().toString(36).slice(2)}`,
    message: item.message || '',
    sessionId: sessionId || '',
    homeSessionId: homeSessionId || '',
    status: sessionId ? 'running' : 'error',
    startedAt: Date.now(),
    error: '',
    mode: item.mode || '',
    model: item.model || '',
    endpointId: item.endpointId || '',
  };
  _launched.push(rec);
  render();
  return rec;
}

/** Terminal update for a launched run. `status` must be one of the six. */
export function noteLaunchResult(rec, status, message) {
  if (!rec) return;
  rec.status = status;
  if (message) rec.error = message;
  render();
}

/** Drop finished rows once the user has had a chance to see them. */
export function sweepLaunched(maxAgeMs = 60000) {
  const now = Date.now();
  let changed = false;
  for (let i = _launched.length - 1; i >= 0; i--) {
    const l = _launched[i];
    const terminal = l.status !== 'running' && l.status !== 'queued';
    if (terminal && now - l.startedAt > maxAgeMs) { _launched.splice(i, 1); changed = true; }
  }
  if (changed) render();
}

/**
 * Poll the launched rows against the live stream registry so a run that ends
 * elsewhere still resolves here. `isStreamLive` is injected — chat.js owns the
 * registry, this module owns the row.
 */
export function refreshLaunched() {
  if (!_launched.length) { stopLaunchPoll(); return; }
  if (!_driver || !_driver.isStreamLive) return;
  let changed = false;
  for (const l of _launched) {
    if (l.status !== 'running') continue;
    if (!l.sessionId) continue;
    let live = false;
    try { live = !!_driver.isStreamLive(l.sessionId); } catch (_) { live = true; }
    if (!live) { l.status = 'success'; changed = true; }
  }
  if (changed) render();
  sweepLaunched();
}

/** Find the launched record a panel row id belongs to. */
export function launchedById(id) {
  return _launched.find(l => l.id === id) || null;
}

/**
 * The launched-run poll is started when the first parallel run appears and
 * stopped when the last one clears — the same lazily-started, self-stopping
 * shape `tasks.js` `_startActivityTimers` uses for its running rows, rather
 * than a timer that burns a tick forever on an empty queue.
 */
let _launchPoll = null;
function startLaunchPoll() {
  if (_launchPoll) return;
  _launchPoll = setInterval(() => refreshLaunched(), 4000);
}
function stopLaunchPoll() {
  if (!_launchPoll) return;
  clearInterval(_launchPoll);
  _launchPoll = null;
}

// ── Public entry points ─────────────────────────────────────────────────────

export function refresh() { render(); }

/**
 * `driver` contract, all optional except `getEntries`:
 *   getEntries()          -> activity-shaped rows for the current chat
 *   getSessionId()        -> current session id
 *   isBusy()              -> a reply is streaming right now
 *   isPaused() / setPaused(bool)
 *   reorder(ids)          -> apply a new queue order
 *   update(id, patch)     -> {message, mode, model, endpointUrl, endpointId}
 *   remove(id)
 *   startNow(id)          -> force this one ahead of the rest
 *   stopRun(id)           -> stop a launched run
 *   runSequential()       -> drain into this chat, one at a time
 *   runParallel()         -> a session per item, all at once
 *   isStreamLive(sid)     -> is a stream still attached to that session
 */
export function init(driver) {
  _driver = driver || null;
  _els = collectEls();
  if (!_els || !_els.root) return false;
  _els.chevron.innerHTML = ICON_CHEVRON;
  _els.icon.innerHTML = ICON_QUEUE;
  wire();
  render();
  return true;
}

const queuePanel = {
  init,
  refresh,
  render,
  promptRunMode,
  noteLaunched,
  noteLaunchResult,
  refreshLaunched,
  launchedById,
  sweepLaunched,
  statusClass,
  statusLabel,
};

export default queuePanel;
window.queuePanelModule = queuePanel;
