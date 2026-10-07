# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW-11` (fx2-chat, P23 round 2) — one agent turn is one reply.

**What was wrong** (measured on `1049a26` by driving the showcase, the seeded
"Plan the launch week"; `/work/notes/fx2-chat.md`): `P23-04` (CHAT-M-21) kept a
turn's reasoning per step and drew it, after a reload and live, as the stream
drew it — each step that thought got a bubble of its own under the model's
name. Five `.msg-ai` bubbles for one reply, two of them with a time; the tool
rows cut into three threads between them; the answer below the first screen.

**What is pinned.** A step that only thought draws no bubble of its own: its
reasoning goes on to the next bubble the turn draws, into that bubble's one
fold, one `.thinking-round` per step in order (a rule between them, so the
steps never run together — what CHAT-M-21 fixed stays fixed); its rows go above
that bubble. Driven, not read (`Law 20`):

  * the reload, through the real `chatRenderer.js` `addMessage` and the real
    `markdown.js` (the one loader, `B882`), over a shim that parses markup — on
    the seeded turn's two records (paused at the card, then its continuation),
    a step that said something, a turn that ended on reasoning, and a record
    from before `round_thinking`;
  * the live stream, through the arms cut out of `chat.js`'s `handleChatSubmit`
    (the harness `test_a_resumed_stream_draws_what_the_live_one_drew.py` built)
    and its end-of-stream render: mid-turn, the reasoning bubble is the last
    thing on the page with the rows above it; at the end, the reload's shape;
  * Stop: the round finalizer a Stop runs (`_finalizeInterruptedView`), on a
    step that had thought, and on one that had written nothing yet.
"""

import json
import shutil
import textwrap
from pathlib import Path

import pytest

import test_a_resumed_stream_draws_what_the_live_one_drew as streams
from test_tool_effect_surfaces_js import _CARD_STUBS, _make_sandbox, _run
from tests.helpers.esc_stub import ui_default_stub  # B874
from tests.helpers.markdown_harness import HARNESS_URL  # B882

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The real renderer, through the one loader. `markdown.js` watches the page for
# folds a person opened before (`MutationObserver`); the shim has no observer.
_REAL_MARKDOWN = """
globalThis.MutationObserver = globalThis.MutationObserver || class { observe() {} disconnect() {} };
import { importMarkdown } from '%s';
const mod = await importMarkdown();
export default mod.default;
export const svgifyEmoji = mod.svgifyEmoji;
""" % HARNESS_URL

# ── the reload ──────────────────────────────────────────────────────────────

_RELOAD_SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
// A browser moves a node appended somewhere else; the base shim copies it.
const append = Node.prototype.appendChild;
Node.prototype.appendChild = function (n) {
  if (n && n.tagName !== '#FRAGMENT' && n.parentNode) n.parentNode.removeChild(n);
  // And keeps its own text: the base shim drops it at the first child, so a
  // role line lost the model's name when the time was appended to it.
  if (!this.childNodes.length && this._text) {
    const t = new Node('#text'); t._text = this._text; this._text = '';
    t.parentNode = this; this.childNodes.push(t);
  }
  return append.call(this, n);
};
export const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
export { Node };
"""

_RELOAD_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, showError: () => {}, copyToClipboard: () => {},\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
    "markdown.js": _REAL_MARKDOWN,
})


@pytest.fixture(scope="module")
def reload_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("oneturnreload"), JS / "chatRenderer.js",
                         _RELOAD_SHIM, _RELOAD_STUBS)


# What a person sees of a turn: the shown nodes after their message, in order.
_READ = r"""
import { document, history } from './shim.js';
const { addMessage } = await import('./chatRenderer.js');
const words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
const shown = (n) => !(n.style && n.style.display === 'none');
function turn() {
  return history.children.filter(shown).map((n) => {
    if (n.classList.contains('msg-user')) return { user: true };
    if (n.classList.contains('agent-thread')) {
      return { rows: n.querySelectorAll('.agent-thread-node').map((c) => words(c.querySelector('.agent-thread-tool'))) };
    }
    if (!n.classList.contains('msg-ai')) return { other: n.className };
    const body = n.querySelector('.body');
    const folds = body.querySelectorAll('.thinking-section');
    const fold = folds[0];
    const rounds = fold ? fold.querySelectorAll('.thinking-round') : [];
    const said = body.childNodes.filter((c) => !(c.classList && c.classList.contains('thinking-section')))
      .map(words).join(' ').trim();
    return {
      bubble: true,
      model: words(n.querySelector('.role')).replace(words(n.querySelector('.role-timestamp')), '').trim(),
      time: !!n.querySelector('.role-timestamp'),
      folds: folds.length,
      steps: !fold ? [] : (rounds.length ? rounds.map(words) : [words(fold.querySelector('.thinking-content-inner'))]),
      foldFirst: !!fold && body.childNodes.indexOf(fold) === 0,
      said,
      footer: !!n.querySelector('.msg-footer'),
      stopped: words(n.querySelector('.stopped-indicator')) || null,
    };
  });
}
const user = (text) => { addMessage('user', text, null, { timestamp: '2026-10-07T15:42:00Z' }); };
"""


def _reload(sandbox, *records) -> list:
    calls = "\n".join(
        "addMessage('assistant', %s, 'scripted-demo', %s);" % (json.dumps(content), json.dumps(md))
        for content, md in records)
    return _run(sandbox, "", _READ + textwrap.dedent("""
        user('Plan my launch week.');
        %s
        console.log(JSON.stringify(turn()));
    """ % calls))


DIGEST = "5f3c1d2e9a8b7c6d"
WEEK_THOUGHTS = [
    "Three things to gather: the automations, the checklist and a free slot.",
    "The weekly metrics chain runs Monday at 08:00. Now the checklist.",
    "Three items are open before Wednesday. Checking the calendar for a gap.",
    "Wednesday has the review at 10:00 and nothing before it, so 09:00.",
    "Everything gathered. Writing it up short, bullets first.",
]
ANSWER = "**Booked:** *Launch review prep*, Wednesday 09:00–09:30."


def _row(round_, tool, action, **extra):
    command = json.dumps({"action": action}) if not action.startswith("{") else action
    return dict({"round": round_, "tool": tool, "command": command, "output": "ok",
                 "exit_code": 0, "status": "ok"}, **extra)


# The two records the showcase saved for the seeded turn (`/api/history`,
# measured on `1049a26`): the reply that paused at the card, then the
# continuation the approval let through.
WEEK_PAUSED = ("Allow this task to continue?", {
    "timestamp": "2026-10-07T15:42:05Z", "round_texts": [""],
    "round_thinking": [WEEK_THOUGHTS[0]], "thinking": WEEK_THOUGHTS[0],
    "tool_events": [_row(1, "manage_tasks", '{"action": "list"}', exit_code=None,
                         output="Waiting for an exact user approval.", ask_user={
                             "kind": "tool_approval", "approval_id": "appr-1", "session_id": "s1",
                             "question": "Allow this task to continue?", "resolved": "approve_task",
                             "options": [{"label": "Allow for this task", "value": "approve_task"}],
                             "action": {"tool": "manage_tasks", "content": '{"action": "list"}',
                                        "digest": DIGEST}})],
})
WEEK_CONTINUED = (ANSWER, {
    "timestamp": "2026-10-07T15:42:09Z", "round_texts": ["", "", "", "", ANSWER],
    "round_thinking": [WEEK_THOUGHTS[1], "", WEEK_THOUGHTS[2], WEEK_THOUGHTS[3], WEEK_THOUGHTS[4]],
    "tool_events": [
        _row(1, "manage_tasks", '{"action": "list"}', approved=True, approval_digest=DIGEST),
        _row(1, "manage_documents", "list"),
        _row(2, "manage_documents", "read"),
        _row(3, "manage_calendar", "list_events"),
        _row(4, "manage_calendar", "create_event"),
    ],
})


