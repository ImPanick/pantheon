# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1754` — the agent's own hand on the workstation desktop.

Panick, 2026-11-06: *"does it have a dedicated Agent mouse? (Fit to theme, of
course)"*; then "Overlay hand on the desktop" on the card. The live browser had
its hand (`P25-07`); the desktop had only the real X pointer, the person's too.

Pinned here:

  * **the feed** (`src/desktop_activity.py`) — an action is said "doing"
    before and "done"/"failed" after, with the points it acts on; a reader
    asks after a `seq` and hears only what changed; a `seq` from before a
    restart reads as 0; it keeps a bounded number, per account;
  * **the tool records only the agent's actions on the screen** — a click,
    a drag, a move reach the feed through the real dispatcher; a screenshot and
    a wait do not; a refusal (`busy`) is "failed"; the person's own input
    through the window's route is never in it;
  * **the route** — `GET /api/workstation/desktop/activity` answers the
    caller's own feed and nobody else's, and is refused to a person without
    the workstation;
  * **the window** — the real `workstationScreen.js` under node: the hand is
    placed on the drawn picture (and, live, inside the client's scaled, centred
    screen), glides to each step, says what it does, and hides while the
    person holds the screen.
"""
from __future__ import annotations

import json
import shutil

import pytest

from src import desktop_activity as DA
from src.workstation_client import account_for
from test_a_window_onto_the_workstation import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, ALSO, PLAIN, agent_clicks, app, as_user, auth, daemon, datadir, no_pantheon_browser,
    run, switch_on, tools_see, ws)
from test_the_workstation_screen_window_js import _PREAMBLE, _run  # noqa: E402
from test_the_workstation_screen_window_js import sandbox  # noqa: F401 — fixture

ROUTE = "/api/workstation/desktop/activity"


@pytest.fixture(autouse=True)
def fresh_feed():
    DA.forget()
    yield
    DA.forget()


# ── the feed ─────────────────────────────────────────────────────────────────

def test_an_action_is_said_before_and_marked_after_with_its_points():
    i = DA.begin("ann", "drag", "Drag from (1, 2) to (3, 4)",
                 {"x": 1, "y": 2, "to_x": 3, "to_y": 4, "text": "never", "mark": True})
    first = DA.since("ann", 0)
    [doing] = first["activity"]
    assert doing["phase"] == "doing" and doing["who"] == "agent" and doing["action"] == "drag"
    assert (doing["x"], doing["y"], doing["to_x"], doing["to_y"]) == (1, 2, 3, 4)
    assert "text" not in doing and "mark" not in doing and not any(k.startswith("_") for k in doing)
    DA.finish("ann", i, True)
    later = DA.since("ann", first["seq"])
    assert [e["phase"] for e in later["activity"]] == ["done"]
    assert DA.since("ann", later["seq"])["activity"] == []


def test_a_failed_action_is_said_failed_and_accounts_are_apart():
    i = DA.begin("ann", "click", "Click at (5, 5)", {"x": 5, "y": 5})
    DA.finish("ann", i, False)
    assert [e["phase"] for e in DA.since("ann")["activity"]] == ["failed"]
    assert DA.since("bob")["activity"] == []
    assert DA.begin("", "click", "x", {}) is None


def test_a_seq_from_before_a_restart_reads_as_zero_and_the_feed_is_bounded():
    for n in range(DA.KEPT + 5):
        DA.begin("ann", "move", f"Move {n}", {"x": n, "y": n})
    got = DA.since("ann", 10 ** 9)
    assert len(got["activity"]) == DA.KEPT
    assert got["activity"][-1]["label"] == f"Move {DA.KEPT + 4}"


# ── the tool records the agent's actions, and only those ─────────────────────

def test_the_agents_click_reaches_the_route_for_its_person_only(app, ws, tools_see):
    switch_on(app, ws)
    result = agent_clicks(ALLOWED, 40, 30)
    assert result["exit_code"] == 0, result
    mine = as_user(app, ALLOWED).get(ROUTE)
    assert mine.status_code == 200 and mine.headers.get("cache-control", "").startswith("no-store")
    [step] = mine.json()["activity"]
    assert step["action"] == "click" and step["phase"] == "done"
    assert (step["x"], step["y"]) == (40, 30) and step["label"] == "Click at (40, 30)"
    # Nobody else's screen shows it, and asking after it is nothing new.
    assert as_user(app, ALSO).get(ROUTE).json()["activity"] == []
    seq = mine.json()["seq"]
    assert as_user(app, ALLOWED).get(f"{ROUTE}?since={seq}").json()["activity"] == []


def test_a_look_and_the_persons_own_hand_are_not_drawn(app, ws, tools_see):
    import src.agent_tools  # noqa: F401
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
    switch_on(app, ws)
    for args in ({"action": "screenshot"}, {"action": "wait", "ms": 5}):
        run(execute_tool_block(ToolBlock("computer", json.dumps(args)), owner=ALLOWED,
                               security_context=NO_TOOL_SECURITY_CONTEXT))
    person = as_user(app, ALLOWED)
    assert person.post("/api/workstation/control", json={"holder": "person"}).status_code == 200
    assert person.post("/api/workstation/input", json={"action": "click", "x": 9, "y": 9}).status_code == 200
    assert person.get(ROUTE).json()["activity"] == []


def test_a_refused_action_is_drawn_as_failed(app, ws, tools_see):
    switch_on(app, ws)
    run(daemon(ws).control(account_for(ALLOWED), "person"))
    result = agent_clicks(ALLOWED, 7, 8)
    assert result["exit_code"] == 1 and result["workstation_error"] == "busy"
    [step] = as_user(app, ALLOWED).get(ROUTE).json()["activity"]
    assert step["phase"] == "failed" and (step["x"], step["y"]) == (7, 8)


def test_a_person_without_the_workstation_is_refused(app, ws):
    switch_on(app, ws)
    assert as_user(app, PLAIN).get(ROUTE).status_code == 403


# ── the window draws it ──────────────────────────────────────────────────────

pytestmark_js = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytestmark_js
def test_a_point_is_placed_on_the_picture_and_inside_the_live_client(sandbox):  # noqa: F811
    out = _run(sandbox, _PREAMBLE, """
        const box = { left: 100, top: 50, width: 640, height: 400 };
        const overlay = { left: 90, top: 40, width: 700, height: 500 };
        // A frame wider than the screen's shape: the client centres it.
        const wide = { left: 0, top: 0, width: 1000, height: 400 };
        out({ corner: mod.placeOnScreen(0, 0, box, overlay, 1280, 800),
              middle: mod.placeOnScreen(640, 400, box, overlay, 1280, 800),
              live: mod.placeOnScreen(1280, 800, wide, { left: 0, top: 0 }, 1280, 800, true),
              none: mod.placeOnScreen(1, 1, { left: 0, top: 0, width: 0, height: 0 }, overlay, 1280, 800) });
    """)
    assert out["corner"] == {"left": 10, "top": 10}
    assert out["middle"] == {"left": 330, "top": 210}
    assert out["live"] == {"left": 820, "top": 400}   # 180 px of margin either side
    assert out["none"] is None


@pytestmark_js
def test_the_hand_glides_says_what_it_does_and_steps_aside_for_the_person(sandbox):  # noqa: F811
    out = _run(sandbox, _PREAMBLE, """
        await open();
        const w = mod._test.win();
        w.agent.getBoundingClientRect = () => ({ left: 100, top: 50, width: 640, height: 400 });
        mod.applyDesktopActivity([
          { id: 1, seq: 3, who: 'agent', action: 'click', label: 'Click at (640, 400)', phase: 'doing',
            x: 640, y: 400 }]);
        const doing = mod._test.hand();
        mod.applyDesktopActivity([
          { id: 2, seq: 5, who: 'agent', action: 'drag', label: 'Drag from (0, 0) to (1280, 800)',
            phase: 'done', x: 0, y: 0, to_x: 1280, to_y: 800 },
          { id: 9, seq: 6, who: 'person', action: 'click', label: 'theirs', phase: 'done', x: 1, y: 1 }]);
        const dragged = mod._test.hand();
        await mod.takeOver();
        await settle(20);
        const held = mod._test.hand();
        out({ doing, dragged, held, phase: w.caption.dataset.phase });
    """)
    assert out["doing"]["shown"] is True and out["doing"]["at"] == {"x": 640, "y": 400}
    assert out["doing"]["caption"] == "Click at (640, 400)"
    assert out["doing"]["transform"].startswith("translate(")
    # A drag's hand ends where it let go; a person's step moves nothing.
    assert out["dragged"]["at"] == {"x": 1280, "y": 800} and out["dragged"]["since"] == 6
    assert out["dragged"]["caption"] == "Drag from (0, 0) to (1280, 800)"
    assert out["held"]["shown"] is False and out["held"]["caption"] is None
