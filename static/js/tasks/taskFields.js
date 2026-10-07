// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The task form — `P22-03`. One form, used twice.
 *
 * `_showForm` and `_saveTaskForm` lived inside `static/js/tasks.js` as a
 * 700-line closure that wrote into the Tasks window's `.modal-body` and nowhere
 * else. The Workbench's side panel (`P22-02`) needs the same form for a node,
 * and a second copy of it is how the two would drift — a field added to one and
 * not the other, a validation message in one and not the other (`Law 7`). So it
 * moved here, once, with what it needs, and both places mount it:
 *
 *   export function mountTaskFields(host, { task, tasks, onSaved, onCancel, mode }) → { destroy() }
 *     host     an element; the form renders INTO it and owns its children
 *              until `destroy()`.
 *     task     a row exactly as `GET /api/tasks` serves it, or `null` for a new
 *              task. A row with no `id` is a draft: the form is filled from it
 *              and Save creates (the Add tab's presets and *Draft with AI*).
 *     tasks    the full list from the same response; the chain pickers read it.
 *     onSaved  called with the saved row — the POST/PUT response — after a
 *              successful save.
 *     onCancel called when the person cancels.
 *     mode     `P22-05` (wf-ui): `'task'` (the default — the form above, byte
 *              for byte), `'node'` or `'trigger'`; see `mountTaskFields`.
 *
 * **What changed in the move, and only this** (it is a move, not a rewrite —
 * the ids, `CHAIN_FIELDS`, the validation messages and the payload are the
 * ones that shipped):
 *
 *   * Every field is found **inside `host`**, not with `document.getElementById`.
 *     The two places that mount this can be open at once — the Tasks window and
 *     the Workbench are both windows — and the ids are the same in both, so a
 *     document-wide lookup would make one form's Save read the other form's
 *     fields: a prompt typed for one task, written into another.
 *   * Cancel and a successful save call the owner's `onCancel` / `onSaved`
 *     instead of switching the Tasks window's tab, which is the Tasks window's
 *     business (`tasks.js` passes exactly that).
 *   * A second mount into the same host replaces the first, and a form that has
 *     been replaced or destroyed stops finding anything, so a fetch that lands
 *     late cannot fill the next task's form with this one's values.
 *
 * The action palette (`/meta/actions`) is fetched here because the form is the
 * thing that needs every field of it; `tasks.js` imports the same fetch and the
 * same cache for its list, so there is one palette in the browser, not two.
 */

import uiModule from '../ui.js';
import { sortModelIds } from '../modelSort.js';
import { getSettings, invalidateSettings } from '../appConfig.js';
import { EDGE_WORDS, EDGE_COLUMNS, KIND_WORDS } from './workflowDiagram.js';

const API_BASE = window.location.origin;

/** The one escaper (`B611`), as `tasks.js` spells it: `ui.js:esc`, with
 *  `String(...)` first so a `0` renders as `0`. */
function _escHtml(s) {
  return uiModule.esc(String(s == null ? '' : s));
}

/** Find one of this form's fields inside `root` — the form's own host, or the
 *  document for the helpers a test drives on their own. The ids are literal
 *  `task-form-*` strings, so they are safe as a selector as written. */
function _byId(root, id) {
  return root && typeof root.querySelector === 'function' ? root.querySelector('#' + id) : null;
}

export const DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// `B873`. The two branches a task can have, as the form's `<select>` id, the
// payload field, and the condition the wire calls it.
//
// `src/task_scheduler.py:112` is the server's own table —
// `{success: "then_task_id", error: "else_task_id"}` — and the browser's half of
// it is `workflowDiagram.js:EDGE_COLUMNS`, which the Workbench's canvas writes
// an edge with. `B1045`: this spelled the same pairing a second time; it reads
// the columns from there now, so the form's save and the canvas's write cannot
// disagree about which column a condition lives in (`Law 7`). What is this
// table's own is the select each condition has in the form. Read by the
// markup, the populate loop and the save.
export const CHAIN_FIELDS = [
  ['task-form-chain', EDGE_COLUMNS.success, 'success'],
  ['task-form-chain-else', EDGE_COLUMNS.error, 'error'],
];

/**
 * What a branch is called in front of a person: the diagram's own words.
 *
 * `workflowDiagram.js:EDGE_WORDS` maps the wire's `success`/`error` onto
 * `if it works` / `if it fails`, and `P8-34` already draws those on the
 * arrows. The form says the same two things, capitalised, so the control that
 * makes an edge and the arrow it draws are not two vocabularies (`Law 14`).
 */
export function _edgeWhenLabel(when) {
  const word = EDGE_WORDS[when] || String(when || '');
  return word.charAt(0).toUpperCase() + word.slice(1);
}

// ---- API ----

/**
 * `P22-03`. The reason the server gave for refusing a save, or `fallback`.
 *
 * Both writes threw one fixed sentence whatever the server said, so a refusal
 * that names its cause — a time zone this machine does not know, a chain that
 * would loop (`P22-01`'s sentence names both tasks) — reached the person as
 * *"Failed to update task"*. `_runNow` in `tasks.js` already reads `detail`
 * this way. FastAPI's own 422 carries a list of objects rather than a sentence;
 * that is not something to show a person, so it keeps the fallback.
 */
async function _refusal(res, fallback) {
  try {
    const data = await res.json();
    if (data && typeof data.detail === 'string' && data.detail.trim()) return data.detail;
  } catch (_) {}
  return fallback;
}

async function _createTask(data) {
  const res = await fetch(`${API_BASE}/api/tasks`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await _refusal(res, 'Failed to create task'));
  return await res.json();
}

async function _updateTask(id, data) {
  const res = await fetch(`${API_BASE}/api/tasks/${id}`, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await _refusal(res, 'Failed to update task'));
  return await res.json();
}

let _outputTargets = null;
async function _fetchOutputTargets() {
  if (_outputTargets) return _outputTargets;
  try {
    const res = await fetch(`${API_BASE}/api/tasks/meta/output-targets`, { credentials: 'same-origin' });
    const data = await res.json();
    _outputTargets = data.targets || [];
  } catch (e) {
    _outputTargets = [{ value: 'session', label: 'Chat' }];
  }
  return _outputTargets;
}

// `P8-22`. `/meta/actions` returns whole palette nodes now — `category`, `icon`,
// `model_backed`, `admin_only` and `params` beside the `name` and `description`
// it always carried — plus `categories` (the group order) and
// `default_trigger_count`. This file used to keep its own copies of the first
// three and its own eleven-name order, so adding an action needed an edit on
// both sides of the wire and `model_backed` was a second list of a fact the
// scheduler already held. There is one list now and it is the server's.
export let _builtinActions = null;
let _actionByName = new Map();
let _actionCategories = null;
let _servedTriggerCount = null;

export async function _fetchActions() {
  if (_builtinActions) return _builtinActions;
  try {
    const res = await fetch(`${API_BASE}/api/tasks/meta/actions`, { credentials: 'same-origin' });
    const data = await res.json();
    _builtinActions = data.actions || [];
    if (Array.isArray(data.categories) && data.categories.length) {
      _actionCategories = data.categories.slice();
    }
    if (Number.isFinite(data.default_trigger_count)) {
      _servedTriggerCount = data.default_trigger_count;
    }
  } catch (e) {
    _builtinActions = [];
  }
  _actionByName = new Map((_builtinActions || []).map(a => [a.name, a]));
  return _builtinActions;
}

/** The palette node for an action name, or `null` before the fetch lands. */
export function _actionNode(name) {
  return (name && _actionByName.get(name)) || null;
}

/** Group order, as served. `[]` before the fetch: `indexOf` then answers -1 for
 *  every name, which sorts them together instead of inventing an order this
 *  file would have to keep in step with the server's. The list re-renders when
 *  the palette arrives. */
export function _categoryOrder() {
  return _actionCategories || [];
}

/**
 * `P8-22`. What an action's single parameter is, and what is currently typed
 * into it — `null` for an action that takes none.
 *
 * A function rather than four lines inside the save handler, because the save
 * handler is a 145-line closure nothing can call: a mutation that stops reading
 * the box survives every assertion made about that handler's source text and
 * dies here (`Law 20` — call the thing).
 *
 * `root` is the form's own host when the form calls it (`P22-03`); the
 * document is the default for a caller with no form of its own.
 */
function _actionPromptValue(action, root = document) {
  const param = _actionNode(action)?.params?.[0];
  if (!param) return null;
  const el = _byId(root, 'task-form-action-param');
  return { param, value: String((el && el.value) || '').trim() };
}

/**
 * `P8-31`. The count an event-triggered task fires on when nobody chooses.
 *
 * The form used to write `5` in two places in front of an API that had no
 * opinion and a bus that has always read a missing count as one. The served
 * number is the answer; the `1` here is only what the bus does with a NULL
 * (`task.trigger_count or 1`), used for the window before `/meta/actions`
 * answers, and the field is refreshed when it does.
 */
function _defaultTriggerCount() {
  return Number.isFinite(_servedTriggerCount) && _servedTriggerCount > 0
    ? _servedTriggerCount
    : 1;
}

async function _fetchUrgentEmailSettings() {
  try {
    return await getSettings();
  } catch (e) {
    return { urgent_email_prompt: '' };
  }
}

async function _saveUrgentEmailSettings(prompt) {
  try {
    await fetch('/api/auth/settings', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        urgent_email_prompt: prompt || '',
      }),
    });
  } finally {
    // The shared snapshot still carries the old prompt — drop it so the next
    // read (here or in any other module) sees what was just written. In a
    // `finally` because a request that throws on the way back may still have
    // been applied.
    invalidateSettings();
  }
}

const _EMAIL_ACCOUNT_ACTIONS = new Set([
  'summarize_emails',
  'draft_email_replies',
  'email_auto_translate',
  'extract_email_events',
  'check_email_urgency',
]);

