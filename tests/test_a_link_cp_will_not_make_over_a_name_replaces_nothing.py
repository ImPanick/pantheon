# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1697` — `cp -l` or `cp -s` onto a name that is there writes nothing over
it, because GNU `cp` refuses; told to replace it, it is destructive.

Measured (coreutils 9.4): `cp -l a b` and `cp -s a b` with `b` there exit 1,
*cannot create hard link 'b' to 'a': File exists*, and leave `b` as it was —
into a folder too (`cp -l a dir/`), and with `-u` or `--update=all`; with
`-f`, `--force`, `--remove-destination`, or `-i` answered yes, `b` becomes the
link (`copy.c` tells `create_hard_link` and `force_symlinkat` to replace on
either). Before the fix, the reading (from `B1669`) read every `cp` without
`-n` or `-b` as writing over its destination: with `b` there, `call_destroys
('bash', 'cp -l notes.md b')` said *cp replaces b* — a card, or a hire's
*never* refusing, for a command that cannot replace anything.

Now (`src/shell_reading.py`, `_copies`): with `-l`/`-s` and none of
`-f`/`--force`/`--remove-destination`/`-i`/`--interactive`, `cp` writes over
nothing it names — the links it makes are still read (`B1692`) — and its
long options are read as `getopt_long` reads them, so `--forc` is `--force`
and `--li` is `--link`.

Measured on the shipped evals: no call runs `cp -l` or `cp -s` — 0 of 380
`bash` calls changed reading by it.

Driven (`Law 20`): the real reader over a real folder; real `cp` showing the
refusal and the replacement; and the real gate and dispatcher running real
`bash` under a hire's `destructive: never`.
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
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — a fixture

THERE = "which was there before this run began"
MINE = "the person's own page"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: notes, the person's page `b`, a folder holding
    a page named as the notes are, and a copy of that folder in `dest`."""
    proj = tmp_path / "proj"
    (proj / "dir").mkdir(parents=True)
    (proj / "notes.md").write_text("notes", encoding="utf-8")
    (proj / "b").write_text(MINE, encoding="utf-8")
    (proj / "dir" / "notes.md").write_text(MINE, encoding="utf-8")
    (proj / "dest" / "dir").mkdir(parents=True)
    (proj / "dest" / "dir" / "notes.md").write_text(MINE, encoding="utf-8")
    return proj


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


REFUSED = ("cp -l notes.md b", "cp -s notes.md b", "cp --link notes.md b",
           "cp --symbolic-link notes.md b", "cp --li notes.md b", "cp -lu notes.md b",
           "cp -l --update=all notes.md b", "cp -l notes.md dir/", "cp -l notes.md dir",
           "cp -lt dir notes.md", "cp -rl dir dest", "cp -sv notes.md b")


@pytest.mark.parametrize("command", REFUSED)
def test_a_link_onto_a_name_that_is_there_writes_nothing_over_it(folder, command):
    """The row's `Verify:`: `cp -l a b` with `b` there is a plain write."""
    assert _reads(folder, command) is None


REPLACED = (("cp -lf notes.md b", "b"), ("cp -l --force notes.md b", "b"),
            ("cp -l --remove-destination notes.md b", "b"), ("cp -li notes.md b", "b"),
            ("cp -sf notes.md b", "b"), ("cp --li --forc notes.md b", "b"),
            ("cp -l --remove-d notes.md b", "b"), ("cp -l --interactive notes.md b", "b"),
            ("cp -lf notes.md dir/", "dir/notes.md"), ("cp -f -t dir -l notes.md", "dir/notes.md"))


@pytest.mark.parametrize("command,shown", REPLACED)
def test_told_to_replace_it_it_is_destructive(folder, command, shown):
    """…and with `-f` or `--remove-destination` (or `-i`, answered yes) it
    is destructive, however the option is written."""
    assert _reads(folder, command) == f"cp replaces {shown}, {THERE}"


def test_busyboxs_cp_takes_the_name_away_and_is_read_so(folder):
    """BusyBox's `cp`, built with `FEATURE_NON_POSIX_CP` (its default),
    unlinks a name that is there and links (`copy_file.c`'s
    `ask_and_unlink`): named as BusyBox's, it is read as replacing."""
    assert _reads(folder, "busybox cp -l notes.md b") == f"cp replaces b, {THERE}"
    assert _reads(folder, "busybox cp -s notes.md b") == f"cp replaces b, {THERE}"


def test_what_else_it_writes_is_read_as_before(folder):
    """A copy without `-l`/`-s` still replaces; one that never overwrites
    still does not; and a `>` onto the name after a refused link still
    writes over the page that was there."""
    assert _reads(folder, "cp notes.md b") == f"cp replaces b, {THERE}"
    assert _reads(folder, "cp -lfn notes.md b") is None
    assert _reads(folder, "cp -l notes.md b; echo x > b") == f"a > redirect replaces b, {THERE}"


# ── the real programs ───────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("cp") is None, reason="coreutils is not installed")
def test_real_cp_refuses_and_replaces_as_read(tmp_path):
    """The premise, measured: without `-f` `cp` refuses and the name keeps
    what it held; with `-f` or `--remove-destination` the name is replaced."""
    for flags, replaced in (("-l", False), ("-s", False), ("-lf", True), ("-sf", True),
                            ("-l --remove-destination", True)):
        work = tmp_path / f"w-{uuid.uuid4().hex[:6]}"
        work.mkdir()
        (work / "a").write_text("a", encoding="utf-8")
        (work / "b").write_text(MINE, encoding="utf-8")
        done = subprocess.run(["bash", "-c", f"cp {flags} a b"], cwd=work, capture_output=True,
                              text=True, timeout=30)
        if replaced:
            assert done.returncode == 0, done.stderr
            assert (work / "b").read_text(encoding="utf-8") == "a", flags
        else:
            assert done.returncode == 1 and "File exists" in done.stderr, done.stderr
            assert (work / "b").read_text(encoding="utf-8") == MINE, flags


def _bash(folder: Path, command: str) -> dict:
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}),
                                 files=_files(folder))

    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("cp") is None, reason="coreutils is not installed")
def test_under_a_never_the_refused_link_runs_and_the_forced_one_does_not(folder, people):
    """Under a hire's `destructive: never`: `cp -l notes.md b` runs — `cp`
    itself refuses, and the page is as it was; `cp -lf` is refused by the
    gate, saying what it would replace, and the page is as it was."""
    ran = _bash(folder, "cp -l notes.md b")
    assert not ran.get("blocked"), ran
    assert "File exists" in (ran.get("output") or "") + (ran.get("error") or ""), ran
    assert (folder / "b").read_text(encoding="utf-8") == MINE

    refused = _bash(folder, "cp -lf notes.md b")
    assert refused.get("blocked") is True, refused
    assert f"(cp replaces b, {THERE})" in refused["error"]
    assert (folder / "b").read_text(encoding="utf-8") == MINE
