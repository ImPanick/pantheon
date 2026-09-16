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
// `B78`/`B84` add two more surfaces, for the same reason. The run-history
// list's word is built inside an `async` function that fetches, then writes a
// string into `body.innerHTML` — reading the template tells you the expression,
// not the sentence a person ends up looking at. And the notification client's
// wording is chosen three branches into a poll loop, where whether it SHOUTS
// matters as much as what it says: the old form raised the failure dot on every
// status that was not `success`, and no amount of reading `'failed'` in the
// template shows that.
//
// Usage:
//   node activity_row_status.js row     '<entry-json>'
//   node activity_row_status.js badge   '<task-json>'
//   node activity_row_status.js tone
//   node activity_row_status.js history '<runs-json-array>'
//   node activity_row_status.js notify  '<notifications-json-array>'
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'tasks.js');
const source = fs.readFileSync(SRC, 'utf8');

// `B13`/`B87`. The word table is a real module and it is **evaluated, not
// stubbed**. This harness was written for `B07` and the renderer it extracts
// later grew a call to `runStaleLabel`, which was in no stub list — so the
// harness threw `ReferenceError` the first time both changes stood in one tree.
// A stub would have fixed the symptom and left the test asserting a word this
// file made up; reading `runStatus.js` means the row is checked against the
// spelling the app actually ships. It is a leaf module with no imports, which
// is what makes that cheap.
const RUN_STATUS_SRC = path.join(__dirname, '..', '..', 'static', 'js', 'runStatus.js');
const runStatusModule = fs.readFileSync(RUN_STATUS_SRC, 'utf8').replace(/^export\s+/gm, '');
// `B83`. The shared icon table, on the same terms and for the same reason: the
// Activity row's force and stop buttons take their glyphs from it now, and a
// stub would report the harness's triangle rather than the one that ships.
const ICONS_SRC = path.join(__dirname, '..', '..', 'static', 'js', 'icons.js');
const iconsModule = fs.readFileSync(ICONS_SRC, 'utf8').replace(/^export\s+/gm, '');

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
// single source the other sites derive from. `B78` moved it OUT of `tasks.js`
// into `runStatus.js` (a fifth ladder, in `queuePanel.js`, could not import
// `tasks.js` and so had copied it by hand), so it now arrives with the word
// table above rather than as its own slice. The anchor that used to cut it out
// of `tasks.js` is deliberately not kept as a fallback: a harness that silently
// accepts either layout stops being able to say which one shipped.
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
// `B84`. The run-history list — the surface that printed the stored enum at a
// person. Lifted whole, because the word, the row class and the dot colour are
// three expressions inside one loop and the question is what the three of them
// say TOGETHER about a single run.
const history = slice('async function _showRunHistory(taskId, taskName) {',
                      '// ---- Actions ----', '_showRunHistory');
// `B78`. The notification client. Lifted whole for the same reason: `msg` and
// the branch that decides between `showToast` and `showError` are separate
// statements, and the defect was that one status set could reach both.
const notify = slice('async function _pollTaskNotifications() {',
                     'function startNotificationPolling() {', '_pollTaskNotifications');
// `_isChatResultRun` decides the Completed tab's contents and `_isFinishedRun`
// is its only consumer, so the pair is lifted together — the whole point of
// `B78`'s third claim is what the CALLER does with the answer.
const finished = slice('function _runToActivityEntry(r) {',
                       'async function _renderCompletedView() {', '_isFinishedRun');
// `B113`. The tab itself. The row is a claim about whether the CAPTION and the
// FILTER say the same thing, and those are 90 lines apart in two functions — so
// the harness renders the whole view against a stubbed fetch and reports the
// sentence a person reads together with the statuses that got past the filter.
// Reading either one alone is what let them disagree for two rows.
const completedView = slice('async function _renderCompletedView() {',
                            '// ---- Activity sources (P6-07) ----', '_renderCompletedView');
const completedRow = slice('function _renderCompletedPreviewEntry(entry) {',
                           'function _wireCompletedPreviewRows(list) {',
                           '_renderCompletedPreviewEntry');
