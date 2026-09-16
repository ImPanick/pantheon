// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B81`. Runs the REAL steering block out of `static/js/chatStream.js` together
// with the REAL busy-edge functions out of `static/js/chat.js`, because the
// property the row is about lives between them: `chat.js` raises the busy edge
// at send-path entry and `chatStream.js` decides, on that edge, whether to
// paint the bar. Testing either half alone cannot see it.
//
// Nothing here greps (`Law 20`). "Painted" means a `.steer-bar` node was
// actually inserted before `.chat-input-bar` by the real `_ensureSteerBar`, and
// the timeline below is the order those insertions and removals really
// happened.
//
// One mechanical transform: `export ` is stripped from the sliced declarations,
// because `new Function` is not a module. Nothing else is rewritten.
//
// Modes (argv[2] = turn kind, argv[3] = what the server sends):
//   turn:   agent | research | chat
//   server: none            — an old build: no `stream_steerable` ever arrives
//           steerable       — the run says it can be steered
//           unsteerable     — the run says it cannot
//   Extra turn kinds: agent-resync / research-resync — a second busy edge with
//   no verdict, which is what `setStreamingState('streaming')` produces after
//   the research toggle has been cleared.
//   argv[4] = 'steer' additionally sends one steer and reports the requests.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const streamSrc = fs.readFileSync(path.join(ROOT, 'static', 'js', 'chatStream.js'), 'utf8');
const chatSrc = fs.readFileSync(path.join(ROOT, 'static', 'js', 'chat.js'), 'utf8');

function slice(source, start, end, label) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  if (from < 0 || to < 0 || to <= from) {
    console.error('ANCHOR-MISSING: ' + label + ' :: ' + JSON.stringify(start));
    process.exit(2);
  }
  return source.slice(from, to);
}

const steerBlock = slice(
  streamSrc,
  'const STEER_API_BASE = window.location.origin;',
  '/**\n * Handle a ui_control SSE event',
  'chatStream steering block',
).replace(/^export /gm, '');

// Two anchors, because the first exists only AFTER `B81`. Taking the busy edge
// itself as the required anchor means this harness also runs against the tree as
// it stood — where `_composerTurnSteerable` simply does not exist, the send path
// passes no verdict, and the bar is painted from the mode alone. That is the
// measurement `Law 9` wants, rather than an ANCHOR-MISSING that only says the
// fix is absent.
function sliceOptional(source, start, end) {
  const from = source.indexOf(start);
  if (from < 0) return '';
  const to = source.indexOf(end, from);
  return to > from ? source.slice(from, to) : '';
}
const busyBlock =
  sliceOptional(chatSrc, "  /** `B81`. The composer's own answer",
                '  function _setForegroundChatBusy(active') +
  slice(chatSrc, '  function _setForegroundChatBusy(active',
        '  let _pendingContinue = null;', 'chat.js busy edge');

// The real send-path entry, wrapped so it can be called. This is the line the
// row is about — `_setForegroundChatBusy` raised at submit, ~880 lines before
// the POST — so the harness runs THAT line rather than reproducing it. Its
// surroundings (`_sendInFlight`, the perf mark, the approval handle, the button)
// are inputs, declared in the prologue below; the slice itself is untouched.
const sendEntry = slice(
  chatSrc,
  '    // --- Send-path entry: block re-clicks between submit and stream start ---',
  '    const _releaseSendFlag = () => {',
  'chat.js send-path entry',
);
const sendEntryBlock = [
  'let _sendInFlight = false;',
  'let _pendingToolApproval = null;',
  'function _createChatSendPerf() { return { mark() {}, report() {} }; }',
  'const submitBtn = { classList: { add() {}, remove() {} } };',
  'function __sendPathEntry() {',
  sendEntry,
  '}',
].join('\n');

const turn = process.argv[2] || 'agent';
const server = process.argv[3] || 'none';

// ── stub DOM: only what the steer bar touches ───────────────────────────────
const timeline = [];
function makeNode(tag, id) {
  const node = {
    tagName: String(tag).toUpperCase(), id: id || '', className: '', value: '',
    checked: false, textContent: '', children: [], parentNode: null,
    listeners: {}, attrs: {}, disabled: false,
    isConnected: false,
    appendChild(n) { n.parentNode = this; n.isConnected = true; this.children.push(n); return n; },
    insertBefore(n, ref) {
      n.parentNode = this; n.isConnected = true;
      const i = this.children.indexOf(ref);
      this.children.splice(i < 0 ? this.children.length : i, 0, n);
      if (n.className === 'steer-bar') timeline.push('paint');
      return n;
    },
    removeChild(n) {
      const i = this.children.indexOf(n);
      if (i >= 0) this.children.splice(i, 1);
      n.parentNode = null; n.isConnected = false;
      if (n.className === 'steer-bar') timeline.push('remove');
      return n;
    },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
  };
  return node;
}

