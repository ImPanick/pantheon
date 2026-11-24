// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloDeck.js — Apollo's page: the deck the work runs on.
//
// The owner's test on a fresh deploy (2026-11-24): Apollo was "another
// ordinary chat ... no tells that it spawned another agent, there's no
// planning, delegation, nothing", and Apollo "must be entirely different from
// the normal chat plane". The shape he chose:
//
//   - Goals rail (left): every goal as a card with its state, its lead and its
//     spend. New goal makes the task and picks its lead on the server
//     (`POST /api/apollo/tasks`, which starts the lead's run), so a goal is
//     staffed whether or not the model would have called a tool for it.
//   - Board (centre): the open goal's plan (the goal and every delegate under
//     it, each with its owner and state), who is on it now, the handoffs
//     between agents, and the lead's own chat, live.
//   - Needs you (right): questions and approvals, answered in place.
//   - Home (no goal open): what moved since the person last looked, what is
//     running, what needs them, and what has been spent.
//   - Apollo's line (bottom): the chat's composer and a short thread under the
//     deck. What the person tells Apollo turns up on the board.
//
// The deck reads `/api/apollo/*` every few seconds while it is on the page and
// redraws a region only when what it shows changed, so an answer being typed
// is never wiped by a refresh.

import uiModule from './ui.js';
import * as M from './apolloPaneModel.js';
import * as D from './apolloDeckModel.js';
import * as Sp from './apolloSpaces.js';
import { createTaskChat } from './apolloTaskChat.js';

const DECK_ID = 'apollo-deck';
const POLL_MS = 5000;
const SEEN_KEY = 'pantheon.apollo.deckSeenAt';

let _deck = null;            // { root, rail, board, needs, form }
let _timer = null;
let _goal = null;            // the open goal's id; null is home
let _chat = null;            // the open goal's lead chat (`createTaskChat`)
let _sigs = {};              // what each region last drew, so a poll redraws only on change
let _seenAt = '';            // when the person last looked, for home's "since you last looked"
let _offSpace = null;
let _gen = 0;

function _say(msg) {
  try { uiModule.showToast(msg); } catch (_) { /* no toast host */ }
}

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
  b.addEventListener('click', onClick);
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

function _readSeen() {
  try { return localStorage.getItem(SEEN_KEY) || ''; } catch (_) { return ''; }
}

function _writeSeen(iso) {
  try { localStorage.setItem(SEEN_KEY, iso); } catch (_) { /* private window: home just shows nothing as moved */ }
}

function _section(title, cls) {
  const s = _el('section', `apo-deck-sec ${cls || ''}`.trim());
  s.appendChild(_el('h4', 'apo-deck-sec-t', title));
  return s;
}

function _dot(dot) {
  const d = _el('span', `apo-dot ${dot.cls}`);
  d.setAttribute('aria-hidden', 'true');
  return d;
}

// ── the rail ───────────────────────────────────────────────────────────────

function _card(task) {
  const c = D.cardOf(task);
  const b = _el('button', `apo-goal${task.id === _goal ? ' is-open' : ''}`);
  b.type = 'button';
  b.dataset.taskId = task.id;          // the orb finds a task by it (`apolloOrb.js`)
  b.setAttribute('aria-current', task.id === _goal ? 'true' : 'false');
  const top = _el('span', 'apo-goal-top');
  top.appendChild(_dot(c.dot));
  top.appendChild(_el('span', 'apo-goal-t', c.title));
  b.appendChild(top);
  const meta = _el('span', 'apo-goal-meta', [c.dot.words, c.lead, c.spend].filter(Boolean).join(' · '));
  b.appendChild(meta);
  if (c.line) b.appendChild(_el('span', 'apo-goal-line', c.line));
  b.addEventListener('click', () => openGoal(task.id));
  return b;
}

