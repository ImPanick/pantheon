# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1783`. A `write_file` call that lost its body emptied the person's file.

`write_file` opened its file for writing, which empties it, without looking at
what it was about to write. So a call whose content never arrived cut the file
to 0 bytes and answered *Wrote 0 bytes*, exit code 0, as if it had worked.
Measured before the fix, each one emptying a file that held data:

* the text form with a path and nothing after it, which is what the fenced
  channel (an Ollama endpoint, a local model off the allowlist) hands the tool
  when a page's own ```` ```html ```` fence ends the ```` ```write_file ````
  block early, and what a `<tool_code>` call whose body has no tag the parser
  knows comes out as;
* a JSON call with no `content`, or a misnamed one (`contents`);
* a JSON `content` of `null`, written as the four bytes `None`, and appended as
  them too; a native call's `null` raised a `TypeError` instead, which ended
  the turn.

Now a body the call did not declare empty is refused over a file that holds
data, measured on disk (a file that is not UTF-8 text holds bytes too), and the
refusal says the file is unchanged, asks for the text again, and only then
gives the exact call that empties a file on purpose: a JSON `content` of `""`.
That clear works from every channel, because a native call's empty `content`
now reaches the tool as JSON instead of as `path` and a newline, which looked
exactly like a lost body. An empty body still makes an empty file where
nothing was and leaves a 0-byte file as it is, without ever opening a file in
a mode that cuts it. The workstation gives the same answer from the same
builder.

Upstream Odysseus fixed this in 9056bac9 (#6414) and 3a125dcc; this ports both
as one change, onto Pantheon's shared reader (`_write_file_intent`), its native
conversion (`write_file_content`) and its workstation writer.

Driven (`Law 20`): the real parsers, the real dispatcher (`execute_tool_block`)
and the real `write_file`, here and in the real workstation daemon.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

import src.agent_loop as al
import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agent_tools.filesystem_tools import WriteFileTool
from src.tool_parsing import parse_tool_blocks
from src.tool_schemas import function_call_to_tool_block
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _home, _norm, _on, _without_where, people, settings, ws,
)

KEEP = "# Ana's notes\n\nKeep these: the plan for Friday, the list for Saturday.\n"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace, holding one file of the person's."""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "notes.md").write_text(KEEP, encoding="utf-8")
    return Path(os.path.realpath(d))


def _run(folder: Path, content: str, tool: str = "write_file") -> dict:
    """One call through the dispatcher, for an admin, in `folder`."""
    return _call(tool, content, "boss", workspace=str(folder))[1]


def _native(args: dict) -> str:
    """A native call's arguments as the loop turns them into a block."""
    block = function_call_to_tool_block("write_file", json.dumps(args))
    assert block is not None and block.tool_type == "write_file"
    return block.content


def _parsed(text: str) -> str:
    """The one `write_file` call the parser reads out of a model's reply."""
    blocks = parse_tool_blocks(text)
    assert [b.tool_type for b in blocks] == ["write_file"], blocks
    return blocks[0].content


def _kept(folder: Path, result: dict) -> None:
    assert result.get("exit_code") == 1, result
    assert (folder / "notes.md").read_text(encoding="utf-8") == KEEP
    assert f"holds {len(KEEP.encode())} bytes" in result["error"], result


# ── a call that lost its body ───────────────────────────────────────────────

LOST = {
    "path-alone": lambda: "notes.md",
    "path-and-a-newline": lambda: "notes.md\n",
    "blank-lines": lambda: "notes.md\n   \n\t\n",
    "json-without-content": lambda: json.dumps({"path": "notes.md"}),
    "json-null-content": lambda: json.dumps({"path": "notes.md", "content": None}),
    "native-without-content": lambda: _native({"path": "notes.md"}),
    "native-misnamed-content": lambda: _native({"path": "notes.md", "contents": "the text"}),
    "native-null-content": lambda: _native({"path": "notes.md", "content": None}),
}