def test_the_seeded_turn_reloads_as_one_reply(reload_sandbox):
    out = _reload(reload_sandbox, WEEK_PAUSED, WEEK_CONTINUED)
    assert [next(iter(n)) for n in out] == ["user", "rows", "bubble"], out
    rows, reply = out[1], out[2]
    # Every call the turn made, in one thread, above the reply — the row that
    # asked for the approval taken by the approved one (`CHAT-M-8`).
    assert rows["rows"] == ["Tasks · list", "Documents · list", "Documents · read",
                            "Calendar · list events", "Calendar · create event"], rows
    # One header: the model and the time the turn started.
    assert reply["model"] == "scripted-demo" and reply["time"], reply
    # One fold, first in the bubble, each step's reasoning in order and apart.
    assert reply["folds"] == 1 and reply["foldFirst"], reply
    assert reply["steps"] == WEEK_THOUGHTS, reply["steps"]
    # And the answer, in the same bubble, with the reply's footer.
    # (The shim keeps no whitespace-only text between tags: "Booked:Launch…".)
    assert reply["said"].startswith("Booked:") and "Launch review prep" in reply["said"], reply["said"]
    assert reply["footer"]


def test_a_turn_still_at_the_card_shows_its_reasoning_below_its_rows(reload_sandbox):
    """The paused record on its own — the card not answered yet."""
    paused = (WEEK_PAUSED[0], dict(WEEK_PAUSED[1], tool_events=[
        dict(WEEK_PAUSED[1]["tool_events"][0], ask_user=dict(
            WEEK_PAUSED[1]["tool_events"][0]["ask_user"], resolved=None))]))
    out = _reload(reload_sandbox, paused)
    kinds = [next(iter(n)) for n in out]
    assert kinds[:3] == ["user", "rows", "bubble"], out
    assert out[2]["steps"] == [WEEK_THOUGHTS[0]] and out[2]["said"] == "", out[2]
    assert not out[2]["footer"], "a turn paused at the card has no reply yet"


def test_a_step_that_said_something_keeps_its_words_where_it_said_them(reload_sandbox):
    record = ("Done: one slot booked.", {
        "round_texts": ["", "Checking the calendar next.", "", "Done: one slot booked."],
        "round_thinking": ["First a list.", "The list is in.", "A gap at nine.", "Booked."],
        "tool_events": [_row(1, "manage_tasks", "list"), _row(2, "manage_calendar", "list_events"),
                        _row(3, "manage_calendar", "create_event")],
    })
    out = _reload(reload_sandbox, record)
    assert [next(iter(n)) for n in out] == ["user", "rows", "bubble", "rows", "bubble"], out
    assert out[1]["rows"] == ["Tasks · list"]
    assert out[2]["steps"] == ["First a list.", "The list is in."]
    assert out[2]["said"] == "Checking the calendar next."
    assert out[3]["rows"] == ["Calendar · list events", "Calendar · create event"]
    assert out[4]["steps"] == ["A gap at nine.", "Booked."]
    assert out[4]["said"] == "Done: one slot booked." and out[4]["footer"]


def test_a_turn_that_ended_on_reasoning_keeps_it_below_its_rows(reload_sandbox):
    """A reply that stopped (or ran out of steps) before it wrote a word."""
    record = ("", {
        "round_texts": ["", ""], "round_thinking": ["Looking first.", "Then the second list."],
        "tool_events": [_row(1, "manage_documents", "list_folders"), _row(2, "manage_documents", "list")],
    })
    out = _reload(reload_sandbox, record)
    assert [next(iter(n)) for n in out] == ["user", "rows", "bubble"], out
    assert out[1]["rows"] == ["Documents · list folders", "Documents · list"]
    assert out[2]["steps"] == ["Looking first.", "Then the second list."] and out[2]["said"] == ""


def test_a_turn_the_person_stopped_reloads_as_one_reply_that_says_so(reload_sandbox):
    """The record the route now keeps for a stopped turn (its rows and rounds,
    `test_a_stopped_agent_turn_reloads_as_one_reply.py`): the rows, one reply,
    and *Stopped · Continue* under it — as the live Stop drew it."""
    record = ("You have three", {
        "stopped": True, "round_texts": ["", "", "You have three"],
        "round_thinking": ["Folders first.", "Now the unfiled ones.", "Counting."],
        "tool_events": [_row(1, "manage_documents", "list_folders"), _row(2, "manage_documents", "list")],
    })
    out = _reload(reload_sandbox, record)
    assert [next(iter(n)) for n in out] == ["user", "rows", "bubble"], out
    reply = out[2]
    assert reply["steps"] == ["Folders first.", "Now the unfiled ones.", "Counting."]
    assert reply["stopped"] == "Stopped · Continue" and reply["footer"], reply


