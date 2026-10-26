# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B751` — `agent_input_token_budget` was a limit with no role layer.

Named beside `B750` in `P12-04` and `P12-09` as *"the same shape"* and never
filed until `B831`. Measured 2026-10-26: both readers — `src/agent_loop.py`'s
`stream_agent_loop` (the trim) and `src/context_budget.py` (`agent_input_budget`,
which the composer's context meter reads) — read it with a plain
`get_setting("agent_input_token_budget", DEFAULT_BUDGET)`, so a role profile
could not set it and an operator had no way to give one team a bigger window
than another.

Now both ask `context_budget.resolve_agent_input_budget_setting`, on the
`resolve_limit` chain (role → instance → default) `skill_max_injected` and the
six character budgets already use, and the key is in `role_limit_ranges` so a
role may carry it. Driven (`Law 20`): the resolver, the role validator, the
real agent loop (only the model's words scripted) and the real meter route.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.roles as roles_mod
import src.settings as settings
from src.context_budget import (
    AGENT_INPUT_BUDGET_SETTING,
    DEFAULT_BUDGET,
    resolve_agent_input_budget_setting,
)

KEY = AGENT_INPUT_BUDGET_SETTING
ROLE_BUDGET = 32_000


@pytest.fixture(autouse=True)
def _layers(monkeypatch):
    """Every layer answers from the test: no stored settings, no roles."""
    stored: dict = {}
    real = settings.get_setting
    monkeypatch.setattr(settings, "setting_is_explicit",
                        lambda key, **kw: key in stored)
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None: stored[key] if key in stored
                        else real(key, default))
    settings.clear_role_limit_provider()
    yield stored
    settings.clear_role_limit_provider()


def _role_for(owner, value):
    settings.set_role_limit_provider(
        lambda key, who: value if (key == KEY and who == owner) else None)


# ── the resolver: role → instance → default ────────────────────────────────

def test_with_nothing_set_it_is_the_shipped_default():
    got = resolve_agent_input_budget_setting("alice")
    assert (got.value, got.source) == (DEFAULT_BUDGET, "default")


def test_an_instance_setting_answers_for_everyone(_layers):
    _layers[KEY] = 9000
    assert resolve_agent_input_budget_setting("alice").value == 9000
    assert resolve_agent_input_budget_setting("bob").value == 9000


def test_a_role_profiles_value_wins_for_the_people_in_that_role(_layers):
    """The row's `Verify:` — a role profile's value wins."""
    _layers[KEY] = 9000
    _role_for("alice", ROLE_BUDGET)
    alice = resolve_agent_input_budget_setting("alice")
    assert (alice.value, alice.source) == (ROLE_BUDGET, "role")
    assert resolve_agent_input_budget_setting("bob").value == 9000


def test_the_instance_off_switch_survives_and_a_role_cannot_set_it(_layers):
    """0 is the instance setting's documented *no trimming*; the resolver's
    floor of 1 would have turned it into a one-token budget. A role is still
    held to 1 and up, like every limit a role carries."""
    _layers[KEY] = 0
    assert resolve_agent_input_budget_setting("alice").value == 0
    assert roles_mod.validate_overrides({KEY: ROLE_BUDGET}) == {KEY: ROLE_BUDGET}
    with pytest.raises(roles_mod.RoleError):
        roles_mod.validate_overrides({KEY: 0})


def test_a_role_may_carry_it():
    assert KEY in roles_mod.limit_keys()
    assert settings.role_limit_ranges()[KEY][0] == 1


# ── reader 1: the agent loop's trim ─────────────────────────────────────────

def test_the_agent_loop_trims_to_the_roles_budget(monkeypatch):
    from test_the_whole_suite_reaches_the_model import _base, _drive
    import src.context_compactor as compactor

    trimmed_to = []
    real_trim = compactor.trim_for_context

    def spy(messages, budget, **kw):
        trimmed_to.append(budget)
        return real_trim(messages, budget, **kw)

    monkeypatch.setattr(compactor, "trim_for_context", spy)
    _base(monkeypatch)

    _drive(monkeypatch, ["The answer."])
    assert trimmed_to and ROLE_BUDGET not in trimmed_to

    trimmed_to.clear()
    _role_for("local", ROLE_BUDGET)          # `_drive` runs as `local`
    _drive(monkeypatch, ["The answer."])
    assert trimmed_to and set(trimmed_to) == {ROLE_BUDGET}, trimmed_to


# ── reader 2: the composer's context meter ──────────────────────────────────

def test_the_context_meter_reports_the_resolved_number(monkeypatch):
    """The other half of the `Verify:` — the meter says the budget this
    person's runs are trimmed to."""
    import routes.history.history_routes as history_routes
    import src.model_context as model_context
    from test_the_wheel_says_the_window_the_agent_uses import _Manager, _Session
    from src.chat_handler import ChatMessage

    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(history_routes, "effective_user", lambda request: "alice")
    monkeypatch.setattr(model_context, "get_context_length_known",
                        lambda url, model: (128_000, True))
    app = FastAPI()
    history = [ChatMessage("user", "word " * 200), ChatMessage("assistant", "ok")]
    app.include_router(history_routes.setup_history_routes(_Manager(_Session(history))))

    def meter():
        res = TestClient(app).get("/api/session/s-1/context?mode=agent")
        assert res.status_code == 200, res.text
        return res.json()

    assert meter()["agent_budget"] == int(128_000 * 0.85)     # auto, no role
    _role_for("alice", ROLE_BUDGET)
    out = meter()
    assert out["agent_budget"] == ROLE_BUDGET and out["window_tokens"] == ROLE_BUDGET
