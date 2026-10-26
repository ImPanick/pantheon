# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deleting a user must invalidate the bearer-token cache.

delete_user removes the user's ApiToken rows from the DB, but the bearer-auth
middleware in app.py serves from an in-memory prefix->token cache that only
rebuilds when flagged dirty (app.state.invalidate_token_cache). If the admin
delete route does not flag it, a deleted user's already-cached token keeps
authenticating until some unrelated token op or a process restart clears the
cache. The DELETE /api/auth/users handler now calls the invalidator on a
successful delete (and only then), so the next bearer request rebuilds the
cache from the DB, where the rows are already gone, and the token is rejected.
"""
import asyncio
import types

from routes.auth_routes import setup_auth_routes, DeleteUserRequest


def _handler(router):
    for route in router.routes:
        if getattr(route, "path", "") == "/api/auth/users" and "DELETE" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("DELETE /api/auth/users handler not found")


def _fake_request(invalidations, manager):
    # `B543`: the route asks `require_admin`, which reads what `AuthMiddleware`
    # stamps, so the request carries the stamp — and the manager on the app.
    from tests.helpers.signed_in import through_the_middleware
    state = types.SimpleNamespace(invalidate_token_cache=lambda: invalidations.append(True))
    app = types.SimpleNamespace(state=state)
    return through_the_middleware(types.SimpleNamespace(cookies={"_dummy": "x"}, app=app), manager)


def _auth_manager(delete_result):
    return types.SimpleNamespace(
        get_username_for_token=lambda token: "admin",
        is_admin=lambda user: True,
        delete_user=lambda username, requesting_user: delete_result,
    )


def _auth_manager_raising():
    def _delete_user(_username, _requesting_user):
        raise RuntimeError("auth save failed after token purge")

    return types.SimpleNamespace(
        get_username_for_token=lambda token: "admin",
        is_admin=lambda user: True,
        delete_user=_delete_user,
    )


def test_successful_delete_invalidates_cache():
    invalidations = []
    manager = _auth_manager(delete_result=True)
    router = setup_auth_routes(manager)
    handler = _handler(router)
    result = asyncio.run(handler(DeleteUserRequest(username="bob"), _fake_request(invalidations, manager)))
    assert result == {"ok": True}
    assert invalidations == [True], "successful delete must flag the token cache stale"


def test_refused_delete_does_not_invalidate_cache():
    invalidations = []
    manager = _auth_manager(delete_result=False)
    router = setup_auth_routes(manager)
    handler = _handler(router)
    try:
        asyncio.run(handler(DeleteUserRequest(username="admin"), _fake_request(invalidations, manager)))
        raised = False
    except Exception:
        raised = True
    assert raised, "a refused delete should raise (HTTP 400)"
    assert invalidations == [], "a refused delete must not touch the token cache"


def test_delete_exception_invalidates_cache_for_partial_token_purge():
    invalidations = []
    manager = _auth_manager_raising()
    router = setup_auth_routes(manager)
    handler = _handler(router)
    try:
        asyncio.run(handler(DeleteUserRequest(username="bob"), _fake_request(invalidations, manager)))
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "delete_user exception should still propagate"
    assert invalidations == [True], "partial token purge must dirty the bearer cache"
