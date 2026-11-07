# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1862` — an edited document wakes the task waiting for one.

`document_updated` was in the catalogue and in the trigger picker, and the
only thing that fired it was the email MCP server merging a draft into a
document. A task set to run "when a document is edited" never ran for a
person's edit, a rename, a restore, or the agent's own `update_document` /
`edit_document`. Each of those doors fires it now, with the same envelope as
`document_created` (`document_id`, `title`):

  * after the edit is committed — the task woken reads the new text;
  * only for an edit: the same text saved again, a checkpoint, a restore to
    the text already there, or linking a document to a chat wakes nothing;
  * once a minute per document, however often the editor saves; another
    document is another minute;
  * a workflow whose step edits the document is not woken by its own edit
    (`run_origin`), and its edit does not use up the minute a person's edit
    then needs; a step test wakes nothing and uses up nothing.

Driven through the real document routes, the real agent tools, the real bus
(`fire_document_updated` → `fire_event` → `_handle_event` → `_count_event`)
and a real SQLite file; only the scheduler's hand-off is a recorder
(`Law 20`).
"""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import routes.document.document_routes as droutes  # noqa: E402
import src.database as sdb  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
from core.database import Document, DocumentVersion, ScheduledTask  # noqa: E402
from routes.document.document_helpers import DocumentPatch, DocumentUpdate  # noqa: E402
from src.agent_tools.document_tools import EditDocumentTool, UpdateDocumentTool  # noqa: E402

pytestmark = pytest.mark.asyncio

OWNER = "alice"


class _Woken:
    """The scheduler's side of the hand-off: which task the bus woke, with
    what, and the document's text at that moment (read from the database)."""

    def __init__(self, factory):
        self.factory = factory
        self.runs = []

    async def run_task_now(self, task_id, trigger=None):
        db = self.factory()
        try:
            doc = db.query(Document).filter(Document.id == trigger["data"]["document_id"]).first()
            text = doc.current_content if doc else None
        finally:
            db.close()
        self.runs.append((task_id, trigger["event"], trigger["data"], text))

    def tasks(self):
        return [(task_id, data["document_id"]) for task_id, _e, data, _t in self.runs]


