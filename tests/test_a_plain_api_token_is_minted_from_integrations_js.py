# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1193` — a plain API token can be minted from a screen.

`P23-03` listed every `/api/tokens` row as *API token* with Remove (`SET-U-9`'s
first half), and the *Add Integration* picker made only *Claude Agent* and
*Codex Agent* tokens — so the companion app's, a script's or a Prometheus
scrape's token (`metrics:read`) could be revoked from the room and made from
nowhere. The picker offers *API token* now: a name, what it may do (the
server's own list from `GET /api/tokens/profiles`), and the secret shown once.

Driven: the real `showTokenForm` and the picker's real `_typeOptions`, cut out
of `settings.js` and run under node against the shim with HTML parsing on, so
the form's own markup is what the code finds; `fetch` answers as the token
routes do and records what was posted.
"""
import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_binding, js_function

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _script() -> str:
    src = SETTINGS_JS.read_text(encoding="utf-8")
    return "\n".join([
        "import { installDom, installHtmlParsing, Node } from './dom.js';",
        "const document = installDom();",
        "installHtmlParsing();",
        esc_source(),
        "const el = (id) => document.getElementById(id);",
        js_binding(src, "INTG_TYPES") + ";",
        js_binding(src, "_typeOptions") + ";",
        "async function readRefusal(res, fb) { const b = await res.json(); return { sentence: b.detail || fb }; }",
        "globalThis.FormData = class { constructor() { this._d = []; }",
        "  append(k, v) { this._d.push([k, String(v)]); } };",
        "const posted = []; let listed = 0;",
        "async function renderList() { listed += 1; }",
        "globalThis.fetch = async (url, opts = {}) => {",
        "  if (String(url).endsWith('/api/tokens/profiles'))",
        "    return { ok: true, status: 200, json: async () => ({ allowed_scopes: ['chat', 'metrics:read', 'todos:read'] }) };",
        "  if (String(url).endsWith('/api/tokens') && opts.method === 'POST') {",
        "    const f = Object.fromEntries(opts.body._d); posted.push(f);",
        "    return { ok: true, status: 200, json: async () => ({ id: 't1', name: f.name, token: 'pan_s3cret',",
        "      scopes: f.scopes.split(',') }) };",
        "  }",
        "  return { ok: false, status: 404, json: async () => ({}) };",
        "};",
        "const formEl = document.body.appendChild(new Node('div'));",
        "async function showTokenForm() " + js_function(src, "async function showTokenForm"),
        "const tick = () => new Promise((r) => setTimeout(r, 0));",
        "const out = { offered: _typeOptions.find(([k]) => k === 'token') || null };",
        "await showTokenForm();",
        "out.scopes = [...formEl.querySelectorAll('.uf-token-scope')].map((c) => [c.value, !!c.checked]);",
        "// Nameless: refused with a sentence, nothing posted.",
        "el('uf-token-create').click(); await tick();",
        "out.nameless = { msg: el('uf-token-msg').textContent, posted: posted.length };",
        "el('uf-token-name').value = 'grafana scrape';",
        "const metrics = [...formEl.querySelectorAll('.uf-token-scope')].find((c) => c.value === 'metrics:read');",
        "metrics.checked = true;",
        "const chat = [...formEl.querySelectorAll('.uf-token-scope')].find((c) => c.value === 'chat');",
        "chat.checked = false;",
        "el('uf-token-create').click(); await tick(); await tick();",
        "out.created = { posted, shown: el('uf-token-value').textContent,",
        "  revealed: el('uf-token-reveal').style.display, msg: el('uf-token-msg').textContent, listed };",
        "// Opened again: the secret is not there to be read a second time.",
        "await showTokenForm();",
        "out.reopened = { shown: el('uf-token-value').textContent, revealed: el('uf-token-reveal').style.display };",
        "console.log(JSON.stringify(out));",
    ])


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tokenform")
    (tmp / "dom.js").write_text(_DOM)
    return _run(tmp, "", _script())


def test_add_integration_offers_an_api_token(drawn):
    assert drawn["offered"] == ["token", "API token"]


def test_the_form_offers_what_the_server_allows_with_chat_first_ticked(drawn):
    assert drawn["scopes"] == [["chat", True], ["metrics:read", False], ["todos:read", False]]


def test_a_token_needs_a_name_and_says_so(drawn):
    assert drawn["nameless"]["posted"] == 0
    assert "name" in drawn["nameless"]["msg"].lower()


def test_a_name_and_scopes_mint_a_token_shown_once(drawn):
    """The row's `Verify:` — Add Integration → API token → a name and scopes →
    the token shown once."""
    created = drawn["created"]
    assert created["posted"] == [{"name": "grafana scrape", "scopes": "metrics:read"}]
    assert created["shown"] == "pan_s3cret"
    assert created["revealed"] == "flex"
    assert "metrics:read" in created["msg"]
    assert created["listed"] == 1, "the new row appears in the list"
    assert drawn["reopened"] == {"shown": "", "revealed": "none"}
