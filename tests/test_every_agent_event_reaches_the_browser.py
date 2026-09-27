# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B904` — every event the agent loop sends reaches the browser while it runs.

`/api/chat_stream`'s agent branch walked each frame through an `if/elif` on its
`type` that had no `else`. A frame whose type it did not name was dropped
without a word. Measured on the tree this row started from, by pushing every
type the loop, `agent_stops` and the teacher build through the route with a
stubbed loop: thirty went in and eleven did not come out — `tool_progress`,
`tool_blocked`, `verifier`, `skills_injected`, `steer_applied`, `skill_saved`,
`generated_image`, `compacted`, `teacher_takeover`, `escalation_failed` and
`skill_save_failed`. Each of those has a handler in `chat.js`, and each had only
ever run against a reload.

So the route now forwards what it does not handle, and this file checks four
things, all by driving code (`Law 20`):

  * **the route.** Every type is derived from the source rather than copied
    into this file, so a type added to the loop tomorrow is pushed through the
    route by this test without anyone editing it. The ones the route handles
    keep their handling and their order — the delta that is saved, the
    `metrics` it normalises, the `model_actual` it rewrites, the save and
    `message_saved` before `[DONE]` and after `agent_terminal`;
  * **the handlers that ran for the first time.** A refusal card closes the step
    the way `tool_start` does and goes where a card goes; a teacher takeover
    leaves the stream in a state the next arm can use, where it used to leave
    `roundHolder` null and hide the student's answer;
  * **the numbers they carry.** `web_search`'s progress said `elapsed_s: 30` —
    its timeout — on every search, and `P4-02` re-anchors the card's clock on
    that key the moment it arrives.
"""

import ast
import asyncio
import json
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

import routes.chat_routes as chat_routes
from src.agent_tools.web_tools import WebSearchTool
from tests.helpers.esc_stub import esc_source  # B874
from tests.helpers.js_source import js_definition  # B876
from tests.helpers.source_text import blank  # B290
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"
AGENT_METER = ROOT / "static" / "js" / "agentMeter.js"
PROVENANCE = ROOT / "static" / "js" / "chatModelProvenance.js"

#: The modules whose events go out through the route's agent branch: the loop,
#: the two guard stops it yields, and the teacher, which relays a recursive
#: run of the loop and adds its own.
EMITTERS = ("src/agent_loop.py", "src/agent_stops.py", "src/teacher_escalation.py")

#: The row's list — its `Verify:` line. Held against the derived set below, so
#: the derivation cannot quietly lose one of the types the row is about.
DROPPED_BEFORE = (
    "tool_progress", "tool_blocked", "verifier", "skills_injected", "steer_applied",
    "skill_saved", "generated_image", "compacted", "teacher_takeover",
    "escalation_failed", "skill_save_failed",
)

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── what the loop sends, read from the loop ─────────────────────────────────


def emitted_types() -> list:
    """Every `"type": "<literal>"` in a dict the emitters build, sorted.

    One structural exclusion and no list: a dict that also carries a
    `"function"` key is an OpenAI tool-call record (`{"type": "function",
    "function": {...}}`) that `_append_tool_results` writes into the model's
    message history. It is not an event and is never sent to a browser.
    """
    found = set()
    for rel in EMITTERS:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if "function" in keys:
                continue
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    found.add(v.value)
    return sorted(found)


def test_the_derivation_sees_the_types_the_row_names_and_the_ones_the_route_handles():
    """A derivation that silently found nothing would make every test below
    pass. It must see the eleven the row is about, and the ones the route has
    always named."""
    types = set(emitted_types())
    assert set(DROPPED_BEFORE) <= types, sorted(set(DROPPED_BEFORE) - types)
    for handled in ("tool_start", "tool_output", "agent_step", "metrics",
                    "agent_terminal", "agent_prep", "agent_budget", "web_sources"):
        assert handled in types, handled
    assert "function" not in types


# ── the route ───────────────────────────────────────────────────────────────


def _frame(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


async def _through_route(monkeypatch, chunks, *, saved_id=None):
    """Push `chunks` out of a stubbed loop and through `/api/chat_stream`.
    Returns `(out, saved)`: every chunk the browser would read, as text, and the
    replies the route saved. `saved_id` makes the save return an id, so the
    route's `message_saved` frame appears."""
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks)
    saved = []

    def _save(*args, **kwargs):
        saved.append(args[3] if len(args) > 3 else None)
        return saved_id

    monkeypatch.setattr(chat_routes, "save_assistant_response", _save)
    response = await endpoint(_RouteRequest("agent"))
    out = []
    async for chunk in response.body_iterator:
        out.append(chunk if isinstance(chunk, str) else chunk.decode())
    return out, saved


