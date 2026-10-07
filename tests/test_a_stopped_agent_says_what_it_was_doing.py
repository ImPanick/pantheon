# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-10` — when a guard stops the agent, the page says what it was doing.

Two guards in `stream_agent_loop` end work the model did not end, and both used
to report one fixed sentence:

  * **The loop-breaker** said *"The loop-breaker detected repeated tool calls
    without new progress…"* for both of its conditions — a runaway (one exact
    call 15 times) and a stall (four rounds that only repeated earlier calls and
    wrote nothing). It never said which tool, how often or with what: the count
    was compared against 15 and thrown away.
  * **The unkept-promise stop** put the phrase it caught on the wire as
    `matched`, and the browser printed the fixed sentence instead.

Three more things were wrong underneath, and each is pinned here:

  1. **The line did not stay on screen.** It was appended to the round's own
     bubble. The next `agent_step` finalizes that bubble and hides a round that
     wrote nothing — which is what a loop-breaker round is — with everything in
     it; the unkept-promise stop ends the stream and the final render replaces
     the bubble's body. `rounds_exhausted` had already learned this (its comment
     in `chat.js` says so) and appends to the chat history instead.
  2. **It was not saved.** A reloaded thread had no trace that a guard fired.
  3. **"Identical" meant "the same first 120 characters".** Both loop-breaker
     counters keyed on `content[:120]`, so the sentence this row asks for would
     have been false for any long command, and a batch of distinct calls with a
     long shared prefix was aborted — the defect `test_loop_breaker_runaway.py`
     was written for, back again for arguments over 120 characters.

Everything is driven, not read (`Law 20`): the words through the functions that
compose them, the loop through `stream_agent_loop` with a scripted model, and
the page through the real modules under node — including the live SSE branch of
`chat.js` and its `_finalizeRoundRender`, lifted by brace balance and run.
"""

import asyncio
import json
import shutil
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import (  # noqa: E402
    _CARD_SHIM, _CARD_STUBS, _DOM, _make_sandbox, _run,
)
from tests.helpers.js_source import js_assignment, js_function  # B914

import src.agent_loop as agent_loop
from src import agent_stops
from src.agent_stops import (
    ARGS_EMPTY, ARGS_SHOWN, ARGS_WITHHELD, call_signature, safe_arguments,
    unkept_promise_stop,
)

ROOT = Path(__file__).resolve().parents[1]
AGENT_STOPS_JS = ROOT / "static" / "js" / "agentStops.js"
CHAT_JS = ROOT / "static" / "js" / "chat.js"
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the words ────────────────────────────────────────────────────────────────


def test_calls_that_differ_after_character_120_are_not_identical():
    # The identity the loop-breaker counts with. It used to be the first 120
    # characters, which made "identical arguments" a false sentence.
    shared = "python3 -c 'import sys; " + "x = 1; " * 20
    assert len(shared) > 120
    assert call_signature("bash", shared + "print(1)'") != call_signature("bash", shared + "print(2)'")
    assert call_signature("bash", "ls -la") == call_signature("bash", "  ls -la \n")
    assert call_signature("bash", "ls") != call_signature("python", "ls")


def test_the_repeated_command_is_quoted_on_one_line_and_cut_short():
    out = safe_arguments("bash", "tail -n 50\n   /var/log/app.log")
    assert out == {"arguments_state": ARGS_SHOWN, "arguments": "tail -n 50 /var/log/app.log"}
    long = safe_arguments("bash", "echo " + "abc " * 60)
    assert long["arguments_state"] == ARGS_SHOWN
    assert len(long["arguments"]) == agent_stops.ARGUMENTS_LIMIT
    assert long["arguments"].endswith("…")


@pytest.mark.parametrize("command", [
    'curl -H "Authorization: Bearer sk-live-4f9a8b7c6d5e4f3a" https://api.example.test/v1',
    "PASSWORD=hunter2 ./deploy.sh",
    "sshpass -p hunter2 ssh admin@db01",
    "export GITHUB_TOKEN=ghp_notreal && gh repo list",
    '{"client_secret": "abc", "url": "https://login.example.test"}',
    "aws s3 ls --profile x AKIAABCDEFGHIJKLMNOP",
    "cat ~/.ssh/id_rsa | head  # -----BEGIN OPENSSH PRIVATE KEY-----",
])
def test_arguments_that_may_hold_a_credential_are_not_echoed(command):
    out = safe_arguments("bash", command)
    assert out == {"arguments_state": ARGS_WITHHELD}


def test_a_credential_tool_is_never_quoted_whatever_it_says():
    assert safe_arguments("vault_get", '{"name": "backups"}') == {"arguments_state": ARGS_WITHHELD}


def test_the_shared_redactor_masks_what_it_recognises(monkeypatch):
    # `Law 14`: the support bundle's redactor, not a second one. A URL keeps
    # its host and path and loses the query string it might carry a key in.
    out = safe_arguments("web_fetch", '{"url": "http://10.9.8.7:8080/status?sig=Zx9"}')
    assert out["arguments_state"] == ARGS_SHOWN
    assert "sig=Zx9" not in out["arguments"]
    assert "10.9.8.7" not in out["arguments"]


def test_a_redactor_that_fails_withholds_rather_than_echoes(monkeypatch):
    import src.diagnostic_bundle as bundle

    def boom(_text):
        raise RuntimeError("redactor broke")

    monkeypatch.setattr(bundle, "redact", boom)
    assert safe_arguments("bash", "ls /srv/data") == {"arguments_state": ARGS_WITHHELD}


def test_no_arguments_is_said_as_none():
    assert safe_arguments("list_models", "   ") == {"arguments_state": ARGS_EMPTY}


def test_the_same_promise_three_times_is_quoted_with_its_count():
    stop = unkept_promise_stop(round_num=3, phrases=["Let me check the logs"] * 3, nudges=2)
    assert stop["message"] == "Stopped: said “Let me check the logs” 3 times without making a call."
    assert stop["announced"] == 3
    assert stop["matched"] == "Let me check the logs"


def test_different_promises_are_counted_and_the_last_is_quoted():
    # "said X three times" would be false when it said three different things.
    stop = unkept_promise_stop(
        round_num=4,
        phrases=["Let me check the logs", "I'll tail the output", "Let me look at the config"],
        nudges=2,
    )
    assert stop["message"] == ("Stopped: said it would act 3 times without making a call"
                               " — last: “Let me look at the config”.")


# ── through the loop ─────────────────────────────────────────────────────────


def _events(chunks):
    out = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _drive(monkeypatch, replies, *, tools, max_rounds, disabled_tools=None):
    """`stream_agent_loop` with a scripted model: one reply per round, the last
    one repeated if the loop asks for more. Every call it makes is recorded."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    queue = list(replies)
    executed = []

    async def fake_stream(*_a, **_k):
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        yield f"data: {json.dumps({'delta': text})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *_a, **_k):
        executed.append((block.tool_type, block.content))
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "look into the failing service"}],
            max_rounds=max_rounds, relevant_tools=set(tools),
            disabled_tools=disabled_tools,
        )]

    return _events(asyncio.run(drain())), executed


