# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-05` — a window onto the workstation: watch it, take it over, hand it back.

The routes the window calls, driven with `TestClient` against the real
workstation routes, the real settings route and a real `AuthManager`, talking
through the real client to the real daemon (`tests/helpers/workstation_daemon.py`
runs `workstation/agentd.py` with a `PictureScreen` that records every action
and changes colour with each one). The fixtures are `P20-02`'s, imported rather
than copied, so the two files describe one world.

What is pinned, and why each is a defect if it breaks:

  * **the screen is the caller's own** — there is no parameter naming whose,
    and one smuggled into the query or the body changes nothing;
  * **the privilege and the switch** — a person without `can_use_workstation`,
    the workstation off, nobody signed in and an API token are each refused,
    in `workstation_for`'s own sentence, and nothing is asked of the daemon;
  * **an unchanged frame is not sent twice** — `304`, through the protocol's
    own conditional; a frame is the picture and nothing else of the daemon's
    answer (never the token), in JPEG;
  * **the person's input reaches *their* display as the person** — every
    field the protocol defines, `holder` always `person` whatever the body
    says, validated by the daemon and refused in its words;
  * **take over makes the agent's input `busy`** — the real `computer` tool,
    through the real dispatcher, gets the daemon's sentence and does nothing;
    hand back frees it; one person taking over does not take another's;
  * **the agent cannot reach any of it through its generic bridge.**

Nothing here reads a source file (`Law 20`).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import core.auth
import src.agent_tools  # noqa: F401 — enters the tool-module cycle the right way round
import src.tool_security as tool_security
from src import workstation_access as wa
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, ALSO, PLAIN, app, as_user, auth, datadir, switch_on, ws)
from workstation import protocol as P

FRAME_KEYS = {"mime", "data_b64", "width", "height", "digest"}
ROUTES = (("GET", "/api/workstation/screen", None),
          ("POST", "/api/workstation/input", {"action": "click", "x": 1, "y": 1}),
          ("GET", "/api/workstation/control", None),
          ("POST", "/api/workstation/control", {"holder": "person"}))


def run(coro):
    return asyncio.run(coro)


def call(client, method, path, body=None):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body)


def daemon(ws):
    return WorkstationClient(ws.url, ws.token)


def digest_now(ws, owner) -> str:
    return run(daemon(ws).screenshot(account_for(owner)))["digest"]


def agent_clicks(owner, x=5, y=5):
    """The agent's own `computer` tool, through the real dispatcher."""
    return run(execute_tool_block(
        ToolBlock("computer", json.dumps({"action": "click", "x": x, "y": y})),
        owner=owner, security_context=NO_TOOL_SECURITY_CONTEXT))[1]


@pytest.fixture
def tools_see(monkeypatch, auth):
    """The tool layer asks `may_use` without the route's auth manager; point the
    one it builds at this file's, so the agent and the routes ask one question."""
    monkeypatch.setattr(core.auth, "AuthManager", lambda *a, **k: auth)
    monkeypatch.setattr(tool_security, "owner_is_admin_or_single_user",
                        lambda owner: owner == ADMIN)


# ── whose screen ─────────────────────────────────────────────────────────────

def test_a_frame_is_the_callers_own_screen_and_nothing_else(app, ws):
    switch_on(app, ws)
    # Someone else's screen, made to look different from a fresh one.
    for i in range(3):
        run(daemon(ws).input(account_for(ALSO), "click", x=i, y=i))
    theirs = digest_now(ws, ALSO)

    r = as_user(app, ALLOWED).get("/api/workstation/screen")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    frame = r.json()
    assert set(frame) == FRAME_KEYS, "a frame is the picture and nothing else of the answer"
    raw = base64.b64decode(frame["data_b64"])
    assert hashlib.sha256(raw).hexdigest()[:16] == frame["digest"]
    assert (frame["width"], frame["height"]) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    assert frame["mime"] == "image/png"   # `PictureScreen` labels both formats PNG
    assert frame["digest"] == digest_now(ws, ALLOWED)
    assert frame["digest"] != theirs
    assert ws.token not in r.text


