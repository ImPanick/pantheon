# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1683` — a compressor that takes away the file it packs or unpacks is
read as taking it away, so a hire's `destructive: never` and Auto's one
exception cover it when the file was there before the run began.

Measured before the fix, with `notes.md` there: `gzip notes.md` — which
leaves `notes.md.gz` and no `notes.md` — gave `call_destroys('bash', 'gzip
notes.md')` `None`, `execute_code` alone, and so did `bzip2`, `xz`, `zstd
--rm`, `gunzip notes.md.gz` (which takes the `.gz` away), `zip -m` and `tar
--remove-files`; a shell `mv` over the same file was destructive (`B1622`).

Built under `D-2026-10-29-02` §1's principle and the deletion rows (`B1622`,
`B1668`): packing or unpacking a file that was there takes it away from
where it was, so it is `destructive`; `-k`/`--keep`, `-c`/`--stdout`, `-t`
and `-l` are not, and neither is `zstd`, `lz4` or `brotli` without the
option that removes. A file the run made itself is its own (`D-2026-10-29-02`
§1, *"Only pre-existing files"*), as for `write_file` and a `>`. And the
output a compressor writes over when forced (`-f`): `gzip -f` onto a `.gz`
that was there, `gunzip -f` onto the file it unpacks to (`B1682`).

The content is recoverable — `gunzip` gives it back — so this is the
cautious reading, and the owner may rule that a reversible compression is
not a deletion; then only these `removes` findings go
(`src/shell_reading.py` says so where they are made).

Measured on the shipped evals: none of the 459 `bash` and `python` calls
packs or unpacks a file (`unzip -l`/`-p`/`-Z1` read an archive), so no
agent's case changed.

