# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1696` — a copy that keeps a symbolic link as one makes a name a write
goes through, and it is read where it lands.

Measured before the fix, with `mylink` → `notes.md`: `cp -a mylink copy;
echo x > copy` gave `call_destroys` `None` and real `bash` emptied
`notes.md` — only the links a command makes itself (`ln`, `link`, `cp -l`/
`-s`, `os.link`/`os.symlink`, `B1692`) were read, not one it copies. Which
copies keep a link, measured (coreutils 9.4): `cp -P`, `-d`, `-a`, `-r`
(and `-R -L -P`, `-La`: the last of `-L`/`-P`/`-H`/`-d`/`-a` wins), and
`cp -rH` for those inside a folder; not plain `cp`, `-L`, `-aL`, `-rH`'s
own sources, or `--preserve=links` (which keeps hard links among what it
copies, not symbolic ones as links). And `rsync -l` (in `-a`), not `-L` or
`--no-l` — read from its manual; no `rsync` is installed here.

Now (`src/shell_reading.py`, `src/run_files.py`): such a copy is a `links`
finding marked `copied` (`named`, `deep`, `inside`), and when a write after
it is onto the copy, or onto a name inside a copied folder, the run reads
the source there: a symbolic link's text, from the copy's own folder, is
where the write lands (`_copied`), and on through any link there. A source
the run cannot read — filled in when it runs, on another machine, one the
command itself links or copies first, or in the workstation, whose daemon
says a name is a link but not its text — is a link whose target cannot be
known: destructive, the cautious reading. In the workstation the copy's name
is also not the run's own afterwards where it copies a link (`_linked`); on
this machine the run's record is kept by real path, so it never was.

And, found here: a name *inside* a folder a link or copy makes was kept as
the run's own (`B1692`'s `_linked` dropped only the folder's name), so after
`cp -rl sub mirror && echo x > mirror/old.md` — asked, and run — a later
`echo y > mirror/old.md` wrote the person's `sub/old.md` with no card. The
run's record now drops every name under such a folder (`RunFiles.forget`,
`_forget_under`).

Measured on the shipped evals: no call copies with `cp` or `rsync` — 0 of
380 `bash` calls changed reading by it.

Driven (`Law 20`): the real reader and the run's record over a real folder
of real links; real `cp` and `bash` showing the write goes through; the real
gate and dispatcher running real `bash` under a hire's `destructive: never`;
and the real workstation daemon.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.run_files import RunFiles
from src.shell_reading import read_shell
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _home, _on, people, settings, ws,
)

NOTES = "Ana's notes — keep these"
THERE = "which was there before this run began"


def _links(root: Path) -> None:
    """The person's links: one beside the notes, one a folder down pointing
    up, one absolute, one to a folder, and a folder holding one."""
    (root / "mylink").symlink_to("notes.md")
    (root / "sub" / "up").symlink_to("../notes.md")
    (root / "abs").symlink_to(root / "notes.md")
    (root / "dirlink").symlink_to("sub")
    (root / "tree").mkdir()
    (root / "tree" / "in").symlink_to("../notes.md")
    (root / "tree" / "plain").write_text("a page", encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    proj = tmp_path / "proj"
    for d in ("sub", "box", "deep/er"):
        (proj / d).mkdir(parents=True)
    (proj / "notes.md").write_text(NOTES, encoding="utf-8")
    (proj / "sub" / "old.md").write_text("old", encoding="utf-8")
    _links(proj)
    return proj


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


def _through(link: str, target: str) -> str:
    return f"a > redirect writes through the link {link} over {target}, {THERE}"


#: Each copy of a link, a write after it, and where it lands.
THROUGH = (
    ("cp -a mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp -P mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp -d mylink copy && echo x > copy", "copy", "notes.md"),
    ("cp -r mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp --no-deref mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp -La mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp -R -L -P mylink copy; echo x > copy", "copy", "notes.md"),
    ("cp -a sub/up box; echo x > box/up", "box/up", "../notes.md"),
    ("cp -a -t box sub/up; echo x > box/up", "box/up", "../notes.md"),
    ("cp -a sub/up sub/up2; echo x > sub/up2", "sub/up2", "../notes.md"),
    ("cp -a abs deep/er/c; echo x > deep/er/c", "deep/er/c", None),
    ("cp -a dirlink dl; echo x > dl/old.md", "dl", "sub/old.md"),
    ("cp -a tree t2; echo x > t2/in", "t2/in", "../notes.md"),
    ("cp -rH tree t3; echo x > t3/in", "t3/in", "../notes.md"),
    ("cp -a mylink copy; ln -s copy l2; echo x > l2", "l2", "notes.md"),
    ("rsync -a mylink copy; echo x > copy", "copy", "notes.md"),
    ("rsync -l mylink copy; echo x > copy", "copy", "notes.md"),
    ("rsync -a tree/ t4; echo x > t4/in", "t4/in", "../notes.md"),
    ("sh -c 'cp -a mylink copy'; echo x | tee copy", "copy", "notes.md"),
)


@pytest.mark.parametrize("command,link,target", THROUGH)
def test_a_write_onto_a_copied_link_lands_where_it_points(folder, command, link, target):
    """The row's `Verify:`: a write onto a symbolic link the command copied,
    pointing at a file that was there, is destructive."""
    target = target or str(folder / "notes.md")
    said = _reads(folder, command)
    if "tee" in command:
        assert said == f"tee writes through the link {link} over {target}, {THERE}"
    else:
        assert said == _through(link, target)


def test_what_copies_no_link_or_lands_on_nothing_that_was_there(folder):
    """Plain `cp`, `-L` last, `-rH`'s own source, `--preserve=links`, a
    file or a page copied with `-a`, a link whose text points from the
    copy's folder at nothing there (`up2` → `../notes.md` above the
    folder; `box/mylink` → `box/notes.md`), `rsync` without `-l` or with
    `-L`/`--no-l`, a dry run, what is in a linked folder (`dirlink/`,
    `dirlink/.`: its names, not the link), a write before the copy, and an
    append."""
    for command in ("cp mylink copy; echo x > copy",
                    "cp -aL mylink copy; echo x > copy",
                    "cp -rH mylink copy; echo x > copy",
                    "cp --preserve=links mylink copy; echo x > copy",
                    "cp -a notes.md c; echo x > c",
                    "cp -a tree t2; echo x > t2/plain",
                    "cp -a sub/up up2; echo x > up2",
                    "cp -a mylink box; echo x > box/mylink",
                    "rsync -r tree/ t4; echo x > t4/in",
                    "rsync -aL tree/ t4; echo x > t4/in",
                    "rsync -a --no-l tree/ t4; echo x > t4/in",
                    "rsync -an mylink copy; echo x > copy",
                    "rsync -a dirlink/ copy; echo x > copy/fresh.md",
                    "cp -a dirlink/. copy; echo x > copy/fresh.md",
                    "echo x > copy; cp -a mylink copy",
                    "cp -a mylink copy; echo x >> copy"):
        assert _reads(folder, command) is None, command


def test_a_copy_whose_source_cannot_be_read_leaves_the_write_unknown(folder):
    """A source filled in when it runs, one the command links first (not
    there yet when the run looks), and one on another machine."""
    assert _reads(folder, 'cp -a "$x" copy; echo y > copy') == (
        "it cannot be known whether what $x points at, where the link copy points, was there "
        "before this run began")
    assert _reads(folder, "ln -s notes.md a; cp -P a c2; echo x > c2") == (
        "it cannot be known whether what a points at, where the link c2 points, was there "
        "before this run began")
    assert _reads(folder, "rsync -a nas.lan:site/ local; echo x > local/index.html") == (
        "it cannot be known whether what nas.lan:site/index.html points at, where the link "
        "local/index.html points, was there before this run began")


def test_the_reading_names_which_links_a_copy_keeps():
    """`Finding.copied`, as the options in order say."""
    def copied(command: str) -> list:
        return [f.copied for f in read_shell(command) if f.kind == "links"]
    assert copied("cp -a a b") == ["deep"]
    assert copied("cp -P a b") == ["named"]
    assert copied("cp -rH a b") == ["inside"]
    assert copied("cp -al a b") == ["", "deep"]       # `B1692`'s hard links, and the links kept
    assert copied("cp -rl a b") == [""]               # with `-l` and no `-P`, it follows
    assert copied("cp a b") == copied("cp -aL a b") == []
    assert copied("cp -as a b") == [""]               # `cp -s` makes links: `B1692`'s
    assert copied("rsync -avz a b") == ["deep"]
    assert copied("rsync -l a b") == ["named"]
    assert copied("rsync -aL a b") == copied("rsync -a --no-l a b") == []


# ── after the command has run ───────────────────────────────────────────────

def test_a_copied_link_is_never_the_runs_own(folder):
    """On this machine the run's record is kept by real path: once `cp -a`
    has made the link, writing it in a later command is looked at where it
    lands — whether or not the copy was read with a write beside it."""
    files = _files(folder)
    assert call_destroys("bash", "cp -a mylink copy", files) is None
    subprocess.run(["bash", "-c", "cp -a mylink copy"], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo gone > copy", files) == f"a > redirect replaces copy, {THERE}"


def test_a_name_inside_a_folder_a_link_makes_is_not_the_runs_own(folder):
    """`cp -rl sub mirror && echo x > mirror/old.md` asks (`B1692`); run, it
    makes `mirror/old.md` a hard link to the person's `sub/old.md` — so a
    later write onto it is looked at again, though the run saw nothing
    there when it read the first."""
    files = _files(folder)
    first = "cp -rl sub mirror && echo x > mirror/old.md"
    assert call_destroys("bash", first, files) == _through("mirror", "sub/old.md")
    subprocess.run(["bash", "-c", "cp -rl sub mirror"], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo gone > mirror/old.md", files) == \
        f"a > redirect replaces mirror/old.md, {THERE}"


def test_a_link_made_into_a_folder_leaves_the_runs_own_files_there_its_own(folder):
    """What the run forgets is the names a link makes and what is under
    them — not the folder it makes them in: the run's own draft beside a
    link `ln -s` made in the same folder stays its own."""
    files = _files(folder)
    assert call_destroys("bash", "echo draft > mine.md", files) is None
    subprocess.run(["bash", "-c", "echo draft > mine.md"], cwd=folder, check=True, timeout=30)
    for command in ("ln -s sub/old.md", "ln -s -t sub ../notes.md"):
        assert call_destroys("bash", command, files) is None
        subprocess.run(["bash", "-c", command], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo again > mine.md", files) is None, "its own draft"
    assert call_destroys("bash", "echo gone > old.md", files) == \
        f"a > redirect replaces old.md, {THERE}"


# ── the real programs, under a hire's never ─────────────────────────────────

def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("cp") is None, reason="coreutils is not installed")
def test_the_write_really_goes_through_and_a_never_refuses_it(folder, people):
    """Real `bash` empties the person's notes through a copied link — the
    premise — and under a hire's `destructive: never` the same command is
    refused and nothing is written; a copy of a page runs."""
    for command in ("cp -a mylink copy; echo gone > copy", "cp -a tree t2; echo gone > t2/in"):
        trial = folder.parent / f"trial-{uuid.uuid4().hex[:6]}"
        shutil.copytree(folder, trial, symlinks=True)
        subprocess.run(["bash", "-c", command], cwd=trial, check=True, timeout=30)
        assert (trial / "notes.md").read_text(encoding="utf-8") == "gone\n", command

        refused = _bash(_never(folder), folder, command)
        assert refused.get("blocked") is True, refused
        assert "a > redirect writes through the link" in refused["error"]
        assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
        assert not (folder / "copy").exists() and not (folder / "t2").exists(), "nothing ran"

    ran = _bash(_never(folder), folder, "cp -a notes.md c; echo made > c")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "c").read_text(encoding="utf-8") == "made\n"
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES


def test_in_the_workstation_a_copied_link_is_one_whose_target_cannot_be_known(ws, settings,
                                                                             people):
    """The workstation's daemon says a name is a link but not its text: a
    never refuses a write onto a copy of one, and nothing is written; a
    copy of a page runs; and a copy of a link made in one command is not
    the run's own in the next."""
    _on(settings, ws)
    files = RunFiles(None, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / "notes.md").write_text(NOTES, encoding="utf-8")
    (home / "mylink").symlink_to("notes.md")

    def bash(command: str) -> dict:
        async def go():
            await files.look("bash", command)
            return (await te.execute_tool_block(ToolBlock("bash", command), owner="ann",
                                                session_id=files.session_id,
                                                security_context=run))[1]
        return asyncio.run(go())

    refused = bash("cp -a mylink copy; echo gone > copy")
    assert refused.get("blocked") is True, refused
    assert ("(it cannot be known whether what mylink points at in your workstation, where the "
            f"link copy points, was there before this run began)") in refused["error"]
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES

    ran = bash("cp -a notes.md page.md; echo made > page.md")
    assert ran.get("exit_code") == 0, ran
    assert bash("echo again > page.md").get("exit_code") == 0, "the run's own copy"

    assert bash("cp -a mylink copy").get("exit_code") == 0
    assert os.path.islink(home / "copy")
    later = bash("echo gone > copy")
    assert later.get("blocked") is True, later
    assert f"(a > redirect replaces copy in your workstation, {THERE})" in later["error"]
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES
