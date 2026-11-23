// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloPane.js — Apollo's pane: what Apollo is doing, what needs the person,
// what came of the work, and what Apollo knows about them.
//
// The outline (`assistant-chat-outline/outline.md`, *Surfaces*): the right
// column that holds the Workstation becomes the Apollo pane, opened from a
// button in the Apollo chat header and docked in that column
// (`cockpitWorkspace.js` docks it as it docks the phone). It shows only from
// the Apollo chat; agent chats keep the Workstation dock.
//
// Three views, one at a time, each with a way back:
//
//   main   — status, Text, Needs you, the Computer card, Activity, Outputs,
//            Open loops, and the door to What Apollo knows
//   task   — one task's report: what it is, where it stands, its question,
//            its budget (editable), Start or Run again, Chat with this agent
//   knows  — what Apollo knows: what the person said, what Apollo inferred,
//            each confirmable, editable or forgettable, and a line to add
//
// **Every rule is the server's.** `routes/apollo_routes.py` says what is the
// person's and refuses the rest in a sentence, which the pane shows as it
// came. No server string is parsed as HTML: markup is built with
// `createElement` and text goes in as `textContent`.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';
import { selectSession } from './sessions.js';
import uiModule from './ui.js';
import * as M from './apolloPaneModel.js';

export const MODAL_ID = 'apollo-pane-modal';
const REFRESH_MS = 8000;

const APOLLO_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/></svg>';

let _win = null;        // the built window's parts
let _view = 'main';     // main | task | knows
let _taskId = '';       // the task the task view shows
let _timer = null;
let _gen = 0;           // a render started before a newer one is dropped
let _showAll = false;   // Activity's Show more
let _editing = '';      // the id of the knows line being edited

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null && text !== '') n.textContent = String(text);
  return n;
}

function _btn(cls, text, onClick, label) {
  const b = _el('button', `apo-btn ${cls || ''}`.trim(), text);
  b.type = 'button';
  if (label) b.setAttribute('aria-label', label);
  b.addEventListener('click', (e) => onClick(e));   // a type=button submits nothing
  return b;
}

async function _api(path, { method = 'GET', body } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const why = data && typeof data.detail === 'string' ? data.detail : `Apollo could not do that (${res.status}).`;
    throw new Error(why);
  }
  return data;
}

function _say(msg) {
  try { uiModule.showToast(msg); } catch (_) { /* no toast host */ }
}

/* ───────────── building ───────────── */

function _build() {
  const modal = _el('div', 'modal apo-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content apo-content');
  const header = _el('div', 'modal-header');
  const h = _el('h4', 'apo-heading');
  const icon = _el('span', 'apo-icon');
  icon.innerHTML = APOLLO_ICON;   // a constant above, never server text
  h.appendChild(icon);
  h.appendChild(_el('span', 'apo-title', 'Apollo'));
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closeApolloPane(); });
  header.appendChild(h);
  header.appendChild(close);

  // The status sits outside the views, so the dock's pane header can read it.
  const status = _el('p', 'apo-status apo-tone-idle', 'Idle');
  status.setAttribute('aria-live', 'polite');
  const body = _el('div', 'apo-body');
  content.appendChild(header);
  content.appendChild(status);
  content.appendChild(body);
  modal.appendChild(content);
  return { modal, content, header, status, body };
}

function _section(title, extra) {
  const s = _el('section', 'apo-sec');
  const head = _el('div', 'apo-sec-h');
  head.appendChild(_el('h5', 'apo-sec-t', title));
  if (extra) head.appendChild(extra);
  s.appendChild(head);
  return s;
}

function _dot(state) {
  const d = M.dotOf(state);
  const dot = _el('span', `apo-dot ${d.cls}`);
  dot.setAttribute('aria-hidden', 'true');
  return { dot, words: d.words };
}

/* ───────────── the main view ───────────── */

