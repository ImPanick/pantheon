# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1640` — a hire's first command lands in its folder on either machine.

Measured before the fix: `$PANTHEON_PROJECTS` was set in one place,
`workstation/agentd.py`'s `_exec_prepare`. Twenty-five runbooks (31 of the
library's 34 `cd`s) began `cd "$PANTHEON_PROJECTS"/'<folder>' && …` (`B1634`),
and on an install with no workstation the shell `_direct_fallback` starts had
Pantheon's own environment, so that `cd` went to `/<folder>` — nothing, and the
rest of the command never ran, or a folder at the root of the machine (a hire's
`tmp` is `/tmp`). Archive Sorter, Roadmap Keeper and Status Reporter used a
relative `cd '<folder>'`, which reaches the folder only where the shell starts
in the projects folder: here, and never in the workstation, whose shell starts
in the home.

The one rule now: wherever a hire's shell runs, `$PANTHEON_PROJECTS` is the
person's own projects folder — the daemon's `/projects/<name>` in the
workstation, `tool_execution.projects_root` here (`projects_env`, given to
`bash` and `python`, to a `#!bg` job and to `shell_with_login`'s shell) — and
every runbook's `cd` starts from it.

Driven (`Law 20`): every runbook's own `cd`, read from its file and filled the
way it says, sent through the real dispatcher (`execute_tool_block`) with the
workspace the hire's run binds (`runtime.workspace_for`) — on this machine with
no workstation, and in the real workstation daemon
(`tests/helpers/workstation_daemon.py`) with its projects mount; and a hire's
whole run through the scheduler, its scripted first call run by the real `bash`.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agents.catalogue import get_agent
from src.agents.runtime import workspace_for
from test_a_folder_with_a_space_is_one_folder import _cd_spans, _fill
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _on, people, settings, ws,
)
from workstation import protocol as P

#: Folders a hire is given: spaced, and with a `'`.
NAMES = ["My Site", "Tom's site"]
#: The runbooks whose `cd` was relative until this row.
WERE_RELATIVE = {"archive-sorter", "roadmap-keeper", "status-reporter"}
WHOLE = 'cd "$PANTHEON_PROJECTS"'


@pytest.fixture
def host(settings, people, monkeypatch, tmp_path):
    """Pantheon's own machine, no workstation: the data folder is the test's."""
    import src.constants as constants
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    root = Path(te.projects_root("boss", create=True))
    for name in NAMES:
        (root / name).mkdir()
    return root


@pytest.fixture
def station(ws, settings, people, tmp_path, monkeypatch):
    """The workstation with its projects mount, as the compose overlay gives it
    (and Pantheon's data folder the test's: a hire's run names its folder
    here too, `B1642`)."""
    import src.constants as constants
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path / "data"))
    _on(settings, ws)
    mount = tmp_path / "projects-mount"
    mine = mount / P.project_folder("ann")
    for name in NAMES:
        (mine / name).mkdir(parents=True)
    ws.system.shared_roots = [mount]
    return Path(os.path.realpath(mine))


def _heads():
    """Each runbook's `cd`, and nothing after it — the part that decides
    where the rest of its command runs."""
    return [(agent, span.split(" && ", 1)[0]) for agent, span in _cd_spans()]


def _lands(head: str, name: str, root: Path) -> Path:
    return root if head == WHOLE else root / name


# ── the one rule ─────────────────────────────────────────────────────────────

def test_every_runbooks_cd_starts_from_the_projects_folder():
    """No runbook's `cd` depends on where the shell happened to start."""
    heads = _heads()
    assert WERE_RELATIVE <= {a for a, _h in heads}
    for agent, head in heads:
        assert head == WHOLE or head.startswith(WHOLE + "/'"), (agent, head)


# ── on Pantheon's machine, with no workstation ───────────────────────────────

@pytest.mark.parametrize("project", [None, "Shop"])
def test_each_runbooks_cd_lands_in_the_hires_folder_here(host, project):
    """With the workspace the hire's run binds — its project, or the whole
    projects folder — the `cd` reaches the folder inside it.

    `B1646`: as a hire's run makes the call (`ToolPolicy.hired`). With a
    project this asserted the `cd` landed beside the project, in the whole
    projects folder, while the run's file tools wrote inside the project; a
    hire's `$PANTHEON_PROJECTS` now names the project
    (`tests/test_a_project_hires_cd_and_its_files_meet_in_its_project.py`)."""
    from src.agent_tools import ToolBlock
    from src.tool_policy import ToolPolicy
    base = host / project if project else host
    for name in NAMES:
        (base / name).mkdir(parents=True, exist_ok=True)
    workspace = workspace_for("boss", project)
    assert workspace == os.path.realpath(base)
    for name in NAMES:
        for agent, head in _heads():
            r = asyncio.run(te.execute_tool_block(
                ToolBlock("bash", _fill(head, name) + " && pwd -P"), session_id=f"hire-{agent}", owner="boss",
                workspace=workspace, tool_policy=ToolPolicy(hired=True),
                security_context=te.NO_TOOL_SECURITY_CONTEXT))[1]
            want = _lands(head, name, base)
            assert r.get("exit_code") == 0 and r.get("stdout") == str(want.resolve()), (agent, head, r)
            assert "ran_in" not in r, r