function _newGoalForm() {
  const form = _el('form', 'apo-newgoal');
  form.hidden = true;
  const title = _el('input', 'apo-input');
  title.type = 'text';
  title.maxLength = 120;
  title.placeholder = 'What do you want done?';
  title.setAttribute('aria-label', 'The goal');
  const brief = _el('textarea', 'apo-input');
  brief.rows = 3;
  brief.maxLength = 8000;
  brief.placeholder = 'Anything the lead should know (optional)';
  brief.setAttribute('aria-label', 'Brief for the lead');
  const acts = _el('div', 'apo-acts');
  const go = _el('button', 'apo-btn apo-primary', 'Start it');
  go.type = 'submit';
  acts.appendChild(go);
  acts.appendChild(_btn('', 'Cancel', () => { form.hidden = true; }));
  form.appendChild(title);
  form.appendChild(brief);
  form.appendChild(acts);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const words = title.value.trim();
    if (!words) { title.focus(); return; }
    go.disabled = true;
    try {
      const t = await _api('/api/apollo/tasks', {
        method: 'POST',
        body: { title: words, brief: brief.value.trim() || null, space_id: Sp.currentSpace(), start: true },
      });
      title.value = '';
      brief.value = '';
      form.hidden = true;
      _say(t.lead_agent ? `On it. ${t.lead_name || 'The lead'} is leading it.` : (t.next_step || 'Started.'));
      await openGoal(t.id);
    } catch (err) {
      _say(err.message);
    } finally {
      go.disabled = false;
    }
  });
  return { form, title };
}

function _drawRail(tasks) {
  const rows = D.railRows(tasks);
  const sig = JSON.stringify([_goal, rows.open.map(D.cardOf), rows.done.map(D.cardOf), rows.moreDone]);
  if (_sigs.rail === sig) return;
  _sigs.rail = sig;
  const list = _deck.railList;
  list.replaceChildren();
  if (!rows.open.length && !rows.done.length) {
    list.appendChild(_el('p', 'apo-deck-none', 'No goals yet. Start one and Apollo staffs it with a lead.'));
    return;
  }
  for (const t of rows.open) list.appendChild(_card(t));
  if (rows.done.length) {
    list.appendChild(_el('h5', 'apo-deck-sub', 'Done'));
    for (const t of rows.done) list.appendChild(_card(t));
    if (rows.moreDone) list.appendChild(_el('p', 'apo-deck-none', `${rows.moreDone} more done`));
  }
}

// ── Needs you ──────────────────────────────────────────────────────────────

function _answerBox(task) {
  const form = _el('form', 'apo-answer');
  const input = _el('input', 'apo-input');
  input.type = 'text';
  input.maxLength = 600;
  input.placeholder = 'Your answer';
  input.setAttribute('aria-label', `Answer: ${task.title}`);
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
      refresh();
    } catch (err) {
      _say(err.message);
    } finally {
      send.disabled = false;
    }
  });
  return form;
}

function _approvalRow(a) {
  const row = _el('div', 'apo-need');
  row.dataset.taskId = a.task_id;
  row.appendChild(_btn('apo-link apo-need-t', a.title, () => openGoal(a.task_id)));
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
    refresh();
  };
  acts.appendChild(_btn('apo-primary', 'Allow once', answer('approve_task', 'Allowed. The lead carries on.'), `Allow once: ${a.tool}`));
  acts.appendChild(_btn('', 'Deny', answer('deny', 'Denied. It was not done.'), `Deny: ${a.tool}`));
  row.appendChild(acts);
  return row;
}

function _drawNeeds(tasks, approvals) {
  const asks = M.needsYou(tasks);
  const sig = JSON.stringify([asks.map((t) => [t.id, t.title, t.question]), approvals.map((a) => a.approval_id)]);
  if (_sigs.needs === sig) return;
  _sigs.needs = sig;
  const box = _deck.needsList;
  box.replaceChildren();
  _deck.needsCount.textContent = String(asks.length + approvals.length);
  if (!asks.length && !approvals.length) {
    box.appendChild(_el('p', 'apo-deck-none', 'Nothing needs you.'));
    return;
  }
  for (const a of approvals) box.appendChild(_approvalRow(a));
  for (const t of asks) {
    const row = _el('div', 'apo-need');
    row.dataset.taskId = t.id;
    row.appendChild(_btn('apo-link apo-need-t', t.title, () => openGoal(t.id)));
    if (t.question) row.appendChild(_el('p', 'apo-q', t.question));
    row.appendChild(_answerBox(t));
    box.appendChild(row);
  }
}

// ── the board ──────────────────────────────────────────────────────────────

function _drawHome(tasks, approvals) {
  const h = D.home(tasks, approvals, _seenAt);
  const sig = JSON.stringify(['home', h]);
  if (_sigs.board === sig) return;
  _sigs.board = sig;
  const board = _deck.board;
  board.replaceChildren();
  board.appendChild(_el('h3', 'apo-board-t', h.headline));
  board.appendChild(_el('p', 'apo-board-meta', h.spent));
  const running = _section('Running now');
  if (h.running.length) {
    for (const r of h.running) {
      const b = _btn('apo-row', `${r.title} · ${r.lead}`, () => openGoal(r.id));
      b.dataset.taskId = r.id;
      running.appendChild(b);
    }
  } else running.appendChild(_el('p', 'apo-deck-none', 'Nothing is running.'));
  board.appendChild(running);
  const moved = _section('Since you last looked');
  if (h.moved.length) {
    for (const r of h.moved) {
      const b = _btn('apo-row', `${r.title} · ${r.words}`, () => openGoal(r.id));
      b.dataset.taskId = r.id;
      moved.appendChild(b);
    }
  } else moved.appendChild(_el('p', 'apo-deck-none', 'Nothing has moved.'));
  board.appendChild(moved);
}

