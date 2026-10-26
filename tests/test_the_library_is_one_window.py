# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-14`, `B734`, `B1276` — the Library is one window, and the dead ones are gone.

`sessions.js` carried two windows nobody could open:

  * **`#library-modal`** (`P9-14`, `B734`). `openLibrary` hands every door to
    the Library window `documentLibrary.js` draws, and drew a window of its own
    only when `window.documentModule` was missing — which it never is: `app.js`
    imports `document.js` statically, and that module sets it as it evaluates.
    `P9-14`'s one-row-at-a-time bulk loops lived in that window, and so did
    `B734`'s nine "Failed to load …"/"No sessions loaded" states with no reason
    and no retry. Both rows asked: delete the dead window under `Law 1`, or make
    it reachable. There is one Library, so it is deleted, and `B734`'s sites
    with it.
  * **`openArchive` / `closeArchive` / `#archive-modal`** (`B1276`): a second
    archive browser with its own state (`_arc`), fetch, cards, bulk bar and
    chips. Nothing called `openArchive`; the one archive is the Library
    window's Archive tab (`B1194`). The row's proposed DELETE: the two
    functions, `_arc*`, the export entries, and the ids in `app.js`.

What is pinned (`Law 20`): `openLibrary`, cut out of `sessions.js` and run,
delegates every door with its tab, and — `window.documentModule` missing —
says so in a sentence and draws nothing; the dismiss list in `app.js` and the
tour's window list, evaluated, name neither dead id; and, as absences over the
whole tree (the one use a file-wide search is right for), nothing in `static/`
names `openArchive`, `closeArchive`, `#archive-modal`, `#library-modal` or the
`_arc` state, and `sessions.js` draws no `doclib-empty` state.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_function

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SESSIONS_JS = STATIC / "js" / "sessions.js"
APP_JS = STATIC / "app.js"
TOUR_JS = STATIC / "js" / "tourHints.js"


def _node(script: str) -> dict:
    out = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_every_library_door_goes_to_the_one_window():
    body = js_function(SESSIONS_JS.read_text(encoding="utf-8"), "export function openLibrary")
    out = _node(f"""
        const asked = [], said = [], drawn = [];
        globalThis.window = globalThis;
        globalThis.document = {{ body: {{ appendChild: (n) => drawn.push(n) }}, getElementById: () => null,
                                 createElement: () => ({{}}) }};
        const uiModule = {{ showError: (m) => said.push(m) }};
        function openLibrary(defaultTab) {body}
        window.documentModule = {{ openLibrary: (o) => asked.push(o) }};
        openLibrary(); openLibrary('chats'); openLibrary('archive');
        delete window.documentModule;
        openLibrary('chats');
        console.log(JSON.stringify({{ asked, said, drawn: drawn.length }}));
    """)
    assert out["asked"] == [{"tab": "documents"}, {"tab": "chats"}, {"tab": "archive"}]
    assert out["said"] == ["The Library did not load. Reload the page to open it."]
    assert out["drawn"] == 0, "a second Library window was drawn"


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_lists_of_windows_name_no_dead_window():
    app = js_binding(APP_JS.read_text(encoding="utf-8"), "_dynamicModalIds")
    tour = js_binding(TOUR_JS.read_text(encoding="utf-8"), "SHOW_MODALS")
    out = _node(f"{app}\n{tour}\nconsole.log(JSON.stringify({{ app: _dynamicModalIds, tour: [...SHOW_MODALS] }}));")
    for ids in (out["app"], out["tour"]):
        assert "library-modal" not in ids and "archive-modal" not in ids
    assert "doclib-modal" in out["app"] and "doclib-modal" in out["tour"], "the one Library left the lists"


def _static_text_files():
    for path in STATIC.rglob("*"):
        if path.is_file() and "lib" not in path.relative_to(STATIC).parts[:1] \
                and path.suffix in (".js", ".mjs", ".html", ".css"):
            yield path


def test_nothing_in_static_names_the_dead_windows():
    # `_arc` the identifier — the dead browser's state. The Library window's
    # Archive tab, the one archive, keeps its own `_arc…` locals and its
    # `._arc-menu` buttons; those are not it.
    gone = re.compile(r"\bopenArchive\b|\bcloseArchive\b|archive-modal|library-modal|\b_arc\b(?!-)")
    found = []
    for path in _static_text_files():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if gone.search(line):
                found.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert found == []


def test_the_chat_module_draws_no_library_states_of_its_own():
    """`B734`'s nine sites were `doclib-empty` grids in the dead window."""
    src = SESSIONS_JS.read_text(encoding="utf-8")
    assert "doclib-empty" not in src
    assert not re.search(r"\b_arc[A-Z]\w*", src), "an archive-browser helper is still defined"
