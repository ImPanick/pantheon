# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B931` — the agent's door and the person's door store the same number.

Two doors write the settings store: `POST /api/auth/settings` (the Settings
page) and the agent's `manage_settings`. The route held every whole-number
setting to a range in a table only it could read (`_INT_RANGES`); the tool
coerced with `int()` and stored whatever it got. Measured on the tree before
this row: `set agent_max_rounds -5` stored `-5` — read as 1 by the chat route,
shown as -5 by the settings panel — and `set skill_audit_hour 25` stored the
hour `H16` clamps because `next_daily_run` waits for it forever.

Now the table is `src.settings.int_setting_ranges()` and both doors validate
through `clamp_int_setting`; the tool says when the number it stored is not the
one it was given. Driven, not read (`Law 20`): the real route and the real tool
against stores of their own, compared value by value.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import routes.auth_routes as auth_routes
import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from test_the_agent_raises_its_own_limits_for_the_run import _manage, _set, stored  # noqa: F401,E402


def _route_post(monkeypatch, store):
    """The real `POST /api/auth/settings`, as an admin, against `store`."""

    class _AuthManager:
        def get_username_for_token(self, token):
            return "admin" if token == "admin-session" else None

        def is_admin(self, username):
            return username == "admin"

    class _Request(SimpleNamespace):
        def __init__(self, body):
            super().__init__(cookies={auth_routes.SESSION_COOKIE: "admin-session"},
                             _body=body)

        async def json(self):
            return self._body

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: dict(store))
    monkeypatch.setattr(auth_routes, "_save_settings",
                        lambda updated: (store.clear(), store.update(updated)))
    router = auth_routes.setup_auth_routes(_AuthManager())
    post = next(r.endpoint for r in router.routes
                if r.path == "/api/auth/settings" and "POST" in r.methods)
    return lambda body: asyncio.run(post(_Request(body)))


# ── the row's Verify ────────────────────────────────────────────────────────

def test_a_step_limit_below_the_range_is_stored_as_1_and_the_reply_says_so(stored):
    settings = stored({})
    result = _manage(_set("agent_max_rounds", -5))
    assert settings.load_settings()["agent_max_rounds"] == 1
    assert result["response"] == (
        "Set agent_max_rounds = 1. -5 is outside the range Settings allows "
        "(1 to 200), so it was clamped to 1, as Settings does.")


@pytest.mark.parametrize("key,asked,kept,low,high", [
    # `H16`: an hour that never comes.
    ("skill_audit_hour", 25, 23, "0", "23"),
    # `P15-08`: a floor below zero that the scheduler would read as its default.
    ("min_task_interval_minutes", -5, 0, "0", "1,440"),
    # `P3-21`: a ceiling past any context window.
    ("local_inference_max_tokens", 10**12, 10_000_000, "0", "10,000,000"),
], ids=["audit-hour", "task-floor", "token-ceiling"])
def test_the_other_numbers_the_settings_page_clamps_are_clamped_here_too(
        stored, key, asked, kept, low, high):
    settings = stored({})
    result = _manage(_set(key, asked))
    assert settings.load_settings()[key] == kept
    assert result["response"] == (
        f"Set {key} = {kept}. {asked:,} is outside the range Settings allows "
        f"({low} to {high}), so it was clamped to {kept:,}, as Settings does.")


def test_a_number_inside_the_range_is_stored_as_given_and_nothing_more_is_said(stored):
    settings = stored({})
    assert _manage(_set("skill_audit_hour", 3))["response"] == "Set skill_audit_hour = 3."
    assert settings.load_settings()["skill_audit_hour"] == 3


# ── one validator: what the agent stores is what the Settings page stores ───

def _probes(low, high):
    return sorted({low - 1, low, high, high + 1, high * 10 + 7, -10**9})


def test_every_ranged_setting_is_stored_the_same_through_both_doors(monkeypatch, stored):
    """For every key the settings route holds to a range and the agent may
    write, and for values below, at and above each bound, the number the
    agent's door stores equals the number the person's door stores."""
    from src.settings import DEFAULT_SETTINGS, int_setting_ranges

    # Both loop caps where no number is a raise, before every probe: a raise
    # is the run's and is never saved (`P7-12`), which is not this row.
    start = {"agent_max_rounds": 200, "agent_max_tool_calls": 0}
    route_store = dict(DEFAULT_SETTINGS)
    post = _route_post(monkeypatch, route_store)

    compared = 0
    for key, (low, high) in int_setting_ranges().items():
        for value in _probes(low, high):
            settings = stored(start)
            result = _manage(_set(key, value))
            if not result.get("response", "").startswith("Set "):
                # `_SELF_RESTRAINT_KEYS`: refused outright, nothing stored.
                assert key == "approval_timeout_seconds", (key, result)
                continue
            post({key: value})
            agent_stored = settings.load_settings()[key]
            assert agent_stored == route_store[key], (key, value)
            assert low <= agent_stored <= high, (key, value, agent_stored)
            compared += 1
    assert compared >= 60, f"only {compared} comparisons ran"


def test_a_value_that_is_not_a_whole_number_is_refused_by_both_doors(monkeypatch, stored):
    from fastapi import HTTPException
    from src.settings import DEFAULT_SETTINGS

    settings = stored({})
    result = _manage(_set("skill_audit_batch", "lots"))
    assert result["exit_code"] == 1 and "isn't a valid value" in result["error"]
    assert settings.load_settings()["skill_audit_batch"] == DEFAULT_SETTINGS["skill_audit_batch"]
    with pytest.raises(HTTPException) as refused:
        _route_post(monkeypatch, dict(DEFAULT_SETTINGS))({"skill_audit_batch": "lots"})
    assert refused.value.status_code == 400
