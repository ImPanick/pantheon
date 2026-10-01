# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-04` — the agent sees the workstation's screen and works its mouse and
keyboard.

Every case drives the shipped code against the real daemon
(`tests/helpers/workstation_daemon.py` runs `workstation/agentd.py` with a
`PictureScreen` that records each action and changes colour for each one):

  * the `computer` tool, through the real dispatcher (`execute_tool_block`),
    as a named person: every protocol input action reaches **that person's**
    display with the fields it was given, and answers with a screenshot taken
    after it — a different picture from the one before;
  * a screenshot is the screen as it is and sends nothing;
  * a point off the screen, a scroll too far, a wait too long and a key string
    that is not xdotool syntax are refused with the daemon's own sentence, and
    nothing reaches the display;
  * while a person holds the screen the tool says so, says nothing was done and
    what to do instead — and can still look;
  * the workstation switched off, without an address, or a person without the
    grant: the tool refuses with `workstation_for`'s own sentence;
  * the turn is offered the tool exactly when `workstation_for` would answer —
    as a function schema, and as a fenced section for a model without native
    tools — and never to a run driven by an API token;
  * the approval class, driven through the run's own gate: a click is
    `execute_code` + `network_egress`, a screenshot only looks, and once a
    screenshot has put untrusted content in the run a click asks while a
    screenshot does not.

Nothing here reads a source file (`Law 20`).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

import core.auth
import src.agent_loop as agent_loop
import src.agent_tools  # noqa: F401 — enters the tool-module cycle the right way round
import src.tool_security as tool_security
import src.workstation_client as wc
from src.agent_tools import ToolBlock
from src.agent_tools.computer_tools import BUSY_ADVICE
from src.tool_capabilities import (
    ToolEffect,
    ToolRunSecurityContext,
    capabilities_for_action,
)
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.workstation_access import workstation_for
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P

PERMITTED = "ann"     # granted `can_use_workstation`
REFUSED = "bob"       # not granted
ADMIN = "root-admin"


def run(coro):
    return asyncio.run(coro)


class _Auth:
    """`core.auth.AuthManager` for two people, so the real `may_use` and the
    real `resolve_privilege` decide."""

    PRIVILEGES = {PERMITTED: {"can_use_workstation": True}, REFUSED: {},
                  # `P20-02`'s `may_use` asks `get_privileges` for admins too
                  # (they hold every declared privilege), not a separate check.
                  ADMIN: {"can_use_workstation": True}}
    # Auth set up, so the pre-setup refusal does not answer for everyone.
    is_configured = True

    def get_privileges(self, owner):
        return dict(self.PRIVILEGES.get(owner, {}))


def configure(monkeypatch, station, **overrides):
    """Point Pantheon at `station` the way an admin's settings would."""
    settings = {"workstation_enabled": True, "workstation_url": station.url,
                "workstation_token": station.token}
    settings.update(overrides)
    monkeypatch.setattr(wc, "_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.setattr(tool_security, "owner_is_admin_or_single_user",
                        lambda owner: owner == ADMIN)
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    return settings


@pytest.fixture
def station(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws)
        yield ws


def call(args, owner=PERMITTED):
    content = args if isinstance(args, str) else json.dumps(args)
    return run(execute_tool_block(ToolBlock("computer", content), owner=owner,
                                  security_context=NO_TOOL_SECURITY_CONTEXT))


def digest_of(result) -> str:
    [image] = result["images"]
    assert image["mimeType"] == "image/png"
    raw = base64.b64decode(image["data"])
    assert raw.startswith(b"\x89PNG"), "the picture is the screen's PNG"
    return hashlib.sha256(raw).hexdigest()[:16]


def screen_digest(station, owner=PERMITTED) -> str:
    return run(WorkstationClient(station.url, station.token).screenshot(account_for(owner)))["digest"]


# ── every action reaches the display, and the screen after it comes back ─────

