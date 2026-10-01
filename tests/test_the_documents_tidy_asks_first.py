# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1006` — the seeded Documents Tidy proposes, and deletes nothing until the person applies it.

The owner, 2026-10-01 (`D-2026-10-01-03`): *propose, don't delete.* Before this
row the seeded `tidy_documents` task — active for every owner, run after every
fifth new document — `db.delete`d what its rules called clutter: a hard delete,
nothing shown, and an owner-less task judged every owner's documents.

Driven end to end (`Law 20`) on a real SQLite database:

  * the task as `ensure_defaults` seeds it, run by the real scheduler
    (`_execute_task_locked`): a plan in the owner's Documents Tidy chat, a
    notification carrying the list, a run row that says what it asked, and
    every document where it was;
  * the notification's answer, through the real route
    (`POST /api/document-folders/plans/{id}/answer`): the person's "Apply the
    plan" deletes exactly the list (the library's soft delete); "Keep them"
    deletes nothing; "Not now" leaves it waiting and listed;
  * only the person: the assistant's loopback (the real `do_app_api`) and a
    bearer token are refused, another person finds nothing, and a yes injected
    into the tidy's chat is not an answer (`B1005`);
  * the plan is sealed to what was shown; a newer proposal replaces the older;
    an owner-less task and a tidy with nothing to do judge nothing;
  * in the browser, the poller hands the proposal to `documentPlanNotice.js`,
    which offers **Review** once and sends the label the person chose.
"""

import asyncio
import json
import secrets
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import routes.document.document_folder_routes as folder_routes  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
import src.tool_execution as tool_execution  # noqa: E402
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN  # noqa: E402
from src import document_actions, document_folders as F  # noqa: E402
from src.agent_tools import ToolBlock  # noqa: E402
from src.builtin_actions import TaskNoop  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402
from src.tool_approval_scopes import PERSON_MESSAGE_SEAL_FIELD, person_said_at  # noqa: E402
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block  # noqa: E402
from src.tools.system import do_app_api  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402
from tests.test_app_api_cannot_widen_the_owner import _route_httpx_into  # noqa: E402
from tests.test_run_status_is_one_vocabulary import ROW, _h  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", ts)
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    scheduler = TaskScheduler(None)
    previous = event_bus.get_task_scheduler()
    event_bus.set_task_scheduler(scheduler)
    with F._plans_lock:
        F._plans.clear()
    try:
        yield type("World", (), {"db": ts, "scheduler": scheduler})
    finally:
        event_bus.set_task_scheduler(previous)
        with F._plans_lock:
            F._plans.clear()


def doc(world, title, owner="bob", content="something", created=LONG_AGO):
    doc_id = "d-" + uuid.uuid4().hex[:10]
    db = world.db()
    db.add(cdb.Document(id=doc_id, title=title, current_content=content, owner=owner,
                        is_active=True, created_at=created, updated_at=created))
    db.commit()
    db.close()
    return doc_id


@pytest.fixture
def mess(world):
    """Bob's library as the rules see it: four to go, three to stay."""
    return {
        "junk": doc(world, "test"),
        "empty": doc(world, "Untitled", content=""),
        "quotes": doc(world, "Re: lunch", content="On Mon, Bob wrote:\n> lunch?\n> at 1"),
        "copy_long": doc(world, "Notes", content="the same notes", created=LONG_AGO + timedelta(days=1)),
        "copy": doc(world, "Notes", content="the same notes"),
        "keep": doc(world, "Budget 2026", content="real numbers"),
        "fresh": doc(world, "test", content="", created=datetime.utcnow() - timedelta(minutes=1)),
    }


def alive(world, doc_id):
    db = world.db()
    try:
        return bool(db.query(cdb.Document).filter(cdb.Document.id == doc_id).one().is_active)
    finally:
        db.close()


def everything(world):
    db = world.db()
    try:
        return sorted((d.id, d.owner, bool(d.is_active), d.current_content)
                      for d in db.query(cdb.Document).all())
    finally:
        db.close()


