# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1784`. A page the model wrapped in a code fence was saved with the fence.

Models often put a file's body inside a Markdown fence (```` ```html ```` …
```` ``` ````) even when the tool asks for the raw text. A native call, a
Hermes or `B1727` markup call, a raw tool call leaked into text, and the
inline-JSON fence form all carry `content` as a string, and `write_file`
wrote it exactly as it came. So `index.html` began with ```` ```html ```` and
ended with ```` ``` ````, a JSON file did not parse, and a script did not run.

Now the shared reader (`_write_file_intent`, which the tool, the workstation
and the gate all read through) leaves out an outer fence for the kinds of file
where one can never be content: HTML, CSS, JavaScript and TypeScript, JSON,
CSV, SQL, Python, shell, SVG, XML and YAML. Markdown, text, and anything else
keep a literal fence. The line break before the closing fence stays, so a
fenced row appended to a ledger still ends its line, and a fence with nothing
in it is an empty body, which `B1783` then decides. The call itself is not
rewritten, so the approval card still shows what the model sent.

On the plain text-fence channel the same mistake never reaches the reader:
the page's own fence ends the ```` ```write_file ```` block early, and the
tool gets the path alone, which is `B1783`'s case.

Upstream Odysseus fixed this in cdd28ed9. Its version dropped the final line
break and wrote an empty fence as the three bytes ```` ``` ````; this one keeps
the line break and reads an empty fence as an empty body.

Driven (`Law 20`): the real native conversion, the real dispatcher and the
real `write_file`, here and in the real workstation daemon.
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

PAGE = "```html\n<div>clock</div>\n```"
LEDGER = "date,amount\n2026-10-01,3.20\n"


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return Path(os.path.realpath(d))


def _run(folder: Path, content: str) -> dict:
    return _call("write_file", content, "boss", workspace=str(folder))[1]


def _native(args: dict) -> str:
    block = function_call_to_tool_block("write_file", json.dumps(args))
    assert block is not None and block.tool_type == "write_file"
    return block.content


def test_a_page_a_native_call_fenced_is_written_without_the_fence(folder, people):
    content = _native({"path": "index.html", "content": PAGE})
    assert content == "index.html\n" + PAGE, "the call is not rewritten: the card shows what was sent"
    result = _run(folder, content)
    assert result.get("exit_code") == 0, result
    assert (folder / "index.html").read_text(encoding="utf-8") == "<div>clock</div>\n"
    assert result["output"] == f"Wrote 17 bytes to {folder / 'index.html'}"


@pytest.mark.parametrize("name, sent, saved", [
    ("out.html", PAGE, "<div>clock</div>\n"),
    ("out.html", PAGE + "\n", "<div>clock</div>\n"),
    ("data.json", '  ```json\r\n{"a": 1}\r\n```', '{"a": 1}\r\n'),
    ("tool.py", "```python\ndef f():\n    '''\n    ```python\n    f()\n    ```\n    '''\n```",
     "def f():\n    '''\n    ```python\n    f()\n    ```\n    '''\n"),
    ("cut.html", "```html\n<div/>", "<div/>"),
    ("App.TSX", "```tsx\nexport const A = () => <b/>;\n```", "export const A = () => <b/>;\n"),
], ids=["html", "html-newline-after", "json-crlf", "python-with-its-own-fences",
        "cut-before-the-closing-fence", "tsx-upper-case"])
def test_each_kind_of_source_file_loses_its_fence_and_keeps_its_own_text(folder, people, name,
                                                                          sent, saved):
    """Upstream's case (the inline-JSON fence form), with the line break kept."""
    result = _run(folder, json.dumps({"path": name, "content": sent}))
    assert result.get("exit_code") == 0, result
    assert (folder / name).read_bytes() == saved.encode("utf-8")


