# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-24` — a stream picked up after navigating away draws what the live one
drew.

**What was wrong.** `resumeStream` (`static/js/chat.js`) is how a chat shows a
run that kept going while nobody watched it: `GET /api/chat/resume` replays the
run's whole buffer from its first event and then streams live. Its dispatch
chain drew the reply's text into one bubble — every step's text run together —
and turned every other event into `rich = true`: the tool cards, the steps,
the prep line (`P4-08`), the meter (`P4-23`), the stop line (`P4-10`), all of
it. A chat reopened in the same tab (`checkBackgroundStream`) got less: one
spinner saying "Response streaming in background".

**What is pinned here.** Driven under node against the real modules
(`agentThread.js`, `agentMeter.js`, `agentStops.js`, `spinner.js`, and
`agentTurn.js`, where `B918` moved the card's life so a compare pane shares it)
and against the real functions cut out of `chat.js` — the live stream's own
arms, the shared drawing functions, `resumeStream` itself:

  * one recorded agent run, fed through the live arms and through the resumed
    stream, draws the same thing after every event — threads, cards, steps,
    spinners, the meter's words, the stop line;
  * and what that is, said outright, so a change that broke both paths the
    same way is caught too;
  * a refused call as a step's first act and after its text, and text after a
    tool — the live arms `B904` changed — drawn the same by both;
  * a replay over a view of the same run already on the page — the live one a
    dropped connection left behind — replaces it rather than doubling it;
  * the stop line is never on the page twice: the resumed view takes its own
    copy away before the reload draws the saved one;
  * leaving the chat mid-replay draws nothing into the chat you went to;
  * reasoning tokens reach the renderer as a thinking block, not as the reply;
  * a chat reopened in the same tab is drawn by the replay, and the tab's own
    reader stops drawing once it is.

Compare mode's own stop line (`B910`) is `test_a_compare_pane_says_why_it_stopped.py`,
which runs in the page this file sets up.

Every case runs code; none asserts on the text of a source file (`Law 20`).
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.js_source import js_assignment, js_binding, js_definition, js_function  # B876, B914
from tests.helpers.source_text import blank_text  # B290
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the page ────────────────────────────────────────────────────────────────
# `test_tool_effect_surfaces_js`'s shim, plus what a stream view reads that an
# approval card never did: markup parsed into nodes (the resumed bubble is
# built with `innerHTML`, and a card's wave and clock are found inside its
# markup), siblings, whether a node is on the page, and a clock the case turns.

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'source', 'track', 'wbr']);
const TOKEN = /<!--[\s\S]*?-->|<\/([A-Za-z][\w-]*)\s*>|<([A-Za-z][\w-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|([^<]+)|</g;
const ATTR = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
const ENTITY = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", '#x27': "'", nbsp: ' ' };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39|#x27|nbsp);/g, (m, k) => ENTITY[k]);

function parseInto(parent, html) {
  const stack = [parent];
  const token = new RegExp(TOKEN.source, 'g');
  let m;
  while ((m = token.exec(html))) {
    const top = stack[stack.length - 1];
    if (m[1]) {
      const tag = m[1].toUpperCase();
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === tag) { stack.length = i; break; }
      }
    } else if (m[2]) {
      const el = new Node(m[2]);
      const attr = new RegExp(ATTR.source, 'g');
      let a;
      while ((a = attr.exec(m[3] || ''))) {
        const value = decode(a[2] ?? a[3] ?? a[4] ?? '');
        if (a[1] === 'class') el.className = value;
        else if (a[1] === 'id') el.id = value;
        else if (a[1].startsWith('data-')) {
          el.dataset[a[1].slice(5).replace(/-([a-z])/g, (x, c) => c.toUpperCase())] = value;
        } else el.attrs[a[1]] = value;
      }
      el.parentNode = top;
      top.childNodes.push(el);
      if (!m[4] && !VOID.has(m[2].toLowerCase())) stack.push(el);
    } else if (m[5] !== undefined || m[0] === '<') {
      const text = new Node('#text');
      text._text = decode(m[5] !== undefined ? m[5] : '<');
      text.parentNode = top;
      top.childNodes.push(text);
    }
  }
}

Object.defineProperty(Node.prototype, 'innerHTML', {
  configurable: true,
  get() { return this._html; },
  set(v) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = []; this._text = ''; this._html = String(v == null ? '' : v);
    parseInto(this, this._html);
  },
});
// A browser moves a node that is appended somewhere else; the base shim copies it.
const append = Node.prototype.appendChild;
Node.prototype.appendChild = function (n) {
  if (n && n.tagName !== '#FRAGMENT' && n.parentNode) n.parentNode.removeChild(n);
  return append.call(this, n);
};
const getter = (name, get) => Object.defineProperty(Node.prototype, name, { configurable: true, get });
getter('isConnected', function () {
  let n = this; while (n.parentNode) n = n.parentNode; return n.tagName === '#DOCUMENT';
});
getter('parentElement', function () {
  const p = this.parentNode; return p && p.tagName !== '#DOCUMENT' ? p : null;
});
getter('lastElementChild', function () { const c = this.children; return c[c.length - 1] || null; });
getter('previousElementSibling', function () {
  const p = this.parentNode; if (!p) return null;
  const c = p.children; const i = c.indexOf(this); return i > 0 ? c[i - 1] : null;
});
getter('nextSibling', function () {
  const p = this.parentNode; if (!p) return null;
  return p.childNodes[p.childNodes.indexOf(this) + 1] || null;
});
Node.prototype.closest = function (sel) {
  for (let n = this; n && n.tagName !== '#DOCUMENT'; n = n.parentNode) {
    if (n.tagName !== '#TEXT' && n.matches(sel)) return n;
  }
  return null;
};
globalThis.dispatchEvent = () => true;
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};

// The clock the case turns: `setTimeout` waits until `flushTimers` says so, so
// a 400ms pause happens exactly where the recorded run says one does.
let clock = 0;
let queue = [];
globalThis.setTimeout = (fn, ms) => {
  const t = { fn, at: clock + Number(ms || 0), live: true };
  queue.push(t);
  return t;
};
globalThis.clearTimeout = (t) => { if (t && typeof t === 'object') t.live = false; };
export function flushTimers(ms = 1000) {
  clock += ms;
  const due = queue.filter((t) => t.live && t.at <= clock);
  queue = queue.filter((t) => t.live && t.at > clock);
  for (const t of due) t.fn();
}

