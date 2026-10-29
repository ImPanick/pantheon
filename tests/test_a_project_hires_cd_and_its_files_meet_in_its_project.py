# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1646` — with a project, a hire's file tools and its runbook's `cd` reach
the same folder, on either machine.

Measured before the fix: a hire's run works in its project
(`runtime.workspace_for(owner, "Shop")` is `<projects>/Shop`, `B1434`), and its
file tools read a relative path from there — `write_file site/index.html`
wrote `<projects>/Shop/site/index.html` — while every runbook's
`cd "$PANTHEON_PROJECTS"/'<folder>'` (`B1640`) and every
`os.environ["PANTHEON_PROJECTS"]` started from the person's whole projects
folder: the `cd` went to `<projects>/site`, which was not there, on this
machine and in the workstation alike. The prompt told the model to add the
project itself (`$PANTHEON_PROJECTS/Shop`), and no runbook does.

The one rule now: in a hire's run (`ToolPolicy.hired`, the task engine's)
`$PANTHEON_PROJECTS` names the folder the run works in — its project, or the
whole projects folder with none (`tool_execution.run_projects_folder`) — for
every runner on either machine, so the runbook's own `cd` and the file tools'
relative paths meet. Every other call (a chat) keeps the whole projects
folder, where the skills say a new project goes.

Driven (`Law 20`): the real dispatcher (`execute_tool_block`) with the
workspace a hire's run binds (`workspace_for`, and as the scheduler names it
for the workstation, `workspace_in_workstation`) and the hire's mark, on this
machine and against the real workstation daemon
(`tests/helpers/workstation_daemon.py`), each runbook's own `cd` read from its
file; and a hire's whole run through the scheduler, its `write_file` and its
`bash` the real ones.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents.catalogue import catalogue, get_agent
from src.agents.runtime import system_prompt, workspace_for
from src.tool_policy import ToolPolicy
from test_a_folder_with_a_space_is_one_folder import _cd_spans, _fill
from test_a_hires_files_and_its_cd_meet_in_the_workstation import (  # noqa: F401 — fixtures
    _file_runbooks, _mine, bare, data, station,
)
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, people, settings, ws,
)
from workstation import protocol as P

PROJECT = "Shop"
#: Folders a hire is given: spaced, and with a `'`.
NAMES = ["My Site", "Tom's site"]
WHOLE = 'cd "$PANTHEON_PROJECTS"'
PY_READS = 'os.environ["PANTHEON_PROJECTS"]'


def _hire_call(tool, content, owner, *, workspace, session_id="hire-run"):
    """A call as a hire's run makes it: the task engine's mark (`B1606`)."""
    if not isinstance(content, str):
        content = json.dumps(content)
    return asyncio.run(te.execute_tool_block(
        ToolBlock(tool, content), session_id=session_id, owner=owner, workspace=workspace,
        tool_policy=ToolPolicy(hired=True), security_context=te.NO_TOOL_SECURITY_CONTEXT))[1]


def _heads():
    """Each runbook's `cd`, and nothing after it — read from the library."""
    return [(agent, span.split(" && ", 1)[0]) for agent, span in _cd_spans()]


def _into(head: str, name: str) -> str:
    """The runbook's `cd` filled with `name`, ending in that folder either way
    (`cd "$PANTHEON_PROJECTS"` alone is followed by the folder, as the two
    runbooks that start there name theirs)."""
    return _fill(head, name) + (f" && cd {shlex.quote(name)}" if head == WHOLE else "")


@pytest.fixture
def host(settings, people, data):
    """Pantheon's own machine, no workstation; the person's projects folder
    has the project and nothing else in it."""
    root = Path(te.projects_root("boss", create=True))
    (root / PROJECT).mkdir()
    return Path(os.path.realpath(root))


# ── the row, on Pantheon's machine ───────────────────────────────────────────

def test_with_a_project_a_hires_cd_and_its_files_meet_here(host):
    workspace = workspace_for("boss", PROJECT)
    assert workspace == str(host / PROJECT)
    heads = _heads()
    assert {"site-builder", "secret-sniffer"} <= {a for a, _h in heads}, heads
    for name in NAMES:
        for agent, head in heads:
            text = f"{agent} wrote this in {name}"
            w = _hire_call("write_file", {"path": f"{name}/probe.txt", "content": text}, "boss",
                           workspace=workspace)
            assert not w.get("error"), (agent, w)
            r = _hire_call("bash", _into(head, name) + " && cat probe.txt && echo && pwd -P", "boss",
                           workspace=workspace, session_id=f"hire-{agent}")
            assert r.get("exit_code") == 0, (agent, head, r)
            assert r["stdout"].splitlines() == [text, str(host / PROJECT / name)], (agent, head, r)
        assert not (host / name).exists(), "the cd's folder beside the project"