def run_seeded_tidy(world, owner="bob"):
    """The task `ensure_defaults` seeds, run once by the scheduler; its run row."""
    asyncio.run(world.scheduler.ensure_defaults(owner))
    db = world.db()
    try:
        task = (db.query(cdb.ScheduledTask).filter(cdb.ScheduledTask.owner == owner)
                .filter(cdb.ScheduledTask.action == "tidy_documents").one())
        task_id = task.id
        run_id = "run-" + uuid.uuid4().hex[:6]
        db.add(cdb.TaskRun(id=run_id, task_id=task_id, status="queued"))
        db.commit()
    finally:
        db.close()
    return run_task(world, task_id, run_id)


def run_task(world, task_id, run_id):
    asyncio.run(world.scheduler._execute_task_locked(
        task_id, run_id, gate_foreground=False, release_executing=False))
    db = world.db()
    try:
        run = db.query(cdb.TaskRun).filter(cdb.TaskRun.id == run_id).one()
        return {"status": run.status, "result": run.result}
    finally:
        db.close()


def chat_rows(world, owner="bob"):
    db = world.db()
    try:
        sid = document_actions.tidy_chat_id(owner)
        return [(m.role, m.content, json.loads(m.meta_data or "{}"))
                for m in db.query(cdb.ChatMessage).filter(cdb.ChatMessage.session_id == sid)
                .order_by(cdb.ChatMessage.timestamp).all()]
    finally:
        db.close()


# ── the answer route, behind what `app.py`'s middleware does ─────────────────

def _app(person="bob"):
    """The real folder routes. A request carrying the internal-tool token is the
    assistant's loopback, attributed to `X-Pantheon-Owner` as `app.py` does; a
    bearer token is marked as one; anything else is *person*'s browser."""
    app = FastAPI()

    @app.middleware("http")
    async def _attribute(request, call_next):
        header = request.headers.get(INTERNAL_TOOL_HEADER)
        request.state.api_token = False
        if header and secrets.compare_digest(header, INTERNAL_TOOL_TOKEN):
            request.state.current_user = request.headers.get("X-Pantheon-Owner")
        elif request.headers.get("authorization"):
            request.state.api_token = True
            request.state.api_token_owner = person
            request.state.current_user = "api"
        else:
            request.state.current_user = person
        return await call_next(request)

    router = APIRouter()
    folder_routes.register_document_folder_routes(router)
    app.include_router(router)
    return app


@pytest.fixture
def routed(monkeypatch):
    def _owner(request, *_a):
        from src.auth_helpers import effective_user
        return effective_user(request)

    monkeypatch.setattr(folder_routes, "require_privilege", _owner)
    monkeypatch.setattr(folder_routes, "get_current_user", _owner)


def answer(plan_id, label, person="bob", headers=None):
    client = TestClient(_app(person))
    return client.post(f"/api/document-folders/plans/{plan_id}/answer",
                       json={"answer": label}, headers=headers or {})


def waiting(person="bob"):
    res = TestClient(_app(person)).get("/api/document-folders/plans")
    assert res.status_code == 200, res.text
    return res.json()["plans"]


def the_notice(world, owner="bob"):
    notes = world.scheduler.pop_notifications(owner)
    assert len(notes) == 1, notes
    return notes[0]


# ── the scheduled task proposes ─────────────────────────────────────────────