// ── reading the page the way a person does ────────────────────────────────
const text = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
const shown = (n) => !(n && n.style && n.style.display === 'none');
/** A spinner's words, without the frame of its wave. */
export function spinnerWords(root) {
  const s = root && root.querySelector('.ai-spinner');
  return s ? text(s).replace(/[▁▂▃▄▅▆▇]/g, '').trim() : null;
}
/** What the meter under a spinner says, part by part. `null` when there is none. */
export function meterWords(root) {
  const m = root && root.querySelector('.agent-meter');
  if (!m || m.hidden) return null;
  const part = (cls) => { const p = m.querySelector('.' + cls); return p && !p.hidden ? text(p) : ''; };
  return [part('agent-meter-prep'), part('agent-meter-steps'), part('agent-meter-tools'),
          part('agent-meter-note')].filter(Boolean).join(' | ');
}
export function card(node) {
  const cls = node._classes();
  return {
    tool: text(node.querySelector('.agent-thread-tool')),
    state: cls.includes('running') ? 'running' : (cls.includes('error') ? 'failed' : 'done'),
    round: text(node.querySelector('.agent-thread-round')),
    tail: text(node.querySelector('.agent-thread-tail')),
  };
}
/** Everything the history shows, top to bottom. */
export function describe(box) {
  return box.children.map((n) => {
    const cls = n._classes();
    if (cls.includes('agent-thread')) {
      return { thread: n.querySelectorAll('.agent-thread-node').map(card),
               top: cls.includes('has-top'), bottom: cls.includes('has-bottom') };
    }
    if (cls.includes('agent-stop')) return { stop: text(n.querySelector('.agent-stop-headline')) };
    // `B915` / `B917`: the turn's other notes, with whether Continue is offered.
    if (cls.includes('rounds-exhausted')) {
      return { note: text(n.querySelector('.rounds-exhausted-label')), continue: !!n.querySelector('.continue-btn') };
    }
    for (const kind of ['budget-exceeded-note', 'teacher-takeover-banner', 'skill-saved-note', 'escalation-failed-note']) {
      if (cls.includes(kind)) return { note: text(n), kind };
    }
    if (cls.includes('agent-thinking-dots')) return { waiting: spinnerWords(n), meter: meterWords(n) };
    if (cls.includes('generated-image-wrap')) return { image: true };
    if (cls.includes('msg')) {
      return { bubble: shown(n) ? 'shown' : 'hidden', text: text(n.querySelector('.stream-content')),
               spinner: spinnerWords(n), meter: meterWords(n) };
    }
    return { other: n.className };
  });
}
"""

_STUBS = {
    # `B874`: the shipped `esc`, not a copy of it.
    "ui.js": ui_default_stub("showToast() {}, showError() {}, scrollHistory() {},\n"
                             "el: (id) => document.getElementById(id),"),
    # `B918`: what `agentTurn.js` — the card's life, moved out of `chat.js` so a
    # compare pane can draw it too — reads from the renderer. The same answers
    # the `chatRenderer` object in `_PREAMBLE` gives the code cut out of chat.js.
    "chatRenderer.js": """
export const buildTodoCard = () => '';
export function demoteSupersededTodoCards() {}
export const safeToolScreenshotSrc = (s) => String(s || '');
export const buildDiffHtml = (d) => (d ? '<div class="agent-diff">changed</div>' : '');
""",
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("resumedview"), JS / "agentThread.js",
                      _SHIM, _STUBS)
    for name in ("agentMeter.js", "agentStops.js", "spinner.js", "agentTurn.js",
                 "chatModelProvenance.js", "chatStreamErrors.js"):
        shutil.copy(JS / name, d / name)
    return d


# ── chat.js, cut into the pieces the two streams run ────────────────────────

def _chat():
    return CHAT_JS.read_text(encoding="utf-8")


def _defn(name: str, prefix: str = "function ") -> str:
    """One whole top-level declaration, located in comment-blanked text so a
    name quoted in prose cannot be mistaken for the code."""
    src = _chat()
    code = blank_text(src, "js")
    return js_definition(src, code.index(f"{prefix}{name}("))


def _live_handler() -> str:
    """`handleChatSubmit`, the function the live stream runs in. `resumeStream`
    has arms that open the same way (`teacher_takeover` since `B917`), so the
    live arms are cut from here, not from the whole file."""
    chat = _chat()
    return js_definition(chat, blank_text(chat, "js").index("export async function handleChatSubmit("))


def _arm(anchor: str) -> str:
    """One arm of the live stream's dispatch, braces and all."""
    return js_function(_live_handler(), anchor)


def _assigned(name: str, marker: str) -> str:
    """The body of the arrow function the live handler assigns to `name` —
    the one holding `marker`. The handler declares every such name first as a
    no-op (`let _finalizeRoundRender = () => {};`, so the catch path can see
    it), and cutting by the name alone returns that `{}`. `B914`: the cutter
    is shared with `P4-10`'s file, which cut by the name alone."""
    return js_assignment(_chat(), name, marker)


def _between(start: str, end: str) -> str:
    """Comment-blanked code from `start` up to and including `end`."""
    code = blank_text(_chat(), "js")
    at = code.index(start)
    return code[at:code.index(end, at) + len(end)]


# The functions both streams draw with, and what they stand on.
_MODULE_LEVEL = (
    "_stripDocumentFenceForChat", "_stripIncompleteRawToolJsonForChat", "_streamDisplayText",
    "_showDocumentWritingStatus", "_finishDocumentWritingStatus", "hasActiveStream",
    "_metricsCostRecordId", "_appendGeneratedImageBubble",
    "_createWaitSpinners", "_newRoundBubble", "_threadForNextCard",
    "_threadIntoNextStep",   # `B919`
    "_headWithTeacher",      # `B922`
    "_threadOrBare", "_removeViewFrom",
    "checkBackgroundStream", "_showBackgroundStreamSpinner",
)


def _module_level() -> str:
    parts = [_defn(name) for name in _MODULE_LEVEL]
    parts.append(_defn("resumeStream", "async function "))
    parts.append(js_binding(_chat(), "_RESUME_RELOAD_TYPES") + ";")
    return "\n".join(parts)


