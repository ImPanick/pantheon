# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1656` — every effect a shipped agent's table names is carried by some call
of its kit, so every row on the hire form is one a call can trip.

**Measured on the tree before this row** (`724a0d3b`, the 173 shipped agents):
26 tables named an effect no call of their kit carries. 24 web readers allowed
`read_public` (Topic Watcher, Competitor Prices, SEO Auditor, Rank Tracker…;
the row counted 25): their kits read the web with `web_search` and
`web_fetch`, which are `brokered_network_read` (and `web_fetch`
`network_egress`), and `read_public` is carried by one thing — the agent
browser's looking at what is already open (`_ACTION_CAPABILITIES`'s `_LOOK`).
So the form drew *read public pages — without asking* beside the rows that did
decide the reading, and a person could tighten it to *never* and nothing
changed. Two more: Bills Due's `external_side_effect: never` (no tool of its
kit can send or act outside Pantheon at all) and Mockup Maker's
`destructive: never` (`write_file` is `write_workspace`; the row promised
something no call is classified as, so the gate it named never asked).

**The one truthful fix is the tables.** The classification is the gate's input
and is right: a search or a fetch is a request made through Pantheon
(`brokered_network_read`), a fetch's address leaves the install
(`network_egress`), and every one of the 24 tables already decided both. The
dead row is gone from each, Bills Due's *never pays* is held by its kit
(`tests/test_the_roster_is_shipped.py`), each agent's version is bumped — so a
hire updating to it drops a grant on the row (`update_hire`) — and its sample
regenerated (unchanged). The hire form's words for `brokered_network_read` say
reading as well as searching, since that row now carries a fetch-only agent's
reading on its own (`static/js/agents/agentsWindow.js`).

`tests/test_every_effect_a_hire_asks_about_can_be_asked.py` (`B1652`) holds the
*ask* half; this holds every rule.

Driven (`Law 20`): the real catalogue and hire store's rules
(`src/agents/hires`), the real classifier, and the real `/api/agents` routes on
a real SQLite file.
"""

from __future__ import annotations

import json

from src.agents import hires as H
from src.agents.catalogue import catalogue, get_agent
from src.tool_capabilities import reach_left, widest_reach

from tests.test_a_hire_compiles_to_tasks import call, client, hire  # noqa: F401  (fixture)
from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)


def _carried(m):
    """`(what some call of its tools carries, what some call its run can
    make carries)` — the second under the table's own `never`s, as a hired run
    gets its kit (`hires.kit`, `tool_capabilities.reach_left`)."""
    never = {e for e, r in H.effective_effects(m, {}).items() if r == "never"}
    tools = set().union(*({e.value for e in widest_reach(t)} for t in m.tools))
    run = set().union(*({e.value for e in reach_left(t, never)} for t in H.kit(m, never)))
    return tools, run


# ── the row's `Verify:` ─────────────────────────────────────────────────────

def test_every_effect_a_shipped_table_names_is_carried_by_some_call_of_its_kit():
    """A `never` names what some call of its tools carries — so it refuses
    something; an `allow` or an `ask` names what some call its run can make
    carries — so it lets something through or asks something."""
    agents, broken = catalogue(None)
    assert broken == [] and len(agents) == 173
    dead = {}
    for m in agents:
        tools, run = _carried(m)
        named = {e: r for e, r in m.effects.items() if e not in (tools if r == "never" else run)}
        if named:
            dead[m.id] = named
    assert dead == {}, dead


def test_the_hire_form_draws_exactly_what_the_kit_can_do():
    """With `B1629`'s half (nothing a call carries is left undecided), the
    table a hire is shown is the kit's reach, row for row."""
    agents, _ = catalogue(None)
    off = {m.id: sorted(set(H.manifest_effects(m)) ^ _carried(m)[0]) for m in agents}
    assert {a: d for a, d in off.items() if d} == {}


def test_read_public_is_the_agent_browsers_looking_and_no_web_readers():
    assert "read_public" in H.tool_effects("agent_browser")
    for tool in ("web_search", "web_fetch"):
        assert "read_public" not in H.tool_effects(tool)
        assert "brokered_network_read" in H.tool_effects(tool)
    named = {m.id for m in catalogue(None)[0] if "read_public" in m.effects}
    assert named <= {m.id for m in catalogue(None)[0] if "agent_browser" in m.tools}, named


# ── on the hire form, through the routes ────────────────────────────────────

def test_a_web_readers_page_draws_no_row_its_calls_cannot_trip(client):
    for agent, rows in (("competitor-prices", {"brokered_network_read": "allow", "network_egress": "allow"}),
                        ("rank-tracker", {"brokered_network_read": "allow"}),
                        ("bills-due", {"read_private": "allow", "write_private": "allow"}),
                        ("mockup-maker", {"write_workspace": "allow"})):
        page = call(client, "GET", f"/api/agents/{agent}").json()
        assert page["effects"] == rows, (agent, page["effects"])
    refused = call(client, "POST", "/api/agents/topic-watcher/hire",
                   json={"inputs": {"topics": ["solar"]}, "grants": {"read_public": "never"}})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Topic Watcher's tools never have the effect “read_public”."


def test_a_hire_that_tightened_the_dead_row_updates_without_it(client, wf_db):
    """A hire made at the old version, its person having set the dead row to
    *never*: it waits to be updated like any hire behind its file, and the
    update drops the grant with the row."""
    from core.database import AgentHire
    h = hire(client, "topic-watcher", inputs={"topics": ["solar"]})
    db = wf_db()
    try:
        row = db.query(AgentHire).get(h["id"])
        row.version, row.grants = "1.1.0", json.dumps({"read_public": "never", "network_egress": "ask"})
        db.commit()
    finally:
        db.close()
    shown = call(client, "GET", f"/api/agents/hires/{h['id']}").json()
    assert shown["update_to"] == get_agent(None, "topic-watcher").version == "1.2.0"
    updated = call(client, "PUT", f"/api/agents/hires/{h['id']}", json={"update": True})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["version"] == "1.2.0" and body["grants"] == {"network_egress": "ask"}
    assert body["effects"] == {"brokered_network_read": "allow", "network_egress": "ask"}
