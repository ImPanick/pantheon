# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1662` — a `never` in an agent's own table that takes a tool away draws
none of that tool's rows, and a person writing one is told so when it is saved.

`hires.kit` takes a tool away whole when every call of it carries a `never`
(`B1619`): `web_fetch` reaches the network on every call, so
`network_egress: never` leaves a `web_fetch` agent no tools at all. **Measured
on `b0a747d6`:** an own agent with `tools: [web_fetch]` and
`effects: {network_egress: never}` saved — `B1659`'s check
(`manifest.check_effects_carried`) passes it, since a call of its tools does
carry `network_egress` — and its page drew *search and read the web — without
asking*, the cautious default for a tool its run never gets, beside the never.

Two halves, as `B1659` has, because either alone breaks one thing:

  * **told when saved** — `manifest.check_tools_kept`, through
    `workshop.check` (save, the dry check, a draft): every tool the file lists
    is one its run gets; a never that takes one away is named with the tool,
    and one that takes them all says so in the lint's words for empty `tools`.
  * **not drawn** — `hires.manifest_effects` draws the rows of the tools the
    kit keeps, for any file however it was kept. Not in the lint, which every
    load runs: a file saved before stays its person's and hireable.

What holds the never is unchanged (`hires.held_effects`): the rows a run reads
lost the never that takes `web_fetch` away, and a run whose nevers came from
the rows alone would get `web_fetch` back — so the run, a summoned turn and a
hire's grants read the table's own nevers beside the rows.

