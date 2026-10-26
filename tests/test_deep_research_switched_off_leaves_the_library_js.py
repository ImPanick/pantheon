# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1275` / `B1277` — the Library follows Deep Research's switches, and an
empty archive says so in one line.

`B1275`, measured on `03f50081`: the table hides Deep Research at every door,
but the Library window always drew its Research tab and the Archive tab always
asked `/api/research/library?archived=true`. Every research route answers to
`require_feature("deep_research")`, so with Deep Research off for everyone the
tab was a 403 state and an empty archive said *"Part of the archive did not
load. Research: …"*. The fix reads the existing switch helper
(`window.pantheonToolShown('research')` — `ui_visibility.js` `toolShown`), the
way Documents follow the Library's (`B1194`).

`B1277`: the empty archive said "Nothing archived yet — Archive a chat, a
document or a research report and it moves here instead of being deleted.",
two sentences naming documents in a window drawn without them. Now: "Nothing
archived yet."

Driven, not read (`Law 20`): `static/js/documentLibrary.js` is imported whole
in the DOM shim's sandbox `B1194` built, with the real `ui_visibility.js`, and
`openLibrary` is called with each of Deep Research's three switches off.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hiding_the_library_keeps_the_archive_js import (  # noqa: E402
    DOCLIB_JS, UI_VIS, _WIN_PREAMBLE, _WIN_SHIM, _WIN_STUBS,
)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Deep Research's three columns in the one table.
RESEARCH_OFF = {
    "everyone": "{ features: { deep_research: false } }",
    "person": "{ privileges: { can_use_research: false }, auth: true }",
    "browser": "{ ui: { 'tool-research': false } }",
}

# The empty state as drawn, every line of it — the shared stub keeps only the
# title, and `B1277` is about the line under it.
_STUBS = {
    **_WIN_STUBS,
    "ui.js": ui_default_stub(
        "showToast: (m, o) => toasts.push({ text: String(m), button: o && typeof o === 'object' ? o.action : null }),"
        " showError: (m) => toasts.push({ text: String(m), button: null }),"
        " renderEmptyState: (host, spec) => { host.textContent = [spec.title, spec.message, spec.reason]"
        ".filter(Boolean).join(' | '); },"
        " isTouchInsideModal: () => false, styledConfirm: async () => false,",
        exports="export const toasts = [];"),
}

# An empty archive: the shim's server, with nothing archived in any source
# (asked is still recorded, by the shim's own fetch, before the answer is
# replaced).
_EMPTY_ARCHIVE = """
const _real = globalThis.fetch;
globalThis.fetch = async (url) => {
  const r = await _real(url);
  if (!/archived/.test(String(url))) return r;
  const none = { sessions: [], documents: [], research: [], total: 0 };
  return { ok: true, status: 200, json: async () => none, text: async () => JSON.stringify(none) };
};
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("b1275-window"), DOCLIB_JS, _WIN_SHIM, _STUBS)
    shutil.copy(UI_VIS, d / "ui_visibility.js")
    return d


def _go(sandbox, script: str) -> dict:
    return _run(sandbox, _WIN_PREAMBLE + _EMPTY_ARCHIVE, script)


@pytest.mark.parametrize("column", sorted(RESEARCH_OFF))
def test_deep_research_off_takes_the_research_tab_and_its_archive_request(sandbox, column):
    """`Verify:` Deep Research off — no Research tab, no research request, an
    empty archive says it is empty."""
    out = _go(sandbox, f"""
        V.applyToolVisibility({RESEARCH_OFF[column]}, document);
        L.openLibrary();
        await tick();
        const first = {{ tabs: tabs(), panels: panels(), active: active() }};
        press('archive');
        await tick();
        const archive = win().querySelector('#doclib-arc-grid').textContent;
        console.log(JSON.stringify({{ first, archive, asked, toasts }}));
    """)
    assert out["first"] == {"tabs": ["chats", "documents", "archive"],
                            "panels": ["chats", "archive", "documents"],
                            "active": "documents"}
    assert not [u for u in out["asked"] if "/api/research" in u], out["asked"]
    assert "/api/sessions/archived" in out["asked"]
    assert out["archive"] == "Nothing archived yet.", (
        "an empty archive with Deep Research off did not say it is empty")
    assert out["toasts"] == []


def test_the_research_tab_asked_for_by_name_is_deep_researchs_door(sandbox):
    """`/library/research` (and the panel's own *Library → Research*) with Deep
    Research off: the window does not open on a tab it no longer has; the door
    says Deep Research's sentence, as every other Deep Research door does."""
    out = _go(sandbox, """
        V.applyToolVisibility({ features: { deep_research: false } }, document);
        L.openLibrary({ tab: 'research' });
        await tick();
        console.log(JSON.stringify({ open: !!win(), asked, toasts }));
    """)
    assert out["open"] is False
    assert out["asked"] == []
    assert out["toasts"] == [{"text": "Deep Research is switched off for everyone. An admin can "
                                      "turn it back on in Settings → Agent Tools.", "button": None}]


def test_library_and_deep_research_both_off_leave_chats_and_the_archive(sandbox):
    """The two rules compose: the chat archive's window with neither documents
    nor research in it, asking for neither, and an archive whose every asked
    source failing still reads "The archive did not load." (`P9-08`)."""
    out = _go(sandbox, """
        V.applyToolVisibility({ features: { deep_research: false, document_editor: false } }, document);
        L.openLibrary({ tab: 'archive' });
        await tick();
        const both = { tabs: tabs(), active: active(), said: win().querySelector('#doclib-arc-grid').textContent };
        L.closeLibrary();
        await tick(30);
        globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => ({ detail: 'down' }), text: async () => 'down' });
        L.openLibrary({ tab: 'archive' });
        await tick();
        const down = win().querySelector('#doclib-arc-grid').textContent;
        console.log(JSON.stringify({ both, down, asked }));
    """)
    assert out["both"] == {"tabs": ["chats", "archive"], "active": "archive",
                           "said": "Nothing archived yet."}
    assert not [u for u in out["asked"] if "/api/research" in u or "/api/document" in u], out["asked"]
    assert out["down"].startswith("The archive did not load."), out["down"]
    assert "Research:" not in out["down"]


def test_deep_research_shown_keeps_its_tab_and_its_archived_reports(sandbox):
    """Nothing switched off: as before — the Research tab, and the Archive asks
    for archived research."""
    out = _go(sandbox, """
        L.openLibrary();
        await tick();
        const first = tabs();
        press('archive');
        await tick();
        console.log(JSON.stringify({ first, asked,
          archive: win().querySelector('#doclib-arc-grid').textContent }));
    """)
    assert out["first"] == ["chats", "documents", "research", "archive"]
    assert "/api/research/library" in out["asked"]
    assert out["archive"] == "Nothing archived yet."