@pytest.fixture()
def world(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'edits.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (cdb, sdb, droutes):
        monkeypatch.setattr(module, "SessionLocal", factory)
    clock = {"now": 1000.0}
    monkeypatch.setattr(event_bus, "_clock", lambda: clock["now"], raising=False)
    monkeypatch.setattr(event_bus, "_document_updated_at", {}, raising=False)
    woken = _Woken(factory)
    monkeypatch.setattr(event_bus, "_task_scheduler", woken)
    db = factory()
    try:
        for doc_id, title, text in (("d1", "Shopping list", "milk"),
                                    ("d2", "Packing list", "socks"),
                                    ("d3", "Reading list", "a book")):
            db.add(Document(id=doc_id, owner=OWNER, title=title, language="markdown",
                            current_content=text, version_count=1, is_active=True))
            db.add(DocumentVersion(id=f"{doc_id}-v1", document_id=doc_id, version_number=1,
                                   content=text, summary="Initial version", source="user"))
        db.add(ScheduledTask(id="listener", owner=OWNER, name="Change log", task_type="llm",
                             prompt="Note the change.", trigger_type="event",
                             trigger_event="document_updated", trigger_count=1,
                             status="active"))
        db.add(ScheduledTask(id="wf", owner=OWNER, name="Doc keeper", task_type="workflow",
                             trigger_type="event", trigger_event="document_updated",
                             trigger_count=1, status="active"))
        db.commit()
    finally:
        db.close()
    return SimpleNamespace(factory=factory, clock=clock, woken=woken)


def _endpoint(method, path):
    router = droutes.setup_document_routes(MagicMock(), None)
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r.endpoint
    raise RuntimeError(f"{method} {path} not found")


PUT = _endpoint("PUT", "/api/document/{doc_id}")
PATCH = _endpoint("PATCH", "/api/document/{doc_id}")
RESTORE = _endpoint("POST", "/api/document/{doc_id}/restore/{num}")
PERSON = SimpleNamespace(state=SimpleNamespace(current_user=OWNER))


def _edit_block(find, replace):
    return f"<<<FIND>>>\n{find}\n<<<REPLACE>>>\n{replace}\n<<<END>>>"


async def _drain():
    """Until every event the edits fired has been handled."""
    me = asyncio.current_task()
    for _ in range(500):
        if not [t for t in asyncio.all_tasks() if t is not me and not t.done()]:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("events still being handled")


def _set_text(world, doc_id, text):
    db = world.factory()
    db.query(Document).filter(Document.id == doc_id).update({"current_content": text})
    db.commit()
    db.close()


async def test_each_door_a_person_edits_through_wakes_the_task_waiting_for_it(world):
    PUT(PERSON, "d1", DocumentUpdate(content="milk, eggs"))
    await _drain()
    PATCH(PERSON, "d2", DocumentPatch(title="Holiday packing"))
    await _drain()
    _set_text(world, "d3", "two books")
    RESTORE(PERSON, "d3", 1)
    await _drain()
    runs = world.woken.runs
    assert sorted(world.woken.tasks()) == sorted([
        ("listener", "d1"), ("wf", "d1"), ("listener", "d2"), ("wf", "d2"),
        ("listener", "d3"), ("wf", "d3")])
    by_doc = {data["document_id"]: (event, data, text) for _t, event, data, text in runs}
    # The envelope `document_created` carries, and the edit already committed.
    assert by_doc["d1"] == ("document_updated",
                            {"document_id": "d1", "title": "Shopping list"}, "milk, eggs")
    assert by_doc["d2"][1] == {"document_id": "d2", "title": "Holiday packing"}
    assert by_doc["d3"][1:] == ({"document_id": "d3", "title": "Reading list"}, "a book")


async def test_what_is_not_an_edit_wakes_nothing(world):
    PUT(PERSON, "d1", DocumentUpdate(content="milk"))
    PUT(PERSON, "d1", DocumentUpdate(content="milk", force_version=True))
    PATCH(PERSON, "d2", DocumentPatch(title="Packing list", language="markdown"))
    PATCH(PERSON, "d2", DocumentPatch(session_id=""))
    RESTORE(PERSON, "d3", 1)
    await _drain()
    assert world.woken.runs == []
    db = world.factory()
    # The checkpoint and the restore were still kept as versions.
    assert db.query(DocumentVersion).filter(DocumentVersion.document_id == "d1").count() == 2
    assert db.query(DocumentVersion).filter(DocumentVersion.document_id == "d3").count() == 2
    db.close()


async def test_a_burst_of_edits_wakes_it_once_a_minute_per_document(world):
    for at, text in ((1000.0, "milk, eggs"), (1010.0, "milk, eggs, bread"),
                     (1059.0, "milk, eggs, bread, jam")):
        world.clock["now"] = at
        PUT(PERSON, "d1", DocumentUpdate(content=text))
        await _drain()
    world.clock["now"] = 1030.0
    PUT(PERSON, "d2", DocumentUpdate(content="socks, hat"))
    await _drain()
    # Three saves of d1 inside its minute: one wake. d2 is its own minute.
    assert sorted(world.woken.tasks()) == sorted([("listener", "d1"), ("wf", "d1"),
                                                  ("listener", "d2"), ("wf", "d2")])
    world.clock["now"] = 1060.0
    PUT(PERSON, "d1", DocumentUpdate(content="milk, eggs, bread, jam, tea"))
    await _drain()
    assert sorted(world.woken.tasks()) == sorted([
        ("listener", "d1"), ("wf", "d1"), ("listener", "d2"), ("wf", "d2"),
        ("listener", "d1"), ("wf", "d1")])
    # The one after the minute names the text as it is now.
    assert world.woken.runs[-1][3] == "milk, eggs, bread, jam, tea"


async def test_the_agents_edits_wake_it_and_a_workflow_does_not_wake_itself(world):
    out = await UpdateDocumentTool().execute("milk, oat milk", {"owner": OWNER, "doc_id": "d1"})
    assert out.get("action") == "update", out
    await _drain()
    assert sorted(world.woken.tasks()) == [("listener", "d1"), ("wf", "d1")]
    assert world.woken.runs[-1][3] == "milk, oat milk"

    # The workflow's own step edits a document: everything else is woken, the
    # workflow is not.
    world.woken.runs.clear()
    with event_bus.run_origin("wf", "Doc keeper", "run-1"):
        out = await EditDocumentTool().execute(_edit_block("socks", "wool socks"),
                                               {"owner": OWNER, "doc_id": "d2"})
    assert out.get("action") == "edit", out
    await _drain()
    assert world.woken.tasks() == [("listener", "d2")]

    # Its edit did not use up the minute a person's edit needs: the person's,
    # a moment later, wakes the workflow too.
    world.woken.runs.clear()
    world.clock["now"] += 5
    PUT(PERSON, "d2", DocumentUpdate(content="wool socks, scarf"))
    await _drain()
    assert sorted(world.woken.tasks()) == [("listener", "d2"), ("wf", "d2")]

    # And the workflow editing it again within its minute wakes nothing more.
    world.woken.runs.clear()
    world.clock["now"] += 5
    with event_bus.run_origin("wf", "Doc keeper", "run-1"):
        await EditDocumentTool().execute(_edit_block("scarf", "red scarf"),
                                         {"owner": OWNER, "doc_id": "d2"})
    await _drain()
    assert world.woken.runs == []


async def test_a_step_test_wakes_nothing_and_takes_no_minute(world):
    with event_bus.run_origin("wf", "Doc keeper", "slot-1", test=True):
        out = await UpdateDocumentTool().execute("milk, cocoa", {"owner": OWNER, "doc_id": "d1"})
    assert out.get("action") == "update", out
    await _drain()
    assert world.woken.runs == []
    PUT(PERSON, "d1", DocumentUpdate(content="milk, cocoa, sugar"))
    await _drain()
    assert sorted(world.woken.tasks()) == [("listener", "d1"), ("wf", "d1")]


async def test_the_minute_is_kept_for_a_minute_of_documents(world, monkeypatch):
    """The record of who fired when is pruned as it grows: an edit a minute
    gone is forgotten, one inside the minute is kept."""
    monkeypatch.setattr(event_bus, "_DOCUMENT_UPDATED_PRUNE_AT", 3)
    for i in range(3):
        assert event_bus.fire_document_updated(OWNER, f"old-{i}", "Old") is True
    world.clock["now"] += 61
    assert event_bus.fire_document_updated(OWNER, "fresh", "Fresh") is True
    assert event_bus.fire_document_updated(OWNER, "fresh", "Fresh") is False
    await _drain()
    assert set(event_bus._document_updated_at) == {(OWNER, "fresh", ())}