Driven (`Law 20`): the real reader and the run's record over a real folder,
and the real gate and dispatcher running the real `gzip`, `zip` and `tar`
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
from src.tool_capabilities import ToolRunSecurityContext, _is_destructive_call, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"
NOTES = "Ana's notes — keep these"
PACKED = ("gz", "bz2", "xz", "zst", "Z", "lz", "br", "lz4")


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's notes, each packed, and a folder."""
    ws = tmp_path / "proj"
    (ws / "site").mkdir(parents=True)
    (ws / "notes.md").write_text(NOTES, encoding="utf-8")
    for ext in PACKED:
        (ws / f"notes.md.{ext}").write_bytes(b"packed")
    (ws / "site" / "index.html").write_text("<h1>mine</h1>", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


#: What packs or unpacks `{}` (`notes`), the file it takes away, and the
#: words that say so.
AWAY = (
    ("gzip {}.md", "{}.md", "gzip"),
    ("gzip -9 -- {}.md", "{}.md", "gzip"),
    ("pigz {}.md", "{}.md", "pigz"),
    ("bzip2 {}.md", "{}.md", "bzip2"),
    ("bzip2 -z {}.md", "{}.md", "bzip2"),
    ("pbzip2 -p4 {}.md", "{}.md", "pbzip2"),
    ("xz -T0 {}.md", "{}.md", "xz"),
    ("lzma {}.md", "{}.md", "lzma"),
    ("lzip {}.md", "{}.md", "lzip"),
    ("compress {}.md", "{}.md", "compress"),
    ("zstd --rm {}.md", "{}.md", "zstd --rm"),
    ("zstd -k --rm {}.md", "{}.md", "zstd --rm"),
    ("lz4 --rm {}.md", "{}.md", "lz4 --rm"),
    ("brotli -j {}.md", "{}.md", "brotli -j"),
    ("gunzip {}.md.gz", "{}.md.gz", "gunzip"),
    ("gzip -d {}.md.gz", "{}.md.gz", "gzip -d"),
    ("unpigz {}.md.gz", "{}.md.gz", "unpigz"),
    ("bunzip2 {}.md.bz2", "{}.md.bz2", "bunzip2"),
    ("unxz {}.md.xz", "{}.md.xz", "unxz"),
    ("xz -d {}.md.xz", "{}.md.xz", "xz -d"),
    ("zstd -d --rm {}.md.zst", "{}.md.zst", "zstd -d --rm"),
    ("unzstd --rm {}.md.zst", "{}.md.zst", "unzstd --rm"),
    ("uncompress {}.md.Z", "{}.md.Z", "uncompress"),
    ("lzip -d {}.md.lz", "{}.md.lz", "lzip -d"),
    ("zip -m a.zip {}.md", "{}.md", "zip -m"),
    ("zip -9m a.zip {}.md", "{}.md", "zip -m"),
    ("tar -czf a.tgz --remove-files {}.md", "{}.md", "tar --remove-files"),
    ("tar czf a.tgz {}.md --remove-files", "{}.md", "tar --remove-files"),
    ("7z a -sdel a.7z {}.md", "{}.md", "7z a -sdel"),
)


@pytest.mark.parametrize("command,gone,why", AWAY)
def test_packing_or_unpacking_a_file_that_was_there_takes_it_away(folder, command, gone, why):
    """The row's `Verify:`: the file that was there carries `destructive`,
    named with what takes it away."""
    assert call_destroys("bash", command.format("notes"), _files(folder)) == \
        f"{why} removes {gone.format('notes')}, {THERE}"


@pytest.mark.parametrize("command,gone,why", AWAY)
def test_a_file_that_is_not_there_is_not_taken_away(folder, command, gone, why):
    assert call_destroys("bash", command.format("fresh"), _files(folder)) is None


def test_what_keeps_its_input_is_not_read_as_taking_it_away(folder):
    """Told to keep it, to write to the screen, or only to test or list;
    `zstd`, `lz4` and `brotli` keep it unless told otherwise (and the last
    of `--rm` and `-k` said wins); `lzip -o` keeps it; a folder without `-r`
    is passed over; an archiver that does not move what it adds."""
    files = _files(folder)
    for command in ("gzip -k notes.md", "gzip --keep notes.md", "gzip -c notes.md > /dev/null",
                    "gzip -t notes.md.gz", "gzip -l notes.md.gz", "gunzip -c notes.md.gz",
                    "gzip -dc notes.md.gz", "zcat notes.md.gz", "bzip2 -k notes.md",
                    "bzip2 -dc notes.md.bz2", "bzcat notes.md.bz2", "xz -k notes.md",
                    "xz -l notes.md.xz", "xzcat notes.md.xz", "zstd notes.md",
                    "zstd --rm -k notes.md", "zstd --rm -c notes.md", "zstd -d notes.md.zst",
                    "lz4 notes.md", "brotli notes.md", "lzip -k notes.md", "lzip -o out.lz notes.md",
                    "gzip site", "unxz notes.md", "zip a.zip notes.md", "zip -r a.zip site",
                    "tar -czf a.tgz notes.md", "7z a a.7z notes.md"):
        assert call_destroys("bash", command, files) is None, command


def test_what_it_takes_away_unnamed_cannot_be_known(folder):
    """`-r` takes away what is in a folder, and a glob or a list of names is
    filled in when it runs: into a folder that was there, or names the
    command does not hold, unknowable — destructive."""
    files = _files(folder)
    for command, said in (
            ("gzip -r site", "what gzip removes in site was there"),
            ("zip -rm a.zip site", "what zip -m removes in site was there"),
            ("tar -czf a.tgz -C site . --remove-files", "what tar --remove-files removes in site was there"),
            ("xz --files=list.txt", "what xz removes in the folder it runs in was there"),
            ("gzip *.md", "*.md was there"),
            ("gunzip notes", "notes.gz was there")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether {said} before this run began", command
    assert call_destroys("bash", "gzip -r fresh", files) is None


def test_forced_it_writes_over_its_output_and_says_what_a_person_meets_first(folder):
    """`-f` writes over the packed or unpacked name. Packing, the file taken
    away is said first; unpacking, the one written over."""
    files = _files(folder)
    assert call_destroys("bash", "gzip -kf notes.md", files) == f"gzip -f replaces notes.md.gz, {THERE}"
    assert call_destroys("bash", "gzip -f notes.md", files) == f"gzip removes notes.md, {THERE}"
    assert call_destroys("bash", "gunzip -f notes.md.gz", files) == f"gunzip -f replaces notes.md, {THERE}"
    assert call_destroys("bash", "bunzip2 -kf notes.md.bz2", files) == \
        f"bunzip2 -f replaces notes.md, {THERE}"
    assert call_destroys("bash", "zstd -f fresh.md -o notes.md.zst", files) == \
        f"zstd -f replaces notes.md.zst, {THERE}"
    assert call_destroys("bash", "gzip -k notes.md", files) is None, "unforced, it keeps the .gz"


def test_the_runs_own_file_is_its_own(folder):
    """A file the run's own `>` made, which was not there before the run
    began, is packed away as a plain write — the run iterating on its own
    draft is not asked."""
    files = _files(folder)
    assert call_destroys("bash", "echo draft > draft.md", files) is None   # the run looks first
    (folder / "draft.md").write_text("draft\n", encoding="utf-8")         # …and its `>` made it
    assert call_destroys("bash", "gzip draft.md", files) is None
    assert call_destroys("bash", "gzip notes.md", files) == f"gzip removes notes.md, {THERE}"


def test_auto_asks_before_packing_away_the_persons_file(folder):
    """Auto's one exception (`B1341`) asks of the same call."""
    assert _is_destructive_call("bash", "gzip notes.md", _files(folder)) is True
    assert _is_destructive_call("bash", "gzip -k notes.md", _files(folder)) is False


# ── the real programs, through the gate ─────────────────────────────────────

def _never(folder: Path, files: RunFiles | None = None) -> ToolRunSecurityContext:
    """A hire's never, for one call; `files` is the run's record, which its
    calls share (each call's own context, as the loop makes one per step)."""
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}),
                                  files=files or _files(folder))


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


