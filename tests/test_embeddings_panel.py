# SPDX-License-Identifier: AGPL-3.0-or-later
"""H04 — a complete embedding-model manager with zero pixels.

`routes/embedding_routes.py` is finished, self-consistent, admin-gated code:
the fastembed catalogue with downloaded / downloading / active / recommended /
size, sorted active-first; a download that runs off the event loop; a progress
poll; a delete that refuses to remove the model in use; and custom endpoint
configuration. `grep -rn "embeddings" static/` returned two irrelevant hits.

The state that matters most is the one where nothing is installed. `fastembed`
and `chromadb` are BOTH optional dependencies — neither is present on a clean
checkout — and without them memory and document search fall back to keyword
matching. `B40` is what that fallback was actually doing, which is why this
panel leads with what is in use rather than with a catalogue, and why a missing
dependency is explained rather than reported as an error.

Per `Law 20`, JS assertions resolve a function before matching.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PANEL = (ROOT / "static" / "js" / "embeddings.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
REGISTRY = (ROOT / "static" / "js" / "settings" / "registry.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "routes" / "embedding_routes.py").read_text(encoding="utf-8")


def _js_fn(source, header):
    start = source.index(header)
    i = source.index("{", start)
    depth, j = 0, i
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {header}")


# ── the door exists in all three places a settings panel needs ──

def test_the_panel_is_registered_as_admin_only():
    """The registry, the nav button and the panel div must agree — there is a
    `getSettingsRegistryIssues` check that warns on a mismatch, and a panel
    registered but not drawn is exactly the drift this row is about."""
    entry = REGISTRY.split("id: 'embeddings'", 1)[1].split("}),", 1)[0]
    assert "adminOnly: true" in entry
    assert "controller: 'admin'" in entry
    assert 'data-settings-tab="embeddings"' in INDEX
    assert 'data-settings-panel="embeddings"' in INDEX


def test_it_is_findable_by_what_someone_would_search_for():
    """Nobody types "fastembed" when their memory stops finding things."""
    entry = REGISTRY.split("id: 'embeddings'", 1)[1].split("}),", 1)[0]
    for word in ("'rag'", "'memory'", "'vector'", "'search'"):
        assert word in entry, f"the panel is not findable by {word}"


def test_the_panel_loads_when_it_is_opened():
    """`initRag` is what happens to a panel nobody calls."""
    hook = _js_fn(SETTINGS, "function onSettingsPanelActivated(")
    assert "tab === 'embeddings'" in hook
    assert "embeddings.js" in hook


def test_it_is_not_loaded_at_boot():
    """Three requests, one of which walks the model cache on disk. Nobody opens
    Settings to look at embeddings by accident."""
    hook = _js_fn(SETTINGS, "function onSettingsPanelActivated(")
    assert "import('./embeddings.js')" in hook, "must be a dynamic import"
    assert "import embeddings" not in SETTINGS, "must not be a static import"


# ── every route the row lists gets a caller ──

@pytest.mark.parametrize("route", [
    "/api/embeddings/models",
    "/api/embeddings/endpoint",
])
def test_the_listed_routes_are_called(route):
    assert route in PANEL


def test_the_per_model_routes_are_called():
    assert "/download" in PANEL and "/status" in PANEL
    assert "method: 'DELETE'" in PANEL


def test_every_embedding_route_now_has_a_frontend_caller():
    """The row's own Verify, measured with the checker rather than asserted.

    Also the trap this cost: a NEW frontend file is invisible to
    `check-unreachable` until it is `git add`ed, because the scan is
    `git ls-files`. The panel was fully wired and the inventory was unchanged."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cu", str(ROOT / ".pantheon" / "check-unreachable.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    called = {mod.normalise(p) for p in mod.frontend_paths()}
    orphans = [p for p, _ in mod.app_routes()
               if "/api/embeddings" in p and mod.normalise(p) not in called]
    assert orphans == [], f"still no caller for: {orphans}"


# ── the state that matters most ──

def test_a_missing_dependency_is_explained_not_reported_as_an_error():
    """`fastembed` is optional and absent on a clean install. "fastembed is not
    installed" tells an operator nothing about what it costs them."""
    body = _js_fn(PANEL, "async function _renderModels(")
    assert "e.status === 503" in body
    assert "pip install fastembed" in body
    assert "keyword matching" in body


def test_the_status_card_says_what_is_actually_in_use():
    body = _js_fn(PANEL, "async function _renderStatus(")
    assert "endpoint.active" in body, "a remote endpoint wins and must be named"
    assert "m.active" in body, "otherwise the active local model"
    assert "'nothing'" in body, "and if neither, say so"


def test_it_reports_vector_storage_separately():
    """chromadb is a second optional dependency, and without it memory search
    cannot use vectors whatever model is configured. Reusing the existing
    `/api/diagnostics/services` rather than adding a second health route."""
    body = _js_fn(PANEL, "async function _renderStatus(")
    assert "/api/diagnostics/services" in body
    assert "'chromadb'" in body
    assert "whatever model is configured above" in PANEL


def test_a_configured_but_undownloaded_model_says_so():
    """The quietest failure available here: the setting names a model that was
    never fetched, so nothing embeds and nothing complains."""
    body = _js_fn(PANEL, "async function _renderStatus(")
    assert "active && !active.downloaded" in body


# ── behaviour the routes cannot enforce ──

def test_delete_is_not_offered_for_the_model_in_use():
    """The route raises 400 for it. An action that always fails is not an
    action."""
    body = _js_fn(PANEL, "function _modelRow(")
    assert "} else if (!model.active) {" in body
    assert 'raise HTTPException(400, "Cannot delete the active embedding model")' in ROUTES, \
        "the route no longer refuses — re-check whether hiding the button is right"


def test_delete_confirms_and_says_it_is_reversible():
    body = _js_fn(PANEL, "async function _deleteModel(")
    assert "styledConfirm" in body
    assert "can be downloaded again" in body
    assert body.index("styledConfirm") < body.index("method: 'DELETE'")


def test_the_routes_refusal_text_is_shown_rather_than_flattened():
    """"Cannot delete the active embedding model" is the whole reason the
    guard exists; replacing it with "failed" throws away the explanation."""
    body = _js_fn(PANEL, "async function _deleteModel(")
    assert "?.detail" in body
    assert "showError(String(e.message || e))" in body


def test_the_endpoint_validation_message_is_shown_verbatim():
    """The save route rejects non-HTTP(S) schemes and the cloud metadata range
    and says which rule was broken. That is more useful than "failed"."""
    body = _js_fn(PANEL, "function _wireEndpoint(")
    assert "?.detail || detail" in body
    assert "msg.textContent = String(e.message || e);" in body


def test_the_api_key_is_not_left_sitting_in_the_dom():
    body = _js_fn(PANEL, "function _wireEndpoint(")
    assert "keyIn.value = '';" in body


def test_a_download_poll_cannot_be_started_twice_or_outlive_the_panel():
    """An interval that outlives its row is how a settings modal ends up making
    requests forever."""
    poll = _js_fn(PANEL, "function _pollUntilDownloaded(")
    assert "if (_pollTimers.has(name)) return;" in poll
    assert "setTimeout" in poll and "setInterval" not in PANEL
    assert "function _stopAllPolls(" in PANEL
    assert "_stopAllPolls();" in _js_fn(PANEL, "export async function open(")


def test_the_catalogue_order_is_the_routes_and_is_not_re_sorted():
    """The route sorts active-first, then downloaded, then by size. That
    decision belongs there, and re-sorting here would silently fork it."""
    body = _js_fn(PANEL, "async function _renderModels(")
    assert ".sort(" not in body


def test_nothing_is_rendered_with_innerhtml():
    """Model names and descriptions come from the fastembed catalogue and the
    endpoint URL is operator-supplied."""
    assert not re.search(r"\.innerHTML\b", PANEL)
    assert "textContent" in PANEL


def test_badges_tint_rather_than_paint_text_in_the_accent():
    """Seven of the sixteen themes fail the contrast floor on undiluted accent
    text — the same finding that shaped `H01`'s panel."""
    body = _js_fn(PANEL, "function _modelRow(")
    assert "color-mix(in srgb, var(--accent" in body
    assert "color:var(--accent" not in body.replace(" ", "")
