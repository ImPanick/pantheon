# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1689` — `jpegoptim`, `oxipng` and `mogrify` writing over a different
file that was there are read as writing over it.

Measured before the fix, with the file there: `jpegoptim -d out -o a.jpg`,
`oxipng --out out/a.png a.png`, `mogrify -path out a.png` and `mogrify
-format png a.jpg` (over `a.png`) gave `call_destroys` `None` —
`execute_code` alone — while `convert a.jpg a.png` was read (`B1682`).

How each is read (`src/shell_reading.py`, the block below `_FFMPEG_INFO`):
all three edit their input in place by default, and an in-place edit stays
a plain write (`D-2026-10-29-03` §1, as `sed -i` and `mogrify` alone already
were) — so only a write onto a *different* file is a replacement:

  * `jpegoptim -d DIR` writes each file by its name in `DIR`, and there it
    refuses a file that is already there unless `-o` (`--overwrite`) — its
    source: `if (file_exists(newname) && !overwrite_mode) … "target file
    already exists"`. So `-d` with `-o` over one is destructive; `-d`
    alone, Image Optimiser's `--dest=optimised`, writes over nothing;
  * `oxipng --out FILE` writes `FILE` whole (`File::create`), `--dir DIR`
    each input by its name there; `-o` is its level, not its output;
  * `mogrify -path DIR` writes each image by its name in `DIR`, `-format
    EXT` writes `name.EXT` beside it (`wand/mogrify.c`), each over what is
    there; a name it expands itself (`'*.jpg'`) is unknowable in the folder.
    Its options are counted from ImageMagick's own table, so a value is
    never read as an image nor an image swallowed as a value.

An output that is the input itself (`-format jpg a.jpg`, `oxipng --out a.png
a.png`, `jpegoptim -d . -o a.jpg`) is the edit, not a replacement.