def test_the_seeded_task_proposes_and_deletes_nothing(world, mess):
    before = everything(world)
    run = run_seeded_tidy(world)
    assert run["status"] == "success", run
    assert run["result"].startswith("Asked you about deleting 4 of 7: "), run
    assert run["result"].endswith("This run deleted nothing."), run
    assert everything(world) == before, "the scheduled tidy deleted before anyone said yes"

    note = the_notice(world)
    review = note["review"]
    assert note["task_name"] == "Documents Tidy" and note["owner"] == "bob"
    assert review["kind"] == "document_plan" and review["count"] == 4
    assert [i["label"] for i in review["items"]] == ["test", "Untitled", "Re: lunch", "Notes"]
    assert [i["note"] for i in review["items"]] == [
        "junk title 'test'", "empty", "email quote-chain only",
        "a duplicate — the fullest copy stays"]
    assert review["approve"] == F.PLAN_APPROVE_LABEL and review["decline"] == F.PLAN_DECLINE_LABEL
    assert "digest" not in json.dumps(note), "the seal stays on the server"

    # The record, in the owner's own Documents Tidy chat in Tasks.
    db = world.db()
    try:
        chat = db.query(cdb.Session).filter(
            cdb.Session.id == document_actions.tidy_chat_id("bob")).one()
        assert (chat.name, chat.owner, chat.folder) == ("Documents Tidy", "bob", "Tasks")
    finally:
        db.close()
    [(role, text, _meta)] = chat_rows(world)
    assert role == "assistant" and "Nothing has been deleted." in text
    assert "- deleted \"test\" (was in Unfiled) — junk title 'test'" in text


def test_the_notice_is_the_owner_s_alone(world, mess):
    doc(world, "asdf", owner="ann")
    run_seeded_tidy(world)
    assert world.scheduler.pop_notifications("ann") == []
    assert waiting("ann") == []
    assert the_notice(world)["owner"] == "bob"


def test_only_the_owner_s_live_documents_are_judged(world, mess):
    """Ann's clutter is not Bob's to be asked about, and a document already
    deleted is nothing a person can see — neither is judged or counted."""
    doc(world, "asdf", owner="ann")
    gone = doc(world, "test")
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == gone).update({cdb.Document.is_active: False})
    db.commit()
    db.close()
    run = run_seeded_tidy(world)
    assert run["status"] == "success" and "deleting 4 of 7:" in run["result"], run
    review = the_notice(world)["review"]
    assert [i["label"] for i in review["items"]] == ["test", "Untitled", "Re: lunch", "Notes"]


# ── the person answers from the notice ──────────────────────────────────────

def test_apply_deletes_exactly_the_list_and_only_then(world, mess, routed):
    from src.agent_tools import document_tools

    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    # The person had one of them open; once it is deleted it is not "open".
    document_tools.set_active_document(mess["empty"])
    res = answer(plan_id, F.PLAN_APPROVE_LABEL)
    assert document_tools.get_active_document() is None
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == "applied" and body["message"] == "Deleted 4 documents."
    for key in ("junk", "empty", "quotes", "copy"):
        assert not alive(world, mess[key]), key
    for key in ("copy_long", "keep", "fresh"):
        assert alive(world, mess[key]), key
    # The library's own delete: the rows stay, switched off.
    assert len(everything(world)) == 7
    # The record: the proposal, the person's sealed answer, what happened.
    rows = chat_rows(world)
    assert [r for r, _t, _m in rows] == ["assistant", "user", "assistant"]
    _role, said, meta = rows[1]
    assert said == F.PLAN_APPROVE_LABEL
    assert person_said_at(meta, document_actions.tidy_chat_id("bob"), said) is not None
    assert rows[2][1].startswith("Deleted 4 documents.")
    again = answer(plan_id, F.PLAN_APPROVE_LABEL)
    assert again.status_code == 404, "answered once, and gone"


def test_keep_them_deletes_nothing_and_ends_it(world, mess, routed):
    before = everything(world)
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    res = answer(plan_id, F.PLAN_DECLINE_LABEL)
    assert res.status_code == 200 and res.json()["outcome"] == "declined", res.text
    assert everything(world) == before
    assert waiting() == []


def test_not_now_leaves_it_waiting_and_offered_again(world, mess, routed):
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    [listed] = waiting()
    assert listed["plan_id"] == plan_id and listed["count"] == 4
    assert listed["items"][0] == {"label": "test", "note": "junk title 'test'"}
    assert answer(plan_id, "maybe later").status_code == 400
    assert [p["plan_id"] for p in waiting()] == [plan_id], "a bad answer is no answer"


# ── only the person ─────────────────────────────────────────────────────────

def test_the_assistant_cannot_answer_it_through_app_api(world, mess, routed, monkeypatch):
    before = everything(world)
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    _route_httpx_into(_app(), monkeypatch)
    out = asyncio.run(do_app_api(json.dumps({
        "action": "call", "method": "POST",
        "path": f"/api/document-folders/plans/{plan_id}/answer",
        "body": {"answer": F.PLAN_APPROVE_LABEL}}), owner="bob"))
    assert out.get("status_code") == 403, out
    assert everything(world) == before
    assert [p["plan_id"] for p in waiting()] == [plan_id]


def test_a_token_cannot_answer_it(world, mess, routed):
    before = everything(world)
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    res = answer(plan_id, F.PLAN_APPROVE_LABEL, headers={"Authorization": "Bearer pk_x"})
    assert res.status_code == 403, res.text
    assert everything(world) == before


def test_another_person_finds_nothing_to_answer(world, mess, routed):
    before = everything(world)
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    assert answer(plan_id, F.PLAN_APPROVE_LABEL, person="ann").status_code == 404
    assert everything(world) == before


def test_a_yes_written_into_the_tidy_chat_is_not_the_person_s(world, mess):
    """The assistant running in the Documents Tidy chat, after a user message
    reading "Apply the plan" that the person did not send (`B1005`)."""
    before = everything(world)
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    sid = document_actions.tidy_chat_id("bob")
    document_actions.post_to_tidy_chat(sid, "user", F.PLAN_APPROVE_LABEL)
    _d, out = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps({"action": "apply_plan", "plan_id": plan_id})),
        session_id=sid, owner="bob", security_context=NO_TOOL_SECURITY_CONTEXT))
    assert out["exit_code"] == 1 and "has not answered" in out["error"], out
    assert everything(world) == before


def test_an_agent_s_plan_is_not_answered_from_a_notice(world, routed):
    """The route answers a proposal made to be answered there; an agent's plan
    is answered on the card in the chat that asked, and is not found here."""
    gone = doc(world, "Old draft")
    db = world.db()
    db.add(cdb.Session(id="chat-bob", owner="bob", name="c", model="m", endpoint_url="x"))
    db.commit()
    db.close()
    _d, plan = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps({"action": "delete", "document_id": gone})),
        session_id="chat-bob", owner="bob", security_context=NO_TOOL_SECURITY_CONTEXT))
    assert plan["outcome"] == "planned"
    assert answer(plan["plan_id"], F.PLAN_APPROVE_LABEL).status_code == 404
    assert waiting() == [] and alive(world, gone)


# ── what it is sealed to, and what replaces it ──────────────────────────────

def test_a_document_written_in_after_the_notice_is_not_deleted(world, routed):
    empty = doc(world, "Untitled", content="")
    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == empty).update(
        {cdb.Document.current_content: "my draft, typed after the notice"})
    db.commit()
    db.close()
    res = answer(plan_id, F.PLAN_APPROVE_LABEL)
    assert res.status_code == 200 and res.json()["outcome"] == "refused", res.text
    assert "changed after this plan was shown" in res.json()["message"]
    assert alive(world, empty)


def test_a_newer_proposal_replaces_the_older(world, mess, routed):
    run_seeded_tidy(world)
    first = the_notice(world)["review"]["plan_id"]
    run_seeded_tidy(world)
    second = the_notice(world)["review"]["plan_id"]
    assert first != second
    assert answer(first, F.PLAN_APPROVE_LABEL).status_code == 404
    assert [p["plan_id"] for p in waiting()] == [second]


# ── nobody's task, and nothing to do ────────────────────────────────────────

