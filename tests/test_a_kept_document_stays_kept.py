# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1019` — a document the person kept in a Documents Tidy proposal stays kept.

`B1006`'s Keep deleted nothing and remembered nothing: measured on the tree
before this row, the next tidy — five new documents later — offered the same
four documents again, every time. The owner's call (`D-2026-10-01-04`): *remember
Keep* — a kept document is marked kept and is not proposed again unless it
changes.

"Changes" is the content, by the digest `B994` seals a plan to; the mark lives
in `Document.tidy_verdict` as `kept:<digest>`, which the library's AI tidy
already skips and never writes; and only the person's own answer — the route
only a person can call, read back through `B1005`'s sealed reading — writes it.

Driven end to end on `B1006`'s harness (`Law 20`): a real SQLite database, the
task `ensure_defaults` seeds run by the real scheduler, the real answer route,
the real `do_app_api`, the real agent tool, and the library's real AI-tidy route
with only the model's reply faked.
"""

import asyncio
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_the_documents_tidy_asks_first import (  # noqa: F401  (fixtures by name)
    _app, alive, answer, cdb, chat_rows, doc, document_actions, everything, F, mess,
    routed, run_seeded_tidy, the_notice, waiting, world,
)
from tests.test_app_api_cannot_widen_the_owner import _route_httpx_into
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tools.system import do_app_api

PROPOSED = ("junk", "empty", "quotes", "copy")
LEFT = ("copy_long", "keep", "fresh")
KEPT_REPLY = "Kept 4 documents. Documents Tidy won't ask about them again unless they change."


def _rows(world):
    db = world.db()
    try:
        return {d.id: d for d in db.query(cdb.Document).all()}
    finally:
        db.close()


def verdicts(world):
    return {i: d.tidy_verdict for i, d in _rows(world).items()}


def stamps(world):
    return {i: d.updated_at for i, d in _rows(world).items()}


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _edit(world, doc_id, **values):
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == doc_id).update(
        {getattr(cdb.Document, k): v for k, v in values.items()})
    db.commit()
    db.close()


def keep(world):
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    res = answer(plan_id, F.PLAN_DECLINE_LABEL)
    assert res.status_code == 200, res.text
    return res.json()


def labels(review):
    return [i["label"] for i in review["items"]]


# ── Keep is remembered ──────────────────────────────────────────────────────

def test_keep_marks_what_was_shown_and_says_so(world, mess, routed):
    before, times = everything(world), stamps(world)
    body = keep(world)
    assert body["outcome"] == "declined" and body["message"] == KEPT_REPLY
    marks = verdicts(world)
    content = {i: d.current_content for i, d in _rows(world).items()}
    for key in PROPOSED:
        assert marks[mess[key]] == "kept:" + _digest(content[mess[key]]), key
    for key in LEFT:
        assert marks[mess[key]] is None, key
    assert everything(world) == before, "Keep deleted or changed something"
    assert stamps(world) == times, "keeping a document was recorded as editing it"
    assert chat_rows(world)[-1][1] == KEPT_REPLY
    assert waiting() == []


def test_the_next_tidy_does_not_ask_about_them_again(world, mess, routed):
    keep(world)
    run = run_seeded_tidy(world)
    assert run == {"status": "skipped", "result": (
        "scanned 7 document(s), no junk (4 documents you chose to keep were left alone)")}
    assert world.scheduler.pop_notifications("bob") == []
    assert waiting() == []


def test_new_clutter_is_asked_about_and_kept_clutter_is_not(world, mess, routed):
    keep(world)
    fresh_junk = doc(world, "scratch", content="tmp words")
    run = run_seeded_tidy(world)
    assert run["status"] == "success", run
    review = the_notice(world)["review"]
    assert labels(review) == ["scratch"]
    assert review["items"][0]["note"] == "junk title 'scratch'"
    record = chat_rows(world)[-1][1]
    assert "4 documents you chose to keep were left alone." in record
    assert answer(review["plan_id"], F.PLAN_APPROVE_LABEL).json()["outcome"] == "applied"
    assert not alive(world, fresh_junk)
    for key in PROPOSED:
        assert alive(world, mess[key]), key


# ── "unless it changes" ─────────────────────────────────────────────────────

def test_a_kept_document_typed_into_is_judged_again(world, mess, routed):
    keep(world)
    _edit(world, mess["junk"], current_content="something else entirely")
    run_seeded_tidy(world)
    review = the_notice(world)["review"]
    assert labels(review) == ["test"]
    assert review["items"][0]["note"] == "junk title 'test'"
    assert "3 documents you chose to keep were left alone." in chat_rows(world)[-1][1]


def test_what_is_kept_is_what_was_shown(world, mess, routed):
    """A document typed into between the notice and the Keep was kept as it
    was shown, not as it is now — so the next tidy judges what it says now. One
    deleted in the library meanwhile is not marked at all."""
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    _edit(world, mess["junk"], current_content="typed after the notice")
    _edit(world, mess["quotes"], is_active=False)
    res = answer(plan_id, F.PLAN_DECLINE_LABEL)
    assert res.json()["message"] == KEPT_REPLY.replace("Kept 4", "Kept 3")
    assert verdicts(world)[mess["quotes"]] is None
    run_seeded_tidy(world)
    assert labels(the_notice(world)["review"]) == ["test"]


def test_a_rename_or_a_move_is_not_a_change(world, mess, routed):
    """The person kept the document; renaming it or filing it does not make it
    clutter again. `updated_at` would have said both were changes — a rename
    moves it, and so does the AI tidy's own verdict write."""
    keep(world)
    _edit(world, mess["junk"], title="asdf")
    db = world.db()
    try:
        F.file_documents(db, "bob", [mess["empty"]], "Archive")
        db.commit()
    finally:
        db.close()
    run = run_seeded_tidy(world)
    assert run["status"] == "skipped" and "4 documents you chose to keep" in run["result"], run


# ── only the person's answer writes it ──────────────────────────────────────

def test_delete_and_not_now_mark_nothing(world, mess, routed):
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    assert answer(plan_id, "maybe later").status_code == 400
    assert set(verdicts(world).values()) == {None}, "a non-answer marked something"
    assert answer(plan_id, F.PLAN_APPROVE_LABEL).json()["outcome"] == "applied"
    assert set(verdicts(world).values()) == {None}


def test_only_keep_marks_anything(world, mess):
    """The route takes two labels; `answer_review` itself marks documents only
    for Keep, so another "no" from a future caller — sealed as the person's,
    so `plan_answer` reads it as declined — deletes nothing and keeps nothing."""
    run_seeded_tidy(world)
    plan = F.waiting_review(the_notice(world)["review"]["plan_id"], "bob")
    out = document_actions.answer_review(plan, "Not now")
    assert out == {"outcome": "declined", "message": "Nothing was deleted.", "changes": []}
    assert set(verdicts(world).values()) == {None}


def test_the_assistant_cannot_keep_through_app_api(world, mess, routed, monkeypatch):
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    _route_httpx_into(_app(), monkeypatch)
    out = asyncio.run(do_app_api(json.dumps({
        "action": "call", "method": "POST",
        "path": f"/api/document-folders/plans/{plan_id}/answer",
        "body": {"answer": F.PLAN_DECLINE_LABEL}}), owner="bob"))
    assert out.get("status_code") == 403, out
    assert set(verdicts(world).values()) == {None}
    assert [p["plan_id"] for p in waiting()] == [plan_id]


def test_a_token_cannot_keep(world, mess, routed):
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    res = answer(plan_id, F.PLAN_DECLINE_LABEL, headers={"Authorization": "Bearer pk_x"})
    assert res.status_code == 403, res.text
    assert set(verdicts(world).values()) == {None}


