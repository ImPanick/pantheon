# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1692` — a write onto a name a link made in the same command lands where
the link points, and is read there.

Measured before the fix, with `notes.md` there: `ln notes.md new.md; echo x >
new.md` and `ln -s notes.md l; echo x > l` gave `call_destroys` `None` —
`execute_code` alone — and real `bash` emptied `notes.md`: the `>` target was
looked at before the run (nothing there), and `ln` without `-f` added
nothing. A hire's `destructive: never` let both run.

Now (`src/shell_reading.py`, `src/run_files.py`): `ln`, `ln -s`, `link`, `cp
-l`/`-s` and Python's `os.link`/`os.symlink` are read for the names they make
(`links` findings, as GNU reads their words — `ln TARGET`, `-t`, a folder
there, `-T`; a symbolic link's text from its own folder unless `-r`), and a
write onto that name after it, or onto a name inside a folder one points at,
is looked at where it lands too, through any link there: a file that was
there before the run makes it a replacement, *written through the link*. A
link whose name or target cannot be known leaves a write after it unknown —
destructive, the cautious reading. A write that takes a name away (`gzip
l`) takes the link, not its target, and stays as it was. And a name a link
made is not the run's own afterwards: the run's record of "nothing was there"
(`B1669`) is dropped for it, so writing it in a later command is looked at
again, even after a command that asked for itself (`ln -f`).

Measured on the shipped evals: no call makes a link — 0 of 377 `bash` and 0
of 81 `python` calls changed reading by it.

Driven (`Law 20`): the real reader and the run's record over a real folder;
real `ln` and `bash` showing the write goes through; the real gate and
dispatcher running real `bash` under a hire's `destructive: never`; and the
real workstation daemon.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _home, _on, people, settings, ws,
)

NOTES = "Ana's notes — keep these"
THERE = "which was there before this run began"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's notes, and a folder with a page."""
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    (proj / "notes.md").write_text(NOTES, encoding="utf-8")
    (proj / "sub" / "old.md").write_text("old", encoding="utf-8")
    return proj


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def _reads(folder: Path, command: str, tool: str = "bash"):
    return call_destroys(tool, command, _files(folder))


def _through(why: str, link: str, target: str) -> str:
    return f"{why} writes through the link {link} over {target}, {THERE}"


#: Each command, and what it writes over through which link.
THROUGH = (
    ("ln notes.md new.md; echo x > new.md", "a > redirect", "new.md", "notes.md"),
    ("ln -s notes.md l; echo x > l", "a > redirect", "l", "notes.md"),
    ("link notes.md n2 && date | tee n2", "tee", "n2", "notes.md"),
    ("cp -l notes.md c; printf x > c", "a > redirect", "c", "notes.md"),
    ("ln -s ../notes.md sub/l; echo x > sub/l", "a > redirect", "sub/l", "../notes.md"),
    ("ln -sr notes.md sub/l; echo x > sub/l", "a > redirect", "sub/l", "notes.md"),
    ("ln -t sub notes.md; echo x > sub/notes.md", "a > redirect", "sub/notes.md", "notes.md"),
    ("ln -s sub/old.md && echo x > old.md", "a > redirect", "old.md", "sub/old.md"),
    ("cd sub && ln -s ../notes.md n && echo x > n", "a > redirect", "n", "../notes.md"),
    ("ln -s notes.md a && ln -s a b && echo x > b", "a > redirect", "b", "notes.md"),
    ("ln -s sub d; echo y > d/old.md", "a > redirect", "d", "sub/old.md"),
    ("ln -s sub d; cp elsewhere/old.md d", "cp", "d", "sub/old.md"),
    ("cp -rl sub mirror; echo x > mirror/old.md", "a > redirect", "mirror", "sub/old.md"),
    ("sh -c 'ln notes.md n2'; curl -so n2 http://localhost/x", "curl -o", "n2", "notes.md"),
)


@pytest.mark.parametrize("command,why,link,target", THROUGH)
def test_a_write_through_a_link_onto_a_file_that_was_there_is_destructive(folder, command, why,
                                                                         link, target):
    """The row's `Verify:`, one way of making a link at a time."""
    assert _reads(folder, command) == _through(why, link, target)


def test_cp_s_and_pythons_links_are_read_too(folder):
    """`cp -s` names its target as written (from the folder it runs in, the
    only place `cp` makes a relative one); Python's `os.symlink`/`os.link`
    are read wherever they are in the code, before its commands."""
    assert _reads(folder, f"cp -s {folder}/notes.md c; echo > c") == \
        _through("a > redirect", "c", f"{folder}/notes.md")
    for code in ("import os, subprocess\nos.symlink('notes.md', 'l')\n"
                 "subprocess.run('echo x > l', shell=True)",
                 "import os, subprocess\nsubprocess.run('echo x > l', shell=True) if "
                 "os.link(src='notes.md', dst='l') is None else None"):
        assert _reads(folder, code, "python") == _through("a > redirect", "l", "notes.md"), code


