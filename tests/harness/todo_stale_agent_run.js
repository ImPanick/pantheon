// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B08`. Runs the REAL agent-run decision code out of `static/js/notes.js`
// against stubs, for a checklist item whose `agent_status` says `running` while
// this page's queue holds nothing.
//
// The property the row asks about cannot be read out of the file. The tooltip
// and the menu are computed in two functions 1,200 lines apart, from two
// different sources — the render reads `item.agent_status`, the menu read
// `_agentSolveState`, which is live-only — and the defect is that they
// disagree. Only running both against one item shows it. Nothing here greps
// (`Law 20`); the tooltip string reported below is the one the render
// assigned, and the menu entries are read off the nodes the menu appended.
//
// Modes:
//   render  <fixture>  — what the checklist row says about the item
//   menu    <fixture>  — which entries `_openTodoAgentMenu` actually built
//   stop    <outcome>  — what pressing Stop on a detached run does
//   classes            — every class the render can put on the button, obtained
//                        by rendering each status rather than by reading the
//                        ternary that produces them
const fs = require('fs');
const path = require('path');
const { iconsSource } = require('./icons_source');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'notes.js');
const source = fs.readFileSync(SRC, 'utf8');

// Each pair is [first line of the region, first line AFTER it]. Separate slices
// rather than one span because the render block, the menu and the queue helpers
// are scattered through the file and everything between them pulls in the rest
// of the notes panel.
const SLICES = [
  ['function _agentSolveKey(noteId, idx) {', 'function _agentSolvePending() {'],
  ['/** Remove a queued job, or stop a running one. */', '/** Build the job for a note-level'],
  ['/** Terminal status for one checklist item', 'function _agentSolveNote(id)'],
  ['function _openTodoAgentMenu(btn) {', '// Build the prompt the agent gets from a note:'],
  ['        const item = note.items[i];', '        const indent = Math.min(item.indent || 0, 3);'],
  // `B875`. The render calls two attribute escapers with two contracts, and
  // this harness used to hand-write a third that matched neither — `& " <`
  // against the product's `" ' < > \``. `_attrEscRaw` arriving broke every
  // case here with `ReferenceError`, which is the honest signal that a
  // stand-in had drifted. Both are lifted from the source now, so the harness
  // cannot disagree with what ships (`Law 20`, `B874`).
  ['function _attrEsc(s) {', '// `_attrEscRaw` is the FIRST stage'],
  ['function _attrEscRaw(s) {', '// Image src guard'],
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
// The last slice is a bare block, not a function; wrap it so it can be called
// once per item with the loop variables the render supplies.
// The two escapers are appended after the render block, so the block is no
// longer last: take it by index rather than by `pop()`.
const escaperParts = parts.splice(-2, 2);
const renderBlock = parts.pop();
parts.push(...escaperParts);
parts.push(`function __renderItem(note, i) {\n${renderBlock}\n  return { agentLive, agentStatus, agentDoneClass, agentBadge, agentStyleAttr, agentTitle, agentSessionAttr, agentStopKind };\n}`);

const mode = process.argv[2] || 'render';
const arg = process.argv[3] || '';

// ── stub DOM: only what the menu touches ────────────────────────────────────
function makeNode(tag) {
  return {
    tagName: String(tag).toUpperCase(), className: '', innerHTML: '', style: { cssText: '' },
    children: [], listeners: {},
    appendChild(n) { this.children.push(n); return n; },
    remove() {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    click() { (this.listeners.click || []).forEach(fn => fn()); },
    getBoundingClientRect: () => ({ top: 10, bottom: 30, right: 200, left: 100 }),
    // The menu is built by assigning one innerHTML string and then querying it
    // back, so the query has to read that string. A regex over the assigned
    // markup is enough: every entry is `data-act="..."` with its label in the
    // following <span>.
    querySelector(sel) {
      const m = /\[data-act="([a-z-]+)"\]/.exec(sel);
      if (!m) return null;
      const act = m[1];
      const rx = new RegExp('data-act="' + act + '"[\\s\\S]*?<span>([\\s\\S]*?)</span>');
      const hit = rx.exec(this.innerHTML);
      if (!hit) return null;
      const node = makeNode('button');
      node.dataset = { act };
      node.label = hit[1].trim();
      return node;
    },
  };
}
const nodes = [];
const document = {
  body: makeNode('body'),
  createElement: (t) => { const n = makeNode(t); nodes.push(n); return n; },
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
const _patchNote = (id, body) => { patched.push({ id, body }); return Promise.resolve(); };
const _linkify = (s) => String(s == null ? '' : s);
const _positionNoteMenu = (menu) => { document.body.appendChild(menu); };
const bindMenuDismiss = (menu, fn) => fn;
const topPortalZ = () => 100;
const closePanel = () => {};
const dismissOrRemove = () => {};

// `stop` mode drives the two answers `/api/chat/resume` can give.
const resumeOutcome = arg || 'live';
class AbortController { constructor() { this.signal = {}; } abort() {} }
const fetchStub = async (url, opts) => {
  fetched.push({ url: String(url), method: (opts && opts.method) || 'GET',
                 runId: (opts && opts.headers && opts.headers['X-Pantheon-Run-Id']) || '' });
  if (String(url).includes('/api/chat/resume/')) {
    if (resumeOutcome === 'gone') return { ok: false, status: 404, headers: { get: () => null } };
    if (resumeOutcome === 'throws') throw new Error('network down');
    return { ok: true, status: 200, headers: { get: (h) => (h === 'X-Pantheon-Run-Id' ? 'run-77' : null) } };
  }
  return { ok: true, status: 200, catch() { return this; } };
};

// ── fixtures: one checklist item, four shapes ───────────────────────────────
const FIXTURES = {
  // The row's case: `running` survived a reload, nothing live behind it.
  stale: { text: 'ship the thing', agent_status: 'running', agent_session_id: 'sess-9' },
  // `running` with no session — neither this page nor the server can be asked.
  orphan: { text: 'ship the thing', agent_status: 'running' },
  done: { text: 'ship the thing', agent_status: 'stream_complete', agent_session_id: 'sess-9' },
  idle: { text: 'ship the thing' },
};
const note = { id: 'note-1', items: [FIXTURES[arg] || FIXTURES.stale] };
const _notes = [note];

// `live` is the control: the same stored `running`, but with this page's queue
// holding the job, which is what the render used to be unable to tell apart.
const _agentSolveRuns = new Map();
const _agentSolveQueue = [];
if (mode === 'render' && arg === 'live') {
  note.items[0] = { ...FIXTURES.stale };
  _agentSolveRuns.set('item:note-1#0', { abort: { abort() {} }, sid: 'sess-9', runId: 'run-1' });
}
if (mode === 'menu' && arg === 'live') {
  note.items[0] = { ...FIXTURES.stale };
  _agentSolveRuns.set('item:note-1#0', { abort: { abort() {} }, sid: 'sess-9', runId: 'run-1' });
}

// `B230`: the menu's stop glyph comes from the shared icon table now, so the
// slice needs the real table in scope — inlined, never stubbed (`B250`).
const make = new Function(
  'document', 'window', 'uiModule', 'API_BASE', 'fetch', 'AbortController',
  '_notes', '_agentSolveRuns', '_agentSolveQueue', '_renderNotes', '_patchNote',
  '_linkify', '_positionNoteMenu', 'bindMenuDismiss', 'topPortalZ',
  'closePanel', 'dismissOrRemove', '_agentSolveTodoItem',
  iconsSource() + '\n' + parts.join('\n\n') + '\n return { _agentRunStopKind, _agentSolveState, _openTodoAgentMenu, _stopDetachedAgentRun, _markTodoAgentStatus, __renderItem };',
);
const api = make(
  document, window, uiModule, API_BASE, fetchStub, AbortController,
  _notes, _agentSolveRuns, _agentSolveQueue, _renderNotes, _patchNote,
  _linkify, _positionNoteMenu, bindMenuDismiss, topPortalZ,
  closePanel, dismissOrRemove, () => {},
);

if (mode === 'render') {
  const r = api.__renderItem(note, 0);
  console.log(JSON.stringify({
    title: r.agentTitle,
    cls: r.agentDoneClass,
    styleAttr: r.agentStyleAttr,
    badge: r.agentBadge,
    stopKind: r.agentStopKind,
    // The tooltip's whole claim is that a menu entry exists. Reported as a
    // boolean so the test can pin it against what the menu actually builds.
    promisesAMenuStop: /open the menu to stop it/.test(r.agentTitle),
  }));
} else if (mode === 'menu') {
  const btn = makeNode('button');
  btn.dataset = { noteId: 'note-1', idx: '0', sessionId: note.items[0].agent_session_id || '' };
  api._openTodoAgentMenu(btn);
  const menu = nodes[nodes.length - 1];
  const acts = [...menu.innerHTML.matchAll(/data-act="([a-z-]+)"[\s\S]*?<span>([\s\S]*?)<\/span>/g)]
    .map(m => ({ act: m[1], label: m[2].trim() }));
  console.log(JSON.stringify({ acts: acts.map(a => a.act), labels: acts.map(a => a.label) }));
} else if (mode === 'classes') {
  // Every status the render has a branch for, plus the live queue states that
  // only exist in memory. Whatever class comes back has to have a rule.
  const statuses = ['running', 'queued', 'stream_complete', 'error', 'aborted', ''];
  const seen = {};
  for (const st of statuses) {
    note.items[0] = { text: 't', agent_status: st, agent_session_id: 'sess-9' };
    seen[st || '(none)'] = api.__renderItem(note, 0).agentDoneClass.trim();
  }
  // The two live-only states, driven through the real queue rather than through
  // a stored status, because `queued` is never persisted.
  note.items[0] = { text: 't' };
  _agentSolveQueue.push({ key: 'item:note-1#0' });
  seen['live-queued'] = api.__renderItem(note, 0).agentDoneClass.trim();
  _agentSolveQueue.length = 0;
  _agentSolveRuns.set('item:note-1#0', {});
  seen['live-running'] = api.__renderItem(note, 0).agentDoneClass.trim();
  _agentSolveRuns.clear();
  console.log(JSON.stringify(seen));
} else if (mode === 'stop') {
  api._stopDetachedAgentRun('note-1', 0, 'sess-9').then((stopped) => {
    console.log(JSON.stringify({
      stopped,
      fetched,
      status: note.items[0].agent_status,
      patched: patched.length,
      rerendered: _renderCount,
      toasts,
    }));
  });
} else {
  console.error('unknown mode: ' + mode);
  process.exit(2);
}
