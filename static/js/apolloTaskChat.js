// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloTaskChat.js — a task's own chat: the person talks to the agent doing
// the work, not to Apollo about it (outline, *Surfaces*, layer 4).
//
// One chat per task, bound to the chat its lead's runs write into
// (`GET /api/apollo/tasks/{id}/chat`), so it outlives a run and reopening the
// task reopens it. It lives in one of two places:
//
//   embedded — inside the Apollo pane's task view, under the report; the pane
//              widens into a dual pane (`apo-wide`). One at a time: opening
//              another task swaps it.
//   floating — its own window, dragged and snapped like any other; several
//              may be open at once, and they stack.
//
// What the person types goes to that lead only:
//
//   * while one of its runs is working, the words steer that run
//     (`POST /api/chat/steer/{session}`, the main chat's own transport);
//   * otherwise they start a turn of the lead in its chat, summoned as itself
//     in Agent mode (`POST /api/chat_stream` with `agent`), so it answers with
//     its own kit and its own approvals.
//
// Either way Apollo's chat gets one line about it (`POST …/said`), never the
// conversation. An approval the lead asks for shows here as buttons and in
// the pane's Needs you; answering here resumes the turn, as the main chat's
// card does. No server text is parsed as HTML: a lead's report is drawn by
// `apolloText.js`, which builds elements and sets text.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';
import * as M from './apolloPaneModel.js';
import { renderText } from './apolloText.js';

const POLL_MS = 8000;
const FLOAT_PREFIX = 'apollo-chat-';
const _floating = new Map();   // task id -> { modal, chat }

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
  b.addEventListener('click', (e) => onClick(e));
  return b;
}

function _say(msg) {
  try { uiModule.showToast(msg); } catch (_) { /* no toast host */ }
}

async function _json(res, fallback) {
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const why = data && typeof data.detail === 'string' ? data.detail : fallback;
    const err = new Error(why);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function _readChat(taskId) {
  const res = await fetch(`/api/apollo/tasks/${encodeURIComponent(taskId)}/chat`, { credentials: 'same-origin' });
  return _json(res, 'The task chat could not be opened just now.');
}

async function _readHistory(sid) {
  const res = await fetch(`/api/history/${encodeURIComponent(sid)}?limit=40`, { credentials: 'same-origin', cache: 'no-store' });
  return _json(res, 'The task chat could not be read just now.');
}

async function _tellApollo(taskId, words) {
  try {
    await fetch(`/api/apollo/tasks/${encodeURIComponent(taskId)}/said`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ words }),
    });
  } catch (_) { /* the line is a courtesy; the words already reached the lead */ }
}

/**
 * Build one task's chat. Returns `{ el, taskId, refresh, destroy }`; `el` is
 * kept across the pane's redraws, so a half-typed message survives them.
 */
