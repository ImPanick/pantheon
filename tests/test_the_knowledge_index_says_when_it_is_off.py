# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1187` — Settings › System › Knowledge index says RAG is off.

`P23-02` gave `GET /api/personal` `healthy` and `reason` (the sentence
`src/rag_singleton.rag_unavailable_reason` writes — *"RAG is off: the embedding
model is not downloaded — Settings › System › Download models from the
internet."*) and the Brain's RAG tab draws it. The Settings card read only
`directories` and `files`, and *Reload Index* said *"Index reloaded: 0
documents"* over a dead index, because `POST /api/personal/reload` answered
`ok: true` whatever the state.

Driven twice: the real personal router behind the real `require_admin` with a
signed-in admin, and the real `admin.js` under node in the admin-panel harness.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.personal_routes as personal_routes
from tests.helpers.signed_in import ADMIN, as_person, people
from test_the_admin_panels_that_never_rendered import (  # noqa: F401
    _admin, admin_sandbox,
)

SENTENCE = ("RAG is off: the embedding model is not downloaded — "
            "Settings › System › Download models from the internet.")


class _Docs:
    def __init__(self):
        self.index = [{"name": "a.md"}, {"name": "b.md"}]
        self.refreshed = 0

    def refresh_index(self):
        self.refreshed += 1


@pytest.fixture
def reload_as_admin(tmp_path, monkeypatch):
    def ask(reason):
        monkeypatch.setattr(personal_routes, "rag_unavailable_reason", lambda: reason)
        docs = _Docs()
        app = as_person(FastAPI(), ADMIN, auth_manager=people(tmp_path / reason[:3].strip()))
        app.include_router(personal_routes.setup_personal_routes(docs, None, True))
        r = TestClient(app).post("/api/personal/reload")
        return r.status_code, r.json(), docs.refreshed
    return ask


def test_a_reload_over_an_index_that_is_off_does_not_claim_success(reload_as_admin):
    status, body, refreshed = reload_as_admin(SENTENCE)
    assert status == 200
    assert body["ok"] is False
    assert body["reason"] == SENTENCE
    assert body["count"] == 2 and refreshed == 1, "the files are still re-read"


def test_a_reload_over_a_live_index_says_ok(reload_as_admin):
    status, body, _ = reload_as_admin("")
    assert (status, body["ok"], body["reason"]) == (200, True, "")


def _store(personal, reload_answer):
    import json
    return """
    mockAdminFetch((url) => {
      if (url.includes('/api/personal/reload')) return res(200, %s);
      if (url.includes('/api/personal')) return res(200, %s);
      if (url.includes('/api/auth/users')) return res(200, { users: [] });
      return res(200, {});
    });
    """ % (json.dumps(reload_answer), json.dumps(personal))


def test_the_card_says_why_the_index_is_off_and_the_reload_does_not_claim_it(admin_sandbox):  # noqa: F811
    out = _admin(admin_sandbox, _store(
        {"directories": [], "files": [], "healthy": False, "reason": SENTENCE},
        {"ok": False, "count": 0, "reason": SENTENCE},
    ) + """
        adminModule._initData();
        await tick();
        const health = byId('adm-ragHealth');
        const shown = { hidden: health.hidden, text: health.textContent };
        fire(byId('adm-ragReloadBtn'), 'click');
        await tick();
        console.log(JSON.stringify({ shown, status: byId('adm-ragStatus').textContent }));
    """)
    assert out["shown"] == {"hidden": False, "text": SENTENCE}
    assert "Index reloaded" not in out["status"]
    assert SENTENCE in out["status"]


def test_a_live_index_shows_no_warning_and_reports_the_reload(admin_sandbox):  # noqa: F811
    out = _admin(admin_sandbox, _store(
        {"directories": ["/srv/handbook"], "files": [], "healthy": True, "reason": ""},
        {"ok": True, "count": 34, "reason": ""},
    ) + """
        adminModule._initData();
        await tick();
        const health = byId('adm-ragHealth');
        const shown = { hidden: health.hidden, text: health.textContent };
        fire(byId('adm-ragReloadBtn'), 'click');
        await tick();
        console.log(JSON.stringify({ shown, status: byId('adm-ragStatus').textContent }));
    """)
    assert out["shown"] == {"hidden": True, "text": ""}
    assert out["status"] == "Index reloaded: 34 documents"