def test_a_turn_paused_at_the_card_never_says_stopped(reload_sandbox):
    """`stopped` on a reply that paused at a card (an old `mark-stopped` race
    wrote it there) is not drawn: that reply asked, it did not stop."""
    paused = (WEEK_PAUSED[0], dict(WEEK_PAUSED[1], stopped=True))
    out = _reload(reload_sandbox, paused)
    assert [n.get("stopped") for n in out if "bubble" in n] == [None], out


def test_a_record_from_before_draws_its_one_string_once(reload_sandbox):
    """A reply saved before `round_thinking` keeps one string for the turn."""
    record = ("The answer.", {
        "round_texts": ["", "The answer."], "thinking": "One string from before.",
        "tool_events": [_row(1, "bash", "ls")],
    })
    out = _reload(reload_sandbox, record)
    assert [next(iter(n)) for n in out] == ["user", "rows", "bubble"], out
    assert out[2]["steps"] == ["One string from before."] and out[2]["said"] == "The answer."


# ── live, and Stop ──────────────────────────────────────────────────────────
# The resumed-stream harness runs the live arms cut out of `handleChatSubmit`.
# Here its renderer is the real `markdown.js` (a fold with its header and
# inner, which the helpers read), and `runLive` is given two endings the
# stream has: its end-of-stream render (`finish`), and the round finalizer a
# Stop runs (`stop`).

_LIVE_MARKDOWN = (
    "globalThis.MutationObserver = globalThis.MutationObserver || class { observe() {} disconnect() {} };\n"
    "import { importMarkdown } from '%s';\n"
    "const realMarkdown = (await importMarkdown()).default;\n" % HARNESS_URL)


def _live_preamble() -> str:
    pre = streams._PREAMBLE
    imp = "import { document, Node, flushTimers, describe } from './shim.js';"
    assert pre.count(imp) == 1, "the harness's shim import moved"
    # `runLive` snapshots the page with `describe`; here that is this file's reader.
    pre = pre.replace(imp, "import { document, Node, flushTimers } from './shim.js';")
    start = pre.index("// The renderer: a `<think>` block becomes")
    end = pre.index("const added = [];")
    return (pre[:start] + _LIVE_MARKDOWN
            + "const rendered = [];\n"
            + "const markdownModule = Object.assign({}, realMarkdown, {\n"
            + "  processWithThinking: (s) => { rendered.push(String(s)); return realMarkdown.processWithThinking(s); },\n"
            + "});\n" + pre[end:])


def _live_driver() -> str:
    code = streams._live_driver()
    sig = "stopAfter = Infinity } = {}) {"
    assert code.count(sig) == 1, "runLive's signature moved"
    code = code.replace(sig, "stopAfter = Infinity, finish = false, stop = false } = {}) {")
    # The live stream's first bubble says when the turn started, as chat.js draws it.
    first = """holder.innerHTML = '<div class="role">test-model</div><div class="body"></div>';"""
    assert code.count(first) == 1, "runLive's first bubble moved"
    code = code.replace(first, first.replace(
        "test-model</div>", """test-model <span class="role-timestamp">03:42 PM</span></div>"""))
    end = "  _cancelThinkingTimer();\n}\n"
    assert end in code, "runLive's ending moved"
    # The end-of-stream render: from the line that reads the last step's text to
    # the fold it settles, cut out of `handleChatSubmit`.
    final = streams._between("const finalDisplay = _streamDisplayText(roundText, { final: _docFenceOpened });",
                             "settleTurnReasoning(roundHolder);")
    tail = ("  if (stop) { const f = _finalizeRoundRender(); snaps.push({ stop: !!(f && f.hasContent),"
            " holder: !!(f && f.holder === holder), last: lastContentRoundHolder === holder }); }\n"
            "  if (finish) {\n"
            "    let _sourcesExpanded = false, _sourcesData = null, _sourcesType = '', _findingsData = null, _sourcesHtml = '';\n"
            "    const _buildSourcesBox = () => '';\n"
            + final + "\n  }\n")
    at = code.rindex(end)
    return code[:at] + tail + code[at:]


