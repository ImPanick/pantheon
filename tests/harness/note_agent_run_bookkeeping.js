// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B80`. Runs the REAL note-level agent-solve code out of `static/js/notes.js`
// against stubs. The row's claim is about a run that outlives the page that
// started it, so the question is what the note has WRITTEN DOWN when the page
// comes back — and then what the ⋯ corner menu builds from it.
//
// Nothing here greps (`Law 20`): the fields reported are the ones the real job
// runner assigned, the patches are the bodies the real `_patchNote` call sites
// produced, and the menu entries are read off the markup `_openNoteCornerMenu`
// actually built.
//
// Modes:
//   job   note|item   — drive one solve to completion; report what the note
//                       (and the item) carry, and every patch body sent
//   abort note|item   — the same, stopped mid-run
//   menu  <fixture>   — which entries the note's ⋯ menu builds
//   stop  <outcome>   — press Stop on a reloaded note and report the requests
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'notes.js');
const source = fs.readFileSync(SRC, 'utf8');

// [first line of the region, first line AFTER it]. Separate slices because the
// queue helpers, the job runner and the corner menu are scattered through the
// file and everything between them drags in the rest of the notes panel.
const SLICES = [
  ['function _agentSolveKey(noteId, idx) {', '/** Build the job for a note-level'],
  ['// Agent-solve: create a chat session server-side', 'function _agentSolveNote(id)'],
  ['function _openNoteCornerMenu(btn) {', 'function _positionNoteMenu(menu, btn, width = 196) {'],
];
const parts = [];
for (const [start, end] of SLICES) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  if (from < 0 || to < 0 || to <= from) {
    console.error('ANCHOR-MISSING: ' + JSON.stringify(start) + ' .. ' + JSON.stringify(end));
    process.exit(2);
  }
  parts.push(source.slice(from, to));
}

const mode = process.argv[2] || 'job';
const arg = process.argv[3] || '';