@pytest.mark.parametrize("smuggled", ["account", "owner", "user"])
def test_naming_another_account_changes_nothing(app, ws, smuggled):
    switch_on(app, ws)
    for i in range(2):
        run(daemon(ws).input(account_for(ALSO), "click", x=i, y=i))
    allowed = as_user(app, ALLOWED)
    r = allowed.get(f"/api/workstation/screen?{smuggled}={account_for(ALSO)}")
    assert r.json()["digest"] == digest_now(ws, ALLOWED) != digest_now(ws, ALSO)
    allowed.post("/api/workstation/input",
                 json={"action": "click", "x": 7, "y": 8, smuggled: account_for(ALSO)})
    assert ws.screen(account_for(ALLOWED)).actions == [{"action": "click", "x": 7, "y": 8}]
    assert len(ws.screen(account_for(ALSO)).actions) == 2
    allowed.post("/api/workstation/control", json={"holder": "person", smuggled: account_for(ALSO)})
    assert run(daemon(ws).ensure(account_for(ALSO)))["holder"] == "agent"
    assert run(daemon(ws).ensure(account_for(ALLOWED)))["holder"] == "person"


def test_the_window_asks_for_jpeg(app, ws):
    switch_on(app, ws)
    as_user(app, ALLOWED).get("/api/workstation/screen")   # makes the screen
    screen = ws.screen(account_for(ALLOWED))
    asked = []
    real = screen.grab
    screen.grab = lambda fmt: (asked.append(fmt), real(fmt))[1]
    assert as_user(app, ALLOWED).get("/api/workstation/screen").status_code == 200
    assert asked == ["jpeg"]


# ── an unchanged frame is not sent again ─────────────────────────────────────

def test_an_unchanged_screen_is_a_304_and_a_changed_one_is_the_new_frame(app, ws):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    first = allowed.get("/api/workstation/screen").json()["digest"]
    same = allowed.get(f"/api/workstation/screen?if_none_match={first}")
    assert same.status_code == 304 and same.content == b""
    allowed.post("/api/workstation/input", json={"action": "click", "x": 10, "y": 10})
    changed = allowed.get(f"/api/workstation/screen?if_none_match={first}")
    assert changed.status_code == 200
    assert changed.json()["digest"] != first
    assert changed.json()["digest"] == digest_now(ws, ALLOWED)


@pytest.mark.parametrize("held", ["", "nothing", "../../v1/health", "&format=png",
                                  "0123456789ABCDEF", "0123456789abcdef0"])
def test_a_conditional_that_is_not_this_frames_digest_gets_the_frame(app, ws, held):
    """Whatever the string, it reaches the daemon as one query value and is
    only compared with the digest — it cannot name another route or format."""
    switch_on(app, ws)
    r = as_user(app, ALLOWED).get("/api/workstation/screen", params={"if_none_match": held})
    assert r.status_code == 200 and set(r.json()) == FRAME_KEYS


# ── who may ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ROUTES)
def test_a_person_without_the_privilege_is_refused_and_nothing_is_asked(app, ws, method, path,
                                                                         body):
    switch_on(app, ws)
    r = call(as_user(app, PLAIN), method, path, body)
    assert r.status_code == 403 and r.json()["detail"] == wa.NOT_PERMITTED_SENTENCE
    assert account_for(PLAIN) not in ws.system.accounts()
    assert ws.system._screens == {}, "a display was asked for on their behalf"


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_off_is_said_and_nothing_is_called(app, ws, method, path, body):
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_url": ws.url, "workstation_token": ws.token})
    r = call(as_user(app, ALLOWED), method, path, body)
    assert r.status_code == 409 and r.json()["detail"] == wa.OFF_SENTENCE
    assert ws.system.accounts() == []


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_an_api_token_and_nobody_are_refused(app, ws, method, path, body):
    """`B70`: a token resolves to the admin who minted it, and is not them."""
    switch_on(app, ws)
    bearer = TestClient(app, headers={"X-Test-Bearer": ADMIN})
    assert call(bearer, method, path, body).status_code == 403
    assert call(as_user(app, None), method, path, body).status_code == 401
    assert ws.system.accounts() == []


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_down_is_said_in_the_clients_sentence(app, method, path, body):
    as_user(app, ADMIN).post("/api/auth/settings", json={
        "workstation_enabled": True, "workstation_url": "http://127.0.0.1:9",
        "workstation_token": "pws_x"})
    r = call(as_user(app, ALLOWED), method, path, body)
    assert r.status_code == 503 and "did not answer" in r.json()["detail"]


def test_a_screen_the_workstation_cannot_show_is_said_in_its_words(app, ws):
    switch_on(app, ws)
    as_user(app, ALLOWED).get("/api/workstation/screen")
    ws.screen(account_for(ALLOWED)).fail_with = "The display stopped. Reset to start it again."
    r = as_user(app, ALLOWED).get("/api/workstation/screen")
    assert r.status_code == 503
    assert r.json()["detail"] == "The display stopped. Reset to start it again."


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", None])
def test_a_picture_that_is_not_a_screen_is_not_passed_on(app, ws, mime):
    """The window builds a `data:` URL from the type the daemon names, so only
    the two picture types the protocol has pass."""
    switch_on(app, ws)
    as_user(app, ALLOWED).get("/api/workstation/screen")
    ws.screen(account_for(ALLOWED)).grab = lambda fmt: (b"<script>x</script>", mime)
    r = as_user(app, ALLOWED).get("/api/workstation/screen")
    assert r.status_code == 502 and "cannot show" in r.json()["detail"]
    assert "<script>" not in r.text


