# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Apollo knows (settled call: memory lives in Pantheon, in Brain).

Every line is stated (the person said it) or inferred (Apollo noticed it). An
inferred line carries its evidence and stays a hunch, a proposed Brain entry,
until the person confirms it; saying the same thing in their own words
confirms it too. Forget deletes, and an edit by the person makes a line theirs.
"""
import pytest

from src.apollo import knows
from src.apollo.errors import ApolloRefused


@pytest.fixture(autouse=True)
def brain(tmp_path, monkeypatch):
    from src.memory import MemoryManager
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path)))


def test_a_stated_line_is_kept_as_the_persons_rule():
    line = knows.remember("ada", "Never book me before 10", category="rule")
    assert line["basis"] == "stated" and line["by_apollo"] is True
    assert "Never book me before 10" in knows.stated_rules("ada")


def test_an_inferred_line_needs_its_evidence():
    with pytest.raises(ApolloRefused):
        knows.remember("ada", "Prefers aisle seats", basis="inferred")
    line = knows.remember("ada", "Prefers aisle seats", basis="inferred",
                          evidence="picked the aisle on the last two flights")
    assert line["basis"] == "inferred"
    assert line["evidence"] == "picked the aisle on the last two flights"


def test_a_hunch_is_not_a_rule_until_confirmed():
    line = knows.remember("ada", "Prefers aisle seats", basis="inferred", evidence="two flights",
                          category="preference")
    assert knows.stated_rules("ada") == []
    assert [h["id"] for h in knows.open_hunches("ada")] == [line["id"]]
    assert knows.confirm("ada", line["id"])["basis"] == "stated"
    assert knows.open_hunches("ada") == []
    assert knows.stated_rules("ada") == ["Prefers aisle seats"]


def test_saying_it_yourself_confirms_the_hunch():
    hunch = knows.remember("ada", "Prefers aisle seats", basis="inferred", evidence="two flights")
    said = knows.remember("ada", "prefers   aisle seats")
    assert said["id"] == hunch["id"] and said["basis"] == "stated"


def test_an_edit_by_the_person_makes_the_line_stated():
    hunch = knows.remember("ada", "Works late on Fridays", basis="inferred", evidence="calendar")
    edited = knows.edit("ada", hunch["id"], "Keeps Friday afternoons clear")
    assert edited["text"] == "Keeps Friday afternoons clear" and edited["basis"] == "stated"


def test_forget_deletes_and_another_person_cannot_reach_the_line():
    line = knows.remember("ada", "Has a dog named Pip")
    with pytest.raises(ApolloRefused) as refused:
        knows.forget("bob", line["id"])
    assert refused.value.status == 404
    assert knows.forget("ada", line["id"]) is True
    assert knows.what_apollo_knows("ada") == []