def _frames_out(out):
    return [json.loads(c[6:]) for c in out if c.startswith("data: {")]


@pytest.mark.asyncio
async def test_every_type_the_loop_builds_comes_out_of_the_route_in_order(monkeypatch):
    """The row's `Verify:`. Every type, pushed through the route in one stream,
    comes out once, in the order it went in."""
    types = emitted_types()
    chunks = [_frame({"type": t, "round": 1, "probe": t}) for t in types]
    out, _ = await _through_route(monkeypatch, chunks + ["data: [DONE]\n\n"])
    # By type, not by the probe key: `metrics` comes out rebuilt from its
    # `data` (the route normalises it), which is handling, not dropping.
    arrived = [f.get("type") for f in _frames_out(out) if f.get("type") in set(types)]
    assert arrived == types, (
        "went in and did not come out: "
        f"{sorted(set(types) - set(arrived))}; order: {arrived}")


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", DROPPED_BEFORE)
async def test_each_type_the_route_dropped_now_arrives_as_it_was_sent(monkeypatch, event_type):
    """Forwarded, not re-encoded: the browser reads the loop's own bytes. The
    frame is written compactly and with a non-ASCII character, so a route that
    decoded and re-encoded it would hand on different bytes."""
    sent = "data: " + json.dumps({"type": event_type, "round": 2, "detail": "fin — done"},
                                 separators=(",", ":"), ensure_ascii=False) + "\n\n"
    out, _ = await _through_route(monkeypatch, [sent, "data: [DONE]\n\n"])
    assert sent in out, f"{event_type} went into the route and did not come out as sent"


@pytest.mark.asyncio
async def test_a_type_nobody_has_written_yet_is_not_dropped_either(monkeypatch):
    """`Law 13`. The route cannot drop the next new type the same way."""
    sent = _frame({"type": "added_to_the_loop_tomorrow", "n": 1})
    out, _ = await _through_route(monkeypatch, [sent, "data: [DONE]\n\n"])
    assert sent in out


@pytest.mark.asyncio
async def test_what_the_route_handles_keeps_its_handling_and_its_order(monkeypatch):
    """The fix is an `else`, and it must not turn a handled frame into a
    forwarded one. The deltas are what is saved, and nothing forwarded around
    them joins the saved reply; `metrics` and `model_actual` still come out
    rewritten; the save's `message_saved` still comes before `[DONE]`."""
    chunks = [
        _frame({"delta": "Hello "}),
        _frame({"type": "tool_progress", "tool": "bash", "tail": "not part of the reply"}),
        _frame({"type": "model_actual", "model": "answered-model", "round": 1}),
        _frame({"delta": "world"}),
        _frame({"type": "verifier", "round": 1, "outcome": "pass", "issues": []}),
        _frame({"type": "metrics", "data": {"total_time": 1}}),
        "data: [DONE]\n\n",
    ]
    out, saved = await _through_route(monkeypatch, chunks, saved_id="msg-1")
    assert saved == ["Hello world"], saved
    frames = _frames_out(out)
    order = [f.get("type") or ("delta" if "delta" in f else "?") for f in frames]
    tail = order[order.index("delta"):]
    assert tail == ["delta", "tool_progress", "model_actual", "delta", "verifier",
                    "metrics", "message_saved"], tail
    assert out[-1] == "data: [DONE]\n\n"
    actual = next(f for f in frames if f.get("type") == "model_actual")
    assert actual["requested_model"] == "selected-model", "model_actual is no longer rewritten"
    metrics = next(f for f in frames if f.get("type") == "metrics")["data"]
    assert metrics["requested_model"] == "selected-model", "metrics is no longer normalised"


