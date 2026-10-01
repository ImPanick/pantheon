# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B968` — with the workstation on, the workspace is a folder in the person's workstation home.

The owner's call (`D-2026-10-01-01`): *with the workstation on, the picker
lists folders in the person's workstation home and the routed tools start
there.* Driven, not read (`Law 20`): the picker's two routes through a real
FastAPI app, the dispatcher (`execute_tool_block`), an approved action replayed
through it, and the chat route — each against the real daemon
(`tests/helpers/workstation_daemon.py`).

  * **the picker** lists the folders in the home (never above it), vets a
    folder there, and refuses one that is not — for anyone who may use the
    workstation, not only an admin; off, it answers exactly as before;
  * **the tools start there**: the shells, and relative paths in the file
    tools; `~` is still the home and the home is still reachable — the
    workspace is where they start, not a boundary;
  * **it is never bound here**: Pantheon's own resolvers do not see it;
  * **`get_workspace` agrees** with where the tools work;
  * **the chat and an approval** vet it in the workstation.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agent_tools as agent_tools
import src.agent_tools.subprocess_tools as sp
import src.agent_tools.workstation_tools as wt
import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.workstation_client import account_for
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _USERS, _Auth, _call, _home, _on, people, settings, ws,
)


def _forget_every_folder():
    # Tolerant of a tree without them, so a run against the code before `B962`
    # fails on behaviour rather than on this fixture.
    if hasattr(sp, "CHAT_FOLDERS"):
        sp.CHAT_FOLDERS.clear()
    getattr(wt, "_HOMES", {}).clear()


@pytest.fixture(autouse=True)
def fresh_memory():
    """Each case starts with no chat holding a folder, and leaves none."""
    _forget_every_folder()
    yield
    _forget_every_folder()


@pytest.fixture
def home(ws):
    """Ann's workstation home, with two folders, a hidden one, a key folder and a file."""
    h = _home(ws, "ann")
    for d in ("proj/src", "Zeta", ".hidden", ".ssh"):
        (h / d).mkdir(parents=True, exist_ok=True)
    (h / "notes.txt").write_text("top\n")
    (h / "proj" / "keep.txt").write_text("alpha\n")
    return h


# ── the picker ───────────────────────────────────────────────────────────────


@pytest.fixture
def picker(people):
    from routes.workspace_routes import setup_workspace_routes
    app = FastAPI()
    app.state.auth_manager = _Auth()

    @app.middleware("http")
    async def who(request, call_next):
        request.state.current_user = request.headers.get("X-Test-User")
        return await call_next(request)

    app.include_router(setup_workspace_routes())
    client = TestClient(app)

    def ask(route, who, **params):
        return client.get(f"/api/workspace/{route}", params=params, headers={"X-Test-User": who})
    return ask


def test_the_picker_lists_the_folders_in_the_workstation_home(ws, settings, picker, home):
    _on(settings, ws)
    r = picker("browse", "ann")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got == {
        "path": str(home), "parent": None, "truncated": False, "selectable": True,
        "where": "workstation", "home": str(home),
        "dirs": [{"name": "proj", "path": str(home / "proj")},
                 {"name": "Zeta", "path": str(home / "Zeta")}],
    }
    got = picker("browse", "ann", path="proj").json()
    assert (got["path"], got["parent"]) == (str(home / "proj"), str(home))
    assert got["dirs"] == [{"name": "src", "path": str(home / "proj" / "src")}]
    # A sensitive folder may be looked into, never chosen.
    assert picker("browse", "ann", path=".ssh").json()["selectable"] is False


@pytest.mark.parametrize("path", ["/etc", "/", "nothing-here", "notes.txt", ".."])
def test_the_picker_never_leaves_the_home(ws, settings, picker, home, path):
    _on(settings, ws)
    got = picker("browse", "ann", path=path).json()
    assert got["path"] == str(home) and got["parent"] is None


def test_with_sudo_on_the_picker_still_stays_in_the_home(ws, settings, picker, home):
    _on(settings, ws, workstation_sudo=True)
    # `B987`: the picker's routes push the admin's `sudo` as a tool call does,
    # so the setting itself lifts the daemon's jail — this case is about the
    # daemon answering `/etc` and the picker declining it anyway.
    assert picker("browse", "ann", path="/etc").json()["path"] == str(home)
    import src.workstation_client as wc
    client = wc.WorkstationClient(ws.url, ws.token)
    assert asyncio.run(client.list(account_for("ann"), "/etc", max_entries=0))["path"] == "/etc"
    assert picker("vet", "ann", path="/etc").json() == {"ok": False, "path": None,
                                                        "where": "workstation"}


