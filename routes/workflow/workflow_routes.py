# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Workbench's workflow documents, over HTTP. `P22-05`…`P22-08`.

`D-2026-10-01-05` §1: a workflow is one named, versioned document started by
one task. These are the routes in `/work/notes/SLICE-B-DESIGN.md` § 5, and
nothing else:

    GET    /api/workflows                                   the list
    POST   /api/workflows                                   new, or from a chain (P22-06)
    GET    /api/workflows/{id}                              one, whole
    PUT    /api/workflows/{id}                              a content save, ?check, positions, or pins
    DELETE /api/workflows/{id}
    GET    /api/workflows/{id}/versions                     P8-10's policy
    GET    /api/workflows/{id}/versions/{version}
    POST   /api/workflows/{id}/versions/{version}/restore
    POST   /api/workflows/{id}/switch                       On / Off
    POST   /api/workflows/{id}/restore-chain                Put the old chain back
    GET    /api/workflows/{id}/runs/{run_id}                one run, every step (P22-07)
    POST   /api/workflows/{id}/nodes/{node_id}/test         test one step (P22-08)

and, from `/work/notes/SLICE-CD-DESIGN.md` § 3's contract **C-W** (wave D):

    GET    /api/workflows/palette                           what a step can be (P22-09…18)
    GET    /api/workflows/waiting                           every step waiting now (P22-17)
    GET    /api/workflows/{id}/nodes/{node_id}/fields       what a step can pick from (P22-09)
    POST   /api/workflows/{id}/runs/{run_id}/answer         a parked step's yes or no (P22-17)

and, from `/work/notes/SLICE-EF-DESIGN.md` § 3's contract **C-A** (wave E):

    POST   /api/workflows  {describe, tz?} | {file}         a draft, or a file (P22-19, P22-24)
    PUT    /api/workflows/{id}  {checked: [node ids]}       a person says steps look right (P22-19)
    GET    /api/workflows/{id}/export                       the workflow as a file (P22-24)
    POST   /api/workflows/{id}/runs/{run_id}/explain        "Why did this fail?" (P22-20)
    POST   /api/workflows/{id}/nodes/{node_id}/fix          apply a fix (P22-20)

The two literal ones are declared before `/{workflow_id}`, or FastAPI would
read "palette" as a workflow's id.

**What is reused, not added.** Running a workflow, its dry run, stopping it and
its list of runs are the trigger task's own routes (`POST /api/tasks/{id}/run`,
`/stop`, `GET /api/tasks/{id}/runs`); its trigger settings are `PUT
/api/tasks/{id}`. A second door for any of those would be a second place to
keep the admin gate and the one-run-at-a-time rule (`Law 14`).

**Every route is owner-scoped** — another owner's workflow is a 404, not a 403
— and **every refusal is `{detail: "<sentence>"}`** (`Law 15`). A body is read
by hand rather than by a pydantic model so that a malformed one is answered in
a sentence too, never FastAPI's 422 list.