const root = makeNode('div');
root.isConnected = true;
const inputBar = makeNode('div');
inputBar.className = 'chat-input-bar';
root.appendChild(inputBar);
const composer = makeNode('textarea', 'message');
const researchToggle = makeNode('input', 'research-toggle');
const sendBtn = makeNode('button');
sendBtn.className = 'send-btn';

const byId = { message: composer, 'research-toggle': researchToggle };
const document = {
  head: makeNode('head'),
  body: makeNode('body'),
  createElement: (t) => makeNode(t),
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => {
    if (sel === '.chat-input-bar') return inputBar;
    if (sel.includes('send-btn')) return null;   // never "streaming" in these runs
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
};

// A window that really dispatches, so the busy edge really reaches the handler.
const winListeners = {};
const window = {
  location: { origin: 'http://test.local' },
  addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); },
  dispatchEvent(ev) { (winListeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
  __pantheonGetChatMode: () => (turn === 'chat' ? 'chat' : 'agent'),
  chatModule: null,
};
class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = (init && init.detail) || null; }
}
const navigator = { platform: 'Linux x86_64' };
const uiModule = {
  el: (id) => byId[id] || null,
  showToast: () => {},
  showError: () => {},
  autoResize: () => {},
};
const sessionModule = { getCurrentSessionId: () => 'sess-1' };
const requests = [];
const fetchStub = async (url, opts) => {
  requests.push({ url: String(url).replace('http://test.local', ''),
                  method: (opts && opts.method) || 'GET' });
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};

const make = new Function(
  'document', 'window', 'navigator', 'uiModule', 'sessionModule', 'fetch', 'CustomEvent',
  busyBlock + '\n\n' + sendEntryBlock + '\n\n' + steerBlock +
  '\n return { _setForegroundChatBusy, handleStreamSteerable, probeSteerSupport, submitSteer,' +
  ' __sendPathEntry,' +
  " _composerTurnSteerable: typeof _composerTurnSteerable === 'function' ? _composerTurnSteerable : null };",
);
const api = make(document, window, navigator, uiModule, sessionModule, fetchStub, CustomEvent);

const barPainted = () => root.children.some(c => c.className === 'steer-bar');

const settle = () => new Promise(r => setTimeout(r, 10));

(async () => {
  if (turn.startsWith('research')) researchToggle.checked = true;
  if (turn === 'broken-composer') {
    // An `el` that throws is the "composer unreadable" case: the verdict has to
    // fail OPEN, or an odd page silently retires steering.
    const _realEl = uiModule.el;
    uiModule.el = (id) => {
      if (id === 'research-toggle') throw new Error('no toggle');
      return _realEl(id);
    };
  }
  // The probe is a per-page question; settle it first so the run below is not
  // measuring the probe's round trip.
  await api.probeSteerSupport();

  // The REAL send-path entry line, run as it stands. Before `B81` it passed no
  // verdict and the second argument did not exist, so this is the true call
  // site on either tree.
  const verdict = api._composerTurnSteerable ? api._composerTurnSteerable() : null;
  api.__sendPathEntry();
  await settle();
  const afterEdge = barPainted();

  if (turn === 'research-then-agent') {
    // Run one ends, run two starts in agent mode on a busy edge that carries no
    // verdict. The first run's `false` must not still be in hand.
    api._setForegroundChatBusy(false);
    await settle();
    researchToggle.checked = false;
    api._setForegroundChatBusy(true);
    await settle();
  } else if (turn === 'research-answered-resync') {
    // The run overruled the composer upward, and THEN the same run is
    // re-announced with no verdict. The run's answer has to keep winning.
    api.handleStreamSteerable({ steerable: true });
    await settle();
    researchToggle.checked = false;
    api._setForegroundChatBusy(true);
    await settle();
  } else if (turn.endsWith('-resync')) {
    // What `setStreamingState('streaming')` does: re-announce the same busy
    // state with no verdict, after the composer has cleared its toggles.
    researchToggle.checked = false;
    api._setForegroundChatBusy(true);
    await settle();
  }
  const afterResync = barPainted();

  if (server === 'steerable') api.handleStreamSteerable({ steerable: true });
  if (server === 'unsteerable') api.handleStreamSteerable({ steerable: false });
  await settle();

  let steerSent = null;
  if (process.argv[4] === 'steer') {
    composer.value = 'turn left instead';
    requests.length = 0;
    steerSent = await api.submitSteer('turn left instead');
  }

  console.log(JSON.stringify({
    verdict,
    // Painted between the send-path entry and the first byte of the response —
    // the window the row measures.
    paintedBeforeTheRunAnswered: afterEdge,
    paintedAfterResync: afterResync,
    paintedNow: barPainted(),
    // Every paint/remove that really happened, in order.
    timeline,
    steerSent,
    requests,
  }));
})().catch((e) => { console.error(e && e.stack || String(e)); process.exit(3); });