def _stops(events):
    return [e for e in events if e.get("type") in ("loop_breaker_triggered", "intent_nudge_exhausted")]


def _metrics(events):
    return next(e for e in events if e.get("type") == "metrics")["data"]


_TAIL = "```bash\ntail -n 50 /var/log/app.log\n```"
_PLAN = '```update_plan\n{"plan":"- [ ] keep going"}\n```'


def test_a_runaway_names_the_tool_the_count_and_the_arguments(monkeypatch):
    # The row's own sentence. Fifteen identical calls in one reply trip the
    # runaway backstop before any of them runs.
    events, executed = _drive(monkeypatch, ["\n".join([_TAIL] * 15), "Here is what I found."],
                              tools={"bash"}, max_rounds=3)
    stop = _stops(events)
    assert len(stop) == 1, events
    stop = stop[0]
    assert stop["message"] == "Stopped: called bash with identical arguments 15 times."
    assert stop["kind"] == "identical_calls"
    assert (stop["tool"], stop["count"], stop["round"]) == ("bash", 15, 1)
    assert stop["arguments_state"] == "shown"
    assert stop["arguments"] == "tail -n 50 /var/log/app.log"
    assert "not run" in stop["next"] and "tools are off" in stop["next"]
    # Every key the event carried before is still there (`Law 1`).
    assert stop["reason"] == "loop_breaker_stall"
    assert stop["detail"] == "calling bash with identical arguments over and over"
    assert executed == [], "the refused round must not run"