function _profile(state) {
  const box = _el('div', 'apo-profile');
  const avatar = _el('span', 'apo-avatar', 'A');
  avatar.setAttribute('aria-hidden', 'true');
  const who = _el('div', 'apo-who');
  who.appendChild(_el('strong', 'apo-name', (state && state.name) || 'Apollo'));
  const hl = M.headline(state);
  who.appendChild(_el('span', `apo-now apo-tone-${hl.tone}`, hl.words));
  box.appendChild(avatar);
  box.appendChild(who);
  box.appendChild(_btn('apo-text', 'Text', () => {
    const composer = document.getElementById('message');
    if (composer) composer.focus();
  }, 'Write to Apollo'));
  return box;
}

function _answerBox(task, after) {
  const form = _el('form', 'apo-answer');
  const input = _el('input', 'apo-input');
  input.type = 'text';
  input.placeholder = 'Your answer';
  input.setAttribute('aria-label', `Answer: ${task.title}`);
  input.maxLength = 600;
  const send = _el('button', 'apo-btn apo-primary', 'Send');
  send.type = 'submit';
  form.appendChild(input);
  form.appendChild(send);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const words = input.value.trim();
    if (!words) return;
    send.disabled = true;
    try {
      const out = await _api(`/api/apollo/tasks/${encodeURIComponent(task.id)}/answer`, { method: 'POST', body: { answer: words } });
      _say(out && out.started ? 'Sent. The lead is back on it.' : 'Sent.');
      input.value = '';
      if (after) after();
    } catch (err) {
      _say(err.message);
    } finally {
      send.disabled = false;
    }
  });
  return form;
}

function _needsSection(list) {
  if (!list.length) return null;
  const s = _section('Needs you');
  s.classList.add('apo-needs');
  for (const t of list) {
    const row = _el('div', 'apo-need');
    const title = _btn('apo-link apo-need-t', t.title, () => _openTask(t.id));
    row.appendChild(title);
    if (t.question) row.appendChild(_el('p', 'apo-q', t.question));
    row.appendChild(_answerBox(t, _refresh));
    s.appendChild(row);
  }
  return s;
}

function _computerSection(ws) {
  const c = M.computerCard(ws);
  const s = _section('Computer');
  const card = _el(c.opens ? 'button' : 'div', `apo-card apo-ws-${c.state}`);
  if (c.opens) {
    card.type = 'button';
    card.setAttribute('aria-label', `Workstation, ${c.label}. Open the live screen.`);
    card.addEventListener('click', () => {
      import('./workstationScreen.js').then((m) => m.openWorkstationScreen({ focus: true })).catch(() => {});
    });
  }
  const top = _el('div', 'apo-card-top');
  const { dot } = _dot(c.state === 'up' ? 'working' : 'waiting');
  top.appendChild(dot);
  top.appendChild(_el('strong', '', 'Workstation'));
  top.appendChild(_el('span', 'apo-card-state', c.label));
  card.appendChild(top);
  if (c.sentence) card.appendChild(_el('p', 'apo-card-line', c.sentence));
  s.appendChild(card);
  return s;
}

function _activitySection(tasks) {
  const all = Array.isArray(tasks) ? tasks : [];
  const s = _section('Activity');
  if (!all.length) {
    s.appendChild(_el('p', 'apo-empty', 'Nothing yet. Ask Apollo for something in the chat and it shows here.'));
    return s;
  }
  const { rows, more } = M.activityRows(all, { limit: _showAll ? all.length : 6 });
  const list = _el('ul', 'apo-list');
  for (const t of rows) {
    const li = _el('li', 'apo-row');
    const b = _el('button', 'apo-row-b');
    b.type = 'button';
    const { dot, words } = _dot(t.state);
    b.appendChild(dot);
    b.appendChild(_el('span', 'apo-row-t', t.title));
    b.appendChild(_el('span', 'apo-row-s', words));
    b.setAttribute('aria-label', `${t.title}, ${words}`);
    b.addEventListener('click', () => _openTask(t.id));
    li.appendChild(b);
    list.appendChild(li);
  }
  s.appendChild(list);
  if (more || _showAll) {
    s.appendChild(_btn('apo-link apo-more', _showAll ? 'Show less' : `Show ${more} more`, () => {
      _showAll = !_showAll;
      _refresh();
    }));
  }
  return s;
}