def test_python_and_a_background_job_are_told_the_project_here(host, monkeypatch, tmp_path):
    """The seven runbooks that read a file under `os.environ["PANTHEON_PROJECTS"]`
    find the one the file tools wrote at that relative path."""
    readers = sorted(m.id for m in catalogue(None)[0] if PY_READS in m.runbook)
    assert len(readers) >= 7 and "etl-runner" in readers, readers
    from src import bg_jobs
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "jobs.json")
    workspace = workspace_for("boss", PROJECT)
    assert not _hire_call("write_file", {"path": "data/sales.csv", "content": "day,total\n1,5\n"}, "boss",
                          workspace=workspace).get("error")
    r = _hire_call("python", f"import os; print(open(os.path.join({PY_READS}, 'data/sales.csv')).read(), end='')",
                   "boss", workspace=workspace)
    assert r.get("exit_code") == 0 and r["stdout"].splitlines() == ["day,total", "1,5"], r
    r = _hire_call("bash", '#!bg\nprintf %s "$PANTHEON_PROJECTS"', "boss", workspace=workspace)
    job = bg_jobs._JOBS_DIR / r["bg_job_id"]
    for _ in range(200):
        if Path(f"{job}.exit").exists():
            break
        time.sleep(0.05)
    assert Path(f"{job}.log").read_text(encoding="utf-8") == str(host / PROJECT)


# ── the row, in the workstation ──────────────────────────────────────────────

def _station_workspaces(owner: str, project):
    """The hire's folder as Pantheon names it, and as the scheduler hands the
    loop when the workstation can name it (`B1642`) — each call meets both."""
    from src.agent_tools.workstation_tools import workspace_in_workstation
    mine = workspace_for(owner, project)
    return [mine, asyncio.run(workspace_in_workstation(owner, mine))]


def test_with_a_project_a_hires_cd_and_its_files_meet_in_the_workstation(station, ws):
    (_mine(station) / PROJECT).mkdir(parents=True)
    runbooks = _file_runbooks()
    assert {"site-builder"} <= {a for a, _h in runbooks}, runbooks
    named, there = _station_workspaces("ann", PROJECT)
    assert there == str(_mine(station) / PROJECT) != named
    for workspace in (named, there):
        for name in NAMES:
            for agent, head in runbooks:
                text = f"{agent} wrote this in {name} from {workspace}"
                w = _hire_call("write_file", {"path": f"{name}/probe.txt", "content": text}, "ann",
                               workspace=workspace)
                assert w.get("ran_in") == "workstation" and not w.get("error"), (agent, w)
                r = _hire_call("bash", _into(head, name) + " && cat probe.txt && echo && pwd -P", "ann",
                               workspace=workspace, session_id=f"hire-{agent}")
                assert r.get("ran_in") == "workstation" and r.get("exit_code") == 0, (agent, head, r)
                assert r["stdout"].splitlines() == [text, str(_mine(station) / PROJECT / name)], (agent, r)
    assert not any((_mine(station) / name).exists() for name in NAMES), "the cd's folder beside the project"


def test_python_is_told_the_project_in_the_workstation(station):
    (_mine(station) / PROJECT).mkdir(parents=True)
    for workspace in _station_workspaces("ann", PROJECT):
        assert not _hire_call("write_file", {"path": "data/sales.csv", "content": "day,total\n"}, "ann",
                              workspace=workspace).get("error")
        r = _hire_call("python", f"import os; print({PY_READS}); print(open(os.path.join({PY_READS}, "
                                 "'data/sales.csv')).read(), end='')", "ann", workspace=workspace)
        assert r.get("ran_in") == "workstation", r
        assert r["stdout"].splitlines() == [str(_mine(station) / PROJECT), "day,total"], r


# ── what stays as it was ─────────────────────────────────────────────────────

SHOWN = 'printf %s "$PANTHEON_PROJECTS"'


def test_a_chat_keeps_the_whole_projects_folder_here(host):
    """A chat whose workspace is a project still has the whole projects folder
    as `$PANTHEON_PROJECTS` — where the skills tell it a new project goes;
    only a hire's run is told its own folder."""
    r = _call("bash", SHOWN, "boss", workspace=workspace_for("boss", PROJECT))[1]
    assert r["stdout"] == te.projects_root("boss"), r