@pytest.mark.skipif(shutil.which("gzip") is None, reason="gzip is not installed")
def test_a_hires_never_refuses_gzip_on_the_persons_file_and_runs_it_on_its_own(folder, people):
    files = _files(folder)
    refused = _bash(_never(folder, files), folder, "gzip notes.md")
    assert refused.get("blocked") is True, refused
    assert f"(gzip removes notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    made = _bash(_never(folder, files), folder, "echo draft > draft.md")
    assert made.get("exit_code") == 0, made
    packed = _bash(_never(folder, files), folder, "gzip draft.md")
    assert packed.get("exit_code") == 0, packed
    assert (folder / "draft.md.gz").is_file() and not (folder / "draft.md").exists()
    kept = _bash(_never(folder, files), folder, "gzip -k notes.md")
    assert not kept.get("blocked"), "-k keeps it, and unforced gzip keeps the .gz there too"
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    forced = _bash(_never(folder, files), folder, "gzip -kf notes.md")
    assert forced.get("blocked") is True, forced
    assert f"(gzip -f replaces notes.md.gz, {THERE})" in forced["error"]
    assert (folder / "notes.md.gz").read_bytes() == b"packed"


@pytest.mark.skipif(shutil.which("zip") is None or shutil.which("tar") is None,
                    reason="zip or tar is not installed")
def test_a_hires_never_refuses_zip_m_and_tar_remove_files_on_the_persons_file(folder, people):
    for command, why in (("zip -m a.zip notes.md", "zip -m"),
                         ("tar -czf a.tgz --remove-files notes.md", "tar --remove-files")):
        refused = _bash(_never(folder), folder, command)
        assert refused.get("blocked") is True, refused
        assert f"({why} removes notes.md, {THERE})" in refused["error"]
        assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    ran = _bash(_never(folder), folder, "zip -q a.zip notes.md")
    assert ran.get("exit_code") == 0, ran
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
