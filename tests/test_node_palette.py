# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-22` — the node palette, and the two actions it used to hide.

`BUILTIN_ACTIONS` dispatches 18 actions. `BUILTIN_ACTION_INFO` described 16 of
them, and `/api/tasks/meta/actions` iterated the descriptions — so `run_local`
and `cookbook_serve` ran perfectly well and were never offered by the only
endpoint that says what exists, which is also the one the task form's action
picker is built from. The counts are recomputed here rather than written down
(`Law 8`): a test asserting "18" passes the day somebody adds a nineteenth
action to one map and not the other, which is the defect itself.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import routes.task_routes as task_routes
from src.builtin_actions import (
    BUILTIN_ACTIONS,
    BUILTIN_ACTION_INFO,
    BUILTIN_ACTION_META,
    MODEL_BACKED_ACTIONS,
)
from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS


def _req(user):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _endpoint(method, path):
    router = task_routes.setup_task_routes(MagicMock())
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise RuntimeError(f"{method} {path} not found")


@pytest.fixture()
def auth_off(monkeypatch):
    """No auth configured — the single-user case, where everyone is admin."""
    monkeypatch.setenv("AUTH_ENABLED", "false")


def test_every_dispatchable_action_is_described():
    """The defect, as an equality rather than as two numbers."""
    missing = set(BUILTIN_ACTIONS) - set(BUILTIN_ACTION_META)
    extra = set(BUILTIN_ACTION_META) - set(BUILTIN_ACTIONS)
    assert not missing, f"dispatchable but undescribed, so invisible to the palette: {sorted(missing)}"
    assert not extra, f"described but not dispatchable: {sorted(extra)}"


def test_the_description_map_is_derived_and_not_a_second_copy():
    assert BUILTIN_ACTION_INFO == {
        name: meta["description"] for name, meta in BUILTIN_ACTION_META.items()
    }


def test_model_backed_is_stated_once():
    """It gated the semaphore in one file and drew a badge in another."""
    from src.task_scheduler import TaskScheduler

    assert MODEL_BACKED_ACTIONS == {
        name for name, meta in BUILTIN_ACTION_META.items() if meta.get("model_backed")
    }
    sched = TaskScheduler.__new__(TaskScheduler)
    for name in BUILTIN_ACTIONS:
        assert sched._action_needs_model(name) == (name in MODEL_BACKED_ACTIONS)


@pytest.mark.asyncio
async def test_the_action_listing_offers_every_action_to_an_admin(auth_off):
    """The two that were invisible. This is the endpoint the task form's
    action picker is built from, so this is also the user-facing fix."""
    actions = _endpoint("GET", "/api/tasks/meta/actions")

    names = {a["name"] for a in (await actions(_req(None)))["actions"]}

    assert names == set(BUILTIN_ACTIONS)
    assert {"run_local", "cookbook_serve"} <= names


@pytest.mark.asyncio
async def test_the_listing_carries_the_taxonomy_the_client_used_to_hold(auth_off):
    actions = _endpoint("GET", "/api/tasks/meta/actions")

    out = await actions(_req(None))
    by_name = {a["name"]: a for a in out["actions"]}

    for name, node in by_name.items():
        assert node["category"], f"{name} has no category"
        assert node["icon"], f"{name} has no icon"
        assert isinstance(node["params"], list)
        assert isinstance(node["model_backed"], bool)
        assert node["admin_only"] is (name in ADMIN_ONLY_TASK_ACTIONS)

    # Every category an action claims is in the published order, or the client
    # cannot place it.
    order = out["categories"]
    assert order, "the listing publishes no category order"
    for node in by_name.values():
        assert node["category"] in order

    # The four actions that take something from the prompt say so, and nothing
    # else claims a parameter it is never handed.
    assert by_name["ssh_command"]["params"][0]["name"] == "command"
    assert by_name["run_script"]["params"][0]["name"] == "script"
    assert by_name["run_local"]["params"][0]["name"] == "script"
    assert by_name["cookbook_serve"]["params"][0]["name"] == "command"
    assert by_name["tidy_sessions"]["params"] == []

    assert by_name["summarize_emails"]["model_backed"] is True
    assert by_name["tidy_documents"]["model_backed"] is False

    assert out["default_trigger_count"] == 1


@pytest.mark.asyncio
async def test_the_listing_hides_admin_only_actions_from_a_non_admin(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    import core.auth as core_auth

    class FakeAuthManager:
        is_configured = True

        def is_admin(self, user):
            return user == "admin"

    monkeypatch.setattr(core_auth, "AuthManager", FakeAuthManager)

    actions = _endpoint("GET", "/api/tasks/meta/actions")
    names = {a["name"] for a in (await actions(_req("alice")))["actions"]}

    assert not (names & ADMIN_ONLY_TASK_ACTIONS)
    assert "tidy_sessions" in names


@pytest.mark.asyncio
async def test_the_listing_keeps_the_shape_its_existing_caller_reads(auth_off):
    """`Law 1` — the merge adds keys to this response and takes none away.
    `static/js/tasks.js` builds the action picker from `name` + `description`."""
    actions = _endpoint("GET", "/api/tasks/meta/actions")

    out = await actions(_req(None))
    assert out["actions"], "the picker would be empty"
    for entry in out["actions"]:
        assert entry["description"] == BUILTIN_ACTION_INFO[entry["name"]]


@pytest.mark.asyncio
async def test_the_output_target_route_still_answers(auth_off):
    """Extracting the builder must not change what the third route returns."""
    targets = _endpoint("GET", "/api/tasks/meta/output-targets")

    out = await targets(_req(None))
    assert [t["value"] for t in out["targets"]][:3] == [
        "session", "notification", "email"]
