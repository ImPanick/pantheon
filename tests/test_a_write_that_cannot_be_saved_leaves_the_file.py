# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1785`. An edit whose new text could not be saved left the file at 0 bytes.

`edit_file`, `write_file` and `apply_patch` opened the file for writing, which
empties it, and only then encoded the new text as UTF-8. A text that cannot be
encoded failed at that point, after the file was already empty. Python's JSON
reader turns the escape `\\ud800` into a lone surrogate, which UTF-8 cannot
hold, and a model writes one whenever it under-escapes a backslash in code
that spells surrogates: a JavaScript regex such as `/[\\uD800-\\uDBFF]/` sent
as `"new_string": "/[\\uD800-\\uDBFF]/"`. Measured before the fix:

* an `edit_file` meant to change one line left the person's whole file at
  0 bytes, and answered with the codec's own error, which never said so;
* `write_file`, native or as inline JSON, did the same, and on a new path left
  a 0-byte file behind;
* `apply_patch`, which promises to reject a whole patch before any file is
  changed, wrote the files before the bad one and emptied that one, and an
  Add File left a 0-byte file.

Now each of them asks whether the new text can be saved before it opens a
file, and refuses with one sentence that says nothing was written and the file
is unchanged, and how to send the characters if they were meant. A patch is
checked whole before its first write, so it stays all or nothing. The
workstation gives the same answers from the same code (`P20-03`): its client
already failed before sending, but with a different sentence, and a patch
there kept the files written before the bad one.

This is Pantheon's own defect; upstream Odysseus has no fix for it to port.

Driven (`Law 20`): the real dispatcher and the real file tools, here and in
the real workstation daemon.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.tool_schemas import function_call_to_tool_block
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _home, _norm, _on, _without_where, people, settings, ws,
)

APP = "// Ana's app\nconst re = null;\nexport function count(s) { return s.length; }\n"

# The model's own JSON, with the regex's backslashes under-escaped.
EDIT = (r'{"path": "app.js", "old_string": "const re = null;", '
        r'"new_string": "const re = /[\uD800-\uDBFF][\uDC00-\uDFFF]/g;"}')
WRITE = r'{"path": "app.js", "content": "const re = /[\uD800-\uDBFF]/g;\n"}'


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "app.js").write_text(APP, encoding="utf-8")
    return Path(os.path.realpath(d))


def _run(folder: Path, tool: str, content: str) -> dict:
    return _call(tool, content, "boss", workspace=str(folder))[1]


def _refused(result: dict, tool: str, kept: str = "the file is unchanged") -> None:
    assert result.get("exit_code") == 1, result
    error = result.get("error", "")
    assert error.startswith(f"{tool}: ") and "cannot be saved as UTF-8" in error, error
    assert f"so nothing was written and {kept}" in error, error
    assert "\\ud800" in error and "escape the backslash: \\\\ud800" in error, error


def _patch(*lines: str) -> str:
    """A patch as a model's JSON carries it, with `SURROGATE` spelled as the
    escape the model wrote."""
    text = "\n".join(("*** Begin Patch", *lines, "*** End Patch"))
    return json.dumps({"patch_text": text}).replace("SURROGATE", "\\ud800")


def test_an_edit_whose_new_text_cannot_be_saved_leaves_the_file_as_it_was(folder, people):
    result = _run(folder, "edit_file", EDIT)
    assert (folder / "app.js").read_bytes() == APP.encode("utf-8"), result
    _refused(result, "edit_file")


@pytest.mark.parametrize("make", [
    lambda: function_call_to_tool_block("write_file", WRITE).content,
    lambda: WRITE,
], ids=["native", "json-fence"])
def test_a_write_whose_text_cannot_be_saved_leaves_the_file_as_it_was(folder, people, make):
    result = _run(folder, "write_file", make())
    assert (folder / "app.js").read_bytes() == APP.encode("utf-8"), result
    _refused(result, "write_file")


