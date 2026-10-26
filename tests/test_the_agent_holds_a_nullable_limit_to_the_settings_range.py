# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1027` — `manage_settings` stored the nullable limits unvalidated.

`B931` gave the agent's door the settings route's whole-number ranges. The
route's OTHER table — the nullable limits `P12-01` moved to
`src.settings.LIMIT_RANGES` (byte caps, context budgets, files per request, the
skills catalogue) — the agent's door still did not read. Their shipped value is
`None`, so `_coerce` returned whatever the model wrote. Measured on the tree
before this row:

    set chat_upload_max_bytes abc        stored "abc", replied "Set … = abc."
    set context_skill_index_chars 5      stored 5, under the route's floor of 200
    set upload_max_files_per_request -3  stored -3, which the resolver clamps to 1

The route's rule — blank or null unsets, a boolean is refused, an integer is
held to the range — is `src.settings.clamp_limit_setting` now, read by both
doors. Driven, not read (`Law 20`): the real tool and the real route against
stores of their own, compared value by value.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import src.agent_tools  # noqa: F401
from test_both_doors_hold_a_setting_to_one_range import _route_post  # noqa: E402
from test_the_agent_raises_its_own_limits_for_the_run import (  # noqa: E402,F401
    _manage, _set, stored,
)


# ── the row's Verify ────────────────────────────────────────────────────────

def test_a_byte_cap_that_is_not_a_number_is_refused(stored):
    settings = stored({})
    result = _manage(_set("chat_upload_max_bytes", "abc"))
    assert result["exit_code"] == 1
    assert "chat_upload_max_bytes must be an integer" in result["error"]
    assert "Nothing changed" in result["error"]
    assert settings.load_settings().get("chat_upload_max_bytes") is None


def test_a_catalogue_budget_under_its_floor_is_stored_at_the_floor_and_said(stored):
    settings = stored({})
    result = _manage(_set("context_skill_index_chars", 5))
    assert settings.load_settings()["context_skill_index_chars"] == 200
    assert result["response"] == (
        "Set context_skill_index_chars = 200. 5 is outside the range Settings "
        "allows (200 to 2,000,000), so it was clamped to 200, as Settings does.")


def test_files_per_request_below_one_is_stored_as_one_and_said(stored):
    settings = stored({})
    result = _manage(_set("upload_max_files_per_request", -3))
    assert settings.load_settings()["upload_max_files_per_request"] == 1
    assert "clamped to 1" in result["response"]


def test_a_boolean_is_not_a_limit_of_one(stored):
    settings = stored({})
    result = _manage(_set("chat_upload_max_bytes", True))
    assert result["exit_code"] == 1
    assert settings.load_settings().get("chat_upload_max_bytes") is None


def test_blank_unsets_it_and_says_who_decides_now(stored):
    settings = stored({"chat_upload_max_bytes": 1024})
    result = _manage(_set("chat_upload_max_bytes", ""))
    assert settings.load_settings()["chat_upload_max_bytes"] is None
    assert result["response"] == (
        "Cleared chat_upload_max_bytes: the environment or the built-in default "
        "decides it now.")


# ── one rule: what the agent stores is what the Settings route stores ───────

def _probes(low, high):
    return [low - 1, low, high, high + 1, -10**9, str(low + 1), "", None, "abc", True]


def test_every_nullable_limit_is_stored_the_same_through_both_doors(monkeypatch, stored):
    from src.agent_tools.admin_tools import _SELF_RESTRAINT_KEYS
    from src.settings import DEFAULT_SETTINGS, LIMIT_RANGES

    route_store = dict(DEFAULT_SETTINGS)
    post = _route_post(monkeypatch, route_store)
    compared = refused = 0
    for key, (low, high) in LIMIT_RANGES.items():
        if key in _SELF_RESTRAINT_KEYS:
            continue        # the auth throttles: refused to the agent outright
        for value in _probes(low, high):
            settings = stored({})
            result = _manage(_set(key, value))
            try:
                post({key: value})
            except HTTPException:
                assert result.get("exit_code") == 1, (key, value, result)
                refused += 1
                continue
            assert result.get("exit_code") == 0, (key, value, result)
            assert settings.load_settings()[key] == route_store[key], (key, value)
            compared += 1
    assert compared >= 100 and refused >= 30, (compared, refused)