let _emailAccounts = null;
async function _fetchEmailAccountsForTasks() {
  if (_emailAccounts) return _emailAccounts;
  try {
    const res = await fetch(`${API_BASE}/api/email/accounts`, { credentials: 'same-origin' });
    const data = await res.json();
    _emailAccounts = Array.isArray(data.accounts) ? data.accounts : [];
  } catch (e) {
    _emailAccounts = [];
  }
  return _emailAccounts;
}

function _taskPromptConfig(prompt) {
  const raw = (prompt || '').trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    const cfg = {};
    for (const line of raw.split(/\r?\n/)) {
      const idx = line.indexOf('=');
      if (idx <= 0) continue;
      const key = line.slice(0, idx).trim();
      const val = line.slice(idx + 1).trim();
      if (key) cfg[key] = val;
    }
    return cfg;
  }
}

function _parseTaskEmailOutputTarget(output) {
  const raw = String(output || '').trim();
  if (!raw) return { enabled: false, to: '', accountId: '' };
  if (raw === 'email') return { enabled: true, to: '', accountId: '' };
  if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw)) return { enabled: true, to: raw, accountId: '' };
  if (!raw.startsWith('email:')) return { enabled: false, to: '', accountId: '' };
  let payload = raw.slice('email:'.length).trim();
  let accountId = '';
  const marker = '|account=';
  const markerIdx = payload.indexOf(marker);
  if (markerIdx >= 0) {
    accountId = payload.slice(markerIdx + marker.length).trim();
    payload = payload.slice(0, markerIdx).trim();
  }
  return {
    enabled: true,
    to: payload && payload !== 'self' ? payload : '',
    accountId,
  };
}

function _buildTaskEmailOutputTarget(to, accountId) {
  const cleanTo = String(to || '').trim();
  const cleanAccount = String(accountId || '').trim();
  const base = `email:${cleanTo || 'self'}`;
  return cleanAccount ? `${base}|account=${cleanAccount}` : (cleanTo ? base : 'email');
}

async function _renderEmailActionOptions(action, existing, extra) {
  if (!_EMAIL_ACCOUNT_ACTIONS.has(action)) return;
  const accounts = (await _fetchEmailAccountsForTasks()).filter(a => a && a.enabled !== false);
  const cfg = _taskPromptConfig(existing?.prompt || '');
  const current = String(cfg.account_id || cfg.email_account_id || '');
  const options = [
    `<option value="" ${current ? '' : 'selected'}>All accounts</option>`,
    ...accounts.map(a => {
      const id = String(a.id || '');
      const label = a.name || a.from_address || a.imap_user || id.slice(0, 8);
      const suffix = a.is_default ? ' (default)' : '';
      return `<option value="${_escHtml(id)}" ${id === current ? 'selected' : ''}>${_escHtml(label + suffix)}</option>`;
    }),
  ].join('');
  extra.insertAdjacentHTML('afterbegin', `
    <label class="task-form-label">Email account</label>
    <select id="task-form-email-account" class="task-form-input">${options}</select>
  `);
}

let _triggerEvents = null;
async function _fetchEvents() {
  if (_triggerEvents) return _triggerEvents;
  try {
    const res = await fetch(`${API_BASE}/api/tasks/meta/events`, { credentials: 'same-origin' });
    const data = await res.json();
    _triggerEvents = data.events || [];
  } catch (e) {
    _triggerEvents = [];
  }
  return _triggerEvents;
}

/**
 * Fill the trigger picker from `/meta/events` and say what the chosen event is.
 *
 * `P8-30`. The registry carries a `description` per event and the picker put it
 * in the `<option>` label — where a `<select>` shows one option at a time and
 * truncates it, so somebody deciding between "document created" and "document
 * updated" read neither sentence. It goes under the select now, for whatever is
 * currently chosen, and it re-reads on change.
 *
 * Module-level rather than inline in `renderTriggerOpts` for the same reason
 * `_actionPromptValue` is: that builder is a closure inside a closure and
 * nothing can call it, so every claim about it would be a claim about its
 * source text.
 *
 * `B671` / `P22-03`. And what the trigger will carry. `/meta/events` has served
 * a `payload_summary` per event since `P8-23` — *"the document's id and
 * title"* — because somebody choosing a trigger needs to know what they can
 * refer to **before** they write the prompt, and nothing read it. It goes in
 * `#task-form-event-payload`, under the description, and follows the
 * selection the way the description does.
 */
async function _populateEventPicker(selectedName, root = document) {
  // `P22-05` (wf-ui). The sentence a workflow's start says differs from a
  // task's; which form this host holds is the mount's (`_formModes`).
  const mode = _formModes.get(root) || 'task';
  const events = await _fetchEvents();
  const sel = _byId(root, 'task-form-event');
  const desc = _byId(root, 'task-form-event-desc');
  const carries = _byId(root, 'task-form-event-payload');
  if (!sel) return events;
  sel.innerHTML = '';
  for (const ev of events) {
    const opt = document.createElement('option');
    // The VALUE is the stored name and never a label: it goes into
    // `ScheduledTask.trigger_event`, and `FORBIDDEN.md` Part 1 turns on those
    // bytes — a rename disables every task using one.
    opt.value = ev.name;
    // The option leads with English and keeps the sentence the registry wrote;
    // the stored name stays reachable through `title` and through the line
    // below, because it is what a person matches against a log line (`Law 1`).
    opt.textContent = `${_eventLabel(ev.name)} — ${ev.description || ''}`;
    opt.title = ev.name;
    if (selectedName === ev.name) { opt.selected = true; sel.value = ev.name; }
    sel.appendChild(opt);
  }
  const syncEventDesc = () => {
    const chosen = events.find(ev => ev.name === sel.value);
    if (carries) {
      carries.textContent = chosen ? _eventPayloadSentence(chosen, _chosenTaskType(root), mode) : '';
    }
    if (!desc) return;
    desc.textContent = chosen
      ? `${chosen.description || ''} Stored as ${chosen.name}.`
      : '';
  };
  sel.addEventListener('change', syncEventDesc);
  syncEventDesc();
  return events;
}

/**
 * `B671`. The sentence that says what a trigger hands the task, from the
 * event's own `payload_summary` — never from a table here, so a ninth event
 * arrives already described.
 *
 * Which task types are handed it was measured, not assumed: only the prompt
 * executor reads the run's trigger (`_execute_llm_task` →
 * `trigger_context_message`); research and the built-in actions do not, and
 * for them the payload is the first line of the run's log and nothing more.
 * Saying "your prompt can refer to it" on an Action task would be a promise the
 * engine does not keep (`Law 10`). An event that declares no payload gets no
 * sentence rather than an empty one.
 */
function _eventPayloadSentence(ev, taskType, mode = 'task') {
  const what = String((ev && ev.payload_summary) || '').trim();
  if (!what) return '';
  // `P22-05` (wf-ui). A workflow's start hands the event to its first step,
  // and only a Prompt step reads it (`P22-07`'s record panel says the same of
  // an Action or Research step), so the sentence says which step is handed it.
  if (mode === 'trigger') {
    return `When it fires, the workflow's first step is handed ${what}. A Prompt step can refer to it; other steps run with their own settings.`;
  }
  if ((taskType || 'llm') === 'llm') {
    return `When it fires, your prompt can refer to ${what}.`;
  }
  return `When it fires, the run's log notes ${what}. Only a Prompt task can refer to that.`;
}

/** Which type the form has chosen, read off the Type toggle in `root`. Two
 *  lookups rather than one descendant selector, which the node harness's DOM
 *  shim does not have. `llm` when there is no toggle — the form's own default. */
function _chosenTaskType(root) {
  const toggle = _byId(root, 'task-form-type-toggle');
  const on = toggle && typeof toggle.querySelector === 'function'
    ? toggle.querySelector('.task-toggle-btn.active') : null;
  return (on && on.dataset && on.dataset.val) || 'llm';
}

/** A stored event name as a sentence opener: `document_updated` → `Document
 *  updated`. `P8-30`. The stored value never changes — `FORBIDDEN.md` Part 1
 *  and `ScheduledTask.trigger_event` both depend on it — so this is a reading
 *  of it and nothing else. */
function _eventLabel(name) {
  const words = String(name || '').replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

export function _localTimeToUtc(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  const uh = String(d.getUTCHours()).padStart(2, '0');
  const um = String(d.getUTCMinutes()).padStart(2, '0');
  return `${uh}:${um}`;
}

// ---- Custom pickers ----
//
// `P22-03`. Each takes the `root` it looks in — the form's own host when the
// form calls it — for the reason in this file's header: two forms on one page
// share these ids.

function _buildTimePicker(containerId, hour, minute, root = document) {
  const wrap = _byId(root, containerId);
  if (!wrap) return;
  wrap.innerHTML = '';

  const hourSel = document.createElement('select');
  hourSel.className = 'task-form-input task-time-select';
  hourSel.id = containerId + '-hour';
  for (let h = 0; h < 24; h++) {
    const opt = document.createElement('option');
    opt.value = h;
    opt.textContent = String(h).padStart(2, '0');
    if (h === hour) opt.selected = true;
    hourSel.appendChild(opt);
  }

  const sep = document.createElement('span');
  sep.className = 'task-time-sep';
  sep.textContent = ':';

  const minSel = document.createElement('select');
  minSel.className = 'task-form-input task-time-select';
  minSel.id = containerId + '-min';
  for (let m = 0; m < 60; m += 5) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = String(m).padStart(2, '0');
    if (m === minute || (m <= minute && m + 5 > minute)) opt.selected = true;
    minSel.appendChild(opt);
  }

  wrap.appendChild(hourSel);
  wrap.appendChild(sep);
  wrap.appendChild(minSel);
}

function _getTimePickerValue(containerId, root = document) {
  const h = parseInt(_byId(root, containerId + '-hour')?.value ?? '9', 10);
  const m = parseInt(_byId(root, containerId + '-min')?.value ?? '0', 10);
  return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}

