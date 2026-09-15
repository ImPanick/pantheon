// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B13`. Runs the three renderers that can have the SAME queued message on
// screen at once — `queuePanel.js`'s docked row, `tasks.js`'s Activity row and
// `chat.js`'s transcript bubble — and prints the word each one shows.
//
// Reading the files answers a different question. `queuePanel.statusLabel` is a
// six-case switch and it is easy to read off; the Activity view's word is
// decided three levels inside `_renderActivityEntry`, by a ternary over a
// `stale` timer, and the bubble's word depends on `pendingUpload`/`restored`
// rather than on the status at all. Only running all three over the same entry
// shows what a person sees, and the row's claim is precisely about what a
// person sees when two surfaces are open together.
//
// Usage:
//   node queue_status_words.js vocabularies
//   node queue_status_words.js together
const fs = require('fs');
const path = require('path');

const JS = path.join(__dirname, '..', '..', 'static', 'js');
const panelSrc = fs.readFileSync(path.join(JS, 'queuePanel.js'), 'utf8');
const tasksSrc = fs.readFileSync(path.join(JS, 'tasks.js'), 'utf8');
const chatSrc = fs.readFileSync(path.join(JS, 'chat.js'), 'utf8');
// The word table is plain data and pure functions with no imports of its own,
// so it is evaluated as written and shared by all three renderers below —
// which is the whole point of the row. A harness that retypes the table would
// prove the three surfaces agree with the harness, not with each other.
const wordsSrc = fs.existsSync(path.join(JS, 'runStatus.js'))
  ? fs.readFileSync(path.join(JS, 'runStatus.js'), 'utf8')
    .replace(/^\/\/.*$/gm, '').replace(/^export\s+/gm, '')
  : '';

function slice(source, startMark, endMark, label) {
  const from = source.indexOf(startMark);
  if (from < 0) { console.error(`ANCHOR-MISSING: ${label} start (${startMark})`); process.exit(2); }
  const to = source.indexOf(endMark, from);
  if (to < 0 || to <= from) { console.error(`ANCHOR-MISSING: ${label} end (${endMark})`); process.exit(2); }
  return source.slice(from, to);
}
// `chat.js` indents its exports inside an IIFE, so the anchor allows leading
// space — a `^export` that quietly matches nothing leaves the keyword in and
// the slice fails to parse rather than failing to run.
const unexport = (s) => s.replace(/^(\s*)export\s+/gm, '$1');

const escHtml = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// ── A DOM stub the panel's createElement/textContent row can be read back from
function makeEl(tag) {
  const el = {
    tagName: tag, attrs: {}, children: [], _text: null, style: {},
    dataset: new Proxy({}, { set(t, k, v) { t[k] = v; return true; }, get(t, k) { return t[k]; } }),
    classList: { add(...c) { el.attrs.class = ((el.attrs.class || '') + ' ' + c.join(' ')).trim(); }, remove() {}, contains() { return false; } },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    appendChild(c) { el.children.push(c); el._text = null; return c; },
    addEventListener() {},
    get className() { return el.attrs.class || ''; }, set className(v) { el.attrs.class = v; },
    get textContent() { return el._text == null ? el.children.map(t => t.textContent || '').join('') : el._text; },
    set textContent(v) { el._text = String(v); el.children = []; },
    get innerHTML() { return el.attrs._html || ''; }, set innerHTML(v) { el.attrs._html = String(v); },
    get title() { return el.attrs.title || ''; }, set title(v) { el.attrs.title = String(v); },
  };
  return el;
}
const document = { createElement: (t) => makeEl(t) };

/** Find the text of the first element carrying `cls` anywhere in the tree. */
function textOf(node, cls) {
  if (!node || !node.attrs) return null;
  if ((node.attrs.class || '').split(/\s+/).includes(cls)) return node.textContent;
  for (const c of node.children || []) {
    const hit = textOf(c, cls);
    if (hit != null) return hit;
  }
  return null;
}

// ── The docked panel ────────────────────────────────────────────────────────
const panelBody = [
  slice(panelSrc, 'const ICON_PLAY =', 'const ICON_GRIP =', 'panel icons'),
  slice(panelSrc, 'const ICON_GRIP =', 'const ICON_PARALLEL =', 'panel icons 2'),
  slice(panelSrc, 'function statusClass(status) {', '// ── Element collection', 'status fns'),
  slice(panelSrc, 'function buildRow(entry) {', '// ── Reading the queue', 'buildRow'),
].join('\n');

const panel = new Function('document', 'formatElapsed', 'modelChoices', 'choiceKeyFor',
  '_editingId', `
  ${wordsSrc}
  ${unexport(panelBody)}
  return { statusLabel, statusClass, buildRow };
`);

// ── The Activity view ───────────────────────────────────────────────────────
const tone = unexport(slice(tasksSrc, 'export function runStatusTone(status) {',
                            'function _statusDot(status) {', 'runStatusTone'));
const controls = unexport(slice(tasksSrc, 'export function activityEntryControls(entry) {',
                                '/** Tooltip for the shared stop control.', 'activityEntryControls'));