def test_a_fenced_row_appended_to_a_ledger_still_ends_its_line(folder, people):
    """Receipt Collector appends its new rows (`B1672`): each must keep its
    line break, or the next sweep's row is glued onto this one."""
    (folder / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    for row in ("2026-11-01,4.50", "2026-11-02,1.00"):
        result = _run(folder, _native({"path": "ledger.csv", "content": f"```csv\n{row}\n```",
                                       "append": True}))
        assert result.get("exit_code") == 0, result
    assert (folder / "ledger.csv").read_text(encoding="utf-8") == (
        LEDGER + "2026-11-01,4.50\n2026-11-02,1.00\n")


def test_a_fence_with_nothing_in_it_is_an_empty_body(folder, people):
    """Never the three bytes ```: an empty body, so where nothing was it makes
    an empty file, and over a page that holds bytes it is refused."""
    made = _run(folder, _native({"path": "new.html", "content": "```html\n```"}))
    assert made.get("exit_code") == 0 and (folder / "new.html").read_bytes() == b"", made
    (folder / "index.html").write_text("<p>the page</p>\n", encoding="utf-8")
    refused = _run(folder, _native({"path": "index.html", "content": "```html\n```"}))
    assert refused.get("exit_code") == 1 and "no file content" in refused["error"], refused
    assert (folder / "index.html").read_text(encoding="utf-8") == "<p>the page</p>\n"


def test_a_fence_is_left_out_only_where_it_cannot_be_content(folder, people):
    """Markdown, text, R Markdown and a file with no suffix keep the fence they
    were sent, and so does a page whose ``` is inside its markup; the same
    fenced body to a page loses it."""
    literal = "```python\nprint('an example')\n```"
    for name in ("notes.md", "notes.txt", "report.rmd", "README"):
        result = _run(folder, json.dumps({"path": name, "content": literal}))
        assert result.get("exit_code") == 0, result
        assert (folder / name).read_text(encoding="utf-8") == literal, name
    markup = "<!doctype html>\n<pre>```</pre>\n"
    assert _run(folder, json.dumps({"path": "inside.html", "content": markup})).get("exit_code") == 0
    assert (folder / "inside.html").read_text(encoding="utf-8") == markup
    assert _run(folder, json.dumps({"path": "page.html", "content": literal})).get("exit_code") == 0
    assert (folder / "page.html").read_text(encoding="utf-8") == "print('an example')\n"


_STEPS = [
    {"path": "proj/index.html", "content": PAGE},
    {"path": "proj/ledger.csv", "content": "```csv\n2026-11-01,4.50\n```", "append": True},
    {"path": "proj/notes.md", "content": PAGE},
    {"path": "proj/kept.html", "content": "```html\n```"},
]


def test_in_the_workstation_a_fenced_page_is_written_as_it_is_here(ws, settings, people, tmp_path):
    host = Path(os.path.realpath(tmp_path / "host-side"))
    home = _home(ws, "ann")
    for root in (host, home):
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
        (root / "proj" / "kept.html").write_text("<p>kept</p>\n", encoding="utf-8")
    calls = [_native(args) for args in _STEPS]
    here = [_call("write_file", c, "boss", workspace=str(host))[1] for c in calls]
    _on(settings, ws)
    there = [_call("write_file", c, "ann")[1] for c in calls]
    assert all(r["ran_in"] == "workstation" for r in there)
    for i, (a, b) in enumerate(zip(here, there)):
        assert _norm(_without_where(b), home) == _norm(a, host), (i, _STEPS[i])
    assert [r.get("exit_code") for r in there] == [0, 0, 0, 1], there
    for root in (host, home):
        assert (root / "proj" / "index.html").read_text(encoding="utf-8") == "<div>clock</div>\n"
        assert (root / "proj" / "ledger.csv").read_text(encoding="utf-8") == LEDGER + "2026-11-01,4.50\n"
        assert (root / "proj" / "notes.md").read_text(encoding="utf-8") == PAGE
        assert (root / "proj" / "kept.html").read_text(encoding="utf-8") == "<p>kept</p>\n"