_PREAMBLE = r"""
import { document, Node, flushTimers, describe } from './shim.js';
import { applyAgentThreadNode, verifierCardOptions, blockedCardOptions, toolOutputPanesHtml,
         agentThreadContent, TOOL_LABELS } from './agentThread.js';
import { renderAgentStop, renderAgentNote } from './agentStops.js';
import { createAgentMeter, presentMeterEvent, METER_EVENT_TYPES } from './agentMeter.js';
// `B918` / `B916`: the card's life and a new step's spinner, the real module,
// under the names chat.js imports them as.
import { startToolCard as _startToolCard, drawToolProgress as _drawToolProgress,
         finishToolCard as _finishToolCard, stopCardTickers as _stopCardTickers,
         openRoundSpinner as _openRoundSpinner } from './agentTurn.js';
import spinnerModule from './spinner.js';
import uiModule from './ui.js';
import { inheritModelRouteState, applyModelRouteEventState } from './chatModelProvenance.js';
import { createTerminalStreamError } from './chatStreamErrors.js';

const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');

// The renderer: a `<think>` block becomes a thinking section, the rest a
// paragraph. `rendered` keeps every text it was handed.
const rendered = [];
function renderText(s) {
  const esc = uiModule.esc;
  const t = String(s == null ? '' : s);
  const m = t.match(/^<think>([\s\S]*?)<\/think>([\s\S]*)$/);
  if (m) return '<div class="thinking-section">' + esc(m[1]) + '</div>' + (m[2] ? '<p>' + esc(m[2]) + '</p>' : '');
  return t ? '<p>' + esc(t) + '</p>' : '';
}
const markdownModule = {
  normalizeThinkingMarkup: (s) => String(s == null ? '' : s),
  squashOutsideCode: (s) => String(s == null ? '' : s),
  processWithThinking: (s) => { rendered.push(String(s)); return renderText(s); },
  mdToHtml: (s) => renderText(s),
};
const added = [];
const chatRenderer = {
  buildTodoCard: () => '',
  demoteSupersededTodoCards() {},
  safeToolScreenshotSrc: (s) => String(s || ''),
  recordSessionMetricsCost() {},
  addMessage(role, text, model) { added.push({ role, text, model }); },
  buildImageBubble() { const d = document.createElement('div'); d.className = 'generated-image-wrap'; return d; },
  stripToolBlocks: (s) => String(s == null ? '' : s),
};
const buildDiffHtml = (d) => (d ? '<div class="agent-diff">changed</div>' : '');
const _buildImageBubble = chatRenderer.buildImageBubble;
const stripToolBlocks = chatRenderer.stripToolBlocks;
const _shortModel = (m) => String(m || '');
const _modelRouteLabel = (requested, actual) => String(actual || requested || '');
const _applyModelColor = () => {};
const _setRoleModelLabel = (el, requested, actual) => { if (el) el.textContent = String(actual || ''); };
const displayMetrics = () => {};
const documentModule = null;
const reloads = [];
const sessionModule = {
  current: 's1',
  getCurrentSessionId() { return this.current; },
  getSessions: () => [{ id: 's1', model: 'test-model' }],
  selectSession(id) { reloads.push({ id, stops: history.querySelectorAll('.agent-stop').length, view: describe(history) }); },
  loadSessions() {},
};
const API_BASE = '';
const _activeStreams = new Map();
const _backgroundStreams = new Map();
const _resumingStreams = new Set();
const _streamRunIds = new Map();
const _researchingStreamIds = new Set();
let _streamSessionId = null;
let isStreaming = true;
/** Empty the history the way a reload does: every node leaves the page. */
function clear() { for (const c of history.childNodes.slice()) c.remove(); }
"""


def _live_driver() -> str:
    """The live stream's arms, cut out of `handleChatSubmit` and run in the
    order the recorded run delivers them, over the state `handleChatSubmit`
    keeps — with the closures those arms call (`_cardThread`, `_openRoundBubble`
    since `B904`), cut out with them."""
    chat = _chat()
    code = blank_text(chat, "js")
    meter_arms = code[code.index("if (json.type === 'agent_prep') {"):
                      code.index("if (json.type === 'tool_approval_resolved') {")]
    arms = [
        ("tool_start", "} else if (json.type === 'tool_start') {"),
        ("tool_progress", "} else if (json.type === 'tool_progress') {"),
        ("tool_output", "} else if (json.type === 'tool_output') {"),
        ("tool_blocked", "} else if (json.type === 'tool_blocked') {"),
        ("verifier", "} else if (json.type === 'verifier') {"),
        ("agent_step", "} else if (json.type === 'agent_step') {"),
        # `B915` / `B917`: the turn's notes and the takeover.
        ("rounds_exhausted", "} else if (json.type === 'rounds_exhausted') {"),
        ("budget_exceeded", "} else if (json.type === 'budget_exceeded') {"),
        ("teacher_takeover", "} else if (json.type === 'teacher_takeover') {"),
        ("skill_saved", "} else if (json.type === 'skill_saved') {"),
    ]
    dispatch = "\n".join(
        f"      {'if' if i == 0 else 'else if'} (json.type === '{name}') {_arm(anchor)}"
        for i, (name, anchor) in enumerate(arms))
    dispatch += ("\n      else if (json.type === 'loop_breaker_triggered' || json.type === 'intent_nudge_exhausted') "
                 + _arm("} else if (json.type === 'loop_breaker_triggered'"))
    dispatch += ("\n      else if (json.type === 'escalation_failed' || json.type === 'skill_save_failed') "
                 + _arm("} else if (json.type === 'escalation_failed' || json.type === 'skill_save_failed') {"))
    return (r"""
function runLive(events, snaps, { runId = 'run-1', stopAfter = Infinity } = {}) {
  const box = history;
  const streamSessionId = 's1';
  const modelName = 'test-model';
  let holder = document.createElement('div');
  holder.className = 'msg msg-ai streaming';
  holder.innerHTML = '<div class="role">test-model</div><div class="body"></div>';
  if (runId) holder.dataset.agentRun = runId;
  box.appendChild(holder);
  let spinner = spinnerModule.create('Processing request', 'right', 'wave');
  holder.querySelector('.body').appendChild(spinner.createElement());
  spinner.start();
  let roundHolder = holder;
  let roundText = '';
  let roundReplyText = null;
  let currentToolBubble = null;
  let lastToolThread = null;
  let roundFinalized = false;
  let roundFinalization = null;
  let lastContentRoundHolder = null;
  let isThinking = false;
  let _thinkingMode = null;
  let _thinkingRecheckAt = 0;
  let _docFenceOpened = false;
  const _thinkingAnalysisGate = { reset() {} };
  const _roundDisplayProjector = { reset() {} };
  const _replyDisplayProjector = { reset() {} };
  const streamingTTS = false;
  const _meter = createAgentMeter();
  let _removeThinkingSpinner = () => {};
  let _cancelThinkingTimer = () => {};
  const _closeOpenThinkingMarkup = () => {};
  const _endLiveThinkingSection = () => {};
  const _cancelLiveThinkingWork = () => {};
  const _cancelThinkingGrace = () => {};
  const _rememberGeneratedImage = () => {};
  const planWindow = { noteToolStart() {}, noteToolEnd() {} };
  const chatStream = { handleUIControl() {} };
  let _lastToolName = '';
  __ENSURE_LAYOUT__
  __ENSURE_VISIBLE__
  __OPEN_ROUND__
  __CARD_THREAD__
  const _finalizeRoundRender = () => __FINALIZE__;
  __WAIT__
  let n = 0;
  for (const json of events) {
    if (n++ >= stopAfter) break;
    if (json === 'flush') { flushTimers(); snaps.push(describe(history)); continue; }
    if (json === '[DONE]') break;
    for (const _once of [0]) {
      const _isBg = false;
      if (json.delta) {
        // Stand-in for the live text arm. Its thinking box, projectors and
        // speech are the live stream's own and not what this row shares; what
        // it does to the bubbles and the spinners is this.
        _cancelThinkingTimer();
        _removeThinkingSpinner();
        _ensureVisibleRoundForDelta();
        roundText += json.delta;
        if (spinner && spinner.element) spinner.destroy();
        const content = _ensureStreamLayout(roundHolder.querySelector('.body'));
        content.innerHTML = markdownModule.processWithThinking(
          markdownModule.squashOutsideCode(_streamDisplayText(roundText)));
        _scheduleThinkingSpinner();
        continue;
      }
      __METER_ARMS__
__DISPATCH__
    }
    snaps.push(describe(history));
  }
  _cancelThinkingTimer();
}
"""
            .replace("__ENSURE_LAYOUT__", _defn("_ensureStreamLayout"))
            .replace("__ENSURE_VISIBLE__", _defn("_ensureVisibleRoundForDelta"))
            .replace("__OPEN_ROUND__", _defn("_openRoundBubble"))
            .replace("__CARD_THREAD__", _defn("_cardThread"))
            .replace("__FINALIZE__", _assigned("_finalizeRoundRender",
                                               "if (roundFinalized) return roundFinalization;"))
            .replace("__WAIT__", _between("const _wait = _createWaitSpinners({",
                                          "_cancelThinkingTimer = () => { _wait.cancel(); };"))
            .replace("__METER_ARMS__", meter_arms)
            .replace("__DISPATCH__", dispatch))


