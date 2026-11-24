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
//   main   — status, Call and Text, Needs you (questions and the approvals
//            a lead is waiting on), the Computer card, Devices, Activity,
//            Outputs, Open loops, and the door to What Apollo knows
//   task   — one task's report: what it is, where it stands, its question,
//            its budget (editable), Start or Run again, and its chat with
//            the lead under the report (the pane widens into a dual pane),
//            or popped out into a window of its own (`apolloTaskChat.js`)
//   knows  — what Apollo knows: what the person said, what Apollo inferred,
//            each confirmable, editable or forgettable, and a line to add
//
// **Every rule is the server's.** `routes/apollo_routes.py` says what is the
// person's and refuses the rest in a sentence, which the pane shows as it
// came. No server string is parsed as HTML: markup is built with
// `createElement` and text goes in as `textContent`.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';
import { createTaskChat, popOutTaskChat, isTaskChatFloating } from './apolloTaskChat.js';
import uiModule from './ui.js';
import * as M from './apolloPaneModel.js';
import * as Sp from './apolloSpaces.js';
import * as Orb from './apolloOrb.js';

export const MODAL_ID = 'apollo-pane-modal';
const REFRESH_MS = 8000;

const APOLLO_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/></svg>';

let _win = null;        // the built window's parts
let _view = 'main';     // main | task | knows | space | rhythm
let _taskId = '';       // the task the task view shows
let _timer = null;
let _gen = 0;           // a render started before a newer one is dropped
let _showAll = false;   // Activity's Show more
let _editing = '';      // the id of the knows line being edited
let _chat = null;       // the embedded task chat, kept across redraws
let _reach = 'here';    // Activity: 'here' (the space Apollo is in) or 'all'
let _offSpace = null;   // stops following the space switcher
let _deleting = '';     // a space whose Delete was pressed once
let _agentDraft = '';   // an admin's edit of a drafted agent, kept across redraws

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

/** `?space=` for where Apollo is, or for every open space. */
function _here() { return encodeURIComponent(Sp.spaceParam()); }
function _reachParam() { return _reach === 'all' ? 'all' : _here(); }

function _say(msg) {
  try { uiModule.showToast(msg); } catch (_) { /* no toast host */ }
}

/* ───────────── building ───────────── */

function _build() {
  const modal = _el('div', 'modal apo-modal');
  modal.id = 'apollo-pane-modal';  // MODAL_ID, written out so check-wiring sees the pane made (apolloOrb.js finds it by id)
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
  const switcher = Sp.createSwitcher();
  header.appendChild(switcher.el);
  header.appendChild(close);

  // The status sits outside the views, so the dock's pane header can read it.
  const status = _el('p', 'apo-status apo-tone-idle', 'Idle');
  status.setAttribute('aria-live', 'polite');
  const body = _el('div', 'apo-body');
  content.appendChild(header);
  content.appendChild(status);
  content.appendChild(body);
  modal.appendChild(content);
  return { modal, content, header, status, body, switcher };
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
  const acts = _el('div', 'apo-acts apo-talk');
  acts.appendChild(_callButton());
  acts.appendChild(_btn('apo-text', 'Text', () => {
    const composer = document.getElementById('message');
    if (composer) composer.focus();
  }, 'Write to Apollo'));
  box.appendChild(acts);
  return box;
}

// Call: a voice conversation with Apollo in its own chat, through the call
// the composer already has (Whisper hears, Kokoro speaks). The pane only
// shows from the Apollo chat, so the call is Apollo's.
function _callButton() {
  const b = _btn('apo-call', 'Call', async () => {
    try {
      const vc = await import('./voiceCall.js');
      vc.toggleVoiceCall();
      setTimeout(() => { b.textContent = vc.isVoiceCallActive() ? 'End call' : 'Call'; }, 300);
    } catch (_) {
      _say('Calls are not available just now.');
    }
  }, 'Call Apollo');
  import('./voiceCall.js').then((vc) => { if (vc.isVoiceCallActive()) b.textContent = 'End call'; }).catch(() => {});
  return b;
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

function _approvalRow(a) {
  const row = _el('div', 'apo-need apo-approval');
  row.appendChild(_btn('apo-link apo-need-t', a.title, () => _openTask(a.task_id)));
  row.appendChild(_el('p', 'apo-q', `Waiting for your OK to use ${a.tool}.`));
  if (a.why) row.appendChild(_el('p', 'apo-card-line', a.why));
  const acts = _el('div', 'apo-acts');
  const answer = (decision, said) => async () => {
    try {
      await _api(`/api/tasks/${encodeURIComponent(a.run_task_id)}/runs/${encodeURIComponent(a.run_id)}/answer`, {
        method: 'POST', body: { approval_id: a.approval_id, decision },
      });
      _say(said);
    } catch (err) { _say(err.message); }
    _refresh();
  };
  acts.appendChild(_btn('apo-primary', 'Allow once', answer('approve_task', 'Allowed. The lead carries on.'), `Allow once: ${a.tool}`));
  acts.appendChild(_btn('', 'Deny', answer('deny', 'Denied. It was not done.'), `Deny: ${a.tool}`));
  row.appendChild(acts);
  return row;
}

function _offerRow(o) {
  const row = _el('div', 'apo-need apo-offer');
  row.appendChild(_el('p', 'apo-q', o.words));
  const acts = _el('div', 'apo-acts');
  const answer = (yes) => async () => {
    try {
      await _api(`/api/apollo/trust/${encodeURIComponent(o.id)}`, { method: 'POST', body: { answer: yes ? 'yes' : 'no' } });
      _say(yes ? `Apollo will just do ${o.tool} for ${o.kind}. Take it back any time.` : 'Not now. Apollo keeps asking.');
    } catch (err) { _say(err.message); }
    _refresh();
  };
  acts.appendChild(_btn('apo-primary', 'Just do it', answer(true), `Just do ${o.tool} for ${o.kind}`));
  acts.appendChild(_btn('', 'Not now', answer(false), `Keep asking before ${o.tool} for ${o.kind}`));
  row.appendChild(acts);
  return row;
}

function _justDoesSection(granted) {
  if (!granted.length) return null;
  const s = _section('Apollo just does');
  for (const g of granted) {
    const row = _el('div', 'apo-nudge');
    row.appendChild(_el('span', 'apo-nudge-t', g.words));
    row.appendChild(_btn('apo-small', 'Ask me again', async () => {
      try {
        await _api(`/api/apollo/trust/${encodeURIComponent(g.id)}`, { method: 'DELETE' });
        _say(`Apollo will ask before ${g.tool} for ${g.kind} again.`);
      } catch (err) { _say(err.message); }
      _refresh();
    }, `Ask again before ${g.tool} for ${g.kind}`));
    s.appendChild(row);
  }
  return s;
}

function _needsSection(list, approvals = [], locked = [], offers = []) {
  if (!list.length && !approvals.length && !locked.length && !offers.length) return null;
  const s = _section('Needs you');
  s.classList.add('apo-needs');
  // A locked space says only that something there needs the person; what it
  // is stays behind the airgap until they go in.
  for (const sp of locked) {
    const row = _el('div', 'apo-need apo-need-locked');
    row.appendChild(_el('p', 'apo-q', M.lockedLine(sp)));
    row.appendChild(_btn('apo-small', 'Go there', () => Sp.switchTo(sp.id), `Go to ${sp.name}`));
    s.appendChild(row);
  }
  for (const a of approvals) s.appendChild(_approvalRow(a));
  for (const o of offers) s.appendChild(_offerRow(o));
  for (const t of list) {
    const row = _el('div', 'apo-need');
    row.dataset.taskId = t.id;   // the orb finds a task by it (`apolloOrb.js`)
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

// Devices: the person's workstation and phone, each with its state; a click
// opens the one that can be opened. Each person sees only their own.
function _devicesSection(ws, phone) {
  const s = _section('Devices');
  const list = _el('ul', 'apo-list');
  const row = (name, label, state, opens, open, line) => {
    const li = _el('li', 'apo-dev');
    const b = _el(opens ? 'button' : 'div', 'apo-dev-b');
    if (opens) {
      b.type = 'button';
      b.setAttribute('aria-label', `${name}, ${label}. Open it.`);
      b.addEventListener('click', open);
    }
    const { dot } = _dot(state);
    b.appendChild(dot);
    b.appendChild(_el('span', 'apo-row-t', name));
    b.appendChild(_el('span', 'apo-row-s', label));
    li.appendChild(b);
    if (line) li.appendChild(_el('p', 'apo-card-line', line));
    list.appendChild(li);
  };
  const c = M.computerCard(ws);
  row('Workstation', c.label, c.state === 'up' ? 'working' : 'waiting', c.opens, () => {
    import('./workstationScreen.js').then((m) => m.openWorkstationScreen({ focus: true })).catch(() => {});
  }, '');
  if (phone) {
    const p = M.phoneCard(phone);
    row(p.name, p.label, p.state === 'on' ? 'working' : 'waiting', p.opens, () => {
      import('./phoneWindow.js').then((m) => m.openPhone()).catch(() => {});
    }, p.sentence);
  }
  s.appendChild(list);
  return s;
}

function _reachToggle() {
  const wrap = _el('span', 'apo-reach');
  wrap.setAttribute('role', 'group');
  wrap.setAttribute('aria-label', 'Which activity to show');
  for (const [key, words] of [['here', 'This space'], ['all', 'All']]) {
    const b = _btn(`apo-small apo-reach-b${_reach === key ? ' apo-on' : ''}`, words, () => {
      if (_reach === key) return;
      _reach = key;
      _showAll = false;
      _refresh();
    });
    b.setAttribute('aria-pressed', String(_reach === key));
    wrap.appendChild(b);
  }
  return wrap;
}

function _activitySection(tasks, spaces = []) {
  const all = Array.isArray(tasks) ? tasks : [];
  const s = _section('Activity', spaces.length ? _reachToggle() : null);
  const names = new Map(spaces.map((x) => [x.id, x.name]));
  if (!all.length) {
    s.appendChild(_el('p', 'apo-empty', 'Nothing yet. Ask Apollo for something in the chat and it shows here.'));
    return s;
  }
  const { rows, more } = M.activityRows(all, { limit: _showAll ? all.length : 6 });
  const list = _el('ul', 'apo-list');
  for (const t of rows) {
    const li = _el('li', 'apo-row');
    li.dataset.taskId = t.id;
    const b = _el('button', 'apo-row-b');
    b.type = 'button';
    const { dot, words } = _dot(t.state);
    b.appendChild(dot);
    b.appendChild(_el('span', 'apo-row-t', t.title));
    const where = _reach === 'all' && t.space_id ? names.get(t.space_id) : '';
    if (where) b.appendChild(_el('span', 'apo-row-sp', where));
    b.appendChild(_el('span', 'apo-row-s', words));
    b.setAttribute('aria-label', where ? `${t.title}, in ${where}, ${words}` : `${t.title}, ${words}`);
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

/** Phase 5b. The agents being made for the person, from gaps a lead found. */
function _madeSection(proposals) {
  const list = M.madeList(proposals);
  if (!list.length) return null;
  const s = _section('Agents being made');
  const ul = _el('ul', 'apo-list');
  for (const p of list) {
    const li = _el('li', `apo-out apo-made apo-made-${p.state}`);
    li.appendChild(_el('p', 'apo-out-t', p.agent_name ? `${p.agent_name}: ${p.need}` : p.need));
    li.appendChild(_el('p', 'apo-out-line', `${p.state_words}. ${p.sentence || ''}`.trim()));
    if (p.state === 'failed') {
      li.appendChild(_btn('apo-link', 'Try again', async () => {
        try { await _api(`/api/apollo/agents/proposals/${encodeURIComponent(p.id)}/retry`, { method: 'POST' }); }
        catch (err) { _say(err.message); }
        _refresh();
      }));
    }
    ul.appendChild(li);
  }
  s.appendChild(ul);
  return s;
}

async function _review(path, body, said) {
  try {
    await _api(path, { method: 'POST', body: body || {} });
    if (said) _say(said);
  } catch (err) { _say(err.message); }
  _editing = '';
  _refresh();
}

function _proposalRow(p) {
  const li = _el('li', 'apo-out apo-review');
  const asks = p.asks_for || {};
  li.appendChild(_el('p', 'apo-out-t', `${asks.name || p.agent_name || 'New agent'}${p.version ? ` ${p.version}` : ''}`));
  li.appendChild(_el('p', 'apo-out-line', `For: ${p.need}`));
  li.appendChild(_el('p', 'apo-out-line', `Why: ${p.why}`));
  if (p.text) li.appendChild(_el('p', 'apo-out-line apo-review-asks', M.asksLine(asks)));
  const proof = M.proofLine(p);
  li.appendChild(_el('p', 'apo-out-line', proof || `${p.state_words}. ${p.sentence || ''}`.trim()));
  const id = encodeURIComponent(p.id);
  if (_editing === `agent:${p.id}`) {
    const box = _el('textarea', 'apo-input apo-review-text');
    box.value = _agentDraft;
    box.rows = 14;
    box.setAttribute('aria-label', 'The agent file');
    box.addEventListener('input', () => { _agentDraft = box.value; });
    li.appendChild(box);
    const row = _el('div', 'apo-acts');
    row.appendChild(_btn('apo-primary', 'Prove it again', () => _review(`/api/apollo/agents/review/${id}/edit`,
      { text: _agentDraft }, 'Proving the edit.')));
    row.appendChild(_btn('', 'Cancel', () => { _editing = ''; _refresh(); }));
    li.appendChild(row);
    return li;
  }
  const row = _el('div', 'apo-acts');
  if (p.state === 'waiting' && p.proof) {
    row.appendChild(_btn('apo-primary', 'Approve', () => _review(`/api/apollo/agents/review/${id}/approve`,
      null, 'Published. Anyone on this server can hire it.'), `Approve ${asks.name || 'this agent'} for everyone`));
  }
  if (p.state === 'waiting' && p.text) {
    row.appendChild(_btn('', 'Edit', () => { _editing = `agent:${p.id}`; _agentDraft = p.text; _refresh(); }));
  }
  row.appendChild(_btn('', 'Reject', () => _review(`/api/apollo/agents/review/${id}/reject`, {}, 'Turned down.')));
  li.appendChild(row);
  return li;
}

/** A published platform agent: a new version, proven before it's approved,
 *  or a step back to an earlier one. */
function _platformRow(a) {
  const li = _el('li', 'apo-out apo-platform');
  const id = encodeURIComponent(a.id);
  li.appendChild(_el('p', 'apo-out-t', `${a.name}: version ${a.live || 'none'} is live`));
  if (_editing === `update:${a.id}`) {
    const box = _el('textarea', 'apo-input apo-review-text');
    box.value = _agentDraft;
    box.rows = 14;
    box.setAttribute('aria-label', `The new version of ${a.name}`);
    box.addEventListener('input', () => { _agentDraft = box.value; });
    li.appendChild(box);
    li.appendChild(_el('p', 'apo-out-line', 'Give it a new version number. It is proven before you can approve it.'));
    const row = _el('div', 'apo-acts');
    row.appendChild(_btn('apo-primary', 'Prove it', () => _review(`/api/apollo/agents/platform/${id}/update`,
      { text: _agentDraft }, 'Proving the new version.')));
    row.appendChild(_btn('', 'Cancel', () => { _editing = ''; _refresh(); }));
    li.appendChild(row);
    return li;
  }
  const row = _el('div', 'apo-acts');
  row.appendChild(_btn('', 'New version', async () => {
    try {
      const src = await _api(`/api/agents/${id}/source`);
      _agentDraft = (src && src.text) || '';
      _editing = `update:${a.id}`;
    } catch (err) { _say(err.message); }
    _refresh();
  }));
  for (const v of (a.versions || [])) {
    if (v.version === a.live) continue;
    row.appendChild(_btn('apo-link', `Roll back to ${v.version}`, () => _review(
      `/api/apollo/agents/platform/${id}/rollback`, { version: v.version }, `${a.name} is back on ${v.version}.`)));
  }
  li.appendChild(row);
  return li;
}

/** Phase 5b, for an admin: drafted agents waiting on a decision, and the
 *  platform agents' versions. Hidden when the server says this isn't an admin. */
function _reviewSection(review) {
  if (!review) return null;
  const waiting = review.waiting || [];
  const published = review.published || [];
  if (!waiting.length && !published.length) return null;
  const s = _section(waiting.length ? 'New agents to approve' : 'Agents made here');
  s.appendChild(_el('p', 'apo-empty', 'An approved agent joins the roster for everyone on this server.'));
  const ul = _el('ul', 'apo-list');
  for (const p of waiting) ul.appendChild(_proposalRow(p));
  for (const a of published) ul.appendChild(_platformRow(a));
  s.appendChild(ul);
  return s;
}

function _spacesSection(state, spaces) {
  const kids = (state && Array.isArray(state.children)) ? state.children : [];
  const here = state && state.space;
  if (!kids.length && !here && spaces.length) return null;
  const s = _section('Spaces', here
    ? _btn('apo-link', 'About this space', () => { _view = 'space'; _deleting = ''; _refresh(); })
    : null);
  if (!kids.length) {
    s.appendChild(_el('p', 'apo-empty', here
      ? 'No spaces inside this one.'
      : 'Keep work apart with spaces, like one for a job and one for home. Make one from the switcher at the top.'));
    return s;
  }
  const list = _el('ul', 'apo-list');
  for (const k of kids) {
    const li = _el('li', 'apo-row');
    const b = _el('button', 'apo-row-b');
    b.type = 'button';
    if (k.sealed) {
      const lock = _el('span', 'apo-lock');
      lock.innerHTML = Sp.LOCK_ICON;   // a constant, never server text
      b.appendChild(lock);
    }
    b.appendChild(_el('span', 'apo-row-t', k.name));
    b.appendChild(_el('span', 'apo-row-s', M.childLine(k)));
    b.setAttribute('aria-label', `${k.name}. ${M.childLine(k)} Go there`);
    b.addEventListener('click', () => Sp.switchTo(k.id));
    li.appendChild(b);
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
  const reach = _reachParam();
  const [state, tasksOut, notesOut, ws, apprOut, phone, spaces, rhythm, voice, trustOut, madeOut, review] = await Promise.all([
    _api(`/api/apollo/state?space=${_here()}`),
    _api(`/api/apollo/tasks?space=${reach}`),
    _api(`/api/apollo/notebook?kind=open_loop&state=open&space=${reach}`),
    fetch('/api/workstation/status', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    _api(`/api/apollo/approvals?space=${reach}`).catch(() => null),
    fetch('/api/workstation/phone', { credentials: 'same-origin', cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    Sp.loadSpaces().catch(() => Sp.spaceList()),
    _api('/api/apollo/rhythm').catch(() => null),
    _api('/api/apollo/voice').catch(() => null),
    _api(`/api/apollo/trust?space=${reach}`).catch(() => null),
    _api('/api/apollo/agents/proposals').catch(() => null),
    fetch('/api/apollo/agents/review', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  if (gen !== _gen || !_win) return;
  const tasks = (tasksOut && tasksOut.tasks) || [];
  _setStatus(state);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_profile(state));
  const trustRows = (trustOut && trustOut.trust) || [];
  const needs = _needsSection(M.needsYou(tasks), (apprOut && apprOut.approvals) || [],
    M.lockedNeeds(spaces, Sp.currentSpace()), trustRows.filter((t) => t.state === 'offered'));
  if (needs) body.appendChild(needs);
  body.appendChild(_computerSection(ws));
  body.appendChild(_devicesSection(ws, phone));
  body.appendChild(_activitySection(tasks, spaces));
  const room = _spacesSection(state, spaces);
  if (room) body.appendChild(room);
  const outs = _outputsSection(tasks);
  if (outs) body.appendChild(outs);
  const made = _madeSection(madeOut && madeOut.proposals);
  if (made) body.appendChild(made);
  const rev = _reviewSection(review);
  if (rev) body.appendChild(rev);
  const loops = _loopsSection(notesOut && notesOut.notes);
  if (loops) body.appendChild(loops);
  body.appendChild(_rhythmSection(rhythm));
  if (voice) body.appendChild(_voiceSection(voice));
  body.appendChild(_orbSection());
  const just = _justDoesSection(trustRows.filter((t) => t.state === 'granted'));
  if (just) body.appendChild(just);
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
  // The orb reads the same headline, so it needn't ask the server again.
  document.dispatchEvent(new CustomEvent('pantheon:apollo-state', { detail: { tone: hl.tone } }));
}

/* ───────────── the task view ───────────── */

function _back(label = 'Back') {
  return _btn('apo-back', `‹ ${label}`, () => { _view = 'main'; _editing = ''; _dropChat(); _refresh(); }, 'Back to Apollo');
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

function _teamSection(team) {
  const members = (team && team.members) || [];
  const log = (team && team.messages) || [];
  if (members.length < 2 && !log.length) return null;
  const sec = _el('section', 'apo-sec apo-team');
  sec.appendChild(_el('h6', 'apo-sec-t', 'Team'));
  const names = {};
  for (const m of members) if (m.lead) names[m.lead] = m.lead_name || m.lead;
  const ul = _el('ul', 'apo-list');
  for (const m of members) {
    const li = _el('li', `apo-row apo-team-m apo-team-d${Math.min(Number(m.depth) || 0, 3)}`);
    const b = _el('button', 'apo-row-b');
    b.type = 'button';
    const { dot, words } = _dot(m.state);
    const who = `${m.lead_name || m.lead || 'No lead'}, ${M.teamRole(m).toLowerCase()}`;
    b.appendChild(dot);
    b.appendChild(_el('span', 'apo-row-t', m.title));
    b.appendChild(_el('span', 'apo-row-sp', who));
    b.appendChild(_el('span', 'apo-row-s', words));
    b.setAttribute('aria-label', `${m.title}, ${who}, ${words}`);
    if (String(m.id) === String(_taskId)) b.setAttribute('aria-current', 'true');
    else b.addEventListener('click', () => { _dropChat(); _openTask(m.id); });
    li.appendChild(b);
    ul.appendChild(li);
  }
  sec.appendChild(ul);
  if (log.length) {
    const ol = _el('ol', 'apo-team-log');
    for (const msg of log.slice(-8)) ol.appendChild(_el('li', `apo-team-l apo-team-${msg.kind}`, M.teamLine(msg, names)));
    sec.appendChild(ol);
  }
  return sec;
}

async function _drawTask(gen) {
  const [state, task, team] = await Promise.all([
    _api('/api/apollo/state'),
    _api(`/api/apollo/tasks/${encodeURIComponent(_taskId)}`),
    _api(`/api/apollo/tasks/${encodeURIComponent(_taskId)}/team`).catch(() => null),
  ]);
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
  const teamSec = _teamSection(team);
  if (teamSec) body.appendChild(teamSec);
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
  const started = !!(task.session_id || task.hire_id);
  const floating = started && isTaskChatFloating(task.id);
  if (started) {
    acts.appendChild(_btn('', floating ? 'Show its chat' : 'Pop out chat', () => {
      _dropChat();
      popOutTaskChat(task.id, { title: task.title });
      _refresh();
    }, floating ? 'Show this task\'s chat window' : 'Open this task\'s chat in its own window'));
  }
  if (acts.childNodes.length) body.appendChild(acts);
  // The task chat, under the report: kept across redraws so a half-typed
  // message and its scroll survive the pane's refresh.
  if (started && !floating) {
    if (!_chat || _chat.taskId !== String(task.id)) {
      _dropChat();
      _chat = createTaskChat(task.id);
    }
    body.appendChild(_chat.el);
    _win.modal.classList.add('apo-wide');
  } else {
    _dropChat();
  }
}

function _dropChat() {
  if (_chat) { _chat.destroy(); _chat = null; }
  if (_win) _win.modal.classList.remove('apo-wide');
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
        await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}?space=${_here()}`, { method: 'PATCH', body: { text: input.value } });
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
  if (line.via_grant) {
    // Read through a grant: it informs this space and is changed only in its own.
    li.appendChild(_el('span', 'apo-line-why', `From ${line.space}, read only.`));
    return li;
  }
  if (line.space && line.space_id !== Sp.currentSpace()) {
    li.appendChild(_el('span', 'apo-line-why', `Kept in ${line.space}.`));
  }
  const acts = _el('span', 'apo-acts');
  if (line.basis !== 'stated') {
    acts.appendChild(_btn('apo-small', 'That is right', async () => {
      try {
        await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}/confirm?space=${_here()}`, { method: 'POST' });
        _say('Confirmed.');
        _refresh();
      } catch (err) { _say(err.message); }
    }, `Confirm: ${line.text}`));
  }
  acts.appendChild(_btn('apo-small', 'Edit', () => { _editing = line.id; _refresh(); }, `Edit: ${line.text}`));
  acts.appendChild(_btn('apo-small', 'Forget', async () => {
    try {
      await _api(`/api/apollo/knows/${encodeURIComponent(line.id)}?space=${_here()}`, { method: 'DELETE' });
      _say('Forgotten.');
      _refresh();
    } catch (err) { _say(err.message); }
  }, `Forget: ${line.text}`));
  li.appendChild(acts);
  return li;
}

async function _drawKnows(gen) {
  const [state, out] = await Promise.all([
    _api(`/api/apollo/state?space=${_here()}`), _api(`/api/apollo/knows?space=${_here()}`)]);
  if (gen !== _gen || !_win) return;
  _setStatus(state);
  const { stated, inferred } = M.knowsGroups(out && out.lines);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_back());
  body.appendChild(_el('h5', 'apo-task-t', 'What Apollo knows'));
  if (state && state.space) {
    body.appendChild(_el('p', 'apo-empty', `In ${M.spaceLabel(state.space)}: what's kept here and above it, and anything this space was given read of.`));
  }

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
      await _api(`/api/apollo/knows?space=${_here()}`, { method: 'POST', body: { text } });
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

/* ───────────── the space view ───────────── */

function _switchRow(text, hint, on, disabled, onChange) {
  const row = _el('label', 'apo-switch');
  const box = _el('input');
  box.type = 'checkbox';
  box.checked = !!on;
  box.disabled = !!disabled;
  box.addEventListener('change', () => onChange(box.checked, box));
  row.appendChild(box);
  const words = _el('span', 'apo-switch-w');
  words.appendChild(_el('span', 'apo-switch-t', text));
  if (hint) words.appendChild(_el('span', 'apo-switch-h', hint));
  row.appendChild(words);
  return row;
}

function _readRow(r) {
  const li = _el('li', 'apo-line');
  li.appendChild(_el('span', 'apo-line-t', M.contextLine(r)));
  if (r.grant_id) {
    const acts = _el('span', 'apo-acts');
    acts.appendChild(_btn('apo-small', 'Revoke', async () => {
      try {
        await _api(`/api/apollo/grants/${encodeURIComponent(r.grant_id)}`, { method: 'DELETE' });
        _say('Revoked.');
        _refresh();
      } catch (err) { _say(err.message); }
    }, `Revoke: ${M.contextLine(r)}`));
    li.appendChild(acts);
  }
  return li;
}

async function _drawSpace(gen) {
  const id = Sp.currentSpace();
  if (!id) { _view = 'main'; await _drawMain(gen); return; }
  const key = encodeURIComponent(id);
  const [state, ctx, spaces] = await Promise.all([
    _api(`/api/apollo/state?space=${key}`),
    _api(`/api/apollo/spaces/${key}/context`),
    Sp.loadSpaces().catch(() => Sp.spaceList()),
  ]);
  if (gen !== _gen || !_win) return;
  _setStatus(state);
  const sp = ctx.space;
  const patch = async (fields, said) => {
    try {
      await _api(`/api/apollo/spaces/${key}`, { method: 'PATCH', body: fields });
      if (said) _say(said);
      await Sp.loadSpaces().catch(() => null);
      Sp.noteSpace(id);
    } catch (err) { _say(err.message); }
    _refresh();
  };
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_back());
  body.appendChild(_el('h5', 'apo-task-t', M.spaceLabel(sp)));

  const name = _el('form', 'apo-add');
  const input = _el('input', 'apo-input');
  input.type = 'text';
  input.value = sp.name || '';
  input.maxLength = 60;
  input.setAttribute('aria-label', 'Name of this space');
  const save = _el('button', 'apo-btn', 'Rename');
  save.type = 'submit';
  name.appendChild(input);
  name.appendChild(save);
  name.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (text && text !== sp.name) patch({ name: text }, 'Renamed.');
  });
  body.appendChild(name);

  const edges = _section('Edges');
  const inherited = sp.sealed && !sp.airgapped;
  edges.appendChild(_switchRow('Airgapped',
    inherited ? 'A space above this one is airgapped, so this one is too.'
      : "Nothing outside reads in, and it reads nothing outside. Turning it on ends this space's grants.",
    sp.sealed, inherited, (on) => patch({ airgapped: on }, on ? 'Airgapped.' : 'The airgap is off.')));
  edges.appendChild(_switchRow('Local models only',
    sp.airgapped ? "Nothing here goes to a paid model's server." : 'Needs this space airgapped first.',
    sp.local_only, !sp.airgapped, (on) => patch({ local_only: on }, on ? 'Local models only here.' : 'Any model may work here.')));
  body.appendChild(edges);

  const from = _section('Reads from');
  const fromRows = ctx.reads_from || [];
  if (fromRows.length) {
    const list = _el('ul', 'apo-list');
    fromRows.forEach((r) => list.appendChild(_readRow(r)));
    from.appendChild(list);
  } else from.appendChild(_el('p', 'apo-empty', sp.sealed ? 'Nothing. It is airgapped.' : 'Nothing but what it holds.'));
  const sources = M.grantSources(spaces, id, ctx, 'memory');
  const sourcesOut = M.grantSources(spaces, id, ctx, 'outcomes');
  if (!sp.sealed && (sources.length || sourcesOut.length)) {
    const give = _el('form', 'apo-add apo-give');
    const scope = _el('select', 'apo-input');
    scope.setAttribute('aria-label', 'What this space may read');
    for (const [v, words] of [['memory', 'What you told Apollo'], ['outcomes', 'What tasks came to']]) {
      const o = _el('option', '', words);
      o.value = v;
      scope.appendChild(o);
    }
    const src = _el('select', 'apo-input');
    src.setAttribute('aria-label', 'In which space');
    const fill = () => {
      src.textContent = '';
      for (const x of M.grantSources(spaces, id, ctx, scope.value)) {
        const o = _el('option', '', x.path || x.name);
        o.value = x.id;
        src.appendChild(o);
      }
    };
    fill();
    scope.addEventListener('change', fill);
    const add = _el('button', 'apo-btn apo-primary', 'Let it read');
    add.type = 'submit';
    give.appendChild(_el('span', 'apo-give-w', 'Let this space read'));
    give.appendChild(scope);
    give.appendChild(_el('span', 'apo-give-w', 'in'));
    give.appendChild(src);
    give.appendChild(add);
    give.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!src.value) return;
      try {
        await _api(`/api/apollo/spaces/${key}/grants`, { method: 'POST', body: { source_id: src.value, scope: scope.value } });
        _say('Done. It reads that from now on, and can change none of it.');
        _refresh();
      } catch (err) { _say(err.message); }
    });
    from.appendChild(give);
  }
  body.appendChild(from);

  const by = _section('Read by');
  const byRows = ctx.read_by || [];
  if (byRows.length) {
    const list = _el('ul', 'apo-list');
    byRows.forEach((r) => list.appendChild(_readRow(r)));
    by.appendChild(list);
  } else by.appendChild(_el('p', 'apo-empty', 'No other space reads this one.'));
  body.appendChild(by);

  const uses = ctx.uses || [];
  if (uses.length) {
    const u = _section('Last reads');
    const list = _el('ul', 'apo-list');
    for (const x of uses) list.appendChild(_el('li', 'apo-line apo-line-t', x.what));
    u.appendChild(list);
    body.appendChild(u);
  }

  const del = _section('Delete');
  del.appendChild(_el('p', 'apo-empty', 'Only an empty space can go: move or finish its tasks, and delete the spaces inside it, first.'));
  del.appendChild(_btn(`apo-small${_deleting === id ? ' apo-danger' : ''}`,
    _deleting === id ? 'Press again to delete' : 'Delete this space', async () => {
      if (_deleting !== id) { _deleting = id; _refresh(); return; }
      _deleting = '';
  _agentDraft = '';
      try {
        await _api(`/api/apollo/spaces/${key}`, { method: 'DELETE' });
        _say('Deleted.');
        _view = 'main';
        await Sp.switchTo(sp.parent_id || null);
      } catch (err) { _say(err.message); _refresh(); }
    }, `Delete ${sp.name}`));
  body.appendChild(del);
}