// ── stub DOM: only what the corner menu touches ─────────────────────────────
function makeNode(tag) {
  return {
    tagName: String(tag).toUpperCase(), className: '', innerHTML: '', style: { cssText: '' },
    children: [], listeners: {},
    appendChild(n) { this.children.push(n); return n; },
    remove() {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    click() { (this.listeners.click || []).forEach(fn => fn()); },
    getBoundingClientRect: () => ({ top: 10, bottom: 30, right: 200, left: 100 }),
    // The menu is built by assigning one innerHTML string and querying it back,
    // so the query reads that string: every entry is `data-act="..."` with its
    // label in the following <span>.
    querySelector(sel) {
      const m = /\[data-act="([a-z-]+)"\]/.exec(sel);
      if (!m) return null;
      const act = m[1];
      const rx = new RegExp('data-act="' + act + '"[\\s\\S]*?<span>([\\s\\S]*?)</span>');
      const hit = rx.exec(this.innerHTML);
      if (!hit) return null;
      const node = this._entries[act] || (this._entries[act] = makeNode('button'));
      node.dataset = { act };
      node.label = hit[1].trim();
      return node;
    },
    _entries: {},
  };
}
const nodes = [];
const document = {
  body: makeNode('body'),
  createElement: (t) => { const n = makeNode(t); n._entries = {}; nodes.push(n); return n; },
  querySelectorAll: () => [],
};
const window = { innerWidth: 1200, innerHeight: 900, sessionModule: null };

// ── stub module surface ─────────────────────────────────────────────────────
const toasts = [];
const patched = [];
const fetched = [];
const uiModule = { showToast: (m) => toasts.push(String(m)), showError: (m) => toasts.push('ERR:' + m) };
const API_BASE = 'http://test.local';
let _renderCount = 0;
const _renderNotes = () => { _renderCount++; };
const _patchNote = (id, body) => { patched.push({ id, body: JSON.parse(JSON.stringify(body)) }); return Promise.resolve(); };
const bindMenuDismiss = (menu, fn) => fn;
const topPortalZ = () => 100;
const dismissOrRemove = () => {};
const _copyNote = () => {};
const _agentSolveNote = () => {};
const AGENT_SOLVE_MAX_CONCURRENT = 2;

class FormData {
  constructor() { this._d = []; }
  append(k, v) { this._d.push([k, String(v)]); }
}
let aborted = false;
class AbortController {
  constructor() { this.signal = { aborted: false }; }
  abort() { aborted = true; this.signal.aborted = true; }
}

// `stop` mode drives the three answers `/api/chat/resume` can give.
const resumeOutcome = (mode === 'stop' ? (arg || 'live') : 'live');
// `abort` mode stops the run while the SSE is draining.
let onStreamRead = null;
const fetchStub = async (url, opts) => {
  const u = String(url);
  fetched.push({ url: u, method: (opts && opts.method) || 'GET',
                 runId: (opts && opts.headers && opts.headers['X-Pantheon-Run-Id']) || '' });
  if (u.includes('/api/chat/resume/')) {
    if (resumeOutcome === 'gone') return { ok: false, status: 404, headers: { get: () => null } };
    if (resumeOutcome === 'throws') throw new Error('network down');
    return { ok: true, status: 200, headers: { get: (h) => (h === 'X-Pantheon-Run-Id' ? 'run-77' : null) } };
  }
  if (u.includes('/api/default-chat')) {
    return { json: async () => ({ endpoint_url: 'http://model.local', model: 'm1', endpoint_id: 'e1' }) };
  }
  if (u.includes('/api/session')) {
    return { ok: true, status: 200, json: async () => ({ id: 'sess-9' }) };
  }
  if (u.includes('/api/chat_stream')) {
    return {
      ok: true, status: 200,
      headers: { get: (h) => (h === 'X-Pantheon-Run-Id' ? 'run-42' : null) },
      body: { getReader: () => ({ read: async () => {
        if (onStreamRead) { const f = onStreamRead; onStreamRead = null; f(); }
        return { done: true };
      } }) },
    };
  }
  return { ok: true, status: 200, catch() { return this; } };
};

// ── fixtures: one note, five shapes ─────────────────────────────────────────
const FIXTURES = {
  // The row's case: a note-level run that outlived the page that started it.
  stale: { agent_status: 'running', agent_session_id: 'sess-9' },
  // `running` with no session — neither this page nor the server can be asked.
  orphan: { agent_status: 'running' },
  done: { agent_status: 'stream_complete', agent_session_id: 'sess-9' },
  ran: { agent_session_id: 'sess-9' },
  idle: {},
};
const note = Object.assign(
  { id: 'note-1', title: 'ship it', note_type: 'checklist', items: [{ text: 'do the thing' }] },
  FIXTURES[arg] || (mode === 'menu' || mode === 'stop' ? FIXTURES.stale : FIXTURES.idle),
);
const _notes = [note];

const _agentSolveRuns = new Map();
const _agentSolveQueue = [];
if (arg === 'live') {
  Object.assign(note, FIXTURES.stale);
  _agentSolveRuns.set('note:note-1', { abort: { abort() {} }, sid: 'sess-9', runId: 'run-1' });
}
if (arg === 'queued') { _agentSolveQueue.push({ key: 'note:note-1' }); }

const make = new Function(
  'document', 'window', 'uiModule', 'API_BASE', 'fetch', 'AbortController', 'FormData',
  '_notes', '_agentSolveRuns', '_agentSolveQueue', 'AGENT_SOLVE_MAX_CONCURRENT',
  '_renderNotes', '_patchNote', 'bindMenuDismiss', 'topPortalZ', 'dismissOrRemove',
  '_copyNote', '_agentSolveNote',
  parts.join('\n\n') +
  '\n return { _agentRunCarrier, _agentRunStopKind, _agentSolveState, _recordAgentRun,' +
  ' _markTodoAgentStatus, _runAgentSolveJob, _stopDetachedAgentRun, _openNoteCornerMenu };',
);
const api = make(
  document, window, uiModule, API_BASE, fetchStub, AbortController, FormData,
  _notes, _agentSolveRuns, _agentSolveQueue, AGENT_SOLVE_MAX_CONCURRENT,
  _renderNotes, _patchNote, bindMenuDismiss, topPortalZ, dismissOrRemove,
  _copyNote, _agentSolveNote,
);

// Everything the stop path needs to know, read off the objects rather than the
// source: what the note carries, what the item carries, what was persisted.
function snapshot() {
  const carrier = (o) => (o ? {
    agent_session_id: o.agent_session_id,
    agent_session_title: o.agent_session_title,
    agent_status: o.agent_status,
    agent_stream_completed_at: typeof o.agent_stream_completed_at === 'string'
      ? (o.agent_stream_completed_at ? 'SET' : '') : o.agent_stream_completed_at,
  } : null);
  return {
    note: carrier(note),
    item: carrier(note.items[0]),
    patched,
    patchedKeys: patched.map(p => Object.keys(p.body).sort()),
    fetched: fetched.map(f => ({ url: f.url.replace(API_BASE, ''), method: f.method, runId: f.runId })),
    toasts,
    rerendered: _renderCount,
  };
}

function buildMenu() {
  const btn = makeNode('button');
  btn.dataset = { noteId: 'note-1' };
  api._openNoteCornerMenu(btn);
  const menu = nodes[nodes.length - 1];
  const acts = [...menu.innerHTML.matchAll(/data-act="([a-z-]+)"[\s\S]*?<span>([\s\S]*?)<\/span>/g)]
    .map(m => ({ act: m[1], label: m[2].trim() }));
  return { menu, acts };
}

(async () => {
  if (mode === 'job' || mode === 'abort') {
    const isItem = arg === 'item';
    const job = { key: isItem ? 'item:note-1#0' : 'note:note-1', noteId: 'note-1',
                  idx: isItem ? 0 : null, prompt: 'p', label: 'ship it' };
    if (mode === 'abort') {
      onStreamRead = () => {
        const run = _agentSolveRuns.get(job.key);
        if (run) { try { run.abort.abort(); } catch (_) {} }
        throw Object.assign(new Error('aborted'), { name: 'AbortError' });
      };
    }
    await api._runAgentSolveJob(job);
    console.log(JSON.stringify(snapshot()));
  } else if (mode === 'menu') {
    const { acts } = buildMenu();
    console.log(JSON.stringify({
      acts: acts.map(a => a.act),
      labels: acts.map(a => a.label),
      stopKind: api._agentRunStopKind('note-1', null, note),
      liveState: api._agentSolveState('note-1', null),
    }));
  } else if (mode === 'stop') {
    const { menu, acts } = buildMenu();
    const entry = menu.querySelector('[data-act="agent-cancel"]');
    if (!entry) { console.log(JSON.stringify({ noStopEntry: true, acts: acts.map(a => a.act) })); return; }
    entry.click();
    await new Promise(r => setTimeout(r, 30));
    console.log(JSON.stringify(Object.assign({ noStopEntry: false }, snapshot())));
  } else if (mode === 'carrier') {
    console.log(JSON.stringify({
      noteIsCarrier: api._agentRunCarrier(note, null) === note,
      itemIsCarrier: api._agentRunCarrier(note, 0) === note.items[0],
      missingItem: api._agentRunCarrier(note, 7),
      missingNote: api._agentRunCarrier(null, null),
    }));
  } else {
    console.error('unknown mode: ' + mode);
    process.exit(2);
  }
})().catch((e) => { console.error(e && e.stack || String(e)); process.exit(3); });
