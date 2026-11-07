# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1990`. A patch that failed part way left the files written before it changed.

`apply_patch` reads every file and matches every hunk before it writes
(`P20-03`), and `B1785` checks that every new text can be saved, so a patch
that does not fit changes nothing. The files were then written one by one,
and a write or delete that failed after another had landed (a file the account
can read but not write, a folder it cannot make, a full disk, a write the
workstation refuses) answered `apply_patch: …` with the earlier files already
changed and nothing put back. The model reads that the patch failed and sends
it again, and the hunk for the file that did change no longer matches:
*"a.py: hunk 1 context not found"*.

Now a failed write or delete puts back every file the patch reached, the
failing one too, the last first, with the same six file operations the patch
is written with, so the workstation does the same. Each file is read back to
check it. The answer says the patch was not applied and every file is as it
was, or names the files it could not put back.

Upstream Odysseus made `apply_patch` all or nothing in `84aa9a91` by writing
temporary files and renaming them over the originals, which calls this
machine's `os` directly; this is written against the six operations instead.
Its case is the first one here.

Driven (`Law 20`): `_run_patch` over the six operations on a dict, for the
failures a disk gives; the real dispatcher and the real file tools on this
machine, with a failure the disk itself gives; and the real workstation daemon.
"""
from __future__ import annotations

import os
from pathlib import Path

import src.agent_tools.filesystem_tools as fs
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _home, _on, people, settings, ws,
)

UNDONE = "the patch was not applied and every file is as it was"


def _patch(*lines: str) -> str:
    return "\n".join(("*** Begin Patch", *lines, "*** End Patch"))


TWO_UPDATES = _patch("*** Update File: a.py", "@@", "-x = 1", "+x = 2",
                     "*** Update File: b.cfg", "@@", "-debug = no", "+debug = yes")


class _Files:
    """`_HostFiles`' six operations over a dict, failing where a disk fails:
    `refuse` refuses a write or a delete, as a read-only file does, and `cut`
    leaves a write's file cut short and then fails, as a full disk does."""

    def __init__(self, files, *, refuse=(), cut=()):
        self.files = dict(files)
        self.refuse = set(refuse)
        self.cut = set(cut)

    def resolve(self, raw):
        return raw

    def exists(self, path):
        return path in self.files

    isfile = exists

    def read_text(self, path):
        if path not in self.files:
            raise FileNotFoundError(2, "No such file or directory", path)
        return self.files[path]

    def write_text(self, path, text):
        if path in self.refuse:
            raise PermissionError(13, "Permission denied", path)
        if path in self.cut:
            self.files[path] = text[:4]
            raise OSError(28, "No space left on device", path)
        self.files[path] = text

    def remove(self, path):
        if path in self.refuse:
            raise PermissionError(13, "Permission denied", path)
        del self.files[path]


def test_a_second_write_that_is_refused_puts_the_first_file_back():
    files = _Files({"a.py": "x = 1\n", "b.cfg": "debug = no\n"}, refuse={"b.cfg"})
    result = fs._run_patch(TWO_UPDATES, files)
    assert result["exit_code"] == 1
    assert "Permission denied" in result["error"] and result["error"].endswith(UNDONE), result
    assert files.files == {"a.py": "x = 1\n", "b.cfg": "debug = no\n"}


def test_a_file_the_patch_added_is_taken_away_again():
    files = _Files({"b.cfg": "debug = no\n"}, refuse={"b.cfg"})
    result = fs._run_patch(_patch(
        "*** Add File: docs/notes.md", "+# Notes",
        "*** Update File: b.cfg", "@@", "-debug = no", "+debug = yes"), files)
    assert result["exit_code"] == 1 and result["error"].endswith(UNDONE), result
    assert files.files == {"b.cfg": "debug = no\n"}