**The route ceiling** (`check-unreachable.py --max-routes 90`): every path here
is spelled literally in `static/js/workbench/workflowApi.js`, its one caller,
so the count of routes no page reaches does not move (design § 5).
"""

import asyncio
import json
import logging
import functools

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.auth_helpers import get_current_user, request_is_a_person
from src import workflow_store as store
from src.workflow_store import WorkflowRefused

logger = logging.getLogger(__name__)

# `P22-08`. Where a test's input comes from (design § 4.1). Stored nowhere, but
# a closed list the panel offers and the route checks (`Law 10`).
TEST_SOURCES = ("last", "pinned", "custom", "example", "none")
# The test's two answers: the plan and a question, or what it made.
TEST_NEEDS_CONFIRMATION = "needs_confirmation"
TEST_RAN = "ran"


def _answers(handler):
    """A `WorkflowRefused` raised anywhere in a handler is its answer:
    the status, and `{detail: sentence}`.

    The wrapper is the handler's own kind: a `def` handler stays a `def`, so
    FastAPI still runs it in its threadpool and its database work never holds
    the event loop (an `async` wrapper around it would — every chat stream
    would wait on a workflow list's queries)."""
    if asyncio.iscoroutinefunction(handler):
        @functools.wraps(handler)
        async def async_wrapper(*args, **kwargs):
            try:
                return await handler(*args, **kwargs)
            except WorkflowRefused as refused:
                return JSONResponse(refused.body(), status_code=refused.status)
        return async_wrapper

    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except WorkflowRefused as refused:
            return JSONResponse(refused.body(), status_code=refused.status)
    return wrapper


# `P22-24` (`SLICE-EF-DESIGN` § 0.12). The most any body here may be: a
# workflow file is the biggest thing posted (a document is at most
# `WORKFLOW_GRAPH_MAX_BYTES`, 256 KiB, plus what it requires), and `_body` read
# with no ceiling at all until this row — the whole stream, into memory.
WORKFLOW_BODY_MAX_BYTES = 1024 * 1024
BODY_TOO_BIG = "The request is larger than 1 MiB, so it was not read. Nothing was saved."


async def _body(request: Request) -> dict:
    """The JSON object a request carries, read under `WORKFLOW_BODY_MAX_BYTES`.
    A declared length over it is refused before a byte is read; the stream is
    then counted as it arrives (a chunked body declares nothing), and refused
    one byte past the cap — `backup_routes._load_import_body`'s move."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > WORKFLOW_BODY_MAX_BYTES:
        raise WorkflowRefused(413, BODY_TOO_BIG)
    raw = bytearray()
    try:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > WORKFLOW_BODY_MAX_BYTES:
                raise WorkflowRefused(413, BODY_TOO_BIG)
    except WorkflowRefused:
        raise
    except Exception:
        raw = bytearray()
    raw = bytes(raw)
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        raise WorkflowRefused(400, "The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise WorkflowRefused(400, "The request body must be a JSON object.")
    return body


def setup_workflow_routes(task_scheduler) -> APIRouter:
    router = APIRouter(prefix="/api/workflows", tags=["workflows"])

    def _owner(request: Request):
        return get_current_user(request)

    # ── shapes (`C2`) ────────────────────────────────────────────────────────

    def _name_of(task):
        from routes.task.task_routes import _display_task_name
        return _display_task_name(task)

    def doc(db, wf, trigger=None) -> dict:
        """`C2` *Doc*: the *Summary*, the document, the trigger as `GET
        /api/tasks` serves it, and how many versions are kept."""
        from routes.task.task_routes import _task_to_dict
        trigger = trigger if trigger is not None else store.trigger_of(db, wf)
        out = store.summary_of(db, wf, name_of=_name_of)
        out["graph"] = store.stored_graph(wf)
        out["trigger_task"] = _task_to_dict(trigger, workflow_id=wf.id) if trigger is not None else None
        out["versions_kept"] = store.versions_kept(db, wf)
        checking = check_plans(db, trigger, out["graph"])
        if checking is not None:
            out["plans"], out["plans_declined"] = checking
        return out

    def check_plans(db, trigger, graph):
        """`B1132`. While a step is marked "check me", what each marked step
        would do: `{node_id: [line]}` — the workflow dry run's own plan of it
        (`TaskScheduler._plan_workflow_node`, one planner, `Law 7`; a step it
        would not run says why first) — and, when the engine would not run the
        document at all (an import whose Integration is missing, say), no
        plans and its sentence (`plans_declined`), as the dry run records.
        `None` when no step is marked.

        Before this row the banner and *Check them now* asked the existing
        dry-run door (`POST /api/tasks/{id}/run?dry=true`) once per saved
        version, and each asking recorded a `skipped` "Dry run" in the Runs —
        checking a draft read as having run it, and a drive's run-wait picked
        the check's dry run up as the newest run. Checking is reading: it
        records nothing. A dry run a person asks for (*Show me what this would
        do*) is still recorded (`Law 1`)."""
        if trigger is None:
            return None
        marked = [n for n in store.nodes_of(graph)
                  if isinstance(n, dict) and isinstance(n.get("unchecked"), dict)]
        if not marked:
            return None
        _wf, parsed, refused = task_scheduler._load_workflow(db, trigger)
        if refused or parsed is None:
            return {}, refused or "Nothing was planned."
        by_id = {str(n.get("id")): n for n in store.nodes_of(parsed)}
        plans = {}
        for mark in marked:
            node_id = str(mark.get("id"))
            steps, declined = task_scheduler._plan_workflow_node(db, trigger, by_id.get(node_id, mark))
            lines = [str(s.get("detail")) for s in steps if isinstance(s, dict) and s.get("detail")]
            plans[node_id] = ([f"Would not run: {declined}"] if declined else []) + lines
        return plans, None

    # ── 1, 2: the list, and a new one ────────────────────────────────────────

    @router.get("")
    @_answers
    def list_workflows(request: Request):
        from core.database import Workflow
        user = _owner(request)
        db = SessionLocal()
        try:
            q = db.query(Workflow)
            if user:
                q = q.filter(Workflow.owner == user)
            rows = q.order_by(Workflow.updated_at.desc(), Workflow.id).all()
            return {"workflows": store.summaries(db, rows, name_of=_name_of)}
        finally:
            db.close()

    @router.post("")
    @_answers
    async def create_workflow(request: Request):
        """New and empty, or (`from_task_id`, `P22-06`) a copy of the chain that
        task is a step of, or (`describe`, `P22-19`) a draft from the person's
        words, or (`file`, `P22-24`) a workflow file. Every way it is created
        switched off; a draft and a file come back with every step marked
        `unchecked`, what is `missing`, and every step's `destinations` (C-A)."""
        user = _owner(request)
        body = await _body(request)
        from_task_id = body.get("from_task_id")
        ways = [key for key in ("from_task_id", "describe", "file") if body.get(key) is not None]
        if len(ways) > 1:
            raise WorkflowRefused(400, "Send one of: from_task_id, describe, or file.")
        db = SessionLocal()
        try:
            if "describe" in ways:
                from src import workflow_assist
                drafted = await workflow_assist.draft_workflow(
                    db, user, body.get("describe"), tz=body.get("tz"))
                return {"workflow": doc(db, drafted.wf, drafted.trigger), "notes": drafted.notes,
                        "missing": drafted.missing, "destinations": drafted.destinations}
            if "file" in ways:
                from src import workflow_share
                made = workflow_share.import_file(db, user, body.get("file"))
                return {"workflow": doc(db, made.wf, made.trigger), "notes": made.notes,
                        "missing": made.missing, "destinations": made.destinations}
            if from_task_id:
                wf, trigger, notes = store.convert_chain(
                    db, owner=user, from_task_id=str(from_task_id), name=body.get("name"),
                    positions=_task_canvas_positions(user), name_of=_name_of)
            else:
                wf, trigger, notes = store.create_workflow(db, owner=user, name=body.get("name"))
            return {"workflow": doc(db, wf, trigger), "notes": notes}
        finally:
            db.close()

    def _task_canvas_positions(user):
        """Where the person put the chain's steps on the tasks canvas
        (`workbench_positions`, `P22-02`), so a converted workflow keeps the
        layout they made."""
        try:
            from routes.prefs_routes import _load_for_user
            value = (_load_for_user(user) or {}).get("workbench_positions") or {}
            tasks = value.get("tasks") if isinstance(value, dict) else None
            return dict(tasks) if isinstance(tasks, dict) else None
        except Exception:
            logger.debug("No task canvas positions for %s", user, exc_info=True)
            return None

    # ── C-W: the palette, and every step waiting now ─────────────────────────
    #
    # Literal paths, BEFORE `/{workflow_id}` (FastAPI matches in order).

    @router.get("/palette")
    @_answers
    def get_palette(request: Request):
        """`P22-09`…`P22-18`. What a step can be, for this person: each kind
        with whether they can use it and why not, the mapping of every field
        (`value` / `never`, `workflow_slots`, so the browser derives nothing),
        their integrations (never a key, never a base URL), MCP tools, skills,
        the AI step's tool choices, the workstation and the limits this engine
        holds a document to — `wf-effects`' `build_palette`, whose `limits` are
        the walker's own readers (`workflow_runs`; `integrate-d`: this route
        restated them over the builder's answer).

        `examples` (`P22-19`, `D-2026-10-02-02` §1): the sentences *Describe
        it* offers to start from — `workflow_assist.EXAMPLE_SENTENCES`, the one
        place they are written, read by the drafter's tests and the browser."""
        from src import workflow_effects as we
        from src.workflow_assist import EXAMPLE_SENTENCES
        out = dict(we.build_palette(_owner(request)) or {})
        out["examples"] = list(EXAMPLE_SENTENCES)
        return out

    @router.get("/waiting")
    @_answers
    def list_waiting(request: Request):
        """`P22-17`. Every step of this person's workflows that waits now — for
        a yes, a time, or Pantheon to be idle — re-offered on page load like
        the plans the Documents Tidy waits on (`static/js/tasks.js`)."""
        db = SessionLocal()
        try:
            return {"waiting": store.waiting_list(db, _owner(request))}
        finally:
            db.close()

    # ── 3: one workflow ──────────────────────────────────────────────────────

    @router.get("/{workflow_id}")
    @_answers
    def get_workflow(request: Request, workflow_id: str):
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            return {"workflow": doc(db, wf)}
        finally:
            db.close()

    @router.put("/{workflow_id}")
    @_answers
    async def save_workflow(request: Request, workflow_id: str, check: bool = False):
        """Five bodies, each its own door to one fact (design § 5):

          {name?, graph, base_version}   a content save; a new version only if
                                         the content moved; 409 if stale
          the same with ?check=true      the same answers, writing nothing
          {positions}                    where steps sit; never a version
          {pins}                         samples pinned on steps; never a version
          {checked: [node ids]}          `P22-19`: a person says these steps look
                                         right; their marks go; never a version;
                                         403 unless a person (`request_is_a_person`)
        """
        body = await _body(request)
        sent = [key for key in ("graph", "positions", "pins", "checked") if key in body]
        if len(sent) != 1:
            raise WorkflowRefused(
                400, "Send one of: the document (graph, with base_version), positions, pins, "
                     "or the steps you checked.")
        if check and sent[0] != "graph":
            raise WorkflowRefused(400, "?check=true checks a document; send its graph.")
        if sent[0] == "checked" and not request_is_a_person(request):
            # `SLICE-EF-DESIGN` § 1.1. Asked before the workflow is even read:
            # the `app_api` blocklist cannot see a body, so this is the control.
            raise WorkflowRefused(403, store.ONLY_A_PERSON_CHECKS)
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            if sent[0] == "checked":
                saved = store.check_steps(db, wf, body["checked"])
                return {"workflow": doc(db, wf), "saved": saved}
            if sent[0] == "positions":
                saved = store.save_positions(db, wf, body["positions"])
                return {"saved": saved, "version": wf.version}
            trigger = store.require_trigger(db, wf)
            if sent[0] == "pins":
                dropped = store.save_pins(db, wf, trigger, body["pins"])
                return {"workflow": doc(db, wf, trigger), "saved": store.SAVED_PINS,
                        "dropped": dropped}
            if not isinstance(body["graph"], (dict, str)):
                raise WorkflowRefused(400, "graph must be the workflow's document.")
            # `integrate-e`: who is saving decides what a changed step's mark
            # becomes — a person's change clears it, anything else's sets it.
            saved = store.save_document(
                db, wf, trigger, name=body.get("name"), graph=body["graph"],
                base_version=body.get("base_version"), check=check,
                by_person=request_is_a_person(request))
            if saved == "check":
                return {"ok": True, "check": True}
            return {"workflow": doc(db, wf, trigger), "saved": saved}
        finally:
            db.close()

    @router.get("/{workflow_id}/export")
    @_answers
    def export_workflow(request: Request, workflow_id: str):
        """`P22-24`. The workflow as a file to hand someone (`workflow_share.
        export_file`, `pantheon_workflow: 1`) — never a webhook token, a key, a
        base URL, a header's value, a sample or an endpoint URL. Sent as an
        attachment, never inline."""
        from fastapi.responses import Response
        from src import workflow_share
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            data = workflow_share.export_file(db, wf, store.trigger_of(db, wf))
            name = workflow_share.file_name(wf.name)
        finally:
            db.close()
        return Response(content=json.dumps(data, indent=2, ensure_ascii=False),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.delete("/{workflow_id}")
    @_answers
    def delete_workflow(request: Request, workflow_id: str):
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.trigger_of(db, wf)
            running = trigger is not None and store.is_running(db, task_scheduler, trigger.id)
            notes = store.delete_workflow(db, wf, trigger, running=running)
            return {"ok": True, "notes": notes}
        finally:
            db.close()

    # ── 4, 5, 6: versions ────────────────────────────────────────────────────

    @router.get("/{workflow_id}/versions")
    @_answers
    def list_versions(request: Request, workflow_id: str):
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            return {"versions": store.list_versions(db, wf)}
        finally:
            db.close()

    @router.get("/{workflow_id}/versions/{version}")
    @_answers
    def get_version(request: Request, workflow_id: str, version: str):
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            row = store.kept_version(db, wf, version)
            out = store.version_summary(row, current=wf.version)
            out["graph"] = json.loads(row.graph)
            return out
        finally:
            db.close()

    @router.post("/{workflow_id}/versions/{version}/restore")
    @_answers
    async def restore_version(request: Request, workflow_id: str, version: str):
        body = await _body(request)
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.require_trigger(db, wf)
            saved = store.restore_version(db, wf, trigger, version,
                                          base_version=body.get("base_version"),
                                          by_person=request_is_a_person(request))
            return {"workflow": doc(db, wf, trigger), "saved": saved}
        finally:
            db.close()

    # ── 7, 8: On / Off, and the chain it came from ───────────────────────────

    @router.post("/{workflow_id}/switch")
    @_answers
    async def switch_workflow(request: Request, workflow_id: str):
        body = await _body(request)
        if not isinstance(body.get("on"), bool):
            raise WorkflowRefused(400, "Say whether to switch it on or off: {\"on\": true} or {\"on\": false}.")
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.require_trigger(db, wf)
            chain_paused, notes = store.switch_workflow(db, wf, trigger, on=body["on"],
                                                        name_of=_name_of)
            return {"workflow": doc(db, wf, trigger), "chain_paused": chain_paused,
                    "notes": notes}
        finally:
            db.close()

    @router.post("/{workflow_id}/restore-chain")
    @_answers
    def restore_chain(request: Request, workflow_id: str):
        db = SessionLocal()
        try:
            user = _owner(request)
            wf = store.owned_workflow(db, workflow_id, user)
            trigger = store.trigger_of(db, wf)
            resumed, notes = store.restore_chain(db, wf, trigger, owner=wf.owner or user,
                                                 name_of=_name_of)
            return {"workflow": doc(db, wf, trigger), "chain_resumed": resumed, "notes": notes}
        finally:
            db.close()

    # ── 9: one run, every step (`P22-07`) ────────────────────────────────────

    @router.get("/{workflow_id}/runs/{run_id}")
    @_answers
    def get_execution(request: Request, workflow_id: str, run_id: str):
        """The run, the graph of the version it ran, and its node records.

        `cleared` says the records were pruned after their window — the run's
        own step log says steps ran, it ended longer ago than records are
        kept, and they are not there — which a person is told, rather than
        shown a run that seems to have done nothing (`Law 10`).
        `cleared_sentence` is what they are told: the engine's
        `records_cleared_sentence()`, naming the window as it is set (added at
        the wave C merge — the panel had typed "30 days" itself, which was
        false once the setting was changed).
        """
        from core.database import TaskRun, TaskRunNode
        from routes.task.task_routes import _run_to_dict
        from src.workflow_runs import node_record_to_dict, records_cleared_sentence
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            run = (db.query(TaskRun)
                   .filter(TaskRun.id == run_id, TaskRun.task_id == wf.task_id).first()
                   if wf.task_id else None)
            if run is None:
                raise WorkflowRefused(404, "No such run of this workflow.")
            recs = (db.query(TaskRunNode).filter(TaskRunNode.run_id == run.id)
                    .order_by(TaskRunNode.seq, TaskRunNode.attempt).all())
            version = next((r.workflow_version for r in recs if r.workflow_version is not None), None)
            graph, kept = store.graph_of_version(db, wf, version)
            cleared = not recs and store.records_were_cleared(run)
            return {
                "run": _run_to_dict(run),
                "version": version,
                "version_kept": kept,
                "graph": graph,
                "nodes": [node_record_to_dict(r) for r in recs],
                "cleared": cleared,
                "cleared_sentence": records_cleared_sentence() if cleared else None,
                "failed": _failed_step(run, graph, kept, recs),
            }
        finally:
            db.close()

    # ── 10: test one step (`P22-08`) ─────────────────────────────────────────

    @router.post("/{workflow_id}/nodes/{node_id}/test")
    @_answers
    async def test_node(request: Request, workflow_id: str, node_id: str):
        """Run one step, as it stands on the canvas, on an input the person
        chose — and nothing else: no run row, no node record, no delivery, no
        notification, no other step (`TaskScheduler.test_workflow_node`).

        A step whose effects reach past Pantheon's own data — it notifies,
        touches a remote, deletes, rewrites or runs code — and every run-task
        step (it really runs another task) answers first with its dry plan and
        `outcome: "needs_confirmation"`; the same request with `confirm: true`
        runs it. That is mistake prevention, not a control against an
        adversary (`Law 17`): the owner can already run the whole workflow.
        """
        body = await _body(request)
        node = body.get("node")
        source = body.get("source") or "none"
        if not isinstance(node, dict):
            raise WorkflowRefused(400, "Send the step to test, as it stands on the canvas (node).")
        if str(node.get("id")) != str(node_id):
            raise WorkflowRefused(400, "The step in the body is not the step in the address.")
        if source not in TEST_SOURCES:
            raise WorkflowRefused(400, f"source must be one of: {', '.join(TEST_SOURCES)}.")
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.require_trigger(db, wf)
            rows = store.owner_rows(db, wf.owner)
            # Validated exactly as on save (design § 4): the step as a document
            # of one, so an unsaved step is tested on its unsaved settings and a
            # refusal is the sentence a save would give.
            from src.workflow_document import GRAPH_VERSION, START_KEY
            stored = store.stored_graph(wf)
            if "{{" in json.dumps(node.get("config") or {}, default=str):
                # `P22-09`. A step that refers to the steps before it is
                # checked where it stands — a reference must name a step
                # upstream of it, which a document of one never has.
                checked_graph = store.check_document(
                    db, _with_node(stored, dict(node, pinned=None)), owner=wf.owner,
                    own_task_id=trigger.id, rows=rows)
                checked = next(n for n in store.nodes_of(checked_graph)
                               if str(n.get("id")) == str(node_id))
            else:
                alone = {"v": GRAPH_VERSION, START_KEY: {"position": None},
                         "nodes": [dict(node, pinned=None)], "edges": []}
                checked = store.nodes_of(store.check_document(
                    db, alone, owner=wf.owner, own_task_id=trigger.id, rows=rows))[0]
            graph = _with_node(stored, checked)
            envelope, dropped = await _test_input(
                db, wf, trigger, stored, graph, checked, source, body.get("input"))
            tasks_by_id = rows[0]
            from src.workflow_document import needs_test_confirmation
            from src.workflow_effects import workflow_resources
            # `P22-13`/`P22-14` (`wf-rules`' merge point 5). What the person can
            # reach — so an MCP tool its server marks read-only is known to be,
            # and the plan of an HTTP, MCP or Code step is the document's own.
            resources = workflow_resources(wf.owner)
            if needs_test_confirmation(checked, tasks_by_id, resources) and not body.get("confirm"):
                plan = _node_plan(checked, wf.owner, tasks_by_id, resources)
                return {
                    "outcome": TEST_NEEDS_CONFIRMATION,
                    "plan": plan,
                    "effects": _effects_not_in(plan, _node_effect_sentences(
                        checked, tasks_by_id, resources)),
                    "input_used": envelope, "dropped": dropped, "source": source,
                }
            name = wf.name
        finally:
            db.close()
        try:
            result = await task_scheduler.test_workflow_node(
                trigger, name, checked, input_envelope=envelope, timeout=None, graph=graph)
        except WorkflowRefused:
            raise
        except Exception as err:
            logger.warning("Test of step %s in workflow %s failed to run", node_id, workflow_id,
                           exc_info=True)
            raise WorkflowRefused(500, f"The test could not run: {type(err).__name__}: {err}") from None
        out = {"outcome": TEST_RAN}
        out.update(result or {})
        out.update({"input_used": envelope, "dropped": dropped, "source": source})
        return out

    # ── C-W: what a step can pick, and a parked step's answer ────────────────

    @router.get("/{workflow_id}/nodes/{node_id}/fields")
    @_answers
    def list_fields(request: Request, workflow_id: str, node_id: str):
        """`P22-09`. The fields a step can pick from the steps before it — the
        last run's records, a pinned sample, what a step promises to answer —
        each with an example and where it came from (`wf-effects`'
        `available_fields`)."""
        from src import workflow_effects as we
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.trigger_of(db, wf)
            graph = store.stored_graph(wf)
            if not any(str(n.get("id")) == str(node_id) for n in store.nodes_of(graph)):
                raise WorkflowRefused(404, "No such step in this workflow.")
            return we.available_fields(db, wf, trigger, graph, str(node_id))
        finally:
            db.close()

    @router.post("/{workflow_id}/runs/{run_id}/answer")
    @_answers
    async def answer_step(request: Request, workflow_id: str, run_id: str):
        """`P22-17` — a parked step's yes or no, from the person whose workflow
        it is. The skill test's `/test-approval` move, in this order:

          1. owner-scoped: anyone else's workflow is a 404, and nothing is
             consumed;
          2. the run must be `waiting` and the step's record must wait on
             exactly this card;
          3. the store must still hold it, for this owner and the session it
             was minted in;
          4. `consume(..., allow_continuation=False)` — SINGLE_ACTION scope, so
             Allow resumes the step ONCE and the gate re-arms behind the sealed
             action (a second gated call in the same turn asks again).
             `approve_task` or `deny`; `approve` (a chat's scope) is a 400 —
             there is no chat to remember it in;
          5. the answer, said with who and when, goes in the step's log and
             the run's, and the run goes on (`resume_workflow_run`, as a
             person's). The consumed approval travels in memory: a restart in
             that window is a lapsed answer, and the step says so.

        The seal, the TTL, single use and owner binding are the store's,
        unchanged (`FORBIDDEN.md` Part 2).
        """
        from src.task_scheduler import QuestionRefused, _resolve_task_timezone
        body = await _body(request)
        decision = str(body.get("decision") or "").strip().lower()
        if decision == "approve":
            raise WorkflowRefused(400, store.NO_CHAT_TO_REMEMBER)
        if decision not in store.ANSWER_DECISIONS:
            raise WorkflowRefused(400, "decision must be approve_task (Allow once) or deny.")
        node_id = str(body.get("node_id") or "")
        approval_id = str(body.get("approval_id") or "")
        item = body.get("item")
        if item is not None and (isinstance(item, bool) or not isinstance(item, int)):
            raise WorkflowRefused(400, "item must be a whole number or null.")
        user = _owner(request)
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, user)
            run, rec, waiting = store.find_waiting_step(db, wf, run_id, node_id, item, approval_id)
            trigger = store.trigger_of(db, wf)
            owner = wf.owner
            session = waiting.get("session_id") or ""
            # `B1111`: the tool as the step's panel names it.
            tool = waiting.get("tool_label") or waiting.get("tool") or "the action"
            label = rec.label or rec.node_id
            tz_name = _resolve_task_timezone(db, trigger) if trigger is not None else None
            task_id = run.task_id
        finally:
            db.close()
        # `B1102`. Steps 3–5 are the scheduler's one answer core, which a plain
        # task's door calls too (`TaskScheduler.answer_question`, `Law 14`).
        try:
            outcome, verdict = await task_scheduler.answer_question(
                task_id=task_id, run_id=run.id, node_id=node_id, item=item,
                approval_id=approval_id, decision=decision, owner=owner, session=session,
                tool=tool, who=user or owner or "you", tz_name=tz_name,
                busy="The workflow is busy for a moment. Answer again.")
        except QuestionRefused as refused:
            raise WorkflowRefused(refused.status, refused.sentence)
        return {"ok": True, "outcome": outcome, "sentence": verdict.sentence,
                "step": label}

    # ── C-A: "Why did this fail?" and "fix this step" (`P22-20`) ─────────────

    @router.post("/{workflow_id}/runs/{run_id}/explain")
    @_answers
    async def explain_step(request: Request, workflow_id: str, run_id: str):
        """`P22-20`. The model reads one step's record of one run — what it
        was handed, what came back, its error and its log, ONLY inside the
        untrusted-context guard — and says why it failed, with a change to the
        step's settings that `FIX_FIELDS` allows, or none. Owner-scoped
        (another owner's run is a 404). The step is the CURRENT document's;
        `changed_since_run` says whether it differs from the one that ran.
        Nothing is written. `{why, model, changed_since_run, proposal,
        left_out}` (C-A)."""
        from core.database import TaskRun, TaskRunNode
        from src import workflow_assist
        from src.task_action_policy import owner_has_admin_task_privileges
        from src.workflow_document import DocumentError, parse_graph
        from src.workflow_effects import workflow_resources
        from src.workflow_runs import node_record_to_dict
        body = await _body(request)
        node_id = str(body.get("node_id") or "")
        item = body.get("item")
        if item is not None and (isinstance(item, bool) or not isinstance(item, int)):
            raise WorkflowRefused(400, "item must be a whole number or null.")
        user = _owner(request)
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, user)
            run = (db.query(TaskRun).filter(TaskRun.id == run_id, TaskRun.task_id == wf.task_id)
                   .first() if wf.task_id else None)
            if run is None:
                raise WorkflowRefused(404, "No such run of this workflow.")
            q = db.query(TaskRunNode).filter(TaskRunNode.run_id == run.id,
                                             TaskRunNode.node_id == node_id,
                                             TaskRunNode.dry.is_(False))
            q = q.filter(TaskRunNode.item.is_(None)) if item is None else \
                q.filter(TaskRunNode.item == item)
            rec = q.order_by(TaskRunNode.attempt.desc(), TaskRunNode.seq.desc()).first()
            if rec is None:
                raise WorkflowRefused(404, "That step has no record in this run.")
            record = node_record_to_dict(rec)
            try:
                current = parse_graph(store.stored_graph(wf))
            except DocumentError as err:
                raise store._document_error_refusal(err) from None
            node = next((n for n in store.nodes_of(current) if str(n.get("id")) == node_id), None)
            if node is None:
                raise WorkflowRefused(404, "That step is not in the workflow any more.")
            ran_graph, kept = store.graph_of_version(db, wf, rec.workflow_version)
            ran = next((n for n in store.nodes_of(ran_graph) if str(n.get("id")) == node_id), None)
            changed = (ran is None or store._step_content(ran) != store._step_content(node)
                       or (not kept and rec.workflow_version != wf.version))
            rows = store.owner_rows(db, wf.owner)
            trigger = store.trigger_of(db, wf)
            owner = wf.owner
            base_version = wf.version
        finally:
            db.close()
        resources = workflow_resources(owner)
        try:
            explained = await workflow_assist.explain_step(
                owner, node=node, record=record, graph=current, base_version=base_version,
                item=item, resources=resources, tasks_by_id=rows[0], crew_ids=rows[1],
                owner_is_admin=owner_has_admin_task_privileges(owner),
                own_task_id=trigger.id if trigger is not None else None)
        except workflow_assist.NoModelSetUp:
            raise WorkflowRefused(503, workflow_assist.NO_MODEL_TO_EXPLAIN) from None
        except ValueError:
            raise WorkflowRefused(422, workflow_assist.EXPLAIN_UNREADABLE) from None
        return {"why": explained.why, "model": workflow_assist.model_name(owner),
                "changed_since_run": changed, "proposal": explained.proposal,
                "left_out": explained.left_out}

    @router.post("/{workflow_id}/nodes/{node_id}/fix")
    @_answers
    async def fix_node(request: Request, workflow_id: str, node_id: str):
        """`P22-20`, *Apply*. A person's only (`request_is_a_person` — not a
        bearer token, not the assistant's loopback): the server asks the fix
        rule again against the stored step (`store.save_fix`), writes a new
        version (source `fixed`) and answers `undo_version`, the version it
        started from, which the existing restore door puts back. A stale base
        is a 409 (`_stale`)."""
        if not request_is_a_person(request):
            raise WorkflowRefused(403, store.ONLY_A_PERSON_FIXES)
        body = await _body(request)
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
            trigger = store.require_trigger(db, wf)
            base = body.get("base_version")
            saved = store.save_fix(db, wf, trigger, node_id=node_id, config=body.get("config"),
                                   base_version=base)
            return {"workflow": doc(db, wf, trigger), "saved": saved, "undo_version": int(base)}
        finally:
            db.close()

    return router