@pytest.mark.parametrize("shape", sorted(LOST))
def test_a_call_that_carried_no_content_leaves_the_file_as_it_was(folder, people, shape):
    _kept(folder, _run(folder, LOST[shape]()))


def test_a_page_whose_own_fence_ended_the_call_leaves_the_file_as_it_was(folder, people):
    """The fenced channel: the page's ```` ```html ```` ends the
    ```` ```write_file ```` block, so the tool is handed the path alone."""
    reply = "Here is the page:\n```write_file\nnotes.md\n```html\n<p>clock</p>\n```\n```"
    content = _parsed(reply)
    assert content == "notes.md"
    _kept(folder, _run(folder, content))


@pytest.mark.parametrize("args", [
    "<path>notes.md</path><contents>the text</contents>",
    "<file_path>notes.md</file_path><text>the text</text>",
], ids=["path-and-contents", "file_path-and-text"])
def test_a_tool_code_call_whose_content_was_dropped_leaves_the_file_as_it_was(folder, people, args):
    content = _parsed(f"<tool_code>{{tool => 'write_file', args => '{args}'}}</tool_code>")
    _kept(folder, _run(folder, content))


def test_a_wrapper_that_carries_the_path_and_the_text_together_still_writes_the_text(
        folder, people):
    """`tool_parsing`'s wrapper readers hand a body that is not JSON to `path`
    whole (`<tool_call><write_file>`, the path, a line break, the text), and
    it is split at its first line, as it always was. The same wrapper with the
    path alone is a lost body."""
    content = _parsed("<tool_call><write_file>page.md\n# Plan\nFriday.</write_file></tool_call>")
    written = _run(folder, content)
    assert written.get("exit_code") == 0, written
    assert sorted(p.name for p in folder.iterdir()) == ["notes.md", "page.md"]
    assert (folder / "page.md").read_text(encoding="utf-8") == "# Plan\nFriday.\n"
    _kept(folder, _run(folder, _parsed("<tool_call><write_file>notes.md</write_file></tool_call>")))


def test_a_file_that_is_not_utf8_is_refused_on_the_bytes_it_holds(folder, people):
    """The read for the diff answers "" for a file it cannot decode, so the
    guard measures the file on disk."""
    raw = b"\xc3\xa9\xe8\xaf\xad\xff\xfe\x00 a latin-1 or binary file"
    (folder / "data.bin").write_bytes(raw)
    result = _run(folder, "data.bin\n")
    assert result.get("exit_code") == 1 and f"holds {len(raw)} bytes" in result["error"], result
    assert (folder / "data.bin").read_bytes() == raw


def test_an_append_whose_content_is_null_adds_nothing(folder, people):
    for content in (_native({"path": "notes.md", "content": None, "append": True}),
                    json.dumps({"path": "notes.md", "content": None, "append": True})):
        result = _run(folder, content)
        assert result.get("exit_code") == 0, result
        assert (folder / "notes.md").read_text(encoding="utf-8") == KEEP, "never the bytes None"


@pytest.mark.parametrize("make", [
    lambda: _native({"path": "settings.json", "content": {"theme": "dark", "size": 14}}),
    lambda: json.dumps({"path": "settings.json", "content": {"theme": "dark", "size": 14}}),
], ids=["native", "json-fence"])
def test_a_content_that_is_not_text_is_written_as_json(folder, people, make):
    """A model that sends a JSON file's content as an object gets the JSON, not
    a Python repr (`{'theme': 'dark'}`), and a native call does not crash."""
    result = _run(folder, make())
    assert result.get("exit_code") == 0, result
    assert json.loads((folder / "settings.json").read_text(encoding="utf-8")) == {
        "theme": "dark", "size": 14}