def test_a_file_the_patch_deleted_is_written_back():
    files = _Files({"old.py": "gone = False\n", "b.cfg": "debug = no\n"}, refuse={"b.cfg"})
    result = fs._run_patch(_patch(
        "*** Delete File: old.py",
        "*** Update File: b.cfg", "@@", "-debug = no", "+debug = yes"), files)
    assert result["exit_code"] == 1 and result["error"].endswith(UNDONE), result
    assert files.files == {"old.py": "gone = False\n", "b.cfg": "debug = no\n"}


def test_a_file_that_cannot_be_put_back_is_named():
    """A full disk: the write emptied `b.cfg` and failed, and writing it back
    fails the same way. `a.py` is put back, and the answer names `b.cfg`
    instead of saying every file is as it was."""
    files = _Files({"a.py": "x = 1\n", "b.cfg": "debug = no\n"}, cut={"b.cfg"})
    result = fs._run_patch(TWO_UPDATES, files)
    assert result["exit_code"] == 1
    assert "No space left on device" in result["error"], result
    assert result["error"].endswith("could not be put back as they were and may be "
                                    "changed: b.cfg"), result
    assert files.files["a.py"] == "x = 1\n"


def test_on_this_machine_a_folder_that_cannot_be_made_leaves_every_file_as_it_was(
        tmp_path, people):
    """The patch's second file goes in a folder that is a file: the disk itself
    refuses, after `a.py` was written. Asked again once the folder is there,
    the same patch applies, which is what the model does next."""
    folder = Path(os.path.realpath(tmp_path)) / "proj"
    folder.mkdir()
    (folder / "a.py").write_text("x = 1\n", encoding="utf-8")
    (folder / "notes").write_text("a file, not a folder\n", encoding="utf-8")
    patch = {"patch_text": _patch("*** Update File: a.py", "@@", "-x = 1", "+x = 2",
                                  "*** Add File: notes/todo.md", "+- [ ] ship it")}

    result = _call("apply_patch", patch, "boss", workspace=str(folder))[1]
    assert result["exit_code"] == 1 and result["error"].endswith(UNDONE), result
    assert (folder / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert sorted(p.name for p in folder.iterdir()) == ["a.py", "notes"]

    (folder / "notes").unlink()
    (folder / "notes").mkdir()
    again = _call("apply_patch", patch, "boss", workspace=str(folder))[1]
    assert again["exit_code"] == 0, again
    assert (folder / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    assert (folder / "notes" / "todo.md").read_text(encoding="utf-8") == "- [ ] ship it\n"


def test_in_the_workstation_a_refused_write_leaves_every_file_as_it_was(
        ws, settings, people, monkeypatch):
    """The same six operations, against the real daemon: only the refusal of
    `b.cfg`'s write is made up; `a.py` is written and put back there."""
    from src.agent_tools import workstation_tools as wt
    from src.workstation_client import WorkstationError

    home = _home(ws, "ann")
    (home / "proj").mkdir(parents=True)
    (home / "proj" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (home / "proj" / "b.cfg").write_text("debug = no\n", encoding="utf-8")
    real_write = wt._WorkstationFiles.write_text

    def refuse_b(self, path, text):
        if path.endswith("/b.cfg"):
            raise wt._WorkstationIOError(WorkstationError(
                "forbidden", "The workstation account may not do that (b.cfg)."))
        return real_write(self, path, text)

    monkeypatch.setattr(wt._WorkstationFiles, "write_text", refuse_b)
    _on(settings, ws)
    result = _call("apply_patch", {"patch_text": TWO_UPDATES.replace(
        "File: a.py", "File: proj/a.py").replace("File: b.cfg", "File: proj/b.cfg")}, "ann")[1]
    assert result["ran_in"] == "workstation", result
    assert result["exit_code"] == 1 and result["error"].endswith(UNDONE), result
    assert (home / "proj" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (home / "proj" / "b.cfg").read_text(encoding="utf-8") == "debug = no\n"