def test_a_chat_keeps_the_whole_projects_folder_in_the_workstation(station):
    (_mine(station) / PROJECT).mkdir(parents=True)
    for workspace in _station_workspaces("ann", PROJECT):
        r = _call("bash", SHOWN, "ann", workspace=workspace)[1]
        assert r.get("ran_in") == "workstation" and r["stdout"] == str(_mine(station)), r


def test_a_hire_with_no_project_is_told_the_whole_projects_folder(host):
    r = _hire_call("bash", SHOWN, "boss", workspace=workspace_for("boss", None))
    assert r["stdout"] == str(host), r


def test_a_hire_with_no_project_is_told_the_whole_projects_folder_in_the_workstation(station):
    for workspace in _station_workspaces("ann", None):
        r = _hire_call("bash", SHOWN, "ann", workspace=workspace)
        assert r.get("ran_in") == "workstation" and r["stdout"] == str(_mine(station)), r


def test_with_nothing_mounted_a_project_hires_cd_still_fails_naming_the_folder(bare):
    """`B1643` holds: the run starts in the home and says why, and the `cd`
    fails naming the projects folder that is not there — never `/<folder>`."""
    missing = _mine(bare)
    head = next(h for a, h in _file_runbooks() if a == "site-builder")
    r = _hire_call("bash", _fill(head, "tmp") + " && pwd -P", "ann", workspace=workspace_for("ann", PROJECT))
    assert r.get("exit_code") != 0 and r.get("stdout") != os.path.realpath("/tmp"), r
    assert str(missing / "tmp") in r.get("stderr", ""), r
    assert f"Your projects folder, {missing}, is not in this workstation" in r.get("note", ""), r


# ── the prompt ───────────────────────────────────────────────────────────────

def test_the_prompt_says_the_variable_names_the_project():
    """It said `$PANTHEON_PROJECTS/Shop`, which is now a folder inside the
    project."""
    manifest = get_agent(None, "site-builder")
    hire = SimpleNamespace(name="Site Builder", project=PROJECT)
    prompt = system_prompt(manifest, hire, owner="boss")
    line = next(ln for ln in prompt.splitlines() if "“Shop”" in ln)
    assert "$PANTHEON_PROJECTS names it" in line and "$PANTHEON_PROJECTS/" not in line, line


# ── a hire's whole run ───────────────────────────────────────────────────────

def test_a_project_hires_page_and_its_cd_meet_in_a_real_run(monkeypatch):
    """Site Builder hired for the project “Shop” with the folder “My Site”,
    run by the scheduler with the evaluation harness's isolated world and
    scripted model — except that its `bash` is the real one, not the world's
    answer: it writes its page with `write_file`, then serves from its
    runbook's own `cd`, the folder filled in."""
    from src.agents import evals as E
    from src.agents import hires as H

    manifest = get_agent(None, "site-builder")
    head = next(h for a, h in _heads() if a == "site-builder")
    command = _fill(head, "My Site") + " && cat index.html && echo && pwd -P"
    case = {"id": "b1646", "inputs": {"brief": "A shop's page", "folder": "My Site"},
            "world": {"files": {f"{PROJECT}/README.md": "the shop"}},
            "script": [{"call": [["write_file", {"path": "My Site/index.html", "content": "<h1>Shop</h1>"}]]},
                       {"call": [["bash", {"command": command}]]},
                       {"say": "**Address**\n- http://localhost:8080/\n**Files**\n- My Site/index.html\n"
                               "**Checked**\n- 200"}],
            "checks": []}
    real_make = H.make_hire
    monkeypatch.setattr(H, "make_hire", lambda db, **kw: real_make(db, project=PROJECT, **kw))
    real_answer = E.World.answer
    monkeypatch.setattr(E.World, "answer", lambda self, tool, content: None if tool == "bash"
                        else real_answer(self, tool, content))
    ran = []
    real_impl = te._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real_impl(block, *a, **kw)
        ran.append((block.tool_type, out[1]))
        return out

    monkeypatch.setattr(te, "_execute_tool_block_impl", spy)

    async def go():
        with E.isolated() as (factory, data_dir):
            await E.run_case(manifest, case, factory=factory, data_dir=data_dir)
            return os.path.realpath(os.path.join(te.projects_root(E.EVAL_OWNER), PROJECT, "My Site"))

    folder = asyncio.run(go())
    wrote = [r for tool, r in ran if tool == "write_file"]
    assert wrote and not wrote[0].get("error"), ran
    bash = [r for tool, r in ran if tool == "bash"]
    assert bash, ran
    assert bash[0].get("exit_code") == 0, bash[0]
    assert bash[0]["stdout"].splitlines() == ["<h1>Shop</h1>", folder], bash[0]