Driven (`Law 20`): the real `/api/agents/own`, `/api/agents/{id}` and hire
routes on a real SQLite file, the real scheduler's run of a hire
(`TaskScheduler._execute_llm_task`) and the real summon, with files written
into the person's own layer as an earlier save left them.
"""

from __future__ import annotations

import os

from src.agents import hires as H
from src.agents import workshop as W
from src.agents.catalogue import catalogue, get_agent

from tests.test_a_hire_compiles_to_tasks import call, client, hire  # noqa: F401  (fixture)
from tests.test_a_hired_agent_runs_as_its_file_says import _hire, _run, _task, world  # noqa: F401
from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)


def _own(tools, effects, agent_id="sealed-reader", name="Sealed Reader"):
    return W.TEMPLATE.replace("id: my-agent", f"id: {agent_id}").replace(
        "name: My Agent", f"name: {name}").replace(
        "tools: [web_search]", f"tools: [{', '.join(tools)}]").replace(
        "effects: {brokered_network_read: allow}", f"effects: {effects}")


#: The row's agent: its only tool reaches the network on every call.
SEALED = _own(["web_fetch"], "{network_egress: never}")
#: The same never with a tool it leaves: `web_search` reads through the broker.
CAREFUL = _own(["web_search", "web_fetch"], "{brokered_network_read: allow, network_egress: never}",
               "careful-reader", "Careful Reader")

NO_TOOLS = ("Effect “network_egress” is never, and every call of web_fetch has it, so it leaves this "
            "agent no tools — an agent with no tools can only talk, and a chat already does that. "
            "Make it ask, or choose a tool that works without it.")


def _kept_before(text, agent_id, owner="alice"):
    """Written into the person's own layer as a save before `B1662` left it."""
    path = W.own_path(owner, agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    W._forget(path)


# ── the row's `Verify:` — told when saved ───────────────────────────────────

def test_an_own_agent_whose_never_takes_its_only_tool_is_told_so_when_saved(client):
    for body in ({"text": SEALED, "dry": True}, {"text": SEALED}):
        res = call(client, "POST", "/api/agents/own", json=body)
        assert res.status_code == 422, res.text
        assert res.json()["detail"] == NO_TOOLS
    assert get_agent("alice", "sealed-reader") is None, "nothing kept"
    fixed = SEALED.replace("network_egress: never", "network_egress: ask")
    assert call(client, "POST", "/api/agents/own", json={"text": fixed}).status_code == 200
    page = call(client, "GET", "/api/agents/sealed-reader").json()
    assert page["effects"] == {"brokered_network_read": "allow", "network_egress": "ask"}


def test_a_never_every_tool_carries_names_them_all(client):
    """`brokered_network_read` is in every call of both web tools."""
    text = _own(["web_search", "web_fetch"], "{brokered_network_read: never}")
    res = call(client, "POST", "/api/agents/own", json={"text": text})
    assert res.status_code == 422 and res.json()["detail"] == (
        "Effect “brokered_network_read” is never, and every call of web_search and web_fetch has "
        "it, so it leaves this agent no tools — an agent with no tools can only talk, and a chat "
        "already does that. Make it ask, or choose a tool that works without it.")


def test_two_nevers_that_each_take_a_tool_say_which_takes_which(client):
    text = _own(["web_fetch", "write_file"], "{network_egress: never, write_workspace: never}")
    res = call(client, "POST", "/api/agents/own", json={"text": text})
    assert res.status_code == 422 and res.json()["detail"] == (
        "Effects “network_egress” and “write_workspace” are never, and every call of each tool has "
        "one (web_fetch “network_egress”, write_file “write_workspace”), so they leave this agent "
        "no tools — an agent with no tools can only talk, and a chat already does that. Make one "
        "ask, or choose tools that work without them.")


def test_a_never_that_takes_one_tool_of_several_is_told_so(client):
    """Its tool line names a tool its runs never get, and the form would not
    draw the never the person wrote."""
    res = call(client, "POST", "/api/agents/own", json={"text": CAREFUL})
    assert res.status_code == 422 and res.json()["detail"] == (
        "Effect “network_egress” is never, and every call of web_fetch has it, so it takes "
        "web_fetch away — a tool on the list that its runs never get. Take web_fetch out, or make "
        "it ask.")
    fixed = CAREFUL.replace("web_search, web_fetch", "web_search").replace(", network_egress: never", "")
    assert call(client, "POST", "/api/agents/own", json={"text": fixed}).status_code == 200


def test_a_never_that_refuses_some_calls_keeps_its_tool_and_saves(client):
    """`B1619`'s case is untouched: `bash` with `destructive: never` keeps
    `bash`, and the never is drawn — it refuses the `rm`."""
    text = _own(["bash"], "{execute_code: ask, destructive: never, network_egress: ask}", "tidy")
    assert call(client, "POST", "/api/agents/own", json={"text": text}).status_code == 200
    page = call(client, "GET", "/api/agents/tidy").json()
    assert page["effects"] == {"destructive": "never", "execute_code": "ask", "network_egress": "ask"}


# ── the row's `Verify:` — a file kept before draws no such row ──────────────

def test_a_file_kept_before_stays_theirs_and_draws_no_row_of_a_tool_it_never_gets(client):
    _kept_before(SEALED, "sealed-reader")
    agents, broken = catalogue("alice")
    assert broken == [], "the lint reads it as it always did"
    mine = next(a for a in agents if a.id == "sealed-reader")
    assert (mine.source, mine.tools, mine.effects) == ("own", ("web_fetch",), {"network_egress": "never"})

    page = call(client, "GET", "/api/agents/sealed-reader").json()
    assert page["effects"] == {}, "no search and read the web — without asking"
    h = hire(client, "sealed-reader", inputs={"topic": "solar"})
    assert h["effects"] == {}, "hired: no row either"

    loosened = call(client, "POST", "/api/agents/sealed-reader/hire",
                    json={"inputs": {"topic": "solar"}, "grants": {"network_egress": "ask"}})
    assert loosened.status_code == 400 and loosened.json()["detail"] == (
        "Sealed Reader says “network_egress” is never; you can make that stricter, not looser."), \
        "not drawn, and still the file's"
    gone = call(client, "POST", "/api/agents/sealed-reader/hire",
                json={"inputs": {"topic": "solar"}, "grants": {"brokered_network_read": "never"}})
    assert gone.status_code == 400 and gone.json()["detail"] == (
        "Sealed Reader never has the effect “brokered_network_read”: a never in its own table "
        "takes web_fetch away.")

    again = call(client, "POST", "/api/agents/own", json={"text": SEALED})
    assert again.status_code == 422 and again.json()["detail"] == NO_TOOLS, "its next save says so"


def test_one_that_kept_a_tool_draws_the_rows_of_that_tool_only(client):
    _kept_before(CAREFUL, "careful-reader")
    page = call(client, "GET", "/api/agents/careful-reader").json()
    assert page["effects"] == {"brokered_network_read": "allow"}
    assert set(H.manifest_effects(get_agent("alice", "careful-reader"))) == set(H.tool_effects("web_search"))


# ── what holds the never is unchanged ───────────────────────────────────────

def test_a_run_of_one_kept_before_still_lacks_the_tool_its_never_takes(world):
    """Read from the drawn rows alone, the never is gone and so is the cut:
    the run would be handed `web_fetch` — a fetch its file says never."""
    factory, sched, seen = world
    db = factory()
    _kept_before(CAREFUL, "careful-reader")
    h, _m = _hire(db, "careful-reader", inputs={"topic": "solar"})
    seen["answer"] = "Done.\n\n## Report\n- searched\n\n## Carry forward\n- nothing"
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["allowed_tools"] == ["web_search"]
    assert seen["slot"]["agent"]["never_effects"] == ["network_egress"]

    _kept_before(SEALED, "sealed-reader")
    h2, _m = _hire(db, "sealed-reader", inputs={"topic": "solar"})
    _run(sched, db, _task(db, h2.id))
    assert seen["slot"]["allowed_tools"] == [], "its never left it no tools, and none are handed it"
    assert seen["slot"]["agent"]["never_effects"] == ["network_egress"]


def test_a_summoned_one_is_held_the_same(world):
    from src.agents.summon import summon
    factory, _sched, _seen = world
    _kept_before(CAREFUL, "careful-reader")
    s = summon("alice", "careful-reader", db=factory())
    assert (s.tools, sorted(s.never_effects)) == (["web_search"], ["network_egress"])


def test_no_shipped_agent_lists_a_tool_its_own_never_takes():
    """Every shipped file already keeps the rule a saved one now keeps, so
    *Customise* saves each as it ships — and its form is drawn as before."""
    agents, _broken = catalogue(None)
    assert len(agents) >= 173
    for m in agents:
        assert W.check(W.source(m)).tools == m.tools, m.id
        assert set(H.manifest_effects(m)) == {e for t in m.tools for e in H.tool_effects(t)}, m.id
