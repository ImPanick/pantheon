# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1698` — a name a move or an archive puts in place is read where a
write onto it lands.

Measured before the fix, with `mylink` → `notes.md`: `mv -n mylink copy;
echo x > copy` and `mkdir out && tar -xf a.tar -C out && echo x > out/l`
(the archive holding `l` → `../notes.md`) gave `call_destroys` `None`, and
real `bash` emptied `notes.md` — as did `unzip` (with `-o` or not) and `git
checkout` of a branch holding such a link. And plainer: `mv -n notes.md n2;
echo x > n2` empties the person's notes outright, read as a new file; `mv`
without `-n` asks for itself, but the name it moved the notes to stayed the
run's own afterwards, to `bash` and to `write_file` alike.

Now (`src/shell_reading.py`, `src/run_files.py`): a move is a `links`
finding marked `moved` — `mv`, `mv -n`, `mv -t`, `git mv` — read as a copy
that keeps every link: a symbolic link moved is one with the same text, read
from its new folder; and where no link is on the way, the name is the
source's own file, so a write onto it, or a name in a moved folder, lands on
the source's place (*… replaces notes.md (moved to n2), which was there
before this run began*), a removal too (`gzip n2`). And `tar -x`, `unzip`,
`7z x` and git's `checkout`, `switch`, `restore`, `pull`, `merge`, `clone`…
are marked `unpacked`: what they put is not read (no archive is opened), so a
write after one at a member it names, or anywhere in the folder it unpacks
unnamed members into — anywhere at all where that folder is unknown, as git's
work tree is — is unknown: *it cannot be known whether what tar -x puts at
out/l is a link to a file that was there before this run began*. A copy into
a folder is read at each name it writes there (`cp page out/`). The names a
move or (in the workstation) an archive puts in place are not the run's own
afterwards (`RunFiles.forget`, `_linked`), `write_file`'s drafts included;
a name that cannot be known clears them all.