function _outputsSection(tasks) {
  const outs = M.outputs(tasks);
  if (!outs.length) return null;
  const s = _section('Outputs');
  const list = _el('ul', 'apo-list');
  for (const o of outs) {
    const li = _el('li', 'apo-out');
    li.appendChild(_btn('apo-link apo-out-t', o.title, () => _openTask(o.id)));
    li.appendChild(_el('p', 'apo-out-line', o.outcome));
    list.appendChild(li);
  }
  s.appendChild(list);
  return s;
}

function _loopsSection(notes) {
  const open = (Array.isArray(notes) ? notes : []).filter((n) => n && n.state === 'open');
  if (!open.length) return null;
  const s = _section('Open loops');
  const list = _el('ul', 'apo-list');
  for (const n of open) {
    const li = _el('li', 'apo-loop');
    li.appendChild(_el('span', 'apo-loop-t', n.text));
    const acts = _el('span', 'apo-acts');
    const set = (state, said) => async () => {
      try {
        await _api(`/api/apollo/notebook/${encodeURIComponent(n.id)}`, { method: 'PATCH', body: { state } });
        _say(said);
        _refresh();
      } catch (err) { _say(err.message); }
    };
    acts.appendChild(_btn('apo-small', 'Settled', set('settled', 'Marked settled.'), `Mark settled: ${n.text}`));
    acts.appendChild(_btn('apo-small', 'Drop', set('dropped', 'Dropped.'), `Drop: ${n.text}`));
    li.appendChild(acts);
    list.appendChild(li);
  }
  s.appendChild(list);
  return s;
}

async function _drawMain(gen) {
  const [state, tasksOut, notesOut, ws] = await Promise.all([
    _api('/api/apollo/state'),
    _api('/api/apollo/tasks'),
    _api('/api/apollo/notebook?kind=open_loop&state=open'),
    fetch('/api/workstation/status', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  if (gen !== _gen || !_win) return;
  const tasks = (tasksOut && tasksOut.tasks) || [];
  _setStatus(state);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_profile(state));
  const needs = _needsSection(M.needsYou(tasks));
  if (needs) body.appendChild(needs);
  body.appendChild(_computerSection(ws));
  body.appendChild(_activitySection(tasks));
  const outs = _outputsSection(tasks);
  if (outs) body.appendChild(outs);
  const loops = _loopsSection(notesOut && notesOut.notes);
  if (loops) body.appendChild(loops);
  const knows = _section('About you');
  knows.appendChild(_el('p', 'apo-empty', 'What you told Apollo, and what it worked out. You can confirm, fix or remove any of it.'));
  knows.appendChild(_btn('apo-link', 'What Apollo knows', () => { _view = 'knows'; _refresh(); }));
  body.appendChild(knows);
}

function _setStatus(state) {
  if (!_win) return;
  const hl = M.headline(state);
  _win.status.textContent = hl.words;
  _win.status.className = `apo-status apo-tone-${hl.tone}`;
}

/* ───────────── the task view ───────────── */

function _back(label = 'Back') {
  return _btn('apo-back', `‹ ${label}`, () => { _view = 'main'; _editing = ''; _refresh(); }, 'Back to Apollo');
}

function _budgetEditor(task) {
  const box = _el('div', 'apo-budget');
  box.appendChild(_el('p', 'apo-budget-line', M.budgetLine(task)));
  const form = _el('form', 'apo-budget-form');
  const input = _el('input', 'apo-input');
  input.type = 'text';
  input.placeholder = 'Budget, like 250k or 2M (empty for the admin cap)';
  input.setAttribute('aria-label', 'Budget for this goal on paid models');
  if (task.budget_tokens !== null && task.budget_tokens !== undefined) input.value = M.tokens(task.budget_tokens);
  const save = _el('button', 'apo-btn', 'Set budget');
  save.type = 'submit';
  form.appendChild(input);
  form.appendChild(save);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const parsed = M.parseBudget(input.value);
    if (!parsed.ok) { _say('Write a budget as a number of tokens, like 250k or 2M.'); return; }
    try {
      await _api(`/api/apollo/tasks/${encodeURIComponent(task.id)}`, { method: 'PATCH', body: { budget_tokens: parsed.value } });
      _say(parsed.value === null ? 'Budget back to the admin cap.' : 'Budget set.');
      _refresh();
    } catch (err) { _say(err.message); }
  });
  box.appendChild(form);
  return box;
}