/* ───────────── rhythm: when Apollo speaks unasked ───────────── */

function _rhythmSection(r) {
  const sec = _section('When Apollo speaks');
  sec.appendChild(_el('p', 'apo-empty', r ? M.rhythmLine(r) : 'Briefings and check-ins could not be read just now.'));
  sec.appendChild(_btn('apo-link', 'Briefings and check-ins', () => { _view = 'rhythm'; _refresh(); }));
  return sec;
}

/* ───────────── the orb (phase 6) ───────────── */

// Both switches live in this browser (`apolloOrb.js`): the orb is how this
// screen looks, like reduced motion, not a fact about the person.
function _orbSection() {
  const sec = _section('The orb');
  sec.appendChild(_switchRow('Show the orb', 'Apollo’s light, over the page while this chat is open. Drag it anywhere; click it for this pane.',
    Orb.orbShown(), false, (on) => { Orb.setOrbShown(on); _say(on ? 'The orb is back.' : 'The orb is put away.'); }));
  sec.appendChild(_switchRow('Keep it still', 'No breathing or gliding. Your system’s reduced motion does this too.',
    Orb.orbStill(), false, (on) => { Orb.setOrbStill(on); _say(on ? 'It keeps still now.' : 'It moves again.'); }));
  return sec;
}