const stopLabel = slice(tasksSrc, 'function _stopLabel(entry) {',
                        "/** Collect every source's rows.", '_stopLabel');
const renderer = slice(tasksSrc, 'function _renderActivityEntry(entry, opts = {}) {',
                       'function _escHtml(s) {', '_renderActivityEntry');

const deps = {
  _activityEntries: [], _escHtml: escHtml, _esc: escHtml,
  _relativeTime: () => '2m ago', _classifyResult: () => 'error', _categoryHue: () => 200,
  _taskIcon: () => '<svg></svg>', _taskAiMark: () => '', _taskClearCacheLabel: () => '',
  _fmtElapsed: () => '0s',
  markdownModule: { squashOutsideCode: (s) => s, processWithThinking: (s) => `<p>${s}</p>` },
};
const names = Object.keys(deps);
const activity = new Function(...names, `
  ${wordsSrc}
  ${tone}
  ${controls}
  ${stopLabel}
  ${renderer}
  return { _renderActivityEntry };
`);

// ── The transcript bubble ───────────────────────────────────────────────────
const bubbleBody = slice(chatSrc, '  function _queuedBubbleHtml(item) {',
                         '  function _paintQueuedBubble(item) {', '_queuedBubbleHtml');
const bubble = new Function('_escapeQueueText', `
  ${wordsSrc}
  ${bubbleBody}
  return { _queuedBubbleHtml };
`);

// ── The one row builder both docked surfaces read from ──────────────────────
// `getQueueActivityEntries` is what makes this a row and not a style question:
// the panel and the Activity view render the SAME object out of it. Run, not
// re-stated, so the row's fields are the shipped ones.
const sourceBody = slice(chatSrc, '  export function getQueueActivityEntries(scope = \'session\') {',
                         '  function _queueItemById(id) {', 'getQueueActivityEntries');
const source = new Function('_queuedAgentRequests', '_currentSessionIdSafe', 'sessionModule',
  '_promoteQueuedRequest', '_removeQueuedRequest', `
  ${unexport(sourceBody)}
  return { getQueueActivityEntries };
`);

const formatElapsed = () => '3s';
const panelApi = panel(document, formatElapsed, () => [], () => '', null);
const activityApi = activity(...names.map((n) => deps[n]));
const bubbleApi = bubble((s) => escHtml(s));

/** The word the docked panel prints for an entry. */
function panelWord(entry) {
  const row = panelApi.buildRow(entry);
  return textOf(row, 'task-log-running-label');
}

/** The word the Activity row prints for an entry. `null` when it shows a time
 *  instead — a terminal row has no running-label at all, which is itself an
 *  answer: the two surfaces do not even agree on whether there is a word. */
function activityWord(entry) {
  const html = activityApi._renderActivityEntry(entry);
  const m = html.match(/<span class="task-log-running-label">([^<]*)<\/span>/);
  return m ? m[1] : null;
}

/** The word the transcript bubble prints. */
function bubbleWord(item) {
  const html = bubbleApi._queuedBubbleHtml(item);
  const m = html.match(/<span class="queued-pill">(?:<svg[\s\S]*?<\/svg>)?([^<]*)<\/span>/);
  return m ? m[1] : null;
}

const SIX = ['queued', 'running', 'success', 'error', 'skipped', 'aborted'];
const mode = process.argv[2] || 'vocabularies';

if (mode === 'vocabularies') {
  // Every word each surface has for each of the six, both subjects.
  const out = {};
  for (const status of SIX) {
    const base = {
      queueId: 'q1', taskName: 'ship the thing', kind: 'llm', status,
      ts: new Date(Date.now() - 3000).toISOString(), result: '', editable: status === 'queued',
      position: 1, sessionId: 's1',
    };
    // 40 minutes in: the Activity view's staleness branch, which reads out of
    // the same label slot and so is part of the same vocabulary.
    const old = { ...base, ts: new Date(Date.now() - 40 * 60 * 1000).toISOString() };
    out[status] = {
      panel: panelWord(base),
      activityJob: activityWord(base),
      activityMessage: activityWord({ ...base, subject: 'message' }),
      activityStaleJob: activityWord(old),
      activityStaleMessage: activityWord({ ...old, subject: 'message' }),
    };
  }
  console.log(JSON.stringify(out));
} else {
  // One queued message, built by the real source, shown on all three surfaces.
  const item = {
    id: 'q1', message: 'ship the thing', sessionId: 's1', attachments: [],
    pendingUpload: false, restored: false, createdAt: Date.now(),
  };
  const sourceApi = source([item], () => 's1', { getSessions: () => [{ id: 's1', name: 'chat' }] },
                           () => {}, () => {});
  const rows = sourceApi.getQueueActivityEntries('session');
  const entry = rows[0] || {};
  const words = {
    panel: panelWord(entry),
    activity: activityWord(entry),
    bubble: bubbleWord(item),
    bubbleRestored: bubbleWord({ ...item, restored: true }),
  };
  const distinct = [...new Set([words.panel, words.activity, words.bubble].filter(Boolean))];
  console.log(JSON.stringify({
    rows: rows.length, subject: entry.subject || null, words, distinct, count: distinct.length,
  }));
}