Image Optimiser's runbook writes `jpegoptim --dest=optimised` and `oxipng
--out optimised/<name>.png` behind `[ -e … ] ||` tests (`B1682`): its new
case has every copy there from an earlier run, and its `destructive: never`
still lets the command run. No shipped eval call changed reading.

Driven (`Law 20`): the real reader and the run's record over a real folder,
the real `mogrify` under a hire's `destructive: never` through the real gate
and dispatcher, and Image Optimiser through the real harness.
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
from src.agents import evals as E
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's images, and copies made before."""
    ws = tmp_path / "proj"
    (ws / "out").mkdir(parents=True)
    for name in ("a.jpg", "a.png", "b.jpg", "out/a.jpg", "out/a.png", "out/b.png"):
        (ws / name).write_text(f"the person's {name}", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


#: Each over a file that was there, its new-path twin, and what writes.
OVER = (
    ("jpegoptim -d out -o a.jpg", "jpegoptim -d out -o b.jpg", "jpegoptim -o", "out/a.jpg"),
    ("jpegoptim --dest=out --overwrite --strip-all -m82 a.jpg",
     "jpegoptim --dest=out --overwrite --strip-all -m82 b.jpg", "jpegoptim --overwrite", "out/a.jpg"),
    ("jpegoptim -o -dout a.jpg", "jpegoptim -o -dout b.jpg", "jpegoptim -o", "out/a.jpg"),
    ("oxipng --out out/a.png a.png", "oxipng --out out/new.png a.png", "oxipng --out", "out/a.png"),
    ("oxipng -o 4 --strip safe --out=out/a.png a.png", "oxipng -o 4 --strip safe --out=new.png a.png",
     "oxipng --out", "out/a.png"),
    ("oxipng --dir out a.png", "oxipng --dir out new.png", "oxipng --dir", "out/a.png"),
    ("mogrify -path out a.png", "mogrify -path out b.jpg", "mogrify -path", "out/a.png"),
    ("mogrify -format png a.jpg", "mogrify -format png b.jpg", "mogrify -format", "a.png"),
    ("mogrify -strip -resize 50% -format png a.jpg", "mogrify -strip -resize 50% -format png b.jpg",
     "mogrify -format", "a.png"),
    ("mogrify +profile '*' -format png a.jpg", "mogrify +profile '*' -format png b.jpg",
     "mogrify -format", "a.png"),
    ("mogrify -path out -format png b.jpg", "mogrify -path out -format webp b.jpg", "mogrify -path",
     "out/b.png"),
    ("magick mogrify -format png a.jpg", "magick mogrify -format png b.jpg", "magick mogrify -format",
     "a.png"),
    ("gm mogrify -output-directory out -format png b.jpg",
     "gm mogrify -output-directory out -format webp b.jpg", "gm mogrify -output-directory", "out/b.png"),
)


@pytest.mark.parametrize("over,new,why,shown", OVER)
def test_over_a_file_that_was_there_it_is_destructive(folder, over, new, why, shown):
    """The row's `Verify:`, one program at a time, naming what writes."""
    assert call_destroys("bash", over, _files(folder)) == f"{why} replaces {shown}, {THERE}"


@pytest.mark.parametrize("over,new,why,shown", OVER)
def test_onto_a_new_path_it_is_a_plain_write(folder, over, new, why, shown):
    assert call_destroys("bash", new, _files(folder)) is None


def test_an_edit_in_place_stays_a_write(folder):
    """`D-2026-10-29-03` §1: each program's own default — and an output
    that names its input — is an edit; and what writes nothing writes over
    nothing (`--stdout`, a dry run, `jpegoptim -n`)."""
    files = _files(folder)
    for command in ("jpegoptim a.jpg", "jpegoptim --strip-all -m82 a.jpg out/a.jpg",
                    "jpegoptim -d . -o a.jpg", "jpegoptim -d out -o out/a.jpg",
                    "jpegoptim -d out -o -n a.jpg", "jpegoptim -d out -o --stdout a.jpg",
                    "oxipng a.png", "oxipng -o 4 a.png", "oxipng -o max -r .",
                    "oxipng --out a.png a.png", "oxipng --dir . a.png", "oxipng --stdout a.png",
                    "oxipng -d --out out/a.png a.png", "oxipng -P --out out/a.png a.png",
                    "mogrify -resize 50% a.png", "mogrify -strip *.png",
                    "mogrify -format jpg a.jpg", "mogrify -format png -path . a.png",
                    "magick mogrify -resize 50% out/a.png", "mogrify -version"):
        assert call_destroys("bash", command, files) is None, command


def test_jpegoptim_into_a_folder_keeps_what_is_there_without_o(folder):
    """Image Optimiser's own words: `--dest` without `-o` refuses a file
    that is there, so it writes over nothing — `B1682`'s test before it is
    for the reader, and not needed for this program."""
    files = _files(folder)
    assert call_destroys("bash", "jpegoptim --dest=out --strip-all -m82 a.jpg", files) is None
    assert call_destroys("bash", "jpegoptim -d out a.jpg", files) is None


def test_names_it_finds_itself_are_unknowable_in_a_folder_that_was_there(folder):
    """`mogrify` expands `'*.jpg'` and reads `@list` itself; `oxipng -r`
    walks a folder; `jpegoptim --files-from` reads its names from a file."""
    files = _files(folder)
    for command, why, shown in (("mogrify -format png '*.jpg'", "mogrify -format", "the folder it runs in"),
                                ("mogrify -format png *.jpg", "mogrify -format", "the folder it runs in"),
                                ("mogrify -path out @list.txt", "mogrify -path", "out"),
                                ("oxipng -r --dir out pictures", "oxipng --dir", "out"),
                                ("jpegoptim -d out -o --files-from=list.txt", "jpegoptim -o", "out")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether what {why} writes in {shown} was there before this run began", \
            command


def test_a_for_loops_name_is_read_by_the_name_it_holds(folder):
    """In `for f in *.jpg` each value is a name with no `/`, so
    `jpegoptim -d out -o "$f"` writes `out/$f` — and a test of those same
    words before it rules the write out (`B1690`'s `_Tests`)."""
    files = _files(folder)
    assert call_destroys("bash", 'for f in *.jpg; do jpegoptim -d out -o "$f"; done', files) == \
        "it cannot be known whether out/$f was there before this run began"
    assert call_destroys("bash", 'for f in *.jpg; do [ -e "out/$f" ] || jpegoptim -d out -o "$f"; done',
                         files) is None
    assert call_destroys("bash", 'for f in */*.jpg; do [ -e "out/$f" ] || jpegoptim -d out -o "$f"; done',
                         files) == \
        "it cannot be known whether what jpegoptim -o writes in out was there before this run began"


# ── the real program, and a shipped agent ───────────────────────────────────

def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("mogrify") is None or shutil.which("convert") is None,
                    reason="ImageMagick is not installed")
def test_a_hires_never_refuses_mogrify_over_the_persons_file_and_runs_it_onto_a_new_one(tmp_path,
                                                                                     people):
    ws = tmp_path / "pics"
    ws.mkdir()
    for name in ("a.jpg", "b.jpg"):
        subprocess.run(["convert", "-size", "4x4", "xc:red", str(ws / name)], check=True)
    (ws / "a.png").write_text("the person's own a.png", encoding="utf-8")
    refused = _bash(_never(ws), ws, "mogrify -format png a.jpg")
    assert refused.get("blocked") is True, refused
    assert f"(mogrify -format replaces a.png, {THERE})" in refused["error"]
    assert (ws / "a.png").read_text(encoding="utf-8") == "the person's own a.png"
    ran = _bash(_never(ws), ws, "mogrify -format png b.jpg")
    assert ran.get("exit_code") == 0, ran
    assert (ws / "b.png").read_bytes()[:4] == b"\x89PNG"      # where the reading said it writes


def test_image_optimiser_reruns_with_every_copy_there_under_its_never():
    """Its runbook's whole command — `jpegoptim --dest`, `oxipng --out`,
    each behind its own test — over a folder whose copies an earlier run
    made: the never lets it run, and nothing is written over."""
    m = get_agent(None, "image-optimiser")
    assert H.manifest_effects(m)["destructive"] == "never"
    case = next(c for c in E.load_evals(m) if c["id"] == "copies-made-before-are-skipped")
    command = case["script"][1]["call"][0][1]["command"]
    assert "[ -e optimised/team.png ] || oxipng --out optimised/team.png team.png" in command
    assert "[ -e optimised/hero.jpg ] || jpegoptim --dest=optimised" in command
    assert {f"site/img/optimised/{n}" for n in ("hero.jpg", "team.png")} <= set(case["world"]["files"])
    [result] = asyncio.run(E.run_agent(m, cases=[case]))
    assert result.passed, result.checks
    assert "bash" in result.calls, result.calls
