# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1699` — File Converter's answer names the copies a burst is written as.

Measured before the fix: real `bash` ran File Converter's 1.5.0 command with
a stand-in `heif-convert` naming a burst's copies as `heif_dec.cc` does, and
printed `OK IMG_0007.heic -> converted/IMG_0007.jpg` while it wrote
`IMG_0007-1.jpg`…`-3.jpg` and no `IMG_0007.jpg`: the line echoed the name the
command handed the converter, so the answer named a file that is not there.

Now (1.5.0 → 1.6.0, runbook and every case's command) the photo kind's `OK`
line names what is there once the converter has run — `ls -dv` of the one
name and the numbered ones, in their numbers' order: `OK IMG_0007.heic ->
converted/IMG_0007-1.jpg converted/IMG_0007-2.jpg converted/IMG_0007-3.jpg`.
The runbook says so, and a new case, `a-burst-converted`, answers with the
copies. The command reads as it did: a re-run over a burst converted before
still runs under its hire's `ask` with no card.

Driven (`Law 20`): File Converter's own command from its catalogue entry, run
by real `bash` with the stand-in on the path; the gate over the re-run; and
the new case through the real harness.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from src.agents import evals as E
from tests.test_a_burst_converted_before_is_skipped_whole import (
    _HEIF_CONVERT, _ask, _file_converter,
)

#: The 1.5.0 photo kind's `OK` line, which named the name it handed over.
OLD_OK = 'echo "OK $f -> converted/${f%.*}.jpg"'
NEW_OK = 'echo "OK $f ->" $(ls -dv "converted/${f%.*}.jpg" "converted/${f%.*}"-[0-9]*.jpg 2>/dev/null)'


def _drop(tmp_path: Path) -> tuple:
    """A drop folder holding a burst of three, one of twelve, a single
    photo and a burst whose name holds a space; and a way to run a command
    there with the stand-in `heif-convert` on the path."""
    projects = tmp_path / "proj"
    drop = projects / "drop"
    drop.mkdir(parents=True)
    for name, count in (("IMG_0007.heic", 3), ("IMG_0012.heic", 12), ("IMG_2041.heic", 1),
                        ("IMG 8.heic", 2)):
        (drop / name).write_text(f"{count}\n", encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "heif-convert").write_text(_HEIF_CONVERT, encoding="utf-8")
    (bin_ / "heif-convert").chmod(0o755)
    (tmp_path / "home").mkdir()
    env = {"PATH": f"{bin_}:{os.environ.get('PATH', '/usr/bin:/bin')}",
           "HOME": str(tmp_path / "home"), "PANTHEON_PROJECTS": str(projects)}

    def run(text: str) -> list:
        out = subprocess.run(["bash", "-c", text], env=env, capture_output=True, text=True,
                             timeout=120).stdout
        return [line for line in out.splitlines() if line.startswith("OK ")]
    return projects, drop, run


def test_a_bursts_ok_line_names_the_copies_that_exist(tmp_path):
    """The row's `Verify:`: each photo's `OK` line names exactly the copies
    there once it has run — a burst's numbered ones in order, a single
    photo's one name — and none that is not."""
    _m, _cases, command = _file_converter()
    _projects, drop, run = _drop(tmp_path)
    lines = run(command)
    assert sorted(lines) == sorted([
        "OK IMG 8.heic -> converted/IMG 8-1.jpg converted/IMG 8-2.jpg",
        "OK IMG_0007.heic -> converted/IMG_0007-1.jpg converted/IMG_0007-2.jpg "
        "converted/IMG_0007-3.jpg",
        "OK IMG_0012.heic -> " + " ".join(f"converted/IMG_0012-{i}.jpg" for i in range(1, 13)),
        "OK IMG_2041.heic -> converted/IMG_2041.jpg",
    ]), lines
    made = sorted(f"converted/{p.name}" for p in (drop / "converted").iterdir())
    assert len(made) == 3 + 12 + 1 + 2
    assert all(any(f" {name}" in line for line in lines) for name in made)


def test_the_old_line_named_a_file_it_never_wrote(tmp_path):
    """The premise: 1.5.0's line, run the same way, names
    `converted/IMG_0007.jpg`, which is not there."""
    _m, _cases, command = _file_converter()
    _projects, drop, run = _drop(tmp_path)
    lines = run(command.replace(NEW_OK, OLD_OK))
    assert "OK IMG_0007.heic -> converted/IMG_0007.jpg" in lines
    assert not (drop / "converted" / "IMG_0007.jpg").exists()


def test_file_converter_carries_the_line_everywhere_and_still_skips_a_burst(tmp_path):
    """1.6.0: the runbook and every case's command; the line's own words
    write nothing, so a re-run over the burst it converted runs under the
    hire's `ask` with no card, and prints nothing."""
    m, cases, command = _file_converter()
    assert m.version == "1.6.0"
    assert NEW_OK in m.runbook and OLD_OK not in m.runbook
    assert "names every copy it made" in m.runbook
    for case in cases:
        for step in case["script"]:
            for tool, args in step.get("call") or []:
                if tool == "bash" and "convert-to" in args["command"]:
                    assert NEW_OK in args["command"], case["id"]
    projects, _drop_folder, run = _drop(tmp_path)
    assert run(command), "the first run converts"
    assert _ask(projects).decision_for("bash", command).allowed is True
    assert run(command) == []


def test_the_burst_case_answers_with_its_copies():
    """`a-burst-converted` through the real harness: the answer names the
    three copies, and no `converted/IMG_0007.jpg`."""
    m, cases, _command = _file_converter()
    case = next(c for c in cases if c["id"] == "a-burst-converted")
    output = case["world"]["shell"][0]["output"]
    assert output == ("OK IMG_0007.heic -> converted/IMG_0007-1.jpg converted/IMG_0007-2.jpg "
                      "converted/IMG_0007-3.jpg")
    [result] = asyncio.run(E.run_agent(m, cases=[case]))
    assert result.passed, (result.case, result.checks)
    assert result.status == "success" and result.calls.count("bash") == 1
