# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B540` — the speech cache is the instance's, and only an admin clears it.

`POST /api/tts/clear-cache` called `tts_service.clear_cache()` with no
privilege check of any kind; the handler took no `Request`, so it could not
have made one. Measured 2026-10-02 against the real app with
`AUTH_ENABLED=true`: a signed-in non-admin got **200** and the cache directory
was emptied. The cache is one directory for everybody — a clip is keyed by
text, provider, model, voice and speed, never by person — and the identical
act on uploads, `POST /api/upload/cleanup`, is `require_admin`.

**The adversary** (`Law 17`) is a second account on the box: somebody the
owner let sign in, who is not the owner. Re-synthesis is the whole cost, and
the row says so; what is not acceptable on a public repository is two answers
to one question in the same tree.

**Why admin and not owner-scoped.** There is no owner to scope to: nothing
records whose clip is whose. And the one caller in the product clears the
cache straight after changing model, voice or speed (`saveAndClearCache` in
`static/js/settings.js`), which is a `POST /api/auth/settings` — already an
admin write. Whoever may change the voice may throw away the clips made with
the old one.

**What a single-user owner keeps.** Everything. An install with auth on has
exactly one account until the owner makes another, and the first account is
the admin; an install with auth off has no accounts, and `require_admin`
returns when auth is off. Both are driven below.

Driven, not grepped (`Law 20`): the real app, the real middleware, the real
`require_admin`, three callers — and the cache file on disk is the evidence,
because a gate that answered 403 after clearing would pass a status check.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.tts_routes import setup_tts_routes
from tests.helpers.gated_app import gated_app_probe

_PROBE = r'''
svc = app_module.tts_service
cleared = []
_real_clear = svc.clear_cache

def _counting_clear():
    cleared.append(1)
    return _real_clear()

# The route closes over this instance and looks `clear_cache` up per call, so
# the count is what the route actually did — not what a status code implies.
svc.clear_cache = _counting_clear

for label, who in CALLERS:
    clip = svc.cache_dir / "b540-probe.mp3"
    clip.write_bytes(b"ID3 a clip somebody else made")
    before = len(cleared)
    res = client(who).post("/api/tts/clear-cache", follow_redirects=False)
    RESULT[label] = {
        "status": res.status_code,
        "body": res.text[:200],
        "clip_survived": clip.exists(),
        "clear_cache_calls": len(cleared) - before,
    }
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b540"), _PROBE)


def test_the_probe_is_gated_and_the_accounts_are_what_they_say(probe):
    """The premise. With auth off every route opens and nothing here means anything."""
    assert probe["premise"] == {
        "auth_enabled": True, "localhost_bypass": False,
        "admin_is_admin": True, "member_is_admin": False,
    }, probe["premise"]


def test_a_signed_in_non_admin_cannot_clear_the_instance_s_cache(probe):
    """`B540`'s `Verify:`. Fails on the tree before the fix: 200, and the clip
    another person's request had made was gone."""
    row = probe["member"]
    assert row["status"] == 403, row
    assert "Admin only" in row["body"], row
    assert row["clip_survived"] is True, row
    assert row["clear_cache_calls"] == 0, row


def test_a_caller_with_no_session_is_stopped_before_the_route(probe):
    """The middleware's half, unchanged — and the clip is still there."""
    row = probe["anonymous"]
    assert row["status"] == 401, row
    assert row["clip_survived"] is True, row
    assert row["clear_cache_calls"] == 0, row


def test_the_admin_still_clears_it(probe):
    """`Law 1`: the capability moved to the person who owns it, it did not go.
    The owner of a single-user install is this account."""
    row = probe["admin"]
    assert row["status"] == 200, row
    assert row["clip_survived"] is False, row
    assert row["clear_cache_calls"] == 1, row


class _Service:
    def __init__(self):
        self.cleared = 0

    def clear_cache(self):
        self.cleared += 1


def test_a_no_login_install_still_clears_it(monkeypatch):
    """The other single-user shape: `AUTH_ENABLED=false`, no accounts at all,
    no middleware. The route is driven over HTTP with nothing in front of it,
    which is exactly what that install runs."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    service = _Service()
    app = FastAPI()
    app.include_router(setup_tts_routes(service))
    res = TestClient(app).post("/api/tts/clear-cache")
    assert res.status_code == 200, res.text
    assert service.cleared == 1


def test_the_gate_is_the_handler_s_own_and_not_only_the_middleware_s(monkeypatch):
    """With auth on and no middleware in front — the shape of any app that
    mounts this router without `app.py` — the handler refuses by itself. A fix
    that leaned on the middleware would pass the three-caller probe for the
    anonymous caller and fail here."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    service = _Service()
    app = FastAPI()
    app.include_router(setup_tts_routes(service))
    res = TestClient(app).post("/api/tts/clear-cache")
    assert res.status_code == 403, res.text
    assert service.cleared == 0
