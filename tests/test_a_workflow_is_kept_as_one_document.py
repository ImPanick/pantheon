# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05`'s API half — a workflow is one document, kept, versioned and
owner-scoped (`/work/notes/SLICE-B-DESIGN.md` § 1.1, § 5, contract `C2`).

**Measured before this file, on `5654cd4`:** no `/api/workflows` route existed
(every path below answered 404 through `app.py`'s router), and a workflow
could only be a chain of task rows with no name, version or document.

What these cases drive: the real `routes/workflow/workflow_routes.py` and the
real task routes, through `TestClient`, on a real SQLite file with the
database's own foreign keys on (`PRAGMA foreign_keys=ON` is set for every
engine by `core.database`), and the real `src/workflow_store.py` behind them.
The engine's half (`C1`: the three tables, `src.workflow_document`,
`src.workflow_runs`, `admin_only_action_of`) is `wf-engine`'s and is on
another branch; `tests/helpers/workflow_contract.py` stands in for each piece
only while it is absent, so after the merge these cases drive the real engine
and assert only what `C1`/`C2` fix. The scheduler is a recorder: nothing here
runs a step (`test_workflow_node` and the walker are the engine's).

The shared fixtures (`wf_db`, `sched`, `client`, `admins`, the graph builders)
are imported by the other Slice B API files (`Law 14`).
"""

from __future__ import annotations

import json
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from tests.helpers import workflow_contract as wc  # noqa: E402

SUMMARY_KEYS = {"id", "name", "task_id", "trigger_status", "version", "step_count",
                "last_run", "converted_from", "updated_at"}
DOC_KEYS = SUMMARY_KEYS | {"graph", "trigger_task", "versions_kept"}
LAST_RUN_KEYS = {"id", "status", "started_at", "finished_at", "dry"}
VERSION_KEYS = {"version", "name", "saved_at", "source", "step_count", "current"}


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def wf_db(monkeypatch, tmp_path):
    """A real SQLite file with every table, the `C1` fakes where absent."""
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    faked = wc.install(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'workflows.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    wc.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    factory.faked = faked
    return factory


@pytest.fixture()
def admins(monkeypatch):
    """Who is an admin: a set the test fills. Patched where each door reads it
    — the policy module (the store and `manage_tasks` import it inside their
    functions) and the task routes' module-level import."""
    import routes.task.task_routes as task_routes
    import src.task_action_policy as tap
    who = set()
    check = lambda owner: owner in who  # noqa: E731
    monkeypatch.setattr(tap, "owner_has_admin_task_privileges", check)
    monkeypatch.setattr(task_routes, "owner_has_admin_task_privileges", check)
    return who


class Scheduler:
    """The scheduler's surface these routes call, as recorders.

    `run_task_now(dry=True)` writes what the engine's dry run of a workflow
    writes (design § 2.6): one `skipped` run headed `DRY_RUN_HEADLINE`, and one
    `dry` node record per step, breadth first from the entry, each holding its
    plan lines. A real run records the call and runs nothing.
    """

    def __init__(self, factory):
        self.factory = factory
        self._executing = set()
        self.runs = []
        self.tests = []
        self.result = {"status": "success", "text": "The summary.", "data": {"n": 3},
                       "steps": [{"kind": "progress", "detail": "Asked the model"}],
                       "model": "m-1", "took_ms": 12}

    async def ensure_defaults(self, owner):
        return None

    async def stop_task(self, task_id):
        return False

    async def run_task_now(self, task_id, *, force=False, trigger=None, dry=False,
                           started_by="background"):
        self.runs.append({"task_id": task_id, "dry": dry, "started_by": started_by,
                          "trigger": trigger})
        if not dry:
            return True
        from src.task_scheduler import DRY_RUN_HEADLINE
        Workflow, _, TaskRunNode = wc.models()
        doc = wc.document()
        db = self.factory()
        try:
            run_id = str(uuid.uuid4())
            wf = db.query(Workflow).filter(Workflow.task_id == task_id).first()
            graph = json.loads(wf.graph) if wf is not None else {"nodes": [], "edges": []}
            by_id = {n["id"]: n for n in graph["nodes"]}
            steps = [{"kind": "dry-run", "detail": DRY_RUN_HEADLINE}]
            db.add(TaskRun(id=run_id, task_id=task_id, status="skipped",
                           result=DRY_RUN_HEADLINE, started_at=cdb.utcnow_naive(),
                           finished_at=cdb.utcnow_naive()))
            db.flush()
            for seq, entry in enumerate(doc.reachable_bfs(graph), 1):
                node = by_id[entry["node_id"] if isinstance(entry, dict) else entry[0]]
                line = f"Would run “{node['label']}”."
                steps.append({"kind": "dry-run", "detail": line})
                db.add(TaskRunNode(id=str(uuid.uuid4()), run_id=run_id, node_id=node["id"],
                                   kind=node["kind"], label=node["label"], seq=seq,
                                   status="skipped", dry=True, workflow_version=wf.version,
                                   steps=json.dumps([{"kind": "dry-run", "detail": line}])))
            db.query(TaskRun).filter(TaskRun.id == run_id).first().steps = json.dumps(steps)
            db.commit()
            return run_id
        finally:
            db.close()

    async def test_workflow_node(self, task, workflow_name, node, *, input_envelope, timeout=None):
        self.tests.append({"task_id": task.id, "workflow_name": workflow_name, "node": node,
                           "input": input_envelope, "timeout": timeout})
        return dict(self.result)


@pytest.fixture()
def sched(wf_db):
    return Scheduler(wf_db)


@pytest.fixture()
def client(wf_db, sched, admins, monkeypatch):
    """Both routers, as `app.py` includes them, the caller named by a header."""
    import routes.task.task_routes as task_routes
    import routes.workflow.workflow_routes as workflow_routes
    import src.task_action_policy as tap
    monkeypatch.setattr(task_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(workflow_routes, "SessionLocal", wf_db)
    monkeypatch.setattr(task_routes, "record_admin_refusal", tap.record_admin_refusal)
    import routes.prefs_routes as prefs
    monkeypatch.setattr(prefs, "_load_for_user", lambda user=None: {})
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(sched))
    app.include_router(workflow_routes.setup_workflow_routes(sched))
    return TestClient(app)


# ── builders ─────────────────────────────────────────────────────────────────

def step(node_id, kind="llm", label=None, **config):
    if kind in ("llm", "research"):
        config.setdefault("prompt", f"Do {node_id}.")
    return {"id": node_id, "kind": kind, "label": label or node_id.upper(), "config": config,
            "position": None, "pinned": None}


def graph(nodes, edges=(), start=None):
    return {"v": 1, "start": {"position": start}, "nodes": list(nodes),
            "edges": [{"from": a, "port": p, "to": b} for a, p, b in edges]}


TWO = graph([step("n1", label="Summarise my inbox"), step("n2", label="Send me the summary")],
            [("n1", "success", "n2")])


def call(client, method, url, user="alice", **kw):
    return client.request(method, url, headers={"x-test-user": user}, **kw)


def new(client, name="Morning digest", user="alice"):
    res = call(client, "POST", "/api/workflows", user=user, json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["workflow"]


def save(client, wf, g=TWO, *, base=None, name=None, user="alice", check=False):
    body = {"graph": g, "base_version": wf["version"] if base is None else base}
    if name is not None:
        body["name"] = name
    url = f"/api/workflows/{wf['id']}" + ("?check=true" if check else "")
    return call(client, "PUT", url, user=user, json=body)


def rows(factory, model, **where):
    db = factory()
    try:
        q = db.query(model)
        for key, value in where.items():
            q = q.filter(getattr(model, key) == value)
        return q.all()
    finally:
        db.close()


def stored(factory, wf_id):
    Workflow = wc.models()[0]
    (row,) = rows(factory, Workflow, id=wf_id)
    return row


def versions(factory, wf_id):
    WorkflowVersion = wc.models()[1]
    return sorted(r.version for r in rows(factory, WorkflowVersion, workflow_id=wf_id))


# ── create, read, list ───────────────────────────────────────────────────────

def test_a_new_workflow_is_one_document_started_by_one_task_and_switched_off(client, wf_db):
    res = call(client, "POST", "/api/workflows", json={"name": "Morning digest"})
    assert res.status_code == 200, res.text
    body = res.json()
    wf = body["workflow"]
    assert set(wf) == DOC_KEYS
    assert (wf["name"], wf["version"], wf["step_count"], wf["versions_kept"]) == (
        "Morning digest", 1, 0, 1)
    assert wf["graph"]["nodes"] == [] and wf["graph"]["edges"] == []
    trigger = wf["trigger_task"]
    assert (trigger["task_type"], trigger["status"], trigger["name"], trigger["workflow_id"]) == (
        "workflow", "paused", "Morning digest", wf["id"])
    assert wf["trigger_status"] == "paused" and wf["task_id"] == trigger["id"]
    assert any("switched off" in note for note in body["notes"])
    # One document, one start, one version — and that start is the only task.
    assert [t.task_type for t in rows(wf_db, ScheduledTask)] == ["workflow"]
    assert versions(wf_db, wf["id"]) == [1]


def test_the_shelf_lists_only_your_own_workflows_as_summaries(client):
    mine = new(client, "Mine")
    new(client, "Bob's", user="bob")
    res = call(client, "GET", "/api/workflows")
    assert res.status_code == 200
    listed = res.json()["workflows"]
    assert [w["id"] for w in listed] == [mine["id"]]
    assert set(listed[0]) == SUMMARY_KEYS
    assert listed[0]["last_run"] is None and listed[0]["converted_from"] is None


def test_the_shelf_reads_the_last_real_run_and_never_a_dry_one(client, wf_db):
    """`B1054`'s rule on the shelf: a plan is never a last run."""
    from src.task_scheduler import DRY_RUN_HEADLINE
    wf = new(client)
    db = wf_db()
    try:
        early, late = cdb.utcnow_naive(), cdb.utcnow_naive()
        db.add(TaskRun(id="real", task_id=wf["task_id"], status="error", error="It broke",
                       started_at=early.replace(year=early.year - 1), finished_at=early))
        db.add(TaskRun(id="plan", task_id=wf["task_id"], status="skipped",
                       result=DRY_RUN_HEADLINE, started_at=late, finished_at=late))
        db.commit()
    finally:
        db.close()
    (summary,) = call(client, "GET", "/api/workflows").json()["workflows"]
    assert set(summary["last_run"]) == LAST_RUN_KEYS
    assert (summary["last_run"]["id"], summary["last_run"]["status"],
            summary["last_run"]["dry"]) == ("real", "error", False)
    assert call(client, "GET", f"/api/workflows/{wf['id']}").json()["workflow"]["last_run"]["id"] == "real"


@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "", None),
    ("PUT", "", {"positions": {}}),
    ("DELETE", "", None),
    ("GET", "/versions", None),
    ("GET", "/versions/1", None),
    ("POST", "/versions/1/restore", {"base_version": 1}),
    ("POST", "/switch", {"on": True}),
    ("POST", "/restore-chain", None),
    ("GET", "/runs/r1", None),
    ("POST", "/nodes/n1/test", {"node": {"id": "n1"}, "source": "none"}),
])
def test_another_owners_workflow_is_not_there_at_any_door(client, method, suffix, body):
    wf = new(client)
    res = call(client, method, f"/api/workflows/{wf['id']}{suffix}", user="bob",
               **({"json": body} if body is not None else {}))
    assert res.status_code == 404, res.text
    assert res.json() == {"detail": "No such workflow."}


