# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1198` — a user row's Rename and Remove sit behind its ⋯, not beside
Privileges at one size.

`SET-U-7`'s other half. `P23-03` made the row wrap and gave it a *Privileges* /
*Hide privileges* button; *Rename* and *Remove* were still two buttons on the
row (`static/js/admin.js`). They live behind a per-row ⋯ menu now — the pattern
the endpoint cards already use (`#adm-epLocalMoreMenu`) — and Privileges stays
on the row.

Driven: the real `loadUsers` cut out of `admin.js` (as
`tests/test_the_shell_switch_is_not_offered_to_a_non_admin.py` cuts it) and run
under node against the shim with HTML parsing on, so the row's own markup is
what the code finds; the ⋯ is pressed, and Remove is pressed and posts the
same `DELETE /api/auth/users` it always did.
"""
import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_binding, js_function

ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "static" / "js" / "admin.js"
UI_VIS_JS = ROOT / "static" / "js" / "ui_visibility.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

USERS = {"users": [
    {"username": "boss", "is_admin": True, "role": None, "privileges": {}},
    {"username": "ann", "is_admin": False, "role": None, "privileges": {}},
]}


def _script() -> str:
    src = ADMIN_JS.read_text(encoding="utf-8")
    return "\n".join([
        "import { installDom, installHtmlParsing, Node } from './dom.js';",
        "const document = installDom();",
        "installHtmlParsing();",
        "// The shim's click is a bare event; the row's handlers stop propagation.",
        "{ const E0 = globalThis.Event; globalThis.Event = class extends E0 {",
        "  stopPropagation() {} preventDefault() {} }; }",
        esc_source(),
        "const deleted = [];",
        "const uiModule = { esc, showError: () => {}, styledPrompt: async () => null,"
        " styledConfirm: async () => true, renderEmptyState: () => {} };",
        "const dismissed = [];",
        "function bindMenuDismiss(menu, onClose) { dismissed.push(menu); return onClose; }",
        "const topPortalZ = () => 10000;",
        "function chevronIcon() { return '<svg></svg>'; }",
        "function el(id) { return document.getElementById(id); }",
        js_binding(src, "PRIV_LABELS") + ";",
        js_binding(src, "NON_ADMIN_RETIRED_PRIVS") + ";",
        js_binding(src, "PRIV_TAKES") + ";",
        f"import {{ toolsHiddenBy, hidesLine }} from {json.dumps(UI_VIS_JS.as_uri())};",
        "function _hidesLine(which) " + js_function(src, "function _hidesLine"),
        "async function loadUsers() " + js_function(src, "async function loadUsers"),
        f"const PAYLOAD = {json.dumps(USERS)};",
        "globalThis.fetch = async (url, opts = {}) => {",
        "  if ((opts.method || 'GET') === 'DELETE') deleted.push(JSON.parse(opts.body));",
        "  return { ok: true, status: 200, json: async () => PAYLOAD };",
        "};",
        "const list = document.body.appendChild(new Node('div'));",
        "list.setAttribute('id', 'adm-userList');",
        "await loadUsers();",
        "const tick = () => new Promise((r) => setTimeout(r, 0));",
        "const out = {};",
        "for (const row of [...list.children]) {",
        "  const name = row.querySelector('.admin-user-name').textContent;",
        "  const more = row.querySelector('[data-adm-user-more]');",
        "  const menu = row.querySelector('.admin-user-more-menu');",
        "  // Buttons on the row itself: everything not inside the ⋯ menu.",
        "  const onRow = [...row.querySelectorAll('button')]",
        "    .filter((b) => !menu || !menu.contains(b))",
        "    .map((b) => b.textContent.trim() || b.getAttribute('aria-label'));",
        "  const inMenu = menu ? [...menu.querySelectorAll('[role=\"menuitem\"]')].map((b) => b.textContent.trim()) : [];",
        "  const before = { shown: menu && menu.style.display, expanded: more && more.getAttribute('aria-expanded') };",
        "  if (more) more.click();",
        "  const after = { shown: menu && menu.style.display, expanded: more && more.getAttribute('aria-expanded') };",
        "  if (more) more.click();",
        "  const again = { shown: menu && menu.style.display, expanded: more && more.getAttribute('aria-expanded') };",
        "  out[name] = { onRow, inMenu, before, after, again };",
        "}",
        "// Remove, from ann's menu, works as the row button did.",
        "const annRow = [...list.children].find((r) => r.querySelector('.admin-user-name').textContent === 'ann');",
        "annRow.querySelector('[data-adm-del-user]').click();",
        "await tick(); await tick();",
        "out.deleted = deleted;",
        "out.dismissBound = dismissed.length;",
        "console.log(JSON.stringify(out));",
    ])


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("usermenu")
    (tmp / "dom.js").write_text(_DOM)
    return _run(tmp, "", _script())


def test_privileges_stays_on_the_row_and_rename_and_remove_do_not(drawn):
    ann = drawn["ann"]
    assert "Privileges" in ann["onRow"]
    assert "Rename" not in ann["onRow"] and "Remove" not in ann["onRow"]
    assert "More for ann" in ann["onRow"], "the ⋯ is on the row, named for the person"
    assert ann["inMenu"] == ["Rename", "Remove"]


def test_an_admin_row_offers_rename_and_no_remove(drawn):
    """As before: an admin is never removed from this list."""
    assert drawn["boss"]["inMenu"] == ["Rename"]


def test_the_menu_opens_and_closes_from_its_button(drawn):
    ann = drawn["ann"]
    assert ann["before"] == {"shown": "none", "expanded": "false"}
    assert ann["after"] == {"shown": "flex", "expanded": "true"}
    assert ann["again"] == {"shown": "none", "expanded": "false"}
    assert drawn["dismissBound"] >= 1, "Esc and an outside click close it (`bindMenuDismiss`)"


def test_remove_from_the_menu_deletes_as_the_row_button_did(drawn):
    assert drawn["deleted"] == [{"username": "ann"}]
