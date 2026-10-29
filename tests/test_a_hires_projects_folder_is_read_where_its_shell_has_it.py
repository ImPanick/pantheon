# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1681` — a command's path spelled against `$PANTHEON_PROJECTS` is looked
for where its shell will have it, so a hire's `>` onto a new file in its
folder is a plain write.

Measured before the fix: `cd "$PANTHEON_PROJECTS"/w && echo hi > brand-new.md`
read as *it cannot be known whether brand-new.md was there before this run
began*: the reader marked every path or `cd` with a `$` in it as filled in
when the command runs, and `B1669`'s cautious reading made it destructive — so
under a hire's `destructive: never` every runbook that `cd`s into its folder
(`B1634`) and writes a new file with `>` was refused, which is why Speed
Logger moved its header to `>>`. Yet the run knows the value: Pantheon sets
the variable itself (`tool_execution.projects_env`, `B1640`; a hire's own
folder, `B1646`).

Now the reader keeps a path that starts with one variable and nothing else
filled in (`"$PANTHEON_PROJECTS"/w`, `${PANTHEON_PROJECTS}/w`), and the run
fills it in by the one rule the shell's environment is set by
(`tool_execution.projects_folder_for`, `RunFiles.shell_values`): a hire's
folder in a hire's run, the person's projects folder in a chat, and `$HOME`
as `~`. Unquoted, a value the shell would split or glob is not known; any
other variable is not known. In the workstation the run asks there as
before, and a hire's `$PANTHEON_PROJECTS` is the folder Pantheon hands its
command (`run_env`); a chat's there is the daemon's own and stays unknown.

Speed Logger's header stays on `>>`: its `>` runs only when `speed.csv` is
not there, behind a `[ -f speed.csv ] ||` this reader cannot see, so every
run after the first would read it as writing over the log
(`test_speed_logger_still_logs_under_its_never`).

Driven (`Law 20`): the real gate and dispatcher running real `bash` with a
hire's mark (`ToolPolicy.hired`), whose environment sets the variable, on
this machine and against the real workstation daemon.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents.runtime import workspace_for
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from src.tool_policy import ToolPolicy
from test_a_hires_files_and_its_cd_meet_in_the_workstation import _mine, data, station  # noqa: F401
from test_the_agents_hands_are_in_the_workstation import people, settings, ws  # noqa: F401

THERE = "which was there before this run began"
NEW = 'cd "$PANTHEON_PROJECTS"/w && echo hi > brand-new.md'
OVER = 'cd "$PANTHEON_PROJECTS"/w && echo hi > notes.md'


@pytest.fixture
def folder(tmp_path):
    """A hire's folder, holding its `w` with the person's notes in it."""
    ws_ = tmp_path / "hire"
    (ws_ / "w").mkdir(parents=True)
    (ws_ / "w" / "notes.md").write_text("keep", encoding="utf-8")
    return ws_


def _files(folder, owner="boss", hired=True) -> RunFiles:
    return RunFiles(str(folder), owner, session_id=f"s-{uuid.uuid4().hex[:8]}", hired=hired)


def test_a_hires_new_file_in_its_folder_is_a_plain_write_and_its_old_one_is_not(folder):
    """The row's `Verify:`, read by the reader and the run's record."""
    files = _files(folder)
    assert call_destroys("bash", NEW, files) is None
    assert call_destroys("bash", OVER, files) == f"a > redirect replaces notes.md, {THERE}"
    for spelled in ('"$PANTHEON_PROJECTS"/w/notes.md', "${PANTHEON_PROJECTS}/w/notes.md",
                    "$PANTHEON_PROJECTS/w/notes.md"):
        assert call_destroys("bash", f"echo hi > {spelled}", files) == \
            f"a > redirect replaces {spelled.replace(chr(34), '')}, {THERE}", spelled
        assert call_destroys("bash", f"echo hi > {spelled.replace('notes', 'new')}", files) is None


