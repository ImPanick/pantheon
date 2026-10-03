# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-M-1 and CHAT-M-5: a reply can be stopped, whichever way it
reached the screen and whichever key stops it.

**What was wrong.**

  * **CHAT-M-1.** Escape is the keyboard's Stop (`keyboard-shortcuts.js`), and
    it called `chatModule.abortCurrentRequest()` with no argument. Without
    `stopServer` that only drops the browser's reader: the run is detached, so
    the server finished it. Measured on `9560d50`: Escape at word 5 of 399, the
    screen said "[Message interrupted]", the server streamed on for 32 s, saved
    all 399 words and named the chat after them. The Stop *button* was right.
  * **CHAT-M-5.** A reply picked up after a reload or a chat switch
    (`resumeStream`) never touched the send button: it stayed "+ New" for the
    whole reply, and there was no way to stop it (Escape did nothing either).

**What changed.** The Stop button's branch of `handleChatSubmit` is one
function, `_stopForegroundReply`; `stopCurrentReply()` is exported and is the
one call Escape makes. `resumeStream` sets the button to Stop through the same
`updateSubmitButton` the live send uses (`FORBIDDEN.md` Part 1: `.send-btn`'s
state machine is reproduced, not copied) and hands it back when the replay
ends or the person leaves; a Stop pressed on a resumed reply posts the exact
run's stop, and the replay ends on the reload of the saved, stopped reply.

Driven under node (`Law 20`): the real functions cut out of `chat.js`, and the
resumed-view harness of `test_a_resumed_stream_draws_what_the_live_one_drew.py`
(its recorded run, its page, its `sandbox`).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_a_resumed_stream_draws_what_the_live_one_drew import RUN, _page, sandbox  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _defn(name: str, prefix: str = "function ") -> str:
    src = CHAT_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    return js_definition(src, code.index(f"{prefix}{name}(")).replace("export function", "function", 1)


# ── CHAT-M-1: Escape stops the way the button stops ────────────────────────

_STOP_CASE = r"""
const calls = { abort: [], fetch: [], button: [], drained: [] };
const API_BASE = '';
globalThis.fetch = (url, init) => { calls.fetch.push(url); return Promise.resolve({ ok: true }); };
const document = { querySelector: (sel) => (sel === '.send-btn' ? { dataset: {} } : null), querySelectorAll: () => [] };
const fileHandlerModule = {};
const sessionModule = { getCurrentSessionId: () => 's1' };
const _researchingStreamIds = new Set();
const _resumingStreams = new Set(__RESUMING__);
const _resumeStopRequested = new Set();
const _resumeHoldsButton = new Set(__RESUMING__);
function _clearResearchTimer() {}
function abortCurrentRequest(stopServer) { calls.abort.push(stopServer === true); }
function updateSubmitButton(state) { calls.button.push(state); }
function _drainQueuedAgentRequests(sid) { calls.drained.push(sid); }
const uiModule = { el: () => null, scrollHistory() {} };
let currentHolder = null, currentAccumulated = '', currentSpinner = null;
let isStreaming = __STREAMING__, _sendInFlight = false;
__FNS__
const stopped = stopCurrentReply();
console.log(JSON.stringify(Object.assign(calls, { stopped,
  resumeStop: [..._resumeStopRequested], holds: [..._resumeHoldsButton] })));
"""


def _stop(tmp_path, *, streaming: bool, resuming=()) -> dict:
    case = (_STOP_CASE
            .replace("__STREAMING__", "true" if streaming else "false")
            .replace("__RESUMING__", json.dumps(list(resuming)))
            .replace("__FNS__", _defn("_stopForegroundReply") + "\n" + _defn("stopCurrentReply")))
    (tmp_path / "case.mjs").write_text(case, encoding="utf-8")
    out = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_escape_while_a_reply_streams_cancels_the_server_run(tmp_path):
    out = _stop(tmp_path, streaming=True)
    assert out["stopped"] is True
    # `abortCurrentRequest(true)` is the exact-run stop the button posts.
    assert out["abort"] == [True]
    assert out["button"] == ["idle"]


def test_escape_with_nothing_streaming_does_nothing(tmp_path):
    out = _stop(tmp_path, streaming=False)
    assert out == {"abort": [], "fetch": [], "button": [], "drained": [], "stopped": False,
                   "resumeStop": [], "holds": []}


def test_stopping_a_resumed_reply_marks_it_for_the_saved_record(tmp_path):
    out = _stop(tmp_path, streaming=True, resuming=["s1"])
    assert out["abort"] == [True]
    assert out["resumeStop"] == ["s1"], "the replay must end on the saved, stopped reply"
    assert out["holds"] == [], "the idle the Stop sets is the hand-back"


# ── CHAT-M-5: a resumed reply has a Stop ───────────────────────────────────

def test_a_resumed_reply_sets_the_send_button_to_stop_and_back(sandbox):
    out = _page(sandbox, """
        const events = %s;
        const during = [];
        await runResumed(events, [], { onEvent() { during.push(sendBtn.dataset.mode); } });
        console.log(JSON.stringify({ during, states: buttonStates, after: sendBtn.dataset.mode,
                                     holds: [..._resumeHoldsButton] }));
    """ % json.dumps(RUN))
    assert out["states"] == ["streaming", "idle"]
    assert set(out["during"]) == {"streaming"}, "the button left Stop while the reply streamed"
    assert out["after"] == "" and out["holds"] == []


def test_a_replay_for_another_chat_does_not_take_the_button(sandbox):
    out = _page(sandbox, """
        sessionModule.current = 's2';
        await runResumed(%s, []);
        console.log(JSON.stringify({ states: buttonStates }));
    """ % json.dumps(RUN))
    assert out["states"] == []


def test_leaving_the_chat_mid_replay_hands_the_button_back(sandbox):
    out = _page(sandbox, """
        let atLeave = null;
        await runResumed(%s, [], { onEvent(i) {
          if (i === 5) { atLeave = sendBtn.dataset.mode; sessionModule.current = 's2'; clear(); }
        } });
        console.log(JSON.stringify({ atLeave, states: buttonStates, after: sendBtn.dataset.mode }));
    """ % json.dumps(RUN))
    assert out["atLeave"] == "streaming"
    assert out["states"] == ["streaming", "idle"] and out["after"] == ""


def test_a_stopped_resumed_reply_ends_on_the_saved_record(sandbox):
    """A plain-text reply is finalised in place when it ends on its own; one
    the person stopped is drawn from what the server saved (marked stopped,
    with its Continue), so the replay reloads it instead."""
    plain = [{"delta": "Hello "}, {"delta": "there"}, "[DONE]"]
    out = _page(sandbox, """
        await runResumed(%s, [], { onEvent(i) { if (i === 0) _resumeStopRequested.add('s1'); } });
        console.log(JSON.stringify({ reloads: reloads.map((r) => r.id), added: added.length }));
    """ % json.dumps(plain))
    assert out == {"reloads": ["s1"], "added": 0}
