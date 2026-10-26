# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed in: the one way a test in this tree is a person (`D-2026-10-07-02` §2).

The owner, verbatim: *"there is always authentication. What's toggleable is
registration. We keep it this way."* Until 2026-10-07 a test that wanted "the
owner of this box" set `AUTH_ENABLED=false` (or patched `auth_disabled` to
answer yes), and every gate waved its nobody through as an admin. That door is
gone from the product, and no test-only switch replaces it — a test is signed
in, as somebody, the way the product signs a person in:

  * :func:`people` — a real `core.auth.AuthManager` over its own `auth.json`,
    with an admin (``ADMIN``, the first account — which is what a single-user
    install's owner is) and a member who is not an admin (``MEMBER``), each
    holding a real session token from the same manager;
  * :func:`signed_in` — that manager registered as the process's shared one
    (`core.auth.register_shared_auth_manager`, which `app.py` calls with the
    app's own), so every policy check that asks `shared_auth_manager()` —
    `owner_is_admin`, `owner_has_admin_task_privileges`,
    `workstation_access.may_use` — answers about these people;
  * :func:`as_person` — a bare app built from routers is given the manager and
    the one thing `AuthMiddleware` adds once a cookie validates: the person on
    ``request.state.current_user``. A dependency override, not a backdoor: the
    stamp is the middleware's output, and the routes' own gates still ask.

`tests/helpers/gated_app.py` is the out-of-process half — the real app, the
real middleware, cookies — and takes its names and password from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

ADMIN = "ada"
MEMBER = "bob"
PASSWORD = "correct-horse-battery"


def people(directory, *, admin: str = ADMIN, members: Iterable[str] = (MEMBER,)):
    """A real `AuthManager` over ``directory``/auth.json with ``admin`` as the
    first account (an admin, as `/api/auth/setup` makes it) and each of
    ``members`` an account that is not. ``manager.tokens`` maps each name to a
    session token the manager itself issued."""
    from core.auth import AuthManager

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    manager = AuthManager(auth_path=str(root / "auth.json"))
    assert manager.setup(admin, PASSWORD), "setup refused: the directory already holds accounts"
    for name in members:
        assert manager.create_user(name, PASSWORD), name
    manager.tokens = {name: manager.create_session_trusted(name)
                      for name in (admin, *members)}
    return manager


def signed_in(monkeypatch, directory, *, admin: str = ADMIN,
              members: Iterable[str] = (MEMBER,)):
    """:func:`people`, registered as the process's shared auth manager for the
    length of the test (restored by ``monkeypatch``). Returns the manager."""
    import core.auth

    manager = people(directory, admin=admin, members=members)
    monkeypatch.setattr(core.auth, "_SHARED_AUTH_MANAGER", manager)
    return manager


def as_person(app, name: Optional[str], *, auth_manager=None):
    """Give a bare app built from routers what the real app gives each route:
    ``app.state.auth_manager``, and ``request.state.current_user`` set to
    ``name`` — what `AuthMiddleware` stamps once a session cookie validates.
    ``None`` stamps nobody: a request with no person on it, which every gate
    now refuses. Returns ``app``."""
    if auth_manager is not None:
        app.state.auth_manager = auth_manager

    @app.middleware("http")
    async def _the_person_signed_in(request, call_next):
        if name is not None:
            request.state.current_user = name
            request.state.api_token = False
        return await call_next(request)

    return app


class PersonRequest:
    """A request a route helper is handed directly, carrying a signed-in
    person as `AuthMiddleware` leaves one: ``state.current_user`` and an app
    holding the auth manager. For helpers called without an ASGI app
    (`require_user`, `require_admin`, a route function's ``request``)."""

    def __init__(self, name: Optional[str], auth_manager=None, *, host: str = "203.0.113.9"):
        from types import SimpleNamespace

        self.state = SimpleNamespace(current_user=name, api_token=False)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=auth_manager))
        self.headers = {}
        self.cookies = {}
        self.client = SimpleNamespace(host=host)


def sign_in(app_module, client, name: str = ADMIN):
    """In a probe that booted the real app (`import app as app_module`): make
    ``name`` the install's first account — its admin, through the app's own
    auth manager, as `/api/auth/setup` would — unless the install already has
    accounts, and put that person's session cookie on ``client``. Every page
    and route the probe then asks for is answered as it is answered to the
    admin of a single-user install. Returns ``client``."""
    from routes.auth_routes import SESSION_COOKIE

    auth = app_module.auth_manager
    if not auth.is_configured:
        assert auth.setup(name, PASSWORD)
    client.cookies.set(SESSION_COOKIE, auth.create_session_trusted(name))
    return client


def through_the_middleware(request, auth_manager):
    """Give a hand-built request what `AuthMiddleware` gives a real one before
    any route sees it: the person its session cookie names, on
    ``request.state.current_user``, and the app's auth manager on
    ``request.app.state.auth_manager``. Returns ``request``.

    `B543`. The user-administration routes in `routes/auth_routes.py` read the
    session cookie themselves until 2026-10-26 (`_get_current_user` +
    `is_admin`), so their tests handed them a bare object with a cookie on it.
    They ask `core.middleware.require_admin` now, which reads what the
    middleware stamped — so the stamp is added here, by the middleware's own
    rule (``get_username_for_token`` of the session cookie), and each test
    keeps the cookie and the manager it was written with. A stand-in manager
    with no ``is_configured`` is given one: a manager that names an admin is
    one on an install that has accounts."""
    from types import SimpleNamespace

    from routes.auth_routes import SESSION_COOKIE

    cookies = getattr(request, "cookies", None) or {}
    user = auth_manager.get_username_for_token(cookies.get(SESSION_COOKIE))
    state = getattr(request, "state", None)
    if state is None:
        state = SimpleNamespace()
        request.state = state
    state.current_user = user
    state.api_token = False
    app = getattr(request, "app", None)
    if app is None:
        app = SimpleNamespace(state=SimpleNamespace())
        request.app = app
    if getattr(app, "state", None) is None:
        app.state = SimpleNamespace()
    app.state.auth_manager = auth_manager
    if not hasattr(auth_manager, "is_configured"):
        try:
            auth_manager.is_configured = True
        except (AttributeError, TypeError):
            pass
    return request


def with_session_stamp(app, auth_manager):
    """:func:`through_the_middleware` for a bare app built from routers and
    served for real: the app holds ``auth_manager``, and each request is
    stamped with the person its session cookie names — `AuthMiddleware`'s rule,
    and nothing else of it (no 401, no exemptions). For tests that drive a
    router over HTTP with cookies, as the browser does (`B543`). Returns ``app``."""
    from routes.auth_routes import SESSION_COOKIE

    app.state.auth_manager = auth_manager

    @app.middleware("http")
    async def _stamp_the_session(request, call_next):
        request.state.current_user = auth_manager.get_username_for_token(
            request.cookies.get(SESSION_COOKIE))
        request.state.api_token = False
        return await call_next(request)

    return app


def stamped_endpoint(endpoint, auth_manager):
    """A route function that stamps, as :func:`through_the_middleware` does,
    whichever argument is the request (the one carrying ``cookies``) before it
    is called. For tests that call a router's endpoints directly with a
    hand-built request (`B543`)."""
    def call(*args, **kwargs):
        args = tuple(through_the_middleware(a, auth_manager) if hasattr(a, "cookies") else a
                     for a in args)
        if "request" in kwargs:
            kwargs["request"] = through_the_middleware(kwargs["request"], auth_manager)
        return endpoint(*args, **kwargs)
    return call
