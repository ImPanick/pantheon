# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B966`, the owner's call (`D-2026-10-01-01`): `can_use_bash` granted a
non-admin nothing — the non-admin blocklist refuses Pantheon's own shell to
every non-admin — so it is retired for non-admins. Settings → Users no longer
offers the switch; one sentence in its place points at the Workstation
permission. The stored key and the server's refusal are unchanged.

Every reader of the key, decided and driven here:

  * **Settings → Users** (`static/js/admin.js` `loadUsers`) — cut out of the
    module and run under node against the users list the real
    `GET /api/auth/users` returns: no switch, the sentence where it stood.
  * **The composer's Shell switch** (`TOOL_VISIBILITY.shell` in
    `static/js/ui_visibility.js` since `P23-03`) —
    keyed on where the person's shell runs, which `GET /api/auth/status` now
    answers (`shell`), not on the privilege; fed the real route's JSON.
  * **The dispatcher** — a non-admin holding the stored privilege is still
    refused the shell (`execute_tool_block`).
  * **The privilege map** (`get_privileges`, the users list, `/status`, roles)
    still carries the key, resolved as before (`Law 1`).
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_binding, js_code, js_function

ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "static" / "js" / "admin.js"
APP_JS = ROOT / "static" / "app.js"
NODE = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SENTENCE = ("Pantheon's own shell is for admins only — turn on Workstation below "
            "to give this person a shell in the workstation.")


# ── a real auth store with three people ─────────────────────────────────────

@pytest.fixture
def auth(tmp_path, monkeypatch):
    """`boss` (admin), `ann` (granted the workstation) and `bob` (still holding a
    `can_use_bash` an admin switched on before this change)."""
    from core.auth import AuthManager
    import src.settings as S

    am = AuthManager(str(tmp_path / "auth.json"))
    assert am.setup("boss", "correct-horse-1")
    assert am.create_user("ann", "correct-horse-1")
    assert am.create_user("bob", "correct-horse-1")
    assert am.set_privileges("ann", {"can_use_workstation": True})
    assert am.set_privileges("bob", {"can_use_bash": True})

    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()
    yield am
    S._invalidate_caches()


def _workstation(on: bool):
    import src.settings as S
    s = S.load_settings()
    s.update({"workstation_enabled": on, "workstation_url": "http://127.0.0.1:9" if on else ""})
    S.save_settings(s)


def _client(am) -> TestClient:
    from routes.auth_routes import setup_auth_routes
    app = FastAPI()
    app.include_router(setup_auth_routes(am))
    return TestClient(app)


def _status(am, who) -> dict:
    from routes.auth_routes import SESSION_COOKIE
    c = _client(am)
    c.cookies.set(SESSION_COOKIE, am.create_session_trusted(who))
    r = c.get("/api/auth/status")
    assert r.status_code == 200, r.text
    return r.json()


# ── the server: where each person's shell runs ──────────────────────────────

@pytest.mark.parametrize("on, who, shell", [
    (False, "boss", "pantheon"),
    (False, "ann", "none"),
    (False, "bob", "none"),          # holds can_use_bash, has no shell
    (True, "boss", "workstation"),
    (True, "ann", "workstation"),
    (True, "bob", "none"),           # can_use_bash is not the workstation grant
])
def test_status_says_where_the_shell_runs(auth, on, who, shell):
    _workstation(on)
    d = _status(auth, who)
    assert d["shell"] == shell


def test_the_privilege_map_still_carries_the_key(auth):
    """`Law 1`: nothing that reads the stored key breaks — it resolves as before."""
    assert _status(auth, "bob")["privileges"]["can_use_bash"] is True
    assert _status(auth, "ann")["privileges"]["can_use_bash"] is False
    assert _status(auth, "boss")["privileges"]["can_use_bash"] is True
    users = {u["username"]: u for u in auth.list_users()}
    assert users["bob"]["privileges"]["can_use_bash"] is True


def test_a_non_admin_holding_the_privilege_is_still_refused_the_shell(auth, monkeypatch):
    """The server's refusal, exactly as it was: the switch said yes, the
    dispatcher says no — which is why the switch is gone."""
    import core.auth
    from src import tool_execution as te
    from src.agent_tools import ToolBlock

    monkeypatch.setattr(core.auth, "AuthManager", lambda *a, **k: auth)
    _workstation(False)
    for tool, content in (("bash", "echo hi"), ("python", "print(1)"), ("read_file", "{}")):
        _, r = asyncio.run(te.execute_tool_block(
            ToolBlock(tool, content), session_id="s1", owner="bob",
            security_context=te.NO_TOOL_SECURITY_CONTEXT))
        assert r["exit_code"] == 1, r
        assert r["error"].startswith(f"Tool '{tool}' is restricted to admin users"), r


# ── the composer: the Shell switch follows `shell` ──────────────────────────

UI_VIS_JS = ROOT / "static" / "js" / "ui_visibility.js"