def test_a_route_that_only_reads_the_database_never_holds_the_event_loop(client, monkeypatch):
    """A `def` handler is run by FastAPI in its threadpool; the refusal wrapper
    must not turn it into a coroutine, or its queries would run on the event
    loop every chat stream shares. Probed where the work happens: the list's
    summaries are built with no running loop in their thread."""
    import asyncio
    import routes.workflow.workflow_routes as workflow_routes
    new(client)
    seen = []
    real = workflow_routes.store.summaries

    def probe(*args, **kwargs):
        seen.append(asyncio._get_running_loop() is None)
        return real(*args, **kwargs)
    monkeypatch.setattr(workflow_routes.store, "summaries", probe)
    assert call(client, "GET", "/api/workflows").status_code == 200
    assert seen == [True], "the list's database work ran on the event loop"


# ── a save, and the version policy (`P8-10`'s) ──────────────────────────────

def test_a_save_that_changes_the_content_makes_one_version_and_renames_the_start(client, wf_db):
    wf = new(client)
    res = save(client, wf, TWO, name="Inbox digest")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["saved"] == "new_version"
    assert (out["workflow"]["version"], out["workflow"]["name"],
            out["workflow"]["step_count"]) == (2, "Inbox digest", 2)
    assert out["workflow"]["trigger_task"]["name"] == "Inbox digest"
    assert versions(wf_db, wf["id"]) == [1, 2]
    (version_row,) = rows(wf_db, wc.models()[1], workflow_id=wf["id"], version=2)
    assert version_row.source == "user"