# ── the person's mouse and keyboard ──────────────────────────────────────────

INPUT_CASES = [
    ({"action": "click", "x": 640, "y": 400}, {"x": 640, "y": 400}),
    ({"action": "double_click", "x": 1, "y": 2}, {"x": 1, "y": 2}),
    ({"action": "triple_click", "x": 3, "y": 4}, {"x": 3, "y": 4}),
    ({"action": "right_click", "x": 1279, "y": 799}, {"x": 1279, "y": 799}),
    ({"action": "middle_click", "x": 0, "y": 0}, {"x": 0, "y": 0}),
    ({"action": "move", "x": 10, "y": 11}, {"x": 10, "y": 11}),
    ({"action": "drag", "x": 1, "y": 2, "to_x": 300, "to_y": 400},
     {"x": 1, "y": 2, "to_x": 300, "to_y": 400}),
    ({"action": "mouse_down", "x": 5, "y": 6}, {"x": 5, "y": 6}),
    ({"action": "mouse_up"}, {}),
    ({"action": "scroll", "x": 10, "y": 10, "dy": 3}, {"x": 10, "y": 10, "dx": 0, "dy": 3}),
    ({"action": "type", "text": "hello, world"}, {"text": "hello, world"}),
    ({"action": "key", "keys": "ctrl+shift+t"}, {"keys": "ctrl+shift+t"}),
]


@pytest.mark.parametrize("body,fields", INPUT_CASES, ids=[c[0]["action"] for c in INPUT_CASES])
def test_each_input_reaches_the_persons_own_display(app, ws, body, fields):
    switch_on(app, ws)
    r = as_user(app, ALLOWED).post("/api/workstation/input", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "action": body["action"]}
    assert ws.screen(account_for(ALLOWED)).actions == [{"action": body["action"], **fields}]
    assert account_for(ALSO) not in ws.system._screens


def test_the_cases_cover_every_action_the_window_can_send():
    assert {c[0]["action"] for c in INPUT_CASES} == set(P.INPUT_ACTIONS) - {"wait"}


def test_the_persons_input_is_the_persons_whatever_the_body_says(app, ws):
    """Held by the person, input from the agent is `busy`. A body claiming to be
    the agent still arrives as the person — and one asking for a screenshot
    after gets none: the route speaks for the keyboard, nothing else."""
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    assert allowed.post("/api/workstation/control", json={"holder": "person"}).status_code == 200
    r = allowed.post("/api/workstation/input", json={
        "action": "click", "x": 9, "y": 9, "holder": "agent", "screenshot_after": True})
    assert r.status_code == 200, r.text
    assert "screenshot" not in r.json()
    assert ws.screen(account_for(ALLOWED)).actions == [{"action": "click", "x": 9, "y": 9}]


@pytest.mark.parametrize("body,words", [
    ({"action": "click", "x": 5000, "y": 1}, "is a pixel from 0 to 1279"),
    ({"action": "click", "x": "5", "y": 1}, "is a pixel from 0 to 1279"),
    ({"action": "scroll", "x": 1, "y": 1, "dy": 999}, "wheel clicks"),
    ({"action": "key", "keys": "rm -rf /"}, "xdotool key syntax"),
    ({"action": "type", "text": ""}, "needs “text”"),
    ({"action": "explode"}, "“action” is one of"),
    ({}, "“action” is one of"),
])
def test_a_bad_input_is_refused_in_the_daemons_words_and_nothing_moves(app, ws, body, words):
    switch_on(app, ws)
    r = as_user(app, ALLOWED).post("/api/workstation/input", json=body)
    assert r.status_code == 400 and words in r.json()["detail"], r.text
    screen = ws.system._screens.get(account_for(ALLOWED))
    assert screen is None or screen.actions == []


