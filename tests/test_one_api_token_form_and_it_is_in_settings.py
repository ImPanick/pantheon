# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1524` — the admin API-token form was a second, unreachable token form.

`initTokenForm`, `loadTokens` and `_TOKEN_SCOPES` in `static/js/admin.js`
returned on `adm-token*` ids no template renders — `check-wiring.py` declared
all eight absent by design — while Settings → MCP & Integrations mints, lists,
renames, re-scopes and revokes tokens (`B1193`, `settings.js` `showTokenForm`).
It also kept its own copy of the scope catalogue, which the Settings form reads
from the server (`GET /api/tokens/profiles`). Deleted, as `B902` deleted the
admin MCP form.

The deletion is a whole-file absence (`Law 20`'s one allowed grep); the rest is
the checker's own declaration table, imported, and the Settings form's
scope, cut out with `js_function`.
"""
import importlib.util
import re
from pathlib import Path

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "static" / "js" / "admin.js"
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
CHECKER = ROOT / ".pantheon" / "check-wiring.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_wiring_b1524", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_admin_module_has_no_token_form():
    admin = ADMIN_JS.read_text(encoding="utf-8")
    for name in ("function initTokenForm", "function loadTokens", "const _TOKEN_SCOPES",
                 "function _renderTokenScopeRows"):
        assert name not in admin, f"{name} is back in admin.js"
    # A lookup is a quoted id; the comment that says why the form went names
    # the ids unquoted (`Law 20`: the shape, not the word).
    assert not re.search(r"""['"]adm-token""", admin), "an adm-token id is looked up again"


def test_the_wiring_checker_declares_no_token_form_absent():
    declared = {i for entry in _checker().ABSENT_BY_DESIGN for i in entry["ids"]}
    assert not {i for i in declared if i.startswith("adm-token")}, \
        "ids of a deleted form are still declared absent by design"


def test_settings_is_where_a_token_is_made_and_it_asks_the_server_what_one_may_do():
    src = SETTINGS_JS.read_text(encoding="utf-8")
    form = js_function(src, "async function showTokenForm")
    assert "fetch('/api/tokens/profiles'" in form, "the scopes come from the server's list"
    assert "fetch('/api/tokens', { method: 'POST'" in form