function _buildDatePicker(containerId, initialDate, root = document) {
  const wrap = _byId(root, containerId);
  if (!wrap) return;
  wrap.innerHTML = '';

  const now = initialDate || new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const day = now.getDate();

  // Year select
  const yearSel = document.createElement('select');
  yearSel.className = 'task-form-input task-date-select';
  yearSel.id = containerId + '-year';
  for (let y = year; y <= year + 2; y++) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    if (y === year) opt.selected = true;
    yearSel.appendChild(opt);
  }

  // Month select
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const monthSel = document.createElement('select');
  monthSel.className = 'task-form-input task-date-select';
  monthSel.id = containerId + '-month';
  MONTHS.forEach((name, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = name;
    if (i === month) opt.selected = true;
    monthSel.appendChild(opt);
  });

  // Day select
  const daySel = document.createElement('select');
  daySel.className = 'task-form-input task-date-select';
  daySel.id = containerId + '-day';
  function populateDays() {
    const y = parseInt(yearSel.value, 10);
    const m = parseInt(monthSel.value, 10);
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const cur = parseInt(daySel.value, 10) || day;
    daySel.innerHTML = '';
    for (let d = 1; d <= daysInMonth; d++) {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = String(d).padStart(2, '0');
      if (d === Math.min(cur, daysInMonth)) opt.selected = true;
      daySel.appendChild(opt);
    }
  }
  populateDays();
  yearSel.addEventListener('change', populateDays);
  monthSel.addEventListener('change', populateDays);

  wrap.appendChild(yearSel);
  wrap.appendChild(monthSel);
  wrap.appendChild(daySel);
}

function _getDatePickerValue(containerId, root = document) {
  const y = parseInt(_byId(root, containerId + '-year')?.value, 10);
  const m = parseInt(_byId(root, containerId + '-month')?.value, 10);
  const d = parseInt(_byId(root, containerId + '-day')?.value, 10);
  return new Date(y, m, d);
}

// ---- Time zone, retries, time limit (`P22-03`, folding `B802`'s third part) ----
//
// `P8-32` put `tz_name`, `max_retries` and `timeout_seconds` on `TaskCreate`,
// `TaskUpdate` and `_task_to_dict`, validated on create and edit, and shipped
// no input for any of them. All three are optional and mean "no opinion" when
// blank, which is what every task already stored means.
//
// **What a zone changes about the time box, measured against the server.**
// `compute_next_run` reads `scheduled_time` as wall-clock time IN the task's
// zone when it has one, and as UTC when it has none. This form has always shown
// the time on the browser's clock and converted it to UTC on the way out
// (`_localTimeToUtc`). Keeping that conversion with a zone set would store
// "09:00 Sydney" as 09:00-in-London-converted-to-UTC and run it at the wrong
// hour every day — so with a zone the time goes out exactly as typed and comes
// back exactly as stored, and without one nothing changes (`Law 1`).

/** The bounds `_validate_execution_settings` (`routes/task/task_routes.py`)
 *  enforces, from `MIN_TASK_TIMEOUT_SECONDS` / `MAX_TASK_TIMEOUT_SECONDS` and
 *  the `0 <= max_retries <= 10` check. Repeated here only so the person is told
 *  in words before the request rather than handed the API's field names after
 *  it; the server stays the judge, and its refusal is shown if they disagree. */
const _TIMEOUT_MIN_SECONDS = 30;
const _TIMEOUT_MAX_SECONDS = 24 * 60 * 60;
const _RETRIES_MAX = 10;

/** The browser's own zone, or `''` if it will not say. */
function _browserZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) { return ''; }
}

/** Whether this browser can draw a time in `zone`. Python's `zoneinfo` decides
 *  which zones the server accepts; a browser whose ICU predates a zone must not
 *  throw while drawing a card for it. */
export function _zoneDrawable(zone) {
  if (!zone) return false;
  try { new Intl.DateTimeFormat('en-US', { timeZone: zone }); return true; } catch (_) { return false; }
}

/** The place in a zone name, as a person says it: `Australia/Sydney` →
 *  `Sydney`, `America/Argentina/Buenos_Aires` → `Buenos Aires`. A zone with no
 *  place in it (`UTC`) is itself. */
export function _zonePlace(zone) {
  const name = String(zone || '').trim();
  if (!name.includes('/')) return name;
  return name.slice(name.lastIndexOf('/') + 1).replace(/_/g, ' ');
}

/** Every zone the form offers: none, this browser's, then the IANA list the
 *  browser knows, with the task's own kept even if the browser does not list
 *  it (an alias `zoneinfo` accepts) — the same rule the model dropdown follows
 *  for an unlisted model. */
function _zoneChoices(current) {
  let listed = [];
  try {
    if (typeof Intl.supportedValuesOf === 'function') listed = Intl.supportedValuesOf('timeZone');
  } catch (_) { listed = []; }
  const here = _browserZone();
  const seen = new Set();
  const out = [{ value: '', label: 'Not set' }];
  const add = (value, label) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    out.push({ value, label: label || value });
  };
  if (current) add(current);
  if (here) add(here, `${here} (this browser)`);
  add('UTC');
  for (const zone of listed) add(zone);
  return out;
}

/** The wall clock in `zone` at the instant `ms`. */
function _wallClockIn(zone, ms) {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: zone, hourCycle: 'h23', year: 'numeric', month: 'numeric',
    day: 'numeric', hour: 'numeric', minute: 'numeric',
  });
  const p = {};
  for (const part of fmt.formatToParts(new Date(ms))) p[part.type] = part.value;
  return { y: +p.year, mo: +p.month - 1, d: +p.day, h: +p.hour % 24, mi: +p.minute };
}

/** The instant at which the clock in `zone` reads `y-mo-d h:mi`. `Once` is the
 *  one schedule `compute_next_run` takes as an absolute instant rather than a
 *  wall-clock time, so a one-off "09:00 Sydney" has to be turned into that
 *  instant here. Two corrections cover a daylight-saving edge. */
function _instantOfWallClock(zone, y, mo, d, h, mi) {
  const want = Date.UTC(y, mo, d, h, mi);
  let guess = want;
  for (let i = 0; i < 2; i += 1) {
    const w = _wallClockIn(zone, guess);
    guess += want - Date.UTC(w.y, w.mo, w.d, w.h, w.mi);
  }
  return new Date(guess);
}

/** What the zone means for the time above it, in words. */
function _zoneNote(zone, schedule) {
  const cron = schedule === 'cron';
  if (zone) {
    return cron ? `The cron times are ${_zonePlace(zone)} time.`
      : `The time above is ${_zonePlace(zone)} time.`;
  }
  return cron ? 'Not set: the cron times are UTC.'
    : 'Not set: the time is read on this browser’s clock and kept in UTC, so it will not move for daylight saving.';
}

/** A stored time limit as a number and a unit the box can show. */
function _timeLimitParts(seconds) {
  const s = Number(seconds) || 0;
  if (s <= 0) return { amount: '', unit: 60 };
  if (s % 3600 === 0) return { amount: String(s / 3600), unit: 3600 };
  if (s % 60 === 0) return { amount: String(s / 60), unit: 60 };
  return { amount: String(s), unit: 1 };
}

/** The retry box, read: `{ value }` or `{ error }`. Blank is no retries. */
function _readRetries(root) {
  const raw = String(_byId(root, 'task-form-retries')?.value ?? '').trim();
  if (!raw) return { value: 0 };
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0 || n > _RETRIES_MAX) {
    return { error: `Retries must be a whole number from 0 to ${_RETRIES_MAX}` };
  }
  return { value: n };
}

/** The time-limit box and its unit, read: `{ value }` in seconds, or
 *  `{ error }`. Blank or 0 is no limit, which is what `0` means on the wire. */
function _readTimeLimit(root) {
  const raw = String(_byId(root, 'task-form-timeout')?.value ?? '').trim();
  if (!raw) return { value: 0 };
  const amount = Number(raw);
  const unit = Number(_byId(root, 'task-form-timeout-unit')?.value || 1) || 1;
  if (!Number.isFinite(amount) || amount < 0) {
    return { error: 'The time limit must be a number' };
  }
  const seconds = Math.round(amount * unit);
  if (seconds === 0) return { value: 0 };
  if (seconds < _TIMEOUT_MIN_SECONDS || seconds > _TIMEOUT_MAX_SECONDS) {
    return { error: 'The time limit must be between 30 seconds and 24 hours' };
  }
  return { value: seconds };
}

/** `openTasks` refetches the three served lists each time the window opens, so
 *  a palette, an event or a delivery target added since is offered. They live
 *  here now, so the reset does too. */
export function resetTaskFieldCaches() {
  _outputTargets = null;
  _builtinActions = null;
  _triggerEvents = null;
}

/** The forms mounted right now, by host — so a second mount into the same host
 *  retires the first, and a retired form's late fetches find nothing. */
const _mounted = new WeakMap();
/** `P22-05` (wf-ui). Each host's form mode (`'task'`, `'node'`, `'trigger'`). */
const _formModes = new WeakMap();

// ---- Form ----

/**
 * The task form, rendered into `host`. The contract is in this file's header
 * and in `/work/notes/P22-WAVE-A.md`; `tasks.js`'s `_showForm` and the
 * Workbench's side panel both call exactly this.
 *
 * The body below is `_showForm` as it shipped, moved: the markup, the ids, the
 * nested renderers and the save are the same text, with `document.getElementById`
 * replaced by `$` (this form's own host) and the two tab switches replaced by
 * the owner's callbacks.
 */