def test_onto_a_link_to_nothing_that_was_there_it_is_a_plain_write(folder):
    """A link to a new path, a write before the link or onto another name,
    an append, a symbolic link whose text names a file beside it that was
    not there, a copy of a name not in the folder linked to, and a write
    that takes the link away: nothing that was there is written over."""
    for command in ("ln -s fresh.md l; echo x > l",
                    "ln -s notes.md l",
                    "echo x > l; ln -s notes.md l",
                    "ln notes.md new.md; echo x > other.md",
                    "ln notes.md new.md; echo x >> new.md",
                    "ln -s notes.md sub/l; echo x > sub/l",
                    "ln -s sub d; cp new.md d",
                    "ln -s notes.md l; gzip -f l",
                    "[ -e l ] || ln -s fresh.md l; echo x > l"):
        assert _reads(folder, command) is None, command


def test_a_link_whose_name_or_target_cannot_be_known_leaves_the_write_unknown(folder):
    """A target filled in when it runs, or a name — which any write after it
    may be — whose target was there; a link on another machine is the far
    side's."""
    assert _reads(folder, 'ln -s "$x" l; echo y > l') == \
        "it cannot be known whether $x, where the link l points, was there before this run began"
    assert _reads(folder, 'ln notes.md "$x"; echo y > out.txt') == \
        f"it cannot be known whether {_through('a > redirect', '$x', 'notes.md')}"
    assert _reads(folder, 'ln -s notes.md "$x"; echo y > out.txt') == \
        "it cannot be known whether notes.md, where the link $x points, was there before this run began"
    assert _reads(folder, 'ln fresh.md "$x"; echo y > out.txt') is None
    assert _reads(folder, "ssh nas 'ln -s notes.md l'; echo y > l") is None


def test_a_name_a_link_made_is_not_the_runs_own_in_a_later_command(folder):
    """The run keeps what it saw at a path the first time (`B1669`), so its
    own `>`'s file is its own draft. A link's name is not: once the command
    that makes it has run — read with a write beside it, or asking for
    itself (`ln -f`) — writing that name later writes the person's notes,
    and is looked at again."""
    files = _files(folder)
    first = "ln notes.md new.md; echo hi > other.txt"
    assert call_destroys("bash", first, files) is None
    subprocess.run(["bash", "-c", first], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo gone > new.md", files) == \
        f"a > redirect replaces new.md, {THERE}"

    files = _files(folder)
    assert call_destroys("bash", "echo draft > mine.md", files) is None
    subprocess.run(["bash", "-c", "echo draft > mine.md"], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo again > mine.md", files) is None, "its own draft"
    run = ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}), files=files)
    asked = run.decision_for("bash", "ln -f notes.md mine.md")
    assert asked.allowed is False and "ln -f replaces whatever had the link's name" in asked.reason
    subprocess.run(["bash", "-c", "ln -f notes.md mine.md"], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo gone > mine.md", files) == \
        f"a > redirect replaces mine.md, {THERE}"


# ── the real programs, under a hire's never ─────────────────────────────────

def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("ln") is None, reason="coreutils is not installed")
def test_the_write_really_goes_through_and_a_never_refuses_it(folder, people):
    """Real `bash` empties the person's notes through each kind of link —
    the premise — and under a hire's `destructive: never` the same command
    is refused and nothing is written; a link to a new file runs."""
    for command in ("ln notes.md new.md; echo gone > new.md", "ln -s notes.md l; echo gone > l"):
        copy = folder.parent / f"copy-{uuid.uuid4().hex[:6]}"
        shutil.copytree(folder, copy)
        subprocess.run(["bash", "-c", command], cwd=copy, check=True, timeout=30)
        assert (copy / "notes.md").read_text(encoding="utf-8") == "gone\n", command

        refused = _bash(_never(folder), folder, command)
        assert refused.get("blocked") is True, refused
        link = command.split("; ")[0].split()[-1]
        assert f"({_through('a > redirect', link, 'notes.md')})" in refused["error"]
        assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
        assert not (folder / link).exists(), "nothing ran"

    ran = _bash(_never(folder), folder, "ln -s fresh.md l2; echo made > l2")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "fresh.md").read_text(encoding="utf-8") == "made\n"


def test_in_the_workstation_the_write_is_looked_at_where_the_link_points(ws, settings, people):
    """The workstation is asked where the link's name and its target are:
    a never refuses the write through it, and nothing is written."""
    _on(settings, ws)
    files = RunFiles(None, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / "notes.md").write_text(NOTES, encoding="utf-8")
    command = "ln -s notes.md l; echo gone > l"

    async def go():
        await files.look("bash", command)
        return (await te.execute_tool_block(ToolBlock("bash", command), owner="ann",
                                            session_id=files.session_id, security_context=run))[1]

    refused = asyncio.run(go())
    assert refused.get("blocked") is True, refused
    assert (f"(a > redirect writes through the link l over notes.md in your workstation, {THERE})"
            in refused["error"])
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES
