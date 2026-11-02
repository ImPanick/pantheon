# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-28` — the company layer: who an agent hands to, what it accepts, and
the event that says a report was filed.

The audit of 2026-11-01 (`P24-27`'s second half, the owner's *"a fully staffed
company"*) found 173 agents with no department, no role and no way to say
whose work follows whose — a team was a hire bundle whose members, in its own
words, *do not hand work to each other*. This row adds the words to say it and
one signal to act on it, and ships the first slice of 28 agents written for
that company from the start.

**Measured before the row, on `9b4feb6`:** 173 agents, 0 with a department,
role, `hands_to` or `accepts`; 14 teams, 0 with a flow; 8 events, none raised
when a hired agent finished; 6 agents named a skill; 0 declared a connector.
**After it:** 201 agents, the 28 new ones each with a department, a role and
their hand-offs; 15 teams, one with a flow; 9 events, `report_filed` raised by
`record_report` with the delivered document's title; 51 agents name a skill
whose every required tool their kit holds; 47 declare the connector their kit
needs.

What this file pins:

  * the five fields are read, kept and shown (`to_public`), and refused in a
    sentence when they are not what they say;
  * a team's `flow` joins two different members by a document, an event or
    `delegate`, and nothing else;
  * `report_filed` is in the catalogue, a trigger can wait on it, the picker
    has words for it, and a finished hired run raises it with the title of the
    document it delivered;
  * every `hands_to` names an agent the hall has, every `accepts` names a
    document some shipped agent delivers, and every skill an agent names has
    its required tools in that agent's kit — so the graph is never a promise
    the roster does not keep.
"""
from __future__ import annotations

import asyncio

import pytest

import src.event_bus as eb
from src.agents import evals as E
from src.agents import manifest as M
from src.agents import teams as T
from src.agents.catalogue import catalogue, get_agent
from src.agents.runtime import delivered_title

BASE = open("library/pantheon/agents/architect/AGENT.md", encoding="utf-8").read()


def _with(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


# ── the fields ───────────────────────────────────────────────────────────────

def test_the_architect_declares_its_place_in_the_company():
    m = M.parse_manifest(BASE)
    assert m.department == "engineering" and m.role == "worker"
    assert [h["agent"] for h in m.hands_to] == ["spec-writer", "api-designer"]
    assert all(h["via"] == "document:Design" for h in m.hands_to)
    pub = m.to_public()
    assert pub["department"] == "engineering" and pub["role"] == "worker"
    assert pub["hands_to"] == [dict(h) for h in m.hands_to]
    assert pub["accepts"] == [] and pub["reports_to"] == ""


def test_an_agent_with_none_of_the_fields_still_reads():
    text = BASE
    for line in ("department: engineering\n", "role: worker\n",
                 "hands_to:\n  - {agent: spec-writer, via: \"document:Design\"}\n"
                 "  - {agent: api-designer, via: \"document:Design\"}\n"):
        text = _with(text, line, "")
    m = M.parse_manifest(text)
    assert m.department == "" and m.role == "worker" and m.hands_to == () and m.accepts == ()


@pytest.mark.parametrize("old,new,words", [
    ("department: engineering", "department: wizardry", "department"),
    ("role: worker", "role: boss", "role"),
    ("{agent: spec-writer, via: \"document:Design\"}", "{agent: spec-writer, via: \"carrier pigeon\"}", "via"),
    ("{agent: spec-writer, via: \"document:Design\"}", "{agent: Spec Writer, via: \"document:Design\"}", "agent"),
    ("hands_to:\n", "reports_to: Nobody In Particular\nhands_to:\n", "reports_to"),
    ("hands_to:\n", "accepts: not-a-list\nhands_to:\n", "accepts"),
])
def test_a_field_that_is_not_what_it_says_is_refused_in_a_sentence(old, new, words):
    with pytest.raises(M.ManifestRefused) as e:
        M.parse_manifest(_with(BASE, old, new))
    assert words in e.value.sentence.lower()


# ── a team's flow ────────────────────────────────────────────────────────────

TEAM = """---
id: two-of-them
name: Two Of Them
tagline: Two of them.
members: [architect, api-designer]
flow:
  - {from: architect, to: api-designer, via: "document:Design"}
---
About.
"""


def test_a_team_flow_is_kept_and_shown():
    team = T.parse_team(TEAM)
    assert team.flow == ({"from": "architect", "to": "api-designer", "via": "document:Design"},)
    agents, _ = catalogue(None)
    pub = T.to_public(team, {m.id: m for m in agents})
    assert pub["flow"] == [{"from": "architect", "to": "api-designer", "via": "document:Design"}]


@pytest.mark.parametrize("old,new,words", [
    ("to: api-designer", "to: architect", "two different members"),
    ("to: api-designer", "to: spec-writer", "two different members"),
    ("via: \"document:Design\"", "via: \"telepathy\"", "via"),
    ("{from: architect, to: api-designer, via: \"document:Design\"}", "{from: architect}", "from"),
])
def test_a_flow_edge_that_is_not_an_edge_is_refused(old, new, words):
    with pytest.raises(M.ManifestRefused) as e:
        T.parse_team(_with(TEAM, old, new))
    assert words in e.value.sentence.lower()


def test_the_engineering_desk_ships_with_a_flow_the_hall_can_draw():
    agents, _ = catalogue(None)
    found, broken = T.teams(None, [m.id for m in agents])
    assert broken == []
    desk = next(t for t in found if t.id == "engineering-desk")
    assert len(desk.flow) == 7
    assert all(e["from"] in desk.members and e["to"] in desk.members for e in desk.flow)


# ── report_filed ─────────────────────────────────────────────────────────────

def test_report_filed_is_an_event_a_hire_can_wait_on():
    assert eb.EVENT_REPORT_FILED == "report_filed" and "report_filed" in eb.EVENT_NAMES
    assert eb.EVENT_PAYLOAD_FIELDS["report_filed"] == ("agent", "hire", "run_id", "title")
    m = M.parse_manifest(_with(BASE, "  - {on: hand}\n", "  - {on: event, event: report_filed}\n"))
    assert m.triggers == ({"on": "event", "event": "report_filed"},)
    assert M.describe_trigger(m.triggers[0]) == "another agent's report"


def test_the_picker_has_words_for_it():
    js = open("static/js/tasks.js", encoding="utf-8").read()
    assert "report_filed: ['agent report filed', 'agent reports filed']" in js


def test_delivered_title_reads_the_contract_check():
    checks = [{"check": "an answer", "ok": True, "detail": "The answer has its sections."},
              {"check": "a document titled “Design”", "ok": True, "detail": "“Design — rate limits” is there."}]
    assert delivered_title(checks) == "Design — rate limits"
    assert delivered_title([{"check": "a document titled “Design”", "ok": False,
                             "detail": "No document titled “Design” was written in this run."}]) == ""
    assert delivered_title([]) == "" and delivered_title(None) == ""


def test_a_finished_hired_run_raises_report_filed_with_what_it_delivered(monkeypatch):
    fired = []
    monkeypatch.setattr(eb, "fire_event", lambda name, owner=None, payload=None: fired.append((name, owner, payload)))
    m = get_agent(None, "architect")
    case = next(c for c in E.load_evals(m) if c["id"] == "a-goal-with-three-options")
    results = asyncio.run(E.run_agent(m, cases=[case]))
    assert results[0].passed, results[0].checks
    reports = [p for n, _o, p in fired if n == "report_filed"]
    assert len(reports) == 1, fired
    assert reports[0]["agent"] == "architect"
    assert reports[0]["title"] == "Design — rate limits on the public API"
    assert reports[0]["run_id"] and reports[0]["hire"]


# ── the roster keeps its graph honest ────────────────────────────────────────

@pytest.fixture(scope="module")
def hall():
    agents, broken = catalogue(None)
    assert broken == []
    return agents


def test_every_hand_off_names_an_agent_the_hall_has(hall):
    ids = {m.id for m in hall}
    for m in hall:
        for h in m.hands_to:
            assert h["agent"] in ids, (m.id, h)
        if m.reports_to:
            assert m.reports_to in ids, (m.id, m.reports_to)


def test_every_accepted_document_is_one_some_agent_delivers(hall):
    delivered = {d.get("title") for m in hall for d in m.delivers if d.get("kind") == "document"}
    for m in hall:
        for a in m.accepts:
            kind, _, title = a.partition(":")
            if kind == "document":
                assert title in delivered, (m.id, a)


def test_the_slice_has_a_department_and_a_role_each(hall):
    wave3 = [m for m in hall if m.wave == 3]
    assert len(wave3) == 28
    for m in wave3:
        assert m.department in M.DEPARTMENTS and m.role in M.ROLES, m.id
        assert m.hands_to or m.accepts, f"{m.id} is in the company and hands to nobody"


def test_every_skill_an_agent_names_has_its_tools_in_the_kit(hall):
    import os
    import re
    need = {}
    for d in os.listdir("library/pantheon/skills"):
        path = os.path.join("library/pantheon/skills", d, "SKILL.md")
        if not os.path.isfile(path):
            continue
        hit = re.search(r"^requires_toolsets:\s*\[(.*?)\]", open(path, encoding="utf-8").read(), re.M)
        need[d] = {t.strip() for t in hit.group(1).split(",") if t.strip()} if hit else set()
    for m in hall:
        for s in m.skills:
            assert s in need, (m.id, s)
            assert need[s] <= set(m.tools), (m.id, s, sorted(need[s] - set(m.tools)))
    assert sum(1 for m in hall if m.skills) >= 51
    assert sum(1 for m in hall if m.needs.get("connectors")) >= 47