def test_python_and_a_background_job_are_told_the_folder_too(host, monkeypatch, tmp_path):
    from src import bg_jobs
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "jobs.json")
    workspace = workspace_for("boss", None)
    r = _call("python", "import os; print(os.environ['PANTHEON_PROJECTS'])", "boss", workspace=workspace)[1]
    assert r["stdout"] == te.projects_root("boss"), r
    r = _call("bash", "#!bg\nprintf %s \"$PANTHEON_PROJECTS\"", "boss", session_id="c1", workspace=workspace)[1]
    job = bg_jobs._JOBS_DIR / r["bg_job_id"]
    for _ in range(200):
        if Path(f"{job}.exit").exists():
            break
        time.sleep(0.05)
    assert Path(f"{job}.log").read_text(encoding="utf-8") == te.projects_root("boss")


def test_a_command_with_a_login_is_told_the_folder_too(host):
    """`shell_with_login`'s shell here (`git_tools._Place`)."""
    from src.agent_tools.git_tools import _Place
    r = asyncio.run(_Place("boss", None).run('printf %s "$PANTHEON_PROJECTS"', str(host), {}, 10))
    assert r["stdout"] == te.projects_root("boss"), r


def test_without_the_variable_a_runbooks_cd_leaves_the_projects_folder():
    """The control: the shell as `_direct_fallback` started it before — the
    folder a hire names is looked for at the root of the machine."""
    env = {k: v for k, v in os.environ.items() if k != P.PROJECTS_ENV}
    head = next(h for a, h in _heads() if a == "bug-fixer")
    done = subprocess.run(["bash", "-c", _fill(head, "tmp") + " && pwd -P"], env=env, capture_output=True,
                          text=True, timeout=30)
    assert done.stdout.strip() == os.path.realpath("/tmp"), done


# ── in the workstation ───────────────────────────────────────────────────────

def test_each_runbooks_cd_lands_in_the_hires_folder_in_the_workstation(station):
    """With the workspace the hire's run binds — its projects folder, which
    the workstation names as it does (`B1642`; it bound none, and the shell
    started in the home) — the daemon's `$PANTHEON_PROJECTS` takes the `cd`
    to the folder."""
    workspace = workspace_for("ann", None)
    for name in NAMES:
        for agent, head in _heads():
            r = _call("bash", _fill(head, name) + " && pwd -P", "ann", session_id=f"hire-{agent}",
                      workspace=workspace)[1]
            assert r.get("ran_in") == "workstation", r
            assert r.get("exit_code") == 0 and r.get("stdout") == str(_lands(head, name, station)), (agent, head, r)


def test_the_old_relative_cd_missed_the_folder_in_the_workstation(station):
    """The control: Roadmap Keeper's `cd` as it was, in the same workstation
    with the workspace the run bound before `B1642` (none: the home)."""
    r = _call("bash", "cd 'My Site' && pwd -P", "ann", session_id="hire-roadmap-keeper")[1]
    assert r.get("ran_in") == "workstation" and r.get("exit_code") != 0, r
    assert "My Site" in (r.get("stderr") or r.get("output") or ""), r


# ── a hire's whole run ───────────────────────────────────────────────────────

def test_a_hires_first_command_runs_in_its_folder_in_a_real_run(monkeypatch):
    """Changelog Writer hired for "My Shop", run by the scheduler with the
    evaluation harness's isolated world and scripted model — except that its
    `bash` is the real one, not the world's answer — and its first call is
    its runbook's own `cd`, the folder filled in."""
    from src.agents import evals as E

    manifest = get_agent(None, "changelog-writer")
    span = next(s for a, s in _cd_spans() if a == "changelog-writer")
    command = _fill(span.split(" && ", 1)[0], "My Shop") + " && pwd -P"
    case = {"id": "b1640", "inputs": {"folder": "My Shop"},
            "world": {"files": {"My Shop/README.md": "the shop"}},
            "script": [{"call": [["bash", {"command": command}]]}, {"say": "Done."}], "checks": []}
    real_answer = E.World.answer
    monkeypatch.setattr(E.World, "answer", lambda self, tool, content: None if tool == "bash"
                        else real_answer(self, tool, content))
    ran = []
    real_impl = te._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real_impl(block, *a, **kw)
        ran.append((block.tool_type, block.content, out[1]))
        return out

    monkeypatch.setattr(te, "_execute_tool_block_impl", spy)

    async def go():
        with E.isolated() as (factory, data):
            await E.run_case(manifest, case, factory=factory, data_dir=data)
            return os.path.realpath(os.path.join(te.projects_root(E.EVAL_OWNER), "My Shop"))

    folder = asyncio.run(go())
    bash = [r for tool, content, r in ran if tool == "bash"]
    assert bash, ran
    assert bash[0].get("exit_code") == 0 and bash[0].get("stdout") == folder, bash[0]