async function _start(task) {
  try {
    const out = await _api(`/api/apollo/tasks/${encodeURIComponent(task.id)}/start`, { method: 'POST' });
    _say(out && out.started ? 'The lead is on it.' : (out && out.why) || 'It could not start.');
  } catch (err) { _say(err.message); }
  refresh();
}

function _drawGoal(task, team) {
  const steps = D.planSteps(team);
  const moves = D.handoffs(team);
  const now = D.runningNow(team);
  const sig = JSON.stringify(['goal', task, steps, moves, now]);
  if (_sigs.board === sig) return;
  _sigs.board = sig;
  const board = _deck.board;
  // The lead's chat is kept across redraws: it reads and streams on its own.
  if (_chat && _chat.el.parentNode) _chat.el.parentNode.removeChild(_chat.el);
  board.replaceChildren();

  const head = _el('header', 'apo-board-h');
  head.dataset.taskId = task.id;
  const t = _el('h3', 'apo-board-t');
  t.appendChild(_dot(M.dotOf(task.state)));
  t.appendChild(document.createTextNode(` ${task.title}`));
  head.appendChild(t);
  const c = D.cardOf(task);
  head.appendChild(_el('p', 'apo-board-meta', [c.dot.words, c.lead].join(' · ')));
  head.appendChild(_el('p', 'apo-board-meta', M.budgetLine(task)));
  const verb = M.runVerb(task);
  if (verb) {
    const acts = _el('div', 'apo-acts');
    acts.appendChild(_btn('apo-primary', verb, () => _start(task), `${verb}: ${task.title}`));
    head.appendChild(acts);
  }
  board.appendChild(head);

  if (task.state === 'needs_you' && task.question) {
    const ask = _section('Needs your answer', 'apo-deck-ask');
    ask.appendChild(_el('p', 'apo-q', task.question));
    ask.appendChild(_answerBox(task));
    board.appendChild(ask);
  } else if (task.state === 'done' && task.outcome) {
    const done = _section('Outcome');
    done.appendChild(_el('p', 'apo-card-line', task.outcome));
    board.appendChild(done);
  } else if (task.next_step) {
    const next = _section('Next');
    next.appendChild(_el('p', 'apo-card-line', task.next_step));
    board.appendChild(next);
  }

  const plan = _section('Plan');
  const ol = _el('ol', 'apo-plan');
  for (const s of steps) {
    const li = _el('li', 'apo-step');
    li.dataset.taskId = s.id;
    li.style.setProperty('--depth', String(s.depth));
    li.appendChild(_dot(s.dot));
    li.appendChild(_el('span', 'apo-step-t', s.title));
    li.appendChild(_el('span', 'apo-step-who', `${s.owner} · ${s.role} · ${s.dot.words}`));
    ol.appendChild(li);
  }
  plan.appendChild(ol);
  if (steps.length <= 1) plan.appendChild(_el('p', 'apo-deck-none', 'The lead hasn\'t handed any part of this on yet.'));
  board.appendChild(plan);

  const on = _section('On it now');
  if (now.length) {
    for (const r of now) on.appendChild(_el('p', 'apo-card-line', `${r.owner}: ${r.on}`));
  } else on.appendChild(_el('p', 'apo-deck-none', 'Nobody is running on this right now.'));
  board.appendChild(on);

  const log = _section('Handoffs');
  if (moves.length) {
    const ul = _el('ul', 'apo-moves');
    for (const m of moves) {
      const li = _el('li', `apo-move apo-move-${m.kind}`, m.line);
      ul.appendChild(li);
    }
    log.appendChild(ul);
  } else log.appendChild(_el('p', 'apo-deck-none', 'No handoffs yet.'));
  board.appendChild(log);

  if (!_chat || _chat.taskId !== String(task.id)) {
    _chat?.destroy();
    _chat = createTaskChat(task.id);
  }
  board.appendChild(_chat.el);
}

// ── the loop ───────────────────────────────────────────────────────────────

