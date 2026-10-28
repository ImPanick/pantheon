# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1635` — Screenshot Reporter's PDF holds the pages in the order they were
listed, however many there are.

Measured before the fix: the one command named each capture by its place in
the list, `.shots-$d/$i.png`, and made the PDF with
`img2pdf .shots-$d/*.png`. The shell sorts a glob by name, so from the tenth
page on the order was `1, 10, 11, 2, 3, …` — the runbook's own judgement call
("the pages go into the PDF in the order the person listed them") was broken by
its own command. Each capture is now numbered with three digits
(`$(printf %03d $i)`), so the glob's order is the list's — a hire's list holds
at most 50 pages (`hires.check_inputs`).

Driven (`Law 20`): the runbook's own command, filled as it says, runs with the
real `img2pdf`; the browser is a stand-in that draws each page as a picture as
wide as the page's number, so the PDF's pictures, read back with `pypdf`, say
which page each one is. The control runs the command as it was, on the same
eleven pages.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents.catalogue import get_agent
from test_a_name_runs_nothing_on_the_far_side import _q, _steps

pytestmark = pytest.mark.skipif(shutil.which("img2pdf") is None, reason="img2pdf is not installed here")

#: A browser that draws the page it is handed — the word after `--`, or, as
#: the command was, its last word — as a PNG `width` pixels wide, where
#: `width` is the page's number (`…/p07` → 107), at the path `--screenshot=`
#: names.
STAND_IN_CHROMIUM = r'''#!%(python)s
import struct, sys, zlib
args = sys.argv[1:]
out = next(a.split("=", 1)[1] for a in args if a.startswith("--screenshot="))
page = args[args.index("--") + 1] if "--" in args else args[-1]
width = 100 + int(page.rsplit("p", 1)[1])
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
rows = b"".join(b"\x00" + b"\x80" * width for _ in range(4))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 4, 8, 0, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
open(out, "wb").write(png)
'''

#: Eleven pages, listed out of their numbers' order, so a PDF in the listed
#: order is one no sort by name or number could make by accident.
PAGES = [f"https://dash.example/p{n:02d}" for n in (7, 3, 11, 1, 10, 2, 9, 4, 8, 6, 5)]

#: The command's capture and PDF as they were, for the control.
OLD_CAPTURE = "--screenshot=.shots-$d/$i.png \"$u\""


def _command() -> str:
    spans = [s for s in re.findall(r"`([^`]+)`", _steps(get_agent(None, "screenshot-reporter").runbook))
             if "img2pdf" in s]
    assert len(spans) == 1, spans
    return (spans[0].replace("'<folder>'", _q("Morning Reports"))
            .replace("<the pages, each in single quotes>", " ".join(map(_q, PAGES))))


@pytest.fixture
def reports(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    chromium = bin_ / "chromium"
    chromium.write_text(STAND_IN_CHROMIUM % {"python": sys.executable}, encoding="utf-8")
    chromium.chmod(chromium.stat().st_mode | stat.S_IXUSR)
    projects = tmp_path / "projects"
    (projects / "Morning Reports").mkdir(parents=True)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ.get('PATH', '/usr/bin:/bin')}", PANTHEON_PROJECTS=str(projects))

    def run(command: str):
        done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=120,
                              cwd=str(tmp_path))
        pdfs = sorted((projects / "Morning Reports").glob("*.pdf"))
        assert len(pdfs) == 1, (done.stdout, done.stderr)
        return done.stdout, _pages(pdfs[0])
    return run


def _pages(pdf: Path):
    """Each page of the PDF, as the page it is a picture of."""
    from pypdf import PdfReader
    out = []
    for page in PdfReader(str(pdf)).pages:
        xobjects = page["/Resources"]["/XObject"]
        (image,) = [xobjects[k].get_object() for k in xobjects]
        out.append(f"https://dash.example/p{int(image['/Width']) - 100:02d}")
    return out


def test_eleven_pages_make_a_pdf_in_the_order_they_were_listed(reports):
    out, pages = reports(_command())
    assert pages == PAGES
    # What it printed says the same order, so the answer's Captured list can.
    assert re.findall(r"^OK \d+ (\S+)$", out, re.M) == PAGES
    assert "PDF " in out


def test_the_command_as_it_was_put_the_tenth_page_second(reports):
    """The control: the captures named `$i.png`, as before, on the same list —
    the shell's sort put `10.png` and `11.png` before `2.png`."""
    command = _command()
    new_capture = "--screenshot=.shots-$d/$(printf %03d $i).png -- \"$u\""
    assert new_capture in command
    out, pages = reports(command.replace(new_capture, OLD_CAPTURE))
    assert pages != PAGES
    assert pages[:4] == [PAGES[0], PAGES[9], PAGES[10], PAGES[1]]