@pytest.mark.parametrize(("path", "answer"), [
    ("proj", "proj"), ("~/proj/src", "proj/src"), ("~", ""), ("Zeta/", "Zeta"),
    ("nothing-here", None), ("notes.txt", None), (".ssh", None), ("/etc", None), ("", None),
])
def test_the_picker_vets_a_folder_in_the_workstation(ws, settings, picker, home, path, answer):
    _on(settings, ws)
    expected = None if answer is None else str(home / answer) if answer else str(home)
    assert picker("vet", "ann", path=path).json() == {"ok": expected is not None,
                                                      "path": expected, "where": "workstation"}


def test_the_picker_is_for_whoever_may_use_the_workstation(ws, settings, picker, home):
    _on(settings, ws)
    # The admin, in their own home.
    got = picker("browse", "boss").json()
    assert got["where"] == "workstation" and got["path"] == str(_home(ws, "boss"))
    # A person without the workstation: the rule for this machine, as before.
    assert picker("browse", "bob").status_code == 403
    assert picker("vet", "bob", path="proj").status_code == 403


def test_a_workstation_that_does_not_answer_is_said_in_its_own_words(ws, settings, picker):
    _on(settings, ws, workstation_url="http://127.0.0.1:9")
    r = picker("browse", "ann")
    assert r.status_code == 503
    assert r.json()["detail"].startswith("The workstation at http://127.0.0.1:9 did not answer")


def test_with_the_workstation_off_the_picker_is_what_it_was(ws, settings, picker, home):
    assert picker("browse", "ann").status_code == 403
    assert picker("vet", "ann", path=str(home)).status_code == 403
    got = picker("browse", "boss", path=str(home))
    assert got.status_code == 200 and "where" not in got.json()
    assert got.json()["path"] == str(home)
    assert picker("vet", "boss", path=str(home)).json() == {"ok": True, "path": str(home)}
    assert list(ws.root.iterdir()) == [ws.root / account_for("ann")]   # made by `home`, nothing new


# ── the tools start there ────────────────────────────────────────────────────


def in_ws(tool, content, *, workspace, owner="ann", chat="c1"):
    r = _call(tool, content, owner, session_id=chat, workspace=workspace)[1]
    assert r.get("ran_in") == "workstation", r
    return r


def test_the_shells_start_in_the_workspace(ws, settings, people, home):
    _on(settings, ws)
    proj = str(home / "proj")
    assert in_ws("bash", "pwd", workspace=proj)["stdout"] == proj
    assert in_ws("bash", "pwd", workspace=proj, chat=None)["stdout"] == proj
    r = in_ws("python", "import os; print(os.getcwd())", workspace=proj)
    assert r["stdout"] == proj and r["cwd"] == proj
    # A chat's folder is kept inside the workspace, and `cd` back is the start.
    in_ws("bash", "cd src", workspace=proj)
    assert in_ws("bash", "pwd", workspace=proj)["stdout"] == f"{proj}/src"
    assert in_ws("bash", "cd ~ && pwd", workspace=proj)["stdout"] == str(home)


def test_the_file_tools_read_a_relative_path_from_the_workspace(ws, settings, people, home):
    _on(settings, ws)
    proj = home / "proj"
    w = str(proj)
    r = in_ws("write_file", json.dumps({"path": "a.txt", "content": "one\n"}), workspace=w)
    assert r["exit_code"] == 0 and (proj / "a.txt").read_text() == "one\n"
    assert r["output"] == f"Wrote 4 bytes to {proj}/a.txt"
    assert in_ws("read_file", json.dumps({"path": "a.txt"}), workspace=w)["output"] == "one\n"
    r = in_ws("edit_file", json.dumps({"path": "a.txt", "old_string": "one", "new_string": "two"}),
              workspace=w)
    assert r["exit_code"] == 0 and (proj / "a.txt").read_text() == "two\n"
    r = in_ws("apply_patch", "*** Begin Patch\n*** Add File: src/b.txt\n+bee\n"
                             "*** Update File: a.txt\n@@\n-two\n+three\n*** End Patch", workspace=w)
    assert r["exit_code"] == 0, r
    assert (proj / "src" / "b.txt").read_text() == "bee\n"
    assert (proj / "a.txt").read_text() == "three\n"
    r = in_ws("ls", "{}", workspace=w)
    assert r["output"].splitlines()[0] == f"{proj}:" and "keep.txt" in r["output"]
    r = in_ws("glob", json.dumps({"pattern": "**/*.txt"}), workspace=w)
    assert sorted(r["output"].splitlines()) == sorted(
        [f"{proj}/a.txt", f"{proj}/keep.txt", f"{proj}/src/b.txt"]), r
    r = in_ws("grep", json.dumps({"pattern": "bee"}), workspace=w)
    assert f"{proj}/src/b.txt" in r["output"]
    # Missing, said under the folder it was looked for in.
    r = in_ws("read_file", json.dumps({"path": "nope.txt"}), workspace=w)
    assert r["error"] == f"read_file: {proj}/nope.txt: not found"


