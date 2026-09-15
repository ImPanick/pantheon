# SPDX-License-Identifier: AGPL-3.0-or-later
"""B08 — a checklist item that still says `running` after the page that started
the run is gone.

`_runAgentSolveJob` patches `agent_status: 'running'` onto the item the moment
the run starts, and the queue that produced it is memory only. So a reload — or
the tab closing mid-run, the `P6-09` scenario — leaves `running` on the item with
nothing live behind it. The render folded stored and live state together
(`agentLive || item.agent_status`) and told the user *"open the menu to stop it"*;
`_openTodoAgentMenu` gated its Stop entry on the live state alone and built no
such entry. Measured before the fix: menu entries were Open + Run again.

These run the real functions through `tests/harness/todo_stale_agent_run.js`
(`Law 20`). The tooltip reported is the one the render assigned; the menu entries
are read off the markup the menu built.

What is pinned, and why each is a defect if it breaks:

  * the tooltip promises a menu entry ONLY when the menu will contain one. The
    two are computed a thousand lines apart from different sources, which is how
    they came to disagree;
  * a stored `running` with a session id offers a real Stop. The server run is
    detached and usually still going, so the honest answer is to stop it, not to
    quietly clear the row (`Law 1`: the fix adds the control rather than removing
    the claim);
  * what the server says decides what the item then claims. A live run becomes
    `aborted`; a 404 becomes `stream_complete`; a request that never completed
    writes nothing at all, because "your run finished" must not be what a person
    is told when their network dropped;
  * a live run still cancels through `_cancelAgentSolve`, with no second stop
    path and no server round trip.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness" / "todo_stale_agent_run.js"
STYLE_CSS = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(*args) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── the tooltip and the menu have to agree ──────────────────────────────────

def test_a_stale_running_todo_promises_a_stop_and_the_menu_has_one():
    """The row's whole case: the sentence and the menu, from one item."""
    rendered = _run("render", "stale")
    menu = _run("menu", "stale")
    assert rendered["stopKind"] == "detached"
    assert rendered["promisesAMenuStop"] is True
    assert "cancel" in menu["acts"], (
        "the tooltip sends the user to this menu to stop the run; before B08 the "
        "entry was gated on the live queue and was not built"
    )
    assert "Stop this run" in menu["labels"]


def test_a_running_todo_with_no_session_stops_claiming_a_stop_exists():
    """Nothing to ask the server about, so the sentence offers nothing."""
    rendered = _run("render", "orphan")
    menu = _run("menu", "orphan")
    assert rendered["stopKind"] == "orphan"
    assert rendered["promisesAMenuStop"] is False
    assert "cancel" not in menu["acts"]
    assert rendered["title"] == "An agent run was started for this todo and never reported back"


def test_the_live_case_is_unchanged():
    """`Law 1`. A run this page owns keeps its badge, its forced visibility and
    its immediate cancel — no server round trip added to the path that never
    needed one."""
    rendered = _run("render", "live")
    menu = _run("menu", "live")
    assert rendered["stopKind"] == "live"
    assert "•••" in rendered["badge"]
    assert "opacity:.9" in rendered["styleAttr"], "the live badge still forces itself visible"
    assert menu["acts"] == ["open", "cancel", "run"]
    assert menu["labels"][1] == "Stop this run"
    assert menu["labels"][2] == "Running…"


@pytest.mark.parametrize("fixture, title", [
    ("done", "Agent stream finished for this todo"),
    ("idle", "Solve this todo with the agent"),
])
def test_the_other_stored_states_are_untouched(fixture, title):
    rendered = _run("render", fixture)
    assert rendered["title"] == title
    assert rendered["stopKind"] == ""
    assert _run("menu", fixture)["acts"].count("cancel") == 0


# ── what the server says decides what the item then claims ──────────────────

def test_stopping_a_detached_run_recovers_its_id_and_records_the_stop():
    out = _run("stop", "live")
    urls = [f["url"] for f in out["fetched"]]
    assert urls[0].endswith("/api/chat/resume/sess-9"), (
        "the run id died with the old page; /api/chat/stop fails closed without it"
    )
    assert urls[1].endswith("/api/chat/stop/sess-9")
    assert out["fetched"][1]["runId"] == "run-77", "the recovered id is what makes the stop land"
    assert out["fetched"][1]["method"] == "POST"
    assert out["stopped"] is True
    assert out["status"] == "aborted", "same status _runAgentSolveJob's own abort path writes"
    assert out["patched"] == 1 and out["rerendered"] == 1


def test_a_run_that_already_ended_stops_the_item_claiming_to_be_running():
    """404 from /api/chat/resume proves the stream is over, and nothing else."""
    out = _run("stop", "gone")
    assert out["stopped"] is False
    assert len(out["fetched"]) == 1, "no stop is posted when there is nothing to stop"
    assert out["status"] == "stream_complete"
    assert any("already finished" in t for t in out["toasts"])


def test_an_unreachable_server_writes_nothing_and_says_so():
    """A dropped request is not evidence the run ended. Replacing a stale claim
    with a false one is the same defect wearing the fix's clothes."""
    out = _run("stop", "throws")
    assert out["stopped"] is None
    assert out["status"] == "running", "the item keeps the only claim anyone can still check"
    assert out["patched"] == 0
    assert any("may still be going" in t for t in out["toasts"])
    assert not any("already finished" in t for t in out["toasts"])


# ── the state a person could not see ────────────────────────────────────────

def test_every_agent_state_the_render_emits_a_class_for_is_styled():
    """`notes.js` emitted `.is-agent-running` and `.is-agent-queued` from the day
    it was written and the stylesheet answered neither, so of the four agent
    states only the finished one was visible without hovering the row — the
    button base is `opacity: 0`. A live run forced itself visible inline and
    looked fine; a run persisted by a page that has since closed had nothing
    forcing it, which made the state a person most needs to act on the only one
    they could not see.

    The class set is obtained by RENDERING each status, not by reading the
    ternary that produces them, so a new state added to the render joins this
    assertion by itself (`Law 13`, `Law 20`). Only the stylesheet lookup is
    textual, because CSS has nothing to execute it with here."""
    emitted = {c for c in _run("classes").values() if c}
    assert emitted == {"is-agent-stream-complete", "is-agent-queued", "is-agent-running"}, (
        f"the render emits {sorted(emitted)}; update the stylesheet, not this set"
    )
    css = STYLE_CSS.read_text()
    for cls in sorted(emitted):
        assert f".note-checkbox-agent.{cls}" in css, (
            f"{cls} is emitted onto the button but the stylesheet has no rule for it, "
            f"so the button stays at the base opacity: 0"
        )