def test_a_save_that_moves_only_where_steps_sit_makes_no_version(client, wf_db):
    wf = new(client)
    wf = save(client, wf, TWO).json()["workflow"]
    moved = json.loads(json.dumps(TWO))
    moved["nodes"][0]["position"] = [40, 80]
    moved["start"]["position"] = [0, 10]
    res = save(client, wf, moved)
    assert res.status_code == 200, res.text
    assert res.json()["saved"] == "unchanged"
    assert res.json()["workflow"]["version"] == 2
    assert versions(wf_db, wf["id"]) == [1, 2]
    kept = json.loads(stored(wf_db, wf["id"]).graph)
    assert kept["nodes"][0]["position"] == [40, 80], "where a step sits is saved either way"


def test_a_stale_save_is_refused_and_writes_nothing(client, wf_db):
    wf = new(client)
    first = save(client, wf, TWO)
    assert first.status_code == 200
    other = graph([step("n1", label="Something else")])
    res = save(client, wf, other, base=1)
    assert res.status_code == 409
    assert set(res.json()) == {"detail"}
    assert "version 2" in res.json()["detail"] and "Nothing was saved" in res.json()["detail"]
    assert [n["label"] for n in json.loads(stored(wf_db, wf["id"]).graph)["nodes"]] == [
        "Summarise my inbox", "Send me the summary"]
    assert versions(wf_db, wf["id"]) == [1, 2]