_LIVE_READ = r"""
const words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
function describe() { return turn(); }
function turn() {
  return history.children.filter((n) => !(n.style && n.style.display === 'none')).map((n) => {
    if (n.classList.contains('agent-thread')) return { rows: n.querySelectorAll('.agent-thread-node').length };
    if (n.classList.contains('agent-thinking-dots')) return { waiting: true };
    if (!n.classList.contains('msg')) return { other: n.className };
    const body = n.querySelector('.body');
    const folds = body.querySelectorAll('.thinking-section');
    return {
      bubble: true, time: !!n.querySelector('.role-timestamp'),
      folds: folds.map((f) => (f.querySelectorAll('.thinking-round').length
        ? f.querySelectorAll('.thinking-round').map(words) : [words(f.querySelector('.thinking-content-inner'))])),
    };
  });
}
"""


def _live(sandbox, events, **opts) -> dict:
    script = (streams._module_level() + "\n" + _live_driver() + "\n" + _LIVE_READ + "\n" + textwrap.dedent("""
        const snaps = [];
        runLive(%s, snaps, %s);
        console.log(JSON.stringify({ end: turn(), snaps }));
    """ % (json.dumps(events), json.dumps(opts))))
    return _run(sandbox, _live_preamble(), script)


def _tool(round_, command, out="done"):
    return [
        {"type": "tool_start", "tool": "manage_documents", "command": command, "round": round_},
        {"type": "tool_output", "tool": "manage_documents", "command": command, "round": round_,
         "exit_code": 0, "output": out},
    ]


THREE_STEPS = (
    [{"delta": "<think>Looking for the folders first.</think>"}]
    + _tool(1, "list_folders")
    + [{"type": "agent_step", "round": 2}, {"delta": "<think>Now the unfiled ones.</think>"}]
    + _tool(2, "list")
    + [{"type": "agent_step", "round": 3},
       {"delta": "<think>Counting them.</think>Three unfiled documents."}]
)


def test_live_the_reasoning_bubble_stays_below_the_rows(sandbox):
    out = _live(sandbox, THREE_STEPS)
    snaps = out["snaps"]
    # `snaps[i]` is the page after event `i`. After step 1's call (event 2):
    # its rows, then the bubble holding its reasoning.
    after_first_call = snaps[2]
    assert [next(iter(n)) for n in after_first_call] == ["rows", "bubble"], after_first_call
    # After step 2's call (event 6): one thread of both rows, then one bubble
    # whose one fold holds both steps — never a bubble per step.
    after_second_call = snaps[6]
    bubbles = [n for n in after_second_call if "bubble" in n]
    assert [next(iter(n)) for n in after_second_call] == ["rows", "bubble"], after_second_call
    assert after_second_call[0]["rows"] == 2
    assert bubbles[0]["folds"] == [["Looking for the folders first.", "Now the unfiled ones."]]
    assert bubbles[0]["time"], "the turn's one bubble says when it started"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("oneturnlive"), JS / "agentThread.js",
                      streams._SHIM, streams._STUBS)
    for name in ("agentMeter.js", "agentStops.js", "spinner.js", "agentTurn.js",
                 "chatModelProvenance.js", "chatStreamErrors.js", "turnReasoning.js"):
        shutil.copy(JS / name, d / name)
    return d


