# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1196` — a non-admin's shortcut change holds, as theirs.

Keybinds were instance settings (`POST /api/auth/settings`, admin only); since
`P23-03` the refusal said *"Admin only."* instead of *Shortcut saved*, but a
person still could not set their own keys. `D-2026-10-25-04` §2 settles which
way: *"Defaults should be defaults. If an admin sets a default, that becomes the
platform wide default … A person's own pick still wins for them."* So an
admin's change is still the instance's, and anyone else's is theirs
(`/api/prefs/keybinds`), merged over the admin's by one rule
(`keyboard-shortcuts.js` `mergeKeybinds`) that the dispatcher, the Shortcuts
panel and `/shortcuts` all read.

Driven: the real prefs router behind the real sign-in stamp, two people; the
real Shortcuts panel (`initShortcuts`, cut out of `settings.js`) under node with
the real `keyboard-shortcuts.js`, as a member and as an admin, rebinding a key,
then opened again — "after a reload".
"""
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.prefs_routes as prefs_routes
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_binding, js_function
from tests.helpers.signed_in import ADMIN, MEMBER, as_person

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
NODE = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the server: a person's own keybinds ─────────────────────────────────────

@pytest.fixture
def prefs_as(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(tmp_path / "prefs.json"))

    def client(who):
        app = as_person(FastAPI(), who)
        app.include_router(prefs_routes.setup_prefs_routes())
        return TestClient(app)
    return client


def test_a_member_stores_their_own_keybinds_and_reads_them_back(prefs_as):
    bob = prefs_as(MEMBER)
    r = bob.put("/api/prefs/keybinds", json={"value": {"open_notes": "Ctrl+Alt+Y"}})
    assert r.status_code == 200, r.text
    assert bob.get("/api/prefs/keybinds").json()["value"] == {"open_notes": "ctrl+alt+y"}
    # Somebody else's are not his.
    assert prefs_as(ADMIN).get("/api/prefs/keybinds").json()["value"] is None


@pytest.mark.parametrize("bad", [["ctrl+k"], "ctrl+k", {"open_notes": 3}, {"": "ctrl+k"},
                                 {"open_notes": "x" * 65}])
def test_a_map_that_is_not_one_is_refused_with_a_sentence(prefs_as, bad):
    r = prefs_as(MEMBER).put("/api/prefs/keybinds", json={"value": bad})
    assert r.status_code == 400
    assert r.json()["detail"].endswith(".")


# ── the panel and the dispatcher ────────────────────────────────────────────

def _panel_script(*, admin: bool, instance: dict, mine: dict) -> str:
    src = (JS / "settings.js").read_text(encoding="utf-8")
    return "\n".join([
        "import { installDom, installHtmlParsing, Node } from './dom.js';",
        "const document = installDom();",
        "installHtmlParsing();",
        "{ const E0 = globalThis.Event; globalThis.Event = class extends E0 {",
        "  stopPropagation() {} preventDefault() {} }; }",
        esc_source(),
        "import { KEYBIND_DEFAULTS, KEYBIND_LABELS, keybindLayers, mergeKeybinds } from './keyboard-shortcuts.js';",
        "import { isAltGrEvent } from './platform.js';",
        "const toasts = [], errors = [];",
        "const uiModule = { esc, showToast: (m) => toasts.push(m), showError: (m) => errors.push(m) };",
        f"const viewerIsAdmin = () => {json.dumps(admin)};",
        "const el = (id) => document.getElementById(id);",
        "async function readRefusal(res, fb) { return { sentence: fb, status: res.status }; }",
        "function _notSaved(e) " + js_function(src, "function _notSaved"),
        "const posted = [], put = [];",
        "async function _postSettings(body) { posted.push(body); return { ok: true }; }",
        js_binding(src, "SHORTCUT_DEFAULTS") + ";",
        js_binding(src, "SHORTCUT_ICONS") + ";",
        js_binding(src, "SHORTCUT_LABELS") + ";",
        js_binding(src, "SHORTCUT_CATEGORIES") + ";",
        "function _formatKeyCaps(combo) " + js_function(src, "function _formatKeyCaps"),
        "function _comboFromEvent(e) " + js_function(src, "function _comboFromEvent"),
        "async function initShortcuts() " + js_function(src, "async function initShortcuts"),
        f"globalThis.__INSTANCE = {json.dumps(instance)};",
        f"let MINE = {json.dumps(mine)};",
        "globalThis.fetch = async (url, opts = {}) => {",
        "  if (String(url).includes('/api/prefs/keybinds')) {",
        "    if ((opts.method || 'GET') === 'PUT') { const v = JSON.parse(opts.body).value; put.push(v); MINE = v;",
        "      return { ok: true, status: 200, json: async () => ({ key: 'keybinds', value: v }) }; }",
        "    return { ok: true, status: 200, json: async () => ({ key: 'keybinds', value: MINE }) };",
        "  }",
        "  return { ok: false, status: 404, json: async () => ({}) };",
        "};",
        "for (const id of ['shortcuts-list', 'shortcuts-reset-btn', 'shortcuts-scope']) {",
        "  const n = document.body.appendChild(new Node(id === 'shortcuts-reset-btn' ? 'button' : 'div'));",
        "  n.setAttribute('id', id);",
        "}",
        "const tick = () => new Promise((r) => setTimeout(r, 0));",
        "const row = (a) => document.querySelector(`.shortcut-row[data-action=\"${a}\"]`);",
        "const shown = (a) => [...row(a).querySelectorAll('kbd')].map((k) => k.textContent).join('+');",
        "await initShortcuts();",
        "const out = { scope: el('shortcuts-scope').textContent, before: shown('open_notes') };",
        "// Rebind Open Notes: press its key, type Ctrl+Alt+Y, confirm.",
        "row('open_notes').querySelector('.shortcut-key').click();",
        "document.dispatchEvent(Object.assign(new Event('keydown'),",
        "  { key: 'y', ctrlKey: true, altKey: true, shiftKey: false, metaKey: false }));",
        "row('open_notes').querySelector('.shortcut-action-btn').click();",
        "await tick(); await tick();",
        "Object.assign(out, { posted, put, toasts, errors, live: window._pantheonKeybinds && window._pantheonKeybinds.open_notes });",
        "// Opened again: the reload.",
        "document.getElementById('shortcuts-list').innerHTML = '';",
        "await initShortcuts();",
        "out.after = shown('open_notes');",
        "out.dispatcher = mergeKeybinds(KEYBIND_DEFAULTS, await keybindLayers()).open_notes;",
        "console.log(JSON.stringify(out));",
    ])


def _sandbox(tmp_path, instance) -> Path:
    (tmp_path / "dom.js").write_text(_DOM)
    shutil.copy(JS / "keyboard-shortcuts.js", tmp_path / "keyboard-shortcuts.js")
    shutil.copy(JS / "platform.js", tmp_path / "platform.js")
    (tmp_path / "appConfig.js").write_text(
        "export function getSettings() { return Promise.resolve({ keybinds: globalThis.__INSTANCE }); }\n")
    return tmp_path


@NODE
def test_a_member_rebinds_a_key_and_it_holds_after_a_reload(tmp_path):
    """The row's `Verify:`. The admin's default (`ctrl+alt+n`, set for the
    instance) is untouched; the member's own pick is stored as theirs and wins
    for them in the panel and in the dispatcher's map."""
    instance = {"open_notes": "ctrl+alt+n"}
    out = _run(_sandbox(tmp_path, instance), "",
               _panel_script(admin=False, instance=instance, mine={}))
    assert out["before"] == "Ctrl+Alt+N", "the admin's default is what a member starts from"
    assert out["posted"] == [], "a member's change never writes the instance's settings"
    assert out["put"] == [{"open_notes": "ctrl+alt+y"}], "only what differs is theirs"
    assert out["errors"] == [] and out["toasts"] == ["Shortcut saved for you"]
    assert out["live"] == "ctrl+alt+y"
    assert out["after"] == "Ctrl+Alt+Y"
    assert out["dispatcher"] == "ctrl+alt+y"
    assert "yours" in out["scope"].lower()


@NODE
def test_an_admins_change_is_still_everyones_default(tmp_path):
    out = _run(_sandbox(tmp_path, {}), "", _panel_script(admin=True, instance={}, mine={}))
    assert out["put"] == []
    assert len(out["posted"]) == 1 and out["posted"][0]["keybinds"]["open_notes"] == "ctrl+alt+y"
    assert "everyone" in out["scope"].lower()
