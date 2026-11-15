# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2135`. What a tool result is sent to the model as: the same facts, without
the bytes no model reads.

The owner, 2026-11-15: *"per-round trimming is also critical as well, we can
take a users dense input - and trim what the model wouldn't need to do the same
job at the same quality"*. Each function here is pure, so a result shaped once
reads the same in every round after it and the request keeps its prefix (a
local server's cache, a cloud provider's cached input).

Only what carries nothing a model can use is taken out:

* a terminal's colour and cursor codes (`\\x1b[...m`), and the progress line a
  carriage return overwrote, which a terminal never showed either;
* the same line printed five or more times in a row, said once with its count;
* a run of base64 too long for a model to read or copy back, named by length;
* the indentation of Pantheon's own structured payload, sent compact.

A file's own text (`read_file`'s `content`) is never touched: a model edits a
file by quoting it exactly.
"""
from __future__ import annotations

import json
import re
from typing import Any

#: A run of base64 at least this long is named rather than sent.
BASE64_RUN_CHARS = 2000
#: The same line this many times in a row or more is said once, with its count.
REPEATED_LINE_RUN = 5

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[\]P^_][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# A carriage return the terminal drew over: everything on the line up to it.
# A `\r\n` line ending is left as it is.
_OVERWRITTEN = re.compile(r"[^\n]*\r(?!\n)")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % BASE64_RUN_CHARS)


def _base64_note(match: "re.Match[str]") -> str:
    return f"[base64 data, {len(match.group(0)):,} characters, not shown]"


def _collapse_repeats(text: str) -> str:
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        run = j - i + 1
        if run >= REPEATED_LINE_RUN and lines[i].strip():
            out.append(lines[i])
            out.append(f"[the line above, {run - 1} more times]")
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return "\n".join(out)


def shape_terminal_output(text: Any) -> Any:
    """A shell's or a script's output as a model reads it. Not a string: as is."""
    if not isinstance(text, str) or not text:
        return text
    shaped = _ANSI.sub("", text)
    shaped = _OVERWRITTEN.sub("", shaped)
    shaped = _BASE64_RUN.sub(_base64_note, shaped)
    return _collapse_repeats(shaped)


def compact_json(value: Any) -> str:
    """Pantheon's own payload as JSON with no indentation: the same keys and
    values in about a third fewer tokens than `indent=2`."""
    text = json.dumps(value, separators=(",", ":"), default=str, ensure_ascii=False)
    return _BASE64_RUN.sub(_base64_note, text)