def test_an_owner_less_task_judges_no_one(world):
    """It used to judge every owner's documents (`if owner: … else: all`)."""
    for owner in ("bob", "ann"):
        doc(world, "test", owner=owner)
        doc(world, "Untitled", owner=owner, content="")
    before = everything(world)
    with pytest.raises(TaskNoop, match="has no owner"):
        asyncio.run(document_actions.run_document_tidy(""))
    db = world.db()
    db.add(cdb.ScheduledTask(id="nobody", owner=None, name="Documents Tidy", task_type="action",
                             action="tidy_documents", status="active", trigger_type="event"))
    db.add(cdb.TaskRun(id="run-n", task_id="nobody", status="queued"))
    db.commit()
    db.close()
    run = run_task(world, "nobody", "run-n")
    assert run["status"] == "skipped" and "judged no one's documents" in run["result"], run
    assert everything(world) == before
    assert F.waiting_reviews(F.EVERY_OWNER) == []
    assert world.scheduler.pop_notifications() == []


def test_nothing_to_tidy_is_a_skip_with_no_notice(world):
    doc(world, "Budget 2026", content="real numbers")
    run = run_seeded_tidy(world)
    assert run["status"] == "skipped" and run["result"] == "scanned 1 document(s), no junk", run
    assert world.scheduler.pop_notifications("bob") == []
    assert chat_rows(world) == []


# ── the browser ─────────────────────────────────────────────────────────────

def test_the_poller_hands_the_proposal_over_instead_of_announcing_it():
    review = {"kind": "document_plan", "plan_id": "p1", "count": 2}
    out = _h(ROW, "notify", json.dumps([
        {"status": "success", "task_name": "Documents Tidy", "body": "2 documents…",
         "review": review},
        {"status": "success", "task_name": "Nightly"},
    ]))
    assert out["offered"] == [review]
    assert out["said"] == [{"how": "toast", "msg": "Task finished: Nightly"}], out


_UI = ui_default_stub(
    "showToast: (msg, opts) => { toasts.push({ msg, action: opts && opts.action }); "
    "if (opts && opts.onAction) actions.push(opts.onAction); },\n"
    "  showError: (msg) => errors.push(msg),\n"
    "  styledConfirm: async (message, opts) => { asked.push({ message, opts }); return globalThis.__choice; },",
    exports="export const toasts = [];\nexport const errors = [];\n"
            "export const actions = [];\nexport const asked = [];",
)


@pytest.fixture(scope="module")
def notice_sandbox(tmp_path_factory):
    box = tmp_path_factory.mktemp("plan_notice")
    shutil.copy(ROOT / "static" / "js" / "documentPlanNotice.js", box / "documentPlanNotice.js")
    (box / "ui.js").write_text(_UI, encoding="utf-8")
    return box


