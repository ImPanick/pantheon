# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1680` — a program told to write its output over a file is read as
writing over it, as a shell's `>` is (`B1669`).

Measured before the fix, with `notes.md` there: `curl -o notes.md …`,
`sort -o notes.md …`, `wget -O notes.md …`, `unzip -o`, `tar -x` and
`ffmpeg -y … notes.md` gave `call_destroys` `None` — `execute_code` alone —
while `echo x > notes.md` over the same file was `destructive`. So a hire's
`destructive: ask`/`never` and Auto's one exception (`B1341`) never covered a
download, a sort or an extraction over the person's file.

Now each program's own words name what it writes from the start
(`src/shell_reading.py` says which, from each manual), and the run decides,
as for a `>`, whether it was there before the run began: over a file that
was there it is destructive and names it, onto a new path it is a plain
write, and what an archive holds — which the command does not name — into a
folder that was there cannot be known, and is destructive.

`sed -i` is not one of them: it edits a file in place, and the owner ruled
after this row was written that an in-place edit is a plain write
(`D-2026-10-29-03` §1, *"edits stay writes"*, `B1671`) — so it stays as it was.

Measured on the shipped evals: none of the 459 `bash` and `python` calls
(378 and 81) names a write target before or after this change — their
`curl -o /dev/null`, `tar -xzOf`, `ffmpeg -n` and `unzip -l`/`-p` write over
nothing — so no agent's case changed.

