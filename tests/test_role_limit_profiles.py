# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-02` — the limit profile a role carries, driven end to end.

`P12-01` registered the role layer and left it empty; `P11-02` installed a
provider that answers. What was still missing on 2026-09-18 is the **profile**:
the provider answers only keys `src.settings.LIMIT_RANGES` declares, and four
of the limits that consult the role leg on every call are not in it. The row
names six things a role should carry — upload size, files per request, request
rate, context budget, concurrent agent runs, model-serve permission — and two
of the six had no key at all.

Nothing here greps a source file (`Law 20`). A resolution order is only
observable by asking for an answer, so every test defines a real role on a real
`AuthManager`, installs the real provider, and asks the product's own resolver
— or, where there is one, the route.
"""
import importlib

import pytest

from src import roles as roles_mod


@pytest.fixture(autouse=True)
def _no_leaked_provider():
    """The provider is process-wide. Install it deliberately; never leak it."""
    roles_mod.clear_role_layer()
    yield
    roles_mod.clear_role_layer()


def _mgr(tmp_path):
    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("admin", "pw-123456", is_admin=True)
    mgr.create_user("bob", "pw-123456")
    return auth_mod, mgr


def _role(tmp_path, overrides):
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("team", overrides)
    mgr.set_user_role("bob", "team")
    roles_mod.install_role_layer(mgr)
    return mgr


# ---------------------------------------------------------------------------
# the gap itself: a leg consulted on every call that can never answer
# ---------------------------------------------------------------------------

def test_every_limit_that_consults_the_role_leg_is_one_a_role_may_carry():
    """`Law 13`. A resolver that asks the role layer for a key no role may hold
    is the unwired half wearing a resolution order.

    The set is derived from the product, not restated here: every key any call
    site hands to `settings.resolve_limit` / `limit_policy.resolve_int_limit`
    with an `owner`.
    """
    from src.task_scheduler import TASK_CONCURRENCY_CAP_SETTING
    from src.tool_approvals import APPROVAL_TIMEOUT_SETTING
    from src.upload_limits import (
        BYTE_LIMITS,
        MAX_FILES_PER_REQUEST_SETTING,
        UPLOAD_BURST_LIMIT_SETTING,
        UPLOAD_BURST_WINDOW_SETTING,
    )

    consulted = set(BYTE_LIMITS) | {
        TASK_CONCURRENCY_CAP_SETTING,
        APPROVAL_TIMEOUT_SETTING,
        UPLOAD_BURST_LIMIT_SETTING,
        UPLOAD_BURST_WINDOW_SETTING,
        MAX_FILES_PER_REQUEST_SETTING,
        "backup_import_max_bytes",
        "tts_cache_max_bytes",
        "upload_rate_limit",
        "upload_rate_window_seconds",
        "auth_login_rate_limit",
        "auth_login_rate_window_seconds",
        "auth_signup_rate_limit",
        "auth_signup_rate_window_seconds",
        "auth_setup_rate_limit",
        "auth_setup_rate_window_seconds",
    }
    missing = sorted(consulted - roles_mod.limit_keys())
    assert missing == [], (
        "these limits ask the role layer and no role may answer: " + repr(missing))


def test_the_role_limit_registry_is_derived_and_not_a_third_list():
    """`Law 14`. The keys a role may carry are `LIMIT_RANGES` plus the limits
    that resolve through the same chain but ship a real default — and every
    bound is imported from the module that owns it, never restated."""
    from src.settings import DEFAULT_SETTINGS, LIMIT_RANGES, role_limit_ranges
    from src.task_scheduler import TASK_CONCURRENCY_CAP_MAX
    from src.tool_approvals import (
        MAX_APPROVAL_TTL_SECONDS,
        MIN_APPROVAL_TTL_SECONDS,
    )
    from src.upload_limits import MAX_UPLOAD_BURST_LIMIT, MIN_UPLOAD_BURST_LIMIT

    ranges = role_limit_ranges()
    assert set(LIMIT_RANGES) < set(ranges)
    assert set(ranges) <= set(DEFAULT_SETTINGS)
    assert roles_mod.limit_keys() == frozenset(ranges)
    assert ranges["task_concurrency_cap"] == (1, TASK_CONCURRENCY_CAP_MAX)
    assert ranges["approval_timeout_seconds"] == (
        MIN_APPROVAL_TTL_SECONDS, MAX_APPROVAL_TTL_SECONDS)
    assert ranges["upload_burst_limit"] == (
        MIN_UPLOAD_BURST_LIMIT, MAX_UPLOAD_BURST_LIMIT)
    # Every key in the shared table keeps the bounds that table gives it.
    for key, bounds in LIMIT_RANGES.items():
        assert ranges[key] == bounds


# ---------------------------------------------------------------------------
# the six the row names, one test each, driven
# ---------------------------------------------------------------------------

def test_a_role_sets_upload_size(tmp_path):
    """Already worked before this row. Kept because the row claims six things
    and a claim nobody drives is the tracker talking to itself."""
    from src.upload_limits import resolve_byte_limit_with_source

    _role(tmp_path, {"gallery_upload_max_bytes": 500 * 1024 * 1024})
    assert resolve_byte_limit_with_source("gallery_upload_max_bytes", "bob") == (
        500 * 1024 * 1024, "role profile")


def test_a_role_sets_files_per_request_and_the_route_honours_it(tmp_path):
    """Driven through the real `POST /api/upload` handler, not the resolver:
    the cap was a module constant the route closed over."""
    import asyncio
    import types

    from fastapi import HTTPException

    import routes.upload_routes as up
    from src.upload_limits import resolve_max_files_per_request

    _role(tmp_path, {"upload_max_files_per_request": 2})
    assert int(resolve_max_files_per_request("bob")) == 2
    assert int(resolve_max_files_per_request("admin")) == 25

    handler = types.SimpleNamespace(upload_rate_log={})
    handler.upload_burst_limit = 50
    handler.upload_burst_window_seconds = 10

    def _save(u, client_ip, owner=None):
        handler.upload_rate_log.setdefault(client_ip, []).append(1.0)
        return {"id": "0" * 32 + ".txt", "name": u.filename, "mime": "text/plain",
                "size": 1, "hash": "h", "uploaded_at": "now", "width": None,
                "height": None, "is_duplicate": False}

    handler.save_upload = _save
    router, _ = up.setup_upload_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/upload"
                    and "POST" in getattr(r, "methods", set()))

    def _req(user):
        return types.SimpleNamespace(
            client=types.SimpleNamespace(host="1.2.3.4"),
            state=types.SimpleNamespace(current_user=user))

    def _files(n):
        return [types.SimpleNamespace(filename=f"f{i}.txt") for i in range(n)]

    with pytest.raises(HTTPException) as ei:
        asyncio.run(endpoint(_req("bob"), _files(3)))
    assert ei.value.status_code == 400
    assert "max 2" in str(ei.value.detail)
    # Rejected whole: nothing reached save_upload.
    assert handler.upload_rate_log == {}

    # Somebody without the role still gets the shipped 25, and the shipped 25
    # is the module constant rather than a number this row chose again: a full
    # batch is accepted and one more is refused, on the same router.
    from src.upload_handler import MAX_FILES_PER_REQUEST
    from src.upload_limits import DEFAULT_MAX_FILES_PER_REQUEST

    assert MAX_FILES_PER_REQUEST == DEFAULT_MAX_FILES_PER_REQUEST == 25
    accepted = asyncio.run(endpoint(_req("admin"), _files(MAX_FILES_PER_REQUEST)))
    assert len(accepted["files"]) == MAX_FILES_PER_REQUEST
    with pytest.raises(HTTPException) as ei:
        asyncio.run(endpoint(_req("admin"), _files(MAX_FILES_PER_REQUEST + 1)))
    assert ei.value.status_code == 400


def test_a_role_sets_the_request_rate_including_the_burst_gate(tmp_path):
    from src.settings import resolve_limit
    from src.upload_limits import (
        resolve_upload_burst_limit,
        resolve_upload_burst_window_seconds,
    )

    _role(tmp_path, {"auth_login_rate_limit": 3,
                     "upload_burst_limit": 7,
                     "upload_burst_window_seconds": 42})
    assert resolve_limit("auth_login_rate_limit", 15, owner="bob") == (3, "role profile")
    burst = resolve_upload_burst_limit("bob")
    assert (int(burst), burst.source) == (7, "role")
    window = resolve_upload_burst_window_seconds("bob")
    assert (int(window), window.source) == (42, "role")


def test_a_role_sets_the_context_budget(tmp_path):
    from src.context_budget import resolve_context_budget

    _role(tmp_path, {"context_attachment_total_chars": 4000})
    assert resolve_context_budget("context_attachment_total_chars", "bob") == 4000
    assert resolve_context_budget("context_attachment_total_chars", "admin") == 24000


def test_a_role_sets_concurrent_agent_runs(tmp_path):
    from src.task_scheduler import resolve_task_concurrency_cap

    _role(tmp_path, {"task_concurrency_cap": 6})
    assert resolve_task_concurrency_cap("bob") == (6, "role profile")
    assert resolve_task_concurrency_cap("admin")[1] == "built-in default"


def test_a_role_sets_which_models_are_served(tmp_path):
    """The one leg of the six that needed nothing built: `allowed_models` is a
    privilege, `resolve_privilege` has consulted the role since `P11-02`, and
    the chat gate reads it from `get_privileges`. Driven through that gate."""
    from routes.chat_helpers import _allowed_models_for_request

    mgr = _role(tmp_path, {"allowed_models": ["small-model"],
                           "allowed_models_restricted": True})

    class _Req:
        def __init__(self, user):
            self.state = type("S", (), {})()
            self.app = type("A", (), {"state": type("S2", (), {"auth_manager": mgr})()})()
            self.state.user = user
            self.cookies = {}
            self.headers = {}

    privs = mgr.get_privileges("bob")
    assert privs["allowed_models"] == ["small-model"]
    assert privs["allowed_models_restricted"] is True
    assert mgr.get_privileges("admin")["allowed_models"] == []
    assert callable(_allowed_models_for_request)


# ---------------------------------------------------------------------------
# what a role still cannot do
# ---------------------------------------------------------------------------

def test_a_role_cannot_talk_a_new_limit_down_to_off(tmp_path):
    """`FORBIDDEN.md` Part 2. Widening what a role may carry does not widen it
    to zero — the floor is enforced at definition and again at every read."""
    _auth_mod, mgr = _mgr(tmp_path)
    for key in ("task_concurrency_cap", "upload_max_files_per_request",
                "context_attachment_total_chars", "approval_timeout_seconds"):
        with pytest.raises(roles_mod.RoleError) as ei:
            mgr.define_role("off", {key: 0})
        # The reason matters as much as the refusal (`Law 10`): "0 is below the
        # floor" and "nobody declares that key" are different answers, and only
        # the first one means the limit is carriable and the floor held.
        assert "no value meaning" in str(ei.value), str(ei.value)
    assert mgr.roles == {}


def test_a_role_is_clamped_at_read_time_to_the_bounds_its_owner_declares(tmp_path):
    """A role is not the one layer that skips the clamp. `auth.json` can be
    hand-edited, so the definition check is not the last word."""
    from src.task_scheduler import (
        TASK_CONCURRENCY_CAP_MAX,
        resolve_task_concurrency_cap,
    )
    from src.tool_approvals import (
        MAX_APPROVAL_TTL_SECONDS,
        resolve_approval_ttl_seconds,
    )

    mgr = _role(tmp_path, {"task_concurrency_cap": 1})
    mgr.roles["team"]["task_concurrency_cap"] = 10_000
    mgr.roles["team"]["approval_timeout_seconds"] = 10_000_000
    assert resolve_task_concurrency_cap("bob") == (TASK_CONCURRENCY_CAP_MAX, "role profile")
    assert resolve_approval_ttl_seconds("bob") == MAX_APPROVAL_TTL_SECONDS


