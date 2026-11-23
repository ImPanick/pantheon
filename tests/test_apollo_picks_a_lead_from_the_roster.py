# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each goal gets a lead agent from the roster (settled call 8).

The pick is the hall's own word matching plus the fit badge for the model the
work would run on. An agent that needs a bigger model is never the lead; the
same goal always gets the same lead; no match is an answer, not a guess.
"""
from types import SimpleNamespace

from src.apollo.lead import pick_lead


def agent(id_, name, tagline, section="Work"):
    a = SimpleNamespace(id=id_, name=name, tagline=tagline, section_label=section)
    a.to_public = lambda: {"section_label": section}
    return a


ROSTER = [
    agent("trip-planner", "Trip Planner", "plans trips, flights and hotels", "Travel"),
    agent("inbox-sorter", "Inbox Sorter", "sorts email and drafts replies", "Email"),
    agent("trip-scout", "Trip Scout", "plans trips on a budget", "Travel"),
]


def fits(badges):
    return lambda a: badges.get(a.id, "not-measured")


def test_the_goals_words_pick_the_agent_that_does_that_work():
    got = pick_lead("ada", "Sort my email and draft replies", agents=ROSTER, fit_of=fits({}))
    assert got["id"] == "inbox-sorter"
    assert got["why"].startswith("Inbox Sorter does this")


def test_on_an_even_match_the_agent_that_runs_well_on_this_model_leads():
    got = pick_lead("ada", "Plan trips to Juneau", agents=ROSTER,
                    fit_of=fits({"trip-scout": "runs-well"}))
    assert got["id"] == "trip-scout" and got["fit"] == "runs-well"


def test_an_agent_that_needs_a_bigger_model_never_leads():
    got = pick_lead("ada", "Plan trips to Juneau", agents=ROSTER,
                    fit_of=fits({"trip-planner": "needs-bigger", "trip-scout": "needs-bigger"}))
    assert got is None


def test_the_same_goal_gets_the_same_lead_every_time():
    picks = {pick_lead("ada", "Plan trips to Juneau", agents=list(order), fit_of=fits({}))["id"]
             for order in (ROSTER, list(reversed(ROSTER)))}
    assert len(picks) == 1


def test_no_match_is_no_lead():
    assert pick_lead("ada", "Tune the piano", agents=ROSTER, fit_of=fits({})) is None