def test_a_body_that_is_not_an_object_is_refused(app, ws):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    for path in ("/api/workstation/input", "/api/workstation/control"):
        r = allowed.post(path, content=b"[1, 2]", headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and "JSON object" in r.json()["detail"]


# ── take over, hand back ─────────────────────────────────────────────────────

def test_take_over_makes_the_agents_input_busy_and_hand_back_frees_it(app, ws, tools_see):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    assert allowed.get("/api/workstation/control").json() == {
        "holder": "agent", "sentence": "The agent has the mouse and keyboard. You are watching."}
    assert agent_clicks(ALLOWED)["exit_code"] == 0, "the agent could not click before"

    taken = allowed.post("/api/workstation/control", json={"holder": "person"})
    assert taken.status_code == 200
    assert taken.json()["holder"] == "person" and taken.json()["since"]
    assert "hand them back" in taken.json()["sentence"]
    assert allowed.get("/api/workstation/control").json()["holder"] == "person"

    refused = agent_clicks(ALLOWED, 50, 50)
    assert refused["workstation_error"] == "busy"
    assert "A person has taken over" in refused["error"]
    with pytest.raises(WorkstationError) as busy:
        run(daemon(ws).input(account_for(ALLOWED), "click", x=1, y=1))
    assert busy.value.code == "busy"
    # The person keeps working while the agent waits.
    assert allowed.post("/api/workstation/input",
                        json={"action": "type", "text": "mine"}).status_code == 200
    assert ws.screen(account_for(ALLOWED)).actions[-1] == {"action": "type", "text": "mine"}
    assert {"action": "click", "x": 50, "y": 50} not in ws.screen(account_for(ALLOWED)).actions

    back = allowed.post("/api/workstation/control", json={"holder": "agent"})
    assert back.status_code == 200 and back.json()["holder"] == "agent"
    assert back.json()["sentence"] == "The agent has the mouse and keyboard again."
    assert allowed.get("/api/workstation/control").json()["holder"] == "agent"
    assert agent_clicks(ALLOWED, 60, 60)["exit_code"] == 0
    assert ws.screen(account_for(ALLOWED)).actions[-1] == {"action": "click", "x": 60, "y": 60}


def test_taking_over_ones_own_screen_leaves_anothers_to_its_agent(app, ws, tools_see):
    switch_on(app, ws)
    as_user(app, ALLOWED).post("/api/workstation/control", json={"holder": "person"})
    assert as_user(app, ALSO).get("/api/workstation/control").json()["holder"] == "agent"
    assert agent_clicks(ALSO)["exit_code"] == 0
    assert agent_clicks(ALLOWED)["workstation_error"] == "busy"


@pytest.mark.parametrize("body", [{"holder": "root"}, {"holder": ""}, {}, {"holder": ["person"]}])
def test_a_holder_that_is_not_one_is_refused_and_nothing_changes(app, ws, body):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    r = allowed.post("/api/workstation/control", json=body)
    assert r.status_code == 400 and "take over" in r.json()["detail"]
    assert allowed.get("/api/workstation/control").json()["holder"] == "agent"


def test_reset_to_clean_hands_the_screen_back(app, ws):
    """The window's *Reset to clean* is `P20-02`'s reset, reused: the daemon
    forgets who held the screen with everything else."""
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    allowed.post("/api/workstation/control", json={"holder": "person"})
    assert allowed.post("/api/workstation/reset").status_code == 200
    assert allowed.get("/api/workstation/control").json()["holder"] == "agent"


def test_the_token_reaches_no_answer(app, ws):
    switch_on(app, ws)
    allowed = as_user(app, ALLOWED)
    texts = [allowed.get("/api/workstation/screen").text,
             allowed.post("/api/workstation/input", json={"action": "click", "x": 1, "y": 1}).text,
             allowed.get("/api/workstation/control").text,
             allowed.post("/api/workstation/control", json={"holder": "person"}).text,
             allowed.post("/api/workstation/input", json={"action": "click", "x": -1, "y": 1}).text]
    assert all(ws.token not in t for t in texts)


# ── the agent's bridge ───────────────────────────────────────────────────────

@pytest.mark.parametrize("path,body", [
    ("/api/workstation/input", {"action": "click", "x": 1, "y": 1}),
    ("/api/workstation/control", {"holder": "person"}),
    ("/api/workstation/control", {"holder": "agent"}),
])
def test_the_agents_bridge_cannot_take_over_or_type_as_the_person(monkeypatch, path, body):
    """Typing through the person's route would step past the agent's own
    `busy`; taking over would lock the person out of their own screen."""
    import httpx

    from src.tools.system import do_app_api

    def _no_request(*a, **k):
        raise AssertionError("a request was made")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _no_request)
    answer = run(do_app_api(json.dumps({"action": "call", "method": "POST", "path": path,
                                        "body": body}), owner=ADMIN))
    assert answer["exit_code"] == 1
    assert "taking over its screen or typing into it" in answer["error"]
    assert "`computer` tool" in answer["error"]