function _fact(label, value) {
  if (!value) return null;
  const row = _el('div', 'apo-fact');
  row.appendChild(_el('span', 'apo-fact-k', label));
  row.appendChild(_el('span', 'apo-fact-v', value));
  return row;
}

async function _drawTask(gen) {
  const [state, task] = await Promise.all([_api('/api/apollo/state'), _api(`/api/apollo/tasks/${encodeURIComponent(_taskId)}`)]);
  if (gen !== _gen || !_win) return;
  _setStatus(state);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_back());
  const head = _el('div', 'apo-task-h');
  const { dot, words } = _dot(task.state);
  head.appendChild(dot);
  head.appendChild(_el('h5', 'apo-task-t', task.title));
  head.appendChild(_el('span', 'apo-row-s', words));
  body.appendChild(head);
  for (const f of [
    _fact('What it is', task.brief),
    _fact('Next step', task.next_step),
    _fact('Lead', task.lead_agent),
    _fact('Came to', task.outcome),
  ]) if (f) body.appendChild(f);
  if (task.state === 'needs_you') {
    const ask = _el('div', 'apo-need');
    if (task.question) ask.appendChild(_el('p', 'apo-q', task.question));
    ask.appendChild(_answerBox(task, _refresh));
    body.appendChild(ask);
  }
  body.appendChild(_budgetEditor(task));
  const acts = _el('div', 'apo-acts apo-task-acts');
  const verb = M.runVerb(task);
  if (verb) {
    acts.appendChild(_btn('apo-primary', verb, async () => {
      try {
        const out = await _api(`/api/apollo/tasks/${encodeURIComponent(task.id)}/start`, { method: 'POST' });
        _say(out && out.started ? 'Started.' : (out && out.why) || 'It could not start just now.');
        _refresh();
      } catch (err) { _say(err.message); }
    }));
  }
  if (task.session_id) {
    acts.appendChild(_btn('', 'Chat with this agent', () => {
      selectSession(task.session_id).catch(() => _say('That chat could not be opened.'));
    }));
  }
  if (acts.childNodes.length) body.appendChild(acts);
}

/* ───────────── the knows view ───────────── */