_RESUMED_DRIVER = r"""
/** Feed `events` to the real `resumeStream` as the run's replayed buffer.
 *  `snaps[i]` is the page once event `i` has been drawn. */
async function runResumed(events, snaps, { runId = 'run-1', onEvent = null, opts = {}, failAt = -1 } = {}) {
  const enc = new TextEncoder();
  let i = 0;
  const reader = {
    async read() {
      if (i > 0 && i <= events.length) {
        snaps.push(describe(history));
        if (onEvent) onEvent(i - 1);
      }
      while (events[i] === 'flush') { flushTimers(); snaps.push(describe(history)); i++; }
      if (i === failAt) throw new TypeError('network error');
      if (i >= events.length) return { done: true };
      const e = events[i++];
      const sse = e === '[DONE]' ? 'data: [DONE]\n\n'
        : (e && e.sseError ? 'event: error\ndata: ' + JSON.stringify(e.sseError) + '\n\n'
          : 'data: ' + JSON.stringify(e) + '\n\n');
      return { done: false, value: enc.encode(sse) };
    },
    async cancel() {},
  };
  globalThis.fetch = async () => ({ ok: true, body: { getReader: () => reader },
                                    headers: { get: () => runId } });
  return resumeStream('s1', null, opts);
}
"""


def _page(sandbox, body: str) -> dict:
    """Run `body` with everything above defined; it logs one JSON line."""
    script = (_module_level() + "\n" + _live_driver() + "\n" + _RESUMED_DRIVER
              + "\n" + textwrap.dedent(body))
    return _run(sandbox, _PREAMBLE, script)


# ── the recorded run ────────────────────────────────────────────────────────
# One agent turn, in the order the loop sends it: four prep steps, a step that
# says a sentence and runs a command (which reports progress), a pause, a second
# step that searches, has a call refused and its work checked, a third step
# whose repeated call the loop-breaker stops, and the answer after it.

def _budget(round_, calls):
    return {"type": "agent_budget", "round": round_, "round_limit": 20,
            "round_limit_source": "configured", "tool_calls": calls, "tool_call_limit": 10}


_STOP = {
    "type": "loop_breaker_triggered", "reason": "loop_breaker_stall", "kind": "identical_calls",
    "round": 3, "tool": "bash", "count": 15, "arguments_state": "shown",
    "arguments": "tail -n 50 /var/log/app.log",
    "message": "Stopped: called bash with identical arguments 15 times.",
    "next": "That last attempt was not run.",
}

RUN = [
    {"type": "agent_prep", "status": "running", "phase": "request_setup", "data": {}},
    {"type": "agent_prep", "status": "running", "phase": "tool_selection", "data": {"request_setup": 0.02}},
    {"type": "agent_prep", "status": "running", "phase": "prompt_build",
     "data": {"request_setup": 0.02, "tool_selection": 0.4}},
    {"type": "agent_prep", "status": "done", "total": 0.5,
     "data": {"request_setup": 0.02, "tool_selection": 0.4, "prompt_build": 0.05, "context_trim": 0.03}},
    _budget(1, 0),
    {"delta": "Let me look at the logs."},
    {"type": "tool_start", "tool": "bash", "command": "ls -la /var/log", "round": 1},
    _budget(1, 1),
    {"type": "tool_progress", "tool": "bash", "elapsed_s": 2.5, "tail": "app.log\nsyslog"},
    {"type": "tool_output", "tool": "bash", "command": "ls -la /var/log", "round": 1,
     "exit_code": 0, "output": "app.log\nsyslog"},
    "flush",
    {"type": "agent_step", "round": 2},
    _budget(2, 1),
    {"type": "tool_start", "tool": "web_search", "command": "pantheon logs", "round": 2},
    _budget(2, 2),
    {"type": "tool_output", "tool": "web_search", "command": "pantheon logs", "round": 2,
     "exit_code": 0, "output": "3 results"},
    {"type": "tool_blocked", "tool": "bash", "command": "rm -rf /var/log", "round": 2,
     "reason": "refused by the current tool policy"},
    {"type": "verifier", "outcome": "pass", "round": 2},
    {"type": "agent_step", "round": 3},
    _budget(3, 2),
    _STOP,
    {"type": "agent_step", "round": 4},
    _budget(4, 2),
    {"delta": "Here is what I found."},
    "[DONE]",
]


def _both(sandbox, events=RUN) -> dict:
    return _page(sandbox, """
        const events = %s;
        const live = [];
        runLive(events, live);
        clear();
        const resumed = [];
        await runResumed(events, resumed);
        console.log(JSON.stringify({ live, resumed, reloads, added }));
    """ % json.dumps(events))


# ── P4-24: the same drawing, from the same functions ────────────────────────

def test_a_resumed_stream_draws_what_the_live_one_drew(sandbox):
    out = _both(sandbox)
    live, resumed = out["live"], out["resumed"]
    steps = len([e for e in RUN if e != "[DONE]"])
    assert len(live) == steps and len(resumed) == steps
    for i, (a, b) in enumerate(zip(live, resumed)):
        event = RUN[i] if RUN[i] == "flush" else RUN[i].get("type", "delta")
        assert b == a, f"after event {i} ({event}) the resumed view differs from the live one"