def test_a_patch_whose_new_text_cannot_be_saved_changes_no_file(folder, people):
    """The file before the bad one is not written, the bad one is not emptied,
    and the one after it is not made."""
    (folder / "a.py").write_text("x = 1\n", encoding="utf-8")
    (folder / "b.py").write_text("y = 1\n", encoding="utf-8")
    result = _run(folder, "apply_patch", _patch(
        "*** Update File: a.py", "@@", "-x = 1", "+x = 2",
        "*** Update File: b.py", "@@", "-y = 1", "+y = 'SURROGATE'",
        "*** Add File: c.py", "+z = 3"))
    assert (folder / "a.py").read_text(encoding="utf-8") == "x = 1\n", result
    assert (folder / "b.py").read_text(encoding="utf-8") == "y = 1\n", result
    assert not (folder / "c.py").exists()
    _refused(result, "apply_patch", "every file is unchanged")
    assert "the new text of b.py" in result["error"]


def test_a_new_file_whose_text_cannot_be_saved_is_never_made(folder, people):
    patched = _run(folder, "apply_patch", _patch("*** Add File: new.py", "+s = 'SURROGATE'"))
    written = _run(folder, "write_file", r'{"path": "new.js", "content": "s = \"\ud800\";\n"}')
    assert sorted(p.name for p in folder.iterdir()) == ["app.js"], "no 0-byte file left behind"
    _refused(patched, "apply_patch", "every file is unchanged")
    _refused(written, "write_file")


def test_a_valid_pair_is_saved_and_an_append_that_cannot_be_is_refused_by_name(folder, people):
    """A surrogate pair is one character, and is written; an append never
    emptied the file, and now it gives the same sentence as the rest."""
    smile = _run(folder, "write_file", r'{"path": "smile.txt", "content": "\ud83d\ude00\n"}')
    assert smile.get("exit_code") == 0, smile
    assert (folder / "smile.txt").read_text(encoding="utf-8") == "\U0001F600\n"
    edited = _run(folder, "edit_file", r'{"path": "app.js", "old_string": "// Ana", '
                                       r'"new_string": "// \ud83d\ude00 Ana"}')
    assert edited.get("exit_code") == 0, edited
    assert (folder / "app.js").read_text(encoding="utf-8") == "// \U0001F600 " + APP[3:]
    before = (folder / "app.js").read_bytes()
    _refused(_run(folder, "write_file", r'{"path": "app.js", "content": "// \ud800\n", '
                                        r'"append": true}'), "write_file")
    assert (folder / "app.js").read_bytes() == before


def test_in_the_workstation_a_text_that_cannot_be_saved_is_answered_as_it_is_here(
        ws, settings, people, tmp_path):
    """One check, written once (`P20-03`): the same calls give the same
    sentence, and neither place changes a file."""
    host = Path(os.path.realpath(tmp_path / "host-side"))
    home = _home(ws, "ann")
    for root in (host, home):
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "app.js").write_text(APP, encoding="utf-8")
        (root / "proj" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / "proj" / "b.py").write_text("y = 1\n", encoding="utf-8")
    steps = [
        ("edit_file", EDIT.replace('"app.js"', '"proj/app.js"')),
        ("write_file", function_call_to_tool_block(
            "write_file", WRITE.replace('"app.js"', '"proj/app.js"')).content),
        ("write_file", r'{"path": "proj/app.js", "content": "// \ud800\n", "append": true}'),
        ("apply_patch", _patch("*** Update File: proj/a.py", "@@", "-x = 1", "+x = 2",
                               "*** Update File: proj/b.py", "@@", "-y = 1", "+y = 'SURROGATE'")),
    ]
    here = [_call(tool, c, "boss", workspace=str(host))[1] for tool, c in steps]
    _on(settings, ws)
    there = [_call(tool, c, "ann")[1] for tool, c in steps]
    assert all(r["ran_in"] == "workstation" for r in there)
    for root in (host, home):
        assert (root / "proj" / "app.js").read_bytes() == APP.encode("utf-8"), root
        assert (root / "proj" / "a.py").read_text(encoding="utf-8") == "x = 1\n", root
        assert (root / "proj" / "b.py").read_text(encoding="utf-8") == "y = 1\n", root
    for i, (a, b) in enumerate(zip(here, there)):
        assert _norm(_without_where(b), home) == _norm(a, host), (i, steps[i][0])
    for (tool, _c), result in zip(steps, there):
        _refused(result, tool, "every file is unchanged" if tool == "apply_patch"
                 else "the file is unchanged")