def test_the_workspace_is_where_they_start_not_a_boundary(ws, settings, people, home):
    _on(settings, ws)
    w = str(home / "proj")
    assert in_ws("read_file", json.dumps({"path": "~/notes.txt"}), workspace=w)["output"] == "top\n"
    assert in_ws("read_file", json.dumps({"path": str(home / "notes.txt")}),
                 workspace=w)["output"] == "top\n"
    in_ws("write_file", json.dumps({"path": "~/up.txt", "content": "x"}), workspace=w)
    assert (home / "up.txt").read_text() == "x"
    # The home jail is the boundary, as it always was.
    r = in_ws("read_file", json.dumps({"path": "/etc/hostname"}), workspace=w)
    assert r["exit_code"] == 1 and "outside your workstation home" in r["error"]
    # And the sensitive-path rule still holds inside the workspace.
    (home / "proj" / ".env").write_text("SECRET=1\n")
    r = in_ws("read_file", json.dumps({"path": ".env"}), workspace=w)
    assert "sensitive" in r["error"]


def test_a_workspace_that_is_gone_starts_the_tools_in_the_home_with_a_sentence(ws, settings,
                                                                                people, home):
    _on(settings, ws)
    w = str(home / "proj")
    shutil.rmtree(home / "proj")
    r = in_ws("bash", "pwd", workspace=w)
    assert r["stdout"] == str(home)
    assert r["note"] == (f"The workspace {w} is not a folder in your workstation any more, so "
                         f"this command started in {home}.")


def test_the_workspace_is_never_bound_on_this_machine(ws, settings, people, home, monkeypatch):
    import sys
    import test_the_agents_hands_are_in_the_workstation as hands
    _on(settings, ws)
    seen = []

    async def spy(content, ctx):
        # Read from the dispatcher `_call` drives, and patched into the
        # registry that dispatcher imports when it runs: the same objects in a
        # clean process, and still the right ones after a test file that swaps
        # `sys.modules` (`B-NEW` in the `ws-shell` note).
        seen.append(hands.te.get_active_workspace())
        return {"output": "ok", "exit_code": 0}

    monkeypatch.setitem(sys.modules["src.agent_tools"].TOOL_HANDLERS, "manage_bg_jobs", spy)
    _call("manage_bg_jobs", "list", "boss", workspace=str(_home(ws, "boss")))
    assert seen == [None]
    # With the workstation off, a workspace on this machine is bound as before.
    settings["workstation_enabled"] = False
    _call("manage_bg_jobs", "list", "boss", workspace=str(home))
    assert seen == [None, str(home)]


def test_get_workspace_says_where_the_tools_work(ws, settings, people, home):
    _on(settings, ws)
    bhome = _home(ws, "boss")
    (bhome / "proj").mkdir(parents=True)
    _, r = _call("get_workspace", "", "boss", workspace=str(bhome / "proj"))
    assert r == {"output": f"{bhome / 'proj'}\n(In your workstation. The shell and file tools "
                           "start in this folder and read relative paths from it; it is where "
                           "they start, not a boundary.)", "exit_code": 0}
    _, r = _call("get_workspace", "", "boss")
    assert r == {"output": "No workspace is set. The shell and file tools run in your workstation "
                           f"and start in your workstation home ({bhome}); relative paths are "
                           "relative to it.", "exit_code": 0}
    # A person who is not an admin gets the same answer about their own home
    # since `B985` (`test_get_workspace_is_lifted_with_the_nine.py`).
    # Off: this machine's answer, unchanged.
    settings["workstation_enabled"] = False
    _, r = _call("get_workspace", "", "boss", workspace=str(home / "proj"))
    assert r["output"].startswith(f"{home / 'proj'}\n(File tools are confined to this folder")


# ── an approved action replays its workspace ────────────────────────────────


def _approve(*, owner, workspace, content="pwd"):
    from src.tool_approvals import ToolApprovalStore
    from src.tool_capabilities import capabilities_for_action
    store = ToolApprovalStore()
    pending = store.create(owner=owner, session_id="c1", origin_run_id="run-1", tool_name="bash",
                           content=content, workspace=workspace,
                           external_untrusted_context_seen=True,
                           capabilities=capabilities_for_action("bash", content))
    return store.consume(pending.approval_id, decision="approve", owner=owner, session_id="c1")


def _replay(grant, *, owner, workspace, content="pwd"):
    from src.tool_capabilities import ToolRunSecurityContext
    return asyncio.run(te.execute_tool_block(
        ToolBlock("bash", content), session_id="c1", owner=owner, workspace=workspace,
        security_context=ToolRunSecurityContext(external_untrusted_context_seen=True),
        exact_approval=grant))[1]


