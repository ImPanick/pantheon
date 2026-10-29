# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1642` — in the workstation a hire's file tools and its runbook's `cd`
reach the same folder; `B1643` — a workstation with nothing mounted at its
projects root says so, and a `cd` into the folder never lands at `/<folder>`.

Measured before the fix, with the real daemon: `runtime.workspace_for`
answered `None` for a person whose tools run in the workstation, so a hire's
file tools read a relative path from the workstation home while its runbook's
`cd "$PANTHEON_PROJECTS"/'<folder>'` went to the projects folder —
`write_file {"path": "My Site/index.html"}` wrote `~/My Site/index.html`, and
`/projects/<name>/My Site`, which Site Builder then served, stayed empty. And
with nothing mounted the daemon left `$PANTHEON_PROJECTS` unset, so the same
`cd` ran `cd /'<folder>'` (a hire's `tmp` is `/tmp`).

The one rule now: a hire's run works in its projects folder on either machine
(`workspace_for`), named on Pantheon's machine as Pantheon names it, and in the
workstation as the workstation does — `projects_root/<name>`, which the daemon
reports (`health`) and gives every command as `$PANTHEON_PROJECTS`
(`workstation_tools.station_folder`). The daemon makes the folder before a
file call as before a command, so a hire whose first call is `ls` is admitted.
With nothing mounted the variable names the folder that is not there, the run
starts in the home as it did, and the answer says why
(`workstation_tools.no_projects_sentence`).

Nothing is loosened: the daemon's jail is what it was (`B1417`, `B1424`), and
the workspace check (`vet_workspace`) admits the person's own projects folder
beside their home — never another person's, never the root, never `/etc`.

Driven (`Law 20`): the real dispatcher (`execute_tool_block`) with the
workspace a hire's run binds (`workspace_for`), against the real workstation
daemon (`tests/helpers/workstation_daemon.py`), each runbook's own `cd` read
from its file.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agents.catalogue import catalogue
from src.agents.runtime import workspace_for
from src.workstation_client import account_for
from test_a_folder_with_a_space_is_one_folder import _cd_spans, _fill
from test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401 — fixture
from test_a_hired_agent_runs_as_its_file_says import _hire, _run, _task, world  # noqa: F401
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _on, people, settings, ws,
)
from workstation import protocol as P

NAMES = ["My Site", "Tom's site"]


@pytest.fixture
def data(monkeypatch, tmp_path):
    """Pantheon's own data folder: the test's."""
    import src.constants as constants
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(constants, "DATA_DIR", str(folder))
    return folder


@pytest.fixture
def station(ws, settings, people, data, tmp_path):
    """The workstation with its projects mount, as the overlay gives it — a
    folder of its own, so its names and Pantheon's differ as they do across
    the mount (`/projects` there, `<data>/projects` here)."""
    _on(settings, ws)
    mount = tmp_path / "projects-mount"
    mount.mkdir()
    ws.system.shared_roots = [mount]
    return Path(os.path.realpath(mount))


@pytest.fixture
def bare(ws, settings, people, data, tmp_path):
    """A workstation with nothing mounted where its projects folder goes."""
    _on(settings, ws)
    root = tmp_path / "nothing-mounted-here"
    ws.system.shared_roots = [root]
    return root


def _mine(root: Path, owner: str = "ann") -> Path:
    return root / P.project_folder(owner)


def _write(path: str, text: str, owner: str = "ann", workspace=None):
    return _call("write_file", {"path": path, "content": text}, owner, workspace=workspace)[1]


def _file_runbooks():
    """Each runbook whose kit writes files, with its own `cd` — read from the
    library, never carried (`Law 6`)."""
    agents, _ = catalogue(None)
    writes = {m.id for m in agents if "write_file" in (m.tools or ())}
    return [(a, span.split(" && ", 1)[0]) for a, span in _cd_spans() if a in writes]


# ── the row ──────────────────────────────────────────────────────────────────

