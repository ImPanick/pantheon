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
    `owner_is_admin_or_single_user`, `owner_has_admin_task_privileges`,
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
