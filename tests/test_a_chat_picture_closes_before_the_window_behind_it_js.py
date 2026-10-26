# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1294` (fx5-cards) — Escape closes a chat picture before the window behind it.

`chatRenderer.js`' `_openImageLightbox` answered Escape with its own
bubble-phase `document` listener (and a `MutationObserver` to drop it). C-NAV
has one arbiter: the capture-phase handler in `ui.js` asks the Escape stack
first (`dismissTopMenu`), then closes the top window and stops the key. The
picture was not on the stack — so with a window open behind it, the first
Escape closed the window and left the picture over the place it had been, and
only the second closed the picture: outermost first, the order C-NAV exists
to prevent. The card preview in `attachHand.js` draws the same `.attach-lightbox`
on the stack.

Now the picture is put on the stack (`bindMenuDismiss`, with any click closing
it as before), and the listener and its observer are gone.

Driven (`Law 20`): the real `_openImageLightbox`, cut out of `chatRenderer.js`,
over the real `escMenuStack.js` in the shared DOM shim. The arbiter's first
question — `dismissTopMenu()` — closes the picture and only the picture; the
next is answered "nothing here", which is when the arbiter goes on to the
window (the arbiter's own order is pinned by
`tests/test_escape_peels_the_innermost_layer_js.py`). No `keydown` listener is
left on `document`, and a sweep (`dismissOrRemove`) takes the picture off the
stack with it.
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


def _lightbox() -> str:
    return js_definition(RENDERER, blank_text(RENDERER, "js").index("function _openImageLightbox("))


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("lightbox")
    (d / "dom.js").write_text(_DOM)
    shutil.copy(JS / "escMenuStack.js", d / "escMenuStack.js")
    return d


def _run(box, script: str) -> dict:
    case = box / "case.mjs"
    case.write_text(
        "import { installDom } from './dom.js';\n"
        "import { bindMenuDismiss, dismissTopMenu, dismissOrRemove, _openMenuCount } from './escMenuStack.js';\n"
        "const document = installDom();\n"
        "const keydowns = [];\n"
        "const _add = document.addEventListener.bind(document);\n"
        "document.addEventListener = (t, fn, o) => { if (t === 'keydown') keydowns.push(fn); return _add(t, fn, o); };\n"
        "globalThis.Image = class { addEventListener() {} };\n"
        "globalThis.MutationObserver = class { observe() {} disconnect() {} };\n"
        "const topPortalZ = () => 10031;\n"
        "const pictures = () => document.body.children.filter((n) => n.className === 'attach-lightbox').length;\n"
        + _lightbox() + "\n" + script)
    out = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30, cwd=box)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_first_escape_closes_the_picture_and_only_the_picture(box):
    out = _run(box, """
        const behind = document.body.appendChild(document.createElement('div'));
        behind.className = 'modal';                 // a window open behind the chat
        _openImageLightbox({ id: 'a'.repeat(32) + '.png', name: 'cat.png' });
        const open = pictures();
        const first = dismissTopMenu();             // the arbiter's first question
        const afterFirst = pictures();
        const second = dismissTopMenu();            // "nothing here": now the window
        console.log(JSON.stringify({ open, first, afterFirst, second, keydowns: keydowns.length,
                                     windowStill: behind.parentNode === document.body }));
    """)
    assert out == {"open": 1, "first": True, "afterFirst": 0, "second": False, "keydowns": 0,
                   "windowStill": True}


def test_a_sweep_takes_the_picture_off_the_stack_with_it(box):
    out = _run(box, """
        _openImageLightbox({ id: 'b'.repeat(32) + '.png', name: 'dog.png' });
        const pic = document.body.children.find((n) => n.className === 'attach-lightbox');
        dismissOrRemove(pic);
        console.log(JSON.stringify({ left: pictures(), stack: _openMenuCount(), next: dismissTopMenu() }));
    """)
    assert out == {"left": 0, "stack": 0, "next": False}