def test_what_both_draw_is_the_run(sandbox):
    """The comparison above cannot see a change that breaks both paths the
    same way, so this says what the page shows, outright."""
    out = _both(sandbox)
    at = {i: snap for i, snap in enumerate(out["resumed"])}
    # Preparing: the spinner names the running step, the line under it the
    # finished ones — the prep line drawn by the call the live stream makes.
    assert at[1][0]["spinner"] == "Choosing tools"
    assert at[1][0]["meter"].startswith("Preparing · Request setup 0.02s · Tool selection")
    assert at[3][0]["spinner"] == "Waiting for the model"
    assert "Prepared in 0.50s" in at[3][0]["meter"]
    # Step 1's budget frame: the meter under the spinner states both rules.
    assert "Step 1 of 20" in at[4][0]["meter"] and "Tool calls 0 of 10" in at[4][0]["meter"]
    # The sentence, then the command: text in the bubble, a running card.
    assert at[5][0] == {"bubble": "shown", "text": "Let me look at the logs.", "spinner": None, "meter": None}
    assert at[6][1]["thread"] == [{"tool": "Running", "state": "running", "round": "1", "tail": ""}]
    # Its progress: the tail of its output on the running card.
    assert at[8][1]["thread"][0]["tail"] == "app.log syslog"
    assert at[9][1]["thread"] == [{"tool": "Terminal", "state": "done", "round": "1", "tail": ""}]
    # The pause: the "Thinking" spinner between tools, carrying the meter.
    assert at[10][-1]["waiting"] == "Thinking"
    assert "Step 1 of 20" in at[10][-1]["meter"] and "Tool calls 1 of 10" in at[10][-1]["meter"]
    # Step 2 opens its own bubble, with a spinner and the meter under it.
    assert at[11][-1]["spinner"] == "Generating response"
    assert "Step 2 of 20" in at[12][-1]["meter"]
    # Its cards: the search, the refused call, and the verdict on the work.
    # Step 2 wrote no text, so its cards continue step 1's thread — the live
    # stream's rule, and the same one history replay follows.
    final = at[len(at) - 1]
    threads = [e["thread"] for e in final if "thread" in e]
    assert len(threads) == 1
    assert [c["tool"] for c in threads[0]] == ["Terminal", "Web Search", "Terminal · blocked", "Verified"]
    assert [c["state"] for c in threads[0]] == ["done", "done", "failed", "done"]
    assert [c["round"] for c in threads[0]] == ["1", "2", "2", "2"]
    # The loop-breaker's line, between the work and the answer after it.
    kinds = [next(iter(e)) for e in final]
    assert kinds.count("stop") == 1
    assert final[kinds.index("stop")]["stop"] == _STOP["message"]
    assert kinds.index("stop") > max(i for i, k in enumerate(kinds) if k == "thread")
    assert final[-1]["text"] == "Here is what I found."
    assert kinds.index("stop") < len(kinds) - 1
    # Steps that wrote nothing are hidden, as the live stream hides them.
    assert [e["bubble"] for e in final if "bubble" in e] == ["shown", "hidden", "hidden", "shown"]


# ── P4-24 × B904: what the merge rewired, through both streams ──────────────
# `B904` gave the live stream two rules the resumed one follows too: a refused
# call closes the step and goes where a card would go, and a card after anything
# visible — the step's own text among it — starts a thread below that. Text after
# a tool, in a step that wrote nothing before it, opens a bubble below the thread
# (`_openRoundBubble` live, `openRound` resumed, both through `_newRoundBubble`).
# The recorded run above reaches none of the three.

REFUSALS = [
    {"type": "tool_blocked", "tool": "write_file", "command": "notes.txt", "round": 1,
     "reason": "refused by the current tool policy"},
    {"type": "tool_start", "tool": "read_file", "command": "notes.txt", "round": 1},
    {"type": "tool_output", "tool": "read_file", "command": "notes.txt", "round": 1,
     "exit_code": 0, "output": "old copy"},
    {"delta": "Found it. Now I'll delete the old copy."},
    {"type": "tool_blocked", "tool": "bash", "command": "rm notes.txt", "round": 1,
     "reason": "refused by the current tool policy"},
    {"type": "agent_step", "round": 2},
    {"delta": "I can't delete it from here."},
    "[DONE]",
]


def test_refusals_and_text_after_a_tool_draw_the_same_in_both_streams(sandbox):
    out = _both(sandbox, REFUSALS)
    live, resumed = out["live"], out["resumed"]
    assert len(live) == len(resumed) == len(REFUSALS) - 1
    for i, (a, b) in enumerate(zip(live, resumed)):
        event = REFUSALS[i].get("type", "delta")
        assert b == a, f"after event {i} ({event}) the resumed view differs from the live one"
    # And what that is. A refusal as the step's first act ends its wait: no
    # spinner is left, and the step, having written nothing, is hidden.
    first = resumed[0]
    assert [next(iter(e)) for e in first] == ["bubble", "thread"], first
    assert first[0]["bubble"] == "hidden" and first[0]["spinner"] is None
    assert [c["state"] for c in first[1]["thread"]] == ["failed"]
    # The read joins the refusal's thread; the text after it gets a bubble of
    # its own below the thread; the refusal after that text goes below the text,
    # in a thread of its own.
    after_text = resumed[3]
    assert [next(iter(e)) for e in after_text] == ["bubble", "thread", "bubble"], after_text
    assert [c["state"] for c in after_text[1]["thread"]] == ["failed", "done"]
    assert after_text[2]["text"] == "Found it. Now I'll delete the old copy."
    final = resumed[-1]
    assert [next(iter(e)) for e in final] == ["bubble", "thread", "bubble", "thread", "bubble"], final
    assert final[3]["top"] and [c["state"] for c in final[3]["thread"]] == ["failed"]
    assert final[4]["text"] == "I can't delete it from here."
    # `B919`. At step 2 the thread directly above its bubble — the second one,
    # the refusal after the text — runs its line on down into it. Both streams
    # gave the connector to the turn's *first* thread, which already had one
    # (the text below it), and the second was left with `bottom: false`.
    at_step_2 = resumed[REFUSALS.index({"type": "agent_step", "round": 2})]
    assert [next(iter(e)) for e in at_step_2] == ["bubble", "thread", "bubble", "thread", "bubble"], at_step_2
    assert at_step_2[3]["bottom"], "the thread directly above step 2 does not run on into it"
    assert at_step_2[1]["bottom"], "the first thread lost the line down to the text below it"


# ── B915 × B917: the turn's notes and a takeover, through both streams ──────
# `P4-24` left the takeover banner and the skill notes out of the resumed view
# (nothing saved them, and `B904` was reworking their live arms), and drew
# neither the Continue offer nor the tool-budget note, because the reload the
# resumed stream ends in would take them away again. They are saved with the
# reply now (`B915`) and drawn by one builder (`renderAgentNote`); a resumed
# takeover closes the student's step and opens the teacher's as the live arm does.

def _cap(round_, calls, limit=2):
    return {"type": "agent_budget", "round": round_, "round_limit": limit,
            "round_limit_source": "configured", "tool_calls": calls, "tool_call_limit": 10}


TAKEOVER = RUN[:4] + [
    _budget(1, 0),
    {"delta": "Let me look."},
    {"type": "tool_start", "tool": "bash", "command": "ls /srv", "round": 1},
    {"type": "tool_output", "tool": "bash", "command": "ls /srv", "round": 1, "exit_code": 2,
     "output": "ls: cannot access '/srv': No such file or directory"},
    {"type": "skill_saved", "name": "list-dirs", "category": "files", "status": "draft"},
    {"type": "agent_step", "round": 2},
    _budget(2, 1),
    {"delta": "I can't find it."},
    # A pause: the Thinking spinner comes up under the student's answer, and
    # the takeover has to take it down, as it closes the student's step.
    "flush",
    {"type": "teacher_takeover", "teacher_model": "big-model@lab", "model": "big-model",
     "student_failure": "agent reply matched give-up pattern <can't find>"},
    dict(_budget(1, 0), teacher=True),
    {"delta": "Checking the mounts.", "teacher": True},
    {"type": "tool_start", "tool": "bash", "command": "mount", "round": 1, "teacher": True},
    {"type": "tool_output", "tool": "bash", "command": "mount", "round": 1, "exit_code": 0,
     "output": "/dev/sdb1 on /data", "teacher": True},
    {"type": "agent_step", "round": 2, "teacher": True},
    dict(_budget(2, 1), teacher=True),
    {"delta": "It is under /data.", "teacher": True},
    {"type": "skill_save_failed", "reason": "teacher said NO_SKILL (problem not reproducible)"},
    "[DONE]",
]

STEP_LIMIT = RUN[:4] + [
    _cap(1, 0),
    {"delta": "Working through the list."},
    {"type": "tool_start", "tool": "bash", "command": "ls a", "round": 1},
    _cap(1, 1),
    {"type": "tool_output", "tool": "bash", "command": "ls a", "round": 1, "exit_code": 0, "output": "a1"},
    "flush",
    {"type": "agent_step", "round": 2},
    _cap(2, 1),
    {"type": "tool_start", "tool": "bash", "command": "ls b", "round": 2},
    _cap(2, 2),
    {"type": "tool_output", "tool": "bash", "command": "ls b", "round": 2, "exit_code": 0, "output": "b1"},
    {"type": "rounds_exhausted", "rounds": 2},
    "[DONE]",
]

BUDGET = RUN[:4] + [
    _budget(1, 0),
    {"type": "tool_start", "tool": "bash", "command": "ls", "round": 1},
    _budget(1, 1),
    {"type": "tool_output", "tool": "bash", "command": "ls", "round": 1, "exit_code": 0, "output": "ok"},
    {"type": "budget_exceeded", "limit": 1, "used": 1},
    "[DONE]",
]


def _same_after_every_event(out, events):
    live, resumed = out["live"], out["resumed"]
    steps = len([e for e in events if e != "[DONE]"])
    assert len(live) == steps and len(resumed) == steps
    for i, (a, b) in enumerate(zip(live, resumed)):
        event = events[i] if events[i] == "flush" else events[i].get("type", "delta")
        assert b == a, f"after event {i} ({event}) the resumed view differs from the live one"


def _kinds(snap):
    return [e.get("kind") or next(iter(e)) for e in snap]


def test_a_takeover_draws_the_same_in_both_streams(sandbox):
    out = _both(sandbox, TAKEOVER)
    _same_after_every_event(out, TAKEOVER)
    at = {i: snap for i, snap in enumerate(out["resumed"])}
    index = {e.get("type"): i for i, e in enumerate(TAKEOVER) if isinstance(e, dict) and "type" in e}
    takeover = index["teacher_takeover"]
    # The student's skill note follows the thread it came from.
    skill = at[index["skill_saved"]]
    assert _kinds(skill) == ["bubble", "thread", "skill-saved-note"], skill
    assert skill[-1]["note"] == "Skill learned: list-dirs [files]"
    # The takeover: the student's answer stays, finished; the banner follows it,
    # as text; the teacher's own bubble opens below with a spinner.
    banner_at = at[takeover]
    assert _kinds(banner_at) == ["bubble", "thread", "skill-saved-note", "bubble",
                                 "teacher-takeover-banner", "bubble"], banner_at
    assert banner_at[3]["text"] == "I can't find it." and banner_at[3]["spinner"] is None
    assert banner_at[4]["note"] == ("Teacher takeover: escalating to big-model@lab — "
                                    "agent reply matched give-up pattern <can't find>")
    assert banner_at[5] == {"bubble": "shown", "text": "", "spinner": "Generating response", "meter": None}
    # The teacher's work: its text in its own bubble, its card in a thread of
    # its own below the banner, and at its next step the line of the thread
    # directly above runs on down (`B919`) — not the student's, above the banner.
    final = out["resumed"][-1]
    assert _kinds(final) == ["bubble", "thread", "skill-saved-note", "bubble", "teacher-takeover-banner",
                             "bubble", "thread", "bubble", "escalation-failed-note"], final
    assert final[5]["text"] == "Checking the mounts." and final[7]["text"] == "It is under /data."
    assert [c["tool"] for c in final[6]["thread"]] == ["Terminal"]
    assert final[6]["bottom"] and not final[1]["bottom"], final
    assert final[-1]["note"] == "Skill not saved: teacher said NO_SKILL (problem not reproducible)"


def test_a_teachers_bubbles_are_headed_with_the_teachers_model(sandbox):
    """`B922`. A step's bubble copies the route of the bubble above it, so the
    teacher's first bubble — and every teacher step after it — was headed with
    the student's model, right under a banner naming the teacher. The takeover
    heads it with the model the teacher's run requests (`model`), in both
    streams, and the teacher's next step inherits that."""
    out = _page(sandbox, """
        const events = %s;
        const heads = () => history.children
          .filter((n) => n.classList.contains('msg') && !n.classList.contains('agent-thinking-dots'))
          .map((n) => n.querySelector('.role').textContent.trim());
        runLive(events, []);
        const live = heads();
        clear();
        let resumed = null;
        await runResumed(events, [], { onEvent(i) { if (i === events.length - 2) resumed = heads(); } });
        console.log(JSON.stringify({ live, resumed }));
    """ % json.dumps(TAKEOVER))
    # The first bubble is headed with its time as well in a resumed view, so
    # the heads compared are the student's second step and the teacher's two.
    assert out["live"][1:] == ["test-model", "big-model", "big-model"], out["live"]
    assert out["resumed"][1:] == out["live"][1:], out


def test_a_step_limit_offers_continue_in_both_streams(sandbox):
    out = _both(sandbox, STEP_LIMIT)
    _same_after_every_event(out, STEP_LIMIT)
    final = out["resumed"][-1]
    assert final[-1] == {"note": "Reached the 2-step limit — not finished.", "continue": True}, final
    assert not any("waiting" in e for e in final), "a Thinking spinner is left waiting for a step past the limit"


def test_a_tool_budget_note_draws_in_both_streams(sandbox):
    out = _both(sandbox, BUDGET)
    _same_after_every_event(out, BUDGET)
    final = out["resumed"][-1]
    assert final[-1] == {"note": "Tool budget reached (1/1 calls). Agent stopped.",
                         "kind": "budget-exceeded-note"}, final


def test_a_resumed_takeover_leaves_nothing_of_its_own_for_the_reload(sandbox):
    """The notes are saved with the reply now, and the reload draws them from
    there; the view that drew them first is gone by then, so none is doubled."""
    out = _both(sandbox, TAKEOVER)
    assert len(out["reloads"]) == 1 and out["reloads"][0]["view"] == []