def test_what_the_shell_fills_in_some_other_way_stays_unknown(tmp_path):
    """Another variable, a second expansion, or — unquoted — a value with a
    space the shell would split: not known, so destructive, as before."""
    spaced = tmp_path / "my hire"
    (spaced / "w").mkdir(parents=True)
    files = _files(spaced)
    for command, shown in (('cd "$PROJECT"/w && echo hi > new.md', "new.md"),
                           ('echo hi > "$PANTHEON_PROJECTS/$NAME"', "$PANTHEON_PROJECTS/$NAME"),
                           ("cd $PANTHEON_PROJECTS/w && echo hi > new.md", "new.md")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether {shown} was there before this run began", command
    assert call_destroys("bash", NEW, files) is None, "quoted, the space is part of one path"


def test_home_is_read_as_the_shells_home(folder, tmp_path, monkeypatch):
    """`$HOME` is `~`: the agent's folder the tools set it to."""
    home = tmp_path / "agent-home"
    home.mkdir()
    (home / "notes.md").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(te, "_AGENT_WORKDIR", str(home))
    files = _files(folder)
    assert call_destroys("bash", 'echo hi > "$HOME"/notes.md', files) == \
        f"a > redirect replaces $HOME/notes.md, {THERE}"
    assert call_destroys("bash", 'cd "$HOME" && echo hi > new.md', files) is None


def test_a_chats_variable_is_the_persons_projects_folder(data, people):
    """Not a hire's run: the variable is the person's whole projects folder
    (`B1640`), and it is read there."""
    root = Path(te.projects_root("boss"))
    (root / "w").mkdir()
    (root / "w" / "notes.md").write_text("keep", encoding="utf-8")
    files = _files(root / "somewhere-else", hired=False)
    assert call_destroys("bash", OVER, files) == f"a > redirect replaces notes.md, {THERE}"
    assert call_destroys("bash", NEW, files) is None


# ── through the real gate and shell ─────────────────────────────────────────

def _hired_bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    """A `bash` call as a hire's run makes it: the task engine's mark, so the
    real shell is given `$PANTHEON_PROJECTS` as the hire's folder."""
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           tool_policy=ToolPolicy(hired=True), security_context=run)
    return asyncio.run(go())[1]


def test_a_hires_never_writes_a_new_file_in_its_folder_and_refuses_the_persons(folder, people):
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))
    made = _hired_bash(run, folder, NEW)
    assert made.get("exit_code") == 0, made
    assert (folder / "w" / "brand-new.md").read_text(encoding="utf-8") == "hi\n", \
        "the shell's variable is the folder the reading looked in"
    refused = _hired_bash(run, folder, OVER)
    assert refused.get("blocked") is True, refused
    assert f"(a > redirect replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "w" / "notes.md").read_text(encoding="utf-8") == "keep"


# ── in the workstation ──────────────────────────────────────────────────────

def test_in_the_workstation_a_hires_variable_is_the_folder_pantheon_hands_it(station):
    """A hire's run there: the loop asks the workstation (`RunFiles.look`)
    with the folder its command is given as `$PANTHEON_PROJECTS`; a new file
    is made by the real shell under a never, the person's is refused. A
    chat's variable there is the daemon's own, and stays unknown."""
    workspace = workspace_for("ann", None)
    there = _mine(station) / "w"
    there.mkdir(parents=True)
    (there / "notes.md").write_text("keep", encoding="utf-8")
    files = RunFiles(workspace, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}", hired=True)
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)

    async def go():
        out = []
        for command in (NEW, OVER):
            await files.look("bash", command)
            out.append((await te.execute_tool_block(
                ToolBlock("bash", command), owner="ann", session_id=files.session_id,
                workspace=workspace, tool_policy=ToolPolicy(hired=True), security_context=run))[1])
        return out

    made, refused = asyncio.run(go())
    assert made.get("ran_in") == "workstation" and made.get("exit_code") == 0, made
    assert (there / "brand-new.md").read_text(encoding="utf-8") == "hi\n"
    assert refused.get("blocked") is True, refused
    assert f"(a > redirect replaces notes.md in your workstation, {THERE})" in refused["error"]
    assert (there / "notes.md").read_text(encoding="utf-8") == "keep"

    chat = RunFiles(workspace, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    asyncio.run(chat.look("bash", NEW))
    assert call_destroys("bash", NEW, chat) == \
        "it cannot be known whether brand-new.md in your workstation was there before this run began"