@NODE
def test_the_composer_offers_the_shell_switch_to_whoever_has_a_shell(auth, tmp_path):
    """`P23-03`: the rule is the `shell` row of `TOOL_VISIBILITY` now — the one
    table every door reads — so it is driven there, fed the real route's JSON."""
    cases = {}
    for on in (False, True):
        _workstation(on)
        for who in ("boss", "ann", "bob"):
            cases[f"{who}-{'on' if on else 'off'}"] = _status(auth, who)
    cases["old-server-admin"] = {"privileges": {"can_use_bash": True}}
    cases["old-server-user"] = {"privileges": {"can_use_bash": False}}
    entry = tmp_path / "shell.mjs"
    entry.write_text(textwrap.dedent(f"""
        const {{ toolOff }} = await import({json.dumps(UI_VIS_JS.as_uri())});
        const cases = {json.dumps(cases)};
        const out = {{}};
        for (const [k, d] of Object.entries(cases)) {{
          out[k] = toolOff('shell', {{ privileges: d.privileges || null, shell: d.shell || null }}) === 'person';
        }}
        console.log(JSON.stringify(out));
    """))
    import subprocess
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {
        "boss-off": False, "ann-off": True, "bob-off": True,
        "boss-on": False, "ann-on": False, "bob-on": True,
        "old-server-admin": False, "old-server-user": True,
    }


def _auth_status_callback() -> str:
    """The body of the `.then(d => { … })` that applies `/api/auth/status` in
    `static/app.js`, braces balanced with strings and comments skipped — the
    one place the person's column of the table is handed its answer."""
    src = APP_JS.read_text(encoding="utf-8")
    code = js_code(src)
    at = src.index("fetch(`${API_BASE}/api/auth/status`")
    assert code[at:at + 6] == "fetch(", "the anchor is in a comment or a string"
    then = code.index(".then(d => {", at)
    brace = then + len(".then(d => ")
    return js_function("function _cb(d) " + src[brace:], "function _cb")


def test_the_composer_hides_the_switch_on_that_answer_and_nothing_else():
    """The decision above is the one the page makes: inside the status
    callback the server's `shell` answer is handed to the table's applier, and
    the privilege is not consulted there (`Law 20`, option 2 — scoped first)."""
    body = js_code(_auth_status_callback())
    assert "window._isAdmin" in body, "cut the wrong callback"
    assert re.search(r"applyToolVisibility\(\s*\{[^}]*shell:\s*d\.shell", body, re.S)
    assert not re.search(r"\.can_use_bash\b", body)


# ── Settings → Users ────────────────────────────────────────────────────────

def _users_case(users_payload: dict) -> str:
    src = ADMIN_JS.read_text(encoding="utf-8")
    parts = [
        "import { installDom, Node } from './dom.js';",
        "const document = installDom();",
        esc_source(),
        "const uiModule = { esc, showError: () => {}, styledPrompt: async () => null,"
        " styledConfirm: async () => false };",
        "function chevronIcon() { return '<svg></svg>'; }",
        "function el(id) { return document.getElementById(id); }",
        js_binding(src, "PRIV_LABELS") + ";",
        js_binding(src, "NON_ADMIN_RETIRED_PRIVS") + ";",
        # `P23-03`: each switch names the Tools entry it hides, read from the
        # one table.
        f"import {{ toolsHiddenBy, hidesLine }} from {json.dumps(UI_VIS_JS.as_uri())};",
        "function _hidesLine(which) " + js_function(src, "function _hidesLine"),
        "async function loadUsers() " + js_function(src, "async function loadUsers"),
        f"const PAYLOAD = {json.dumps(users_payload)};",
        "globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => PAYLOAD });",
        "const list = document.body.appendChild(new Node('div'));",
        "list.setAttribute('id', 'adm-userList');",
        "await loadUsers();",
        "const out = {};",
        "for (const row of list.children) {",
        "  const panel = row.querySelector('.admin-priv-panel');",
        "  const name = (row.children[0]._html.match(/admin-user-name\">([^<]*)</) || [])[1];",
        "  out[name] = panel ? panel._html : null;",
        "}",
        "console.log(JSON.stringify(out));",
    ]
    return "\n".join(parts)


def _features(panel_html: str) -> list:
    """The Features block, in order: ('switch', key) or ('sentence', text)."""
    block = panel_html.split(">Limits<", 1)[0]
    items = []
    for m in re.finditer(r'data-priv="([^"]+)"|<div class="admin-toggle-sub"[^>]*>([^<]*)</div>', block):
        items.append(("switch", m.group(1)) if m.group(1)
                     else ("sentence", html.unescape(m.group(2))))
    return items


@NODE
def test_users_offers_no_shell_switch_and_says_where_the_shell_is(auth, tmp_path):
    from routes.auth_routes import SESSION_COOKIE
    c = _client(auth)
    c.cookies.set(SESSION_COOKIE, auth.create_session_trusted("boss"))
    r = c.get("/api/auth/users")
    assert r.status_code == 200, r.text
    (tmp_path / "dom.js").write_text(_DOM)
    panels = _run(tmp_path, "", _users_case(r.json()))

    assert panels["boss"] is None, "an admin has no privilege panel, as before"
    for who in ("ann", "bob"):
        items = _features(panels[who])
        assert ("switch", "can_use_bash") not in items, who
        keys = [k for kind, k in items]
        assert items[keys.index("can_use_browser") + 1] == ("sentence", SENTENCE), items
        assert items[keys.index("can_use_browser") + 2] == ("switch", "can_use_workstation"), items
        assert [k for kind, k in items if kind == "switch"] == [
            "can_use_agent", "can_use_browser", "can_use_workstation", "can_use_documents",
            "can_use_research", "can_generate_images", "can_manage_memory"]
