# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1693` — a converter given several images writes numbered names, and they
are looked for beside the one name it is given.

Measured before the fix: ImageMagick 6.9.12's `convert multi.gif out.png`
writes `out-0.png`, `out-1.png`, `out-2.png` and no `out.png` (so do
`magick`, `montage`, each `-write`, `mogrify -format`, and `+adjoin` into
any format), and `heif-convert` writes `out-1.jpg`, `out-2.jpg`… for a file
holding several images (`heif_dec.cc`) — while `B1682`/`B1690` read only the
name given: with `out-1.png` there, `call_destroys('bash', 'convert in.gif
out.png')` was `None`, and a hire's `never` let it write over the person's
file.

Now, the cautious reading as the owner's rulings have taken it
(`D-2026-10-29-02` §1): how many images an input holds is the input's, and
the reader does not open it to count — so besides the name, each such write
is read for the names of that numbered shape in its folder (`Finding.
numbered`), and the run lists the folder the first time it looks
(`RunFiles.listed`): a file of that shape that was there makes the write
unknown, and so destructive; where none is, it is a plain write. A format
ImageMagick keeps every frame of in one file (`gif`, `tif`, `pdf`, `webp`…,
measured) has none, unless `+adjoin`. The name made from a `for` loop's
name — File Converter's `"converted/${f%.*}.jpg"` — has any name with no `/`
before its number; a name the reader cannot spell leaves what is written
beside it unknown.

Measured on the shipped evals: 6 of 377 `bash` calls changed reading — File
Converter's, whose `heif-convert` line now carries the numbered names in
`converted/` — and none changed whether it is destructive in its own worlds,
where no numbered copy is there.

Driven (`Law 20`): the real reader and the run's record over a real folder;
real ImageMagick writing the numbered names the reading names; the real gate
and dispatcher running real `bash` under a hire's `destructive: never`, the
run's own copies its own on the next pass and across a card; File
Converter's own command under its `ask`; and the real workstation daemon.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents import evals as E
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _home, _on, people, settings, ws,
)

THERE = "which was there before this run began"
MINE = "the person's own"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace, holding the person's own files of each numbered
    shape — and a folder for a converter's output."""
    proj = tmp_path / "proj"
    (proj / "out").mkdir(parents=True)
    for name in ("out-1.png", "w-0.png", "sheet-1.png", "anim-2.png", "photo-2.jpg",
                 "g.png.0", "loop-0.gif", "out/pic-0.png", "burst.HEIC"):
        (proj / name).write_text(f"{MINE} {name}", encoding="utf-8")
    return proj


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


#: Each command, what writes, and the person's file of its numbered shape.
NUMBERED = (
    ("convert in.gif out.png", "convert", "out-1.png"),
    ("magick in.gif -resize 50% out.png", "magick", "out-1.png"),
    ("magick convert in.gif out.png", "magick convert", "out-1.png"),
    ("convert in.gif -write w.png out.gif", "convert", "w-0.png"),
    ("montage a.png b.png -tile 1x1 sheet.png", "montage", "sheet-1.png"),
    ("mogrify -format png anim.gif", "mogrify -format", "anim-2.png"),
    ("convert in.gif +adjoin loop.gif", "convert", "loop-0.gif"),
    ("convert in.gif out/pic.png", "convert", "out/pic-0.png"),
    ("gm convert in.gif g.png", "gm convert", "g.png.0"),
    ("heif-convert burst.heic photo.jpg", "heif-convert", "photo-2.jpg"),
    ("heif-dec -o photo.jpg burst.heic", "heif-dec", "photo-2.jpg"),
    ("heif-convert photo.HEIC", "heif-convert", "photo-2.jpg"),
)


@pytest.mark.parametrize("command,why,mine", NUMBERED)
def test_a_numbered_copy_that_was_there_makes_the_write_unknown(folder, command, why, mine):
    """The row's `Verify:`: the numbered names, which cannot be known, are
    read where such files are there — and the sentence names the file."""
    assert _reads(folder, command) == f"it cannot be known whether {why} writes over {mine}, {THERE}"


@pytest.mark.parametrize("command,why,mine", NUMBERED)
def test_where_none_of_that_shape_is_there_it_is_a_plain_write(folder, command, why, mine):
    (folder / mine).unlink()
    assert _reads(folder, command) is None


def test_what_has_no_numbered_names_or_none_of_these(folder):
    """A format that keeps every frame in one file, another name's numbers,
    a `%d` name ImageMagick numbers itself (unknowable already), and an
    output folder that is not there."""
    assert _reads(folder, "convert in.gif loop.gif") is None
    assert _reads(folder, "convert in.gif other.png") is None
    assert _reads(folder, "convert in.gif new/out.png") is None
    assert _reads(folder, "convert in.gif 'frame-%02d.png'") == \
        "it cannot be known whether frame-%02d.png was there before this run began"