ACTION_CASES = [
    ({"action": "click", "x": 640, "y": 400}, {"x": 640, "y": 400}, "click at (640, 400)"),
    ({"action": "double_click", "x": 1, "y": 2}, {"x": 1, "y": 2}, "double click at (1, 2)"),
    ({"action": "triple_click", "x": 3, "y": 4}, {"x": 3, "y": 4}, "triple click at (3, 4)"),
    ({"action": "right_click", "x": 1279, "y": 799}, {"x": 1279, "y": 799},
     "right click at (1279, 799)"),
    ({"action": "middle_click", "x": 0, "y": 0}, {"x": 0, "y": 0}, "middle click at (0, 0)"),
    ({"action": "move", "x": 10, "y": 11}, {"x": 10, "y": 11}, "move to (10, 11)"),
    ({"action": "drag", "x": 1, "y": 2, "to_x": 300, "to_y": 400},
     {"x": 1, "y": 2, "to_x": 300, "to_y": 400}, "drag from (1, 2) to (300, 400)"),
    ({"action": "mouse_down"}, {}, "mouse down"),
    ({"action": "mouse_up", "x": 5, "y": 6}, {"x": 5, "y": 6}, "mouse up at (5, 6)"),
    ({"action": "scroll", "x": 10, "y": 10, "dy": -2}, {"x": 10, "y": 10, "dx": 0, "dy": -2},
     "scroll up 2 at (10, 10)"),
    ({"action": "type", "text": "hello world"}, {"text": "hello world"}, "type “hello world”"),
    ({"action": "key", "keys": "ctrl+l"}, {"keys": "ctrl+l"}, "key ctrl+l"),
    ({"action": "wait", "ms": 5}, None, "wait 5 ms"),
]


def test_the_cases_cover_every_action_the_protocol_has():
    """The tool offers the protocol's actions; the cases below drive each one."""
    assert {case[0]["action"] for case in ACTION_CASES} == set(P.INPUT_ACTIONS)


@pytest.mark.parametrize("args, sent, words", ACTION_CASES,
                         ids=[case[0]["action"] for case in ACTION_CASES])
def test_each_action_reaches_the_persons_display_and_shows_the_screen_after_it(
        station, args, sent, words):
    before = screen_digest(station)
    desc, result = call(args)
    assert result["exit_code"] == 0, result
    assert desc == f"computer: {words}"
    assert result["screenshot_caption"] == f"Screen after {words}"
    screen = station.screen(account_for(PERMITTED))
    if sent is None:
        # A wait moves nothing; it still answers with the screen after it.
        assert screen.actions == []
        assert digest_of(result) == before
    else:
        assert screen.actions == [dict({"action": args["action"]}, **sent)]
        assert digest_of(result) != before, "the screenshot was taken after the action"
    # The person's own display, and nobody else's.
    assert station.screen(account_for(None)).actions == []


def test_a_screenshot_is_the_screen_as_it_is_and_touches_nothing(station):
    desc, result = call({"action": "screenshot"})
    assert result["exit_code"] == 0 and desc == "computer: screenshot"
    assert digest_of(result) == screen_digest(station)
    assert station.screen(account_for(PERMITTED)).actions == []
    assert f"{P.SCREEN_WIDTH}×{P.SCREEN_HEIGHT}" in result["output"]


def test_the_spellings_another_computer_use_tool_taught_are_understood(station):
    call({"action": "left_click", "coordinate": [7, 8]})
    call({"action": "scroll", "coordinate": [9, 9], "scroll_direction": "down", "scroll_amount": 4})
    call({"action": "click", "x": "12", "y": 13.0})
    assert station.screen(account_for(PERMITTED)).actions == [
        {"action": "click", "x": 7, "y": 8},
        {"action": "scroll", "x": 9, "y": 9, "dx": 0, "dy": 4},
        {"action": "click", "x": 12, "y": 13},
    ]


# ── refused, in the daemon's words, with nothing sent ────────────────────────