def test_a_hires_relative_file_path_and_its_cd_reach_the_same_folder(station, ws):
    workspace = workspace_for("ann", None)
    runbooks = _file_runbooks()
    assert {"site-builder"} <= {a for a, _h in runbooks}, runbooks
    for name in NAMES:
        for agent, head in runbooks:
            text = f"{agent} wrote this in {name}"
            w = _write(f"{name}/probe.txt", text, workspace=workspace)
            assert w.get("ran_in") == "workstation" and not w.get("error"), (agent, w)
            r = _call("bash", _fill(head, name) + " && cat probe.txt && echo && pwd -P", "ann",
                      session_id=f"hire-{agent}", workspace=workspace)[1]
            assert r.get("exit_code") == 0, (agent, head, r)
            assert r["stdout"].splitlines() == [text, str(_mine(station) / name)], (agent, head, r)
        assert not (ws.root / account_for("ann") / name).exists(), "a file went to the home"


def test_site_builders_steps_meet_in_its_folder(station, ws):
    """Site Builder's runbook as it reads: `ls` the folder, `write_file` its
    pages, `read_file` one back, then serve from its `cd`."""
    workspace = workspace_for("ann", None)
    listed = _call("ls", {"path": "My Site"}, "ann", workspace=workspace)[1]
    assert "not a directory" in (listed.get("error") or ""), listed   # nothing there yet
    assert not _write("My Site/index.html", "<h1>Choir</h1>", workspace=workspace).get("error")
    listed = _call("ls", {"path": "My Site"}, "ann", workspace=workspace)[1]
    assert "index.html" in listed.get("output", ""), listed
    read = _call("read_file", {"path": "My Site/index.html"}, "ann", workspace=workspace)[1]
    assert "<h1>Choir</h1>" in read.get("output", ""), read
    assert (_mine(station) / "My Site" / "index.html").read_text(encoding="utf-8") == "<h1>Choir</h1>"
    assert not (ws.root / account_for("ann") / "My Site").exists(), "the page went to the home"


def test_a_project_hires_files_and_its_shell_are_in_its_project(station):
    workspace = workspace_for("ann", "Shop")
    assert not _write("page.html", "<p>shop</p>", workspace=workspace).get("error")
    r = _call("bash", "cat page.html && echo && pwd -P", "ann", session_id="hire-shop", workspace=workspace)[1]
    assert r["stdout"].splitlines() == ["<p>shop</p>", str(_mine(station) / "Shop")], r
    # `B1646`: a hire's run (`ToolPolicy.hired`) is told its project as
    # `$PANTHEON_PROJECTS`, so the runbook's `cd` needs no project added — this
    # asserted `cd "$PANTHEON_PROJECTS"/'Shop'`, the project named twice over
    # by a runbook that never names it. A chat keeps the whole folder.
    from src.agent_tools import ToolBlock
    from src.tool_policy import ToolPolicy
    r = asyncio.run(te.execute_tool_block(
        ToolBlock("bash", "cd \"$PANTHEON_PROJECTS\" && cat page.html"), session_id="hire-shop2", owner="ann",
        workspace=workspace, tool_policy=ToolPolicy(hired=True), security_context=te.NO_TOOL_SECURITY_CONTEXT))[1]
    assert r["stdout"] == "<p>shop</p>", r


def test_a_hires_first_call_may_be_a_file_call(station):
    """The daemon makes the folder before a file call, as before a command: a
    fresh person's first `ls` is admitted, not refused as outside the home."""
    assert not _mine(station, "cat").exists()
    r = _call("ls", {"path": ""}, "cat", workspace=workspace_for("cat", None))[1]
    assert not r.get("error"), r
    assert _mine(station, "cat").is_dir()


def test_before_the_rule_the_file_went_to_the_home(station, ws):
    """The control: the run as it bound nothing in the workstation — the page
    lands in the home, and the folder the runbook serves stays empty."""
    assert not _write("My Site/index.html", "<h1>Choir</h1>").get("error")
    assert (ws.root / account_for("ann") / "My Site" / "index.html").is_file()
    head = next(h for a, h in _file_runbooks() if a == "site-builder")
    r = _call("bash", _fill(head, "My Site") + " && ls", "ann", session_id="old")[1]
    assert r.get("exit_code") != 0, r