def test_live_the_end_of_the_stream_is_the_reload(sandbox, reload_sandbox):
    live = _live(sandbox, THREE_STEPS, finish=True)["end"]
    assert [next(iter(n)) for n in live] == ["rows", "bubble"], live
    assert live[0]["rows"] == 2
    reply = live[1]
    assert reply["folds"] == [["Looking for the folders first.", "Now the unfiled ones.", "Counting them."]]
    assert reply["time"]
    # The same turn as its record reloads it.
    record = ("Three unfiled documents.", {
        "round_texts": ["", "", "Three unfiled documents."],
        "round_thinking": ["Looking for the folders first.", "Now the unfiled ones.", "Counting them."],
        "tool_events": [_row(1, "manage_documents", "list_folders"), _row(2, "manage_documents", "list")],
    })
    reloaded = _reload(reload_sandbox, record)[1:]
    assert [next(iter(n)) for n in reloaded] == ["rows", "bubble"]
    assert reloaded[1]["steps"] == reply["folds"][0] and reloaded[0]["rows"] == ["Documents · list folders", "Documents · list"]


def test_stop_while_a_step_thinks_keeps_the_turns_reasoning_in_one_fold(sandbox):
    events = THREE_STEPS[:1] + _tool(1, "list_folders") + [
        {"type": "agent_step", "round": 2}, {"delta": "<think>Now the unfiled ones.</think>"}]
    out = _live(sandbox, events, stop=True)
    end = out["end"]
    assert [next(iter(n)) for n in end] == ["rows", "bubble"], end
    assert end[1]["folds"] == [["Looking for the folders first.", "Now the unfiled ones."]]
    assert out["snaps"][-1]["stop"] is True, "the stopped step is the reply the Stop line goes under"


def test_stop_before_a_step_writes_gives_the_reasoning_back(sandbox):
    """Stop the moment step 2 opens: it wrote nothing, so it is hidden — and the
    reasoning it had taken goes back to step 1's bubble, which is shown again
    and is the one a Stop's line goes under (`lastContentRoundHolder`)."""
    events = THREE_STEPS[:1] + _tool(1, "list_folders") + [{"type": "agent_step", "round": 2}]
    out = _live(sandbox, events, stop=True)
    end = out["end"]
    assert [next(iter(n)) for n in end] == ["rows", "bubble"], end
    assert end[1]["folds"] == [["Looking for the folders first."]] and end[1]["time"]
    assert out["snaps"][-1] == {"stop": False, "holder": False, "last": True}


# ── the module itself, and the send path's one line ─────────────────────────

_MODULE = r"""
import { document, history, Node } from './shim.js';
const tr = await import('./turnReasoning.js');
const words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
let ids = 0;
/** A fold as `markdown.js` draws one; `live` as the live stream draws its own. */
function fold(text, { live = false, open = false } = {}) {
  const id = 'f' + (++ids);
  return '<div class="thinking-section"><div class="thinking-header" data-thinking-id="' + id + '">'
    + '<div class="thinking-header-left"><span data-label="thinking process">View thinking process</span></div>'
    + (live ? '<span class="live-think-timer">1.8s · 75 tok</span>' : '')
    + '<span class="thinking-toggle' + (live ? ' live-think-toggle' : '') + (open ? ' expanded' : '') + '" id="' + id + '-toggle"></span></div>'
    + '<div class="thinking-content' + (open ? ' expanded' : '') + '" id="' + id + '">'
    + '<div class="thinking-content-inner"><p>' + text + '</p></div></div></div>';
}
function bubble(html, { cls = 'msg msg-ai', time = false } = {}) {
  const n = document.createElement('div');
  n.className = cls;
  n.innerHTML = '<div class="role">m' + (time ? ' <span class="role-timestamp">03:42 PM</span>' : '')
    + '</div><div class="body">' + html + '</div>';
  history.appendChild(n);
  return n;
}
const shown = (n) => !(n.style && n.style.display === 'none');
"""


def _module(sandbox, body: str) -> dict:
    return _run(sandbox, "", _MODULE + textwrap.dedent(body))