export function createTaskChat(taskId, { onTitle } = {}) {
  const el = _el('section', 'apo-chat');
  el.dataset.taskId = String(taskId);
  const head = _el('div', 'apo-chat-h');
  const title = _el('h5', 'apo-sec-t', 'Chat with the lead');
  head.appendChild(title);
  el.appendChild(head);
  const log = _el('div', 'apo-chat-log');
  log.setAttribute('role', 'log');
  log.setAttribute('aria-live', 'polite');
  el.appendChild(log);
  const asking = _el('div', 'apo-chat-ask');
  el.appendChild(asking);
  const form = _el('form', 'apo-chat-form');
  const input = _el('textarea', 'apo-input apo-chat-input');
  input.rows = 2;
  input.maxLength = 8000;
  input.placeholder = 'Message the lead';
  input.setAttribute('aria-label', 'Message the lead on this task');
  const send = _el('button', 'apo-btn apo-primary', 'Send');
  send.type = 'submit';
  form.appendChild(input);
  form.appendChild(send);
  el.appendChild(form);
  const note = _el('p', 'apo-empty apo-chat-note', 'Only this task\'s lead reads this. Apollo gets one line about it.');
  el.appendChild(note);

  let sid = '';
  let lead = 'the lead';
  let leadAgent = '';
  let alive = true;
  let busy = false;
  let timer = null;
  let gen = 0;
  let live = null;          // the lead's answer as it streams
  let held = null;          // an approval from a stream, until answered

  function _atBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  }

  function _drawLines(entries) {
    const stick = _atBottom();
    log.textContent = '';
    if (!entries.length) log.appendChild(_el('p', 'apo-empty', `Nothing here yet. Ask ${lead} anything about the task.`));
    for (const e of entries) {
      if (e.role === 'apollo') {
        // Apollo's handoff that started the lead's run: a line, not a bubble.
        log.appendChild(_el('p', 'apo-msg-handoff', `Apollo handed this goal to ${lead}.`));
        continue;
      }
      const row = _el('div', `apo-msg apo-msg-${e.role === 'user' ? 'you' : 'lead'}`);
      row.appendChild(_el('span', 'apo-msg-who', e.role === 'user' ? 'You' : lead));
      if (e.role === 'user') row.appendChild(_el('p', 'apo-msg-t', e.text));
      else row.appendChild(renderText(_el('div', 'apo-msg-t'), e.text));
      log.appendChild(row);
    }
    if (live) log.appendChild(live);
    if (stick) log.scrollTop = log.scrollHeight;
  }

  function _drawAsk(approval) {
    held = approval || null;
    asking.textContent = '';
    if (!approval) return;
    const box = _el('div', 'apo-need');
    box.appendChild(_el('p', 'apo-q', approval.question));
    const acts = _el('div', 'apo-acts');
    for (const o of approval.options) {
      acts.appendChild(_btn(o.decision === 'deny' ? '' : 'apo-primary', o.label, () => _answer(approval, o)));
    }
    box.appendChild(acts);
    asking.appendChild(box);
  }

  async function refresh() {
    if (!alive || busy) return;
    const g = ++gen;
    if (timer) { clearTimeout(timer); timer = null; }
    try {
      if (!sid) {
        const found = await _readChat(taskId);
        if (!alive || g !== gen) return;
        sid = found.session_id;
        lead = found.lead || lead;
        leadAgent = found.lead_agent || '';
        title.textContent = `Chat with ${lead}`;
        input.placeholder = `Message ${lead}`;
        if (onTitle) onTitle(found);
      }
      const data = await _readHistory(sid);
      if (!alive || g !== gen) return;
      const history = (data && data.history) || [];
      _drawLines(M.chatEntries(history));
      // An approval that came in on a stream shows until it is answered, even
      // before the chat's saved history carries it.
      _drawAsk(M.pendingApproval(history) || held);
      form.hidden = false;
    } catch (err) {
      if (!alive || g !== gen) return;
      log.textContent = '';
      log.appendChild(_el('p', 'apo-empty', err.message));
      form.hidden = err.status === 409 || err.status === 403;
    }
    if (alive) timer = setTimeout(refresh, POLL_MS);
  }

  async function _stream(fd) {
    live = _el('div', 'apo-msg apo-msg-lead apo-msg-live');
    live.appendChild(_el('span', 'apo-msg-who', lead));
    const words = _el('p', 'apo-msg-t', 'Working…');
    live.appendChild(words);
    log.appendChild(live);
    log.scrollTop = log.scrollHeight;
    const res = await fetch('/api/chat_stream', { method: 'POST', credentials: 'same-origin', body: fd });
    if (!res.ok) await _json(res, `The lead could not take that (${res.status}).`);
    let text = '';
    let approval = null;
    let buf = '';
    const reader = res.body && res.body.getReader ? res.body.getReader() : null;
    if (reader) {
      const dec = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const { events, rest } = M.sseEvents(buf);
        buf = rest;
        for (const ev of events) {
          if (typeof ev.delta === 'string') { text += ev.delta; words.textContent = text; }
          approval = M.approvalOf(ev) || approval;
        }
      }
      const tail = M.sseEvents(`${buf}\n`).events;
      for (const ev of tail) approval = M.approvalOf(ev) || approval;
    } else {
      const { events } = M.sseEvents(`${await res.text()}\n`);
      for (const ev of events) approval = M.approvalOf(ev) || approval;
    }
    return approval;
  }

  function _form(extra) {
    const fd = new FormData();
    fd.append('session', sid);
    fd.append('mode', 'agent');
    for (const [k, v] of Object.entries(extra)) fd.append(k, v);
    return fd;
  }

  async function _answer(approval, option) {
    if (busy) return;
    busy = true;
    held = null;
    asking.textContent = '';
    try {
      const fd = _form({ message: '', tool_approval_id: approval.id, tool_approval_decision: option.decision });
      const again = await _stream(fd);
      _drawAsk(again);
    } catch (err) {
      _say(err.message);
    } finally {
      live = null;
      busy = false;
      refresh();
    }
  }

  async function _send(words, agentId) {
    // A run that is working takes the words as a steer, between its steps.
    try {
      const res = await fetch(`/api/chat/steer/${encodeURIComponent(sid)}`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: words }),
      });
      if (res.ok) {
        const out = await res.json().catch(() => ({}));
        if (out && out.accepted) return 'steered';
      }
    } catch (_) { /* no live run: a turn of its own below */ }
    const fd = _form({ message: words });
    if (agentId) fd.append('agent', agentId);
    const approval = await _stream(fd);
    _drawAsk(approval);
    return 'answered';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const words = input.value.trim();
    if (!words || busy || !sid) return;
    busy = true;
    send.disabled = true;
    const mine = _el('div', 'apo-msg apo-msg-you');
    mine.appendChild(_el('span', 'apo-msg-who', 'You'));
    mine.appendChild(_el('p', 'apo-msg-t', words));
    log.appendChild(mine);
    log.scrollTop = log.scrollHeight;
    input.value = '';
    held = null;
    asking.textContent = '';
    try {
      const how = await _send(words, leadAgent);
      if (how === 'steered') _say(`${lead} takes that at its next step.`);
      _tellApollo(taskId, words);
    } catch (err) {
      _say(err.message || 'That did not reach the lead.');
      input.value = words;
      mine.remove();
    } finally {
      live = null;
      busy = false;
      send.disabled = false;
      refresh();
    }
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  });

  function destroy() {
    alive = false;
    ++gen;
    if (timer) { clearTimeout(timer); timer = null; }
    if (el.parentNode) el.parentNode.removeChild(el);
  }

  refresh();
  return { el, taskId: String(taskId), refresh, destroy, focus: () => input.focus() };
}