def test_a_save_must_say_which_version_it_started_from(client):
    wf = new(client)
    res = call(client, "PUT", f"/api/workflows/{wf['id']}", json={"graph": TWO})
    assert res.status_code == 400
    assert "base_version" in res.json()["detail"]


def test_check_answers_what_a_save_would_and_writes_nothing(client, wf_db):
    wf = new(client)
    before = stored(wf_db, wf["id"])
    ok = save(client, wf, TWO, check=True)
    assert (ok.status_code, ok.json()) == (200, {"ok": True, "check": True})
    looped = graph([step("n1"), step("n2")], [("n1", "success", "n2"), ("n2", "success", "n1")])
    refused = save(client, wf, looped, check=True)
    assert refused.status_code == 400
    stale = save(client, wf, TWO, base=7, check=True)
    assert stale.status_code == 409
    after = stored(wf_db, wf["id"])
    assert (after.graph, after.version, after.name) == (before.graph, before.version, before.name)
    assert versions(wf_db, wf["id"]) == [1]


def test_a_document_the_engine_refuses_is_refused_with_its_own_sentence(client, wf_db):
    wf = new(client)
    looped = graph([step("n1"), step("n2")], [("n1", "success", "n2"), ("n2", "error", "n1")])
    res = save(client, wf, looped)
    assert res.status_code == 400
    body = res.json()
    assert set(body) == {"detail", "reason", "node_ids"}
    assert isinstance(body["detail"], str) and body["detail"].strip()
    doc = wc.document()
    assert body["reason"] in doc.WORKFLOW_REFUSAL_REASONS
    # The engine's own sentence, word for word (`Law 10`: the same at save and run).
    refusal = doc.validate_document(doc.parse_graph(json.dumps(looped)), owner="alice",
                                    tasks_by_id={}, crew_ids=set(), owner_is_admin=True,
                                    own_task_id=wf["task_id"])
    assert body["detail"] == refusal.sentence and body["node_ids"] == list(refusal.node_ids)
    assert versions(wf_db, wf["id"]) == [1]