Driven (`Law 20`): the real reader and the run's record over a real folder,
and the real gate and dispatcher running the real `sort`, `tar` and `curl`
under a hire's `destructive: never`.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"
NOTES = "Ana's notes — keep these"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's notes, and a folder with a page in it."""
    ws = tmp_path / "proj"
    (ws / "site").mkdir(parents=True)
    (ws / "notes.md").write_text(NOTES, encoding="utf-8")
    (ws / "site" / "index.html").write_text("<h1>mine</h1>", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


#: Each program over `notes.md` (`{}`), and what writes over it.
OVER = (
    ("curl -o {} https://example.com/n", "curl -o"),
    ("curl -sSLo {} https://example.com/n", "curl -o"),
    ("curl --output {} https://example.com/n", "curl --output"),
    ("curl -D {} https://example.com/", "curl -D"),
    ("curl -c {} https://example.com/", "curl -c"),
    ("wget -O {} https://example.com/n", "wget -O"),
    ("wget -qO {} https://example.com/n", "wget -O"),
    ("wget --output-document={} https://example.com/n", "wget --output-document"),
    ("wget -o {} https://example.com/n", "wget -o"),
    ("sort -o {} list.txt", "sort -o"),
    ("sort -u -o{} list.txt", "sort -o"),
    ("sort --output={} list.txt", "sort --output"),
    ("tar -czf {} site", "tar -c"),
    ("ffmpeg -i talk.mp4 -y {}", "ffmpeg -y"),
    ("ffmpeg -y -i talk.mp4 -c:v libx264 -an {}", "ffmpeg -y"),
)


@pytest.mark.parametrize("command,why", OVER)
def test_over_a_file_that_was_there_it_is_destructive(folder, command, why):
    """The row's `Verify:`, one program at a time, naming what writes."""
    assert call_destroys("bash", command.format("notes.md"), _files(folder)) == \
        f"{why} replaces notes.md, {THERE}"


@pytest.mark.parametrize("command,why", OVER)
def test_onto_a_new_path_it_is_a_plain_write(folder, command, why):
    assert call_destroys("bash", command.format("new.md"), _files(folder)) is None


def test_a_download_saved_under_its_own_name_is_read_by_that_name(folder):
    """`curl -O` and `wget -N` save an address under the last part of its
    path (its query is not part of it), in `--output-dir`/`-P` if given."""
    files = _files(folder)
    assert call_destroys("bash", "curl -O 'https://example.com/a/notes.md?v=2'", files) == \
        f"curl -O replaces notes.md, {THERE}"
    assert call_destroys("bash", "wget -N https://example.com/a/notes.md", files) == \
        f"wget -N replaces notes.md, {THERE}"
    assert call_destroys("bash", "curl --output-dir site -O https://example.com/index.html",
                         files) == f"curl -O replaces site/index.html, {THERE}"
    for command in ("curl -O https://example.com/a/new.md", "curl --output-dir site -O "
                    "https://example.com/new.html", "wget -N -P site https://example.com/x.html"):
        assert call_destroys("bash", command, files) is None, command


def test_what_keeps_the_file_or_names_none_is_not_read_as_replacing_it(folder):
    """Not a replacement: the screen or a device; a resumed download, which
    appends; `--no-clobber`, `-nc`; a plain `wget`, which saves a second copy
    beside the first; `unzip` without `-o` (it asks, and with no one to answer
    keeps the file) or a listing; `tar` to its output, keeping old files, or
    adding to an archive; `ffmpeg` without `-y`; a `sort` to its output."""
    files = _files(folder)
    for command in ("curl -s -o /dev/null -w '%{http_code}' https://example.com/",
                    "curl -o - https://example.com/", "curl -C - -o notes.md https://example.com/n",
                    "curl --no-clobber -o notes.md https://example.com/n",
                    "wget -qO- https://example.com/", "wget -nc -O notes.md https://example.com/n",
                    "wget https://example.com/notes.md", "unzip a.zip", "unzip -n a.zip",
                    "unzip -l a.zip", "unzip -p a.zip notes.md", "tar -tzf a.tgz",
                    "tar -xzOf a.tgz notes.md", "tar -xkf a.tgz", "tar --skip-old-files -xf a.tar",
                    "tar -rf notes.md site", "ffmpeg -i talk.mp4 notes.md",
                    "ffmpeg -nostdin -n -i talk.mp4 notes.md", "sort list.txt",
                    "sort -t, -k2 list.txt | head"):
        assert call_destroys("bash", command, files) is None, command


def test_an_archive_writes_what_it_holds_into_a_folder(folder):
    """`unzip -o` and `tar -x`: a member the command names is looked for in
    the folder; what an archive holds, named nowhere, cannot be known in a
    folder that was there — and replaces nothing in one that was not."""
    files = _files(folder)
    for command, why, shown in (("unzip -o a.zip", "unzip -o", "the folder it runs in"),
                                ("unzip -qo a.zip -d site", "unzip -o", "site"),
                                ("tar -xzf a.tgz", "tar -x", "the folder it runs in"),
                                ("tar xzf a.tgz -C site", "tar -x", "site"),
                                ("tar --extract --file=a.tar --directory=site", "tar -x", "site")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether what {why} writes in {shown} was there before this run began", \
            command
    for command, why in (("unzip -o a.zip index.html -d site", "unzip -o"),
                         ("tar -xf a.tar -C site index.html", "tar -x")):
        assert call_destroys("bash", command, files) == f"{why} replaces site/index.html, {THERE}"
    for command in ("unzip -o a.zip -d fresh", "tar -xzf a.tgz -C fresh",
                    "mkdir -p fresh && tar -xzf a.tgz -C fresh",
                    "unzip -o a.zip site/new.html", "tar -xf a.tar site/new.html"):
        assert call_destroys("bash", command, files) is None, command


def test_sed_i_is_an_in_place_edit_and_stays_a_plain_write(folder):
    """`D-2026-10-29-03` §1: an in-place edit of a file that was there is a
    plain write, as `edit_file`'s is."""
    assert call_destroys("bash", "sed -i 's/keep/kept/' notes.md", _files(folder)) is None


# ── the real programs, through the gate ─────────────────────────────────────

def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def test_a_hires_never_refuses_sort_over_the_persons_file_and_runs_it_onto_a_new_one(folder, people):
    (folder / "list.txt").write_text("b\na\n", encoding="utf-8")
    refused = _bash(_never(folder), folder, "sort -o notes.md list.txt")
    assert refused.get("blocked") is True, refused
    assert f"(sort -o replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    ran = _bash(_never(folder), folder, "sort -o sorted.txt list.txt")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "sorted.txt").read_text(encoding="utf-8") == "a\nb\n"


def test_a_hires_never_extracts_into_a_new_folder_and_not_over_the_persons(folder, people):
    """Real `tar`: the archive holds `index.html`; into the person's `site`
    it would replace their page — refused, and the page stays — and into a
    new folder it runs."""
    src = folder.parent / "build"
    src.mkdir()
    (src / "index.html").write_text("<h1>theirs</h1>", encoding="utf-8")
    assert _bash(_never(folder), folder, f"tar -cf ../a.tar -C {src} index.html").get("exit_code") == 0
    refused = _bash(_never(folder), folder, "tar -xf ../a.tar -C site")
    assert refused.get("blocked") is True, refused
    assert f"(it cannot be known whether what tar -x writes in site was there before this run began)" \
        in refused["error"]
    assert (folder / "site" / "index.html").read_text(encoding="utf-8") == "<h1>mine</h1>"
    ran = _bash(_never(folder), folder, "mkdir -p fresh && tar -xf ../a.tar -C fresh")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "fresh" / "index.html").read_text(encoding="utf-8") == "<h1>theirs</h1>"


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
def test_a_hires_never_refuses_curl_writing_over_the_persons_file(folder, people):
    """Real `curl`, reading a file on this machine, which reaches no other."""
    (folder / "page.html").write_text("<p>fetched</p>", encoding="utf-8")
    url = (folder / "page.html").as_uri()
    refused = _bash(_never(folder), folder, f"curl -s -o notes.md {url}")
    assert refused.get("blocked") is True, refused
    assert f"(curl -o replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    ran = _bash(_never(folder), folder, f"curl -s -o copy.html {url}")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "copy.html").read_text(encoding="utf-8") == "<p>fetched</p>"