def test_a_fold_the_live_stream_left_open_is_shut_then_replaced(reload_sandbox):
    """A turn that paused at the card ends with its live fold open and its clock
    in the header; the reply the approval lets go on reads as its reload does."""
    out = _module(reload_sandbox, """
        const paused = bubble(fold('Round one.', { live: true, open: true }), { time: true });
        const next = bubble('');
        tr.carryTurnReasoning(paused, next);
        const carried = next.querySelector('.thinking-section');
        const shutOnArrival = !carried.querySelector('.expanded');
        // The step's own render: a fresh fold from the renderer.
        next.querySelector('.body').innerHTML = fold('Round two.') + '<p>The answer.</p>';
        tr.settleTurnReasoning(next);
        const folds = next.querySelectorAll('.thinking-section');
        console.log(JSON.stringify({
          shutOnArrival, folds: folds.length,
          steps: folds[0].querySelectorAll('.thinking-round').map(words),
          clock: !!folds[0].querySelector('.live-think-timer'),
          open: !!folds[0].querySelector('.expanded'),
          pausedShown: shown(paused), time: !!next.querySelector('.role-timestamp'),
        }));
    """)
    assert out == {"shutOnArrival": True, "folds": 1, "steps": ["Round one.", "Round two."],
                   "clock": False, "open": False, "pausedShown": False, "time": True}, out


def test_a_fold_the_person_opened_stays_open(reload_sandbox):
    out = _module(reload_sandbox, """
        const first = bubble(fold('Round one.'), { time: true });
        const next = bubble('');
        tr.carryTurnReasoning(first, next);
        // The person opens the turn's fold while step 2 runs.
        next.querySelectorAll('.thinking-content, .thinking-toggle').forEach((n) => n.classList.add('expanded'));
        next.querySelector('.body').innerHTML = fold('Round two.') + '<p>The answer.</p>';
        tr.settleTurnReasoning(next);
        const f = next.querySelectorAll('.thinking-section');
        console.log(JSON.stringify({ folds: f.length, open: !!f[0].querySelector('.thinking-content.expanded'),
          steps: f[0].querySelectorAll('.thinking-round').map(words) }));
    """)
    assert out == {"folds": 1, "open": True, "steps": ["Round one.", "Round two."]}, out


def test_nothing_is_carried_past_what_a_person_reads(reload_sandbox):
    """A note, a stop line or a banner between two steps ends the stretch: the
    reasoning above it stays above it."""
    out = _module(reload_sandbox, """
        const first = bubble(fold('The student tried.'), { time: true });
        const banner = document.createElement('div');
        banner.className = 'teacher-takeover-banner';
        banner.textContent = 'A stronger model took over.';
        history.appendChild(banner);
        const next = bubble('');
        console.log(JSON.stringify({ above: tr.reasoningAbove(next) === first,
          moved: tr.carryTurnReasoning(first, next), firstShown: shown(first) }));
    """)
    assert out == {"above": False, "moved": False, "firstShown": True}, out


def test_the_footer_goes_under_the_bubble_the_turn_shows(reload_sandbox):
    """Live, the footer goes under the last step's bubble or the first; when both
    are hidden — the first step's reasoning went on, the last wrote nothing —
    under the bubble the turn shows (`chat.js`, end of stream)."""
    out = _module(reload_sandbox, """
        const user = bubble('<p>Hi</p>', { cls: 'msg msg-user' });
        const first = bubble(fold('One.'), { time: true });
        const thread = document.createElement('div'); thread.className = 'agent-thread';
        history.insertBefore(thread, first);
        const second = bubble('');
        tr.carryTurnReasoning(first, second);
        const third = bubble(''); third.style.display = 'none';
        console.log(JSON.stringify({ firstHidden: !shown(first), footerTo: tr.lastShownStep(first) === second }));
    """)
    assert out == {"firstHidden": True, "footerTo": True}, out


def _approval_send_line() -> str:
    """The lines `handleChatSubmit` runs once the reply's first bubble is on the
    page — the continuation an approval lets through takes the paused reply's
    reasoning there."""
    return streams._between("box.appendChild(holder);", "uiModule.scrollHistory();")