def test_an_admin_only_step_is_a_403_for_anyone_but_an_admin(client, admins):
    from src.task_action_policy import admin_refusal_message
    wf = new(client)
    risky = graph([step("n1", "action", "Clean the disk", action="run_local", prompt="rm -rf /tmp/x")])
    res = save(client, wf, risky)
    assert res.status_code == 403
    assert res.json() == {"detail": admin_refusal_message("run_local")}
    admins.add("alice")
    assert save(client, wf, risky).status_code == 200


def test_a_body_that_is_not_one_of_the_four_is_answered_in_a_sentence(client):
    wf = new(client)
    url = f"/api/workflows/{wf['id']}"
    for kwargs in ({"content": b"{not json"}, {"json": ["a list"]},
                   {"json": {"graph": TWO, "positions": {}, "base_version": 1}}, {"json": {}}):
        res = call(client, "PUT", url, **kwargs)
        assert res.status_code == 400, kwargs
        assert isinstance(res.json()["detail"], str), "a sentence, never FastAPI's 422 list"


# ── positions and pins: saved by themselves, never a version ────────────────

def test_positions_are_kept_forgotten_and_never_make_a_version(client, wf_db):
    wf = save(client, new(client), TWO).json()["workflow"]
    url = f"/api/workflows/{wf['id']}"
    res = call(client, "PUT", url, json={"positions": {"n1": [10, 20], "start": [0, 5],
                                                        "not-a-step": [1, 1]}})
    assert res.status_code == 200, res.text
    assert res.json()["saved"] == "positions"
    kept = json.loads(stored(wf_db, wf["id"]).graph)
    assert kept["nodes"][0]["position"] == [10, 20] and kept["start"]["position"] == [0, 5]
    assert "not-a-step" not in json.dumps(kept)
    forgot = call(client, "PUT", url, json={"positions": {"n1": None, "start": None}})
    assert forgot.status_code == 200
    kept = json.loads(stored(wf_db, wf["id"]).graph)
    assert kept["nodes"][0]["position"] is None and kept["start"]["position"] is None
    bad = call(client, "PUT", url, json={"positions": {"n1": [1, "two"]}})
    assert bad.status_code == 400 and "n1" in bad.json()["detail"]
    assert stored(wf_db, wf["id"]).version == 2 and versions(wf_db, wf["id"]) == [1, 2]


def test_pins_are_kept_say_what_they_dropped_and_never_make_a_version(client, wf_db):
    wf = save(client, new(client), TWO).json()["workflow"]
    url = f"/api/workflows/{wf['id']}"
    sample = {"task": "Summarise my inbox", "result": "Three mails.", "colour": "blue"}
    res = call(client, "PUT", url, json={"pins": {"n2": sample}})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["saved"] == "pins" and out["dropped"] == {"n2": ["colour"]}
    assert out["workflow"]["version"] == 2 and versions(wf_db, wf["id"]) == [1, 2]
    pinned = out["workflow"]["graph"]["nodes"][1]["pinned"]
    assert pinned and pinned["data"].get("result") == "Three mails."
    # A content save neither sets nor clears a pin; removing the step takes it.
    renamed = json.loads(json.dumps(TWO))
    renamed["nodes"][1]["label"] = "Send it to me"
    renamed["nodes"][1]["pinned"] = None
    after = save(client, out["workflow"], renamed).json()["workflow"]
    assert after["graph"]["nodes"][1]["pinned"] == pinned
    alone = graph([step("n1", label="Summarise my inbox")])
    after = save(client, after, alone).json()["workflow"]
    assert all(n.get("pinned") is None for n in after["graph"]["nodes"])
    # The kept versions never hold a pin.
    for row in rows(wf_db, wc.models()[1], workflow_id=wf["id"]):
        assert all(n.get("pinned") is None for n in json.loads(row.graph)["nodes"])
    unknown = call(client, "PUT", url, json={"pins": {"n9": sample}})
    assert unknown.status_code == 400 and "n9" in unknown.json()["detail"]
    unpin = call(client, "PUT", url, json={"pins": {"n1": None}})
    assert unpin.status_code == 200


# ── versions ─────────────────────────────────────────────────────────────────