def test_the_refusal_names_what_was_kept_and_its_clear_works_as_sent(folder, people):
    """The likely case first (send the text again), the clear second, as JSON
    that is valid for a path with a quote in it, and that empties the file
    when sent back exactly as given."""
    name = 'draft "two".md'
    (folder / name).write_text(KEEP, encoding="utf-8")
    refused = _run(folder, f"{name}\n")
    error = refused.get("error", "")
    assert refused.get("exit_code") == 1 and "output" not in refused, refused
    assert "nothing was written and the file is unchanged" in error
    assert f"holds {len(KEEP.encode())} bytes" in error
    assert error.index("file's text") < error.index("If you mean to empty"), error
    clear = re.search(r"send exactly: (\{.*\})$", error, re.S)
    assert clear and json.loads(clear.group(1)) == {"path": name, "content": ""}, error
    assert (folder / name).read_text(encoding="utf-8") == KEEP
    cleared = _run(folder, clear.group(1))
    assert cleared.get("exit_code") == 0, cleared
    assert (folder / name).read_bytes() == b""


# ── a clear the call declares ───────────────────────────────────────────────

CHANNELS = {
    "json-fence": lambda args: _parsed(f"```write_file {json.dumps(args)}\n```"),
    "native": _native,
    "raw-call-in-text": lambda args: _parsed(json.dumps(
        {"type": "function", "function": {"name": "write_file", "arguments": json.dumps(args)}})),
}


@pytest.mark.parametrize("channel", sorted(CHANNELS))
def test_on_each_channel_a_declared_clear_empties_the_file_and_a_lost_body_does_not(
        folder, people, channel):
    make = CHANNELS[channel]
    _kept(folder, _run(folder, make({"path": "notes.md"})))
    blank = _run(folder, make({"path": "notes.md", "content": " \t "}))
    assert blank.get("exit_code") == 0, blank
    assert (folder / "notes.md").read_text(encoding="utf-8") == " \t ", "a blank text, as sent"
    cleared = _run(folder, make({"path": "notes.md", "content": ""}))
    assert cleared.get("exit_code") == 0, cleared
    assert (folder / "notes.md").read_bytes() == b""


def test_an_empty_file_is_still_made_where_nothing_was_and_only_bytes_are_refused(folder, people):
    """What stays as it was: an empty body makes an empty file where nothing
    was, a blank one is written as sent there, a 0-byte file stays as it is,
    a folder answers as it always has, a real body writes with its diff, and
    `edit_file` can still empty a file. Only bytes are refused."""
    made = _run(folder, "made.md\n")
    assert made.get("exit_code") == 0 and (folder / "made.md").read_bytes() == b"", made
    assert made["output"] == f"Wrote 0 bytes to {folder / 'made.md'}"
    blank = _run(folder, "blank.md\n  \n\t")
    assert blank.get("exit_code") == 0 and (folder / "blank.md").read_text() == "  \n\t", blank
    (folder / "empty.md").write_bytes(b"")
    again = _run(folder, "empty.md")
    assert again.get("exit_code") == 0 and (folder / "empty.md").read_bytes() == b"", again
    (folder / "sub").mkdir()
    into = _run(folder, "sub\n")
    assert into.get("exit_code") == 1 and "Is a directory" in into["error"], into
    (folder / "page.md").write_text(KEEP, encoding="utf-8")
    real = _run(folder, "page.md\n# Ana's notes\n\nOnly Friday now.\n")
    assert real.get("exit_code") == 0 and real["diff"]["removed"] == 1, real
    edited = _run(folder, json.dumps({"path": "page.md", "old_string": "# Ana's notes\n\nOnly Friday now.\n",
                                      "new_string": ""}), tool="edit_file")
    assert edited.get("exit_code") == 0 and (folder / "page.md").read_bytes() == b"", edited
    _kept(folder, _run(folder, "notes.md\n"))


# ── a writer that puts bytes there meanwhile ────────────────────────────────

def _bytes_after_the_size_check(target: str, monkeypatch) -> None:
    """The file is empty when its size is read, and holds bytes a moment later."""
    Path(target).write_bytes(b"")
    real = os.path.getsize

    def getsize(path):
        size = real(path)
        if path == target and size == 0:
            Path(target).write_text("written meanwhile", encoding="utf-8")
        return size
    monkeypatch.setattr(os.path, "getsize", getsize)