function _lineRow(line) {
  const li = _el('li', `apo-line apo-line-${line.basis === 'stated' ? 'stated' : 'inferred'}`);
  if (_editing === line.id) {
    const form = _el('form', 'apo-edit');
    const input = _el('input', 'apo-input');
    input.type = 'text';
    input.value = line.text || '';
    input.maxLength = 500;
    input.setAttribute('aria-label', 'Edit this line');
    const save = _el('button', 'apo-btn apo-primary', 'Save');
    save.type = 'submit';
    form.appendChild(input);
    form.appendChild(save);
    form.appendChild(_btn('', 'Cancel', () => { _editing = ''; _refresh(); }));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}`, { method: 'PATCH', body: { text: input.value } });
        _editing = '';
        _say('Saved. Apollo takes it as you wrote it.');
        _refresh();
      } catch (err) { _say(err.message); }
    });
    li.appendChild(form);
    setTimeout(() => input.focus(), 0);
    return li;
  }
  li.appendChild(_el('span', 'apo-line-t', line.text));
  if (line.basis !== 'stated' && line.evidence) li.appendChild(_el('span', 'apo-line-why', `From: ${line.evidence}`));
  const acts = _el('span', 'apo-acts');
  if (line.basis !== 'stated') {
    acts.appendChild(_btn('apo-small', 'That is right', async () => {
      try {
        await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}/confirm`, { method: 'POST' });
        _say('Confirmed.');
        _refresh();
      } catch (err) { _say(err.message); }
    }, `Confirm: ${line.text}`));
  }
  acts.appendChild(_btn('apo-small', 'Edit', () => { _editing = line.id; _refresh(); }, `Edit: ${line.text}`));
  acts.appendChild(_btn('apo-small', 'Forget', async () => {
    try {
      await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}`, { method: 'DELETE' });
      _say('Forgotten.');
      _refresh();
    } catch (err) { _say(err.message); }
  }, `Forget: ${line.text}`));
  li.appendChild(acts);
  return li;
}

async function _drawKnows(gen) {
  const [state, out] = await Promise.all([_api('/api/apollo/state'), _api('/api/apollo/knows')]);
  if (gen !== _gen || !_win) return;
  _setStatus(state);
  const { stated, inferred } = M.knowsGroups(out && out.lines);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_back());
  body.appendChild(_el('h5', 'apo-task-t', 'What Apollo knows'));

  const add = _el('form', 'apo-add');
  const input = _el('input', 'apo-input');
  input.type = 'text';
  input.placeholder = 'Tell Apollo something to keep';
  input.maxLength = 500;
  input.setAttribute('aria-label', 'Tell Apollo something to keep');
  const save = _el('button', 'apo-btn apo-primary', 'Add');
  save.type = 'submit';
  add.appendChild(input);
  add.appendChild(save);
  add.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    try {
      await _api('/api/apollo/knows', { method: 'POST', body: { text } });
      input.value = '';
      _say('Got it.');
      _refresh();
    } catch (err) { _say(err.message); }
  });
  body.appendChild(add);

  const said = _section('What you told it');
  if (stated.length) {
    const list = _el('ul', 'apo-list');
    stated.forEach((l) => list.appendChild(_lineRow(l)));
    said.appendChild(list);
  } else said.appendChild(_el('p', 'apo-empty', 'Nothing yet.'));
  body.appendChild(said);

  const guessed = _section('What it worked out');
  guessed.appendChild(_el('p', 'apo-empty', 'Hunches from what it saw. None changes what Apollo does until you confirm it.'));
  if (inferred.length) {
    const list = _el('ul', 'apo-list');
    inferred.forEach((l) => list.appendChild(_lineRow(l)));
    guessed.appendChild(list);
  }
  body.appendChild(guessed);
}

/* ───────────── refresh and lifecycle ───────────── */

function _openTask(id) {
  _view = 'task';
  _taskId = id;
  _refresh();
}

async function _refresh() {
  if (!_win) return;
  const gen = ++_gen;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  try {
    if (_view === 'task' && _taskId) await _drawTask(gen);
    else if (_view === 'knows') await _drawKnows(gen);
    else await _drawMain(gen);
  } catch (err) {
    if (gen !== _gen || !_win) return;
    _win.body.textContent = '';
    if (_view !== 'main') _win.body.appendChild(_back());
    _win.body.appendChild(_el('p', 'apo-error', err.message || 'Apollo could not load just now.'));
  }
  // Keep the main view current while it is open; an edit in progress is left alone.
  if (gen === _gen && _win && !_editing && !_win.modal.classList.contains('modal-minimized')) {
    _timer = setTimeout(() => {
      const active = document.activeElement;
      if (_win && active && _win.modal.contains(active) && active.tagName === 'INPUT') {
        _timer = setTimeout(_refresh, REFRESH_MS);   // they are typing: look later
        return;
      }
      _refresh();
    }, REFRESH_MS);
  }
}

function _teardown() {
  if (!_win) return;
  ++_gen;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  const modal = _win.modal;
  _win = null;
  _view = 'main';
  _taskId = '';
  _editing = '';
  _showAll = false;
  if (modal.parentNode) modal.parentNode.removeChild(modal);
}

/** Open the pane, or bring it forward. */
export function openApolloPane() {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
    _refresh();
    return true;
  }
  if (_win) _teardown();
  _win = _build();
  document.body.appendChild(_win.modal);
  Modals.register(MODAL_ID, { restoreFn: _refresh, closeFn: _teardown });
  Modals.injectMinimizeButton(_win.modal, MODAL_ID);
  makeWindowDraggable(_win.modal, {
    content: _win.content, header: _win.header,
    skipSelector: 'button, input, select, label, form', minWidth: 300, minHeight: 360,
  });
  _refresh();
  return true;
}

export function closeApolloPane() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

export function isApolloPaneOpen() { return !!_win; }
