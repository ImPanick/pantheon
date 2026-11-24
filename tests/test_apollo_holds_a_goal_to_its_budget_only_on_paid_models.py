# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's goal budgets (settled call 9, his words: *"Local LLM's have no cap"*).

A person sets a goal's budget in tokens, under the admin's cap. The budget and
the cap hold only when the run is on an API-billed model; a local server is
never charged and never stopped. A goal over its budget on a paid model does
not start: it asks.
"""
from types import SimpleNamespace

import pytest

from src.apollo import budget as B
from src.apollo.errors import ApolloRefused

LOCAL = "http://127.0.0.1:11434/v1/chat/completions"
PAID = "https://api.example-llm.com/v1/chat/completions"


def goal(budget=None, spent=0):
    return SimpleNamespace(title="Plan the trip", budget_tokens=budget, spent_tokens=spent)


def test_a_local_server_is_not_billed_and_a_hosted_api_is():
    assert B.billed(LOCAL) is False
    assert B.billed(PAID) is True
    assert B.billed("") is False


def test_a_person_cannot_set_a_budget_over_the_admins_cap():
    with pytest.raises(ApolloRefused) as refused:
        B.check_person_budget(5_000, cap=1_000)
    assert refused.value.sentence.endswith(".")
    assert B.check_person_budget(800, cap=1_000) == 800
    assert B.check_person_budget(None, cap=1_000) is None


def test_with_no_budget_of_their_own_a_goal_is_held_to_the_admins_cap():
    assert B.limit_for(goal(), cap=1_000) == 1_000
    assert B.limit_for(goal(budget=300), cap=1_000) == 300


def test_a_goal_over_its_budget_stops_on_a_paid_model_and_runs_on_a_local_one():
    spent = goal(budget=300, spent=300)
    ok, why = B.may_spend(spent, PAID, cap=1_000)
    assert ok is False and why.endswith(".")
    ok, why = B.may_spend(spent, LOCAL, cap=1_000)
    assert ok is True


def test_only_a_paid_run_is_charged_to_the_goal():
    g = goal(budget=1_000)
    B.charge(g, 250, LOCAL)
    assert g.spent_tokens == 0
    B.charge(g, 250, PAID)
    assert g.spent_tokens == 250


def test_the_admins_cap_is_read_from_settings_and_held_to_its_range():
    assert B.admin_cap({B.CAP_KEY: 42}) == 42
    assert B.admin_cap({B.CAP_KEY: -5}) == 0
    assert B.admin_cap({B.CAP_KEY: "nonsense"}) == B.CAP_DEFAULT


def test_the_cap_is_an_install_setting_with_its_range():
    from src.settings import DEFAULT_SETTINGS, int_setting_ranges
    assert DEFAULT_SETTINGS[B.CAP_KEY] == B.CAP_DEFAULT
    assert int_setting_ranges()[B.CAP_KEY] == B.CAP_RANGE