def _a_file_after_the_absence_check(target: str, monkeypatch) -> None:
    """Nothing is there when it is looked for, and a file is a moment later."""
    real = os.path.isfile

    def isfile(path):
        there = real(path)
        if path == target and not there:
            Path(target).write_text("written meanwhile", encoding="utf-8")
            return False
        return there
    monkeypatch.setattr(os.path, "isfile", isfile)


@pytest.mark.parametrize("race, exit_code", [
    (_bytes_after_the_size_check, 0),      # it was a 0-byte file when looked at
    (_a_file_after_the_absence_check, 1),  # the file that appeared holds bytes
], ids=["after-the-size-check", "after-the-absence-check"])
def test_an_empty_body_never_cuts_bytes_another_writer_put_there(tmp_path, race, exit_code,
                                                                 monkeypatch):
    """Upstream's two races (3a125dcc): no file is opened in a mode that cuts
    it, so bytes that land between the look and the write stay."""
    target = os.path.realpath(str(tmp_path / "log.md"))
    race(target, monkeypatch)
    result = asyncio.run(WriteFileTool().execute(f"{target}\n", {}))
    assert Path(target).read_text(encoding="utf-8") == "written meanwhile", result
    assert result.get("exit_code") == exit_code, result


# ── in the workstation ──────────────────────────────────────────────────────

_STEPS = [
    ("write_file", "proj/notes.md\n"),
    ("write_file", {"path": "proj/notes.md"}),
    ("write_file", {"path": "proj/notes.md", "content": None}),
    ("write_file", "proj/empty.md"),
    ("write_file", "proj/empty.md\n  \n"),
    ("write_file", "proj/new.md\n"),
    ("write_file", "proj\n"),
    ("write_file", {"path": "proj/clear.md", "content": ""}),
]


def test_in_the_workstation_an_empty_body_is_answered_as_it_is_here(ws, settings, people, tmp_path):
    """One refusal builder for both writers (`P20-03`): the same steps give the
    same answers, and the file in the workstation is kept."""
    host = Path(os.path.realpath(tmp_path / "host-side"))
    home = _home(ws, "ann")
    for root in (host, home):
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "notes.md").write_text(KEEP, encoding="utf-8")
        (root / "proj" / "clear.md").write_text(KEEP, encoding="utf-8")
        (root / "proj" / "empty.md").write_bytes(b"")
    here = [_call(tool, args, "boss", workspace=str(host))[1] for tool, args in _STEPS]
    _on(settings, ws)
    there = [_call(tool, args, "ann")[1] for tool, args in _STEPS]
    assert all(r["ran_in"] == "workstation" for r in there)
    for i, (a, b) in enumerate(zip(here, there)):
        assert _norm(_without_where(b), home) == _norm(a, host), (i, _STEPS[i])
    assert [r.get("exit_code") for r in there] == [1, 1, 1, 0, 0, 0, 1, 0], there
    for root in (host, home):
        assert (root / "proj" / "notes.md").read_text(encoding="utf-8") == KEEP
        assert (root / "proj" / "empty.md").read_text(encoding="utf-8") == "  \n"
        assert (root / "proj" / "new.md").read_bytes() == b""
        assert (root / "proj" / "clear.md").read_bytes() == b""


# ── the prompt ──────────────────────────────────────────────────────────────

def test_the_prompt_teaches_a_clear_that_works(folder, people):
    """The fenced prompt says an empty body over data is refused, and the clear
    it teaches, with a path in it, empties a file."""
    section = al._assemble_prompt({"write_file"})
    assert "An empty body over a file that holds data is refused" in section
    taught = re.search(r'to empty a file on purpose, give `(\{[^`]*\})`', section)
    assert taught, section
    call = taught.group(1).replace("<file path>", "notes.md")
    cleared = _run(folder, call)
    assert cleared.get("exit_code") == 0 and (folder / "notes.md").read_bytes() == b"", cleared