@pytest.mark.asyncio
async def test_a_terminal_failure_is_still_saved_before_it_is_forwarded(monkeypatch):
    """`agent_terminal` saves the partial reply and says so before the frame
    goes out; a forwarded frame after it is still forwarded."""
    chunks = [
        _frame({"delta": "partial"}),
        _frame({"type": "agent_terminal", "data": {"failure": {"status": 502}}}),
        _frame({"type": "escalation_failed", "reason": "teacher endpoint not resolvable"}),
    ]
    out, saved = await _through_route(monkeypatch, chunks, saved_id="msg-2")
    order = [f.get("type") for f in _frames_out(out) if f.get("type")]
    at = order.index("agent_terminal")
    assert order[at - 1] == "message_saved", order
    assert order[at + 1] == "escalation_failed", order
    assert saved and saved[0].startswith("partial"), saved


# ── the numbers the newly-arriving frames carry ────────────────────────────


def test_web_searchs_progress_reports_the_time_the_search_took(monkeypatch):
    """`elapsed_s: 30` was the timeout, sent as a measurement on every search.
    Nothing noticed while the route dropped `tool_progress`; once it arrives,
    `P4-02` sets the card's clock from it, and a quick search reads as thirty
    seconds. A search made to take a quarter of a second reports about that."""
    import src.search as search

    def slow_search(query, **kwargs):
        time.sleep(0.25)
        return "results", []

    monkeypatch.setattr(search, "comprehensive_web_search", slow_search, raising=False)
    events = []

    async def progress(evt):
        events.append(evt)

    result = asyncio.run(WebSearchTool().execute("pantheon", {"progress_cb": progress}))
    assert result["exit_code"] == 0
    assert [e["elapsed_s"] for e in events][:1] == [0]
    done = events[-1]["elapsed_s"]
    assert 0.2 <= done < 10, f"a 0.25s search reported {done}s"


# ── the handlers that ran for the first time ────────────────────────────────


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
// Two properties a browser has and the suite's small DOM does not; the arms
// below read both.
Object.defineProperty(Node.prototype, 'lastElementChild', {
  get() { const c = this.children; return c.length ? c[c.length - 1] : null; },
});
Object.defineProperty(Node.prototype, 'isConnected', {
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; },
});
export const box = document.body.appendChild(new Node('div'));
box.setAttribute('id', 'chat-history');

/** A reply bubble the way the stream builds one, with `text` in it. */
export function bubble(text, extra = '') {
  const b = box.appendChild(new Node('div'));
  b.className = ('msg msg-ai ' + extra).trim();
  const role = b.appendChild(new Node('div'));
  role.className = 'role';
  const body = b.appendChild(new Node('div'));
  body.className = 'body';
  if (text) {
    const content = body.appendChild(new Node('div'));
    content.className = 'stream-content';
    content.textContent = text;
  }
  return b;
}

/** A thread with one card in it. */
export function thread(label) {
  const t = box.appendChild(new Node('div'));
  t.className = 'agent-thread';
  const card = t.appendChild(new Node('div'));
  card.className = 'agent-thread-node';
  card.dataset.label = label;
  return t;
}

/** The history as a person reads it, top to bottom. */
export function history() {
  return box.children.map((n) => ({
    cls: n.className,
    hidden: n.style.display === 'none',
    text: n.classList.contains('agent-thread') ? '' : n.textContent.trim(),
    cards: n.classList.contains('agent-thread')
      ? n.children.map((c) => c.dataset.label) : undefined,
    spinner: !!n.querySelector('.ai-spinner'),
    finished: n._walk([]).some((c) => String(c._html || '').includes('final-render')),
  }));
}
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = _make_sandbox(tmp_path_factory.mktemp("everyevent"), AGENT_METER, _SHIM, {})
    shutil.copy(PROVENANCE, d / PROVENANCE.name)
    return d