And, found here: a link made into a folder from a name filled in when it runs
(`ln "$x" box/`) was read as making `box/$x`, those very characters; it is
any name in `box` now. And `tar -xP` (`B1680`'s reading) keeps a member's
leading `/`, so from inside a folder `mkdir` made it wrote the person's notes
unread — where it writes is unknown now.

Measured on the shipped evals: 10 of 380 `bash` calls changed reading (Archive
Sorter's and Photo Organiser's `mv -n`, a far `mv`, a `git checkout -- .`),
and none changed whether it is destructive; 0 of 81 `python` calls changed.

Driven (`Law 20`): the real reader and the run's record over a real folder
of real links; real `mv`, `tar`, `unzip`, `git` and `bash` showing the write
goes through; the real gate and dispatcher under a hire's `destructive:
never`; the run's record across commands; and the real workstation daemon.
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import tarfile
import uuid
import zipfile
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


def _archives(root: Path) -> None:
    """`a.tar` and `b.zip`, each holding `l` → `../notes.md` and a page."""
    with tarfile.open(root / "a.tar", "w") as tar:
        link = tarfile.TarInfo("l")
        link.type, link.linkname = tarfile.SYMTYPE, "../notes.md"
        tar.addfile(link)
        page = tarfile.TarInfo("page")
        page.size = 6
        tar.addfile(page, io.BytesIO(b"a page"))
    with zipfile.ZipFile(root / "b.zip", "w") as z:
        link = zipfile.ZipInfo("l")
        link.create_system, link.external_attr = 3, 0o120777 << 16     # a symbolic link
        z.writestr(link, "../notes.md")
        z.writestr("page", "a page")


@pytest.fixture
def folder(tmp_path):
    proj = tmp_path / "proj"
    for d in ("sub", "box"):
        (proj / d).mkdir(parents=True)
    (proj / "notes.md").write_text(NOTES, encoding="utf-8")
    (proj / "sub" / "old.md").write_text("old", encoding="utf-8")
    (proj / "mylink").symlink_to("notes.md")
    (proj / "sub" / "up").symlink_to("../notes.md")
    _archives(proj)
    return proj


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


def _through(link: str, target: str, why: str = "a > redirect") -> str:
    return f"{why} writes through the link {link} over {target}, {THERE}"


def _moved(name: str, to: str, why: str = "a > redirect", does: str = "replaces") -> str:
    return f"{why} {does} {name} (moved to {to}), {THERE}"


def _unpacked(why: str, name: str) -> str:
    return (f"it cannot be known whether what {why} puts at {name} is a link to a file that "
            f"was there before this run began")


#: Each move or unpacking, a write after it, and what the card says.
READ = (
    # a link moved: the same text, from its new folder
    ("mv -n mylink copy; echo x > copy", _through("copy", "notes.md")),
    ("mv -b mylink copy; echo x > copy", _through("copy", "notes.md")),
    ("mv --no-clobber mylink copy && echo x > copy", _through("copy", "notes.md")),
    ("mv -n sub/up box/; echo x > box/up", _through("box/up", "../notes.md")),
    ("mv -n -t box sub/up; echo x | tee box/up", _through("box/up", "../notes.md", "tee")),
    # the person's own file, at its new name
    ("mv -n notes.md n2; echo x > n2", _moved("notes.md", "n2")),
    ("mv -n -T notes.md n2 && cp sub/old.md n2", _moved("notes.md", "n2", "cp")),
    ("mv -n notes.md box && echo x > box/notes.md", _moved("notes.md", "box/notes.md")),
    ("mv -n sub s2; echo x > s2/old.md", _moved("sub/old.md", "s2/old.md")),
    ("mv -n notes.md n2; gzip n2", _moved("notes.md", "n2", "gzip", "removes")),
    ("git mv notes.md n3 && echo x > n3", _moved("notes.md", "n3")),
    ("mv -n notes.md n2; ln -s n2 l; echo x > l", _through("l", "notes.md")),
    # what an archive or git puts
    ("mkdir out && tar -xf a.tar -C out && echo x > out/l", _unpacked("tar -x", "out/l")),
    ("mkdir out && tar -xkf a.tar -C out l && echo x > out/l", _unpacked("tar -x", "out/l")),
    ("tar -xf a.tar --skip-old-files; echo x > l", _unpacked("tar -x", "l")),
    ("mkdir out && tar -xf a.tar -C out && cp sub/old.md out/l", _unpacked("tar -x", "out/l")),
    ("unzip -q b.zip -d out2 && echo y > out2/l", _unpacked("unzip", "out2/l")),
    ("unzip -o b.zip -d out2 && echo y > out2/l", _unpacked("unzip", "out2/l")),
    ("7z x a.7z -oout3 && echo y > out3/l", _unpacked("7z x", "out3/l")),
    ("git checkout other && echo x > l", _unpacked("git checkout", "l")),
    ("git pull && echo x > ../notes.md", _unpacked("git pull", "../notes.md")),
    ("git clone ../repo r && echo x > r/l", _unpacked("git clone", "r/l")),
    ("tar -xkPf a.tar -C box; echo x > ../fresh.md", _unpacked("tar -x", "../fresh.md")),
    # found here: with `-P` a member's own name may be anywhere
    ("mkdir o && tar -xPf a.tar -C o", f"it cannot be known whether what a.tar holds {THERE[6:]}"),
)


@pytest.mark.parametrize("command,said", READ)
def test_a_write_onto_what_a_move_or_an_archive_put_is_read_where_it_lands(folder, command, said):
    """The row's `Verify:`: a write after the command onto a name `mv -n`
    moved a link (or the person's file) to, or into a folder an archive was
    unpacked into, is destructive where it lands on a file that was there;
    what an archive holds is not read, so its members are unknown."""
    assert _reads(folder, command) == said


def test_what_a_move_or_an_archive_does_not_reach_is_read_as_before(folder):
    """An append; a write before the move, or outside the folder an archive
    unpacks into; a move of the run's own file; a listing, a print to the
    screen, a branch made where it stands; a dry run."""
    for command in ("mv -n mylink copy; echo x >> copy",
                    "echo x > copy; mv -n mylink copy",
                    "echo x > d1; mv -n d1 d2; echo y > d2",
                    "mkdir out && tar -xf a.tar -C out && echo x > page2",
                    "mkdir out && tar -xf a.tar -C out l && echo x > out/page",
                    "for f in *.jpg; do mv -n \"$f\" box/; done; echo x > log.txt",
                    "tar -tf a.tar > list.txt",
                    "tar -xOf a.tar page > page2",
                    "unzip -l b.zip > list.txt",
                    "git checkout -b fix && echo x > fix.md",
                    "git switch -c fix && echo x > fix.md",
                    "git stash list > stashes.txt",
                    "git restore --staged notes.md && echo x > n.md",
                    "git mv -n notes.md n3 && echo x > n3"):
        assert _reads(folder, command) is None, command


def test_a_move_whose_name_cannot_be_known_leaves_a_write_in_its_folder_unknown(folder):
    """`mv -n "$f" box/` puts `$f` at a name in `box` the command does not
    spell — any of them — and a source filled in when it runs cannot be
    looked at. Found here, the same for a link: `ln "$x" box/` was read as
    making `box/$x`, those very characters, so a write onto `box/a` after
    it was a new file."""
    assert _reads(folder, 'for f in *; do mv -n "$f" box/; done; echo x > box/notes.md') == (
        "it cannot be known whether $f (moved to box/notes.md) was there before this run began")
    assert _reads(folder, 'mv -n "$x" n2; echo y > n2') == (
        "it cannot be known whether $x (moved to n2) was there before this run began")
    assert _reads(folder, 'ln "$x" box/; echo y > box/a') == (
        "it cannot be known whether $x, where the link box/$x points, was there before this run "
        "began")


def test_the_reading_names_what_a_move_or_an_archive_puts():
    """`Finding.copied`: `moved` and `unpacked`, with the folder and the
    members it names."""
    def put(command: str) -> list:
        return [(f.why, f.path, f.known, f.sources, f.into, f.copied)
                for f in read_shell(command) if f.kind == "links"]
    assert put("mv -n a b") == [("mv", "b", True, (("a", True),), "", "moved")]
    assert put("mv -t d a b") == [("mv", "d", True, (("a", True), ("b", True)), "folder", "moved")]
    assert put("mv -nT a b") == [("mv", "b", True, (("a", True),), "file", "moved")]
    assert put("git -C r mv a b") == [("git mv", "r/b", True, (("r/a", True),), "", "moved")]
    assert put("tar -xf a.tar -C out") == [
        ("tar -x", "out", True, (("", False),), "folder", "unpacked")]
    assert put("tar -xkf a.tar l") == [("tar -x", ".", True, (("l", True),), "folder", "unpacked")]
    assert put("unzip b.zip -d o") == [("unzip", "o", True, (("", False),), "folder", "unpacked")]
    assert put("git checkout main")[0][2:] == (False, (("", False),), "folder", "unpacked")
    assert put("git clone u d") == [("git clone", "d", True, (("", False),), "folder", "unpacked")]
    for command in ("tar -xOf a.tar l", "tar -tf a.tar", "unzip -l b.zip", "unzip -p b.zip l",
                    "7z l a.7z", "git checkout -b x", "git switch -c x", "git reset --soft HEAD~",
                    "git apply --check p.diff", "git clone --bare u d", "mv --help"):
        assert put(command) == [], command


# ── the real programs, under a hire's never ─────────────────────────────────

def _repo(folder: Path) -> None:
    """A repository in `repo`, whose branch `other` holds `l` → `../notes.md`."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
    repo = folder / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "a"],
                 ["checkout", "-q", "-b", "other"]):
        subprocess.run(git + args, cwd=repo, check=True, timeout=30)
    (repo / "l").symlink_to("../notes.md")
    for args in (["add", "l"], ["commit", "-q", "-m", "b"], ["checkout", "-q", "main"]):
        subprocess.run(git + args, cwd=repo, check=True, timeout=30)


def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


REAL = (
    ("mv -n mylink copy; echo gone > copy", "through the link copy"),
    ("mv -n notes.md n2; echo gone > n2", "(moved to n2)"),
    ("mkdir out && tar -xf a.tar -C out && echo gone > out/l", "what tar -x puts at out/l"),
    ("unzip -q b.zip -d out2 && echo gone > out2/l", "what unzip puts at out2/l"),
    ("cd repo && git checkout -q other && echo gone > l", "what git checkout puts at l"),
)


@pytest.mark.skipif(not all(shutil.which(p) for p in ("mv", "tar", "unzip", "git")),
                    reason="coreutils, tar, unzip or git is not installed")
@pytest.mark.parametrize("command,said", REAL)
def test_the_write_really_lands_there_and_a_never_refuses_it(folder, people, command, said):
    """Real `bash` empties the person's notes through each — the premise —
    and under a hire's `destructive: never` the same command is refused and
    nothing is written."""
    _repo(folder)
    trial = folder.parent / f"trial-{uuid.uuid4().hex[:6]}"
    shutil.copytree(folder, trial, symlinks=True)
    subprocess.run(["bash", "-c", command], cwd=trial, check=True, timeout=60)
    landed = trial / ("notes.md" if "n2" not in command else "n2")
    assert landed.read_text(encoding="utf-8") == "gone\n", command

    refused = _bash(_never(folder), folder, command)
    assert refused.get("blocked") is True, refused
    assert said in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES


@pytest.mark.skipif(shutil.which("tar") is None, reason="tar is not installed")
def test_tar_p_writes_a_member_anywhere_and_a_never_refuses_it(folder, people):
    """Found here (`B1680`'s reading): `tar -xP` keeps a member's leading
    `/`, so from inside a folder `mkdir` made it writes the person's notes
    — read as writing nothing that was there, the folder being new. Now
    where it writes cannot be known."""
    member = tarfile.TarInfo(str(folder / "notes.md"))
    member.size = 5
    with tarfile.open(folder / "abs.tar", "w", format=tarfile.GNU_FORMAT) as tar:
        tar.addfile(member, io.BytesIO(b"gone\n"))
    command = "mkdir o && tar -xPf abs.tar -C o"
    assert _reads(folder, command) == f"it cannot be known whether what abs.tar holds {THERE[6:]}"
    refused = _bash(_never(folder), folder, command)
    assert refused.get("blocked") is True, refused
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    subprocess.run(["bash", "-c", command], cwd=folder, check=True, timeout=30)
    assert (folder / "notes.md").read_text(encoding="utf-8") == "gone\n", "the premise"


def test_a_move_of_a_page_into_a_fresh_name_and_a_write_elsewhere_run(folder, people):
    """What does not reach a file that was there runs under the never."""
    ran = _bash(_never(folder), folder,
                "echo draft > d.md && mv -n d.md box/ && echo again > box/d.md "
                "&& mkdir out && tar -xf a.tar -C out && echo made > made.md")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "box" / "d.md").read_text(encoding="utf-8") == "again\n"
    assert os.path.islink(folder / "out" / "l")
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES


# ── after the command has run ───────────────────────────────────────────────

def test_a_name_a_move_puts_the_persons_file_at_is_not_the_runs_own(folder):
    """The run looked at `n2` (nothing there) for a write it did not make;
    `mv -n notes.md n2` then put the notes there — so a later write onto
    `n2` is looked at again. Before, the run kept `n2` as its own and the
    write emptied the notes with no card."""
    files = _files(folder)
    assert call_destroys("bash", "echo draft > n2", files) is None
    assert call_destroys("bash", "mv -n notes.md n2", files) is None
    subprocess.run(["bash", "-c", "mv -n notes.md n2"], cwd=folder, check=True, timeout=30)
    assert call_destroys("bash", "echo gone > n2", files) == f"a > redirect replaces n2, {THERE}"


def test_a_draft_a_move_replaced_is_not_write_files_own(folder):
    """`write_file` made `draft.md`; `mv notes.md draft.md` asks for itself
    and, said yes to, leaves the person's notes there — so `write_file
    draft.md` asks too. Before, the run's record still held it as the
    draft `write_file` made."""
    files = _files(folder)
    files.note_made(str(folder / "draft.md"))
    (folder / "draft.md").write_text("a draft", encoding="utf-8")
    write = {"path": "draft.md", "content": "rewritten"}
    assert call_destroys("write_file", write, files) is None, "its own draft"
    asked = ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}),
                                   files=files).decision_for("bash", "mv notes.md draft.md")
    assert asked.allowed is False and "mv replaces whatever already has the new name" in asked.reason
    subprocess.run(["bash", "-c", "mv notes.md draft.md"], cwd=folder, check=True, timeout=30)
    assert call_destroys("write_file", write, files) == \
        f"write_file replaces draft.md, {THERE}"


def test_a_name_that_cannot_be_known_clears_what_the_run_holds(folder):
    """`ln notes.md "$x"` may make any name a hard link to the notes: every
    name the run held as its own is looked at again."""
    files = _files(folder)
    assert call_destroys("bash", "echo draft > fresh.md", files) is None
    assert call_destroys("bash", 'x=fresh.md; ln notes.md "$x"', files) is None
    subprocess.run(["bash", "-c", 'x=fresh.md; ln notes.md "$x"'], cwd=folder, check=True,
                   timeout=30)
    assert call_destroys("bash", "echo gone > fresh.md", files) == \
        f"a > redirect replaces fresh.md, {THERE}"


# ── in the workstation ──────────────────────────────────────────────────────

def test_in_the_workstation_a_move_and_an_archive_are_read_too(ws, settings, people):
    """The daemon says a name is a link but not its text: a moved link is
    one whose target cannot be known, a moved file is the person's, and
    what an archive puts is unknown — each refused under a never, nothing
    written; and a name an archive put a link at, which the run had looked
    at and found nothing, is not its own in the next command."""
    _on(settings, ws)
    files = RunFiles(None, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / "notes.md").write_text(NOTES, encoding="utf-8")
    (home / "mylink").symlink_to("notes.md")
    (home / "out").mkdir()
    _archives(home / "out")

    def bash(command: str) -> dict:
        async def go():
            await files.look("bash", command)
            return (await te.execute_tool_block(ToolBlock("bash", command), owner="ann",
                                                session_id=files.session_id,
                                                security_context=run))[1]
        return asyncio.run(go())

    for command, said in (
            ("mv -n mylink copy; echo gone > copy",
             "it cannot be known whether what mylink points at in your workstation, where the "
             "link copy points, was there before this run began"),
            ("mv -n notes.md n2; echo gone > n2",
             f"a > redirect replaces notes.md in your workstation (moved to n2), {THERE}"),
            ("tar -xkf out/a.tar -C out && echo gone > out/l",
             "it cannot be known whether what tar -x puts at out/l in your workstation is a link "
             "to a file that was there before this run began")):
        refused = bash(command)
        assert refused.get("blocked") is True, refused
        assert f"({said})" in refused["error"], refused["error"]
        assert (home / "notes.md").read_text(encoding="utf-8") == NOTES
        assert not (home / "n2").exists() and not (home / "copy").exists()

    asyncio.run(files.look("bash", "echo draft > out/l"))       # looked at: nothing there
    assert bash("tar -xkf out/a.tar -C out").get("exit_code") == 0
    assert os.path.islink(home / "out" / "l")
    later = bash("echo gone > out/l")
    assert later.get("blocked") is True, later
    assert f"(a > redirect replaces out/l in your workstation, {THERE})" in later["error"]
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES
