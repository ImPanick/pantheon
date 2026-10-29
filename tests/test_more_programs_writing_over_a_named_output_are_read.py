# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1682` — the rest of the programs that write over a named output are read
as writing over it, as `B1680`'s are.

Measured before the fix, with the file there: `pandoc in.md -o notes.md`,
`convert`/`magick in.jpg notes.png`, `openssl enc -in a -out notes.md`,
`cwebp … -o notes.md`, `gunzip -f notes.md.gz`, `7z x -y a.7z`, `yt-dlp
--force-overwrites -o notes.md …`, `rsync -a src/ ./` and `wget -r …` gave
`call_destroys` `None` — `execute_code` alone — while `echo x > notes.md`
over the same file was `destructive`.

Now each is read from its manual (`src/shell_reading.py`, the block below
`_OUTPUT_READERS`): over a file that was there before the run it is
destructive and names it; onto a new path it is a plain write; and what the
command does not name — an archive's members, a site's tree, what is in an
`rsync` source with a trailing `/` — into a folder that was there cannot be
known, and is destructive.

Reading these made a shipped agent's real re-run refusable: Image
Optimiser's command writes each copy behind `[ -e optimised/<name> ] ||`, and
under its `destructive: never` a `cwebp -o` over an output a previous run made
would have been refused. So the reader also reads that test (`_guard`): a
write the command makes only when nothing is at its path replaces nothing —
at the head of its list, not after an `&&`, whose failure runs the write
whatever is there. The runbook now puts each test after a `;` (1.3.0 →
1.4.0), and its name-conflict case runs its command under the never with the
earlier copy there. Measured on the shipped evals: 3 of 378 `bash` calls
changed reading (Image Optimiser's, each a `cwebp -o` after `mkdir -p
optimised &&`); after the runbook's change, none.

Driven (`Law 20`): the real reader and the run's record over a real folder,
the real gate and dispatcher running the real `pandoc` and `openssl` under a
hire's `destructive: never`, and Image Optimiser through the real harness.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents import evals as E
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"
NOTES = "Ana's notes — keep these"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's notes, a page in a folder, a folder
    of sources, and a site's folder a mirror would write into."""
    ws = tmp_path / "proj"
    for sub in ("site", "src", "example.com"):
        (ws / sub).mkdir(parents=True)
    (ws / "notes.md").write_text(NOTES, encoding="utf-8")
    (ws / "site" / "index.html").write_text("<h1>mine</h1>", encoding="utf-8")
    (ws / "src" / "one.txt").write_text("one", encoding="utf-8")
    (ws / "example.com" / "index.html").write_text("<h1>mirrored</h1>", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


#: Each program over `notes.md` (`{}`), and what writes over it.
OVER = (
    ("pandoc in.md -o {}", "pandoc -o"),
    ("pandoc -so {} in.md", "pandoc -o"),
    ("pandoc --output={} in.md", "pandoc --output"),
    ("pandoc --outp {} in.md", "pandoc --output"),
    ("pandoc in.md --log={} -o out.html", "pandoc --log"),
    ("convert in.jpg {}", "convert"),
    ("convert in.jpg -resize 50% png:{}", "convert"),
    ("convert in.jpg -write {} -resize 50% out.png", "convert"),
    ("magick in.jpg {}", "magick"),
    ("magick convert in.jpg {}", "magick convert"),
    ("gm convert in.jpg {}", "gm convert"),
    ("montage a.png b.png -tile 2x1 {}", "montage"),
    ("openssl enc -aes-256-cbc -pbkdf2 -in a -out {}", "openssl -out"),
    ("openssl rand -out={} 32", "openssl -out"),
    ("openssl req -new -newkey rsa:2048 -nodes -keyout {} -out req.pem", "openssl -keyout"),
    ("cwebp -q 80 in.png -o {}", "cwebp -o"),
    ("dwebp in.webp -o {}", "dwebp -o"),
    ("gif2webp in.gif -o {}", "gif2webp -o"),
    ("gunzip -kf {}.gz", "gunzip -f"),
    ("gzip -dkf {}.gz", "gzip -d -f"),
    ("7z x -y a.7z {}", "7z x"),
    ("7za x -aoa a.7z {}", "7za x"),
    ("yt-dlp --force-overwrites -o {} https://video.example/v", "yt-dlp --force-overwrites"),
    ("rsync -a draft.md {}", "rsync"),
)


@pytest.mark.parametrize("command,why", OVER)
def test_over_a_file_that_was_there_it_is_destructive(folder, command, why):
    """The row's `Verify:`, one program at a time, naming what writes."""
    assert call_destroys("bash", command.format("notes.md"), _files(folder)) == \
        f"{why} replaces notes.md, {THERE}"


@pytest.mark.parametrize("command,why", OVER)
def test_onto_a_new_path_it_is_a_plain_write(folder, command, why):
    assert call_destroys("bash", command.format("new.md"), _files(folder)) is None


def test_what_keeps_the_file_or_writes_none_is_not_read_as_replacing_it(folder):
    """The screen or no file; an edit in place (`D-2026-10-29-03` §1); a
    listing or a test; 7-Zip asking, skipping or to its output; `yt-dlp`
    without `--force-overwrites` (it never writes over the download), or
    with `-w` after it; `rsync` told to keep what is there or only to list;
    `wget -r` told not to clobber, or `-nd` without `-N` (a second copy is
    saved as `name.1`)."""
    files = _files(folder)
    for command in ("pandoc in.md -o -", "pandoc in.md", "convert in.jpg png:-",
                    "convert in.jpg null:", "convert -list format", "magick -version",
                    "magick identify notes.md", "magick mogrify -resize 50% notes.md",
                    "gm identify notes.md", "openssl x509 -noout -in notes.md",
                    "openssl dgst -sha256 notes.md", "cwebp in.png -o -",
                    "gunzip -c notes.md.gz", "7z x a.7z notes.md", "7z x -y -aos a.7z notes.md",
                    "7z x -y -so a.7z notes.md", "7z l a.7z",
                    "yt-dlp -o notes.md https://video.example/v",
                    "yt-dlp --force-overwrites -w -o notes.md https://video.example/v",
                    "rsync -a --ignore-existing draft.md notes.md", "rsync -an draft.md notes.md",
                    "rsync -ab draft.md notes.md", "rsync --list-only src/",
                    "wget -r -nc https://example.com/", "wget -r -nd https://example.com/"):
        assert call_destroys("bash", command, files) is None, command


def test_what_the_command_does_not_name_into_a_folder_that_was_there_cannot_be_known(folder):
    """An archive's members, a site's tree, what is in an `rsync` source
    with its trailing `/`, a document's media, a video's own name: into a
    folder that was there, unknowable — destructive; into a new one, nothing
    was there to replace."""
    files = _files(folder)
    for command, why, shown in (("rsync -a src/ ./", "rsync", "the folder it runs in"),
                                ("rsync -a src/ site", "rsync", "site"),
                                ("7z x -y a.7z", "7z x", "the folder it runs in"),
                                ("7z x -y a.7z -osite", "7z x", "site"),
                                ("wget -r https://example.com/", "wget -r", "example.com"),
                                ("wget -m -nH https://example.com/", "wget -m",
                                 "the folder it runs in"),
                                ("pandoc in.docx --extract-media=site -o new.md",
                                 "pandoc --extract-media", "site"),
                                ("yt-dlp --force-overwrites https://video.example/v",
                                 "yt-dlp --force-overwrites", "the folder it runs in")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether what {why} writes in {shown} was there before this run began", \
            command
    for command in ("rsync -a src/ fresh/", "7z x -y a.7z -ofresh", "wget -r https://other.example/",
                    "wget -r -P fresh https://example.com/",
                    "pandoc in.docx --extract-media=fresh -o new.md"):
        assert call_destroys("bash", command, files) is None, command


def test_a_named_member_or_source_is_looked_for_where_it_lands(folder):
    """`rsync` puts a source by its name in a folder (`-R`: its whole path);
    `7z e` drops a member's folders, `7z x` keeps them; a `wget -r` site's
    folder is its host, lower case."""
    files = _files(folder)
    assert call_destroys("bash", "rsync -a other/index.html site/", files) == \
        f"rsync replaces site/index.html, {THERE}"
    assert call_destroys("bash", "7z e -y a.7z deep/index.html -osite", files) == \
        f"7z e replaces site/index.html, {THERE}"
    assert call_destroys("bash", "7z x -y a.7z deep/index.html -osite", files) is None
    assert call_destroys("bash", "wget -r https://EXAMPLE.com/x", files) == \
        f"it cannot be known whether what wget -r writes in example.com was there before this run began"
    assert call_destroys("bash", "convert in.pdf page-%d.png", files) == \
        "it cannot be known whether page-%d.png was there before this run began"


def test_rsync_onto_another_machine_writes_on_the_far_side(folder):
    """Whether what is there was there cannot be known from here — the
    cautious reading `B1669` gives `ssh host '…'`."""
    assert call_destroys("bash", "rsync -a src/ nas.lan:backup/", _files(folder)) == \
        "it cannot be known whether nas.lan:backup/ on the far side was there before this run began"


def test_a_write_behind_a_test_that_nothing_is_there_replaces_nothing(folder):
    """`[ -e f ] || …`, `test -e f || …`, `[[ -e f ]] || …` and `[ ! -e f ] &&
    …` at the head of a list: what follows writes `f` only when it is not
    there. Not after an `&&` (what came before failing runs it), not
    negated the other way, not a different path, and not when what follows
    moves first; `-f` does not rule out a folder a copy writes into. A
    variable is the same value in the test and the write — but not one bash
    changes each time it is read (`$RANDOM`, `$_`)."""
    files = _files(folder)
    for command in ("[ -e notes.md ] || cwebp in.png -o notes.md",
                    '[ -e "$out" ] || convert in.jpg "$out"',
                    "test -e notes.md || echo hi > notes.md",
                    "[[ -e notes.md ]] || echo hi > notes.md",
                    "[ -f notes.md ] || pandoc in.md -o notes.md",
                    "[ ! -e notes.md ] && echo hi > notes.md",
                    "mkdir -p d; [ -e notes.md ] || echo hi > notes.md",
                    "false || [ -e notes.md ] || echo hi > notes.md",
                    "if [ -e notes.md ] || echo hi > notes.md; then :; fi",
                    "[ -e site ] || cp other/index.html site",
                    "cd site && { [ -e index.html ] || echo hi > index.html; }"):
        assert call_destroys("bash", command, files) is None, command
    for command, shown in (("mkdir -p d && [ -e notes.md ] || echo hi > notes.md", "a > redirect"),
                           ("[ -e notes.md ] && echo hi > notes.md", "a > redirect"),
                           ("! [ -e notes.md ] || echo hi > notes.md", "a > redirect"),
                           ("[ ! -e notes.md ] || echo hi > notes.md", "a > redirect"),
                           ("[ -e other.md ] || echo hi > notes.md", "a > redirect"),
                           ("[ -e ./notes.md ] || echo hi > notes.md", "a > redirect"),
                           ("[ -e notes.md ] || echo hi > new.md; echo hi > notes.md",
                            "a > redirect"),
                           ("[ -e notes.md ] || env -C . sh -c 'echo hi > notes.md'",
                            "a > redirect"),
                           ("[ -e notes.md ] || pandoc in.md -o notes.md && convert a.png notes.md",
                            "convert")):
        assert call_destroys("bash", command, files) == f"{shown} replaces notes.md, {THERE}", command
    assert call_destroys("bash", "[ -f site ] || cp other/index.html site", files) == \
        f"cp replaces site/index.html, {THERE}"
    for shifting in ("RANDOM", "_"):
        assert call_destroys("bash", f'[ -e "${shifting}" ] || echo hi > "${shifting}"', files) == \
            f"it cannot be known whether ${shifting} was there before this run began"


# ── a shipped agent ─────────────────────────────────────────────────────────

def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def test_image_optimiser_reruns_over_its_own_copies_under_its_never(tmp_path):
    """Its runbook's command, run again over a folder it optimised before:
    each copy behind its own test after a `;` is skipped, so the never lets
    it run; the same command with its test after an `&&` is refused. And
    every case passes through the real harness — the name-conflict case
    runs its command with the earlier copy there."""
    m = get_agent(None, "image-optimiser")
    assert H.manifest_effects(m)["destructive"] == "never"
    assert m.version == "1.4.0"
    img = tmp_path / "site" / "img"
    (img / "optimised").mkdir(parents=True)
    (img / "optimised" / "hero.webp").write_text("from the last run", encoding="utf-8")
    again = ('cd "site/img" && command -v cwebp; mkdir -p optimised; '
             "[ -e optimised/hero.webp ] || cwebp -q 80 hero.jpg -o optimised/hero.webp; "
             "[ -e optimised/hero.jpg ] || convert hero.jpg -strip -quality 82 optimised/hero.jpg; "
             "stat -c '%s %n' hero.jpg optimised/*")
    assert _never(tmp_path).decision_for("bash", again).allowed is True
    chained = again.replace("mkdir -p optimised; ", "mkdir -p optimised && ")
    refused = _never(tmp_path).decision_for("bash", chained)
    assert refused.allowed is False
    cases = E.load_evals(m)
    for case in cases:
        for step in case["script"]:
            for tool, args in step.get("call") or []:
                if tool == "bash":
                    assert "optimised && [ -e" not in args["command"], case["id"]
    results = asyncio.run(E.run_agent(m))
    assert len(results) == len(cases) == 6
    for result in results:
        assert result.passed, (result.case, result.checks)
    conflict = next(r for r in results if r.case == "a-name-conflict-is-never-overwritten")
    assert {"check": "it called bash", "ok": True, "detail": "It did."} in conflict.checks


# ── the real programs, through the gate ─────────────────────────────────────

def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_hires_never_refuses_pandoc_over_the_persons_file_and_runs_it_onto_a_new_one(folder,
                                                                                    people):
    (folder / "in.md").write_text("# Hello\n", encoding="utf-8")
    refused = _bash(_never(folder), folder, "pandoc in.md -o notes.md")
    assert refused.get("blocked") is True, refused
    assert f"(pandoc -o replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    ran = _bash(_never(folder), folder, "pandoc in.md -o page.html")
    assert ran.get("exit_code") == 0, ran
    assert "Hello" in (folder / "page.html").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_a_hires_never_refuses_openssl_over_the_persons_file_and_runs_it_onto_a_new_one(folder,
                                                                                     people):
    refused = _bash(_never(folder), folder, "openssl rand -out notes.md 16")
    assert refused.get("blocked") is True, refused
    assert f"(openssl -out replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    ran = _bash(_never(folder), folder, "openssl rand -out key.bin 16")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "key.bin").stat().st_size == 16