def _live_handler() -> str:
    """Comment-blanked `handleChatSubmit`, the function the live stream runs
    in. Its arms are cut from here rather than from the whole file: a resumed
    stream (`resumeStream`, `P4-24`) has arms of its own that open the same way."""
    code = blank(CHAT_JS)
    start = code.index("export async function handleChatSubmit(")
    return code[start:start + len(js_definition(CHAT_JS.read_text(encoding="utf-8"), start))]


def _arm(opening: str, closing: str) -> str:
    """One arm of the live dispatcher, cut out by its own delimiters in
    comment-blanked text, so a delimiter quoted in prose cannot be taken for
    code. Returns the body between the braces."""
    code = _live_handler()
    assert code.count(opening) == 1, f"{opening!r} is no longer a unique anchor"
    start = code.index(opening) + len(opening)
    return code[start:code.index(closing, start)]


def _definition(anchor: str) -> str:
    """One declaration out of chat.js through the suite's one scanner (`B876`),
    or '' when this tree does not have it — so the same test runs against the
    tree before this row and fails on what it asserts, not on a missing name."""
    code = blank(CHAT_JS)
    if code.count(anchor) != 1:
        return ""
    return js_definition(CHAT_JS.read_text(encoding="utf-8"), code.index(anchor))


_STUBS = r"""
const calls = [];
// The round's final render marks what it wrote, so a test can tell a step
// that was finished from one left as it streamed.
const markdownModule = {
  normalizeThinkingMarkup: (s) => s, squashOutsideCode: (s) => s,
  processWithThinking: (s) => '<div class="final-render">' + s + '</div>',
};
const _streamDisplayText = (t) => String(t || '');
const window = { hljs: null };
// `B874`: the shipped `esc` (declared above this block by `esc_source`).
const uiModule = { scrollHistory() {}, esc };
const sessionModule = { getSessions: () => [] };
const streamSessionId = 's1';
const modelName = 'student-model';
const _modelRouteLabel = (requested, actual) => actual || requested || '';
const _applyModelColor = () => {};
const _cancelThinkingGrace = () => {};
const _thinkingAnalysisGate = { reset() {} };
const _roundDisplayProjector = { reset() {} };
const _replyDisplayProjector = { reset() {} };
const _closeOpenThinkingMarkup = () => {};
const _cancelThinkingTimer = () => calls.push('cancelThinkingTimer');
const _removeThinkingSpinner = () => calls.push('removeThinkingSpinner');
const _endLiveThinkingSection = () => calls.push('endLiveThinking');
const _cancelLiveThinkingWork = () => {};
const applyAgentThreadNode = (node, opts) => {
  node.className = 'agent-thread-node';
  node.dataset.label = opts.label;
};
const blockedCardOptions = (j) => ({ label: 'refused ' + j.tool });
const planWindow = { noteToolStart() {} };
const setInterval = () => 0;
let _lastToolName = '';
let _docFenceOpened = false;
let _thinkingMode = null;
let isThinking = false;
let roundText = '';
let roundReplyText = null;
let roundFinalized = false;
let roundFinalization = null;
let lastContentRoundHolder = null;
let currentToolBubble = null;
let lastToolThread = null;
let spinner = null;
let _finalizeRoundRender = () => {};
/** The reply spinner the stream shows while it waits, inside `bubbleNode`. */
function waitSpinner(bubbleNode) {
  const el = new Node('span');
  el.className = 'ai-spinner';
  bubbleNode.querySelector('.body').appendChild(el);
  return { element: el, destroy() { calls.push('spinner.destroy'); el.remove(); this.element = null; } };
}
"""


def _script(body: str) -> str:
    """The stubs, every declaration the arms reach for, the arms themselves as
    functions, then `body`."""
    parts = [
        "import { document, Node, box, bubble, thread, history } from './shim.js';",
        "import { inheritModelRouteState } from './chatModelProvenance.js';",
        esc_source(),
        _STUBS,
        "let holder = null; let roundHolder = null;",
        _definition("function _ensureStreamLayout("),
        # The `let … = () => {};` placeholder above the stream shares this
        # prefix; the newline after the brace is what only the real one has.
        _definition("_finalizeRoundRender = () => {\n"),
        _definition("function _ensureVisibleRoundForDelta("),
        _definition("function _openRoundBubble("),
        _definition("function _cardThread("),
        # `P4-24`: what those closures and the arms below draw through, at
        # module scope so a resumed stream draws the same way.
        _definition("function _newRoundBubble("),
        _definition("function _threadForNextCard("),
        _definition("function _startToolCard("),
        "function toolBlocked(json, _isBg = false) { for (const _ of [0]) {"
        + _arm("} else if (json.type === 'tool_blocked') {",
               "} else if (json.type === 'auto_escalated') {") + "} }",
        "function toolStart(json, _isBg = false) { for (const _ of [0]) {"
        + _arm("} else if (json.type === 'tool_start') {",
               "} else if (json.type === 'tool_progress') {") + "} }",
        "function takeover(json, _isBg = false) { for (const _ of [0]) {"
        + _arm("} else if (json.type === 'teacher_takeover') {",
               "} else if (json.type === 'skill_saved') {") + "} }",
        "const spinnerModule = { create: (label) => ({ label, element: null,"
        " createElement() { this.element = new Node('span'); this.element.className = 'ai-spinner';"
        " return this.element; }, start() {}, destroy() { if (this.element) this.element.remove();"
        " this.element = null; } }) };",
        textwrap.dedent(body),
    ]
    return "\n".join(parts)