// The real dot, not a stub. `B78` measured its private colour map as short of
// the six; `B110` deleted the map and made it emit the sheet's own
// `.task-log-status-*` class, so the anchor is the function rather than the
// literal that used to sit above it. A stubbed one would report the harness's
// palette, which is exactly the question.
const dot = slice('function _statusDot(status) {', 'const _TASK_ICONS = {', '_statusDot');
// `B171`. The open-in-chat control's word and sentence, and the function that
// actually seeds the chat session. Both surfaces that draw the button call the
// first and the second decides who is credited with the run's text, so they are
// lifted whole and run — the defect was a `role` in an object literal three
// statements into an async function that fetches twice before reaching it, and
// no amount of reading the template shows what a person ends up looking at.
const openControl = slice('function _openInChatControl(entry) {',
                          "// Open a task run's result in a fresh chat session",
                          '_openInChatControl');
const openInChat = slice('async function _openResultInChat(entry) {',
                         'function _classifyResult(text) {', '_openResultInChat');

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
  ${runStatusModule}
  ${iconsModule}
  ${controls}
  ${openControl}
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

// `B78`/`B84`. A second factory rather than more parameters on the first: the
// run-history list and the notification poller need a DOM and a `fetch` that
// the four original modes must NOT have, and widening the shared factory would
// let a renderer start depending on one without this file noticing.
function makeExtra(extra) {
  const local = { ...deps, ...extra };
  const ks = Object.keys(local);
  return new Function(...ks, `
    let _viewingRuns = null;
    let _open = false;
    let _completedLimit = 40;
    let _completedHasMore = false;
    ${runStatusModule}
    ${iconsModule}
    ${dot}
    ${openControl}
    ${finished}
    ${completedRow}
    ${completedView}
    ${history}
    ${notify}
    ${openInChat}
    return { _showRunHistory, _pollTaskNotifications, _isFinishedRun,
             _isChatResultRun, _renderCompletedView, _renderCompletedPreviewEntry,
             _runToActivityEntry, _openResultInChat, _openInChatControl };
  `)(...ks.map((k) => local[k]));
}

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
    // `B110` moved the badge's three colour variants out of an inline style and
    // onto `.task-lastrun-*` rules, so the stub element has to carry a class the
    // way a real one does or the harness reports "no colour at all".
    createElement: () => ({ style: { cssText: '' }, className: '', innerHTML: '',
                            title: '', addEventListener() {} }),
  };
  const api = make(...names.map((n) => deps[n]), stubDoc,
                   { appendChild: (el) => appended.push(el) }, task);
  api._renderBadge();
  const el = appended[appended.length - 1];
  const cls = el ? String(el.className || '') : '';
  console.log(JSON.stringify({
    status: task.last_run_status,
    // Green tick, red cross, or the neutral dot? This is the whole question:
    // the pre-B07 form had no third answer.
    mark: el ? el.innerHTML.replace(/<[^>]*>/g, '').trim().split(/\s+/)[0] : null,
    // Which colour the stripe + glyph take. Either spelling counts: `B07` wrote
    // the token into an inline style, `B110` moved the same token into a
    // `.task-lastrun-*` rule, and "the badge is in its red variant" is the
    // claim both rows are making.
    red: el ? (cls.includes('task-lastrun-error')
               || el.style.cssText.includes('--red')) : null,
    green: el ? (cls.includes('task-lastrun-ok')
                 || el.style.cssText.includes('--green')) : null,
    cls,
    html: el ? el.innerHTML : null,
  }));
} else if (mode === 'history') {
  // What the run-history list SAYS about each run, read off the markup it
  // writes into the panel rather than off its template.
  const runs = JSON.parse(process.argv[3] || '[]');
  let written = '';
  const bodyEl = {
    set innerHTML(v) { written = String(v); },
    get innerHTML() { return written; },
    appendChild() {}, querySelectorAll: () => [],
  };
  const doc = {
    getElementById: (id) => (id === 'tasks-modal'
      ? { querySelector: () => bodyEl }
      : { addEventListener() {} }),
  };
  const api = makeExtra({
    document: doc,
    _fetchRuns: async () => runs,
    _absoluteTime: () => '09/15 10:00',
    _renderMainView: () => {},
    spinnerModule: { createLoadingRow: () => ({}), createWhirlpool: () => ({ element: { style: {} } }) },
  });
  api._showRunHistory('t1', 'Nightly tidy').then(() => {
    // One record per rendered run, in order.
    const items = written.split('<div class="task-run-item ').slice(1);
    console.log(JSON.stringify(items.map((chunk, i) => ({
      status: runs[i] && runs[i].status,
      rowClass: (chunk.match(/^([a-z-]+)"/) || [])[1] || null,
      // The word a person reads. `null` would mean the slot vanished.
      word: (chunk.match(/<span title="[^"]*">([^<]*)<\/span>/) || [])[1] ?? null,
      // The stored value, which must still be reachable somewhere.
      title: (chunk.match(/<span title="([^"]*)">/) || [])[1] ?? null,
      // `B110`. The dot's `.task-log-status-*` suffix — the Activity row's own
      // rule — where this used to be a hex literal `tasks.js` held itself.
      // `''` means the bare base class, which is the neutral.
      dot: (chunk.match(/class="task-log-status ?(?:task-log-status-)?([a-z]*)"/) || [])[1] ?? null,
    }))));
  });
} else if (mode === 'notify') {
  // What the notification client says, and — the half that matters — whether it
  // shouts. `failure` is `_setTaskFailurePending(true)`: the red dot on the
  // Tasks button that tells a person something is wrong.
  const notes = JSON.parse(process.argv[3] || '[]');
  const said = [];
  let failure = false;
  const api = makeExtra({
    document: { querySelector: () => null },
    fetch: async () => ({ ok: true, json: async () => ({ notifications: notes }) }),
    _setTaskFailurePending: (v) => { if (v) failure = true; },
    _setTaskCompletionPending: () => {},
    _renderCompletedView: () => {},
    _renderActivityView: () => {},
    uiModule: {
      showToast: (m) => said.push({ how: 'toast', msg: m }),
      showError: (m) => said.push({ how: 'error', msg: m }),
      copyToClipboard() {},
    },
  });
  api._pollTaskNotifications().then(() => {
    console.log(JSON.stringify({ said, failure }));
  });
} else if (mode === 'completed') {
  // Which runs reach the Completed tab. `_isFinishedRun` is the name `B78`
  // complains about; `_isChatResultRun` is what the tab actually filters on.
  const entries = JSON.parse(process.argv[3] || '[]');
  const api = makeExtra({});
  console.log(JSON.stringify(entries.map((e) => ({
    status: e.status, kind: e.kind,
    finished: api._isFinishedRun(e),
    inCompletedTab: api._isChatResultRun(e),
  }))));
} else if (mode === 'tab') {
  // `B113`. The Completed tab, rendered whole from a stubbed `/runs/recent`:
  // the caption a person reads, the statuses that got past the filter, and the
  // word each surviving row shows for its own outcome. One render, because the
  // row's claim is that those three agree.
  const runs = JSON.parse(process.argv[3] || '[]');
  let written = '';
  const listEl = {
    set innerHTML(v) { written = String(v); },
    get innerHTML() { return written; },
    appendChild() {}, insertAdjacentHTML() {},
    querySelector: () => null, querySelectorAll: () => [],
  };
  let shellHtml = '';
  const bodyEl = {
    set innerHTML(v) { shellHtml = String(v); },
    get innerHTML() { return shellHtml; },
    querySelector: () => null,
  };
  const doc = {
    getElementById: (id) => (id === 'tasks-modal'
      ? { querySelector: () => bodyEl }
      : id === 'tasks-completed-list' ? listEl
      : { addEventListener() {} }),
  };
  const api = makeExtra({
    document: doc,
    fetch: async () => ({ ok: true, json: async () => ({ runs, has_more: false }) }),
    _setTaskCompletionPending: () => {},
    _syncCompletedTabCount: () => {},
    _wireCompletedPreviewRows: () => {},
    _taskIcon: () => '<svg data-icon="1"></svg>',
    _taskAiMark: () => '',
    _relativeTime: () => '2m ago',
    markdownModule: { mdToHtml: (t) => `<p>${t}</p>`, squashOutsideCode: (t) => t,
                      processWithThinking: (t) => `<p>${t}</p>` },
    spinnerModule: { createLoadingRow: () => ({}),
                     createWhirlpool: () => ({ element: { style: {} } }) },
  });
  api._renderCompletedView().then(() => {
    // The caption, as text, off the shell the view actually wrote.
    const caption = (shellHtml.match(/<p class="memory-desc">([\s\S]*?)<\/p>/) || [])[1] || '';
    const rows = written.split('<div class="memory-item doclib-chat-row task-completed-preview-row').slice(1);
    console.log(JSON.stringify({
      caption: caption.replace(/<[^>]*>/g, '').trim(),
      empty: /task-completed-empty/.test(written)
        ? written.replace(/<[^>]*>/g, '').trim() : null,
      rows: rows.map((chunk) => ({
        // The dot's shared class, and the word beside it — `null` when the row
        // shows no word, which is the success case.
        dot: (chunk.match(/class="task-log-status ?(?:task-log-status-)?([a-z]*)"/) || [])[1] ?? null,
        titled: (chunk.match(/class="task-log-status[^"]*" title="([^"]*)"/) || [])[1] ?? null,
        word: (chunk.match(/class="task-completed-outcome">([^<]*)</) || [])[1] ?? null,
        name: (chunk.match(/class="task-log-name">([^<]*)</) || [])[1] ?? null,
        // `B171`. The row's own open control, same two questions as the
        // Activity row's, so the test can put the two side by side.
        openLabel: ((chunk.match(
          /class="doclib-chat-open-btn task-completed-open-chat"[^>]*>[\s\S]*?<\/svg>\s*([^<]*)</) || [])[1] || '')
          .trim() || null,
        openTitle: (chunk.match(
          /class="doclib-chat-open-btn task-completed-open-chat" type="button" title="([^"]*)"/) || [])[1] ?? null,
      })),
    }));
  });
} else if (mode === 'open') {
  // `B171`. What pressing *Open in chat* actually puts in the session, and what
  // the button said it would do. The whole point is that these two are decided
  // in different functions 400 lines apart, so they are reported from one run:
  // the control's word and sentence, and the messages the session is seeded
  // with, each with the role it is attributed to.
  const entry = JSON.parse(process.argv[3] || '{}');
  const injected = [];
  let sessionName = '';
  const api = makeExtra({
    document: { getElementById: () => null, querySelector: () => null },
    window: {
      modelsModule: { getCachedItems: () => [] },
      sessionModule: { loadSessions: async () => {}, selectSession: () => {} },
    },
    closeTasks: () => {},
    fetch: async (url, opts) => {
      const u = String(url);
      if (u.includes('/inject_messages')) {
        injected.push(...JSON.parse(opts.body).messages);
        return { ok: true, json: async () => ({}) };
      }
      if (u.includes('/api/session')) {
        try { sessionName = opts.body.get('name'); } catch (_) {}
        return { ok: true, json: async () => ({ id: 's1' }) };
      }
      // `/api/default-chat`
      return { ok: true, json: async () => ({ endpoint_url: 'http://x', model: 'm' }) };
    },
  });
  api._openResultInChat(entry).then(() => {
    const control = api._openInChatControl(entry);
    console.log(JSON.stringify({
      status: entry.status,
      label: control.label,
      title: control.title,
      sessionName,
      // The claim `B171` makes: nothing the run reported is attributed to the
      // assistant unless the assistant actually produced it.
      roles: injected.map((m) => m.role),
      messages: injected,
      assistantSaid: injected.filter((m) => m.role === 'assistant')
                             .map((m) => m.content),
    }));
  });
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
    // `B171`. The word on the open control and the sentence it carries, read
    // off the emitted markup rather than off the expression that built them.
    openLabel: ((html.match(
      /class="task-log-open-chat"[^>]*>[\s\S]*?<\/svg>\s*([^<]*)</) || [])[1] || '')
      .trim() || null,
    openTitle: (html.match(
      /class="task-log-open-chat" type="button" title="([^"]*)"/) || [])[1] ?? null,
    // What the row would be entitled to from the shared control rule.
    entitled: api.activityEntryControls(entry),
    html,
  }));
}
