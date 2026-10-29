# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1647` — in the workstation `git` and `shell_with_login` work in the
person's own projects folder, where a hire's run works.

Measured before the fix, with the real daemon: `git_tools._Place.resolve`
admitted a path only inside the workstation home, though the daemon's jail
admits the person's own projects folder beside it (`B1417`) and a hire's run
works there (`B1642`). And the place took the hire's folder as Pantheon names
it (`<data>/projects/<name>`), a path the workstation does not have. So
`git status` through the dispatcher with a hire's workspace answered
"… is outside your home, so git does not work there.", and `shell_with_login`
"None is outside your home, so nothing runs there.", whichever name the folder
had.

Now the place names a hire's folder as the workstation does (the bash and file
tools' own `station_folder`), and admits exactly what `vet_workspace` admits —
the home and the person's own projects folder when one is mounted
(`workstation_tools.own_reach`, the one question both ask). Never another
person's folder, never the root every person's folder is in.

Driven (`Law 20`): the real dispatcher (`execute_tool_block`) against the real
workstation daemon (`tests/helpers/workstation_daemon.py`) with its projects
mount, a real repository made by the real `git`.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.agents.runtime import workspace_for
from test_a_hires_files_and_its_cd_meet_in_the_workstation import _mine, bare, data, station  # noqa: F401
from test_the_agents_hands_are_in_the_workstation import _call, people, settings, ws  # noqa: F401
from workstation import protocol as P

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

PASSWORD = "Pw-correct-horse-77"


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    """The git identity and vault tables, in the test's own database."""
    import core.database as cdb
    import src.secret_storage as ss
    from src import vault as V
    engine = create_engine(f"sqlite:///{tmp_path / 'accounts.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.VaultKey.__table__, cdb.VaultItem.__table__,
                                                 cdb.GitIdentity.__table__, cdb.GitCredential.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    V._unlocked_until.clear()
    return factory


def _repo(folder: Path) -> Path:
    """A repository with one commit and one new file, made by the real git."""
    folder.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "ann@example.org",
           "GIT_COMMITTER_NAME": "Ann", "GIT_COMMITTER_EMAIL": "ann@example.org", "HOME": str(folder)}
    for argv in (["init", "-q", "-b", "main"], ["add", "README.md"], ["commit", "-q", "-m", "start"]):
        if argv[0] == "add":
            (folder / "README.md").write_text("the shop\n", encoding="utf-8")
        subprocess.run(["git", *argv], cwd=folder, env=env, check=True, capture_output=True, timeout=30)
    (folder / "new.txt").write_text("new\n", encoding="utf-8")
    return folder


def _workspaces(owner: str, project=None):
    """The hire's folder as Pantheon names it, and as the scheduler hands the
    loop when the workstation can name it (`B1642`)."""
    from src.agent_tools.workstation_tools import workspace_in_workstation
    mine = workspace_for(owner, project)
    return [mine, asyncio.run(workspace_in_workstation(owner, mine))]


def _git(args, owner="ann", workspace=None):
    return _call("git", args, owner, workspace=workspace)[1]


# ── the row ──────────────────────────────────────────────────────────────────

def test_git_status_answers_from_the_hires_projects_folder(station, accounts):
    folder = _repo(_mine(station))
    for workspace in _workspaces("ann"):
        r = _git({"action": "status"}, workspace=workspace)
        assert r.get("ran_in") == "workstation" and r.get("exit_code") == 0, (workspace, r)
        assert r["repo"] == str(folder), r
        assert "## main" in r["output"] and "?? new.txt" in r["output"], r


def test_git_works_in_a_hires_project_and_in_a_repository_named_from_the_folder(station, accounts):
    shop = _repo(_mine(station) / "Shop")
    for workspace in _workspaces("ann", "Shop"):
        r = _git({"action": "log"}, workspace=workspace)
        assert r.get("exit_code") == 0 and r["repo"] == str(shop) and "start" in r["output"], r
    for workspace in _workspaces("ann"):
        r = _git({"action": "status", "repo": "Shop"}, workspace=workspace)
        assert r.get("exit_code") == 0 and r["repo"] == str(shop), r


def test_shell_with_login_starts_in_the_hires_projects_folder(station, accounts):
    from src import vault as V
    s = accounts()
    V.create(s, "ann", {"label": "Svc", "addresses": "127.0.0.1:9", "username": "agent", "secret": PASSWORD})
    s.close()
    (_mine(station) / "Shop").mkdir(parents=True)
    for workspace in _workspaces("ann", "Shop"):
        r = _call("shell_with_login", {"logins": ["Svc"], "command": "pwd -P"}, "ann", workspace=workspace)[1]
        assert r.get("ran_in") == "workstation" and r.get("exit_code") == 0, r
        assert r["output"].splitlines()[0] == str(_mine(station) / "Shop"), r
    r = _call("shell_with_login", {"logins": ["Svc"], "command": "pwd", "cwd": f"../../{P.project_folder('cat')}"},
              "ann", workspace=_workspaces("ann", "Shop")[1])[1]
    assert r.get("exit_code") == 1 and "outside your home and your projects folder" in r["error"], r


def test_a_hires_login_shell_is_told_its_project(station, accounts):
    """`B1646` on this runner too: in a hire's run (`ToolPolicy.hired`) the
    command's `$PANTHEON_PROJECTS` is the folder the run works in."""
    import src.tool_execution as te
    from src import vault as V
    from src.agent_tools import ToolBlock
    from src.tool_policy import ToolPolicy
    s = accounts()
    V.create(s, "ann", {"label": "Svc", "addresses": "127.0.0.1:9", "username": "agent", "secret": PASSWORD})
    s.close()
    shop = _mine(station) / "Shop"
    shop.mkdir(parents=True)
    for workspace in _workspaces("ann", "Shop"):
        body = json.dumps({"logins": ["Svc"], "command": 'pwd -P; printf "%s\\n" "$PANTHEON_PROJECTS"'})
        r = asyncio.run(te.execute_tool_block(
            ToolBlock("shell_with_login", body), session_id="hire-run", owner="ann", workspace=workspace,
            tool_policy=ToolPolicy(hired=True), security_context=te.NO_TOOL_SECURITY_CONTEXT))[1]
        assert r.get("exit_code") == 0 and r["output"].splitlines()[:2] == [str(shop), str(shop)], r


# ── nothing is loosened ──────────────────────────────────────────────────────

def test_another_persons_folder_and_the_root_are_still_refused(station, accounts):
    _call("ls", {"path": ""}, "cat", workspace=workspace_for("cat", None))   # cat's folder, made
    theirs = _repo(_mine(station, "cat"))
    _repo(_mine(station))
    for workspace in _workspaces("ann"):
        for repo in (f"../{P.project_folder('cat')}", str(theirs), str(station), "/etc"):
            r = _git({"action": "status", "repo": repo}, workspace=workspace)
            assert r.get("exit_code") == 1 and "repo" not in r, (repo, r)
            assert f"is outside your home and your projects folder ({_mine(station)})" in r["error"], (repo, r)


def test_with_nothing_mounted_git_runs_in_the_home_and_says_why(bare, accounts):
    """`B1643`: a hire's projects folder that is not there — git runs in the
    home, as the shell does, and says why; it never names the missing folder
    as a place it worked."""
    r = _git({"action": "status"}, workspace=workspace_for("ann", None))
    assert r.get("ran_in") == "workstation", r
    assert f"Your projects folder, {_mine(bare)}, is not in this workstation" in r.get("note", ""), r
    assert "outside" not in json.dumps(r), r
