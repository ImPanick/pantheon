# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1606` — a hired run with no document in hand writes nothing.

`B1599` gave each agent turn its own document holder, so `update_document`
acts on the document the turn has in hand. With none, it still fell back to
`_most_recent_owned_document`: a hired agent that never read or made a
document, calling `update_document`, overwrote whichever of the person's
documents was edited last — their "Q3 letter" — and reported it as done.

A person's chat keeps that fallback (`Law 1`): the person is there, the
document it lands on opens in front of them, and its versions take it back.
A hired run is watched by nobody while it goes.

Driven through the agents' own harness (`src.agents.evals`): the real
scheduler, the real loop with its tool tasks, the real document tools over a
throwaway SQLite file.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.agent_tools as agent_tools
import src.agent_tools.document_tools as D

LETTER = "Dear board,\n\nQ3 closed ahead of plan.\n"
NOTES = "Shopping: eggs, milk.\n"


def _kit(monkeypatch, tool):
    """Proofreader's kit — documents only, nothing that reaches outside, so a
    write runs without asking (`D-2026-10-24-01`) — with `tool` added."""
    import src.agents.catalogue as catalogue
    base = get_agent(None, "proofreader")
    kit = dataclasses.replace(base, tools=list(base.tools) + [tool])
    real_get = catalogue.get_agent
    monkeypatch.setattr(catalogue, "get_agent",
                        lambda owner, aid: kit if aid == kit.id else real_get(owner, aid))
    return kit


def _spy(monkeypatch, tool):
    landed = []
    real = agent_tools.TOOL_HANDLERS[tool]

    async def spy(content, ctx):
        out = await real(content, ctx)
        landed.append(out)
        return out

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, spy)
    return landed


def _case(call):
    return {
        "id": "writes-with-nothing-in-hand",
        "inputs": {"document": "Q3 letter"},
        "world": {"documents": [
            {"id": "doc-letter", "title": "Q3 letter", "content": LETTER},
        ]},
        "script": [
            {"call": [call]},
            {"say": "Done.\n\n## Report\n- tried\n\n## Carry forward\n- nothing"},
        ],
        "checks": [{"called": call[0]}],
    }


@pytest.mark.parametrize("tool, args", [
    ("update_document", {"content": "Dear board,\n\nEverything is fine.\n"}),
    ("edit_document", {"edits": [{"find": "Q3 closed ahead of plan.", "replace": "Q3 closed."}]}),
])
def test_a_hired_run_that_names_no_document_is_refused_and_writes_nothing(monkeypatch, tool, args):
    kit = _kit(monkeypatch, tool)
    monkeypatch.setattr(D, "_active_document_id", None)
    landed = _spy(monkeypatch, tool)
    (r,) = asyncio.run(E.run_agent(kit, cases=[_case([tool, args])]))
    assert landed, f"{tool} never ran: {r.calls} ({r.status}, {r.error})"
    out = landed[0]
    assert r.documents == [], f"the run wrote the person's letter: {r.documents}"
    assert "doc_id" not in out and out.get("exit_code") == 1, out
    err = out.get("error") or ""
    assert "nothing was written" in err.lower() and "read" in err.lower(), (
        f"the refusal must say nothing was written and what to do instead: {err!r}")


def test_a_hired_run_still_updates_the_document_it_read(monkeypatch):
    """The refusal is for a run with nothing in hand — one that read the
    letter writes it, as `B1599` made it."""
    kit = _kit(monkeypatch, "update_document")
    landed = _spy(monkeypatch, "update_document")
    case = _case(["update_document", {"content": "Dear board,\n\nQ3 closed.\n"}])
    case["script"].insert(0, {"call": [["manage_documents", {"action": "read", "document_id": "doc-letter"}]]})
    (r,) = asyncio.run(E.run_agent(kit, cases=[case]))
    assert landed and landed[0].get("doc_id") == "doc-letter", landed
    assert r.documents == [{"title": "Q3 letter", "content": "Dear board,\n\nQ3 closed."}], r.documents


@pytest.fixture
def two_documents(monkeypatch):
    from core.database import Document
    monkeypatch.setattr(D, "_active_document_id", None)
    with E.isolated() as (factory, _data):
        db = factory()
        db.add(Document(id="doc-letter", owner=E.EVAL_OWNER, title="Q3 letter", current_content=LETTER))
        db.add(Document(id="doc-notes", owner=E.EVAL_OWNER, title="Notes", current_content=NOTES))
        db.commit()
        db.close()
        yield factory
    D.bind_turn_document(None)


def _update(text):
    return asyncio.run(D.UpdateDocumentTool().execute(text, {"owner": E.EVAL_OWNER}))


def test_a_chat_with_nothing_in_hand_still_takes_the_most_recent(two_documents):
    """`Law 1`: a person's chat — the holder a chat turn binds — keeps the
    fallback the tool always had; the document it lands on opens in front of
    the person."""
    D.bind_turn_document(D.new_turn_document(None))
    out = _update("Shopping: eggs.")
    assert out.get("action") == "update" and out.get("doc_id") in {"doc-letter", "doc-notes"}, out


def test_a_hired_turns_holder_refuses_before_opening_anything(two_documents):
    D.bind_turn_document(D.new_turn_document(None, hired=True))
    out = _update("Shopping: eggs.")
    assert out.get("exit_code") == 1 and "nothing was written" in out["error"].lower(), out
    db = two_documents()
    try:
        from core.database import Document
        assert {d.id: d.current_content for d in db.query(Document).all()} == {
            "doc-letter": LETTER, "doc-notes": NOTES}
    finally:
        db.close()


def test_a_summoned_agents_turn_is_not_a_hired_run():
    """The loop learns a run is hired from the scheduler's policy — the one
    place that knows, driven by the harness tests above — and a summoned
    agent's turn (a person is here, `P24-26`) and a plain chat's are not."""
    from src.tool_policy import ToolPolicy
    from src.agents.summon import Summoned
    assert ToolPolicy().hired is False
    summoned = Summoned(agent_id="proofreader", name="Proofreader", tools=["update_document"],
                        ask_effects=frozenset(), never_effects=frozenset())
    assert summoned.policy(ToolPolicy()).hired is False