/** Read everything the deck shows and redraw what changed. */
export async function refresh() {
  if (!_deck) return;
  const gen = ++_gen;
  const space = Sp.spaceParam();
  let tasks = [];
  let approvals = [];
  try {
    const [t, a] = await Promise.all([
      _api(`/api/apollo/tasks?space=${encodeURIComponent(space)}`),
      _api(`/api/apollo/approvals?space=${encodeURIComponent(space)}`).catch(() => ({ approvals: [] })),
    ]);
    tasks = (t && t.tasks) || [];
    approvals = (a && a.approvals) || [];
  } catch (err) {
    if (gen === _gen && _deck) _deck.status.textContent = err.message;
    return;
  }
  if (gen !== _gen || !_deck) return;
  _deck.status.textContent = '';
  _drawRail(tasks);
  _drawNeeds(tasks, approvals);
  if (_goal) {
    let task = tasks.find((x) => x.id === _goal);
    let team = null;
    try {
      [task, team] = await Promise.all([
        task ? Promise.resolve(task) : _api(`/api/apollo/tasks/${encodeURIComponent(_goal)}`),
        _api(`/api/apollo/tasks/${encodeURIComponent(_goal)}/team`),
      ]);
    } catch (err) {
      // The goal went (removed, or another space's): back to home.
      if (gen === _gen && _deck) { _sigs = {}; openGoal(null); }
      return;
    }
    if (gen !== _gen || !_deck) return;
    _drawGoal(task, team);
  } else {
    _drawHome(tasks, approvals);
  }
}

/** Open a goal on the board; `null` is home. */
export async function openGoal(id) {
  _goal = id || null;
  _sigs.rail = null;
  _sigs.board = null;
  if (!_goal && _chat) { _chat.destroy(); _chat = null; }
  await refresh();
}

export function openGoalId() { return _goal; }

function _loop() {
  clearTimeout(_timer);
  _timer = setTimeout(async () => {
    try { await refresh(); } finally { if (_deck) _loop(); }
  }, POLL_MS);
}

/** Put the deck on the page, before the chat thread. */
export function mountDeck() {
  if (_deck) return _deck.root;
  const host = document.getElementById('chat-container');
  const history = document.getElementById('chat-history');
  if (!host) return null;
  _seenAt = _readSeen();
  _writeSeen(new Date().toISOString());

  const root = _el('section', 'apo-deck');
  root.id = DECK_ID;
  root.setAttribute('aria-label', 'Apollo');

  const rail = _el('aside', 'apo-deck-rail');
  rail.setAttribute('aria-label', 'Goals');
  const railHead = _el('div', 'apo-deck-rail-h');
  railHead.appendChild(_btn('apo-home', 'Home', () => openGoal(null), 'Apollo home'));
  const { form, title } = _newGoalForm();
  railHead.appendChild(_btn('apo-primary', 'New goal', () => { form.hidden = !form.hidden; if (!form.hidden) title.focus(); }));
  rail.appendChild(railHead);
  rail.appendChild(form);
  const railList = _el('div', 'apo-deck-goals');
  rail.appendChild(railList);

  const board = _el('div', 'apo-deck-board');
  board.setAttribute('aria-live', 'polite');

  const needs = _el('aside', 'apo-deck-needs apo-needs');
  needs.setAttribute('aria-label', 'Needs you');
  const needsHead = _el('h4', 'apo-deck-sec-t', 'Needs you ');
  const needsCount = _el('span', 'apo-count', '0');
  needsHead.appendChild(needsCount);
  needs.appendChild(needsHead);
  const needsList = _el('div', 'apo-deck-needs-list');
  needs.appendChild(needsList);

  const status = _el('p', 'apo-deck-status');
  status.setAttribute('role', 'status');

  root.appendChild(rail);
  root.appendChild(board);
  root.appendChild(needs);
  root.appendChild(status);
  if (history && history.parentNode === host) host.insertBefore(root, history);
  else host.appendChild(root);

  _deck = { root, railList, board, needsList, needsCount, status };
  _sigs = {};
  _offSpace = Sp.onSpaceChange(() => { _sigs = {}; openGoal(null); });
  refresh();
  _loop();
  return root;
}

/** Take the deck off the page. */
export function unmountDeck() {
  clearTimeout(_timer);
  _timer = null;
  _gen += 1;
  if (_chat) { _chat.destroy(); _chat = null; }
  if (_offSpace) { _offSpace(); _offSpace = null; }
  _deck?.root.remove();
  _deck = null;
  _goal = null;
  _sigs = {};
}

export function isDeckMounted() { return !!_deck; }
