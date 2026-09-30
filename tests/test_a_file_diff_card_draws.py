# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B938`. A file edit's diff card draws — live, after a reload, in a compare pane.

`buildDiffHtml` is `P4-01`'s one diff renderer, called by all three. Its module
binds no `esc` at the top, and the function wrote every row and the file name
through a bare `esc(...)`, so it raised `ReferenceError: esc is not defined` on
every diff: the card was not drawn, and on a reload nothing after it in the
reply was either. Here the shipped function is cut out of `chatRenderer.js` and
run with only what its module really provides — `uiModule`, carrying the
shipped escaper — and no global `esc` to hide the defect behind (`Law 20`).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _diff_html(diff: dict) -> str:
    src = CHAT_RENDERER.read_text(encoding="utf-8")
    body = js_definition(src, src.index("export function buildDiffHtml("))
    script = (
        "(function(){\n" + esc_source("_shippedEsc")
        + "const uiModule = { esc: _shippedEsc };\n"
        + body.replace("export function", "function", 1) + "\n"
        + "process.stdout.write(JSON.stringify(buildDiffHtml(%s)));\n})();\n" % json.dumps(diff)
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_a_diff_draws_with_its_rows_and_its_file_name():
    html = _diff_html({"text": "@@ -1 +1 @@\n-old line\n+new line\n same", "file": "notes.md",
                       "added": 1, "removed": 1})
    assert '<span class="diff-file">notes.md</span>' in html
    assert '<span class="diff-del">old line</span>' in html
    assert '<span class="diff-add">new line</span>' in html
    assert '<span class="diff-hunk">@@ -1 +1 @@</span>' in html
    assert '<span class="diff-stat-add">+1</span>' in html


def test_what_the_file_says_is_drawn_as_text():
    """The rows are a file's contents and its name is the model's — both text."""
    html = _diff_html({"text": '+<img src=x onerror="alert(1)">', "file": 'a"<b>.txt'})
    assert "<img" not in html and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "a&quot;&lt;b&gt;.txt" in html


def test_nothing_to_show_is_nothing():
    assert _diff_html({}) == "" and _diff_html({"file": "a.txt"}) == ""