def test_a_stall_says_how_many_rounds_it_went_round_in(monkeypatch):
    # Same shape as `test_agent_rounds_exhausted.py`: a system-owned tool, so
    # no approval gate interrupts the repetition.
    events, _ = _drive(monkeypatch, [_PLAN] * 5 + ["Here is where it stands."],
                       tools={"update_plan"}, max_rounds=7)
    stop = _stops(events)[0]
    assert stop["kind"] == "no_progress"
    assert stop["rounds_without_progress"] == 4
    assert stop["message"] == ("Stopped: called update_plan with identical arguments 5 times,"
                               " 4 rounds in a row without writing anything.")
    assert stop["round"] == 5


def test_a_long_batch_of_distinct_calls_is_not_a_loop(monkeypatch):
    # `P4-10`'s premise defect. Eighteen DIFFERENT plan updates sharing their
    # first 150 characters: counted on `content[:120]` they were one call made
    # eighteen times, the runaway backstop fired and all eighteen were dropped.
    prefix = "- [ ] " + "reconcile the ledger entries for the quarter " * 4
    assert len(prefix) > 120
    batch = "\n".join(
        "```update_plan\n" + json.dumps({"plan": f"{prefix} step {i}"}) + "\n```"
        for i in range(18)
    )
    events, executed = _drive(monkeypatch, [batch, "All eighteen are in."],
                              tools={"update_plan"}, max_rounds=3)
    assert _stops(events) == []
    assert len(executed) == 18


def test_a_credential_in_the_repeated_call_goes_nowhere(monkeypatch):
    secret = "sk-live-4f9a8b7c6d5e4f3a2b1c"
    call = f'```bash\ncurl -H "Authorization: Bearer {secret}" https://api.example.test/v1/jobs\n```'
    events, _ = _drive(monkeypatch, ["\n".join([call] * 15), "Could not reach it."],
                       tools={"bash"}, max_rounds=3)
    stop = _stops(events)[0]
    assert stop["arguments_state"] == "withheld"
    assert "arguments" not in stop
    assert secret not in json.dumps(stop)
    assert secret not in json.dumps(_metrics(events).get("agent_stops"))


def test_a_switched_off_tool_is_named_as_the_way_out(monkeypatch):
    events, _ = _drive(monkeypatch, ["\n".join([_TAIL] * 15), "It is off."],
                       tools={"bash"}, max_rounds=3, disabled_tools={"bash"})
    assert "bash is switched off for this chat" in _stops(events)[0]["next"]


def test_the_unkept_promise_quotes_what_it_kept_saying(monkeypatch):
    events, executed = _drive(monkeypatch, ["Let me check the logs"], tools={"bash"}, max_rounds=5)
    stop = _stops(events)[0]
    assert stop["type"] == "intent_nudge_exhausted"
    assert stop["message"] == "Stopped: said “Let me check the logs” 3 times without making a call."
    assert (stop["nudges"], stop["announced"], stop["round"]) == (2, 3, 3)
    assert stop["matched"] == "Let me check the logs"
    assert stop["reason"] == "intent_without_action_nudge_cap"
    assert stop["next"].startswith("Nothing was run.")
    assert executed == []


def test_the_unkept_promise_does_not_claim_one_phrase_when_there_were_three(monkeypatch):
    events, _ = _drive(monkeypatch, ["Let me check the logs", "I'll tail the output",
                                     "Let me look at the config"], tools={"bash"}, max_rounds=5)
    assert _stops(events)[0]["message"].endswith("— last: “Let me look at the config”.")


@pytest.mark.parametrize("replies, tools", [
    (["\n".join([_TAIL] * 15), "Here is what I found."], {"bash"}),
    (["Let me check the logs"], {"bash"}),
])
def test_the_stop_survives_a_reload(monkeypatch, replies, tools):
    # One action, two surfaces, one answer: what the stream said is what the
    # saved reply carries.
    events, _ = _drive(monkeypatch, replies, tools=tools, max_rounds=5)
    live = _stops(events)
    assert live
    assert _metrics(events)["agent_stops"] == live


def test_a_turn_no_guard_stopped_saves_no_stop(monkeypatch):
    events, _ = _drive(monkeypatch, ["All done — nothing to change."], tools={"bash"}, max_rounds=3)
    assert _stops(events) == []
    assert "agent_stops" not in _metrics(events)


# ── the line on the page ─────────────────────────────────────────────────────


_STOP_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
export const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');

