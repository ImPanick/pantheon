# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1531` — Escape closes the OCR editor before the window behind it.

The twin of `B1294`. `chatRenderer.js`' `_openVisionEditor` (the *Aa* button on
a chat photo: the vision model's text, to correct and save) answered Escape
with its own bubble-phase `document` listener, `_visionEditorEsc`. C-NAV has
one arbiter: the capture-phase handler in `ui.js` asks the Escape stack first
(`dismissTopMenu`), then closes the top window and stops the key. The editor
was not on the stack — so with a window open behind it, the first Escape
closed the window and left the editor over the place it had been.

Now the editor registers on the stack (`registerMenuDismiss`) and its own
listener is gone.

Driven (`Law 20`): the real `_openVisionEditor` and `_closeVisionEditor`, cut
out of `chatRenderer.js`, over the real `escMenuStack.js` in the shared DOM
shim. The arbiter's first question closes the editor and only the editor; the
next is answered "nothing here", which is when the arbiter goes on to the
window (its own order is pinned by `tests/test_escape_peels_the_innermost_
layer_js.py`). No `keydown` listener is put on `document`; Close, reopening,
and a sweep (`dismissOrRemove`) each leave the stack empty.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _DOM

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
RENDERER = (JS / "chatRenderer.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(signature: str) -> str:
    return js_definition(RENDERER, blank_text(RENDERER, "js").index(signature))


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("visioneditor")
    (d / "dom.js").write_text(_DOM)
    shutil.copy(JS / "escMenuStack.js", d / "escMenuStack.js")
    return d


def _run(box, script: str) -> dict:
    case = box / "case.mjs"
    case.write_text(
        "import { installDom } from './dom.js';\n"
        "import { bindMenuDismiss, registerMenuDismiss, dismissTopMenu, dismissOrRemove, _openMenuCount }"
        " from './escMenuStack.js';\n"
        "const document = installDom();\n"
        "const keydowns = [];\n"
        "const _add = document.addEventListener.bind(document);\n"
        "document.addEventListener = (t, fn, o) => { if (t === 'keydown') keydowns.push(fn); return _add(t, fn, o); };\n"
        "globalThis.fetch = () => new Promise(() => {});   // the saved text never matters here\n"
        "const topPortalZ = () => 10031;\n"
        "const uiModule = { showToast() {}, showError() {} };\n"
        "const editors = () => document.body.children.filter((n) => n.className === 'vision-editor-overlay').length;\n"
        # The module-level bindings the two functions share, as the file declares them.
        "let _visionEditorEl = null;\nlet _visionEditorUnreg = null;\nlet _visionEditorEsc = null;\n"
        + _cut("function _closeVisionEditor(") + "\n"
        + _cut("function _openVisionEditor(") + "\n"
        + script)
    out = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30, cwd=box)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_first_escape_closes_the_editor_and_only_the_editor(box):
    """The row's `Verify:`."""
    out = _run(box, """
        const behind = document.body.appendChild(document.createElement('div'));
        behind.className = 'modal';                 // a window open behind the chat
        _openVisionEditor({ id: 'a'.repeat(32) + '.png' }, null);
        const open = editors();
        const first = dismissTopMenu();             // the arbiter's first question
        const afterFirst = editors();
        const second = dismissTopMenu();            // "nothing here": now the window
        console.log(JSON.stringify({ open, first, afterFirst, second, keydowns: keydowns.length,
                                     windowStill: behind.parentNode === document.body }));
    """)
    assert out == {"open": 1, "first": True, "afterFirst": 0, "second": False, "keydowns": 0,
                   "windowStill": True}


def test_close_reopen_and_a_sweep_each_leave_the_stack_empty(box):
    out = _run(box, """
        _openVisionEditor({ id: 'b'.repeat(32) + '.png' }, null);
        _openVisionEditor({ id: 'c'.repeat(32) + '.png' }, null);   // reopened on another photo
        const reopened = { editors: editors(), stack: _openMenuCount() };
        const closeBtn = document.body.children.find((n) => n.className === 'vision-editor-overlay')
          .querySelector('.vision-editor-btn');
        closeBtn.dispatchEvent({ type: 'click', target: closeBtn, stopPropagation() {}, preventDefault() {} });
        const closed = { editors: editors(), stack: _openMenuCount() };
        _openVisionEditor({ id: 'd'.repeat(32) + '.png' }, null);
        dismissOrRemove(document.body.children.find((n) => n.className === 'vision-editor-overlay'));
        console.log(JSON.stringify({ reopened, closed, swept: { editors: editors(), stack: _openMenuCount() },
                                     next: dismissTopMenu() }));
    """)
    assert out["reopened"] == {"editors": 1, "stack": 1}, "a reopen left the first editor on the stack"
    assert out["closed"] == {"editors": 0, "stack": 0}
    assert out["swept"] == {"editors": 0, "stack": 0}
    assert out["next"] is False
