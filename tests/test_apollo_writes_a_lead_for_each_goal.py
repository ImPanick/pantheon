# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo writes a lead for each goal, and a teammate for each hand-off.

The owner's direction (2026-11-24): Apollo should run its team the way Grok
does, "just not individual bots assigned off rip — they can be dynamic". Asked
whether Apollo should write a lead for each goal that is never saved, so it
needs no admin's approval, he said "Yes". Checked here, with the real
`goal_lead.py`, `tasks.create`, `catalogue.get_agent` and `fleet.hand_off`:
  * a goal with no saved agent named gets a lead written for it, which its
    owner's lookups find and nobody else's do, and which never joins the
    roster;
  * a written lead holds only tools a person could pick, never one that
    changes the server, and everything but reading asks the person first;
  * Apollo's name, role, steps and tools for the lead are kept, the two steps
    that keep a yes the person's are always last, and a spec that can't be
    written falls back to the plain lead;
  * the saved agent that best fits the goal is named as the teammate to hand
    to;
  * a hand-off with no agent named writes a teammate for the job, still cut to
    what its delegator holds.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.apollo import fleet as F
from src.apollo import goal_lead as G
from src.apollo import tasks as T
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)

ADA = "ada"


@pytest.fixture
def no_fit(monkeypatch):
    """No saved agent fits, so a lead's runbook is Apollo's alone."""
    monkeypatch.setattr("src.apollo.lead.pick_lead", lambda owner, text, **k: None)


@pytest.fixture
def db(apollo_db):
    d = apollo_db()
    yield d
    d.close()


def _goal(db, owner=ADA, **kw):
    t = T.create(db, owner, title=kw.pop("title", "Renew the rack's TLS certificate"),
                 brief=kw.pop("brief", "Find when it expires and renew it."), **kw)
    db.flush()
    return t


def test_a_goal_with_no_agent_named_gets_a_lead_written_for_it(db, no_fit):
    from src.agents.catalogue import catalogue, get_agent
    t = _goal(db)
    assert G.is_goal_lead(t.lead_agent) and t.lead_agent == G.lead_id(t.id)
    assert t.next_step is None
    m = get_agent(ADA, t.lead_agent)
    assert m is not None and m.name == "Lead: Renew the rack's TLS certificate"
    assert get_agent("bob", t.lead_agent) is None                 # another person's lookups don't find it
    agents, _broken = catalogue(ADA)
    assert t.lead_agent not in {a.id for a in agents}             # never in the roster or the hall


def test_a_saved_agent_named_still_leads(db, no_fit, monkeypatch):
    import src.agents.catalogue as catalogue
    real = catalogue.get_agent
    monkeypatch.setattr(catalogue, "get_agent",
                        lambda owner, aid: SimpleNamespace(id="cert-watch", name="Certificate Watch")
                        if aid == "cert-watch" else real(owner, aid))
    t = _goal(db, lead_agent="cert-watch")
    assert t.lead_agent == "cert-watch"


def test_a_written_lead_reads_freely_and_asks_before_anything_else(no_fit):
    from src.agents.hires import tool_effects
    from src.tool_policy import selectable_tool_names
    admin = [n for n in selectable_tool_names() if "admin_change" in tool_effects(n)]
    assert admin, "the server has tools that change it, so this test means something"
    m = G.write(ADA, "1234567890abcdef1234567890abcdef", title="Tidy the notes",
                spec={"tools": admin[:3] + ["read_file", "write_file", "not_a_tool"]})
    assert list(m.tools) == ["read_file", "write_file"]
    for effect, mode in m.effects.items():
        assert mode == ("allow" if effect in G.ALLOWED_EFFECTS else "ask"), effect
    assert m.effects.get("write_workspace") == "ask"


def test_apollos_name_role_steps_and_tools_are_kept_and_the_yes_stays_the_persons(no_fit):
    m = G.write(ADA, "abcdef1234567890abcdef1234567890", title="Renew the cert",
                spec={"name": "Cert renewer", "role": "Renews the rack's certificate",
                      "steps": ["1. Read when the certificate expires", "2. Renew it"],
                      "tools": ["web_search", "read_file"]})
    assert (m.name, m.tagline, list(m.tools)) == ("Cert renewer", "Renews the rack's certificate",
                                                  ["web_search", "read_file"])
    lines = m.runbook.splitlines()
    assert lines[0] == "1. Read when the certificate expires" and lines[1] == "2. Renew it"
    assert lines[-2:] == [f"3. {G.KEEP_STEPS[0]}", f"4. {G.KEEP_STEPS[1]}"]