@pytest.mark.parametrize("args, words", [
    ({"action": "click", "x": P.SCREEN_WIDTH, "y": 0}, f"from 0 to {P.SCREEN_WIDTH - 1}"),
    ({"action": "click", "x": 0, "y": P.SCREEN_HEIGHT}, f"from 0 to {P.SCREEN_HEIGHT - 1}"),
    ({"action": "move", "x": -1, "y": 5}, "pixel"),
    ({"action": "drag", "x": 1, "y": 1, "to_x": 5000, "to_y": 1}, "pixel"),
    ({"action": "click"}, "needs"),
    ({"action": "scroll", "x": 1, "y": 1, "dy": 51}, "-50 to 50"),
    ({"action": "wait", "ms": P.MAX_WAIT_MS + 1}, str(P.MAX_WAIT_MS)),
    ({"action": "key", "keys": "ctrl+l; rm -rf /"}, "xdotool"),
    ({"action": "type", "text": "x" * (P.MAX_TYPE_CHARS + 1)}, "characters"),
], ids=["x-off", "y-off", "negative", "drag-off", "no-point", "scroll", "wait", "keys", "type"])
def test_an_action_outside_the_bounds_is_refused_and_nothing_reaches_the_screen(
        station, args, words):
    _desc, result = call(args)
    assert result["exit_code"] == 1 and "images" not in result
    assert result["workstation_error"] in ("bad_request", "too_large")
    assert words in result["error"]
    assert station.screen(account_for(PERMITTED)).actions == []


def test_an_action_the_tool_does_not_know_is_named_with_the_ones_it_does(station):
    _desc, result = call({"action": "teleport"})
    assert result["exit_code"] == 1
    assert "teleport" in result["error"] and "double_click" in result["error"]
    assert station.screen(account_for(PERMITTED)).actions == []


# ── a person has the screen ──────────────────────────────────────────────────

def test_while_a_person_holds_the_screen_the_agent_is_told_what_to_do(station):
    client = WorkstationClient(station.url, station.token)
    run(client.control(account_for(PERMITTED), "person"))
    _desc, result = call({"action": "click", "x": 5, "y": 5})
    assert result["exit_code"] == 1 and result["workstation_error"] == "busy"
    assert "taken over" in result["error"]
    assert result["error"].endswith(BUSY_ADVICE)
    assert "Nothing was done" in result["error"] and "ask_user" in result["error"]
    assert station.screen(account_for(PERMITTED)).actions == []
    # It can still look while it waits.
    _desc, shot = call({"action": "screenshot"})
    assert shot["exit_code"] == 0 and shot["images"]
    run(client.control(account_for(PERMITTED), "agent"))
    _desc, again = call({"action": "click", "x": 5, "y": 5})
    assert again["exit_code"] == 0
    assert station.screen(account_for(PERMITTED)).actions == [{"action": "click", "x": 5, "y": 5}]


# ── off, unconfigured, not permitted: the access module's own sentence ───────

def _refusal(owner):
    with pytest.raises(WorkstationError) as caught:
        workstation_for(owner)
    return caught.value


@pytest.mark.parametrize("case", ["off", "unconfigured", "not_permitted"])
def test_a_person_the_workstation_would_not_answer_is_told_why(tmp_path, monkeypatch, case):
    with running_workstation(tmp_path) as ws:
        owner = PERMITTED
        if case == "off":
            configure(monkeypatch, ws, workstation_enabled=False)
        elif case == "unconfigured":
            configure(monkeypatch, ws, workstation_url="")
        else:
            configure(monkeypatch, ws)
            owner = REFUSED
        expected = _refusal(owner)
        assert expected.code == case
        _desc, result = call({"action": "click", "x": 1, "y": 1}, owner=owner)
        assert result["error"] == expected.message
        assert result["workstation_error"] == case and result["exit_code"] == 1
        assert ws.screen(account_for(owner)).actions == []


# ── offered to the turn exactly when the workstation would answer ────────────