def _with_node(graph: dict, node: dict) -> dict:
    """The stored document with this step as the canvas has it: replaced where
    it is, added where it is new."""
    out = dict(graph)
    nodes = list(store.nodes_of(graph))
    for i, existing in enumerate(nodes):
        if str(existing.get("id")) == str(node.get("id")):
            nodes[i] = dict(node, pinned=existing.get("pinned"))
            break
    else:
        nodes.append(node)
    out["nodes"] = nodes
    return out


def _field(record, key):
    return record.get(key) if isinstance(record, dict) else getattr(record, key, None)


def _declared_fields(shape) -> tuple:
    """The fields a step is handed, from `node_input_shape` (`C1`): the last
    element of its tuple, or `fields` of a dict; `None` is handed nothing."""
    if shape is None:
        return ()
    if isinstance(shape, dict):
        return tuple(shape.get("fields") or ())
    if isinstance(shape, (tuple, list)) and shape and isinstance(shape[-1], (tuple, list)):
        return tuple(shape[-1])
    return ()


# `P22-08`. Where a sample typed as plain text goes: the first of these the
# step is handed — what the step before it made (`result`, the hand-off), a
# webhook's `body`, an event's `text`. A step handed none of them is asked for
# JSON with its own fields, named, rather than given a field it never reads.
PLAIN_TEXT_FIELDS = ("result", "body", "text")