/** What a person would read off the line, and how it was built. */
export function describe(node) {
  if (!node) return null;
  const part = (cls) => node.querySelector('.' + cls);
  const read = (cls) => (part(cls) ? part(cls).textContent : null);
  return {
    className: node.className,
    kind: node.dataset.stopKind || null,
    round: node.dataset.round || null,
    headline: read('agent-stop-headline'),
    args: read('agent-stop-args'),
    withheld: read('agent-stop-withheld'),
    next: read('agent-stop-next'),
    // Raw `_html` of every part: '' if and only if it was set as text.
    html: node.childNodes.map((c) => c._html),
    inHistory: node.parentNode === history,
  };
}
"""


@pytest.fixture(scope="module")
def stop_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("agentstop"), AGENT_STOPS_JS, _STOP_SHIM, {})


def _stop_js(sandbox, script):
    return _run(
        sandbox,
        "import { document, history, describe } from './shim.js';\n"
        "const m = await import('./agentStops.js');\n",
        script,
    )


_RUNAWAY = {
    "type": "loop_breaker_triggered", "reason": "loop_breaker_stall", "kind": "identical_calls",
    "round": 4, "tool": "bash", "count": 15, "arguments_state": "shown",
    "arguments": "tail -n 50 /var/log/app.log",
    "message": "Stopped: called bash with identical arguments 15 times.",
    "next": "That last attempt was not run.",
    "detail": "calling bash with identical arguments over and over",
}


@needs_node
def test_the_line_says_the_headline_the_arguments_and_what_next(stop_sandbox):
    out = _stop_js(stop_sandbox, f"""
        const node = m.renderAgentStop(history, {json.dumps(_RUNAWAY)});
        console.log(JSON.stringify(describe(node)));
    """)
    assert out["headline"] == "Stopped: called bash with identical arguments 15 times."
    assert out["args"] == "tail -n 50 /var/log/app.log"
    assert out["next"] == "That last attempt was not run."
    assert out["withheld"] is None
    assert (out["kind"], out["round"]) == ("identical_calls", "4")
    assert out["inHistory"]


@needs_node
def test_hostile_words_reach_the_screen_as_text(stop_sandbox):
    # The headline quotes the model and the excerpt is a command line; both
    # are text somebody else wrote.
    event = dict(_RUNAWAY,
                 message="Stopped: said “<img src=x onerror=alert(1)>” 3 times.",
                 arguments="<script>alert(document.cookie)</script>",
                 next="<b onmouseover=alert(2)>go</b>")
    out = _stop_js(stop_sandbox, f"""
        console.log(JSON.stringify(describe(m.renderAgentStop(history, {json.dumps(event)}))));
    """)
    assert out["html"] == ["", "", ""], "a part of the line was assigned as markup"
    assert out["headline"] == "Stopped: said “<img src=x onerror=alert(1)>” 3 times."
    assert out["args"] == "<script>alert(document.cookie)</script>"


@needs_node
def test_withheld_arguments_are_said_to_be_withheld(stop_sandbox):
    event = {k: v for k, v in _RUNAWAY.items() if k != "arguments"}
    event["arguments_state"] = "withheld"
    out = _stop_js(stop_sandbox, f"""
        console.log(JSON.stringify(describe(m.renderAgentStop(history, {json.dumps(event)}))));
    """)
    assert out["args"] is None
    assert out["withheld"] == "Its arguments are not shown here because they may hold a credential."


@needs_node
def test_an_event_from_before_this_row_still_draws_its_own_sentence(stop_sandbox):
    old = {"type": "intent_nudge_exhausted", "reason": "intent_without_action_nudge_cap",
           "message": "The agent stopped because it repeatedly announced a tool action "
                      "without making the tool call.", "round": 3, "nudges": 2,
           "matched": "Let me check the logs"}
    out = _stop_js(stop_sandbox, f"""
        console.log(JSON.stringify(describe(m.renderAgentStop(history, {json.dumps(old)}))));
    """)
    assert out["headline"] == old["message"]
    assert (out["args"], out["withheld"], out["next"]) == (None, None, None)


@needs_node
def test_anything_else_draws_nothing(stop_sandbox):
    out = _stop_js(stop_sandbox, """
        const drawn = [
          m.renderAgentStop(history, { type: 'tool_output', message: 'x' }),
          m.renderAgentStop(history, null),
          m.renderAgentStop(null, { type: 'loop_breaker_triggered', message: 'x' }),
        ];
        console.log(JSON.stringify({ drawn: drawn.map(Boolean), children: history.childNodes.length }));
    """)
    assert out == {"drawn": [False, False, False], "children": 0}


# The live branch of `chat.js`, run rather than read. The SSE switch is 2,000
# lines inside one function, so the branch and the round finalizer are cut out
# by brace balance (`Law 20` option 2) and run against the real `agentStops.js`
# in the DOM shim, in the order the stream delivers them: the stop event, then
# the next round's `agent_step`, whose first act is `_finalizeRoundRender()`.
#
# `B914`. The finalizer is assigned twice in `handleChatSubmit`: first as a
# no-op the catch path can see (`let _finalizeRoundRender = () => {};`), then
# for real a thousand lines later. These cases cut it by the name alone, which
# opens the first, so for as long as they existed they ran `{}` — and the first
# one, about the next step hiding a round that wrote nothing, never hid one.
# The cut is now the assignment that holds the finalizer's own first line, and
# the script reports whether the round was hidden, so an empty finalizer cannot
# pass for a real one again.

_LIVE_SCRIPT = r"""
import { installDom, Node } from './dom.js';
import { renderAgentStop } from './agentStops.js';
// `B-NEW-11` (fx2-chat): the finalizer settles a step's reasoning through it.
import { settleTurnReasoning } from './turnReasoning.js';
const document = installDom();
const uiModule = { scrollHistory() {} };
const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
function bubble(text) {
  const wrap = history.appendChild(new Node('div'));
  wrap.className = 'msg msg-ai';
  const body = wrap.appendChild(new Node('div'));
  body.className = 'body';
  if (text) body.textContent = text;
  return wrap;
}
const markdownModule = {
  normalizeThinkingMarkup: (s) => String(s || ''),
  processWithThinking: (s) => String(s || ''),
  squashOutsideCode: (s) => String(s || ''),
};
function _streamDisplayText(t) { return String(t || ''); }
function _ensureStreamLayout(body) __ENSURE__
let roundFinalized = false;
let roundFinalization = null;
let lastContentRoundHolder = null;
const holder = bubble('On it.');
let roundHolder = bubble(__ROUND_TEXT__);
let roundText = __ROUND_TEXT__;
const _finalizeRoundRender = () => __FINALIZE__;
const _isBg = false;
const _cancelThinkingTimer = () => {};
const _removeThinkingSpinner = () => {};
for (const json of [__EVENT__]) __BRANCH__
__AFTER__
const hidden = (n) => { for (let p = n; p; p = p.parentNode) if (p.style && p.style.display === 'none') return true; return false; };
const inBubble = (n) => { for (let p = n.parentNode; p; p = p.parentNode) if (p.classList && p.classList.contains('msg')) return true; return false; };
const lines = history._walk([]).filter((n) => n.classList && (n.classList.contains('agent-stop') || n.classList.contains('stopped-indicator')));
console.log(JSON.stringify({
  found: lines.length,
  visible: lines.filter((n) => !hidden(n)).map((n) => n.textContent),
  insideABubble: lines.some(inBubble),
  roundHidden: roundHolder.style.display === 'none',
}));
"""

#: The real finalizer's first line. `B914`: a cut that does not hold it is the
#: no-op placeholder, and the cases below would run nothing.
_FINALIZER_MARKER = "if (roundFinalized) return roundFinalization;"


def _finalizer(chat: str) -> str:
    body = js_assignment(chat, "_finalizeRoundRender", _FINALIZER_MARKER)
    assert "roundFinalized" in body, f"the round finalizer cut is not the real one: {body[:80]!r}"
    return body


def _live(sandbox: Path, event: dict, *, round_text: str, after: str) -> dict:
    chat = CHAT_JS.read_text(encoding="utf-8")
    branch = js_function(chat, "} else if (json.type === 'loop_breaker_triggered'")
    script = (_LIVE_SCRIPT
              .replace("__ENSURE__", js_function(chat, "function _ensureStreamLayout"))
              .replace("__FINALIZE__", _finalizer(chat))
              .replace("__ROUND_TEXT__", json.dumps(round_text))
              .replace("__EVENT__", json.dumps(event))
              .replace("__BRANCH__", branch)
              .replace("__AFTER__", after))
    return _run(sandbox, "", script)


@pytest.fixture(scope="module")
def live_sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("livestop")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    shutil.copy(AGENT_STOPS_JS, d / "agentStops.js")
    shutil.copy(AGENT_STOPS_JS.parent / "turnReasoning.js", d / "turnReasoning.js")   # B-NEW-11
    return d


@needs_node
def test_the_live_line_outlasts_the_next_round(live_sandbox):
    # A loop-breaker round writes nothing — that is its definition — and the
    # next `agent_step` hides a round that wrote nothing. The old line lived in
    # that round's body and went with it.
    out = _live(live_sandbox, _RUNAWAY, round_text="", after="_finalizeRoundRender();")
    # `B914`: the finalizer really ran, and did what the case is about.
    assert out["roundHidden"], "the round that wrote nothing was not hidden"
    assert out["found"] == 1
    assert len(out["visible"]) == 1, "the next step hid the line along with its round"
    assert out["visible"][0].startswith("Stopped: called bash with identical arguments 15 times.")
    assert not out["insideABubble"]


@needs_node
def test_the_live_line_outlasts_the_final_render(live_sandbox):
    # The unkept-promise stop ends the stream, and the end-of-stream render in
    # `chat.js` replaces the last round's body wholesale
    # (`_body4.innerHTML = …processWithThinking(…)`), which is simulated here as
    # the one assignment it is.
    stop = unkept_promise_stop(round_num=3, phrases=["Let me check the logs"] * 3, nudges=2)
    out = _live(live_sandbox, stop, round_text="Let me check the logs",
                after="roundHolder.querySelector('.body').innerHTML = 'Let me check the logs';")
    assert out["visible"] == [stop["message"] + stop["next"]]
    assert not out["insideABubble"]


# History replay: the same line, from the saved reply, in the round it stopped.

@pytest.fixture(scope="module")
def card_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("stopreplay"), CHAT_RENDERER, _CARD_SHIM, _CARD_STUBS)


def _replay(sandbox, metadata):
    return _run(sandbox, (
        "import { document, history } from './shim.js';\n"
        "const { addMessage } = await import('./chatRenderer.js');\n"
    ), f"""
        history.childNodes = [];
        addMessage('assistant', 'reply', 'test-model', {json.dumps(metadata)});
        const shape = history.children.map((n) => {{
          const cls = String(n.className || '');
          if (cls.includes('agent-stop')) return 'stop:' + n.querySelector('.agent-stop-headline').textContent;
          if (cls.includes('agent-thread')) return 'thread';
          if (cls.includes('msg')) return 'msg:' + (n.querySelector('.body') ? n.querySelector('.body').textContent : '');
          return cls;
        }});
        const line = history.querySelector('.agent-stop');
        console.log(JSON.stringify({{ shape, html: line ? line.childNodes.map((c) => c._html) : null }}));
    """)


def _plan_event(n):
    return {"round": n, "tool": "update_plan", "command": '{"plan":"- [ ] keep going"}',
            "output": "ok", "exit_code": 0}


@needs_node
def test_a_reloaded_loop_breaker_stop_sits_between_the_work_and_the_answer(card_sandbox):
    stop = dict(_RUNAWAY, kind="no_progress", round=5, tool="update_plan", count=5,
                arguments='{"plan":"- [ ] keep going"}', rounds_without_progress=4,
                message="Stopped: called update_plan with identical arguments 5 times,"
                        " 4 rounds in a row without writing anything.")
    out = _replay(card_sandbox, {
        "round_texts": ["", "", "", "", "", "Here is where it stands."],
        "tool_events": [_plan_event(n) for n in (1, 2, 3, 4)],
        "agent_stops": [stop],
    })
    assert out["shape"] == ["thread", "stop:" + stop["message"], "msg:Here is where it stands."]


@needs_node
def test_a_reloaded_unkept_promise_follows_the_round_that_made_it(card_sandbox):
    stop = unkept_promise_stop(round_num=3, phrases=["Let me check the logs"] * 3, nudges=2)
    out = _replay(card_sandbox, {
        "round_texts": ["Let me check the logs"] * 3,
        "agent_stops": [stop],
    })
    assert out["shape"] == ["msg:Let me check the logs"] * 3 + ["stop:" + stop["message"]]


@needs_node
def test_a_reloaded_stop_is_still_text(card_sandbox):
    stop = dict(_RUNAWAY, round=1, message="Stopped: <img src=x onerror=alert(1)>",
                arguments="<svg onload=alert(1)>")
    out = _replay(card_sandbox, {"round_texts": ["", "Done."], "agent_stops": [stop]})
    assert out["html"] == ["", "", ""]
    assert "stop:Stopped: <img src=x onerror=alert(1)>" in out["shape"]


@needs_node
def test_a_one_round_reply_with_a_stop_still_shows_it(card_sandbox):
    # The replay branch used to be reachable only with tool events or more
    # than one round of text; a stop is drawn only there, so it opens it too.
    out = _replay(card_sandbox, {"round_texts": [""], "agent_stops": [dict(_RUNAWAY, round=1)]})
    assert "stop:" + _RUNAWAY["message"] in out["shape"]
