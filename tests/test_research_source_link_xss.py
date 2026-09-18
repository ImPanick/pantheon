# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guards for API-provided research source hrefs."""

from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent


def test_document_library_research_preview_whitelists_source_hrefs():
    src = (_REPO / "static" / "js" / "documentLibrary.js").read_text(encoding="utf-8")

    assert "function _safeResearchHref(raw)" in src
    assert "parsed.protocol === 'http:' || parsed.protocol === 'https:'" in src
    assert "const url = _safeResearchHref(src.url);" in src
    assert 'href="${_esc(url)}"' not in src
    assert "Failed to load: ${e.message}" not in src


def test_a_research_load_error_cannot_become_markup():
    """UPDATED 2026-09-18 by `P9-08`.

    This used to read `assert "Failed to load: ${_esc(e.message)}" in src`,
    pinning one escaping idiom inside one `innerHTML` template. That template is
    gone: the Research tab's failure is drawn by `ui.js`'s shared
    `renderEmptyState`, which assigns the server's words through `textContent`
    and never builds markup at all — so the property this guards is held more
    strongly than escaping held it, and the old assertion was pinning the
    *mitigation* rather than the property (`Law 20`).

    The dangerous construction is still asserted absent above, which is the one
    thing a whole-file substring search is good for. What replaces the positive
    half is a scope-resolved check that the error path reaches the shared
    renderer — and `tests/test_empty_states_js.py` then drives that renderer with
    `<img src=x onerror=1>` in the reason and reads back that the node's raw
    HTML is empty.
    """
    src = (_REPO / "static" / "js" / "documentLibrary.js").read_text(encoding="utf-8")
    start = src.index("async function _renderLibResearch(")
    end = src.index("_renderResearchGrid();", start)
    body = src[start:end]
    assert "renderEmptyState" in body, "the research load error no longer uses the shared state"
    assert "reason: e && e.message" in body, "the server's own words are not carried"
    assert "innerHTML = `" not in body, "the error is being built as markup again"


def test_research_panel_whitelists_source_hrefs():
    src = (_REPO / "static" / "js" / "research" / "panel.js").read_text(encoding="utf-8")

    assert "function _safeSourceHref(raw)" in src
    assert "parsed.protocol === 'http:' || parsed.protocol === 'https:'" in src
    assert "const url = _safeSourceHref(s.url);" in src
    assert 'const url = _esc(s.url || \'\');' not in src