def test_an_approved_action_runs_in_its_workstation_workspace(ws, settings, people, home):
    _on(settings, ws)
    w = str(home / "proj")
    r = _replay(_approve(owner="ann", workspace=w), owner="ann", workspace=w)
    assert r["stdout"] == w and r["ran_in"] == "workstation", r


def test_an_approval_sealed_with_a_folder_on_this_machine_is_refused_in_the_workstation(
        ws, settings, people, home, tmp_path):
    _on(settings, ws)
    here = os.path.realpath(tmp_path)      # a real, safe folder — on this machine
    r = _replay(_approve(owner="ann", workspace=here), owner="ann", workspace=here)
    assert r["policy"] == "exact_tool_approval" and "no longer a valid safe directory" in r["error"]


def test_a_workstation_that_is_down_at_approval_runs_nothing_anywhere(ws, settings, people, home,
                                                                      monkeypatch):
    _on(settings, ws)
    w = str(home / "proj")
    ran_here = []

    async def spy(content, ctx):
        ran_here.append(content)
        return {"output": "ran here", "exit_code": 0}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "bash", spy)
    settings["workstation_url"] = "http://127.0.0.1:9"
    r = _replay(_approve(owner="ann", workspace=w), owner="ann", workspace=w)
    assert r["workstation_error"] == "unavailable" and ran_here == []


# ── the chat sends it ────────────────────────────────────────────────────────


def _request(user):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)),
                           state=SimpleNamespace(current_user=user), headers={})


def test_the_chat_vets_the_workspace_in_the_workstation(ws, settings, people, home):
    import routes.chat_routes as cr
    _on(settings, ws)
    run = lambda raw, who="ann": asyncio.run(cr._resolve_posted_workspace(_request(who), raw))
    assert run("proj") == (str(home / "proj"), "")
    assert run(str(home / "proj")) == (str(home / "proj"), "")
    assert run("nothing-here") == ("", "nothing-here")
    assert run(".ssh") == ("", ".ssh")
    assert run("") == ("", "")
    # Who may: anyone the workstation answers for — the host rule refuses ann.
    assert run("proj", who="bob") == ("", "")
    # A path on this machine is not bound for someone whose tools are there.
    assert cr._resolve_workspace_from_message_path(
        _request("boss"), f"please fix {home}/proj/keep.txt") == ("", "")
    # Down: nothing bound, nothing rejected — every routed tool will say so.
    settings["workstation_url"] = "http://127.0.0.1:9"
    assert run("proj") == ("", "")


def test_with_the_workstation_off_the_chat_binds_as_before(ws, settings, people, home):
    import routes.chat_routes as cr
    run = lambda raw, who: asyncio.run(cr._resolve_posted_workspace(_request(who), raw))
    assert run(str(home), "boss") == (str(home), "")
    assert run(str(home), "ann") == ("", "")
    assert cr._resolve_workspace_from_message_path(
        _request("boss"), f"please fix {home}/proj/keep.txt") == (str(home / "proj"), "")


@pytest.mark.asyncio
async def test_the_chat_route_hands_the_loop_the_workstation_folder_and_says_why_one_is_refused(
        ws, settings, people, home, monkeypatch):
    import routes.chat_routes as chat_routes
    import src.settings as S
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    monkeypatch.setitem(_USERS, "alice", {"admin": False, "privs": {"can_use_workstation": True}})
    alice_home = _home(ws, "alice")
    (alice_home / "proj").mkdir(parents=True)
    _on(settings, ws)

    async def route(workspace):
        captured = {}
        endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)
        # The harness answers every setting with its default; the workstation's
        # keys are this test's.
        values = dict(settings)
        monkeypatch.setattr(S, "get_setting",
                            lambda key, default=None: values.get(key, default))

        async def loop(endpoint_url, model, messages, **kwargs):
            captured["workspace"] = kwargs.get("workspace")
            yield "data: [DONE]\n\n"

        monkeypatch.setattr(chat_routes, "stream_agent_loop", loop)
        request = _RouteRequest("agent")
        request._form.update({"compare_mode": "false", "workspace": workspace})
        response = await endpoint(request)
        events = []
        async for chunk in response.body_iterator:
            for line in str(chunk).splitlines():
                if line.startswith("data: {"):
                    events.append(json.loads(line[6:]))
        return captured.get("workspace"), [e for e in events if e.get("type") == "workspace_rejected"]

    got, rejected = await route("proj")
    assert got == str(alice_home / "proj") and rejected == []
    got, rejected = await route("/app/data/somewhere")
    assert got is None
    assert rejected == [{"type": "workspace_rejected", "data": {
        "path": "/app/data/somewhere",
        "message": ("Workspace /app/data/somewhere is not a folder in your workstation; the "
                    "agent's tools start in your workstation home.")}}]
