# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-02` — the elapsed time on a running tool card, and where it comes from.

The server has always sent `elapsed_s` on every `tool_progress` event —
measured from the moment the subprocess actually started — and **nothing in
`static/` ever read it**. The one place the handler mentioned elapsed time read
`json.elapsed`, a key nobody sends, so the indeterminate image-progress case
rendered an empty string.

The card's own timer was a local stopwatch started when the `tool_start` event
was *rendered*. That is not when the tool started: it is after the dispatch,
after the network, and for an approved tool after however long the person took
to press the button. On a resumed background stream it is worse — `tool_start`
replays and the clock restarts at zero on a tool that has been running for a
minute.

The 50ms ticker stays, because its reason is good: a number that only moved on
the 2s backend heartbeat reads as frozen. What changes is its anchor. Every
progress event re-bases it on the server's figure, so the smooth count is a
correction of server truth rather than a stopwatch that started late.

The logic is lifted out and run rather than read: the branch that does this is
buried in a 200-line SSE switch, and a test that asserts on its source text
would be a test of the file.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHAT = _REPO / "static" / "js" / "chat.js"
_SUBPROCESS_TOOLS = _REPO / "src" / "agent_tools" / "subprocess_tools.py"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _reanchor_source() -> str:
    """The re-anchoring branch, lifted from chat.js."""
    text = _CHAT.read_text(encoding="utf-8")
    start = text.index("if (currentToolBubble && json.elapsed_s != null) {")
    depth, i = 0, start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return textwrap.dedent(text[start:i + 1])


def _run(payload: dict, start_offset_ms: int = 0) -> dict:
    script = f"""
        const NOW = 1_000_000_000_000;
        const Date_now = () => NOW;
        const Date = {{ now: Date_now }};
        const currentToolBubble = {{ _startTime: NOW - {start_offset_ms} }};
        const json = {json.dumps(payload)};
        {_reanchor_source()}
        console.log(JSON.stringify({{
          startTime: currentToolBubble._startTime,
          impliedElapsedS: (NOW - currentToolBubble._startTime) / 1000,
        }}));
    """
    proc = subprocess.run(["node", "--input-type=module"], input=textwrap.dedent(script),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_clock_is_re_anchored_to_what_the_server_says():
    # The card thinks 2s have passed; the server says 47.3. The server wins,
    # and the ticker's next frame reads 47.3 rather than 2.
    out = _run({"elapsed_s": 47.3}, start_offset_ms=2000)
    assert out["impliedElapsedS"] == pytest.approx(47.3)


def test_a_late_start_is_corrected_rather_than_accumulated():
    # The failure this exists for: the local clock starts when `tool_start` is
    # rendered, so it is always behind, and it never catches up on its own.
    late = _run({"elapsed_s": 12.0}, start_offset_ms=0)
    assert late["impliedElapsedS"] == pytest.approx(12.0), (
        "a card that has just rendered must still show the tool's real age"
    )


@pytest.mark.parametrize("payload", [
    {},                          # no elapsed at all (an image-progress tick)
    {"elapsed_s": None},
    {"elapsed_s": "not a number"},
    {"elapsed_s": -5},           # a clock that went backwards
])
def test_a_missing_or_nonsense_figure_leaves_the_local_clock_alone(payload):
    # Better a slightly-late number that moves than a card that jumps to 1970.
    out = _run(payload, start_offset_ms=3000)
    assert out["impliedElapsedS"] == pytest.approx(3.0)


def test_zero_is_a_real_answer():
    # A tool that has just started reports 0.0, and that is not "missing".
    out = _run({"elapsed_s": 0}, start_offset_ms=9000)
    assert out["impliedElapsedS"] == pytest.approx(0.0)


# ── the key both ends use ─────────────────────────────────────────────────────


def test_the_server_sends_the_key_the_client_reads():
    # The mismatch the row is named after, held from both sides so a rename on
    # either one fails here rather than silently emptying the display.
    server = _SUBPROCESS_TOOLS.read_text(encoding="utf-8")
    assert '"elapsed_s": round(time.time() - started, 1)' in server
    client = _CHAT.read_text(encoding="utf-8")
    assert "json.elapsed_s" in client
    # Whole-line comments are cut first. The comment explaining this fix quotes
    # the wrong key by name, and matching prose would fail on the sentence that
    # documents the fix — `Law 20`, and the fourth time this session.
    code = "\n".join(
        line for line in client.splitlines() if not line.lstrip().startswith("//")
    )
    assert re.search(r"json\.elapsed(?![_\w])", code) is None, (
        "something reads `json.elapsed` again — a key nothing has ever sent"
    )


def _ticker_intervals() -> list:
    """Every `_elapsedTicker = setInterval(…, N)` and its N."""
    text = _CHAT.read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"_elapsedTicker = setInterval\(", text):
        depth, i = 0, match.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        call = text[match.end():i]
        found.append(int(call.rsplit(",", 1)[1].strip()))
    return found


def test_the_smooth_ticker_survived():
    # Anchoring to a 2s heartbeat by *replacing* the ticker would make the
    # number stand still between events, which is the thing its own comment
    # says it exists to avoid. Every ticker is checked, not "a `}, 50)` appears
    # somewhere" — there are two and the other one is the document writer's.
    intervals = _ticker_intervals()
    assert intervals, "no elapsed ticker left at all"
    assert all(ms <= 250 for ms in intervals), (
        f"an elapsed ticker slowed to {intervals}ms; below ~4fps the number "
        "reads as stuck between server heartbeats"
    )


def test_the_image_progress_reads_the_server_figure_too():
    # M5: the re-anchor branch and this one read the same key, and fixing only
    # one leaves the indeterminate image tick showing an empty string — which
    # is the exact symptom the row was filed for.
    client = _CHAT.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in client.splitlines() if not line.lstrip().startswith("//")
    )
    value_line = next(
        line for line in code.splitlines()
        if "agent-image-progress" not in line and "value.textContent" in line
    )
    assert "elapsed_s" in value_line, (
        "the indeterminate image-progress tick shows nothing again: "
        + value_line.strip()
    )


def test_every_progress_payload_carries_the_figure():
    # Both emitters — the tmux path and the plain-subprocess path.
    server = _SUBPROCESS_TOOLS.read_text(encoding="utf-8")
    assert server.count('"elapsed_s": round(time.time() - started, 1)') == 2
