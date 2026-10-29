# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1659` — a person's own agent file names only effects its calls carry: it
is told so when it is saved, and a file kept before draws no row that cannot
happen.

`B1656` held the shipped tables to it: every effect a table names is carried
by some call of its kit, so every row on the hire form is one a call can trip.
A person's own file (*New agent*, *Describe it*, *Customise* —
`src/agents/workshop.py`) was held only to the lint, which checks that an
effect's name is real, and `hires.manifest_effects` copied every named effect
into the form. **Measured on `43eb2626`:** an own agent with only `web_fetch`
and `read_public: allow` saved, and its page drew *read public pages —
without asking* — `read_public` is the agent browser's looking, and no call of
`web_fetch` carries it — beside the rows that did decide its reading; and a
Topic Watcher customised before `B1656` (its table allowed `read_public`)
drew the row the shipped file had just lost.

Both halves, because either alone breaks one of them: a refusal in the lint
would run on every load and turn that customised Topic Watcher broken — its
hires' runs stopped for a line that changes nothing — and only not drawing
the row would leave a person believing their line does something. So the
save tells (`manifest.check_effects_carried`, through `workshop.check`: saved,
checked, drafted, proposed), and the form draws only what some call of the
tools carries (`hires.manifest_effects`), for any file however it was kept.