def _node(sandbox: Path, body: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(_script(body), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


@node_only
def test_a_refusal_ends_the_wait_the_way_a_tool_call_does(sandbox):
    """The model's first act is a call the policy refuses. The reply's spinner
    kept saying "Waiting for the model" above the refusal card, with a second
    spinner below it — a refused call is still the model's action."""
    out = _node(sandbox, """
        holder = bubble('');
        roundHolder = holder;
        spinner = waitSpinner(holder);
        toolBlocked({ type: 'tool_blocked', tool: 'write_file', round: 1 });
        console.log(JSON.stringify({ calls, history: history(), open: currentToolBubble }));
    """)
    assert "spinner.destroy" in out["calls"], "the reply's spinner outlived the refusal"
    assert "cancelThinkingTimer" in out["calls"] and "removeThinkingSpinner" in out["calls"]
    assert not any(n["spinner"] for n in out["history"]), out["history"]
    assert out["history"][-1]["cards"] == ["refused write_file"], out["history"]
    assert out["history"][0]["hidden"], "an empty step was left on screen, as tool_start would not"
    assert out["open"] is None


@node_only
def test_a_refusal_in_a_later_step_is_drawn_below_that_steps_text(sandbox):
    """It reached for `lastToolThread` whatever had been drawn since, so a call
    refused in step 2 landed in step 1's thread — above step 2's own words."""
    out = _node(sandbox, """
        holder = bubble('');
        holder.style.display = 'none';
        lastToolThread = thread('bash');
        roundHolder = bubble("Found it. Now I'll delete the old copy.", 'msg-continuation');
        roundText = "Found it. Now I'll delete the old copy.";
        toolBlocked({ type: 'tool_blocked', tool: 'bash', round: 2 });
        console.log(JSON.stringify({ history: history() }));
    """)
    h = out["history"]
    assert h[1]["cards"] == ["bash"], f"the refusal joined step 1's thread: {h}"
    assert h[2]["text"].startswith("Found it"), h
    assert h[3]["cards"] == ["refused bash"], h


@node_only
def test_a_refusal_in_the_same_step_joins_that_steps_thread(sandbox):
    """And it is not split off needlessly: straight after a card, with nothing
    drawn between, it is part of the same thread."""
    out = _node(sandbox, """
        holder = bubble('Checking.');
        roundHolder = holder;
        roundText = 'Checking.';
        roundFinalized = true;
        lastToolThread = thread('read_file');
        toolBlocked({ type: 'tool_blocked', tool: 'write_file', round: 1 });
        console.log(JSON.stringify({ history: history() }));
    """)
    assert out["history"][-1]["cards"] == ["read_file", "refused write_file"], out["history"]


_STUDENT_THEN_TAKEOVER = """
    holder = bubble("I don't have a tool for that.");
    roundHolder = holder;
    roundText = "I don't have a tool for that.";
    takeover({ type: 'teacher_takeover', teacher_model: 'big-model',
               student_failure: 'said it had no tool' });
"""


@node_only
def test_a_takeover_keeps_the_students_answer_and_opens_the_teachers_own_bubble(sandbox):
    """It set `roundHolder = null`. The teacher's first token then threw in
    `_renderStream` (it reads `roundHolder.querySelector`), and nothing below
    the banner was ready for the teacher's run."""
    out = _node(sandbox, _STUDENT_THEN_TAKEOVER + """
        console.log(JSON.stringify({ history: history(),
          teacherBubble: !!roundHolder && roundHolder !== holder && roundHolder.isConnected,
          last: roundHolder === box.lastElementChild,
          spinnerIn: !!(spinner && spinner.element && roundHolder
                        && roundHolder.querySelector('.ai-spinner') === spinner.element) }));
    """)
    h = out["history"]
    assert h[0]["text"] == "I don't have a tool for that." and not h[0]["hidden"], h
    assert h[0]["finished"], f"the student's last step was left as it streamed: {h}"
    assert "teacher-takeover-banner" in h[1]["cls"], h
    assert out["teacherBubble"] and out["last"], (
        "the teacher's run has no bubble of its own below the banner")
    assert out["spinnerIn"], "the teacher's preparation has no spinner to hang under"


@node_only
def test_the_teachers_first_tool_call_does_not_hide_the_students_answer(sandbox):
    """With `roundHolder` null, the teacher's first `tool_start` finalized the
    *first* bubble — `roundHolder || holder` — against an empty round text, and
    hid the student's answer."""
    out = _node(sandbox, _STUDENT_THEN_TAKEOVER + """
        toolStart({ type: 'tool_start', tool: 'web_search', command: 'q', round: 1 });
        console.log(JSON.stringify({ history: history(),
          answerShown: holder.style.display !== 'none' }));
    """)
    assert out["answerShown"], f"the student's answer was hidden: {out['history']}"


@node_only
def test_the_teachers_cards_start_below_the_banner(sandbox):
    """Only a `.msg` bubble ended `tool_start`'s search for a thread to join, so
    with the student's last step empty (hidden) the search walked past the
    banner and the teacher's first card joined the student's thread above it."""
    out = _node(sandbox, """
        holder = bubble('');
        holder.style.display = 'none';
        lastToolThread = thread('bash');
        roundHolder = bubble('', 'msg-continuation');
        roundHolder.style.display = 'none';
        takeover({ type: 'teacher_takeover', teacher_model: 'big-model' });
        toolStart({ type: 'tool_start', tool: 'web_search', command: 'q', round: 1 });
        console.log(JSON.stringify({ history: history() }));
    """)
    h = out["history"]
    banner = next(i for i, n in enumerate(h) if "teacher-takeover-banner" in n["cls"])
    assert h[1]["cards"] == ["bash"], f"the teacher's card joined the student's thread: {h}"
    assert [n for n in h[banner + 1:] if n.get("cards")], f"no thread below the banner: {h}"
    assert "has-bottom" not in h[1]["cls"], (
        f"the student's thread was drawn as running on into the teacher's reply: {h}")


@node_only
def test_the_teachers_first_words_go_below_the_banner(sandbox):
    out = _node(sandbox, _STUDENT_THEN_TAKEOVER + """
        _ensureVisibleRoundForDelta();
        const banner = box.children.findIndex((n) => n.classList.contains('teacher-takeover-banner'));
        console.log(JSON.stringify({ banner,
          at: roundHolder ? box.children.indexOf(roundHolder) : null }));
    """)
    assert out["at"] is not None and out["at"] > out["banner"], out
