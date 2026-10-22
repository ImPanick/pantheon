# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1417`, `B1418`. Somewhere safe to build, and the install kept out of it.

The owner, from a screenshot of the workspace picker: *"this shouldn't be at
the project root folder. That's like accessing system level things which
should be protected. We should have an almost sandboxed route for the LLM to
then create directories etc inside of."* And then: *"make sure the
workstation VM can access the provided directory to be able to run whatever
the LLM needs to test. Securely and safely."*

Three things were measured before anything changed, and each is a case here:

* **The picker opened on `/app`** — the running product's own source tree —
  because `/api/workspace/browse` starts at `path or "~"` and `~` is the
  install directory.
* **With no workspace bound, the agent's file tools could read and write the
  install's records.** Driven through the real `_resolve_tool_path`:
  `auth.json`, `app.db`, `memory.json`, `settings.json`, `sessions.json` and
  `user_prefs.json` were all reachable, because the data directory is the
  default root and the deny list was about SSH keys.
* **`get_workspace` was the dead end in both of the owner's transcripts**:
  *"No workspace is set… use absolute paths"* — true, and a model starting a
  project had no path to use.

What changed: a `projects/` folder under the data directory is where new work
goes; the picker opens there and `get_workspace` names it; the install's
records are refused **by location** (a project's own `auth.json` is fine);
and only `projects/` is shared into the workstation, where the daemon's jail
admits it beside each account's home.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import yaml

from src import tool_execution as te

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A data directory of the install's shape, with every record in it."""
    data = tmp_path / "data"
    data.mkdir()
    for name in ("auth.json", "app.db", "app.db-wal", "app.db-shm", "memory.json",
                 "settings.json", "sessions.json", "user_prefs.json",
                 "cookbook_state.json"):
        (data / name).write_text("{}" if name.endswith(".json") else "")
    (data / "ssh").mkdir()
    (data / "ssh" / "config").write_text("Host x")
    (data / "ssh" / "id_ed25519").write_text("KEY")
    (data / "uploads" / "2026").mkdir(parents=True)
    (data / "uploads" / "2026" / "report.pdf").write_text("pdf")
    (data / "KeystoneInc").mkdir()
    (data / "KeystoneInc" / "app.js").write_text("js")
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    monkeypatch.setattr(te, "_tool_path_roots", lambda: [str(data)])
    return data


def _reachable(path) -> bool:
    try:
        te._resolve_tool_path(str(path))
        return True
    except ValueError:
        return False


# ── B1418: the install's records ────────────────────────────────────────────

@pytest.mark.parametrize("record", [
    "auth.json", "app.db", "app.db-wal", "app.db-shm", "memory.json",
    "settings.json", "sessions.json", "user_prefs.json", "cookbook_state.json",
])
def test_the_installs_records_are_out_of_reach(data_dir, record):
    """Every one of these was reachable before — readable and writable by the
    model's file tools — and `auth.json` holds the install's credentials."""
    assert not _reachable(data_dir / record), record


def test_a_record_added_next_year_is_out_of_reach_too(data_dir):
    """By location, so a state file nobody has written yet is covered on the
    day it appears. A list of names would drift past it."""
    (data_dir / "something_new_state.json").write_text("{}")
    assert not _reachable(data_dir / "something_new_state.json")


def test_a_new_file_beside_the_records_is_refused(data_dir):
    """A fresh `notes.txt` written next to `auth.json` is indistinguishable
    from a record. New work goes in `projects/`."""
    assert not _reachable(data_dir / "notes.txt")


@pytest.mark.parametrize("name", ["config", "id_ed25519"])
def test_the_cookbook_identity_is_out_of_reach(data_dir, name):
    assert not _reachable(data_dir / "ssh" / name)


@pytest.mark.parametrize("name", ["auth.json", "settings.json", "app.db"])
def test_a_projects_own_file_of_the_same_name_is_the_persons(data_dir, name):
    """**The reason the rule is a location and not a name.** A site the agent
    is building may well have its own `auth.json`; refusing the person's own
    files to protect the install's would be a new bug wearing a fix."""
    site = data_dir / "projects" / "site"
    site.mkdir(parents=True)
    (site / name).write_text("theirs")
    assert _reachable(site / name)


@pytest.mark.parametrize("rel", [
    "uploads/2026/report.pdf", "KeystoneInc/app.js", "projects/site/index.html",
])
def test_content_stays_reachable(data_dir, rel):
    """Content lives in subdirectories. Uploads the agent reads, a folder the
    owner made by hand (`KeystoneInc/` was in their own transcript), and
    projects all stay where they were."""
    path = data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    assert _reachable(path), rel


def test_a_workspace_bound_to_the_data_directory_does_not_open_it(data_dir):
    """The workspace branch asks the same question. Bound to the data directory
    itself, every record would otherwise be "inside the workspace"."""
    token = te._active_workspace.set(str(data_dir))
    try:
        assert not _reachable(data_dir / "auth.json")
        (data_dir / "projects").mkdir(exist_ok=True)
        (data_dir / "projects" / "a.txt").write_text("a")
        assert _reachable(data_dir / "projects" / "a.txt")
    finally:
        te._active_workspace.reset(token)


def test_a_symlink_from_a_project_to_a_record_is_refused(data_dir):
    """Root in the workstation can write anything into `/projects`, including
    a link pointing back at a record. Pantheon's tools resolve it with
    `realpath` first, so it is refused as the record it points at."""
    site = data_dir / "projects" / "site"
    site.mkdir(parents=True)
    (site / "innocent.json").symlink_to(data_dir / "auth.json")
    assert not _reachable(site / "innocent.json")


def test_the_refusal_says_where_the_work_belongs(data_dir):
    with pytest.raises(ValueError) as refused:
        te._resolve_tool_path(str(data_dir / "auth.json"))
    message = str(refused.value)
    assert "Pantheon's own records" in message
    assert "projects folder" in message


# ── B1417: the projects folder ──────────────────────────────────────────────

def test_the_projects_folder_is_made_under_the_data_directory(data_dir):
    # `B1424`: one folder per person inside it, by the workstation's name.
    from workstation import protocol as P
    assert te.projects_base() == os.path.join(str(data_dir), "projects")
    root = te.projects_root()
    assert root == os.path.join(str(data_dir), "projects", P.project_folder(None))
    assert os.path.isdir(root)


def test_get_workspace_names_where_projects_go(data_dir):
    """The dead end in both transcripts, closed: with no workspace bound, the
    answer is a place to work, not an instruction to find one."""
    from src.agent_tools.filesystem_tools import GetWorkspaceTool
    token = te._active_workspace.set(None)
    try:
        out = asyncio.run(GetWorkspaceTool().execute("", {}))
    finally:
        te._active_workspace.reset(token)
    assert out["projects_root"] == te.projects_root()
    assert te.projects_root() in out["output"]
    assert "use absolute paths" not in out["output"]


def test_the_picker_opens_on_the_projects_folder_not_the_install(data_dir, monkeypatch):
    """Driven through the real route. `/app` was the default, which is the
    running product."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.workspace_routes as wr

    monkeypatch.setattr(wr, "get_current_user", lambda request: "admin")
    monkeypatch.setattr(wr, "owner_is_admin_or_single_user", lambda owner: True)
    monkeypatch.setattr(wr, "_in_workstation", lambda request, owner: False)
    app = FastAPI()
    builder = getattr(wr, "setup_workspace_routes", None) or getattr(wr, "create_router")
    app.include_router(builder())
    answer = TestClient(app).get("/api/workspace/browse").json()
    # `B1424`: the caller's own folder in it.
    assert answer["path"] == os.path.realpath(te.projects_root("admin"))


# ── the workstation sees projects/ and nothing else of Pantheon's ───────────

def _workstation_volumes():
    compose = yaml.safe_load((ROOT / "docker" / "workstation.yml").read_text())
    return compose["services"]["workstation"]["volumes"]


def _parsed(volume: str):
    """`(source, target)` for one compose volume string.

    Interpolation first: `${APP_DATA_DIR:-./data}` carries its own colon, so a
    plain split reads the variable's default as the container path — which is
    exactly the mistake the first draft of these cases made, and both went red
    for it rather than for anything the compose file said.
    """
    import re
    text = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", volume)
    parts = text.split(":")
    return parts[0], parts[1]


def test_the_workstation_is_given_the_projects_folder():
    assert "${APP_DATA_DIR:-./data}/projects:/projects:z" in _workstation_volumes()


def test_the_workstation_is_given_nothing_else_of_pantheons():
    """`docker/workstation.yml` has said since `P20-01`: *no Pantheon volume
    but the pairing one*. The projects folder is the one exception and it is a
    subdirectory — a mount of `./data` would hand root in the sandbox the
    install's credentials, memory and database."""
    for volume in _workstation_volumes():
        source, _ = _parsed(volume)
        if source.startswith("./data"):
            assert source == "./data/projects", volume


def test_the_daemon_and_pantheon_name_one_projects_folder():
    """The mount's target and the jail's shared root are one constant: a folder
    mounted where the daemon is not looking is a folder the agent cannot use."""
    from workstation import protocol as P
    targets = {_parsed(v)[1]: _parsed(v)[0] for v in _workstation_volumes()}
    assert targets.get(P.PROJECTS_DIR) == "./data/projects", targets


# ── the daemon's jail admits it, and only it ────────────────────────────────

@pytest.fixture
def station(tmp_path):
    from tests.helpers.workstation_daemon import running_workstation
    with running_workstation(tmp_path, sudo=False) as ws:
        yield ws


def _client(ws):
    from src.workstation_client import WorkstationClient
    return WorkstationClient(ws.url, ws.token)


def test_with_sudo_off_the_projects_folder_is_a_place_to_work(station, tmp_path):
    from src.workstation_client import account_for
    projects = tmp_path / "projects"
    projects.mkdir()
    station.system.shared_roots = [projects]
    client, acct = _client(station), account_for(None)
    # `B1424`: the person's own folder in it, made by `ensure`.
    mine = asyncio.run(client.ensure(acct))["projects"]
    (Path(mine) / "index.html").write_text("<h1>hi</h1>")
    got = asyncio.run(client.read(acct, str(Path(mine) / "index.html")))
    assert got["data"] == b"<h1>hi</h1>"


def test_a_symlink_out_of_the_projects_folder_is_refused(station, tmp_path):
    """The same rule as `test_a_symlink_out_of_the_home_is_refused`: the
    request is `realpath`ed before the jail looks at it."""
    from src.workstation_client import WorkstationError, account_for
    projects = tmp_path / "projects"
    projects.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("no")
    station.system.shared_roots = [projects]
    client, acct = _client(station), account_for(None)
    # `B1424`: planted inside the person's own folder, the one place admitted.
    mine = Path(asyncio.run(client.ensure(acct))["projects"])
    (mine / "escape").symlink_to(secret)
    with pytest.raises(WorkstationError) as refused:
        asyncio.run(client.read(acct, str(mine / "escape")))
    assert refused.value.code == "outside_home"


def test_without_the_mount_the_jail_is_exactly_what_it_was(station, tmp_path):
    """A workstation started without the projects folder answers as it always
    did: `shared_roots` names a path that is not a directory, so it admits
    nothing."""
    from src.workstation_client import WorkstationError, account_for
    outside = tmp_path / "outside.txt"
    outside.write_text("there")
    station.system.shared_roots = [tmp_path / "not-mounted"]
    client, acct = _client(station), account_for(None)
    asyncio.run(client.ensure(acct))
    with pytest.raises(WorkstationError) as refused:
        asyncio.run(client.read(acct, str(outside)))
    assert refused.value.code == "outside_home"
    assert "projects" not in str(refused.value), (
        "a folder that is not there should not be offered as somewhere to work")
