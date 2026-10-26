# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1219` — inside a folder, the type chips count the folder, and an empty
folder says where its documents are.

`DOCS-M-4`'s other half. `P23-06` made a folder chip count what opening it
shows; measured on `03f50081`, opening *Projects* — whose seven documents are
all in *Projects › Lumen 2.0* — drew `all (17) markdown (10) …`, the whole
library's counts, over a list showing none, and the empty state said only
"No documents here." without saying "7 in Lumen 2.0".

Now `GET /api/documents/library` counts its type facet in the open folder (one
folder scope for the list and its counts), and keeps the library's own number
as `library_total` for the "3 of 17" heading (`B1241`); the empty state names
the subfolders that hold documents and opens the fullest.

Driven (`Law 20`): the real routes through the real router, and
`static/js/documentLibrary.js` imported whole in `B1194`'s DOM sandbox with its
`fetch` pointed at those routes on a loopback socket (`B400`'s `live`
harness), the folder chip clicked as a person clicks it.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.test_a_file_imported_from_device_opens_readable import live  # noqa: F401
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hiding_the_library_keeps_the_archive_js import (  # noqa: E402
    DOCLIB_JS, UI_VIS, _WIN_PREAMBLE, _WIN_SHIM, _WIN_STUBS,
)
from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402

from tests.helpers.esc_stub import ui_default_stub  # noqa: E402


def _seed(env):  # noqa: F811
    """17 documents: 7 in Projects › Lumen 2.0 (5 markdown, 2 text), 3 in
    Clients, 7 unfiled; Projects itself holds none."""
    def doc(title, language, folder=None):
        body = {"title": title, "language": language, "content": title + " body"}
        if folder:
            body["folder"] = folder
        r = env.client.post("/api/document", json=body)
        assert r.status_code == 200, r.text
    for i in range(5):
        doc(f"spec {i}", "markdown", "Projects/Lumen 2.0")
    for i in range(2):
        doc(f"note {i}", "text", "Projects/Lumen 2.0")
    for i in range(3):
        doc(f"client {i}", "markdown", "Clients")
    for i in range(7):
        doc(f"loose {i}", "python" if i < 2 else "markdown")


@pytest.fixture
def folders_routed(env, monkeypatch):  # noqa: F811
    """The folder routes read this test's database and person. `env` patches
    the modules it imports; `document_folder_routes` binds `SessionLocal` and
    its two auth helpers when it is first imported, which in a full run is
    another test's doing."""
    import routes.document.document_folder_routes as folder_routes
    from tests.test_an_uploaded_document_keeps_its_name import OWNER
    monkeypatch.setattr(folder_routes, "SessionLocal", env.Session)
    monkeypatch.setattr(folder_routes, "get_current_user", lambda request: OWNER)
    monkeypatch.setattr(folder_routes, "require_privilege", lambda request, priv: OWNER)
    return env


def _library(env, **params):  # noqa: F811
    r = env.client.get("/api/documents/library", params={"limit": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_type_counts_are_the_open_folders(env, folders_routed):  # noqa: F811
    _seed(env)
    everything = _library(env)
    assert everything["languages"] == {"markdown": 13, "text": 2, "python": 2}
    assert everything["library_total"] == 17
    projects = _library(env, folder="Projects")
    assert projects["total"] == 0 and projects["languages"] == {}, projects["languages"]
    assert projects["library_total"] == 17
    lumen = _library(env, folder="Projects/Lumen 2.0")
    assert lumen["total"] == 7 and lumen["languages"] == {"markdown": 5, "text": 2}
    unfiled = _library(env, unfiled="true")
    assert unfiled["languages"] == {"markdown": 5, "python": 2} and unfiled["library_total"] == 17
    # The chip filters inside the folder as it counts.
    assert _library(env, folder="Projects/Lumen 2.0", language="text")["total"] == 2


# ── the window ──────────────────────────────────────────────────────────────

_KEEP_FETCH = "globalThis.__nodeFetch = globalThis.fetch;\n"

_STUBS = {
    **_WIN_STUBS,
    "ui.js": ui_default_stub(
        "showToast: (m) => toasts.push(String(m)), showError: (m) => toasts.push('ERR ' + m),"
        " renderEmptyState: (host, spec) => { host.textContent = [spec.title, spec.message]"
        ".filter(Boolean).join(' | '); host.__action = spec.action || null; },"
        " isTouchInsideModal: () => false, styledConfirm: async () => false,",
        exports="export const toasts = [];"),
}


@pytest.fixture
def window_box(tmp_path):
    (tmp_path / "b1219-window").mkdir()
    d = _make_sandbox(tmp_path / "b1219-window", DOCLIB_JS, _WIN_SHIM, _STUBS)
    shutil.copy(UI_VIS, d / "ui_visibility.js")
    (d / "keepfetch.js").write_text(_KEEP_FETCH)
    return d


def _window(box: Path, base: str, script: str) -> dict:
    entry = box / "case.mjs"
    entry.write_text(
        "import './keepfetch.js';\n" + _WIN_PREAMBLE
        + f"globalThis.fetch = (url, opts) => globalThis.__nodeFetch({json.dumps(base)} + String(url), opts);\n"
        + textwrap.dedent(script))
    environ = dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    proc = subprocess.run(["node", str(entry)], cwd=box, capture_output=True, text=True,
                          timeout=90, env=environ)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, (proc.stdout, proc.stderr)
    return json.loads(lines[-1])


_READ = """
const chips = () => win().querySelector('#doclib-chips').querySelectorAll('.memory-cat-chip').map((c) => c.textContent);
const folderChip = (name) => win().querySelectorAll('.doclib-folder-chip')
  .find((c) => c.querySelector('.doclib-folder-chip-name').textContent === name);
const grid = () => win().querySelector('#doclib-grid');
const stats = () => win().querySelector('#doclib-stats').textContent;
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_inside_a_folder_the_chips_count_it_and_the_empty_state_says_where(
        live, folders_routed, window_box):  # noqa: F811
    """`Fix:` scope the type chips to the open folder; name the subfolders that
    hold documents in the empty state."""
    _seed(live)
    out = _window(window_box, live.base, _READ + """
        L.openLibrary();
        await tick(40);
        const library = { chips: chips(), stats: stats() };
        folderChip('Projects').dispatchEvent({ type: 'click' });
        await tick(40);
        const projects = { chips: chips(), stats: stats(), empty: grid().textContent,
          action: grid().__action && grid().__action.label };
        grid().__action.onClick();
        await tick(40);
        const lumen = { chips: chips(), stats: stats(),
          cards: grid().querySelectorAll('.doclib-card').length };
        console.log(JSON.stringify({ library, projects, lumen, toasts }));
    """)
    assert out["toasts"] == [], out
    assert out["library"]["chips"][:1] == ["all (17)"], out
    assert out["library"]["stats"] == ""
    assert out["projects"]["chips"] == [], "the whole library's counts over an empty folder"
    assert out["projects"]["stats"] == "0 of 17"
    assert out["projects"]["empty"] == "No documents here. | 7 in Lumen 2.0."
    assert out["projects"]["action"] == "Open Lumen 2.0"
    assert out["lumen"]["chips"] == ["all (7)", "markdown (5)", "text (2)"]
    assert out["lumen"]["stats"] == "7 of 17"
    assert out["lumen"]["cards"] == 7