Driven (`Law 20`): the real `/api/agents/own`, `/api/agents/draft`,
`/api/agents/{id}` and hire routes on a real SQLite file, and a file written
into the person's own layer as an earlier save left it.
"""

from __future__ import annotations

import dataclasses
import os

from src.agents import hires as H
from src.agents import workshop as W
from src.agents.catalogue import catalogue, get_agent

from tests.test_a_hire_compiles_to_tasks import call, client, hire  # noqa: F401  (fixture)
from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)


def _own(tools, effects, agent_id="page-reader"):
    return W.TEMPLATE.replace("id: my-agent", f"id: {agent_id}").replace(
        "tools: [web_search]", f"tools: [{', '.join(tools)}]").replace(
        "effects: {brokered_network_read: allow}", f"effects: {effects}")


READER = _own(["web_fetch"], "{brokered_network_read: allow, network_egress: ask, read_public: allow}")


# ── the row's `Verify:` — told when saved ───────────────────────────────────

def test_an_own_web_fetch_agent_allowing_read_public_is_told_so_when_saved(client):
    for body in ({"text": READER, "dry": True}, {"text": READER}):
        res = call(client, "POST", "/api/agents/own", json=body)
        assert res.status_code == 422, res.text
        assert res.json()["detail"] == (
            "Effect “read_public” is allow, and no call this agent can make has it — a row on the "
            "hire form that never happens. Take it out; the effects its calls can have are: "
            "brokered_network_read, network_egress.")
    assert get_agent("alice", "page-reader") is None, "nothing kept"
    fixed = READER.replace(", read_public: allow", "")
    assert call(client, "POST", "/api/agents/own", json={"text": fixed}).status_code == 200
    page = call(client, "GET", "/api/agents/page-reader").json()
    assert page["effects"] == {"brokered_network_read": "allow", "network_egress": "ask"}


def test_a_never_no_call_carries_refuses_nothing_and_is_told_so(client):
    """Mockup Maker's case as it was: a file tool no call of which is
    `destructive`. `B1660` made a `write_file` over a file that was there
    `destructive`, so the case is `edit_file` now — an edit in place, which
    replaces no file whole."""
    text = _own(["edit_file"], "{write_workspace: allow, destructive: never}", "page-maker")
    res = call(client, "POST", "/api/agents/own", json={"text": text})
    assert res.status_code == 422 and res.json()["detail"] == (
        "Effect “destructive” is never, and no call of this agent's tools has it, so it refuses "
        "nothing — a row on the hire form that never happens. Take it out; its tools' effects "
        "are: write_workspace.")


def test_an_allow_for_a_tool_its_own_never_takes_away_is_told_so(client):
    """Every `web_fetch` call reaches the network, so `network_egress: never`
    takes the tool away whole (`hires.kit`) and nothing is left to read with."""
    text = _own(["web_fetch"], "{network_egress: never, brokered_network_read: allow}", "sealed-reader")
    res = call(client, "POST", "/api/agents/own", json={"text": text})
    assert res.status_code == 422 and res.json()["detail"] == (
        "Effect “brokered_network_read” is allow, and no call this agent can make has it (a never in "
        "its table takes web_fetch away) — a row on the hire form that never happens. Take it out; "
        "the effects its calls can have are: none.")


def test_a_draft_that_names_one_is_told_why_and_redrafted(client, monkeypatch):
    import src.workflow_assist as wa
    from tests.test_an_agent_is_written_by_its_person import _fields
    seen = []
    answers = [_fields(tools=["web_fetch"], effects={"read_public": "allow", "brokered_network_read": "allow",
                                                     "network_egress": "ask"}),
               _fields(tools=["web_fetch"], effects={"brokered_network_read": "allow", "network_egress": "ask"})]

    async def model(owner, messages, *, max_tokens):
        seen.append(messages)
        return answers.pop(0), None

    monkeypatch.setattr(wa, "ask_for_json", model)
    out = call(client, "POST", "/api/agents/draft", json={"description": "read pages for me"}).json()
    assert out["ok"] is True and "read_public" not in out["text"], out
    assert "Effect “read_public” is allow, and no call this agent can make has it" in seen[1][-1]["content"]


# ── the row's `Verify:` — a file kept before draws no such row ──────────────

def _kept_before(owner="alice"):
    """Topic Watcher as a person customised it before `B1656`: its table
    allowed `read_public`. Written into their own layer as that save left it."""
    shipped = get_agent(None, "topic-watcher")
    text = W.source(shipped).replace(f"version: {shipped.version}", "version: 1.1.0").replace(
        "effects: {brokered_network_read: allow, network_egress: allow}",
        "effects: {read_public: allow, brokered_network_read: allow, network_egress: allow}")
    assert "read_public: allow" in text
    path = W.own_path(owner, "topic-watcher")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    W._forget(path)
    return text


def test_a_file_kept_before_stays_theirs_and_draws_no_row_that_cannot_happen(client):
    text = _kept_before()
    agents, broken = catalogue("alice")
    assert broken == [], "the lint reads it as it always did"
    mine = next(a for a in agents if a.id == "topic-watcher")
    assert (mine.source, mine.effects["read_public"]) == ("own", "allow"), "its line is kept as written"

    page = call(client, "GET", "/api/agents/topic-watcher").json()
    assert page["effects"] == {"brokered_network_read": "allow", "network_egress": "allow"}
    refused = call(client, "POST", "/api/agents/topic-watcher/hire",
                   json={"inputs": {"topics": ["solar"]}, "grants": {"read_public": "never"}})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Topic Watcher's tools never have the effect “read_public”."
    h = hire(client, "topic-watcher", inputs={"topics": ["solar"]})
    assert h["effects"] == page["effects"], "hired: the rows its calls can trip, and those only"

    again = call(client, "POST", "/api/agents/own", json={"text": text})
    assert again.status_code == 422 and "“read_public” is allow" in again.json()["detail"], \
        "its next save says so"


# ── the form, for any table ─────────────────────────────────────────────────

def test_the_form_draws_a_named_rule_only_where_some_call_carries_it():
    for tools, effects in ((["web_fetch"], {"read_public": "allow"}),
                           (["edit_file"], {"destructive": "never"}),   # `B1660`: not write_file
                           (["web_search", "agent_browser"], {"read_public": "never"})):
        m = dataclasses.replace(W.check(_own(tools, "{}")), effects=effects)
        reach = {e for t in tools for e in H.tool_effects(t)}
        assert set(H.manifest_effects(m)) == reach, (tools, effects)
    reader = W.check(_own(["web_search", "agent_browser"], "{read_public: never}"))
    assert H.manifest_effects(reader)["read_public"] == "never", "a never some call carries is drawn"
