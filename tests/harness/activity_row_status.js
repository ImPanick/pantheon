// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B07`. Runs the real status-dependent renderers out of `tasks.js` — the
// Activity row, the task card's last-run badge, the Activity Errors-chip
// classifier and the shared `runStatusTone` derivation — against stubs, and
// reports what each one actually PRODUCES for a given stored run status.
//
// The property the row turns on cannot be read off the file. Flipping a run's
// stored status from `error` to `skipped` changes which *branch* three separate
// renderers take, and one of those branches — `_renderActivityEntry`'s slim
// variant — computes `actionBtn` and then returns a template that never
// interpolates it. Nothing at the computation site says the value is dropped;
// only running the function and looking at the emitted HTML shows that the
// row's Copy log and Run again buttons are gone.
//
// Usage:
//   node activity_row_status.js row   '<entry-json>'
//   node activity_row_status.js badge '<task-json>'
//   node activity_row_status.js tone
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'tasks.js');
const source = fs.readFileSync(SRC, 'utf8');

function slice(startMark, endMark, label) {
  const from = source.indexOf(startMark);
  if (from < 0) {
    console.error(`ANCHOR-MISSING: ${label} start (${startMark})`);
    process.exit(2);
  }
  const to = source.indexOf(endMark, from);
  if (to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: ${label} end (${endMark})`);
    process.exit(2);
  }
  return source.slice(from, to);
}

const unexport = (s) => s.replace(/^export\s+/gm, '');

// Extracted, never re-declared: a harness that reimplements the rule tests the
// harness. `runStatusTone` in particular must be the shipped one — it is the
// single source the other three sites now derive from.
const tone = unexport(slice('export function runStatusTone(status) {',
                            'function _statusDot(status) {', 'runStatusTone'));
const renderer = slice('function _renderActivityEntry(entry, opts = {}) {',
                       'function _escHtml(s) {', '_renderActivityEntry');
const controls = unexport(slice('export function activityEntryControls(entry) {',
                                '/** Tooltip for the shared stop control.', 'activityEntryControls'));
const stopLabel = slice('function _stopLabel(entry) {',
                        '/** Collect every source\'s rows.', '_stopLabel');
// `_entryStatus` lives inside the Activity view closure — it is what decides
// whether a row lands under the Errors chip.
const entryStatus = slice('  const _entryStatus = (e) => {',
                          '  const _isNotification =', '_entryStatus');
// The task card's last-run badge is DOM-building code inside `_renderList`'s
// card loop, so it is lifted with its own `if` and run against a stub document.
const badge = slice('    if (task.last_run_status) {',
                    '    const taskType = task.task_type', 'last-run badge');
// The wiring pass. Rendering a button and *attaching its handler* are two
// separate functions in two places, and `.is-skipped` is singled out in this
// one — so a button that renders is not yet a button that does anything.
const wire = slice('function _wireActivityRows(list) {',
                   'function _renderCompletedPreviewEntry(entry) {', '_wireActivityRows');

const escHtml = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const deps = {
  _activityEntries: [],
  _escHtml: escHtml,
  _esc: escHtml,
  _relativeTime: () => '2m ago',
  // Deliberately says "error" for any text, so a decision that survives only
  // because the text-scan fallback classified the row cannot hide here.
  _classifyResult: () => 'error',
  _categoryHue: () => 200,
  _taskIcon: () => '<svg data-icon="1"></svg>',
  _taskAiMark: () => '',
  _taskClearCacheLabel: () => '',
  _fmtElapsed: () => '0s',
  _showRunHistory: () => {},
  _startActivityTimers: () => {},
  _runEntryAction: () => {},
  _openResultInChat: () => {},
  _doRunNow: () => {},
  _doClearTaskCache: () => {},
  _stopTask: async () => {},
  _renderActivityView: () => {},
  API_BASE: '',
  uiModule: { showToast() {}, showError() {}, copyToClipboard() {} },
  spinnerModule: { createWhirlpool: () => ({ element: { style: {} } }) },
  markdownModule: {
    squashOutsideCode: (s) => s,
    processWithThinking: (s) => `<p>${s}</p>`,
  },
};

const names = Object.keys(deps);
const make = new Function(...names, 'document', 'detail', 'task', `
  ${tone}
  ${controls}
  ${stopLabel}
  ${entryStatus}
  ${renderer}
  ${wire}
  function _renderBadge() {
  ${badge}
  }
  return { _renderActivityEntry, activityEntryControls, _entryStatus, runStatusTone,
           _renderBadge, _wireActivityRows };
`);

// Selectors `_wireActivityRows` asks each row for. A row stub answers by
// looking for the class in the HTML the renderer actually emitted, so this
// reports handlers attached to real markup rather than to a hand-built fixture.
const WIRED = ['.task-log-row-toggle', '.task-log-open-chat', '.task-log-open-report',
               '.task-log-force-run', '.task-log-stop', '.task-log-run-again',
               '.task-log-copy', '.task-log-clear-cache'];

const mode = process.argv[2] || 'row';

if (mode === 'tone') {
  const api = make(...names.map((n) => deps[n]), null, null, null);
  const out = {};
  for (const s of ['queued', 'running', 'success', 'error', 'skipped', 'aborted',
                   'failed', '', undefined]) {
    out[String(s)] = api.runStatusTone(s);
  }
  console.log(JSON.stringify(out));
} else if (mode === 'badge') {
  const task = JSON.parse(process.argv[3] || '{}');
  const appended = [];
  const stubDoc = {
    createElement: () => ({ style: { cssText: '' }, innerHTML: '', title: '',
                            addEventListener() {} }),
  };
  const api = make(...names.map((n) => deps[n]), stubDoc,
                   { appendChild: (el) => appended.push(el) }, task);
  api._renderBadge();
  const el = appended[appended.length - 1];
  console.log(JSON.stringify({
    status: task.last_run_status,
    // Green tick, red cross, or the neutral dot? This is the whole question:
    // the pre-B07 form had no third answer.
    mark: el ? el.innerHTML.replace(/<[^>]*>/g, '').trim().split(/\s+/)[0] : null,
    // Which colour var the stripe + glyph use.
    red: el ? el.style.cssText.includes('--red') : null,
    green: el ? el.style.cssText.includes('--green') : null,
    html: el ? el.innerHTML : null,
  }));
} else if (mode === 'wire') {
  const entry = JSON.parse(process.argv[3] || '{}');
  const api = make(...names.map((n) => deps[n]), null, null, null);
  const html = api._renderActivityEntry(entry);
  const handlers = [];
  // The row's own class list, read off the markup the renderer emitted.
  const rowClasses = ((html.match(/<div class="(task-log-row[^"]*)"/) || [])[1] || '')
    .split(/\s+/).filter(Boolean);
  const row = {
    dataset: { entryIdx: '0' },
    classList: { contains: (c) => rowClasses.includes(c), toggle() {} },
    addEventListener: (ev) => handlers.push('row:' + ev),
    querySelector: (sel) => html.includes(`class="${sel.slice(1)}"`)
      ? { addEventListener: (ev) => handlers.push(sel + ':' + ev) }
      : null,
  };
  const list = {
    querySelectorAll: (sel) => (sel === '.task-log-row' ? [row] : []),
  };
  api._wireActivityRows(list);
  const out = { status: entry.status, rowClick: handlers.includes('row:click') };
  for (const sel of WIRED) out[sel] = handlers.includes(sel + ':click');
  console.log(JSON.stringify(out));
} else {
  const entry = JSON.parse(process.argv[3] || '{}');
  const api = make(...names.map((n) => deps[n]), null, null, null);
  const html = api._renderActivityEntry(entry);
  console.log(JSON.stringify({
    status: entry.status,
    // What a person can actually click on this row.
    copyLog: html.includes('task-log-copy'),
    runAgain: html.includes('task-log-run-again'),
    openInChat: html.includes('task-log-open-chat'),
    clearCache: html.includes('task-log-clear-cache'),
    // Is the message on screen at all? Either spelling counts: the slim row
    // escapes the reason inline, the full row hands it to the markdown
    // renderer, and both are "the person can read why".
    showsResult: html.includes(escHtml(entry.result || ' '))
              || html.includes(entry.result || ' '),
    slim: html.includes('is-skipped'),
    // Errors-chip membership.
    chip: api._entryStatus(entry),
    // The dot/stripe name.
    dot: (html.match(/task-log-status task-log-status-(\w+)/) || [])[1] || null,
    // What the row would be entitled to from the shared control rule.
    entitled: api.activityEntryControls(entry),
    html,
  }));
}