def test_a_new_step_continues_the_thread_directly_above_it_and_no_other(sandbox):
    """`B919`, the rule both `agent_step` arms now call (`_threadIntoNextStep`),
    over the shapes a turn's bottom can have when a step begins. The connector
    goes to the thread directly above the new step, past bubbles hidden for
    writing nothing and the wait spinner — and to nothing when something else
    that is visible sits between, or when the thread is an earlier turn's."""
    out = _page(sandbox, """
        const el = (cls, { hidden = false, text = '' } = {}) => {
          const n = document.createElement('div');
          n.className = cls;
          if (hidden) n.style.display = 'none';
          if (text) n.textContent = text;
          return history.appendChild(n);
        };
        const cases = {};
        const run = (name, build) => {
          clear();
          const made = build();
          const got = _threadIntoNextStep(history);
          cases[name] = { marked: made.indexOf(got),
                          bottoms: made.map((n) => n.classList.contains('has-bottom')) };
        };
        run('two threads', () => [el('agent-thread streaming'), el('msg msg-ai', { text: 'Found it.' }),
                                  el('agent-thread streaming')]);
        run('past a hidden step and the wait spinner', () => [el('agent-thread streaming'),
          el('msg msg-ai msg-continuation', { hidden: true }), el('msg msg-ai agent-thinking-dots')]);
        run('text below the thread', () => [el('agent-thread streaming'),
          el('msg msg-ai msg-continuation', { text: 'Here it is.' })]);
        run('a stop line below the thread', () => [el('agent-thread streaming'), el('agent-stop')]);
        run('a banner below the thread', () => [el('agent-thread streaming'),
          el('teacher-takeover-banner'), el('msg msg-ai msg-continuation', { hidden: true })]);
        run("an earlier turn's thread", () => [el('agent-thread'), el('msg msg-ai', { hidden: true })]);
        console.log(JSON.stringify(cases));
    """)
    assert out["two threads"] == {"marked": 2, "bottoms": [False, False, True]}, out
    assert out["past a hidden step and the wait spinner"]["marked"] == 0, out
    for shape in ("text below the thread", "a stop line below the thread",
                  "a banner below the thread", "an earlier turn's thread"):
        assert out[shape]["marked"] == -1 and not any(out[shape]["bottoms"]), (shape, out[shape])


def test_the_replay_ends_in_the_reload_with_nothing_of_its_own_left(sandbox):
    """A rich reply is re-drawn from the saved record. The stop line is saved
    with it (`metadata.agent_stops`) and the reload draws it again — so the
    resumed view has taken its own copy away by then, and a stop line is never
    on the page twice. Nothing it drew is left behind for the reload to sit
    under."""
    out = _both(sandbox)
    assert len(out["reloads"]) == 1
    assert out["reloads"][0]["stops"] == 0
    assert out["reloads"][0]["view"] == []
    assert out["added"] == []


def test_a_replay_over_the_view_a_dropped_connection_left_replaces_it(sandbox):
    """The live stream drew half the run and lost its connection;
    `_tryAutoRecover` picks the run up again and the replay starts from the
    run's first event. The page then shows the run once, not the first half
    twice."""
    out = _page(sandbox, """
        const events = %s;
        const full = [];
        runLive(events, full);
        const whole = full[full.length - 1];
        clear();
        runLive(events, [], { stopAfter: 12 });          // the view the dead stream left
        const resumed = [];
        await runResumed(events, resumed);
        console.log(JSON.stringify({ whole, replayed: resumed[resumed.length - 1] }));
    """ % json.dumps(RUN))
    assert out["replayed"] == out["whole"]
    assert sum(1 for e in out["replayed"] if "stop" in e) == 1


def test_a_replay_that_loses_its_connection_takes_its_view_with_it(sandbox):
    """A resumed stream cut off mid-run falls back to the reload. Its cards
    must not be left on the page — and their clocks must stop — or the reload
    of a still-running run would sit under a frozen half-copy."""
    out = _page(sandbox, """
        const events = %s;
        const resumed = [];
        let started = null;
        await runResumed(events, resumed, { failAt: 9, onEvent(i) {
          if (i === 6) started = history.querySelector('.agent-thread-node');
        } });
        const running = history.querySelectorAll('.agent-thread-node').length;
        const ticking = !!(started && (started._elapsedTicker || started._waveInterval));
        console.log(JSON.stringify({ reloads, running, ticking, had: !!started, left: describe(history) }));
    """ % json.dumps(RUN))
    assert len(out["reloads"]) == 1
    assert out["reloads"][0]["view"] == []
    assert out["left"] == [] and out["running"] == 0
    assert out["had"] and not out["ticking"], "the dropped replay's running card kept ticking"


def test_a_replay_that_ends_on_an_error_leaves_no_card_running(sandbox):
    """A failure the server did not record stays on screen — it is the only
    evidence. A card that was running when it came never gets its result, so
    it stops its clock and stops saying it is running, as the live stream's
    catch path leaves one."""
    events = RUN[:7] + [{"sseError": {"status": 502, "error": "upstream went away"}}]
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        const node = history.querySelector('.agent-thread-node');
        console.log(JSON.stringify({ reloads, left: describe(history),
          ticking: !!(node._elapsedTicker || node._waveInterval),
          running: node.classList.contains('running') }));
    """ % json.dumps(events))
    assert out["reloads"] == []
    assert out["left"][0]["text"] == "Let me look at the logs.[Error: upstream went away]"
    assert out["left"][1]["thread"][0]["tool"] == "Running"
    assert not out["ticking"], "the orphaned card's clock is still going"
    assert not out["running"], "the orphaned card still says it is running"


def test_a_document_being_written_shows_the_writing_card(sandbox):
    """The live stream shows a document the model is writing as a *Writing*
    card in the thread, with the reply bubble hidden until there is text
    outside the fence. A resumed stream printed "Done." from the fence's first
    line — it asked for the finished form of text that was still arriving."""
    events = [{"delta": "```create_document\n# Notes\n"}, {"delta": "The first line."}, "[DONE]"]
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ resumed }));
    """ % json.dumps(events))
    writing = out["resumed"][1]
    assert writing[0]["thread"] == [{"tool": "Writing", "state": "running", "round": "", "tail": ""}]
    assert writing[1]["bubble"] == "hidden"
    assert not any(e.get("text") == "Done." for e in writing)


def test_leaving_the_chat_mid_replay_draws_nothing_into_the_next_one(sandbox):
    """The replay draws into the history, so it has to stop the moment the
    person moves on. A read already under way used to deliver its events into
    whatever chat was on screen by then."""
    out = _page(sandbox, """
        const events = %s;
        const resumed = [];
        let seen = null;
        await runResumed(events, resumed, { onEvent(i) {
          if (i === 5) {                       // after the sentence: the person leaves
            sessionModule.current = 's2';
            clear();                          // the next chat's history
          }
          if (i === 6) seen = describe(history);
        } });
        console.log(JSON.stringify({ after: describe(history), reloads, seen }));
    """ % json.dumps(RUN))
    assert out["after"] == []
    assert out["seen"] is None, "an event after leaving was drawn"
    assert out["reloads"] == []


def test_reasoning_reaches_the_renderer_as_a_thinking_block(sandbox):
    """Reasoning tokens arrive flagged `thinking`. The live stream wraps each run
    of them in <think>…</think>; a resumed stream printed them as the reply,
    and a plain reply kept them in the bubble it finalized."""
    events = [
        {"delta": "The user wants", "thinking": True},
        {"delta": " a greeting.", "thinking": True},
        {"delta": "Hello!"},
        "[DONE]",
    ]
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ rendered, added, reloads }));
    """ % json.dumps(events))
    assert out["rendered"][0] == "<think>The user wants</think>"
    assert out["rendered"][-1] == "<think>The user wants a greeting.</think>Hello!"
    assert out["added"] == [{"role": "assistant", "text": "<think>The user wants a greeting.</think>Hello!",
                             "model": "test-model"}]
    assert out["reloads"] == []


def test_a_plain_reply_is_still_finalized_in_place(sandbox):
    """The meter's frames arrive on every agent turn. A turn that only answers
    is still finalized where it stands, with no reload: prep and budget frames
    are not what makes a reply "rich"."""
    events = RUN[:5] + [{"delta": "Just an answer."}, "[DONE]"]
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ added, reloads, left: describe(history) }));
    """ % json.dumps(events))
    assert out["added"] == [{"role": "assistant", "text": "Just an answer.", "model": "test-model"}]
    assert out["reloads"] == [] and out["left"] == []


