# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B986` — with the workstation on, a message naming a folder there binds it.

On Pantheon's machine a chat message naming a path ("fix /srv/app/main.py")
binds its folder as the turn's workspace and makes the turn an agent turn
(`chat_routes._resolve_workspace_from_message_path`, admins only — it probes this
machine). `B968` switched that off for a person whose tools run in their
workstation, since a folder here is one their tools never reach — and nothing
did the same for a path in their workstation home. Now the chat asks the
workstation (`_resolve_message_path_workspace` → `workstation_tools.
workspace_named`): the folder named, or a named file's folder, vetted exactly as
the posted workspace is (`vet_workspace`: a folder in the person's home, not a
sensitive one) and bound for that turn — for anyone the workstation answers
for, because what it binds is a folder of their own home, the picker's reach.

Driven, not read (`Law 20`): the resolver against the real daemon
(`tests/helpers/workstation_daemon.py`, `P20-03`'s people and settings), and the
real chat route (`_chat_stream_endpoint`, as `B968`'s chat case drives it) for a
non-admin whose message names a file in her workstation home.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _USERS, _home, _on, people, settings, ws)


def _request(user):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)),
                           state=SimpleNamespace(current_user=user), headers={})


def _bind(message, who="ann"):
    import routes.chat_routes as cr
    return asyncio.run(cr._resolve_message_path_workspace(_request(who), message))


@pytest.fixture
def home(ws):
    h = _home(ws, "ann")
    for d in ("proj/src", ".ssh"):
        (h / d).mkdir(parents=True, exist_ok=True)
    (h / "proj" / "app.py").write_text("print('hi')\n")
    (h / ".ssh" / "config").write_text("Host *\n")
    return h


@pytest.mark.parametrize("message, folder", [
    ("fix ~/proj/app.py please", "proj"),                       # a file: its folder
    ("open ~/proj/src", "proj/src"),                            # a folder: itself
    ("fix {home}/proj/app.py", "proj"),                         # the absolute spelling
    ("debug {home}/proj/src/.", "proj/src"),
    ("run the tests in ~/proj.", "proj"),                       # trailing punctuation
])
def test_a_path_in_the_workstation_home_binds_its_folder(ws, settings, people, home, message,
                                                         folder):
    _on(settings, ws)
    assert _bind(message.format(home=home)) == (str(home / folder), "")


@pytest.mark.parametrize("message", [
    "fix ~/.ssh/config",              # sensitive: never bound, as the picker never offers it
    "open ~/.ssh",
    "fix /etc/passwd",                # outside the home
    "fix ~/nothing/here.py",          # nothing there
    "hello ~/proj",                   # no task named: nothing is bound, as here
    "fix {boss}/x.py",                # somebody else's home
])
def test_what_is_not_a_folder_of_the_home_binds_nothing(ws, settings, people, home, message):
    _on(settings, ws)
    boss = _home(ws, "boss")
    boss.mkdir(parents=True, exist_ok=True)
    (boss / "x.py").write_text("")
    assert _bind(message.format(boss=boss)) == ("", "")


def test_with_sudo_on_it_still_binds_only_a_folder_of_the_home(ws, settings, people, home):
    _on(settings, ws, workstation_sudo=True)
    ws.system.set_sudo(True)          # the daemon resolves /etc now; the home rule does not move
    assert _bind("fix /etc/passwd") == ("", "")
    assert _bind("fix ~/proj/app.py") == (str(home / "proj"), "")


def test_anyone_the_workstation_answers_for_and_nobody_else(ws, settings, people, home):
    _on(settings, ws)
    assert _bind("fix ~/proj/app.py", who="ann") == (str(home / "proj"), "")   # not an admin
    # Not granted: the host rule, which refuses a non-admin — nothing bound.
    assert _bind(f"fix {home}/proj/app.py", who="bob") == ("", "")


def test_a_workstation_that_does_not_answer_binds_nothing(ws, settings, people, home):
    _on(settings, ws)
    settings["workstation_url"] = "http://127.0.0.1:9"
    assert _bind("fix ~/proj/app.py") == ("", "")


def test_with_the_workstation_off_the_host_rule_is_as_it_was(ws, settings, people, home):
    """`Law 1`: an admin's path on this machine binds; a non-admin's binds nothing."""
    assert _bind(f"fix {home}/proj/app.py", who="boss") == (str(home / "proj"), "")
    assert _bind(f"fix {home}/proj/app.py", who="ann") == ("", "")


@pytest.mark.asyncio
async def test_the_chat_route_hands_the_agent_the_folder_for_the_turn(
        ws, settings, people, monkeypatch):
    import routes.chat_routes as chat_routes
    import src.settings as S
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    monkeypatch.setitem(_USERS, "alice", {"admin": False, "privs": {"can_use_workstation": True}})
    alice = _home(ws, "alice")
    (alice / "proj").mkdir(parents=True)
    (alice / "proj" / "app.py").write_text("x = 1\n")
    _on(settings, ws)

    async def turn(message):
        captured = {}
        endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured)
        values = dict(settings)
        monkeypatch.setattr(S, "get_setting", lambda key, default=None: values.get(key, default))
        monkeypatch.setattr(chat_routes, "coerce_message_and_session",
                            lambda *a, **k: (message, "session-1"))

        async def loop(endpoint_url, model, messages, **kwargs):
            captured["workspace"] = kwargs.get("workspace")
            yield "data: [DONE]\n\n"

        monkeypatch.setattr(chat_routes, "stream_agent_loop", loop)
        request = _RouteRequest("chat")
        request._form.update({"compare_mode": "false", "message": message})
        response = await endpoint(request)
        events = []
        async for chunk in response.body_iterator:
            for line in str(chunk).splitlines():
                if line.startswith("data: {"):
                    events.append(json.loads(line[6:]))
        return captured, events

    # Sent from chat mode with no workspace: the agent runs, in that folder.
    captured, _ = await turn("fix ~/proj/app.py")
    assert captured.get("workspace") == str(alice / "proj"), captured
    # A path that is not a folder of her home binds nothing.
    captured, _ = await turn("fix ~/nowhere/app.py")
    assert captured.get("workspace") is None, captured