def test_a_keep_written_into_the_tidy_chat_is_not_the_person_s(world, mess):
    """A "Don't change anything" the person did not send — the assistant's, in
    the tidy's own chat — is passed over by the reading that guards the keep,
    as it is by the one that guards the delete (`B1005`)."""
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    sid = document_actions.tidy_chat_id("bob")
    document_actions.post_to_tidy_chat(sid, "user", F.PLAN_DECLINE_LABEL)
    plan = F.waiting_review(plan_id, "bob")
    db = world.db()
    try:
        assert document_actions.remember_kept(db, plan) == 0
    finally:
        db.close()
    _d, out = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps({"action": "apply_plan", "plan_id": plan_id})),
        session_id=sid, owner="bob", security_context=NO_TOOL_SECURITY_CONTEXT))
    assert "has not answered" in out.get("error", ""), out
    assert set(verdicts(world).values()) == {None}


def test_a_model_s_keep_is_not_the_person_s(world, mess):
    """The library's AI tidy writes `keep`; a model's guess, made from the
    document's own text, does not hide it from the rules. Nor does a mark for
    content the document no longer has."""
    _edit(world, mess["junk"], tidy_verdict="keep")
    _edit(world, mess["empty"], tidy_verdict="kept:" + _digest("what it used to say"))
    run_seeded_tidy(world)
    assert labels(the_notice(world)["review"]) == ["test", "Untitled", "Re: lunch", "Notes"]


# ── the other two tidies ────────────────────────────────────────────────────

def test_the_agent_s_tidy_leaves_kept_documents_out_and_says_so(world, mess, routed):
    keep(world)
    db = world.db()
    db.add(cdb.Session(id="chat-bob", owner="bob", name="c", model="m", endpoint_url="x"))
    db.commit()
    db.close()

    def tidy():
        _d, out = asyncio.run(execute_tool_block(
            ToolBlock("manage_documents", json.dumps({"action": "tidy"})),
            session_id="chat-bob", owner="bob", security_context=NO_TOOL_SECURITY_CONTEXT))
        return out

    out = tidy()
    assert out["outcome"] == "unchanged", out
    assert out["response"] == ("Nothing to tidy — of your 7 document(s), the only ones that "
                               "look like clutter are the 4 you chose to keep when Documents "
                               "Tidy asked.")
    doc(world, "asdf", content="qwerty")
    out = tidy()
    assert out["outcome"] == "planned", out
    assert [c["title"] for c in out["changes"]] == ["asdf"]
    assert "4 you chose to keep when Documents Tidy asked are left out." in out["response"]


def test_the_library_s_ai_tidy_never_judges_a_kept_document(world, mess, routed, monkeypatch):
    """`POST /api/documents/ai-tidy` skips any document with a verdict, and the
    person's is one: a document kept here is never sent to a model that would
    delete it on a "junk"."""
    import routes.document.document_routes as droutes
    import src.llm_core as llm_core
    import src.task_endpoint as task_endpoint

    keep(world)
    asked = []

    async def model(url, model_name, messages, **kwargs):
        asked.append(messages[-1]["content"])
        return json.dumps(["junk"] * 30)

    monkeypatch.setattr(llm_core, "llm_call_async", model)
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint",
                        lambda owner=None: ("http://127.0.0.1:1/v1", "m", {}))
    monkeypatch.setattr(droutes, "SessionLocal", world.db)
    monkeypatch.setattr(droutes, "get_current_user", lambda request: "bob")
    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    res = TestClient(app).post("/api/documents/ai-tidy")
    assert res.status_code == 200, res.text
    assert res.json()["reviewed"] == 3, res.json()
    for key in PROPOSED:
        assert alive(world, mess[key]), key
        assert verdicts(world)[mess[key]].startswith("kept:"), key
    [prompt] = asked
    assert prompt.count("[") >= 3 and "[3]" not in prompt, "only the three unreviewed were sent"