def test_a_loops_name_has_any_name_before_its_number(folder):
    """File Converter's `heif-convert "$f" "converted/${f%.*}.jpg"` behind its
    test: any numbered `.jpg` in `converted/` may be one; another kind of
    name is not; a name the reader cannot spell leaves what is beside it
    unknown."""
    (folder / "converted").mkdir()
    (folder / "converted" / "IMG_2041.jpg").write_text("an earlier copy", encoding="utf-8")
    loop = ('for f in *; do [ -e "converted/${f%.*}.jpg" ] && continue; '
            'heif-convert "$f" "converted/${f%.*}.jpg"; done')
    assert _reads(folder, loop) is None
    (folder / "converted" / "IMG_7-2.JPG").write_text("a burst's second", encoding="utf-8")
    assert _reads(folder, loop) == \
        f"it cannot be known whether heif-convert writes over converted/IMG_7-2.JPG, {THERE}"
    assert _reads(folder, '[ -e "out/$x.png" ] || convert in.gif "out/$x.png"') == \
        "it cannot be known whether what convert writes beside out/$x.png was there before this run began"


# ── the real programs, under a hire's never ─────────────────────────────────

def _never(files: RunFiles) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files)


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("convert") is None, reason="ImageMagick is not installed")
def test_imagemagick_writes_the_names_read_and_a_never_keeps_the_persons(tmp_path, people):
    """Real `convert`: a three-frame GIF to `out.png` writes `out-0.png`…
    `out-2.png`, the shape read. Under a hire's never, the run's first
    conversion runs (none there), its second over its own copies runs, and
    a run resumed from a card reads them alike; a new run, for which they
    were there, is refused — and they are not written over."""
    pics = tmp_path / "pics"
    pics.mkdir()
    subprocess.run(["convert", "-size", "4x4", "xc:red", "xc:blue", "xc:green", str(pics / "multi.gif")],
                   check=True, timeout=60)
    command = "convert multi.gif -resize 2x2 out.png"
    files = _files(pics)
    first = _bash(_never(files), pics, command)
    assert first.get("exit_code") == 0, first
    assert sorted(p.name for p in pics.iterdir()) == ["multi.gif", "out-0.png", "out-1.png", "out-2.png"]
    again = _bash(_never(files), pics, command)
    assert again.get("exit_code") == 0, "the run's own copies: a plain write"
    resumed = RunFiles(str(pics), "boss", carried=json.loads(json.dumps(files.carried())),
                       session_id=files.session_id)
    assert _never(resumed).decision_for("bash", command).allowed is True

    for p in pics.glob("out-*.png"):
        p.write_text(f"{MINE} {p.name}", encoding="utf-8")
    refused = _bash(_never(_files(pics)), pics, command)
    assert refused.get("blocked") is True, refused
    assert f"(it cannot be known whether convert writes over out-0.png, {THERE})" in refused["error"]
    for p in pics.glob("out-*.png"):
        assert p.read_text(encoding="utf-8") == f"{MINE} {p.name}"


def test_file_converter_asks_before_a_burst_photos_copies_and_not_without_them(tmp_path):
    """File Converter's own command under its hire's `ask`: a drop folder
    whose `converted/` holds only the copies its test skips runs with no
    card; one holding a numbered copy its tests do not skip waits for a
    yes, naming it. (`B1695` changed which: the photo kind now tests a
    burst's first copy, so `IMG_7-1.jpg` there skips `IMG_7.heic` whole —
    `tests/test_a_burst_converted_before_is_skipped_whole.py` — and the
    copy that still asks is a numbered one whose first is not there.)"""
    m = get_agent(None, "file-converter")
    command = E.load_evals(m)[0]["script"][0]["call"][0][1]["command"]
    drop = tmp_path / "proj" / "drop"
    (drop / "converted").mkdir(parents=True)
    for name in ("IMG_2041.heic", "converted/IMG_2041.jpg", "IMG_7.heic"):
        (drop / name).write_text("there", encoding="utf-8")

    def ask():
        return ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}),
                                      files=RunFiles(str(tmp_path / "proj"), "boss",
                                                     session_id=f"s-{uuid.uuid4().hex[:8]}",
                                                     hired=True))

    assert ask().decision_for("bash", command).allowed is True
    (drop / "converted" / "IMG_7-2.jpg").write_text("a burst's second", encoding="utf-8")
    asked = ask().decision_for("bash", command)
    assert asked.allowed is False
    assert (f"(it cannot be known whether heif-convert writes over converted/IMG_7-2.jpg, {THERE})"
            in asked.reason)


def test_in_the_workstation_the_folder_is_listed_there(ws, settings, people):
    """The workstation lists the folder: a never refuses a conversion with a
    numbered copy of the person's there, and nothing is written over."""
    _on(settings, ws)
    files = RunFiles(None, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / "out-1.png").write_text(MINE, encoding="utf-8")
    command = "convert in.gif out.png"

    async def go():
        await files.look("bash", command)
        return (await te.execute_tool_block(ToolBlock("bash", command), owner="ann",
                                            session_id=files.session_id, security_context=run))[1]

    refused = asyncio.run(go())
    assert refused.get("blocked") is True, refused
    assert (f"(it cannot be known whether convert writes over out-1.png in your workstation, {THERE})"
            in refused["error"])
    assert (home / "out-1.png").read_text(encoding="utf-8") == MINE
