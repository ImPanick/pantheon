# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1599` — a hired agent's suggestions land on the document it read.

`suggest_document` (and `edit_document`, `update_document`, a `delete` that
names nothing) acted on `ctx.get("doc_id") or _active_document_id`, and the
second is one pointer for the whole process: every turn's prompt build sets
it to that turn's editor document, or clears it. So a hired Roadmap Keeper
that read the person's roadmap and called `suggest_document` put its
suggestions on whatever document the person's chat had open at that moment —
or refused with "No active document to suggest on" when no chat had one.

Driven through the agents' own harness (`src.agents.evals`): the real
scheduler, the real loop with its tool tasks, the real document tools over a
throwaway SQLite file — with the person's chat simulated the only way it
touches a run, by moving the process-wide pointer mid-run.
"""

from __future__ import annotations

import asyncio

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.agent_tools as agent_tools
import src.agent_tools.document_tools as D

ROADMAP = "## Q4\n- [ ] Dark mode — planned for October\n- [ ] Export to PDF — planned\n"
MINUTES = "Minutes of the board, 3 November. Dark mode — planned for October was discussed."


def _case():
    return {
        "id": "suggests-on-the-roadmap",
        "inputs": {"roadmap": "Roadmap"},
        "world": {"documents": [
            {"id": "doc-roadmap", "title": "Roadmap", "content": ROADMAP},
            {"id": "doc-open", "title": "Board minutes", "content": MINUTES},
        ]},
        "script": [
            {"call": [["manage_documents", {"action": "read", "document_id": "doc-roadmap"}]]},
            {"call": [["suggest_document", {"suggestions": [
                {"find": "Dark mode — planned for October", "replace": "Dark mode — shipped 21 October",
                 "reason": "it shipped"}]}]]},
            {"say": "Suggested 1 change to the roadmap.\n\n## Report\n- suggested 1 change\n\n"
                    "## Carry forward\n- nothing"},
        ],
        "checks": [{"called": "suggest_document"}],
    }


def _spy_on_suggest(monkeypatch):
    """The real `suggest_document`, recording where each call landed — with
    the person's chat opening "Board minutes" just before it: another turn's
    prompt build, in its own context, so the process-wide pointer moves and
    nothing this run holds does."""
    landed = []
    real = agent_tools.TOOL_HANDLERS["suggest_document"]

    async def suggest(content, ctx):
        D._active_document_id = "doc-open"
        out = await real(content, ctx)
        landed.append(out)
        return out

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "suggest_document", suggest)
    return landed


def test_a_hired_runs_suggestion_lands_on_the_document_it_read(monkeypatch):
    """A kit that cannot carry anything out of the install writes without
    asking (`D-2026-10-24-01`): the suggestion lands at once — on the roadmap
    the run read, never on the minutes the person is looking at."""
    import dataclasses
    import src.agents.catalogue as catalogue
    base = get_agent(None, "proofreader")
    kit = dataclasses.replace(base, tools=list(base.tools) + ["suggest_document"])
    real_get = catalogue.get_agent
    monkeypatch.setattr(catalogue, "get_agent",
                        lambda owner, aid: kit if aid == kit.id else real_get(owner, aid))
    landed = _spy_on_suggest(monkeypatch)
    (r,) = asyncio.run(E.run_agent(kit, cases=[dict(_case(), inputs={"document": "Roadmap"})]))
    assert landed, f"suggest_document never ran: {r.calls} ({r.status}, {r.error})"
    out = landed[0]
    assert out.get("doc_id") == "doc-roadmap", (
        f"the suggestion went to {out.get('doc_id')!r} ({out.get('error')!r}), not the roadmap it read")
    assert out.get("count") == 1


def test_an_asked_suggestion_seals_the_document_it_read(monkeypatch):
    """Roadmap Keeper's kit has a shell, so a write after reading asks
    (`P7-03`). Its card sealed the editor's document — a hired run has none —
    so it refused with "Open the exact document to edit" and the suggestion
    could never land. The card seals the roadmap the run read; approved, the
    suggestion lands there."""
    # `P24-27` rewrote the shipped Roadmap Keeper to write a suggestions
    # document instead (`suggest_document`'s target was this row's defect), so
    # the kit is its frontmatter as it stood: a shell beside the documents, and
    # `suggest_document`, delivering the answer only.
    import dataclasses
    import src.agents.catalogue as catalogue
    base = get_agent(None, "roadmap-keeper")
    m = dataclasses.replace(base, tools=tuple(t for t in base.tools if t != "create_document") + ("suggest_document",),
                            delivers=())
    real_get = catalogue.get_agent
    monkeypatch.setattr(catalogue, "get_agent",
                        lambda owner, aid: m if aid == m.id else real_get(owner, aid))
    landed = _spy_on_suggest(monkeypatch)
    case = dict(_case(), answers=["approve_task"])
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    assert landed, f"suggest_document never ran: {r.calls} ({r.status}, {r.error})"
    assert landed[-1].get("doc_id") == "doc-roadmap", landed[-1]


def _read(doc_id):
    return asyncio.run(D.ManageDocumentTool().execute(
        '{"action": "read", "document_id": "%s"}' % doc_id, {"owner": E.EVAL_OWNER}))


def _suggest(find):
    block = f"<<<FIND>>>\n{find}\n<<<SUGGEST>>>\nx\n<<<REASON>>>\ny\n<<<END>>>"
    return asyncio.run(D.SuggestDocumentTool().execute(block, {"owner": E.EVAL_OWNER}))


@pytest.fixture
def two_documents(monkeypatch):
    from core.database import Document
    monkeypatch.setattr(D, "_active_document_id", None)
    with E.isolated() as (factory, _data):
        db = factory()
        db.add(Document(id="doc-roadmap", owner=E.EVAL_OWNER, title="Roadmap", current_content=ROADMAP))
        db.add(Document(id="doc-open", owner=E.EVAL_OWNER, title="Board minutes", current_content=MINUTES))
        db.commit()
        db.close()
        yield
    D.bind_turn_document(None)


def test_a_turn_opened_on_an_editor_document_keeps_it(two_documents):
    """A chat whose editor has the minutes open, reading the roadmap for
    reference, still suggests on the minutes — what the person is looking at."""
    D.bind_turn_document(D.new_turn_document("doc-open"))
    assert _read("doc-roadmap").get("exit_code") == 0
    assert _suggest("Dark mode — planned for October")["doc_id"] == "doc-open"


def test_a_turn_with_no_editor_document_takes_up_what_it_reads(two_documents):
    holder = D.new_turn_document(None)
    D.bind_turn_document(holder)
    D._active_document_id = "doc-open"   # another turn's
    assert _suggest("Dark mode — planned for October") == {"error": "No active document to suggest on"}, \
        "before it read anything, the run has no document — not another turn's"
    _read("doc-roadmap")
    assert holder.id == "doc-roadmap"
    assert _suggest("Dark mode — planned for October")["doc_id"] == "doc-roadmap"


def test_outside_an_agent_turn_the_process_pointer_still_answers(two_documents):
    """`Law 1`: a caller with no turn (a workflow's effect, a route) is
    answered as before."""
    D.bind_turn_document(None)
    D.set_active_document("doc-roadmap")
    assert _suggest("Dark mode — planned for October")["doc_id"] == "doc-roadmap"