def test_a_stop_line_alone_sends_the_reply_to_the_reload(sandbox):
    """The stop is saved with the reply and drawn from there by the reload, so
    a reply with one must be reloaded even when nothing else about it is rich
    — finalized in place, it would lose the line the moment it ended."""
    promise = {"type": "intent_nudge_exhausted", "round": 1, "kind": "unkept_promise",
               "message": "Stopped: said “Let me check” 3 times without making a call."}
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ drawn: resumed[resumed.length - 1], added, reloads }));
    """ % json.dumps([{"delta": "Let me check"}, promise, "[DONE]"]))
    assert {"stop": promise["message"]} in out["drawn"]
    assert out["added"] == [] and len(out["reloads"]) == 1


def test_a_compaction_sends_the_reply_to_the_reload(sandbox):
    """`B921`. An agent turn's compaction is saved with the reply as one of its
    notes, and the reload draws it as a line; a plain reply finalized in place
    would not have it. The view draws nothing of it itself — live it is a
    toast, which a replay from the first event would raise again."""
    compacted = {"type": "compacted", "context_length": 8192,
                 "data": {"context_length": 8192, "messages_before": 12, "messages_after": 6,
                          "tokens_before": 7000, "tokens_after": 2100}}
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ added, reloads, left: describe(history) }));
    """ % json.dumps(RUN[:5] + [compacted, {"delta": "Just an answer."}, "[DONE]"]))
    assert out["added"] == [] and len(out["reloads"]) == 1
    assert out["left"] == []


def test_a_stop_at_a_limit_is_on_the_meter_and_sends_the_reply_to_the_reload(sandbox):
    events = RUN[:5] + [{"type": "rounds_exhausted", "rounds": 20}, "[DONE]"]
    out = _page(sandbox, """
        const resumed = [];
        await runResumed(%s, resumed);
        console.log(JSON.stringify({ resumed, reloads }));
    """ % json.dumps(events))
    assert out["resumed"][-1][0]["meter"].endswith("Stopped at the 20-step limit")
    # `B917`: and the offer beside it, drawn as live, since the reload keeps it.
    assert out["resumed"][-1][-1] == {"note": "Reached the 20-step limit — not finished.", "continue": True}
    assert len(out["reloads"]) == 1


# ── P4-24: the same tab ─────────────────────────────────────────────────────

def test_a_chat_reopened_in_the_same_tab_is_drawn_by_the_replay(sandbox):
    """`checkBackgroundStream` hands a running background stream to the replay,
    marks the tab's own reader as no longer drawing, and keeps the old spinner
    only for what the replay cannot do."""
    out = _page(sandbox, """
        const results = {};
        // A run this tab went on reading while another chat was open.
        const ctrl = { name: 'post' };
        _activeStreams.set('s1', { abortCtrl: ctrl });
        _backgroundStreams.set('s1', { status: 'running', abortCtrl: ctrl });
        const resumed = [];
        const events = %s;
        const done = runResumed(events, resumed, { opts: { besideBackgroundReader: true } });
        await done;
        results.replayed = resumed.length;
        // `checkBackgroundStream` itself, over a fresh entry.
        clear();
        _backgroundStreams.set('s1', { status: 'running', abortCtrl: ctrl });
        let asked = null;
        globalThis.fetch = async (url) => { asked = url; return { ok: false, body: null, headers: { get: () => '' } }; };
        checkBackgroundStream('s1');
        await new Promise((r) => setImmediate(r));
        await new Promise((r) => setImmediate(r));
        results.asked = asked;
        results.marked = _backgroundStreams.get('s1').resumedView === true;
        results.fallback = describe(history).map((e) => e.spinner || null);
        // Research keeps its own progress view: the spinner, and no replay.
        clear();
        asked = null;
        _researchingStreamIds.add('s1');
        checkBackgroundStream('s1');
        await new Promise((r) => setImmediate(r));
        results.researchAsked = asked;
        results.research = describe(history).map((e) => e.spinner || null);
        console.log(JSON.stringify(results));
    """ % json.dumps(RUN))
    assert out["replayed"] > 20, "the replay did not attach beside the tab's own reader"
    assert out["asked"] == "/api/chat/resume/s1"
    assert out["marked"]
    assert out["fallback"] == ["Response streaming in background"]
    assert out["researchAsked"] is None
    assert out["research"] == ["Response streaming in background"]


def test_the_tabs_own_reader_stops_drawing_once_the_replay_has_the_chat():
    """The live handler decides per line whether it is in the background. It
    is, once a replay has taken its chat over — for that send only."""
    code = blank_text(_chat(), "js")
    start = code.index("const _bgView = _backgroundStreams.get(streamSessionId);")
    decl = code[start:code.index(";", code.index("const _isBg =", start)) + 1]
    script = textwrap.dedent("""
        const results = [];
        const mine = {}, other = {};
        for (const [current, entry, abortCtrl] of [
          ['s1', null, mine],
          ['s2', null, mine],
          ['s1', { resumedView: true, abortCtrl: mine }, mine],
          ['s1', { resumedView: true, abortCtrl: other }, mine],
          ['s1', { resumedView: false, abortCtrl: mine }, mine],
        ]) {
          const streamSessionId = 's1';
          const sessionModule = { getCurrentSessionId: () => current };
          const _backgroundStreams = new Map(entry ? [['s1', entry]] : []);
          %s
          results.push(_isBg);
        }
        console.log(JSON.stringify(results));
    """) % decl
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [False, True, True, False, False]


def test_leaving_again_keeps_the_replay_in_charge(sandbox):
    """Re-selecting the chat detaches its stream again (the resumed view's own
    reload does this). The hand-over must survive that, or the tab's reader
    would draw into the reloading page for the instant before
    `checkBackgroundStream` runs."""
    out = _page(sandbox, """
        const ctrl = {};
        _activeStreams.set('s1', { abortCtrl: ctrl, holder: null, query: 'q', cancelViewWork() {} });
        _backgroundStreams.set('s1', { status: 'running', abortCtrl: ctrl, resumedView: true });
        let currentAbort = null, currentHolder = null, currentAccumulated = '';
        const _terminalSavedStreams = new Set();
        function abortCurrentRequest() {}
        function _syncForegroundStreamGlobals() {}
        function updateSubmitButton() {}
        %s
        detachCurrentStream('s1');
        const kept = _backgroundStreams.get('s1').resumedView;
        _activeStreams.set('s1', { abortCtrl: {}, holder: null, query: 'q', cancelViewWork() {} });
        detachCurrentStream('s1');
        console.log(JSON.stringify({ kept, newSend: _backgroundStreams.get('s1').resumedView }));
    """ % _defn("detachCurrentStream", "export function ").replace("export function", "function", 1))
    assert out == {"kept": True, "newSend": False}
