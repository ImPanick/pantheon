# SPDX-License-Identifier: AGPL-3.0-or-later
"""B53 — five route modules shared one router, and five test files worked around it.

`setup_*_routes()` is called once in production, so nothing was broken. What it
looked like from inside the suite was different: five modules kept
`router = APIRouter(...)` at module level, decorated it inside the setup
function and returned it, so **a second call registered a second copy of every
route on the same router**. FastAPI dispatches to the first match, so the second
call's handlers — and the manager they close over — were silently ignored while
the call appeared to succeed.

Five test files carried a workaround. Three sliced the tail
(`before = len(router.routes)` … `router.routes[before:]`), two swapped in a
fresh `APIRouter` before each test, one of them with the comment *"Module-level
router accumulates routes across setup calls; reset it."* Nobody fixed the
cause, and the suite's green quietly depended on collection order:
`test_session_list_owner_scope` passed alone and failed after
`test_archived_sessions_model_filter`, because the `/api/sessions` route it
picked was the earlier file's, closing over the earlier file's mock.

Each router is built inside its setup function now. One call, one router.
"""
import importlib
import inspect

import pytest

# module path -> setup function name
MODULES = {
    "routes.compare.compare_routes": "setup_compare_routes",
    "routes.mcp.mcp_routes": "setup_mcp_routes",
    "routes.session_routes": "setup_session_routes",
    "routes.upload_routes": "setup_upload_routes",
    "routes.webhook.webhook_routes": "setup_webhook_routes",
}


@pytest.mark.parametrize("mod_path,fn_name", sorted(MODULES.items()))
def test_the_router_is_not_a_module_global(mod_path, fn_name):
    """A module-level `router` is the whole defect: it is the only way two
    calls can share one."""
    mod = importlib.import_module(mod_path)
    assert not hasattr(mod, "router"), (
        f"{mod_path} has a module-level `router` again — two calls to "
        f"{fn_name} will register every route twice on it"
    )


@pytest.mark.parametrize("mod_path,fn_name", sorted(MODULES.items()))
def test_the_setup_function_builds_one(mod_path, fn_name):
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, fn_name)
    src = inspect.getsource(fn)
    assert "router = APIRouter(" in src, (
        f"{fn_name} does not build its own router; where does the one it "
        "returns come from?"
    )


def test_two_calls_do_not_share_routes():
    """The behaviour, not the source. Two routers, and neither carries the
    other's routes — which is what makes a second `setup_*` call mean what it
    says."""
    from unittest.mock import MagicMock

    import routes.session_routes as sr

    first = sr.setup_session_routes(MagicMock(), {})
    second = sr.setup_session_routes(MagicMock(), {})
    assert first is not second
    assert len(first.routes) == len(second.routes)
    assert len(first.routes) > 5, "the router came back empty"

    def _keys(router):
        # (path, methods), not path alone: `/api/session/{sid}` is registered
        # for GET and for DELETE, which is one route each and not a duplicate.
        return [(r.path, frozenset(r.methods)) for r in router.routes]

    # No duplicates within a router: that is what accumulation looked like.
    assert len(_keys(first)) == len(set(_keys(first))), sorted(
        str(k) for k in _keys(first))
    assert set(_keys(first)) == set(_keys(second))
    assert not (set(id(r) for r in first.routes) & set(id(r) for r in second.routes))


def test_the_second_call_is_the_one_that_answers(monkeypatch, tmp_path):
    """The failure this caused, stated directly: with a shared router, the route
    a caller found for `/api/sessions` was the *first* one registered, so a
    second setup's session manager was never consulted. That is precisely how
    `test_session_list_owner_scope` failed after
    `test_archived_sessions_model_filter` and passed alone."""
    from unittest.mock import MagicMock

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    import core.database as cdb
    import routes.session_routes as sr

    engine = create_engine(f"sqlite:///{tmp_path/'b53.db'}",
                           connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(sr, "SessionLocal",
                        sessionmaker(bind=engine, autoflush=False, autocommit=False))
    monkeypatch.setattr(sr, "effective_user", lambda request: "alice")

    first_manager, second_manager = MagicMock(), MagicMock()
    first_manager.get_sessions_for_user.return_value = {}
    second_manager.get_sessions_for_user.return_value = {}
    sr.setup_session_routes(first_manager, {})
    router = sr.setup_session_routes(second_manager, {})

    endpoint = next(r.endpoint for r in router.routes
                    if r.path == "/api/sessions" and "GET" in r.methods)
    request = MagicMock()
    request.query_params.get.return_value = ""
    endpoint(request=request)
    assert second_manager.get_sessions_for_user.called, (
        "the router returned by the second call reaches the first call's "
        "manager — the routers are still shared"
    )
    assert not first_manager.get_sessions_for_user.called


def test_no_test_needs_to_reset_a_router_any_more():
    """Five files carried a workaround. If one comes back, the cause is back."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent
    offenders = []
    for path in sorted(root.rglob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        text = re.sub(r"(?m)^\s*#.*$", "", path.read_text(encoding="utf-8"))
        if re.search(r'setattr\(\s*\w+\s*,\s*["\']router["\']', text):
            offenders.append(path.name + ": swaps a module's router")
        if re.search(r"before\s*=\s*len\(\s*router\.routes\s*\)", text):
            offenders.append(path.name + ": slices the tail of a shared router")
    assert not offenders, offenders