export function mountTaskFields(host, {
  task = null, tasks = [], onSaved = null, onCancel = null, mode = 'task',
  slots = null, pickField = null, extra = null, problem = null,
} = {}) {
  if (!host) return { destroy() {} };
  // `P22-05` (wf-ui). Which form: see the sections below. Anything else is the
  // task form, so a caller that passes nothing gets what it always got.
  const isNode = mode === 'node';
  const isTrigger = mode === 'trigger';
  _formModes.set(host, isNode || isTrigger ? mode : 'task');
  const previous = _mounted.get(host);
  if (previous) previous.destroy();
  let alive = true;
  // Inside this form's host, and nothing at all once it is retired: a model
  // list or an action palette that lands after the person has moved on must not
  // write into whatever this host shows next.
  const $ = (id) => (alive ? _byId(host, id) : null);
  // A row with no `id` is a draft — prefilled, and created on save.
  const existing = task || null;

  const curTaskType = existing?.task_type || 'llm';
  const curTriggerType = existing?.trigger_type || 'schedule';

  // `P22-05` (wf-ui). One form, three uses (`Law 7`): the 180 lines of a
  // type's fields — prompt and persona, the action's parameter box drawn from
  // its `params`, the e-mail accounts, the output targets — and their
  // validation messages exist once, here, and a workflow's step panel is this
  // form with a `mode` rather than a second form that would drift from it (the
  // `P22-03` incident). The markup below is the form as it shipped, cut into
  // its sections; `'task'` puts every section back, in order, so the Tasks
  // window and the tasks canvas get the same string they always did.
  //
  //   'task'    — the form, unchanged.
  //   'node'    — a workflow document's step: the kind is locked (chosen in the
  //               palette); Trigger, Chain, Time limit and Notifications are
  //               the workflow's, not a step's, and are not drawn; Output's
  //               first choice is "Only hand it to the next step"; the button
  //               is Done, and it calls `onSaved({ label, kind, config })`
  //               WITHOUT a request — the step lives in the workflow's draft
  //               until the workflow is saved. `task` is the step in the task
  //               form's field names: `{ name: label, task_type: kind, ...config }`.
  //   'trigger' — a workflow's start: the Trigger section, Time limit and
  //               Notifications only, saved by `PUT /api/tasks/{id}` with none
  //               of task_type, output, model, chain or prompt.
  //
  // `P22-09`/`P22-16` (wf-canvas) — three hooks, read in `'node'` mode only,
  // so the other two draw what they always drew:
  //   `slots`     — the palette's slots for this kind (`{ field: { mapping,
  //                 why } }`, C-W); which of the step's text boxes may take a
  //                 field from an earlier step is the server's answer.
  //   `pickField(input, { field, slot })` — the room's decorator
  //                 (`workbench/fieldPicker.js:decorateField`), handed each
  //                 text box the step stores (`prompt`): *Insert a field…* on a
  //                 `value` one, the reason on a `never` one. This file draws
  //                 neither and imports neither — a sandbox that loads the task
  //                 form needs nothing new.
  //   `extra(el)` — a section of the caller's under the step's fields (a
  //                 Prompt step's tools and answer shape), whose `read()` adds
  //                 its keys to Done's config, or refuses.
  //   `problem`   — the draft's refusal naming this step (`{ sentence, field }`),
  //                 said on that field.
  // `P23-05` (WB-U-2, WB-U-12, Doc 2 § 5): one noun — *task* — and a lede only
  // where the heading cannot carry it. A step's kind is the subtitle (its
  // locked one-button toggle below is kept, out of sight, as the form's read
  // of the kind).
  const heading = isNode ? 'Edit step' : isTrigger ? 'What starts it'
    : (existing?.id ? 'Edit task' : 'New task');
  const lede = isNode
    ? `${_escHtml(KIND_WORDS[curTaskType] || 'Prompt')} step. Done here, then Save above.`
    : isTrigger ? 'When it runs.' : '';
  const namePlaceholder = isNode ? _escHtml(KIND_WORDS[curTaskType] || 'Step') : (existing?.id ? '' : 'Auto-generated if blank');
  const saveWord = isNode ? 'Done' : isTrigger ? 'Save' : (existing?.id ? 'Save' : 'Create');
  const sections = {
    head: `
    <div class="admin-card" style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
      <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:2px;">
        <h2 style="margin:0;padding:0;line-height:1;">${heading}</h2>
      </div>
      ${lede ? `<p class="memory-desc">${lede}</p>` : ''}
    <div class="task-form" style="flex:1;overflow-y:auto;min-height:0;">`,
    name: `
      <label class="task-form-label">Name</label>
      <input type="text" id="task-form-name" class="task-form-input" value="${_escHtml(existing?.name || '')}" placeholder="${namePlaceholder}" />
`,
    type: `
      <label class="task-form-label">Type</label>
      <div class="task-form-toggle" id="task-form-type-toggle">
        <button class="task-toggle-btn ${curTaskType === 'llm' ? 'active' : ''}" data-val="llm" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>Prompt</button>
        <button class="task-toggle-btn ${curTaskType === 'research' ? 'active' : ''}" data-val="research" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>Research</button>
        <button class="task-toggle-btn ${curTaskType === 'action' ? 'active' : ''}" data-val="action" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>Action</button>
      </div>

      <div id="task-form-type-opts"></div>
`,
    trigger: `
      <label class="task-form-label">Trigger</label>
      <div class="task-form-toggle" id="task-form-trigger-toggle">
        <button class="task-toggle-btn ${curTriggerType === 'schedule' ? 'active' : ''}" data-val="schedule" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Schedule</button>
        <button class="task-toggle-btn ${curTriggerType === 'event' ? 'active' : ''}" data-val="event" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>Event</button>
        <button class="task-toggle-btn ${curTriggerType === 'webhook' ? 'active' : ''}" data-val="webhook" style="position:relative;top:-4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>Webhook</button>
      </div>

      <div id="task-form-trigger-opts"></div>
`,
    output: `
      <label class="task-form-label">Output</label>
      <select id="task-form-output" class="task-form-input">
        <option value="session">Chat</option>
      </select>
      <div id="task-form-output-extra"></div>
`,
    model: `
      <label class="task-form-label">Model</label>
      <select id="task-form-model" class="task-form-input">
        <option value="">Default</option>
      </select>
`,
    timeout: `
      <label class="task-form-label" for="task-form-timeout">Time limit <span style="opacity:0.5;font-weight:normal;font-size:10px;">(optional — blank for none)</span></label>
      <div class="task-form-timeout-row">
        <input type="number" id="task-form-timeout" class="task-form-input" min="0" step="1" inputmode="numeric" placeholder="No limit" value="${_escHtml(_timeLimitParts(existing?.timeout_seconds).amount)}" />
        <select id="task-form-timeout-unit" class="task-form-input" aria-label="Time limit unit">
          <option value="1" ${_timeLimitParts(existing?.timeout_seconds).unit === 1 ? 'selected' : ''}>seconds</option>
          <option value="60" ${_timeLimitParts(existing?.timeout_seconds).unit === 60 ? 'selected' : ''}>minutes</option>
          <option value="3600" ${_timeLimitParts(existing?.timeout_seconds).unit === 3600 ? 'selected' : ''}>hours</option>
        </select>
      </div>
      <div class="task-form-hint">A run that takes longer than this is stopped and counts as failed.</div>
`,
    chain: `
      <label class="task-form-label">Chain <span style="opacity:0.5;font-weight:normal;font-size:10px;">(optional — what runs after this one)</span></label>
      <div class="task-form-chain">
        <label class="task-form-chain-row">
          <span class="task-form-chain-when">${_escHtml(_edgeWhenLabel('success'))}</span>
          <select id="task-form-chain" class="task-form-input">
            <option value="">None</option>
          </select>
        </label>
        <label class="task-form-chain-row">
          <span class="task-form-chain-when">${_escHtml(_edgeWhenLabel('error'))}</span>
          <select id="task-form-chain-else" class="task-form-input">
            <option value="">None</option>
          </select>
        </label>
      </div>
`,
    notif: `
      <label class="task-form-notif-toggle">
        <input type="checkbox" id="task-form-notif" ${existing && existing.notifications_enabled === false ? '' : 'checked'}>
        <span class="task-form-notif-switch" aria-hidden="true"></span>
        <span class="task-form-notif-copy">
          <span>Notifications</span>
          <span>Silence completion alerts for chatty cron jobs.</span>
        </span>
      </label>
`,
    actions: `
      <div class="task-form-actions">
        <button id="task-form-cancel" class="memory-toolbar-btn"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="vertical-align:-1px;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>Cancel</button>
        <button id="task-form-save" class="memory-toolbar-btn active"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px;"><polyline points="20 6 9 17 4 12"/></svg>${saveWord}</button>
      </div>
    </div>
    </div>
  `,
  };
  if (isNode) {
    // The kind, shown and not chosen: a step's kind is picked in the palette,
    // and a Prompt step's prompt is not an Action's parameter.
    sections.type = `
      <div class="task-form-toggle task-form-toggle-locked" id="task-form-type-toggle" style="display:none">
        <button type="button" class="task-toggle-btn active" data-val="${_escHtml(curTaskType)}" disabled aria-disabled="true">${_escHtml(KIND_WORDS[curTaskType] || curTaskType)}</button>
      </div>

      <div id="task-form-type-opts"></div>
`;
    sections.output = `
      <label class="task-form-label" for="task-form-output">Output</label>
      <select id="task-form-output" class="task-form-input">
        <option value="">Only hand it to the next step</option>
      </select>
      <div id="task-form-output-extra"></div>
`;
  }
  if (isNode) sections.extra = '\n      <div id="task-form-step-extra" class="task-form-step-extra"></div>\n';
  const order = isNode
    ? ['head', 'name', 'type', ...(curTaskType === 'run_task' ? [] : ['output']),
      ...(curTaskType === 'llm' || curTaskType === 'research' ? ['model'] : []),
      ...(typeof extra === 'function' ? ['extra'] : []), 'actions']
    : isTrigger
      ? ['head', 'trigger', 'timeout', 'notif', 'actions']
      : ['head', 'name', 'type', 'trigger', 'output', 'model', 'timeout', 'chain', 'notif', 'actions'];
  host.innerHTML = order.map((k) => sections[k]).join('');

  // --- `P22-09` (wf-canvas): a step's text boxes, told what they may take ---
  const nodeHandles = {};
  const problemField = isNode && problem && problem.field
    ? String(problem.field).replace(/^config\./, '') : '';
  let problemShown = false;
  const _decorate = (el, field) => {
    if (!isNode || !el || typeof pickField !== 'function') return null;
    if (nodeHandles[field]) { try { nodeHandles[field].destroy(); } catch (_) { /* gone */ } }
    const slot = slots && typeof slots === 'object' && slots[field] ? slots[field] : null;
    let h = null;
    try { h = pickField(el, { field, slot }); } catch (_) { h = null; }
    if (h) nodeHandles[field] = h;
    if (h && problemField === field && typeof h.show === 'function') { h.show(problem.sentence); problemShown = true; }
    return h;
  };

  // --- Task type toggle ---
  let taskType = curTaskType;
  const typeToggle = $('task-form-type-toggle');
  const typeOpts = $('task-form-type-opts');

  function renderTypeOpts() {
    if (!typeOpts) return;
    typeOpts.innerHTML = '';
    if (taskType === 'run_task') {
      // `P22-05` (wf-ui). A step that runs one of the person's tasks, as it
      // would run on its own. A workflow is not offered: a step may not run a
      // workflow (§ 8's default), and the server refuses one in words.
      typeOpts.innerHTML = `
        <label class="task-form-label" for="task-form-run-task">Task to run</label>
        <select id="task-form-run-task" class="task-form-input"><option value="">Choose a task…</option></select>
        <div class="task-form-hint">It runs with its own settings and keeps its own history, and what it makes is handed to the next step.</div>
      `;
      const sel = $('task-form-run-task');
      const choices = (Array.isArray(tasks) ? tasks : [])
        .filter((t) => t && t.id != null && t.task_type !== 'workflow')
        .sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
      for (const t of choices) {
        const opt = document.createElement('option');
        opt.value = String(t.id);
        opt.textContent = String(t.name || 'Untitled task');
        if (String(existing?.task_id || '') === String(t.id)) opt.selected = true;
        sel.appendChild(opt);
      }
      return;
    }
    if (taskType === 'llm' || taskType === 'research') {
      const placeholder = taskType === 'research' ? 'What should be researched?' : 'What should the AI do?';
      const _personaOpts = [
        ['', 'Default (no persona)'],
        ['socrates', 'Socrates'],
        ['razor', 'Razor'],
        ['nietzsche', 'Nietzsche'],
        ['spark', 'Spark'],
        ['pantheon', 'Pantheon'],
      ];
      const _curPersona = (existing?.character_id || '').toLowerCase();
      const _personaOptsHtml = _personaOpts.map(([v, label]) =>
        `<option value="${v}" ${v === _curPersona ? 'selected' : ''}>${label}</option>`).join('');
      typeOpts.innerHTML = `
        <label class="task-form-label">${taskType === 'research' ? 'Research question' : 'Prompt'}</label>
        <textarea id="task-form-prompt" class="task-form-input task-form-textarea" rows="4" placeholder="${placeholder}">${_escHtml(existing?.prompt || '')}</textarea>
${(isNode && taskType === 'research') ? '' : `
        <label class="task-form-label">Persona</label>
        <select id="task-form-persona" class="task-form-input">${_personaOptsHtml}</select>`}
      `;
      // `P22-05`. A Research step takes no persona (its config has no
      // `character_id`), so its step form does not offer one; every other
      // use of this form draws the same text it always did.
      _decorate($('task-form-prompt'), 'prompt');
    } else {
      typeOpts.innerHTML = `
        <label class="task-form-label">Action</label>
        <select id="task-form-action" class="task-form-input">
          <option value="">Loading…</option>
        </select>
        <div id="task-form-action-extra"></div>
      `;
      const syncActionExtra = async () => {
        const sel = $('task-form-action');
        const extra = $('task-form-action-extra');
        if (!sel || !extra) return;
        const action = sel.value;
        extra.innerHTML = '';
        // `P8-22`. Four built-ins take an argument and the form had no box for
        // any of them: `ssh_command` wanted a command, `run_script` and
        // `run_local` a script body, `cookbook_serve` a serve config. Picking
        // one in this form produced a task with an empty `prompt`. The schema
        // is on the wire — `label`, `type`, `description` — so the field is
        // drawn from the node instead of from a list of action names this file
        // would have to keep in step with the registry.
        const param = _actionNode(action)?.params?.[0];
        if (param) {
          const isLong = param.type === 'text' || param.type === 'json';
          const box = isLong
            ? `<textarea id="task-form-action-param" class="task-form-input task-form-textarea" rows="4" placeholder="${_escHtml(param.label || '')}"></textarea>`
            : `<input type="text" id="task-form-action-param" class="task-form-input" placeholder="${_escHtml(param.label || '')}" />`;
          extra.insertAdjacentHTML('beforeend', `
            <label class="task-form-label" for="task-form-action-param">${_escHtml(param.label || param.name || 'Argument')}</label>
            ${box}
            <div class="memory-desc" style="font-size:11px;margin-top:4px;">${_escHtml(param.description || '')}</div>
          `);
          // `value` is assigned rather than interpolated: a stored command is
          // arbitrary text and `</textarea>` in it would close the element.
          const paramEl = $('task-form-action-param');
          if (paramEl && existing?.action === action) paramEl.value = existing.prompt || '';
          // `P22-09`. An action's parameter is a command or a host — never
          // filled from another step — and the step's box says so.
          _decorate(paramEl, 'prompt');
        }
        if (!_EMAIL_ACCOUNT_ACTIONS.has(action)) return;
        await _renderEmailActionOptions(action, existing, extra);
        // `P22-05`. The triage rules are the instance's, saved by a request of
        // their own; a step's form makes no request, so they stay where they
        // are set — on the e-mail tagging task — and are not offered here.
        if (action === 'check_email_urgency' && !isNode) {
          extra.insertAdjacentHTML('beforeend', `
            <label class="task-form-label">Email triage rules</label>
            <textarea id="task-form-urgent-email-prompt" class="task-form-input task-form-textarea" rows="4" placeholder="What should count as urgent? e.g. deadlines, blockers, people waiting outside."></textarea>
            <div class="memory-desc" style="font-size:11px;margin-top:4px;">Pause/resume and schedule are controlled by this task. It tags work, personal, urgent, action-needed, finance, legal, travel, newsletter, marketing, spam, and related mail categories. Urgent/reply-soon emails use your reminder settings.</div>
          `);
          const settings = await _fetchUrgentEmailSettings();
          const promptEl = $('task-form-urgent-email-prompt');
          if (promptEl && !promptEl.dataset.loaded) {
            promptEl.value = settings.urgent_email_prompt || '';
            promptEl.dataset.loaded = '1';
          }
          const notifEl = $('task-form-notif');
          if (notifEl && !existing?.id) notifEl.checked = false;
        }
      };
      _fetchActions().then(actions => {
        const sel = $('task-form-action');
        if (!sel) return;
        sel.innerHTML = '';
        for (const a of actions) {
          const opt = document.createElement('option');
          opt.value = a.name;
          opt.textContent = `${a.name} — ${a.description}`;
          if (existing?.action === a.name) opt.selected = true;
          sel.appendChild(opt);
        }
        sel.addEventListener('change', syncActionExtra);
        syncActionExtra();
      });
    }
  }

  if (typeToggle && !isNode) typeToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.task-toggle-btn');
    if (!btn) return;
    taskType = btn.dataset.val;
    typeToggle.querySelectorAll('.task-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.val === taskType));
    renderTypeOpts();
    // `B671`. What an event hands the task depends on the type — only a Prompt
    // is given it — so the sentence under the event picker is read again.
    $('task-form-event')?.dispatchEvent(new Event('change'));
  });
  renderTypeOpts();

  // `P22-16` (wf-canvas). The caller's section under a step's fields.
  let extraView = null;
  if (isNode && typeof extra === 'function' && $('task-form-step-extra')) {
    try { extraView = extra($('task-form-step-extra')); } catch (_) { extraView = null; }
  }
  // The draft's refusal for this step, when no box of the form took it.
  if (isNode && problem && problem.sentence) {
    setTimeout(() => {
      if (problemShown || !alive) return;
      const form = host.querySelector('.task-form');
      if (!form) return;
      const line = document.createElement('p');
      line.className = 'task-form-problem';
      line.setAttribute('role', 'alert');
      line.textContent = String(problem.sentence);
      form.insertBefore(line, form.firstChild);
    }, 0);
  }

  // --- Trigger type toggle ---
  let triggerType = curTriggerType;
  const triggerToggle = $('task-form-trigger-toggle');
  const triggerOpts = $('task-form-trigger-opts');

  function renderTriggerOpts() {
    if (!triggerOpts) return;
    triggerOpts.innerHTML = '';
    if (triggerType === 'schedule') {
      triggerOpts.innerHTML = `
        <label class="task-form-label">Frequency</label>
        <select id="task-form-schedule" class="task-form-input">
          <option value="daily" ${(!existing?.schedule || existing.schedule === 'daily') ? 'selected' : ''}>Daily</option>
          <option value="weekly" ${existing?.schedule === 'weekly' ? 'selected' : ''}>Weekly</option>
          <option value="monthly" ${existing?.schedule === 'monthly' ? 'selected' : ''}>Monthly</option>
          <option value="once" ${existing?.schedule === 'once' ? 'selected' : ''}>Once</option>
          <option value="cron" ${existing?.schedule === 'cron' ? 'selected' : ''}>Cron</option>
        </select>
        <div id="task-form-schedule-opts"></div>
        <div id="task-form-time-section">
          <label class="task-form-label">Time</label>
          <div class="task-time-picker" id="task-form-time-wrap"></div>
        </div>
        <label class="task-form-label" for="task-form-tz">Time zone <span style="opacity:0.5;font-weight:normal;font-size:10px;">(optional)</span></label>
        <select id="task-form-tz" class="task-form-input"></select>
        <div id="task-form-tz-note" class="task-form-hint"></div>
        <label class="task-form-label" for="task-form-retries">Retry a failed run <span style="opacity:0.5;font-weight:normal;font-size:10px;">(optional — up to ${_RETRIES_MAX} times)</span></label>
        <input type="number" id="task-form-retries" class="task-form-input task-form-number" min="0" max="${_RETRIES_MAX}" step="1" inputmode="numeric" placeholder="0" value="${_escHtml(Number(existing?.max_retries) > 0 ? String(existing.max_retries) : '')}" />
        <div class="task-form-hint">After a failure it tries again, this many times at most. Each retry waits about twice as long as the one before.</div>
      `;

      // `P22-03`. The zone, before the time picker is filled: a task with a
      // zone stores its wall-clock time and is shown it as stored.
      const tzSel = $('task-form-tz');
      if (tzSel) {
        for (const choice of _zoneChoices(existing?.tz_name || '')) {
          const opt = document.createElement('option');
          opt.value = choice.value;
          opt.textContent = choice.label;
          if (choice.value === (existing?.tz_name || '')) opt.selected = true;
          tzSel.appendChild(opt);
        }
        tzSel.value = existing?.tz_name || '';
      }
      const storedZone = existing?.tz_name || '';

      // Build time picker
      let initH = 9, initM = 0;
      if (storedZone && existing?.schedule === 'once' && existing.scheduled_date
          && _zoneDrawable(storedZone)) {
        // A one-off is an instant (`compute_next_run` returns `scheduled_date`
        // as it is), so its time is read off that instant on the zone's clock.
        const w = _wallClockIn(storedZone, new Date(existing.scheduled_date).getTime());
        initH = w.h;
        initM = w.mi;
      } else if (existing && existing.scheduled_time) {
        const [uh, um] = existing.scheduled_time.split(':').map(Number);
        if (storedZone) {
          initH = uh;
          initM = um;
        } else {
          const d = new Date();
          d.setUTCHours(uh, um, 0, 0);
          initH = d.getHours();
          initM = d.getMinutes();
        }
      }
      _buildTimePicker('task-form-time-wrap', initH, initM, host);

      const schedSelect = $('task-form-schedule');
      const schedOpts = $('task-form-schedule-opts');
      const syncZoneNote = () => {
        const note = $('task-form-tz-note');
        if (note) note.textContent = _zoneNote($('task-form-tz')?.value || '', schedSelect?.value);
      };
      tzSel?.addEventListener('change', syncZoneNote);

      function updateScheduleOpts() {
        schedOpts.innerHTML = '';
        const sched = schedSelect.value;
        const timeSection = $('task-form-time-section');
        if (timeSection) timeSection.style.display = sched === 'cron' ? 'none' : '';
        syncZoneNote();
        if (sched === 'weekly') {
          const label = document.createElement('label');
          label.className = 'task-form-label';
          label.textContent = 'Day of week';
          schedOpts.appendChild(label);
          const sel = document.createElement('select');
          sel.id = 'task-form-day';
          sel.className = 'task-form-input';
          DAYS_OF_WEEK.forEach((day, i) => {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = day;
            if (existing && existing.scheduled_day === i) opt.selected = true;
            sel.appendChild(opt);
          });
          schedOpts.appendChild(sel);
        } else if (sched === 'monthly') {
          const label = document.createElement('label');
          label.className = 'task-form-label';
          label.textContent = 'Day of month';
          schedOpts.appendChild(label);
          const inp = document.createElement('input');
          inp.type = 'number';
          inp.id = 'task-form-day';
          inp.className = 'task-form-input';
          inp.min = 1; inp.max = 31;
          inp.value = existing?.scheduled_day ?? 1;
          schedOpts.appendChild(inp);
        } else if (sched === 'once') {
          const label = document.createElement('label');
          label.className = 'task-form-label';
          label.textContent = 'Date';
          schedOpts.appendChild(label);
          const dateWrap = document.createElement('div');
          dateWrap.className = 'task-date-picker';
          dateWrap.id = 'task-form-date';
          schedOpts.appendChild(dateWrap);
          // `P22-03`. With a zone, the date is the one on that zone's
          // calendar — 23:30 Sydney on the 3rd is the 3rd, wherever the
          // browser is.
          let initialDate = existing?.scheduled_date ? new Date(existing.scheduled_date) : new Date();
          if (storedZone && existing?.scheduled_date && _zoneDrawable(storedZone)) {
            const w = _wallClockIn(storedZone, initialDate.getTime());
            initialDate = new Date(w.y, w.mo, w.d);
          }
          _buildDatePicker('task-form-date', initialDate, host);
        } else if (sched === 'cron') {
          const label = document.createElement('label');
          label.className = 'task-form-label';
          label.textContent = 'Cron expression';
          schedOpts.appendChild(label);
          const inp = document.createElement('input');
          inp.type = 'text';
          inp.id = 'task-form-cron';
          inp.className = 'task-form-input';
          inp.placeholder = '*/30 * * * *';
          inp.value = existing?.cron_expression || '';
          schedOpts.appendChild(inp);
          const hint = document.createElement('div');
          hint.style.cssText = 'font-size:10px;opacity:0.4;margin-top:2px;';
          hint.textContent = 'min hour day month weekday — e.g. "0 */2 * * *" = every 2 hours';
          schedOpts.appendChild(hint);
        }
      }
      schedSelect.addEventListener('change', updateScheduleOpts);
      updateScheduleOpts();

    } else if (triggerType === 'event') {
      triggerOpts.innerHTML = `
        <label class="task-form-label">Event</label>
        <select id="task-form-event" class="task-form-input">
          <option value="">Loading…</option>
        </select>
        <div id="task-form-event-desc" class="task-form-event-desc"></div>
        <div id="task-form-event-payload" class="task-form-event-payload"></div>
        <label class="task-form-label">Every N occurrences</label>
        <input type="number" id="task-form-trigger-count" class="task-form-input" min="1" max="1000" value="${existing?.trigger_count || _defaultTriggerCount()}" />
      `;
      // `P8-31`. The field used to be pre-filled with a literal 5 — a number
      // nobody chose, in front of an API that had no default and a bus that
      // reads a missing count as one. It reads the served
      // `default_trigger_count` now; this refresh covers the case where the
      // palette has not landed yet, and stops the moment the person types.
      const countEl = $('task-form-trigger-count');
      if (countEl) {
        countEl.addEventListener('input', () => { countEl.dataset.touched = '1'; });
        if (!existing?.trigger_count) {
          _fetchActions().then(() => {
            if (!countEl.dataset.touched) countEl.value = String(_defaultTriggerCount());
          });
        }
      }
      _populateEventPicker(existing?.trigger_event, host);
    } else if (triggerType === 'webhook') {
      if (existing?.webhook_token) {
        const url = `${API_BASE}/api/tasks/${existing.id}/webhook/${existing.webhook_token}`;
        // `H17(b)`. This URL carries its own bearer token in the path and the
        // label says "No auth needed" — which is accurate and is exactly why
        // the missing control mattered. `POST /api/tasks/{id}/webhook-regenerate`
        // rotates the token and had **no caller anywhere**, so if the URL leaked
        // — a pasted screenshot, a shared CI log, a copied support ticket —
        // there was no revocation path in the product at all. A secret you can
        // copy but cannot rotate is a secret with no lifecycle.
        triggerOpts.innerHTML = `
          <label class="task-form-label">Webhook URL</label>
          <div style="display:flex;gap:4px;align-items:center;">
            <input type="text" class="task-form-input" value="${url}" readonly style="flex:1;font-size:11px;opacity:0.8;" id="task-form-webhook-url" />
            <button class="task-btn" id="task-form-webhook-copy" style="white-space:nowrap;">Copy</button>
            <button class="task-btn" id="task-form-webhook-rotate" style="white-space:nowrap;" title="Issue a new token. The current URL stops working immediately.">Rotate</button>
          </div>
          <div style="font-size:10px;opacity:0.4;margin-top:4px;">POST this URL from any external service to trigger the task. Anyone holding it can run the task — rotate if it leaks.</div>
        `;
        $('task-form-webhook-copy')?.addEventListener('click', async () => {
          // `B59`. Was `navigator.clipboard.writeText(url)` followed
          // unconditionally by `showToast('Copied')`. Over plain http on a LAN
          // `navigator.clipboard` is `undefined`, so that threw, copied
          // nothing — **and still said Copied**, about a URL that lets anyone
          // holding it trigger this task. The line above it in this same
          // template warns to rotate it if it leaks; the button below was
          // telling people it was safely on their clipboard when it was not.
          // `copied`, not `ok`: `test_the_webhook_token_can_be_rotated` scans a
          // window around `webhook-regenerate` for `const ok = …` and requires
          // it to be the rotation's `confirm(...)` and nothing else — a guard
          // against `const ok = true || confirm(...)`, which is a mutation that
          // survived its first version. A second `ok` in that window is caught
          // by the same rule, correctly, and the test is not the thing to bend.
          const copied = await uiModule.copyText(url);
          if (uiModule) uiModule.showToast(copied ? 'Copied' : 'Copy failed');
        });
        $('task-form-webhook-rotate')?.addEventListener('click', async () => {
          // Confirmed, because it is irreversible for anything already using
          // the old URL — which is the point of it, and still a surprise if
          // nobody said so.
          const ok = window.confirm(
            'Issue a new webhook token?\n\nThe current URL stops working immediately. '
            + 'Anything already using it will need the new one.');
          if (!ok) return;
          try {
            const res = await fetch(`${API_BASE}/api/tasks/${existing.id}/webhook-regenerate`,
                                    { method: 'POST', credentials: 'same-origin' });
            const data = await res.json();
            if (!res.ok || !data.webhook_token) {
              if (uiModule) uiModule.showError('Could not rotate the token. The old URL still works.');
              return;
            }
            existing.webhook_token = data.webhook_token;
            renderTriggerOpts();
            if (uiModule) uiModule.showToast('New webhook URL issued');
          } catch (e) {
            if (uiModule) uiModule.showError('Could not reach Pantheon. The old URL still works.');
          }
        });
      } else {
        triggerOpts.innerHTML = '<div style="font-size:11px;opacity:0.5;margin-top:4px;">Webhook URL will be generated when the task is saved.</div>';
      }
    }
  }

  if (triggerToggle) triggerToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.task-toggle-btn');
    if (!btn) return;
    triggerType = btn.dataset.val;
    triggerToggle.querySelectorAll('.task-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.val === triggerType));
    renderTriggerOpts();
  });
  renderTriggerOpts();

  // `P22-05`. Whether the served lists have arrived: a step's Done before they
  // do keeps what the step had rather than reading the placeholder.
  let _outputsLoaded = false;
  let _modelsLoaded = false;

  // Populate output targets
  const renderOutputExtra = async () => {
    const outputSel = $('task-form-output');
    const extra = $('task-form-output-extra');
    if (!outputSel || !extra) return;
    const currentTo = $('task-form-output-email-to')?.value;
    const currentAccountId = $('task-form-output-email-account')?.value;
    extra.innerHTML = '';
    if (outputSel.value !== 'email') return;
    const parsed = _parseTaskEmailOutputTarget(existing?.output_target || '');
    if (currentTo != null) parsed.to = currentTo;
    if (currentAccountId != null) parsed.accountId = currentAccountId;
    const accounts = (await _fetchEmailAccountsForTasks()).filter(a => a && a.enabled !== false);
    const options = [
      `<option value="" ${parsed.accountId ? '' : 'selected'}>Default sending account</option>`,
      ...accounts.map(a => {
        const id = String(a.id || '');
        const label = a.name || a.from_address || a.imap_user || id.slice(0, 8);
        const suffix = a.is_default ? ' (default)' : '';
        return `<option value="${_escHtml(id)}" ${id === parsed.accountId ? 'selected' : ''}>${_escHtml(label + suffix)}</option>`;
      }),
    ].join('');
    extra.innerHTML = `
      <div class="task-form-output-email" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:6px;">
        <label>
          <span class="task-form-label" style="margin-top:0;">From</span>
          <select id="task-form-output-email-account" class="task-form-input">${options}</select>
        </label>
        <label>
          <span class="task-form-label" style="margin-top:0;">To</span>
          <input id="task-form-output-email-to" class="task-form-input" type="email" value="${_escHtml(parsed.to)}" placeholder="Me / selected account" />
        </label>
      </div>
      <div class="memory-desc" style="font-size:10px;margin-top:3px;">Leave To blank to send to the selected account’s own address.</div>
    `;
  };

  if ($('task-form-output')) _fetchOutputTargets().then(targets => {
    const outputSel = $('task-form-output');
    if (outputSel) _outputsLoaded = true;
    if (!outputSel || (targets.length <= 1 && !isNode)) return;
    outputSel.innerHTML = '';
    if (isNode) {
      // `P22-05`. A step's result goes to the next step whatever this says;
      // a target is somewhere it is ALSO delivered. Nothing is the default
      // for a new step (§ 1.2: `output_target: null`).
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Only hand it to the next step';
      if (!existing?.output_target) opt.selected = true;
      outputSel.appendChild(opt);
    }
    const existingEmailOutput = _parseTaskEmailOutputTarget(existing?.output_target || '');
    let matchedOutput = false;
    for (const t of targets) {
      const opt = document.createElement('option');
      opt.value = t.value;
      opt.textContent = t.label;
      if (existingEmailOutput.enabled && t.value === 'email') {
        opt.selected = true;
        matchedOutput = true;
      } else if (!existingEmailOutput.enabled && existing?.output_target === t.value) {
        opt.selected = true;
        matchedOutput = true;
      }
      outputSel.appendChild(opt);
    }
    if (existing?.output_target && !matchedOutput && !existingEmailOutput.enabled) {
      const opt = document.createElement('option');
      opt.value = existing.output_target;
      opt.textContent = existing.output_target.includes('@') ? `Email: ${existing.output_target}` : existing.output_target;
      opt.selected = true;
      outputSel.appendChild(opt);
    }
    outputSel.addEventListener('change', renderOutputExtra);
    renderOutputExtra();
  });

  // Populate model dropdown from /api/models. Value is "endpoint_url::model"
  // so a single field encodes both the model name and which endpoint to call.
  // Blank value (option 0) = inherit session default.
  if ($('task-form-model')) fetch(`${API_BASE}/api/models`, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(data => {
      const modelSel = $('task-form-model');
      if (!modelSel) return;
      _modelsLoaded = true;
      const items = (data.items || []).filter(it => (it.model_type || 'llm') === 'llm');
      const curKey = existing?.endpoint_url && existing?.model
        ? `${existing.endpoint_url}::${existing.model}`
        : '';
      for (const it of items) {
        if (it.offline || !it.models || it.models.length === 0) continue;
        const group = document.createElement('optgroup');
        group.label = it.endpoint_name || it.host || 'endpoint';
        const all = sortModelIds([...(it.models || []), ...(it.models_extra || [])]);
        for (const m of all) {
          const opt = document.createElement('option');
          opt.value = `${it.url}::${m}`;
          opt.textContent = m;
          if (opt.value === curKey) opt.selected = true;
          group.appendChild(opt);
        }
        modelSel.appendChild(group);
      }
      // Preserve a previously-set pairing even if /api/models doesn't list it
      // anymore (e.g. endpoint disabled). Shows so the user knows it's set.
      if (curKey && modelSel.value !== curKey) {
        const opt = document.createElement('option');
        opt.value = curKey;
        opt.textContent = `${existing.model} (unlisted endpoint)`;
        opt.selected = true;
        modelSel.appendChild(opt);
      }
    })
    .catch(() => {});

  // Populate both chain dropdowns.
  //
  // `B873`. There was one, and it was `then_task_id`. `P8-28` gave the engine
  // the failure edge, `task_edges` stores it, `_task_to_dict` puts it on every
  // row and `P8-34`'s diagram draws it as the dotted arrow — and the only ways
  // to create one were the API and the agent. One loop over the two, rather
  // than a copy of the block with the other field name in it: two copies is
  // how the first one ended up with no second (`Law 13`).
  for (const [selectId, field] of CHAIN_FIELDS) {
    const sel = $(selectId);
    if (!sel) continue;
    const otherTasks = (Array.isArray(tasks) ? tasks : []).filter(t => !existing || t.id !== existing.id);
    for (const t of otherTasks) {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.name;
      if (existing?.[field] === t.id) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  // Cancel — the owner decides where that goes. The Tasks window returns to its
  // Tasks tab (keeping the active-tab highlight in sync); the Workbench closes
  // its panel. Esc is the owner's too: the Tasks window's Esc goes back to the
  // Add tab's presets, which means nothing in a side panel (`tasks.js:_showForm`).
  $('task-form-cancel').addEventListener('click', () => {
    if (typeof onCancel === 'function') onCancel();
  });

  // `P22-05` (wf-ui). A step's Done: what the form holds, as the step, and NO
  // request — the step lives in the workflow's draft until the workflow's own
  // Save. The config holds § 1.2's keys for the kind and nothing else, so the
  // server's check reads exactly what a step may carry; a value the form draws
  // no input for (a Prompt step's crew member and step limit) is kept as it
  // came, and so is a model or output whose list has not arrived yet.
  const _applyNode = () => {
    const kind = curTaskType;
    const label = String($('task-form-name')?.value || '').trim() || KIND_WORDS[kind] || 'Step';
    const config = {};
    const keep = (k, v) => { if (v != null && v !== '') config[k] = v; };
    const refuse = (m) => { if (uiModule) uiModule.showError(m); };
    if (kind === 'run_task') {
      const target = $('task-form-run-task')?.value || '';
      if (!target) { refuse('Choose the task this step runs'); return; }
      config.task_id = target;
      if (typeof onSaved === 'function') onSaved({ label, kind, config });
      return;
    }
    if (kind === 'llm') {
      keep('crew_member_id', existing?.crew_member_id);
      keep('max_steps', existing?.max_steps);
      // `P22-16`. An AI step's tools and answer shape: the caller's section
      // decides them when it is drawn; without it they are kept as they came.
      if (extraView && typeof extraView.read === 'function') {
        const more = extraView.read();
        if (more && more.refusal) {
          refuse(more.refusal);
          return;
        }
        for (const [k, v] of Object.entries((more && more.config) || {})) config[k] = v;
      } else {
        keep('tools', existing?.tools);
        keep('answer_fields', existing?.answer_fields);
      }
    }
    const outSel = $('task-form-output');
    if (outSel && _outputsLoaded) {
      const v = outSel.value || '';
      keep('output_target', v === 'email'
        ? _buildTaskEmailOutputTarget($('task-form-output-email-to')?.value || '', $('task-form-output-email-account')?.value || '')
        : v);
    } else {
      keep('output_target', existing?.output_target);
    }
    if (kind === 'llm' || kind === 'research') {
      const prompt = $('task-form-prompt')?.value?.trim();
      if (!prompt) { refuse('Prompt is required'); return; }
      config.prompt = prompt;
      if (kind === 'llm') keep('character_id', $('task-form-persona')?.value || '');
      const modelVal = $('task-form-model')?.value || '';
      const idx = modelVal.indexOf('::');
      if (idx > 0) {
        config.endpoint_url = modelVal.slice(0, idx);
        config.model = modelVal.slice(idx + 2);
      } else if (!_modelsLoaded) {
        keep('endpoint_url', existing?.endpoint_url);
        keep('model', existing?.model);
      }
    } else {
      const action = $('task-form-action')?.value;
      if (!action) { refuse('Select an action'); return; }
      config.action = action;
      const chosen = _actionPromptValue(action, host);
      if (chosen) {
        if (!chosen.value && chosen.param.required) {
          refuse(`${chosen.param.label || chosen.param.name} is required for ${action}`);
          return;
        }
        keep('prompt', chosen.value);
      } else if (_EMAIL_ACCOUNT_ACTIONS.has(action)) {
        const accountId = $('task-form-email-account')?.value || '';
        if (accountId) config.prompt = JSON.stringify({ account_id: accountId });
      }
    }
    if (typeof onSaved === 'function') onSaved({ label, kind, config });
  };

  // `P22-05` (wf-ui). A workflow's start: its trigger, time limit and
  // notifications, written to its trigger task through the door every task
  // is edited by — and nothing else, so a start's save cannot change what
  // the task is (`task_type`), what it says (`prompt`), where it delivers,
  // its model or a chain.
  const _saveTrigger = async (readTrigger) => {
    if (!existing || !existing.id) {
      if (uiModule) uiModule.showError('This workflow has no start to save yet.');
      return;
    }
    const payload = { trigger_type: triggerType };
    if (!readTrigger(payload)) return;
    const notifEl = $('task-form-notif');
    if (notifEl) payload.notifications_enabled = !!notifEl.checked;
    try {
      const saved = await _updateTask(existing.id, payload);
      if (uiModule) uiModule.showToast('Start saved');
      if (typeof onSaved === 'function') await onSaved((saved && saved.task) || saved);
    } catch (e) {
      if (uiModule) uiModule.showError(e.message);
    }
  };

  // Save
  // Named rather than anonymous: 200 lines of payload assembly that no
  // stack trace and no test could refer to by anything but a line number.
  const _saveTaskForm = async () => {
    // `P22-05` (wf-ui). The trigger's fields, read into `payload` — the task's
    // save and a workflow start's save both call this, so the trigger is read
    // one way (`Law 7`). `false` when the person has been told what to fix.
    // It is here, inside the Save every mode goes through, so the save's own
    // scope still holds the served trigger-count default it always did.
    const _triggerInto = (payload) => {
      // Trigger specifics
      if (triggerType === 'schedule') {
        const schedSelect = $('task-form-schedule');
        payload.schedule = schedSelect?.value || 'daily';
        // `P22-03`. The zone the time means; `''` clears one (the API reads an
        // empty string as "no zone of its own").
        const zone = $('task-form-tz')?.value || '';

        if (payload.schedule === 'cron') {
          const cronVal = $('task-form-cron')?.value?.trim();
          if (!cronVal) {
            if (uiModule) uiModule.showError('Cron expression is required');
            return false;
          }
          payload.cron_expression = cronVal;
        } else {
          const timeVal = _getTimePickerValue('task-form-time-wrap', host);
          // With a zone the server reads this as that zone's clock, so it goes
          // out as typed; without one it is UTC, as it always was.
          payload.scheduled_time = zone ? timeVal : _localTimeToUtc(timeVal);

          const dayInput = $('task-form-day');
          if (dayInput) payload.scheduled_day = parseInt(dayInput.value, 10);

          if (payload.schedule === 'once' && $('task-form-date')) {
            const pickedDate = _getDatePickerValue('task-form-date', host);
            const [h, m] = timeVal.split(':').map(Number);
            if (zone) {
              if (!_zoneDrawable(zone)) {
                if (uiModule) uiModule.showError(`This browser cannot place a date in ${zone}. Pick another time zone.`);
                return false;
              }
              payload.scheduled_date = _instantOfWallClock(
                zone, pickedDate.getFullYear(), pickedDate.getMonth(), pickedDate.getDate(), h, m,
              ).toISOString();
            } else {
              pickedDate.setHours(h, m, 0, 0);
              payload.scheduled_date = pickedDate.toISOString();
            }
          }
        }
        payload.tz_name = zone;
        // Retries are a schedule's: a failed event or webhook task waits for its
        // next trigger and is never re-run on a clock (`failure_next_run`), so the
        // box is only drawn, and only sent, for a scheduled task.
        const retries = _readRetries(host);
        if (retries.error) {
          if (uiModule) uiModule.showError(retries.error);
          return false;
        }
        payload.max_retries = retries.value;
      } else if (triggerType === 'event') {
        const evSel = $('task-form-event');
        const countInput = $('task-form-trigger-count');
        if (!evSel?.value) {
          if (uiModule) uiModule.showError('Select an event');
          return false;
        }
        payload.trigger_event = evSel.value;
        // `P8-31`. The second of the two fives. The served default is the answer
        // when the field is blank; `DEFAULT_TRIGGER_COUNT` lives beside the bus
        // that reads it and ships on `/meta/actions`.
        payload.trigger_count = parseInt(countInput?.value || String(_defaultTriggerCount()), 10);
      }
      // webhook: no extra fields needed, token is auto-generated server-side

      // `P22-03`. A ceiling on one run's wall clock, for every trigger. Blank is
      // `0`, which the API stores as "no limit" — so clearing the box clears it.
      const limit = _readTimeLimit(host);
      if (limit.error) {
        if (uiModule) uiModule.showError(limit.error);
        return false;
      }
      payload.timeout_seconds = limit.value;
      return true;
    };

    if (isNode) { _applyNode(); return; }
    if (isTrigger) { await _saveTrigger(_triggerInto); return; }
    const nameEl = $('task-form-name');
    const outputSelValue = $('task-form-output')?.value || 'session';
    let outputTarget = outputSelValue;
    if (outputSelValue === 'email') {
      const to = $('task-form-output-email-to')?.value || '';
      const accountId = $('task-form-output-email-account')?.value || '';
      outputTarget = _buildTaskEmailOutputTarget(to, accountId);
    }

    const payload = {
      task_type: taskType,
      trigger_type: triggerType,
      output_target: outputTarget,
    };
    if (nameEl) payload.name = nameEl.value.trim() || undefined;

    // Model / endpoint override. Blank = inherit session default. Otherwise
    // value is `endpoint_url::model_id`.
    const modelVal = $('task-form-model')?.value || '';
    if (modelVal) {
      const idx = modelVal.indexOf('::');
      if (idx > 0) {
        payload.endpoint_url = modelVal.slice(0, idx);
        payload.model = modelVal.slice(idx + 2);
      }
    } else {
      // Explicitly clear so a previously-pinned task can return to default.
      payload.endpoint_url = '';
      payload.model = '';
    }

    // Chain — both branches. `B873`.
    //
    // Sent unconditionally, including empty: `''` is how the API clears an
    // edge (`task_routes.py:927-929` — `is not None` is the guard, so an
    // omitted key leaves the stored edge alone), and a person who sets a
    // failure branch and then changes their mind has to be able to remove it.
    for (const [selectId, field] of CHAIN_FIELDS) {
      payload[field] = $(selectId)?.value || '';
    }

    // Notifications toggle — defaults to true if absent.
    const notifEl = $('task-form-notif');
    if (notifEl) payload.notifications_enabled = !!notifEl.checked;

    // Task type specifics
    if (taskType === 'llm' || taskType === 'research') {
      const prompt = $('task-form-prompt')?.value?.trim();
      if (!prompt) {
        if (uiModule) uiModule.showError('Prompt is required');
        return;
      }
      payload.prompt = prompt;
      const personaVal = $('task-form-persona')?.value || '';
      payload.character_id = personaVal;
    } else {
      // Non-llm/research tasks: explicitly clear any persona on switch.
      payload.character_id = '';
      const action = $('task-form-action')?.value;
      if (!action) {
        if (uiModule) uiModule.showError('Select an action');
        return;
      }
      payload.action = action;
      // `P8-22`. An action that declares a parameter carries it in `prompt` —
      // that is the column the scheduler already reads for `ssh_command` and
      // its three siblings. Required means required: saving a `run_local` with
      // an empty script produced a task that ran nothing and said so only when
      // it fired.
      const chosen = _actionPromptValue(action, host);
      if (chosen) {
        if (!chosen.value && chosen.param.required) {
          if (uiModule) uiModule.showError(`${chosen.param.label || chosen.param.name} is required for ${action}`);
          return;
        }
        payload.prompt = chosen.value;
      } else if (_EMAIL_ACCOUNT_ACTIONS.has(action)) {
        const accountId = $('task-form-email-account')?.value || '';
        payload.prompt = accountId ? JSON.stringify({ account_id: accountId }) : '';
      }
      if (action === 'check_email_urgency') {
        const urgentPrompt = $('task-form-urgent-email-prompt')?.value || '';
        try {
          await _saveUrgentEmailSettings(urgentPrompt);
        } catch (e) {
          if (uiModule) uiModule.showError('Failed to save urgency rules');
          return;
        }
      }
    }

    if (!_triggerInto(payload)) return;

    try {
      // Edit only when we have a real existing task (has an id). A draft
      // object passed for AI pre-fill has no id → create via POST.
      let saved;
      if (existing && existing.id) {
        saved = await _updateTask(existing.id, payload);
        if (uiModule) uiModule.showToast('Task updated');
      } else {
        saved = await _createTask(payload);
        if (uiModule) uiModule.showToast('Task created');
      }
      // Both routes answer with the row itself (`_task_to_dict`); a `{ task }`
      // envelope is read too, so the owner is handed the row either way.
      if (typeof onSaved === 'function') await onSaved((saved && saved.task) || saved);
    } catch (e) {
      if (uiModule) uiModule.showError(e.message);
    }
  };
  $('task-form-save').addEventListener('click', _saveTaskForm);

  const view = {
    destroy() {
      if (!alive) return;
      for (const h of Object.values(nodeHandles)) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } }
      if (extraView && typeof extraView.destroy === 'function') { try { extraView.destroy(); } catch (_) { /* gone */ } }
      alive = false;
      if (_mounted.get(host) === view) _mounted.delete(host);
      if (typeof host.replaceChildren === 'function') host.replaceChildren();
      else host.innerHTML = '';
    },
  };
  _mounted.set(host, view);
  return view;
}