def test_versions_are_listed_newest_first_and_each_can_be_read(client):
    wf = new(client)
    wf = save(client, wf, TWO).json()["workflow"]
    res = call(client, "GET", f"/api/workflows/{wf['id']}/versions")
    assert res.status_code == 200
    listed = res.json()["versions"]
    assert [v["version"] for v in listed] == [2, 1]
    assert all(set(v) == VERSION_KEYS for v in listed)
    assert [v["current"] for v in listed] == [True, False]
    assert [v["step_count"] for v in listed] == [2, 0]
    one = call(client, "GET", f"/api/workflows/{wf['id']}/versions/1").json()
    assert {"version", "name", "saved_at", "source", "graph"} <= set(one)
    assert one["graph"]["nodes"] == []
    missing = call(client, "GET", f"/api/workflows/{wf['id']}/versions/9")
    assert (missing.status_code, missing.json()) == (404, {"detail": "No such version."})


def test_a_restore_writes_a_new_version_and_loses_nothing(client, wf_db):
    wf = new(client)
    wf = save(client, wf, TWO).json()["workflow"]
    wf = save(client, wf, graph([step("n1", label="Only this")])).json()["workflow"]
    res = call(client, "POST", f"/api/workflows/{wf['id']}/versions/2/restore",
               json={"base_version": 3})
    assert res.status_code == 200, res.text
    assert res.json()["saved"] == "new_version"
    back = res.json()["workflow"]
    assert back["version"] == 4 and [n["label"] for n in back["graph"]["nodes"]] == [
        "Summarise my inbox", "Send me the summary"]
    assert versions(wf_db, wf["id"]) == [1, 2, 3, 4]
    (row,) = rows(wf_db, wc.models()[1], workflow_id=wf["id"], version=4)
    assert row.source == "restored"
    stale = call(client, "POST", f"/api/workflows/{wf['id']}/versions/1/restore",
                 json={"base_version": 3})
    assert stale.status_code == 409


def test_twenty_versions_are_kept_and_a_pruned_one_says_so(client, wf_db):
    wf = new(client)
    for i in range(24):
        wf = save(client, wf, graph([step("n1", label=f"Edit {i}")])).json()["workflow"]
    assert wf["version"] == 25
    kept = versions(wf_db, wf["id"])
    assert kept == list(range(6, 26)) and wf["versions_kept"] == 20
    gone = call(client, "GET", f"/api/workflows/{wf['id']}/versions/2")
    assert gone.status_code == 404
    assert "no longer kept" in gone.json()["detail"] and "20" in gone.json()["detail"]


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_takes_the_document_its_versions_its_start_and_its_runs(client, wf_db):
    Workflow, WorkflowVersion, TaskRunNode = wc.models()
    wf = save(client, new(client), TWO).json()["workflow"]
    db = wf_db()
    try:
        db.add(ScheduledTask(id="other", owner="alice", name="Other", task_type="llm",
                             prompt="x", trigger_type="webhook", status="active"))
        db.add(TaskRun(id="r1", task_id=wf["task_id"], status="success"))
        db.flush()
        db.add(TaskRunNode(id="rec1", run_id="r1", node_id="n1", status="success"))
        db.commit()
    finally:
        db.close()
    res = call(client, "DELETE", f"/api/workflows/{wf['id']}")
    assert res.status_code == 200, res.text
    assert rows(wf_db, Workflow) == [] and rows(wf_db, WorkflowVersion) == []
    assert rows(wf_db, TaskRun) == [] and rows(wf_db, TaskRunNode) == []
    assert [t.id for t in rows(wf_db, ScheduledTask)] == ["other"]


def test_a_running_workflow_is_not_deleted(client, sched, wf_db):
    wf = new(client)
    sched._executing.add(wf["task_id"])
    res = call(client, "DELETE", f"/api/workflows/{wf['id']}")
    assert res.status_code == 409 and "Stop it first" in res.json()["detail"]
    assert len(rows(wf_db, wc.models()[0])) == 1
    sched._executing.clear()
    db = wf_db()
    try:
        db.add(TaskRun(id="q", task_id=wf["task_id"], status="queued"))
        db.commit()
    finally:
        db.close()
    assert call(client, "DELETE", f"/api/workflows/{wf['id']}").status_code == 409