def _offered(monkeypatch, *, model="gpt-4o", owner=PERMITTED, delegated=False):
    """What round one of the real agent loop offers the model: the function
    schemas it sends, and the system prompt."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    seen = {}

    async def fake_stream(candidates, messages, **kwargs):
        request = await kwargs["candidate_request_factory"](0, *candidates[0])
        seen["tools"] = [t["function"]["name"] for t in (request["kwargs"].get("tools") or [])]
        seen["prompt"] = request["messages"][0]["content"]
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", model, [{"role": "user", "content": "open the page"}],
            max_rounds=1, owner=owner, relevant_tools={"computer", "web_search"},
            delegated_credential=delegated)]

    run(drain())
    return seen


def test_a_person_the_workstation_answers_is_offered_the_tool(station, monkeypatch):
    offered = _offered(monkeypatch)
    assert "computer" in offered["tools"]


def test_a_model_without_native_tools_is_shown_the_fenced_form(station, monkeypatch):
    offered = _offered(monkeypatch, model="small-local-model")
    assert "```computer" in offered["prompt"]
    assert f"{P.SCREEN_WIDTH}×{P.SCREEN_HEIGHT}" in offered["prompt"]


@pytest.mark.parametrize("case", ["off", "not_permitted", "token"])
def test_a_turn_the_workstation_would_not_answer_is_not_offered_it(
        tmp_path, monkeypatch, case):
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws, **({"workstation_enabled": False} if case == "off" else {}))
        owner = REFUSED if case == "not_permitted" else PERMITTED
        offered = _offered(monkeypatch, owner=owner, delegated=case == "token")
        assert "computer" not in offered["tools"], offered["tools"]
        assert "web_search" in offered["tools"], "the rest of the turn's tools are untouched"
        fenced = _offered(monkeypatch, model="small-local-model", owner=owner,
                          delegated=case == "token")
        assert "```computer" not in fenced["prompt"]


# ── the approval class, through the run's own gate ───────────────────────────

CLICK = json.dumps({"action": "click", "x": 1, "y": 1})
LOOK = json.dumps({"action": "screenshot"})


def test_a_click_runs_code_and_reaches_the_network_and_a_screenshot_only_looks():
    click = capabilities_for_action("computer", CLICK)
    assert click.effects == {ToolEffect.EXECUTE_CODE, ToolEffect.NETWORK_EGRESS}
    assert ToolEffect.DESTRUCTIVE not in click.effects, "a separate box with Reset, not the host"
    for looking in (LOOK, json.dumps({"action": "wait", "ms": 10})):
        assert capabilities_for_action("computer", looking).effects == {ToolEffect.READ_WORKSPACE}
    assert click.result_integrity.value == "external_untrusted"
    assert capabilities_for_action("computer", LOOK).result_integrity.value == "external_untrusted"


def test_once_the_screen_has_been_read_a_click_asks_and_a_look_does_not(station):
    gate = ToolRunSecurityContext()
    assert gate.decision_for("computer", CLICK).allowed, "a clean run clicks unasked"
    _desc, shot = call({"action": "screenshot"})
    gate.observe_tool_result("computer", shot, LOOK)
    assert gate.external_untrusted_context_seen, "what the screen shows is untrusted content"
    asked = gate.decision_for("computer", CLICK)
    assert not asked.allowed
    assert set(asked.tripped_effects) == {"execute_code", "network_egress"}
    assert gate.decision_for("computer", LOOK).allowed, "looking never asks"


# ── the operator's own words switch it off ───────────────────────────────────

@pytest.mark.parametrize("words", ["computer", "desktop", "computer_use"])
def test_an_operator_can_switch_the_desktop_off_in_their_own_words(monkeypatch, words):
    """`manage_settings disable_tool` takes friendly names; the desktop answers
    to the ones a person would use for it, and lands in the global list the
    chat route reads on every request."""
    import sys
    import types

    import src.settings as settings_mod
    from src.tool_implementations import do_manage_settings

    db_mod = types.ModuleType("core.database")

    class _Db:
        def close(self):
            pass

    db_mod.SessionLocal = lambda: _Db()
    monkeypatch.setitem(sys.modules, "core.database", db_mod)
    store = {}
    monkeypatch.setattr(settings_mod, "load_settings", lambda: dict(store))
    monkeypatch.setattr(settings_mod, "save_settings",
                        lambda s: (store.clear(), store.update(s)))

    result = run(do_manage_settings(json.dumps({"action": "disable_tool", "tool": words}),
                                    owner="admin"))
    assert result["exit_code"] == 0, result
    assert store["disabled_tools"] == ["computer"]


def test_plan_mode_keeps_the_desktop_out_even_without_the_schema_list(monkeypatch):
    """Plan mode is an allowlist applied as a denylist, and its backstop
    (`_PLAN_MODE_KNOWN_MUTATORS`) is what still blocks a mutator when the
    schema list cannot be read (`P3-17`'s import-cycle case). A click on a
    desktop can do anything a shell can, so it is on that list."""
    import sys

    monkeypatch.setitem(sys.modules, "src.tool_schemas", None)
    assert "computer" in tool_security.plan_mode_disabled_tools()