def test_a_spec_that_cant_be_written_falls_back_to_the_plain_lead(no_fit, monkeypatch):
    from src.agents import workshop
    from src.agents.manifest import ManifestRefused
    real = workshop.check

    def check(text):
        if "Bad lead" in text:
            raise ManifestRefused("refused")
        return real(text)
    monkeypatch.setattr(workshop, "check", check)
    m = G.write(ADA, "00000000000000000000aaaa", title="Plan the garden", spec={"name": "Bad lead"})
    assert m.name == "Lead: Plan the garden" and list(m.tools) == list(G.DEFAULT_TOOLS)


def test_when_nothing_can_be_written_apollo_leads_the_goal(db, no_fit, monkeypatch):
    monkeypatch.setattr(G, "write", lambda *a, **k: None)
    t = _goal(db)
    assert t.lead_agent is None and "Apollo leads it" in t.next_step


def test_the_saved_agent_that_fits_is_named_as_the_teammate_to_hand_to(monkeypatch):
    monkeypatch.setattr("src.apollo.lead.pick_lead",
                        lambda owner, text, **k: {"id": "cert-watch", "name": "Certificate Watch"}
                        if "certificate" in text.lower() else None)
    m = G.write(ADA, "fedcba0987654321fedcba0987654321", title="Renew the rack's TLS certificate")
    assert "Certificate Watch (cert-watch) is a saved agent that fits this goal" in m.runbook
    plain = G.write(ADA, "11111111111111111111bbbb", title="Plan the garden")
    assert "saved agent that fits" not in plain.runbook


def test_a_hand_off_with_no_agent_writes_a_teammate_cut_to_its_delegator(db, no_fit, monkeypatch):
    import src.agents.catalogue as catalogue
    import src.agents.hires as hires
    real = catalogue.get_agent
    lead = SimpleNamespace(id="lead", name="Lead", tagline="runs the goal",
                           tools=("web_search", "read_file"), effects={})
    monkeypatch.setattr(catalogue, "get_agent", lambda owner, aid: lead if aid == "lead" else real(owner, aid))
    monkeypatch.setattr(hires, "held_effects", lambda m, grants=None: dict(m.effects))
    monkeypatch.setattr(hires, "kit", lambda m, never: [t for t in m.tools if t not in never])
    goal = _goal(db, lead_agent="lead")
    child = F.hand_off(db, ADA, goal, from_agent="lead", to_agent=None, brief="Find the expiry date",
                       lead={"name": "Expiry finder", "tools": ["web_search", "write_file"]})
    assert G.is_goal_lead(child.lead_agent) and child.parent_id == goal.id
    assert goal.next_step == "Waiting on Expiry finder."
    tools, _never, _ask, _allow = F.narrow(["web_search", "write_file"], [], [], [],
                                           F.ceiling_for(db, child.id))
    assert tools == ["web_search"]                                # no write the lead above never had


def test_a_hand_off_whose_teammate_cant_be_written_leaves_nothing_behind(db, no_fit, monkeypatch):
    import src.agents.catalogue as catalogue
    lead = SimpleNamespace(id="lead", name="Lead", tagline="runs the goal", tools=("web_search",), effects={})
    monkeypatch.setattr(catalogue, "get_agent", lambda owner, aid: lead if aid == "lead" else None)
    goal = _goal(db, lead_agent="lead")
    monkeypatch.setattr(G, "write", lambda *a, **k: None)
    with pytest.raises(ApolloRefused) as e:
        F.hand_off(db, ADA, goal, from_agent="lead", to_agent="", brief="Find the expiry date")
    assert "Do it yourself" in e.value.sentence
    assert F.children(db, ADA, goal) == []


def test_a_goal_leads_id_is_the_goals_so_no_saved_agent_can_be_mistaken_for_one():
    assert G.lead_id("3F2A9B1C-0D4E-4F5A-8B6C-7D8E9F0A1B2C") == "goal-3f2a9b1c0d4e4f5a8b6c"
    assert not G.is_goal_lead("goal-setter")
    assert not G.is_goal_lead("goal-3f2a9b1c0d4e4f5a8b6c/../x")
