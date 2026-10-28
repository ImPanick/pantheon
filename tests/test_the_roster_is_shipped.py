# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-23` — wave 2 of the roster ships: 155 more agents on today's tools.

The plan (`D-2026-10-22-01`, the Claude Doc's § *The roster*) lists 207
agents in 26 sections: 18 starters, 156 in wave 2, 33 in wave 3. Wave 2 ships
here but for one — *Audit Log Reviewer* reads Pantheon's own audit log, and no
tool reads it yet, so it waits with wave 3 rather than ship with a runbook that
cannot do its job. The lint (`P24-01`) is the one rule for each file and every
shipped one passes it (`test_an_agent_is_one_file.py`); what is pinned here is
what the lint cannot see, across the whole roster:

  * **the count and the spread** — 173 agents, every one of the 26 sections
    with at least one, the hall's chips all drawn;
  * **nothing acts outward unasked** — no agent allows an effect that leaves
    the install (`external_side_effect`) or cannot be undone (`destructive`),
    and Bills Due declares it never pays (`D-2026-10-22-01` §3);
  * **no wave-2 effect is left to the default** — every effect of every tool a
    wave-2 agent lists is in its table. (Two starters, Morning Brief and Weekly
    Review, list tools that can write and left `write_private` out on purpose:
    an effect a file is silent on asks, and they only read. `P24-27` has them
    say `ask` outright, and `tests/test_an_agent_has_substance.py` holds every
    agent at its bar to a table with nothing left to the default.);
  * **the teams are the plan's fourteen**, every member in the hall.
"""

from __future__ import annotations

import pytest

from src.agents.catalogue import catalogue
from src.agents.manifest import SECTION_IDS
from src.agents.teams import teams

PLAN_TEAMS = {"inbox-zero", "chief-of-staff", "household", "home-lab", "ship-a-website", "code-health",
              "security-watch", "research-desk", "model-lab", "content-studio", "growth", "sales-desk",
              "support-desk", "the-books"}


@pytest.fixture(scope="module")
def hall():
    agents, broken = catalogue(None)
    assert broken == []
    return agents


def test_the_roster_has_its_starters_and_wave_two(hall):
    waves = {}
    for m in hall:
        waves[m.wave] = waves.get(m.wave, 0) + 1
    assert waves == {1: 18, 2: 155}
    assert sum(1 for m in hall if m.starred) == 5


def test_every_section_has_agents(hall):
    assert {m.section for m in hall} == set(SECTION_IDS)


def test_nothing_acts_outward_or_irreversibly_without_asking(hall):
    for m in hall:
        for effect in ("external_side_effect", "destructive", "admin_change"):
            assert m.effects.get(effect, "ask") != "allow", (m.id, effect)
    bills = next(m for m in hall if m.id == "bills-due")
    assert bills.effects["external_side_effect"] == "never"


def test_every_effect_of_a_wave_two_tool_is_in_the_table(hall):
    from src.tool_capabilities import capabilities_for_tool
    for m in (m for m in hall if m.wave == 2):
        for tool in m.tools:
            for effect in capabilities_for_tool(tool).effects:
                assert effect.value in m.effects, (m.id, tool, effect.value)


def test_the_teams_are_the_plans_fourteen(hall):
    found, broken = teams(None, [m.id for m in hall])
    assert broken == []
    assert {t.id for t in found} == PLAN_TEAMS
