# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B732` — `admin.js` stops reporting six different failures in the class it
uses for "nothing here".

`static/js/admin.js` wrote `<div class="admin-empty">` for *"Access denied"*,
*"No users found"*, *"Failed to load tools"*, *"No tools found"* and *"No
directories indexed"*, and `static/index.html` used the same class for five
*"Loading..."* placeholders — an administrator who had lost their session and
one with an empty list saw the same grey sentence, and neither was told what to
do next. The lists now draw through `P9-07`'s one shape (`ui.renderEmptyState`):
signed out, not an administrator, failed with the server's words, and empty —
four answers, each with its way on.

Driven: the real `admin.js` under node in the admin-panel harness
(`tests/test_the_admin_panels_that_never_rendered.py`), with `/api/auth/users`
answering each way. The row's `Verify:` is the 403 case.
"""
from pathlib import Path

from test_the_admin_panels_that_never_rendered import (  # noqa: F401
    _admin, admin_sandbox,
)

ROOT = Path(__file__).resolve().parents[1]


def _users_answer(status, body):
    import json
    return """
    mockAdminFetch((url) => {
      if (url.includes('/api/auth/users')) return res(%d, %s);
      if (url.includes('/api/personal')) return res(%d, %s);
      return res(200, {});
    });
    const { emptyStates } = await import('./ui.js');
    adminModule._initData();
    await tick();
    const users = emptyStates.filter(e => e.host === 'adm-userList');
    const rag = emptyStates.filter(e => e.host === 'adm-ragDirList');
    """ % (status, json.dumps(body), status, json.dumps(body))


def _drawn(sandbox, status, body):  # noqa: F811
    return _admin(sandbox, _users_answer(status, body) + """
        const pick = (e) => e && { kind: e.kind, title: e.spec.title, message: e.spec.message || '',
                                   reason: e.spec.reason || '', retry: !!e.spec.onRetry,
                                   action: e.spec.action ? e.spec.action.label : null };
        console.log(JSON.stringify({
          users: pick(users[users.length - 1]), rag: pick(rag[rag.length - 1]),
          html: html('adm-userList'),
        }));
    """)


def test_a_revoked_admin_is_told_they_are_not_an_administrator(admin_sandbox):  # noqa: F811
    """The row's `Verify:`. Not "No users found", not "Access denied"."""
    out = _drawn(admin_sandbox, 403, {"detail": "Admin only"})
    users = out["users"]
    assert users["kind"] == "error"
    assert "not signed in as an administrator" in users["title"]
    assert users["action"], "the state says what to do next"
    assert "No users" not in out["html"] and "No accounts" not in out["html"]
    # The same 403 on the knowledge index is not "No directories indexed" either.
    assert out["rag"]["kind"] == "error" and "administrator" in out["rag"]["title"]


def test_a_lost_session_says_so_and_offers_the_sign_in(admin_sandbox):  # noqa: F811
    out = _drawn(admin_sandbox, 401, {"error": "Not authenticated"})
    assert out["users"]["kind"] == "error"
    assert "signed out" in out["users"]["title"]
    assert out["users"]["action"] == "Sign in"


def test_a_failure_carries_the_servers_words_and_a_retry(admin_sandbox):  # noqa: F811
    out = _drawn(admin_sandbox, 500, {"detail": "auth.json could not be read"})
    assert out["users"]["kind"] == "error"
    assert out["users"]["reason"] == "auth.json could not be read"
    assert out["users"]["retry"] is True


def test_an_empty_list_is_empty_and_says_what_to_add(admin_sandbox):  # noqa: F811
    out = _drawn(admin_sandbox, 200, {"users": [], "directories": [], "files": []})
    assert out["users"]["kind"] == "empty"
    assert out["users"]["message"]
    assert out["rag"]["kind"] == "empty" and out["rag"]["message"]
    assert out["users"]["retry"] is False, "Try again over an empty shelf is the other lie"


def test_the_page_no_longer_says_loading_in_the_nothing_here_class():
    """Absence anywhere in the page is the claim (`Law 20`'s one exception)."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div class="admin-empty">Loading...</div>' not in html
