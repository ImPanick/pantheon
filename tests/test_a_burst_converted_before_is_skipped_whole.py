# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1695` — File Converter skips a burst photo it converted before, and the
reading sees the test that skips it.

Measured before the fix: `heif-convert` writes `X-1.jpg`, `X-2.jpg`… — and
no `X.jpg` — for a file holding several images (`heif_dec.cc`), so File
Converter's photo test, `[ -e "converted/${f%.*}.jpg" ] && continue`, never
skipped a burst: each re-run converted it again, and since `B1693` read
those copies as numbered names that were there, waiting for a yes that named
one (`it cannot be known whether heif-convert writes over
converted/IMG_0007-1.jpg…`) every half hour.

Now the photo kind also tests the burst's first copy — `[ -e
"converted/${f%.*}-1.jpg" ] && continue` (1.4.0 → 1.5.0) — and the reader
follows that test: `heif-convert` numbers its images from 1, one after
another, so it writes the first whenever it writes any, and a test of the
first speaks for them all (`Finding.first`, `tested`). The run then reads a
numbered name that was there as written over only where the first of its
own is not beside it (`run_files._first_of`): a burst converted before is
skipped whole, while `IMG_7-2.jpg` with no `IMG_7-1.jpg` — another file's
copy a new burst would write over — still asks. ImageMagick's numbers start
at a frame's scene, not a fixed number, and are not followed.

Measured on the shipped evals: File Converter's 6 `bash` calls changed
reading (the numbered write now carries its first name and its test); no
other call changed. Its new case, `a-burst-converted-before`, runs under its
`ask` with no card.

Driven (`Law 20`): the real reader and the run's record over a real folder;
File Converter's own command under its hire's `ask` through the real gate;
the command run twice by real `bash`, with a stand-in `heif-convert` on the
path that names a burst's copies as `heif_dec.cc` does (none is installed
here); and the new case through the real harness.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from src.agents import evals as E
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.shell_reading import read_shell
from src.tool_capabilities import ToolRunSecurityContext, call_destroys

THERE = "which was there before this run began"
FIRST_TEST = '[ -e "converted/${f%.*}-1.jpg" ] && continue; '
LOOP = ('for f in *; do [ -e "converted/${f%.*}.jpg" ] && continue; ' + FIRST_TEST
        + 'heif-convert "$f" "converted/${f%.*}.jpg"; done')


def _files(folder: Path, hired: bool = False) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}", hired=hired)


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


@pytest.fixture
def folder(tmp_path):
    """A drop folder: a burst, and `converted/` beside it."""
    drop = tmp_path / "drop"
    (drop / "converted").mkdir(parents=True)
    (drop / "IMG_7.heic").write_text("a burst", encoding="utf-8")
    return drop


def _put(folder: Path, *names: str) -> None:
    for name in names:
        (folder / "converted" / name).write_text(f"an earlier copy, {name}", encoding="utf-8")


def test_the_reading_carries_the_first_name_and_the_test_of_it():
    """The numbered write names its first, as the command spells it, and
    is marked tested where a test of exactly those words skips it."""
    numbered = [f for f in read_shell(LOOP) if f.numbered]
    assert len(numbered) == 1
    assert numbered[0].first == "converted/${f%.*}-1.jpg" and numbered[0].tested is True
    untested = [f for f in read_shell(LOOP.replace(FIRST_TEST, "")) if f.numbered]
    assert untested[0].first == "converted/${f%.*}-1.jpg" and untested[0].tested is False


def test_a_bursts_copies_behind_the_test_of_its_first_are_skipped(folder):
    """The row's `Verify:` at the reading: a burst converted before — its
    first copy there — is no write over anything; without the test, the
    same folder waits for a yes naming the first copy."""
    _put(folder, "IMG_7-1.jpg", "IMG_7-2.jpg", "IMG_7-3.jpg")
    assert _reads(folder, LOOP) is None
    assert _reads(folder, LOOP.replace(FIRST_TEST, "")) == \
        f"it cannot be known whether heif-convert writes over converted/IMG_7-1.jpg, {THERE}"


def test_a_numbered_copy_whose_first_is_not_there_still_asks(folder):
    """`IMG_7-2.jpg` with no `IMG_7-1.jpg` is not a burst converted before
    — a burst named `IMG_7` would write over it — and another name's first
    does not speak for it."""
    _put(folder, "IMG_7-2.jpg")
    assert _reads(folder, LOOP) == \
        f"it cannot be known whether heif-convert writes over converted/IMG_7-2.jpg, {THERE}"
    _put(folder, "IMG_8-1.jpg", "IMG_8-2.jpg")
    assert _reads(folder, LOOP) == \
        f"it cannot be known whether heif-convert writes over converted/IMG_7-2.jpg, {THERE}"
    _put(folder, "IMG_7-1.jpg")
    assert _reads(folder, LOOP) is None


def test_the_test_is_followed_where_a_test_is_and_only_of_the_first(tmp_path):
    """Before one command (`[ -e out-1.jpg ] ||`), and in an `if`; a test of
    the second name, or of ImageMagick's first frame (its numbers are a
    frame's scene, not a fixed start), does not speak for them all."""
    for name in ("out-1.jpg", "out-2.jpg", "pic-0.png", "pic-1.png"):
        (tmp_path / name).write_text("there", encoding="utf-8")
    assert _reads(tmp_path, "[ -e out-1.jpg ] || heif-convert in.heic out.jpg") is None
    assert _reads(tmp_path, "if [ ! -e out-1.jpg ]; then heif-convert in.heic out.jpg; fi") is None
    assert _reads(tmp_path, "[ -e out-2.jpg ] || heif-convert in.heic out.jpg") == \
        f"it cannot be known whether heif-convert writes over out-1.jpg, {THERE}"
    assert _reads(tmp_path, "[ -e pic-0.png ] || convert in.gif pic.png") == \
        f"it cannot be known whether convert writes over pic-0.png, {THERE}"
    (tmp_path / "out-1.jpg").unlink()
    assert _reads(tmp_path, "[ -e out-1.jpg ] || heif-convert in.heic out.jpg") == \
        f"it cannot be known whether heif-convert writes over out-2.jpg, {THERE}"


# ── File Converter ──────────────────────────────────────────────────────────

def _file_converter():
    m = get_agent(None, "file-converter")
    cases = E.load_evals(m)
    return m, cases, cases[0]["script"][0]["call"][0][1]["command"]


def test_file_converters_photo_kind_tests_a_bursts_first_copy():
    """1.5.0: the runbook and every case's command test the first copy,
    right after the single name's test, and its hire still asks. (`B1699`
    made it 1.6.0: its `OK` line names the copies that exist.)"""
    m, cases, command = _file_converter()
    assert m.version == "1.6.0"
    assert H.manifest_effects(m)["destructive"] == "ask"
    assert ('heic|HEIC) [ -e "converted/${f%.*}.jpg" ] && continue; ' + FIRST_TEST
            + 'heif-convert "$f" "converted/${f%.*}.jpg"') in command
    assert ('heic) [ -e "converted/${f%.*}.jpg" ] && continue; ' + FIRST_TEST) in m.runbook
    for case in cases:
        for step in case["script"]:
            for tool, args in step.get("call") or []:
                if tool == "bash" and "convert-to" in args["command"]:
                    assert args["command"] == command, case["id"]


def _ask(projects: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}),
                                  files=_files(projects, hired=True))


def test_file_converter_runs_under_its_ask_without_a_card_with_a_burst_there(tmp_path):
    """The gate, over a drop folder holding a burst an earlier run
    converted: no card. The 1.4.0 command — no test of the first copy —
    waited for a yes naming it."""
    _m, _cases, command = _file_converter()
    drop = tmp_path / "proj" / "drop"
    (drop / "converted").mkdir(parents=True)
    for name in ("IMG_0007.heic", "converted/IMG_0007-1.jpg", "converted/IMG_0007-2.jpg",
                 "IMG_2041.heic", "converted/IMG_2041.jpg"):
        (drop / name).write_text("there", encoding="utf-8")
    assert _ask(tmp_path / "proj").decision_for("bash", command).allowed is True
    asked = _ask(tmp_path / "proj").decision_for("bash", command.replace(FIRST_TEST, ""))
    assert asked.allowed is False
    assert (f"(it cannot be known whether heif-convert writes over converted/IMG_0007-1.jpg, {THERE})"
            in asked.reason)


#: A stand-in for libheif's `heif-convert IN OUT` (none is installed here):
#: a file whose first line is a count above one is a burst, written as
#: `heif_dec.cc` names it — the output up to its last `.`, `-1`, `-2`…, then
#: the rest; any other, as `OUT`.
_HEIF_CONVERT = """#!/bin/bash
in="$1"; out="$2"; n=$(head -n 1 "$in")
if [ "$n" -gt 1 ] 2>/dev/null; then
  for i in $(seq 1 "$n"); do echo "photo $i of $in" > "${out%.*}-$i.${out##*.}"; done
else
  echo "photo of $in" > "$out"
fi
"""


def test_a_re_run_leaves_a_bursts_copies_as_they_were(tmp_path):
    """The row's `Verify:`, run: real `bash` runs File Converter's command
    with a burst in the drop folder — the first run writes its numbered
    copies; the gate then reads the next run under the hire's `ask` with no
    card; and the next run leaves them as they were. The 1.4.0 command
    converted the burst again on every run."""
    _m, _cases, command = _file_converter()
    projects = tmp_path / "proj"
    drop = projects / "drop"
    drop.mkdir(parents=True)
    (drop / "IMG_0007.heic").write_text("3\n", encoding="utf-8")
    (drop / "IMG_2041.heic").write_text("1\n", encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "heif-convert").write_text(_HEIF_CONVERT, encoding="utf-8")
    (bin_ / "heif-convert").chmod(0o755)
    (tmp_path / "home").mkdir()
    env = {"PATH": f"{bin_}:{os.environ.get('PATH', '/usr/bin:/bin')}",
           "HOME": str(tmp_path / "home"), "PANTHEON_PROJECTS": str(projects)}

    def run(text: str) -> str:
        return subprocess.run(["bash", "-c", text], env=env, capture_output=True, text=True,
                              timeout=120).stdout

    first = run(command)
    assert "OK IMG_0007.heic" in first and "OK IMG_2041.heic" in first, first
    made = sorted(p.name for p in (drop / "converted").iterdir())
    assert made == ["IMG_0007-1.jpg", "IMG_0007-2.jpg", "IMG_0007-3.jpg", "IMG_2041.jpg"]
    for p in (drop / "converted").iterdir():
        p.write_text("kept from the first run", encoding="utf-8")

    assert _ask(projects).decision_for("bash", command).allowed is True
    second = run(command)
    assert "OK" not in second, second
    for p in (drop / "converted").iterdir():
        assert p.read_text(encoding="utf-8") == "kept from the first run", p.name

    again = run(command.replace(FIRST_TEST, ""))
    assert "OK IMG_0007.heic" in again, "1.4.0 converted the burst again"
    assert (drop / "converted" / "IMG_0007-2.jpg").read_text(encoding="utf-8") != \
        "kept from the first run"


def test_the_burst_case_through_the_harness():
    """`a-burst-converted-before`, whose world holds a burst's copies and
    no single name: the command runs under the hire's `ask` with no card,
    and the copies are as they were."""
    m, cases, _command = _file_converter()
    case = next(c for c in cases if c["id"] == "a-burst-converted-before")
    files = case["world"]["files"]
    assert {"drop/IMG_0007.heic", "drop/converted/IMG_0007-1.jpg"} <= set(files)
    assert "drop/converted/IMG_0007.jpg" not in files
    [result] = asyncio.run(E.run_agent(m, cases=[case]))
    assert result.passed, (result.case, result.checks)
    assert result.status == "success" and result.calls.count("bash") == 1
