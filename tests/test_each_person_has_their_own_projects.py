# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1424`: each person's projects folder is theirs, and an admin's too.

The owner, 2026-10-22: *"for the workstation and projects folder — let's ensure
these are per-user scoped and instanced. No overlaps, no shared events. Admins
should be able to see and access other users' projects and folders/events."*

Before this, `B1417` gave the workstation ONE `/projects` for everyone and
Pantheon one `data/projects`: every account could read, change and delete what
every other account built, and list who else was building.

Driven through the real daemon (`tests/helpers/workstation_daemon.py`), the
real routes behind a real `AuthManager` (`P20-02`'s fixtures, imported), the
real `sync_config`, and — where Unix ownership is the claim — the real
`UbuntuSystem` acting as each account, which this suite can do as root.
"""
from __future__ import annotations

import asyncio
import os
import stat

import pytest

import src.agent_tools  # noqa: F401 — enters the tool-module cycle the right way round
from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, ALLOWED, ALSO, PLAIN, app, as_user, auth, datadir, switch_on, ws)
from workstation import protocol as P


def run(coro):
    return asyncio.run(coro)


def daemon(ws):
    return WorkstationClient(ws.url, ws.token)


@pytest.fixture
def projects(ws, tmp_path):
    """The workstation with its projects mount, as the compose overlay gives it."""
    root = tmp_path / "projects-mount"
    root.mkdir()
    ws.system.shared_roots = [root]
    return root


A, B = account_for(ALLOWED), account_for(ALSO)


# ── one folder each, made on first use ───────────────────────────────────────

def test_each_person_is_given_a_folder_of_their_own(ws, projects):
    a = run(daemon(ws).ensure(A))["projects"]
    b = run(daemon(ws).ensure(B))["projects"]
    assert a == str(projects / P.project_folder(ALLOWED))
    assert b == str(projects / P.project_folder(ALSO))
    assert a != b
    assert os.path.isdir(a) and os.path.isdir(b)


def test_a_command_is_told_where_its_folder_is(ws, projects):
    out = run(daemon(ws).exec(A, f'printf %s "${P.PROJECTS_ENV}"'))
    assert out["stdout"] == str(projects / P.project_folder(ALLOWED))


def test_without_the_mount_there_is_no_folder_and_no_variable(ws):
    assert run(daemon(ws).ensure(A))["projects"] is None
    out = run(daemon(ws).exec(A, f'printf %s "${{{P.PROJECTS_ENV}:-unset}}"'))
    assert out["stdout"] == "unset"


# ── no overlaps ──────────────────────────────────────────────────────────────

def test_a_person_works_in_their_own_folder(ws, projects):
    mine = run(daemon(ws).ensure(A))["projects"]
    run(daemon(ws).write(A, f"{mine}/site/index.html", b"<h1>mine</h1>"))
    assert run(daemon(ws).read(A, f"{mine}/site/index.html"))["data"] == b"<h1>mine</h1>"


def test_a_person_cannot_reach_anothers_folder(ws, projects):
    theirs = run(daemon(ws).ensure(B))["projects"]
    run(daemon(ws).write(B, f"{theirs}/secret.txt", b"b's"))
    run(daemon(ws).ensure(A))
    for attempt in (lambda: daemon(ws).read(A, f"{theirs}/secret.txt"),
                    lambda: daemon(ws).write(A, f"{theirs}/planted.txt", b"x"),
                    lambda: daemon(ws).list(A, theirs)):
        with pytest.raises(WorkstationError) as e:
            run(attempt())
        assert e.value.code == "outside_home", e.value.message
    assert not os.path.exists(f"{theirs}/planted.txt")


def test_a_person_cannot_list_who_else_has_a_folder(ws, projects):
    run(daemon(ws).ensure(B))
    run(daemon(ws).ensure(A))
    with pytest.raises(WorkstationError) as e:
        run(daemon(ws).list(A, str(projects)))
    assert e.value.code == "outside_home"


def test_the_refusal_names_the_persons_own_folder(ws, projects):
    mine = run(daemon(ws).ensure(A))["projects"]
    with pytest.raises(WorkstationError) as e:
        run(daemon(ws).read(A, str(projects / "elsewhere.txt")))
    assert f"your projects folder ({mine})" in e.value.message


def test_a_folder_that_is_a_symlink_is_not_admitted(ws, projects, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("not yours", encoding="utf-8")
    os.symlink(outside, projects / P.project_folder(ALLOWED))
    assert run(daemon(ws).ensure(A))["projects"] is None
    with pytest.raises(WorkstationError):
        run(daemon(ws).read(A, str(projects / P.project_folder(ALLOWED) / "x.txt")))


# ── admins see everyone's ────────────────────────────────────────────────────

def test_an_admin_account_reaches_every_folder(ws, projects):
    theirs = run(daemon(ws).ensure(B))["projects"]
    run(daemon(ws).write(B, f"{theirs}/notes.md", b"b's notes"))
    admin = account_for(ADMIN)
    run(daemon(ws).ensure(admin))
    run(daemon(ws).config(admins=[admin]))
    assert run(daemon(ws).read(admin, f"{theirs}/notes.md"))["data"] == b"b's notes"
    names = {e["path"] for e in run(daemon(ws).list(admin, str(projects)))["entries"]}
    assert {P.project_folder(ALSO), P.project_folder(ADMIN)} <= names


def test_taking_admin_away_takes_the_reach_away(ws, projects):
    theirs = run(daemon(ws).ensure(B))["projects"]
    admin = account_for(ADMIN)
    run(daemon(ws).config(admins=[admin]))
    run(daemon(ws).config(admins=[]))
    with pytest.raises(WorkstationError):
        run(daemon(ws).list(admin, theirs))


@pytest.mark.parametrize("bad", ["pw-x-00000000", ["not an account"], [1], {"a": 1}])
def test_the_admin_list_is_checked(ws, bad):
    with pytest.raises(WorkstationError) as e:
        run(daemon(ws).config(admins=bad))
    assert e.value.code == "bad_request"


def test_the_daemon_says_who_it_was_told(ws):
    admin = account_for(ADMIN)
    run(daemon(ws).config(admins=[admin]))
    assert run(daemon(ws).health())["admins"] == [admin]


def test_pantheon_tells_it_the_admins_and_only_when_they_changed(app, ws, auth, monkeypatch):
    switch_on(app, ws)
    client = daemon(ws)
    pushed = []
    real = client.config

    async def spy(**settings):
        pushed.append(settings)
        return await real(**settings)

    client.config = spy
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager", lambda: auth)
    run(wa.sync_config(client))
    assert {"admins": [account_for(ADMIN)]} in pushed
    pushed.clear()
    run(wa.sync_config(client))
    assert not any("admins" in p for p in pushed), pushed


def test_the_admin_list_is_the_admins(auth, monkeypatch):
    assert wa.admin_accounts(auth) == [account_for(ADMIN)]


# ── Pantheon's side: the same folder, by the same name ───────────────────────

def test_pantheons_folder_for_a_person_is_the_workstations_name(datadir):
    from src.tool_execution import projects_base, projects_root
    for who in (ALLOWED, "Ann Smith", None):
        root = projects_root(who)
        assert os.path.dirname(root) == projects_base()
        assert os.path.basename(root) == P.project_folder(wa.workstation_owner(who))
        assert os.path.isdir(root)
    assert projects_root(ALLOWED) != projects_root(ALSO)


def test_get_workspace_through_the_dispatcher_names_the_callers_folder(datadir, monkeypatch):
    """The path a model's call takes: `execute_tool_block`, not the handler."""
    import src.tool_execution as te
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block, projects_root
    monkeypatch.setattr(te, "owner_is_admin", lambda owner: owner == ADMIN)
    monkeypatch.setattr("src.tool_execution._works_in_workstation", lambda owner: False,
                        raising=False)
    out = run(execute_tool_block(ToolBlock("get_workspace", ""), owner=ADMIN,
                                 security_context=NO_TOOL_SECURITY_CONTEXT))[1]
    assert projects_root(ADMIN) in out.get("output", ""), out


def test_get_workspace_names_the_callers_folder(datadir):
    from src.tool_execution import _direct_fallback, projects_root
    out = run(_direct_fallback("get_workspace", "", owner=ALSO))
    assert projects_root(ALSO) in out["output"]
    assert out["projects_root"] == projects_root(ALSO)
    assert projects_root(ALLOWED) not in out["output"]


def test_the_picker_opens_on_the_callers_own_folder(datadir, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.workspace_routes as wr
    from src.tool_execution import projects_root

    application = FastAPI()

    @application.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    application.include_router(wr.setup_workspace_routes())
    monkeypatch.setattr(wr, "_in_workstation", lambda request, owner: False)
    monkeypatch.setattr(wr, "owner_is_admin", lambda owner: owner == ADMIN)
    r = TestClient(application).get("/api/workspace/browse", headers={"x-test-user": ADMIN})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == os.path.realpath(projects_root(ADMIN))
    # An admin may walk up into everyone's: the parent is the projects root.
    assert r.json()["parent"] == os.path.realpath(os.path.dirname(projects_root(ADMIN)))


# ── watching: an admin may watch another person's screen ─────────────────────

def test_an_admin_watches_another_persons_screen(app, ws):
    switch_on(app, ws)
    for i in range(3):
        run(daemon(ws).input(B, "click", x=i, y=i))
    theirs = run(daemon(ws).screenshot(B))["digest"]
    r = as_user(app, ADMIN).get(f"/api/workstation/screen?person={ALSO}")
    assert r.status_code == 200, r.text
    assert r.json()["digest"] == theirs
    r = as_user(app, ADMIN).get(f"/api/workstation/control?person={ALSO}")
    assert r.status_code == 200 and r.json()["holder"] == "agent"


def test_nobody_else_may_name_a_person(app, ws):
    switch_on(app, ws)
    r = as_user(app, ALLOWED).get(f"/api/workstation/screen?person={ALSO}")
    assert r.status_code == 403
    r = as_user(app, ALLOWED).get(f"/api/workstation/control?person={ALSO}")
    assert r.status_code == 403


def test_watching_is_not_driving(app, ws):
    """The input, take-over and reset routes take no `person`: an admin
    naming one still acts on their own screen and nobody else's."""
    switch_on(app, ws)
    before = len(ws.screen(B).actions) if B in getattr(ws.system, "_screens", {}) else 0
    admin = as_user(app, ADMIN)
    admin.post(f"/api/workstation/input?person={ALSO}",
               json={"action": "click", "x": 3, "y": 3, "person": ALSO})
    admin.post(f"/api/workstation/control?person={ALSO}", json={"holder": "person", "person": ALSO})
    assert run(daemon(ws).ensure(B))["holder"] == "agent"
    after = len(ws.screen(B).actions)
    assert after == before


def test_an_unknown_person_is_said_to_be_unknown(app, ws):
    switch_on(app, ws)
    r = as_user(app, ADMIN).get("/api/workstation/screen?person=nobody-here")
    assert r.status_code == 404
    assert "nobody-here" in r.json()["detail"]


# ── the Ubuntu workstation: who owns what on disk ────────────────────────────

ubuntu = pytest.mark.skipif(os.geteuid() != 0, reason="Unix ownership needs root to set")


@pytest.fixture
def station(tmp_path):
    from workstation.ubuntu import UbuntuSystem
    system = UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel", prepare=False)
    root = tmp_path / "projects"
    root.mkdir()
    system.shared_roots = [root]
    system.projects_gid = 4242
    return system, root


@ubuntu
def test_a_folder_is_the_persons_in_pantheons_group_and_closed_to_others(station):
    system, root = station
    uid = system.registry.uid_for(A)
    [folder] = system.make_project_dirs(A)
    st = os.stat(folder)
    assert (st.st_uid, st.st_gid) == (uid, 4242)
    assert stat.S_IMODE(st.st_mode) == 0o2770
    top = os.stat(root)
    assert top.st_gid == 4242
    assert stat.S_IMODE(top.st_mode) == 0o771, "others may pass through, not list"


@ubuntu
def test_a_folder_moved_by_someone_else_is_put_back(station):
    system, root = station
    system.registry.uid_for(A)
    [folder] = system.make_project_dirs(A)
    os.chown(folder, 0, 0)
    os.chmod(folder, 0o777)
    system.make_project_dirs(A)
    st = os.stat(folder)
    assert (st.st_uid, stat.S_IMODE(st.st_mode)) == (system.registry.get(A), 0o2770)


@ubuntu
def test_a_symlink_is_never_given_away(station, tmp_path):
    system, root = station
    target = tmp_path / "target"
    target.mkdir()
    os.symlink(target, root / P.project_folder(ALLOWED))
    system.registry.uid_for(A)
    os.chmod(target, 0o700)
    assert system.make_project_dirs(A) == []
    assert os.stat(target).st_uid == 0
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o700, "the link's target was changed"


@ubuntu
def test_an_admin_acts_with_the_projects_group_and_nobody_else_does(station):
    import shutil
    import tempfile
    from pathlib import Path
    system, root = station
    system.sudo = False
    # Under /tmp itself: pytest's own folders are root's 0700, which an
    # account acting as itself cannot pass through.
    tmp_path = Path(tempfile.mkdtemp(prefix="b1424-"))
    os.chmod(tmp_path, 0o755)
    request_cleanup = lambda: shutil.rmtree(tmp_path, ignore_errors=True)  # noqa: E731
    for acct in (A, B):
        uid = system.registry.uid_for(acct)
        d = tmp_path / acct
        d.mkdir()
        os.chown(d, uid, uid)
    system.set_admins([A])
    with system.acting_as(A):
        (tmp_path / A / "f").write_text("x")
    with system.acting_as(B):
        (tmp_path / B / "f").write_text("x")
    try:
        assert os.stat(tmp_path / A / "f").st_gid == 4242
        assert os.stat(tmp_path / B / "f").st_gid == system.registry.get(B)
    finally:
        request_cleanup()


@ubuntu
def test_what_anyone_makes_is_theirs_and_their_groups_only(tmp_path, monkeypatch):
    """The mask every command and every file operation inherits: with it, a
    file a person builds in their setgid folder is Pantheon's group's to read
    and write, and no other account's to read at all."""
    import workstation.ubuntu as ub
    monkeypatch.setattr(ub, "write_sudoers", lambda *a, **k: None)
    monkeypatch.setattr(ub.UbuntuSystem, "_hold_network", lambda self, mode: None)
    monkeypatch.setattr(ub.os, "setgroups", lambda groups: None)
    monkeypatch.setattr(ub, "X_SOCKET_DIR", tmp_path / "x11")
    monkeypatch.setattr(ub.grp, "getgrnam", lambda name: object())
    before = os.umask(0o022)
    try:
        ub.UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel",
                        runtime_root=tmp_path / "run", sudoers_path=tmp_path / "sudoers")
        now = os.umask(0o022)
    finally:
        os.umask(before)
    assert now == 0o007