@pytest.mark.parametrize("decision, carried", [("approve_task", True), ("deny", False)])
def test_the_continuation_an_approval_lets_through_is_the_same_reply(reload_sandbox, decision, carried):
    out = _module(reload_sandbox, """
        const { reasoningAbove, carryTurnReasoning } = tr;
        const user = bubble('<p>Plan my week.</p>', { cls: 'msg msg-user' });
        const paused = bubble(fold('Three things to gather.'), { time: true });
        const rows = document.createElement('div'); rows.className = 'agent-thread';
        history.insertBefore(rows, paused);
        const box = history;
        const holder = bubble('<div class="ai-spinner">Processing request</div>');
        holder.remove();
        const approvalForSend = { approval_id: 'appr-1', decision: %s };
        const uiModule = { scrollHistory() {} };
        %s
        uiModule.scrollHistory();
        const f = holder.querySelectorAll('.thinking-section');
        console.log(JSON.stringify({ pausedShown: shown(paused), folds: f.length,
          steps: f.length ? f[0].querySelectorAll('.thinking-round').map(words) : [] }));
    """ % (json.dumps(decision), _approval_send_line()))
    if carried:
        assert out == {"pausedShown": False, "folds": 1, "steps": ["Three things to gather."]}, out
    else:
        assert out == {"pausedShown": True, "folds": 0, "steps": []}, out


def test_a_resumed_view_keeps_one_fold_while_a_step_streams(sandbox):
    """`resumeStream` — a page reloaded mid-turn — draws each step's reasoning
    shut, as the reload does; a step streaming there joins the turn's one fold
    as it comes, rather than standing under it as a second *View thinking
    process*. The view ends in the canonical reload (`agent_step` makes it rich)."""
    events = THREE_STEPS + ["[DONE]"]
    script = (streams._module_level() + "\n" + _live_driver() + "\n" + streams._RESUMED_DRIVER
              + "\n" + _LIVE_READ + "\n" + textwrap.dedent("""
        const snaps = [];
        await runResumed(%s, snaps);
        console.log(JSON.stringify({ snaps, reloads: reloads.length }));
    """ % json.dumps(events)))
    out = _run(sandbox, _live_preamble(), script)
    # `snaps[i]` is the page after event `i`. Step 3's words are streaming
    # (event 8): the rows, then one bubble, one fold of the three steps.
    streaming = out["snaps"][8]
    assert [next(iter(n)) for n in streaming] == ["rows", "bubble"], streaming
    assert streaming[1]["folds"] == [["Looking for the folders first.", "Now the unfiled ones.", "Counting them."]]
    assert all(len(n["folds"]) <= 1 for snap in out["snaps"] for n in snap if "bubble" in n), out["snaps"]
    assert out["reloads"] == 1


def test_every_fold_on_the_page_opens_its_own_reasoning(reload_sandbox):
    """A fold is opened by its id (`markdown.js`'s click handler reads
    `data-thinking-id` and calls `getElementById`). A reload draws every turn in
    one tick, and the id was the millisecond plus a block index that is always
    0: two turns' folds shared one, and the second turn's header opened the
    first turn's reasoning."""
    out = _run(reload_sandbox, "", _READ + textwrap.dedent("""
        // One millisecond for the whole reload, as a browser draws it (measured
        // under node with the real renderer: six folds, two ids between them).
        Date.now = () => 1791398137498;
        user('First.');
        addMessage('assistant', 'One.', 'm', %s);
        user('Second.');
        addMessage('assistant', 'Two.', 'm', %s);
        addMessage('assistant', '<think>A plain reply thought too.</think>Three.', 'm', {});
        const headers = history.querySelectorAll('.thinking-header');
        console.log(JSON.stringify(headers.map((h) => {
          const content = document.getElementById(h.dataset.thinkingId);
          const fold = h.parentNode;
          return { opens: !!content && content.parentNode === fold,
                   text: words(content && content.querySelector('.thinking-content-inner')) };
        })));
    """ % (json.dumps({"round_texts": ["", "One."], "round_thinking": ["First a.", "First b."],
                        "tool_events": [_row(1, "bash", "ls")]}),
           json.dumps({"round_texts": ["", "Two."], "round_thinking": ["Second a.", "Second b."],
                        "tool_events": [_row(1, "bash", "ls")]}))))
    assert [f["opens"] for f in out] == [True, True, True], out
    # (The shim keeps no whitespace-only text between the steps' parts.)
    assert [f["text"] for f in out] == ["First a.First b.", "Second a.Second b.", "A plain reply thought too."], out
