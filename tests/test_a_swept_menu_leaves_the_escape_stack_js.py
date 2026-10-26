# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1295` (fx5-cards) — a menu swept away leaves the Escape stack with it.

Two sweeps in `static/app.js` cleared the message ··· menu with a bare
`.remove()`: any scroll of the chat, and `closeAllPopups` (a rail button, a
sidebar row, a section header). `chatRenderer.js` opens that menu through
`bindMenuDismiss`, which puts it on the Escape stack — so its entry stayed
until the next click anywhere, and the next Escape popped a menu that was
already gone, `dismissTopMenu()` answered `true`, and the `ui.js` arbiter
stopped there: a window open behind stayed open. `escMenuStack.dismissOrRemove`
exists for exactly this, and both sweeps use it now.

Driven (`Law 20`): both sweeps cut out of `app.js` and run over the real
`escMenuStack.js` in the shared DOM shim, with a ··· menu opened the way the
renderer opens it. After each sweep the menu is gone and the arbiter's first
question — `dismissTopMenu()` — is answered "nothing here", which is when it
goes on to close the window (its order is pinned by
`tests/test_escape_peels_the_innermost_layer_js.py`).
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
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(signature: str) -> str:
    return js_definition(APP, blank_text(APP, "js").index(signature))


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("sweeps")
    (d / "dom.js").write_text(_DOM)
    shutil.copy(ROOT / "static" / "js" / "escMenuStack.js", d / "escMenuStack.js")
    return d


def _run(box, sweep: str) -> dict:
    case = box / "case.mjs"
    case.write_text(
        "import { installDom } from './dom.js';\n"
        "import { bindMenuDismiss, dismissTopMenu, dismissOrRemove } from './escMenuStack.js';\n"
        "const document = installDom();\n"
        + _cut("function _sweepChatScrollPopups(") + "\n"
        + _cut("function closeAllPopups(") + "\n"
        + """
const menu = document.body.appendChild(document.createElement('div'));
menu.className = 'msg-overflow-menu';
bindMenuDismiss(menu, () => menu.remove());          // as chatRenderer opens it
const kept = document.body.appendChild(document.createElement('div'));
kept.className = 'msg-overflow-menu';                  // the one a click keeps
%s
const gone = !menu.parentNode;
const answer = dismissTopMenu();                       // the arbiter's first question
console.log(JSON.stringify({ gone, answer }));
""" % sweep)
    out = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30, cwd=box)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_scroll_of_the_chat_takes_the_menu_off_the_stack(box):
    assert _run(box, "_sweepChatScrollPopups();") == {"gone": True, "answer": False}


def test_closing_every_popup_takes_the_menu_off_the_stack(box):
    assert _run(box, "closeAllPopups(kept);") == {"gone": True, "answer": False}