/* ───────────── voice: one character, a few dials ───────────── */

function _voiceSection(v) {
  const sec = _section('Voice');
  const put = async (fields, said) => {
    try {
      await _api('/api/apollo/voice', { method: 'PUT', body: fields });
      if (said) _say(said);
    } catch (err) { _say(err.message); }
    _refresh();
  };
  const presets = _el('div', 'apo-presets');
  presets.setAttribute('role', 'group');
  presets.setAttribute('aria-label', 'Starting points');
  for (const p of v.presets || []) {
    const b = _btn(`apo-chip${v.preset === p.id ? ' apo-on' : ''}`, p.name, () => put({ preset: p.id }, `${p.name} it is.`));
    b.setAttribute('aria-pressed', String(v.preset === p.id));
    presets.appendChild(b);
  }
  sec.appendChild(presets);
  for (const dial of ['warmth', 'play']) {
    const [lo, hi] = M.DIAL_ENDS[dial];
    const row = _el('label', 'apo-dial');
    row.appendChild(_el('span', 'apo-dial-end', lo));
    const r = _el('input', 'apo-range');
    r.type = 'range';
    r.min = '-2';
    r.max = '2';
    r.step = '1';
    r.value = String(v[dial] || 0);
    r.setAttribute('aria-label', `${lo} to ${hi}`);
    r.setAttribute('aria-valuetext', M.dialWords(dial, v[dial]));
    r.addEventListener('change', () => {
      const n = Number(r.value) || 0;
      if (n === (v[dial] || 0)) return;
      put({ [dial]: n }, `${M.dialWords(dial, n)}.`);
    });
    row.appendChild(r);
    row.appendChild(_el('span', 'apo-dial-end', hi));
    sec.appendChild(row);
  }
  for (const n of v.nudges || []) {
    const li = _el('div', 'apo-nudge');
    li.appendChild(_el('span', 'apo-nudge-t', n.words));
    li.appendChild(_btn('apo-small', 'Undo', async () => {
      try {
        await _api(`/api/apollo/voice/undo/${encodeURIComponent(n.id)}`, { method: 'POST' });
        _say('Put back.');
      } catch (err) { _say(err.message); }
      _refresh();
    }, `Undo: ${n.words}`));
    sec.appendChild(li);
  }
  sec.appendChild(_el('p', 'apo-empty', 'Apollo still tells you when a plan has a hole or you’re wrong. No setting turns that off.'));
  sec.appendChild(_el('p', 'apo-empty apo-held', M.heldLine(v.held)));
  return sec;
}