def test_a_hires_run_is_given_the_folder_as_the_workstation_names_it(world, station):
    """Its whole run — the prompt's "Active workspace", every tool call, every
    approval — is given the folder as the workstation names it, so a path the
    model reads back is one the workstation has (`workspace_in_workstation`)."""
    factory, sched, seen = world
    db = factory()
    h, _m = _hire(db, "site-builder", owner="ann", inputs={"brief": "A choir's page", "folder": "My Site"})
    seen["answer"] = "Address: http://localhost:8080 Files: index.html Checked: 200"
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["workspace"] == str(_mine(station)), seen["slot"]


# ── nothing is loosened ──────────────────────────────────────────────────────

def test_a_hires_folder_is_its_own_and_no_one_elses(station):
    workspace = workspace_for("ann", None)
    _call("ls", {"path": ""}, "cat", workspace=workspace_for("cat", None))   # cat's folder, made
    other = f"../{P.project_folder('cat')}/x.txt"
    w = _write(other, "mine now", workspace=workspace)
    assert w.get("error") and "outside" in w["error"], w
    assert not (_mine(station, "cat") / "x.txt").exists()


def test_the_workspace_check_admits_the_persons_own_projects_folder_only(station):
    from src.agent_tools.workstation_tools import vet_workspace
    _call("ls", {"path": ""}, "cat", workspace=workspace_for("cat", None))
    (_mine(station) / "Shop").mkdir(parents=True)

    def vet(raw):
        return asyncio.run(vet_workspace("ann", raw))

    assert vet(workspace_for("ann", None)) == str(_mine(station))
    assert vet(workspace_for("ann", "Shop")) == str(_mine(station) / "Shop")
    assert vet(str(_mine(station) / "Shop")) == str(_mine(station) / "Shop")
    assert vet(str(_mine(station, "cat"))) is None, "another person's folder"
    assert vet(str(station)) is None, "the root every folder is in"
    assert vet("/etc") is None
    # An approved action the hire's run parked replays in the folder it was sealed with.
    assert asyncio.run(te._sealed_workspace_holds(workspace_for("ann", None), "ann")) is True


# ── `B1643`: nothing mounted ─────────────────────────────────────────────────

def test_with_nothing_mounted_a_hires_cd_fails_naming_the_folder(bare):
    missing = _mine(bare)
    head = next(h for a, h in _file_runbooks() if a == "site-builder")
    r = _call("bash", _fill(head, "tmp") + " && pwd -P", "ann", session_id="hire-sb",
              workspace=workspace_for("ann", None))[1]
    assert r.get("exit_code") != 0 and r.get("stdout") != os.path.realpath("/tmp"), r
    assert str(missing / "tmp") in r.get("stderr", ""), r
    assert f"Your projects folder, {missing}, is not in this workstation" in r.get("note", ""), r


def test_with_nothing_mounted_a_chats_cd_into_the_folder_says_why_too(bare):
    missing = _mine(bare)
    r = _call("bash", "cd \"$PANTHEON_PROJECTS\"/'tmp' && pwd -P", "ann", session_id="chat")[1]
    assert r.get("exit_code") != 0 and r.get("stdout") != os.path.realpath("/tmp"), r
    assert f"Your projects folder, {missing}, is not in this workstation" in r.get("note", ""), r
    quiet = _call("bash", "echo hi", "ann", session_id="chat2")[1]
    assert "projects folder" not in (quiet.get("note") or ""), quiet


def test_with_nothing_mounted_a_hires_files_go_home_and_it_says_so(bare, ws):
    w = _write("My Site/index.html", "<h1>Choir</h1>", workspace=workspace_for("ann", None))
    assert not w.get("error"), w
    assert (ws.root / account_for("ann") / "My Site" / "index.html").is_file()
    assert "This ran in your workstation home instead." in w.get("note", ""), w


def test_the_daemon_reports_where_the_projects_folder_is(station, bare, ws):
    from src.workstation_client import WorkstationClient
    health = asyncio.run(WorkstationClient(ws.url, ws.token).health())
    assert health["projects_root"] == str(os.path.realpath(bare)) and health["projects_mounted"] is False
    ws.system.shared_roots = [station]
    health = asyncio.run(WorkstationClient(ws.url, ws.token).health())
    assert health["projects_root"] == str(station) and health["projects_mounted"] is True
