# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B542` and `B441` — what answers before a sign-in is a method on a path.

`B542`. `_is_auth_exempt(path)` took the path alone, and `AuthMiddleware` asks
it first. `/api/auth/features` and `/api/auth/settings` are listed so the
pre-login page can read feature flags and keybinds — and the POST on each path
shared the exemption: one rewrites the feature toggles, the other every app
setting, credentials included. Only each handler's own admin check stood in
front of an unauthenticated write. The adversary (`Law 17`): anyone who can
reach the port, the day a refactor of either handler drops that check.

`B441`. `/api/ready` was written as an orchestrator's readiness probe and
answered 401 to one. It is exempt for GET now, and a caller with no session is
told `ready` and nothing else.

Driven through the real app booted out of process (`tests/helpers/gated_app.py`),
and the exemption is asked of the app's **routing table**, not its list: every
route, every method it serves, through the real `_is_auth_exempt`.
"""
import pytest

from tests.helpers.gated_app import gated_app_probe

#: The writes that must answer to somebody with no session, and why. The sign-in
#: doors are how a person gets one; the webhook's path is its own credential
#: (`AUTH_EXEMPT_PATTERNS`, checked by its handler). Nothing else may be here.
SIGN_IN_DOORS = {
    "POST /api/auth/setup", "POST /api/auth/signup",
    "POST /api/auth/login", "POST /api/auth/logout",
}
WEBHOOK = "/api/tasks/{task_id}/webhook/{token}"

_PROBE = r'''
import re
from starlette.routing import Mount

READS = {"GET", "HEAD", "OPTIONS"}

def every_route(node, seen):
    # This FastAPI keeps an included router nested (`_IncludedRouter`, its
    # content on `original_router`) rather than flattening it into
    # `app.routes`; `.pantheon/check-unreachable.py` walks it the same way.
    for route in getattr(node, "routes", None) or []:
        if id(route) in seen or isinstance(route, Mount):
            continue
        seen.add(id(route))
        if getattr(route, "methods", None):
            yield route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from every_route(inner, seen)

walked = list(every_route(app_module.app, set()))
exempt_writes = []
for route in walked:
    template = route.path
    concrete = re.sub(r"\{[^}]+\}", "x", template)
    for method in route.methods:
        if method not in READS and app_module._is_auth_exempt(concrete, method):
            exempt_writes.append(f"{method} {template}")
RESULT["exempt_writes"] = sorted(exempt_writes)
RESULT["routes_walked"] = len(walked)

def status(c, method, path, **kw):
    return c.request(method, path, follow_redirects=False, **kw).status_code

anon, member, admin = client(None), client(MEMBER), client(ADMIN)
RESULT["anonymous"] = {
    "POST /api/auth/settings": status(anon, "POST", "/api/auth/settings", json={"tts_voice": "x"}),
    "POST /api/auth/features": status(anon, "POST", "/api/auth/features", json={}),
    "GET /api/auth/settings": status(anon, "GET", "/api/auth/settings"),
    "GET /api/auth/features": status(anon, "GET", "/api/auth/features"),
}
RESULT["member"] = {
    "POST /api/auth/settings": status(member, "POST", "/api/auth/settings", json={}),
    "POST /api/auth/features": status(member, "POST", "/api/auth/features", json={}),
}
RESULT["admin"] = {
    "POST /api/auth/features": status(admin, "POST", "/api/auth/features", json={}),
}

# `B441`.
r = anon.get("/api/ready")
RESULT["ready_anonymous"] = {"status": r.status_code, "body": r.json()}
r = admin.get("/api/ready")
RESULT["ready_admin"] = {"status": r.status_code, "keys": sorted(r.json())}
import src.readiness as readiness
readiness.check_readiness = lambda: {
    "ready": False, "version": "x", "timestamp": "t",
    "checks": {"database": {"ok": False, "error": "could not connect to server at db.internal:5432"},
               "data_dir": {"ok": True, "path": "/srv/pantheon/data"}}}
r = anon.get("/api/ready")
RESULT["not_ready_anonymous"] = {"status": r.status_code, "body": r.json()}
'''


@pytest.fixture(scope="module")
def answered(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("exempt-methods"), _PROBE)


def test_the_premise_holds(answered):
    premise = answered["premise"]
    assert premise["auth_enabled"] and premise["admin_is_admin"]
    assert not premise["member_is_admin"]
    assert answered["routes_walked"] > 100, "the walk found too few routes to mean anything"


def test_no_exempt_route_writes_but_the_sign_in_doors(answered):
    """The row's `Verify:` — walked over the real routing table."""
    unexpected = [w for w in answered["exempt_writes"]
                  if w not in SIGN_IN_DOORS and not w.endswith(WEBHOOK)]
    assert unexpected == [], (
        f"{unexpected} answer a write with no session. An exemption names the "
        "methods it covers in app.py's AUTH_EXEMPT_EXACT; a write on a path listed "
        "for its read must meet the middleware (B542).")
    # And not vacuously: the sign-in doors are found by the same walk.
    assert SIGN_IN_DOORS <= set(answered["exempt_writes"])


def test_the_two_writes_need_a_session_and_the_reads_do_not(answered):
    anon = answered["anonymous"]
    assert anon["POST /api/auth/settings"] == 401
    assert anon["POST /api/auth/features"] == 401
    # The pre-login page still reads both.
    assert anon["GET /api/auth/settings"] == 200
    assert anon["GET /api/auth/features"] == 200


def test_a_signed_in_member_is_refused_and_an_admin_is_answered(answered):
    assert answered["member"] == {"POST /api/auth/settings": 403, "POST /api/auth/features": 403}
    assert answered["admin"]["POST /api/auth/features"] == 200


def test_the_readiness_probe_answers_without_a_session(answered):
    """`B441`: 200 when whole, the verdict and nothing else."""
    assert answered["ready_anonymous"] == {"status": 200, "body": {"ready": True}}
    # Signed in, the whole report.
    assert answered["ready_admin"]["status"] == 200
    assert {"ready", "checks", "version"} <= set(answered["ready_admin"]["keys"])


def test_a_broken_instance_answers_503_and_says_nothing_about_why(answered):
    """The 503 the probe is built to return is reachable now — and a stranger
    is not handed the database's own error text or the data directory's path."""
    assert answered["not_ready_anonymous"] == {"status": 503, "body": {"ready": False}}