def _sample_data(raw, fields, label) -> dict:
    """The person's sample as the object `build_pin` takes. JSON that is an
    object is used as it is; any other text goes into the step's text field
    (`PLAIN_TEXT_FIELDS`). A step that is handed nothing gets `{}`, and the
    engine's own refusal says why (`build_pin`)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise WorkflowRefused(400, "The sample must be text, or a JSON object.")
    if not fields:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = None
    if isinstance(value, dict):
        return value
    field = next((f for f in PLAIN_TEXT_FIELDS if f in fields), None)
    if field is None:
        raise WorkflowRefused(
            400, f"{label} is handed {', '.join(fields)}. Paste the sample as JSON with those "
                 f"fields, for example {{\"{fields[0]}\": \"…\"}}.")
    return {field: raw}


def _pinned_envelope(graph, node_id, trigger, data):
    """`build_pin`, its refusals answered as sentences (`{detail}`, 400)."""
    from src.workflow_document import DocumentError, build_pin
    try:
        envelope, dropped = build_pin(graph, node_id, trigger, data)
    except DocumentError as err:
        raise store._document_error_refusal(err) from None
    return envelope, list(dropped or ())


async def _test_input(db, wf, trigger, stored, graph, node, source, raw):
    """The envelope the step would really be handed, from the chosen source,
    and the keys a sample lost because the step is never handed them."""
    from src.workflow_document import node_input_shape
    label = store.quoted(node.get("label") or node.get("id"))
    node_id = str(node.get("id"))
    if source == "none":
        return None, []
    if source == "last":
        from src.workflow_runs import last_node_record
        rec = last_node_record(db, trigger.id, node_id)
        if rec is None:
            raise WorkflowRefused(
                400, f"{label} has not run yet, so there is no last input to test it with. "
                     f"Pin a sample, paste one, or let the model write one.")
        value = _field(rec, "input")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = None
        if isinstance(value, dict) and value.get("truncated") is True:
            raise WorkflowRefused(
                400, f"The last input {label} was handed was too long to keep whole "
                     f"({value.get('chars', 'many')} characters), so it cannot be used for a "
                     f"test. Pin a sample or paste one instead.")
        return value, []
    if source == "pinned":
        pinned = next((n.get("pinned") for n in store.nodes_of(stored)
                       if str(n.get("id")) == node_id), None)
        if not pinned:
            raise WorkflowRefused(
                400, f"Nothing is pinned on {label}. Pin a sample first, or choose another source.")
        return pinned, []
    fields = _declared_fields(node_input_shape(graph, node_id, trigger))
    if source == "custom":
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise WorkflowRefused(400, "Paste the sample to test with.")
        return _pinned_envelope(graph, node_id, trigger, _sample_data(raw, fields, label))
    # example
    if not fields:
        raise WorkflowRefused(
            400, f"{label} is handed nothing when it runs, so there is nothing to write an example of.")
    data = await _write_example(wf.owner, node.get("label") or node_id, fields)
    return _pinned_envelope(graph, node_id, trigger, data)


async def _write_example(owner, label, fields) -> dict:
    """`P8-08`'s shape: leave it blank and the model invents a plausible
    example — here, one JSON object with exactly the fields the step is handed.
    The utility model, falling back to the default — `workflow_assist.
    ask_for_json`, the one model call `POST /api/tasks/parse` and the
    drafter ask too (`P22-19`, `Law 7`)."""
    from src import workflow_assist

    system = (
        "You write ONE realistic, invented example of the data a workflow step is handed. "
        "Reply with ONLY a JSON object whose keys are exactly the fields listed, each with "
        "a short plausible value. No prose, no markdown fences.")
    try:
        data, why = await workflow_assist.ask_for_json(
            owner, [{"role": "system", "content": system},
                    {"role": "user", "content": f"Step: {str(label)[:120]}\nFields: {', '.join(fields)}"}],
            max_tokens=600, temperature=0.7, timeout=45)
    except workflow_assist.NoModelSetUp:
        raise WorkflowRefused(400, "No model is set up to write an example. Paste a sample instead.") from None
    if why is not None and why.kind == workflow_assist.ASK_NO_ANSWER:
        raise WorkflowRefused(502, f"The model did not write an example: {why.sentence}")
    if not isinstance(data, dict):
        raise WorkflowRefused(502, "The model's example could not be read as JSON. Try again, or paste one.")
    return data


def _failed_step(run, graph, kept, recs) -> dict | None:
    """`P22-07` / `P22-11`. The step a failed run failed on — the walker's own
    rule (`workflow_runs.RunState.unhandled_error`: the last step that failed
    with no arrow out of its failure port), so the Runs view opens on the step
    the run's `error` names. `integrate-d`: the room took "the last record,
    when it failed", Slice B's single path — with branches side by side or a
    For-each's item records after its own, the last record is often another
    one, and the failed run opened on nothing ("This run ended: failed.").
    `None` for any other run, or when the graph is not the version it ran."""
    if run.status != "error" or not kept or not recs:
        return None
    from src.workflow_document import DocumentError, parse_graph
    from src.workflow_runs import RunState
    try:
        state = RunState(parse_graph(graph), [r for r in recs if not r.dry])
    except DocumentError:
        return None
    rec = state.unhandled_error()
    if rec is None:
        return None
    return {"node_id": rec.node_id, "label": rec.label or rec.node_id, "error": rec.error or ""}


def _node_plan(node, owner, tasks_by_id, resources=None) -> list:
    """What the step would do, as the dry run says it (`dry_run_plan`, the one
    planner): a run-task step is "Would run the task …" and that task's own
    plan, which is what testing it does.

    `P22-10`…`P22-18`. Any kind that is not a task's — a logic, HTTP, MCP,
    Skill, Code, Wait, Merge or For-each step — is the document's own planner
    (`plan_lines`), exactly as the workflow's dry run plans it
    (`TaskScheduler._plan_workflow_node`). `integrate-d`: this answered
    `dry_run_plan(task_type=kind)` for every kind, so testing an HTTP POST said
    it "Would send this task's prompt to a model, with tools".
    """
    from src.builtin_actions import dry_run_plan
    from src import workflow_document as wd
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    kind = node.get("kind")
    if kind != wd.NODE_KIND_RUN_TASK and kind not in wd.STAND_IN_KINDS:
        if resources is None:
            from src.workflow_effects import workflow_resources
            resources = workflow_resources(owner)
        return list(wd.plan_lines(node, resources))
    if kind == "run_task":
        from routes.task.task_routes import _display_task_name
        from src.task_scheduler import DRY_RUN_HEADLINE, dry_run_lines
        target = tasks_by_id.get(str(config.get("task_id") or ""))
        if target is None:
            return ["Would run a task that no longer exists."]
        lines = [f"Would run the task {store.quoted(_display_task_name(target))}."]
        return lines + [line for line in dry_run_lines(target) if line != DRY_RUN_HEADLINE]
    return dry_run_plan(task_type=kind, action=config.get("action"), prompt=config.get("prompt"),
                        owner=owner, model=config.get("model"),
                        endpoint_url=config.get("endpoint_url"))


# What a planner's line says an effect with (`dry_run_plan`, `plan_lines`):
# "It would: runs your code in your own workstation account, …".
PLAN_EFFECT_LEAD = "It would: "


def _effects_not_in(plan, sentences) -> list:
    """`B1112`. The effect sentences the plan's own "It would: …" lines do not
    already say. Both are written from one set of sentences
    (`EFFECT_SENTENCES`, `CODE_EFFECT_SENTENCE`), and *Test this step* drew
    the plan and then the effects beside it — so a Code step said "runs your
    code in your own workstation account" twice, an Action step each of its
    effects twice (measured by `integrate-d`, P22-18; the pattern predates
    wave D). An effect the plan does not say (a Run task step's "calls a
    model", say) is still listed. Only the plan's effect lines are read, so
    a prompt that happens to contain the words does not hide one."""
    said = [str(line)[len(PLAN_EFFECT_LEAD):] for line in plan or ()
            if str(line).startswith(PLAN_EFFECT_LEAD)]
    return [s for s in sentences if not any(s in line for line in said)]


def _node_effect_sentences(node, tasks_by_id, resources=None) -> list:
    """What testing this step would do, in words. A Code step's command runs in
    the person's workstation, so it says so (`CODE_EFFECT_SENTENCE`) where an
    action's says it runs as the user Pantheon runs as."""
    from src.builtin_actions import EFFECT_RUNS_CODE, EFFECT_SENTENCES
    from src.workflow_document import (
        CODE_EFFECT_SENTENCE, NODE_KIND_CODE, NODE_KIND_FOREACH, node_effects,
    )
    step = node
    if node.get("kind") == NODE_KIND_FOREACH:
        inner = (node.get("config") or {}).get("step")
        step = inner if isinstance(inner, dict) else {}
    code = step.get("kind") == NODE_KIND_CODE
    return [CODE_EFFECT_SENTENCE if (code and e == EFFECT_RUNS_CODE) else EFFECT_SENTENCES[e]
            for e in (node_effects(node, tasks_by_id, resources) or ()) if e in EFFECT_SENTENCES]
