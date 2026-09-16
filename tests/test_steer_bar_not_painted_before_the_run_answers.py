# SPDX-License-Identifier: AGPL-3.0-or-later
"""B81 — the steer bar was drawn one round trip before the run could contradict it.

`B14` made the run announce its own steerability as the first SSE event, which
is the only place that can answer the question — but it arrives after the
response does. `chat.js` fired `_setForegroundChatBusy(true)` at send-path
entry, `chatStream.js` drew the bar on that edge, and the
`POST /api/chat_stream` does not leave until ~880 lines of synchronous composer
setup later — so on a research turn the bar was up for that plus one network
round trip before `stream_steerable` removed it.

**The decision this row asked for, made deliberately.** Two options were named
and both were declined:

  * an `X-Pantheon-Steerable` header beside `X-Pantheon-Run-Id` reaches
    `chat.js` before the first chunk, but `chat.js` owns the response and
    `chatStream.js` owns the bar, so it is a second path for one fact
    (`Law 14`) — and it arrives after the POST, so the bar is still painted for
    the 880 lines before it. It fixes the smaller half of the window and adds a
    transport;
  * drawing nothing until the run answers retires steering on any server that
    has the steer route but not the event, which is the half of `Verify` that
    says steering must still work there.

What landed instead is neither: the client-side guess that already existed was
**corrected**, not replaced. `routes/chat_routes.py` `_stream_is_steerable`
decides from four terms — `chat_mode`, `do_research`, `is_image_session`,
`compare_mode`. `chatStream.js` read ONE of them (`_steerChatModeOnly`), which
is why a research turn drew a bar: research is sent in agent mode, so the term
it read says nothing about it. `chat.js` now evaluates the two terms a client
can honestly see, at the one moment both are readable — the research toggle is
cleared just before the POST — and ships the verdict on the busy event it
already dispatches. No new header, no new event, no new transport.

Stated rather than faked: `is_image_session` is a model/endpoint-registry
question with no client equivalent, and a compare pane never reaches this edge
(`compare/stream.js` POSTs `/api/chat_stream` itself). Both stay with the run's
own answer, which is the only thing that knows.

These run the real code from BOTH files together through
`tests/harness/steer_bar_first_paint.js` (`Law 20`), because the property lives
between them. "Painted" means a `.steer-bar` node was really inserted by the
real `_ensureSteerBar`; the timeline is the order the insertions and removals
really happened. Measured before the fix: a research turn's timeline was
`["paint"]` with nothing to remove it on a server with no event, and
`["paint", "remove"]` on one with it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness" / "steer_bar_first_paint.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(turn, server="none", *extra) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS), turn, server, *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── Verify, first half: a research turn paints nothing, ever ────────────────

@pytest.mark.parametrize("server", ["none", "unsteerable"])
def test_a_research_turn_paints_no_steer_bar_at_any_point(server):
    """The row's `Verify`, on both servers — including the one that never
    corrects, where the old code left the bar up for the whole run."""
    got = _run("research", server)
    assert got["paintedBeforeTheRunAnswered"] is False
    assert got["timeline"] == [], (
        "before B81 the busy edge painted the bar for a research turn and only "
        "`stream_steerable` took it down, one round trip later"
    )
    assert got["paintedNow"] is False


def test_a_research_turn_that_the_run_says_is_steerable_gets_its_bar():
    """`B14` runs in both directions and still does: a `research_pending`
    continuation, or an auto-escalated turn, is corrected UPWARD — and the paint
    happens only once the run has said so, never before."""
    got = _run("research", "steerable")
    assert got["paintedBeforeTheRunAnswered"] is False
    assert got["timeline"] == ["paint"]
    assert got["paintedNow"] is True


# ── Verify, second half: a server with no event must keep steering ─────────

def test_an_agent_turn_still_gets_its_bar_with_no_event_from_the_server():
    """The reason "draw nothing until the run answers" was declined."""
    got = _run("agent", "none")
    assert got["paintedBeforeTheRunAnswered"] is True
    assert got["timeline"] == ["paint"]


def test_steering_still_sends_on_a_server_that_never_answers():
    got = _run("agent", "none", "steer")
    assert got["steerSent"] is True
    assert got["requests"] == [{"url": "/api/chat/steer/sess-1", "method": "POST"}]


# ── the parts that must not have changed ───────────────────────────────────

def test_a_chat_turn_still_paints_nothing():
    """`P6-18`'s own case. Chat mode has no rounds, so no step to deliver at."""
    got = _run("chat", "none")
    assert got["timeline"] == []


def test_the_run_still_takes_the_bar_down_when_it_says_no():
    """An image-generation session is the case the client cannot see: the bar
    goes up on the composer's guess and the run takes it down. `B14` intact."""
    got = _run("agent", "unsteerable")
    assert got["timeline"] == ["paint", "remove"]
    assert got["paintedNow"] is False


@pytest.mark.parametrize("turn,expected", [("agent", True), ("research", False), ("chat", False)])
def test_the_composer_verdict_reads_the_mode_and_the_research_toggle(turn, expected):
    """Two terms, not one and not four. The mode alone is what said a research
    turn was steerable; `is_image_session` and `compare_mode` are deliberately
    absent, because a client answer to either would be a second predicate."""
    assert _run(turn, "none")["verdict"] is expected


# ── the trap in the middle: a busy edge that carries no verdict ────────────
#
# `_setForegroundChatBusy(true)` is raised three times over one turn: once by
# the send path (which is the only one that knows what the turn is) and again by
# `setStreamingState('streaming')` and `_syncForegroundStreamGlobals`, after the
# composer has cleared its toggles. A verdict is what marks the first from the
# other two.

def test_a_verdictless_busy_edge_does_not_erase_the_verdict_in_hand():
    """`setStreamingState('streaming')` re-announces the same run AFTER the
    research toggle has been cleared. If that edge recomputed — or reset the
    verdict to unknown and fell back to the mode alone — the bar would appear
    mid-research, which is the defect with a delay on it."""
    got = _run("research-resync", "none")
    assert got["paintedAfterResync"] is False
    assert got["timeline"] == []


def test_a_verdictless_busy_edge_leaves_a_steerable_turn_alone():
    got = _run("agent-resync", "none")
    assert got["paintedAfterResync"] is True
    assert got["timeline"] == ["paint"]


def test_a_verdict_does_not_outlive_its_run():
    """Run one is research, run two is an agent turn announced with no verdict
    (an older `chat.js`, or the re-announcement path). The first run's `false`
    must be gone by then, or steering is retired for the rest of the page."""
    got = _run("research-then-agent", "none")
    assert got["paintedBeforeTheRunAnswered"] is False
    assert got["paintedAfterResync"] is True
    assert got["timeline"] == ["paint"]


def test_a_verdictless_edge_does_not_throw_away_the_run_s_own_answer():
    """The run overruled the composer upward and is then re-announced. `B14`'s
    answer is the authoritative one and outranks a guess that has since gone
    stale — before this, every busy edge reset it to unknown."""
    got = _run("research-answered-resync", "none")
    assert got["paintedBeforeTheRunAnswered"] is False
    assert got["paintedAfterResync"] is True
    assert got["timeline"] == ["paint"]


def test_a_composer_it_cannot_read_fails_open():
    """`Law 1`: an unreadable toggle must not retire steering. The server is the
    authority and refuses what it cannot deliver; withholding the bar on a
    client-side exception would hide a control that works."""
    got = _run("broken-composer", "none")
    assert got["verdict"] is True
    assert got["timeline"] == ["paint"]