/* ───────────── floating windows ───────────── */

/** Open a task's chat in its own window, or bring it forward. Several may be
 *  open at once; each new one sits a step below and right of the last. */
export function popOutTaskChat(taskId, { title = '' } = {}) {
  const id = String(taskId);
  const modalId = `${FLOAT_PREFIX}${id}`;
  const open = _floating.get(id);
  if (open && Modals.isRegistered(modalId)) {
    if (Modals.isMinimized(modalId)) Modals.restore(modalId);
    else Modals.showWindow(modalId);
    open.chat.focus();
    return open;
  }
  const modal = _el('div', 'modal apo-chat-modal');
  modal.id = modalId;
  const step = _floating.size;
  modal.style.setProperty('--apo-stack', String(step));
  const content = _el('div', 'modal-content apo-chat-content');
  const header = _el('div', 'modal-header');
  const h = _el('h4', 'apo-heading', title ? `Task: ${title}` : 'Task chat');
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  header.appendChild(h);
  header.appendChild(close);
  content.appendChild(header);
  const chat = createTaskChat(id, { onTitle: (found) => { h.textContent = `Task: ${found.title}`; } });
  content.appendChild(chat.el);
  modal.appendChild(content);
  document.body.appendChild(modal);
  const entry = { modal, chat };
  _floating.set(id, entry);
  const teardown = () => {
    chat.destroy();
    _floating.delete(id);
    if (modal.parentNode) modal.parentNode.removeChild(modal);
  };
  close.addEventListener('click', (e) => { e.preventDefault(); if (Modals.isRegistered(modalId)) Modals.close(modalId); else teardown(); });
  Modals.register(modalId, { restoreFn: () => chat.refresh(), closeFn: teardown, label: title ? `Task: ${title}` : 'Task chat', icon: '' });
  Modals.injectMinimizeButton(modal, modalId);
  makeWindowDraggable(modal, {
    content, header, skipSelector: 'button, input, textarea, select, label, form', minWidth: 300, minHeight: 320,
  });
  chat.focus();
  return entry;
}

export function isTaskChatFloating(taskId) { return _floating.has(String(taskId)); }

export function closeFloatingTaskChats() {
  for (const id of Array.from(_floating.keys())) {
    const modalId = `${FLOAT_PREFIX}${id}`;
    if (Modals.isRegistered(modalId)) Modals.close(modalId);
    else { const e = _floating.get(id); if (e) e.chat.destroy(); _floating.delete(id); }
  }
}