def _node(box, script):
    entry = box / "case.mjs"
    entry.write_text(
        "globalThis.window = { location: { origin: '' }, focus() {} };\n"
        "const sent = [];\n"
        "globalThis.fetch = async (url, init) => { sent.push({ url, init: init || null });\n"
        "  if (url.endsWith('/plans')) return { ok: true, json: async () => ({ plans: globalThis.__waiting || [] }) };\n"
        "  return { ok: globalThis.__ok !== false, json: async () => globalThis.__reply || {} }; };\n"
        "const ui = await import('./ui.js');\n"
        "const notice = await import('./documentPlanNotice.js');\n"
        + script, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=box, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_REVIEW = json.dumps({
    "kind": "document_plan", "plan_id": "p/1", "title": "Documents Tidy", "count": 2,
    "summary": "2 documents look like clutter. Nothing is deleted until you say so.",
    "question": "Delete these 2 documents?", "more": 0,
    "items": [{"label": "<img src=x>", "note": "empty"}, {"label": "test", "note": "junk title 'test'"}],
    "approve": "Apply the plan", "decline": "Don't change anything",
})


@pytest.mark.parametrize("choice,label", [
    ("true", "Apply the plan"), ("'alternate'", "Don't change anything"), ("false", None)])
def test_review_sends_the_label_the_person_chose(notice_sandbox, choice, label):
    out = _node(notice_sandbox, f"""
const review = {_REVIEW};
globalThis.__choice = {choice};
globalThis.__reply = {{ outcome: 'applied', message: 'Deleted 2 documents.' }};
const first = notice.offerDocumentPlan(review);
const again = notice.offerDocumentPlan(review);
await ui.actions[0]();
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({{ first, again, toasts: ui.toasts, asked: ui.asked, sent }}));
""")
    assert out["first"] is True and out["again"] is False, "offered once per page"
    assert out["toasts"][0] == {
        "msg": "Documents Tidy: 2 documents look like clutter. Nothing is deleted until you say so.",
        "action": "Review"}
    [asked] = out["asked"]
    assert asked["message"] == "Delete these 2 documents?", "the question carries the count"
    assert asked["opts"]["confirmText"] == "Delete" and asked["opts"]["danger"] is True
    assert asked["opts"]["alternateText"] == "Keep" and asked["opts"]["cancelText"] == "Not now"
    assert asked["opts"]["details"]["items"][0] == {"label": "<img src=x>", "note": "empty"}
    if label is None:
        assert out["sent"] == [], "Not now sends nothing"
    else:
        [sent] = out["sent"]
        assert sent["url"] == "/api/document-folders/plans/p%2F1/answer"
        assert json.loads(sent["init"]["body"]) == {"answer": label}
        assert out["toasts"][-1]["msg"] == "Documents Tidy: Deleted 2 documents."


def test_a_refused_answer_is_said_and_a_reload_offers_what_waits(notice_sandbox):
    out = _node(notice_sandbox, f"""
globalThis.__waiting = [{_REVIEW}, {_REVIEW}, {{ kind: 'something_else', plan_id: 'x' }}];
const shown = await notice.offerWaitingDocumentPlans();
globalThis.__choice = true;
globalThis.__ok = false;
globalThis.__reply = {{ detail: 'That tidy is no longer waiting.' }};
await ui.actions[0]();
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({{ shown, errors: ui.errors, urls: sent.map((s) => s.url) }}));
""")
    assert out["shown"] == 1, "one proposal, offered once; anything else ignored"
    assert out["urls"] == ["/api/document-folders/plans", "/api/document-folders/plans/p%2F1/answer"]
    assert out["errors"] == ["Documents Tidy: That tidy is no longer waiting."]


def test_it_waits_longer_than_an_agent_s_plan(world, mess, monkeypatch):
    """An agent's plan lapses after 30 minutes, because the person is in the
    chat that asked. Nobody is waiting on the tidy's, so it waits a week."""
    import time as _time

    run_seeded_tidy(world)
    plan_id = the_notice(world)["review"]["plan_id"]
    start = _time.monotonic()
    monkeypatch.setattr(F.time, "monotonic", lambda: start + 3 * 24 * 3600)
    assert [p.plan_id for p in F.waiting_reviews("bob")] == [plan_id]
    monkeypatch.setattr(F.time, "monotonic", lambda: start + 8 * 24 * 3600)
    assert F.waiting_reviews("bob") == []


def test_tasks_js_loads_the_notice_when_a_proposal_arrives(notice_sandbox):
    """`tasks.js` loads `documentPlanNotice.js` on first use; its two loaders,
    cut out of the shipped file and run where the module sits beside them."""
    from tests.helpers.js_source import js_function

    src = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    loaders = "".join(
        f"function {name}(review) {js_function(src, 'function ' + name)}\n"
        for name in ("_offerDocumentPlan", "_offerWaitingDocumentPlans"))
    out = _node(notice_sandbox, f"""
{loaders}
globalThis.__waiting = [{{ ...{_REVIEW}, plan_id: 'p2' }}];
_offerDocumentPlan({_REVIEW});
_offerWaitingDocumentPlans();
await new Promise((r) => setTimeout(r, 50));
console.log(JSON.stringify({{ toasts: ui.toasts.map((t) => t.action) }}));
""")
    assert out["toasts"] == ["Review", "Review"], out
