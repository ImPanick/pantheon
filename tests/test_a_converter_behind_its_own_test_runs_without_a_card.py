# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1690` — LibreOffice and `heif-convert` writing over a file are read,
and so is the test a loop or a branch puts before a write: File Converter's
`[ -e … ] && continue` and `if [ ! -e f ]; then …`.

Measured before the fix, with the file there: `libreoffice --convert-to pdf
--outdir out notes.docx` (over `out/notes.pdf`) and `heif-convert in.heic
notes.jpg` gave `call_destroys` `None` — `execute_code` alone. And a test
only counted over the next command (`B1682`): `for f in *; do o=…; [ -e "$o"
] && continue; echo x > "$o"; done` and `if [ ! -e notes.md ]; then echo x >
notes.md; fi` were destructive, though neither can write over anything.

Now (`src/shell_reading.py`): LibreOffice's `--convert-to EXT` writes each
document's name without its last extension, `.EXT`, in `--outdir` (or where
it runs) — over what is there, *"Overwriting: …"* — and `heif-convert` its
`-o`, its second word, or its input up to the last `.` with `.jpg`. A name
made from a quoted variable is read in the shell's own words: `heif-convert
"$f"` writes `${f%.*}.jpg`, and inside `for f in *` — a name with no `/` and
no leading `.` — `libreoffice --outdir converted "$f"` writes
`converted/${f%.*}.pdf`. And `_Tests` follows a loop's `[ -e f ] && continue`
over the rest of its body and an `if [ ! -e f ]` over its branch — only in
the same shell as the loop, at the head of its list, until the body ends, a
`cd`, or anything that could set a variable in `f` — so a write at those same
words replaces nothing.

File Converter's loop tested `"$o"` (`o="converted/$b.pdf"`) before
`libreoffice`, whose output the command never names: read, every run with a
`converted/` folder would have waited for a yes under its `ask`. So each kind
now tests the very file it writes (1.3.0 → 1.4.0). Measured on the shipped
evals: at the old runbooks 7 of 378 `bash` calls changed reading — File
Converter's 6, and Config Drift's `scp` (`B1688`); after 1.4.0, only Config
Drift's.

Driven (`Law 20`): the real reader and the run's record over a real folder;
File Converter's own command run twice by real `bash` and real LibreOffice,
read between by the real gate under its hire's `ask`; and File Converter
through the real harness, its earlier copies there.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from src.agents import evals as E
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys

THERE = "which was there before this run began"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's documents and photos, a folder of
    copies an earlier run made, and a site."""
    ws = tmp_path / "proj"
    for sub in ("out", "converted", "site"):
        (ws / sub).mkdir(parents=True)
    for name in ("notes.md", "notes.pdf", "notes.jpg", "shot.xmp", "out/notes.pdf",
                 "out/my.notes.v2.pdf", "converted/a.pdf", "converted/a.jpg", "site/index.html",
                 "a.docx", "a.heic"):
        (ws / name).write_text(f"the person's {name}", encoding="utf-8")
    return ws


def _files(folder: Path, hired: bool = False) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}", hired=hired)


def _reads(folder: Path, command: str):
    return call_destroys("bash", command, _files(folder))


#: Each over a file that was there, its new-path twin, and what writes.
OVER = (
    ("libreoffice --headless --convert-to pdf --outdir out notes.docx",
     "libreoffice --headless --convert-to pdf --outdir out fresh.docx", "libreoffice --convert-to",
     "out/notes.pdf"),
    ("soffice --headless --convert-to 'pdf:writer_pdf_Export' --outdir out notes.odt",
     "soffice --headless --convert-to 'pdf:writer_pdf_Export' --outdir fresh notes.odt",
     "soffice --convert-to", "out/notes.pdf"),
    ("libreoffice7.6 -convert-to pdf -outdir out my.notes.v2.docx",
     "libreoffice7.6 -convert-to pdf -outdir out my.notes.v3.docx", "libreoffice7.6 --convert-to",
     "out/my.notes.v2.pdf"),
    ("lowriter --convert-to pdf notes.docx", "lowriter --convert-to odt notes.docx",
     "lowriter --convert-to", "notes.pdf"),
    ("heif-convert in.heic notes.jpg", "heif-convert in.heic new.jpg", "heif-convert", "notes.jpg"),
    ("heif-convert notes.heic", "heif-convert new.heic", "heif-convert", "notes.jpg"),
    ("heif-convert -q 90 -o notes.jpg in.heic", "heif-convert -q 90 -o new.jpg in.heic",
     "heif-convert", "notes.jpg"),
    ("heif-dec in.heic notes.jpg", "heif-dec in.heic new.png", "heif-dec", "notes.jpg"),
    ("heif-convert --with-xmp in.heic shot.jpg", "heif-convert --with-xmp in.heic snap.jpg",
     "heif-convert --with-xmp", "shot.xmp"),
)


@pytest.mark.parametrize("over,new,why,shown", OVER)
def test_over_a_file_that_was_there_it_is_destructive(folder, over, new, why, shown):
    """The row's `Verify:`, one program at a time, naming what writes."""
    assert _reads(folder, over) == f"{why} replaces {shown}, {THERE}"


@pytest.mark.parametrize("over,new,why,shown", OVER)
def test_onto_a_new_path_it_is_a_plain_write(folder, over, new, why, shown):
    assert _reads(folder, new) is None


def test_what_writes_no_file_or_no_name_it_holds(folder):
    """`--cat` is the screen and a bare `libreoffice notes.docx` opens it;
    `--print-to-file` and a document filled in when it runs are named by
    LibreOffice, `--with-aux` by the file — unknowable where they land."""
    for command in ("libreoffice --cat notes.docx", "libreoffice notes.docx",
                    "libreoffice --headless --convert-to pdf", "heif-convert --list-decoders",
                    "heif-convert --version"):
        assert _reads(folder, command) is None, command
    for command, why, shown in (('libreoffice --convert-to pdf --outdir out "$doc"',
                                 "libreoffice --convert-to", "out"),
                                ("libreoffice --print-to-file --outdir out notes.docx",
                                 "libreoffice --print-to-file", "out")):
        assert _reads(folder, command) == \
            f"it cannot be known whether what {why} writes in {shown} was there before this run began"
    assert _reads(folder, "heif-convert --with-aux in.heic snap.jpg") == \
        f"it cannot be known whether snap-* was there before this run began"
    assert _reads(folder, 'heif-convert "$f"') == \
        "it cannot be known whether ${f%.*}.jpg was there before this run began"


# ── a test over the rest of a body ──────────────────────────────────────────

def test_a_loops_test_rules_out_the_rest_of_its_body(folder):
    """`[ -e f ] && continue` (or `break`, `[ ! -e f ] || continue`, `test`,
    `[[ ]]`) at the head of its list, in the same shell as its loop: what
    follows in the body writes at `f` only when nothing was there."""
    for command in (
            'for f in *; do [ -e "converted/${f%.*}.pdf" ] && continue; '
            'libreoffice --headless --convert-to pdf --outdir converted "$f"; done',
            'for f in *.heic; do [ -e "converted/${f%.*}.jpg" ] && continue; '
            'heif-convert "$f" "converted/${f%.*}.jpg" && echo "OK $f" || echo "FAIL $f"; done',
            'for f in *; do o="converted/$f.txt"; [ -e "$o" ] && continue; echo x > "$o"; done',
            "for i in 1; do [ ! -e notes.md ] || continue; echo hi > notes.md; done",
            "for i in 1; do test -e notes.md && break; echo hi > notes.md; done",
            "for i in 1; do [[ -e notes.md ]] && continue; date; echo hi > notes.md; done",
            "for i in 1; do for j in 2; do [ -e notes.md ] && continue 2; echo hi > notes.md; done; done",
            "for i in 1; do false || [ -e notes.md ] && continue; echo hi > notes.md; done",
            "while read -r f; do [ -e notes.md ] && continue\necho hi > notes.md\ndone < list.txt",
            "for i in 1; do [ -e notes.md ] && continue; date | tee notes.md; done",
            "for i in 1; do [ -e notes.md ] && continue; sh -c 'echo hi > notes.md'; done"):
        assert _reads(folder, command) is None, command
    # `B1693` changed this one: the test speaks for `$o`, while `heif-convert`
    # writes `…-1.jpg`, `…-2.jpg` beside it for a file holding several
    # images, in a folder `$o`'s words do not name (`converted/${f%.*}.jpg`,
    # spelled out above, is looked in).
    assert _reads(folder, 'for f in *.heic; do o="converted/${f%.*}.jpg"; [ -e "$o" ] && continue; '
                          'heif-convert "$f" "$o"; done') == \
        "it cannot be known whether what heif-convert writes beside $o was there before this run began"


def test_a_loops_test_does_not_speak_where_bash_would_run_on(folder):
    """No loop, a subshell or a pipe (`continue` ends nothing there), a test
    after an `&&` (what came before failing runs the rest), a test the other
    way round, `continue 0`, another path, past the body or the arm, after a
    `cd` or a new value for its variable, a function or a `trap` in the
    command — or a variable in a shell of its own, which has only what was
    exported."""
    a_write = f"a > redirect replaces notes.md, {THERE}"
    for command in ("[ -e notes.md ] && continue; echo hi > notes.md",
                    "for i in 1; do ( [ -e notes.md ] && continue; echo hi > notes.md ); done",
                    "for i in 1; do [ -e notes.md ] && continue | cat; echo hi > notes.md; done",
                    "for i in 1; do mkdir -p d && [ -e notes.md ] && continue; echo hi > notes.md; done",
                    "for i in 1; do [ -e notes.md ] || continue; echo hi > notes.md; done",
                    "for i in 1; do [ ! -e notes.md ] && continue; echo hi > notes.md; done",
                    "for i in 1; do [ -e notes.md ] && continue 0; echo hi > notes.md; done",
                    "for i in 1; do [ -e ./notes.md ] && continue; echo hi > notes.md; done",
                    "for i in 1; do [ -e notes.md ] && continue; done; echo hi > notes.md",
                    "for i in 1; do case $i in 1) [ -e notes.md ] && continue;; esac; echo hi > notes.md; done",
                    "f() { :; }; for i in 1; do [ -e notes.md ] && continue; echo hi > notes.md; done",
                    "trap 'date' EXIT; for i in 1; do [ -e notes.md ] && continue; echo hi > notes.md; done"):
        assert _reads(folder, command) == a_write, command
    assert _reads(folder, "for i in 1; do [ -e index.html ] && continue; cd site; echo hi > index.html; done") \
        == f"a > redirect replaces index.html, {THERE}"
    for command in ('for i in 1; do [ -e "$o" ] && continue; o=notes.md; echo hi > "$o"; done',
                    'for i in 1; do [ -e "$o" ] && continue; read -r o < list; echo hi > "$o"; done',
                    'for i in 1; do [ -e "$o" ] && continue; : "${o:=notes.md}"; echo hi > "$o"; done',
                    'for i in 1; do [ -e "$o" ] && continue; sh -c \'echo hi > "$o"\'; done',
                    '[ -e "$o" ] || bash -c \'echo hi > "$o"\''):
        assert _reads(folder, command) == "it cannot be known whether $o was there before this run began", \
            command


def test_an_if_branch_rules_out_what_it_holds(folder):
    """`if [ ! -e f ]; then …` — the whole condition — over its branch."""
    for command in ("if [ ! -e notes.md ]; then echo hi > notes.md; fi",
                    "if ! [ -e notes.md ]; then date; echo hi > notes.md; fi",
                    "if test ! -e notes.md\nthen\n  echo hi > notes.md\nfi",
                    "if [[ ! -e notes.md ]]; then cp other.md notes.md; fi",
                    "if false; then :; elif [ ! -e notes.md ]; then echo hi > notes.md; fi",
                    "if [ ! -e notes.md ]; then if true; then echo hi > notes.md; fi; fi",
                    'for f in *; do if [ ! -e "converted/${f%.*}.jpg" ]; then '
                    'heif-convert "$f" "converted/${f%.*}.jpg"; fi; done'):
        assert _reads(folder, command) is None, command
    for command, shown in (("if [ -e notes.md ]; then echo hi > notes.md; fi", "a > redirect"),
                           ("if [ ! -e notes.md ]; then :; else echo hi > notes.md; fi", "a > redirect"),
                           ("if [ ! -e notes.md ]; then :; fi; echo hi > notes.md", "a > redirect"),
                           ("if [ ! -e notes.md ]; true; then echo hi > notes.md; fi", "a > redirect"),
                           ("if [ ! -e notes.md ] || true; then echo hi > notes.md; fi", "a > redirect"),
                           ("if [ ! -e other.md ]; then cp a.md notes.md; fi", "cp")):
        assert _reads(folder, command) == f"{shown} replaces notes.md, {THERE}", command


def test_b1682s_test_takes_any_words_that_name_one_file(folder):
    """The next-command test (`B1682`) now takes a path spelled with any
    quoted variables — the same words, the same file — and a `!` in front;
    not a command's output or anything unquoted."""
    assert _reads(folder, '[ -e "converted/$b.webp" ] || cwebp in.png -o "converted/$b.webp"') is None
    assert _reads(folder, "! [ -e notes.md ] && echo hi > notes.md") is None
    assert _reads(folder, '[ -e "$(date).md" ] || echo hi > "$(date).md"') == \
        "it cannot be known whether $(date).md was there before this run began"
    assert _reads(folder, "[ -e $o ] || echo hi > $o") == \
        "it cannot be known whether $o was there before this run began"


def test_a_loops_name_holds_a_name_in_the_folder_only_from_names_in_the_folder(folder):
    """`for f in *` hands names with no `/` and no leading `.`; a list that
    can hand anything else, a `dotglob`, or a new value for `f` leaves
    LibreOffice's output unknowable where it lands."""
    guarded = ('for f in {}; do [ -e "converted/${{f%.*}}.pdf" ] && continue; '
               'libreoffice --convert-to pdf --outdir converted "$f"; done')
    for listed in ("*", "*.docx a.odt", "*.docx *.odt"):
        assert _reads(folder, guarded.format(listed)) is None, listed
    unknowable = ("it cannot be known whether what libreoffice --convert-to writes in converted was "
                  "there before this run began")
    for command in (guarded.format("*/*"), guarded.format(".*"), guarded.format('"$@"'),
                    guarded.format("$list"), "shopt -s dotglob; " + guarded.format("*"),
                    guarded.format("*").replace("do [", 'do f="../$f"; ['),
                    "for f; do " + guarded.format("*").split("; do ", 1)[1]):
        assert _reads(folder, command) == unknowable, command


# ── File Converter ──────────────────────────────────────────────────────────

def _file_converter():
    m = get_agent(None, "file-converter")
    cases = E.load_evals(m)
    command = cases[0]["script"][0]["call"][0][1]["command"]
    return m, cases, command


def test_file_converters_runbook_tests_the_very_file_each_kind_writes():
    """1.4.0: its runbook and every case run the one command, and each kind
    tests the file it is about to write — not an `$o` LibreOffice never
    names. (`B1695` made it 1.5.0: the photo kind also tests a burst's
    first numbered copy — `tests/test_a_burst_converted_before_is_skipped_whole.py`;
    `B1699` 1.6.0: its `OK` line names a burst's copies —
    `tests/test_a_bursts_answer_names_the_copies_it_wrote.py`.)"""
    m, cases, command = _file_converter()
    assert m.version == "1.6.0"
    assert H.manifest_effects(m)["destructive"] == "ask"
    for kind, write in (("pdf", 'libreoffice --headless --convert-to pdf --outdir converted "$f"'),
                        ("jpg", 'heif-convert "$f" "converted/${f%.*}.jpg"'),
                        ("mp4", '-c:a aac "converted/${f%.*}.mp4"')):
        assert f'[ -e "converted/${{f%.*}}.{kind}" ] && continue; ' in command
        assert write in command
    for case in cases:
        for step in case["script"]:
            for tool, args in step.get("call") or []:
                if tool == "bash" and "convert-to" in args["command"]:
                    assert args["command"] == command, case["id"]
    runbook = command.replace("'drop'", "'<folder>'").replace("|DOCX|ODT", "").replace(
        "|HEIC", "").replace("|MOV|MKV", "")
    assert runbook in m.runbook


def test_file_converter_runs_under_its_ask_without_a_card_with_its_copies_there(tmp_path):
    """The gate, over a drop folder whose copies an earlier run made: no
    card; the same command without the PDF's test waits for a yes."""
    _m, _cases, command = _file_converter()
    drop = tmp_path / "proj" / "drop"
    (drop / "converted").mkdir(parents=True)
    for name in ("contract.docx", "IMG_2041.heic", "converted/contract.pdf", "converted/IMG_2041.jpg"):
        (drop / name).write_text("there", encoding="utf-8")

    def ask():
        return ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}),
                                      files=_files(tmp_path / "proj", hired=True))

    assert ask().decision_for("bash", command).allowed is True
    asked = ask().decision_for("bash", command.replace('[ -e "converted/${f%.*}.pdf" ] && continue; ', ""))
    assert asked.allowed is False
    assert "(it cannot be known whether converted/${f%.*}.pdf was there before this run began)" in asked.reason


@pytest.mark.skipif(shutil.which("libreoffice") is None or shutil.which("pandoc") is None,
                    reason="LibreOffice or pandoc is not installed")
def test_file_converters_command_writes_where_it_was_read_to_and_skips_it_after(tmp_path):
    """Real `bash`, real LibreOffice: the first run writes exactly
    `converted/${f%.*}.pdf` for each document (a name with dots and a space
    too); the gate then reads the command, with those copies there, as
    writing over nothing; and a second run leaves each copy as it was."""
    _m, _cases, command = _file_converter()
    projects = tmp_path / "proj"
    drop = projects / "drop"
    drop.mkdir(parents=True)
    source = tmp_path / "c.md"
    source.write_text("# Contract\n\nTerms.\n", encoding="utf-8")
    for name in ("contract.docx", "my.report v2.odt"):
        subprocess.run(["pandoc", str(source), "-o", str(drop / name)], check=True, timeout=120)
    (drop / "invoice.pdf").write_text("%PDF the person's own", encoding="utf-8")
    (tmp_path / "home").mkdir()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "home"),
           "PANTHEON_PROJECTS": str(projects)}

    def run():
        return subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True,
                              timeout=300).stdout

    first = run()
    assert "OK contract.docx -> converted/contract.pdf" in first, first
    assert "OK my.report v2.odt -> converted/my.report v2.pdf" in first, first
    assert "SKIP invoice.pdf" in first
    made = sorted(p.name for p in (drop / "converted").iterdir())
    assert made == ["contract.pdf", "my.report v2.pdf"]          # `${f%.*}.pdf`, each
    for pdf in (drop / "converted").iterdir():
        pdf.write_text("kept from the first run", encoding="utf-8")
    run_ask = ToolRunSecurityContext(hire_ask_effects=frozenset({"destructive"}),
                                     files=_files(projects, hired=True))
    assert run_ask.decision_for("bash", command).allowed is True
    second = run()
    assert "OK" not in second and "SKIP invoice.pdf" in second, second
    for pdf in (drop / "converted").iterdir():
        assert pdf.read_text(encoding="utf-8") == "kept from the first run"


def test_file_converter_through_the_harness():
    """Every case passes; `nothing-new`, whose world holds the copies an
    earlier run made, runs its command under the hire's `ask` with no
    card — before `_Tests` read the `continue`, it waited for a yes."""
    m, cases, _command = _file_converter()
    world = next(c for c in cases if c["id"] == "nothing-new")["world"]
    assert {"drop/converted/contract.pdf", "drop/converted/IMG_2041.jpg"} <= set(world["files"])
    results = asyncio.run(E.run_agent(m))
    assert len(results) == len(cases)
    for result in results:
        assert result.passed, (result.case, result.checks)
    nothing_new = next(r for r in results if r.case == "nothing-new")
    assert nothing_new.status == "success" and "bash" in nothing_new.calls
    assert json.dumps(nothing_new.checks).count('"ok": false') == 0