async function _drawRhythm(gen) {
  const [state, r] = await Promise.all([
    _api(`/api/apollo/state?space=${_here()}`),
    _api('/api/apollo/rhythm'),
  ]);
  if (gen !== _gen || !_win) return;
  _setStatus(state);
  const body = _win.body;
  body.textContent = '';
  body.appendChild(_back());
  body.appendChild(_el('h5', 'apo-task-t', 'When Apollo speaks'));
  const zone = r.timezone ? ` Times are in ${r.timezone}.` : '';
  body.appendChild(_el('p', 'apo-empty',
    `Briefings come at the times you set. Check-ins speak only when something changed, and never in quiet hours.${zone}`));
  if (!r.has_chat) {
    body.appendChild(_el('p', 'apo-error', 'Open your Apollo chat once first, so Apollo has somewhere to speak.'));
    return;
  }
  const put = async (fields, said) => {
    try {
      await _api('/api/apollo/rhythm', { method: 'PUT', body: fields });
      if (said) _say(said);
    } catch (err) { _say(err.message); }
    _refresh();
  };
  const list = (r.briefings || []).map((b) => ({ id: b.id, time: b.time, enabled: b.enabled }));

  const brief = _section('Briefings');
  if (!list.length) brief.appendChild(_el('p', 'apo-empty', 'None yet. The first of the day is First light.'));
  const ul = _el('ul', 'apo-list');
  (r.briefings || []).forEach((b, i) => {
    const li = _el('li', 'apo-line apo-brief');
    li.appendChild(_el('span', 'apo-brief-n', b.name));
    const when = _el('input', 'apo-input apo-time');
    when.type = 'time';
    when.value = b.time;
    when.setAttribute('aria-label', `${b.name} time`);
    when.addEventListener('change', () => {
      if (!when.value || when.value === b.time) return;
      const next = list.map((x, j) => (j === i ? { ...x, time: when.value } : x));
      put({ briefings: next }, 'Moved.');
    });
    li.appendChild(when);
    li.appendChild(_switchRow('On', '', b.enabled, false, (on) => {
      const next = list.map((x, j) => (j === i ? { ...x, enabled: on } : x));
      put({ briefings: next }, on ? `${b.name} is on.` : `${b.name} is paused.`);
    }));
    const acts = _el('span', 'apo-acts');
    acts.appendChild(_btn('apo-small', 'Remove', () => {
      put({ briefings: list.filter((_, j) => j !== i) }, 'Removed.');
    }, `Remove ${b.name} at ${b.time}`));
    li.appendChild(acts);
    ul.appendChild(li);
  });
  if (list.length) brief.appendChild(ul);
  const at = M.nextBriefingTime(list);
  if (list.length < 6 && at) {
    brief.appendChild(_btn('apo-btn', list.length ? 'Add a briefing' : 'Add First light',
      () => put({ briefings: [...list, { time: at, enabled: true }] }, `Added at ${at}. Change the time if you like.`)));
  }
  body.appendChild(brief);

  const chk = _section('Check-ins');
  chk.appendChild(_el('p', 'apo-empty', 'Between briefings Apollo looks, and says something only if a task needs you, finished, or waits for your yes.'));
  const pick = _el('select', 'apo-input apo-select');
  pick.setAttribute('aria-label', 'How often check-ins look');
  for (const h of M.CHECKIN_HOURS) {
    const o = _el('option', '', M.checkinLabel(h));
    o.value = String(h);
    if (h === (Number(r.checkin_hours) || 0)) o.selected = true;
    pick.appendChild(o);
  }
  pick.addEventListener('change', () => {
    const h = Number(pick.value) || 0;
    put({ checkin_hours: h }, h ? `Check-ins ${M.checkinLabel(h).toLowerCase()}.` : 'Check-ins are off.');
  });
  chk.appendChild(pick);
  chk.appendChild(_el('p', 'apo-empty', M.lastSpoke(r.last_spoke_at)));
  body.appendChild(chk);

  const q = r.quiet || {};
  const quiet = _section('Quiet hours');
  const form = _el('form', 'apo-quiet');
  const from = _el('input', 'apo-input apo-time');
  from.type = 'time';
  from.value = q.start || '';
  from.setAttribute('aria-label', 'Quiet from');
  const to = _el('input', 'apo-input apo-time');
  to.type = 'time';
  to.value = q.end || '';
  to.setAttribute('aria-label', 'Quiet until');
  form.appendChild(_el('span', '', 'From'));
  form.appendChild(from);
  form.appendChild(_el('span', '', 'until'));
  form.appendChild(to);
  const save = _el('button', 'apo-btn apo-primary', 'Save');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!from.value || !to.value) { _say('Quiet hours need a start and an end.'); return; }
    put({ quiet: { start: from.value, end: to.value } }, `Quiet ${from.value} to ${to.value}.`);
  });
  quiet.appendChild(form);
  if (q.start && q.end) {
    quiet.appendChild(_btn('apo-small', 'No quiet hours', () => put({ quiet: { start: null, end: null } }, 'Quiet hours are off.')));
  }
  body.appendChild(quiet);
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
    else if (_view === 'space') await _drawSpace(gen);
    else if (_view === 'rhythm') await _drawRhythm(gen);
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
      if (_win && active && _win.modal.contains(active) && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
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
  _dropChat();
  if (_offSpace) { _offSpace(); _offSpace = null; }
  if (_win.switcher) _win.switcher.destroy();
  const modal = _win.modal;
  _win = null;
  _view = 'main';
  _taskId = '';
  _editing = '';
  _showAll = false;
  _reach = 'here';
  _deleting = '';
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
  // Moving Apollo to another space shows that space from the top.
  _offSpace = Sp.onSpaceChange(() => {
    _view = 'main';
    _taskId = '';
    _editing = '';
    _deleting = '';
    _showAll = false;
    _dropChat();
    _refresh();
  });
  Modals.injectMinimizeButton(_win.modal, MODAL_ID);
  makeWindowDraggable(_win.modal, {
    content: _win.content, header: _win.header,
    skipSelector: 'button, input, textarea, select, label, form', minWidth: 300, minHeight: 360,
  });
  _refresh();
  return true;
}

export function closeApolloPane() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

export function isApolloPaneOpen() { return !!_win; }
