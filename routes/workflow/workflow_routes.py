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
from src.auth_helpers import get_current_user
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


async def _body(request: Request) -> dict:
    try:
        raw = await request.body()
    except Exception:
        raw = b""
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
        return out

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
        task is a step of. Either way it is created switched off."""
        user = _owner(request)
        body = await _body(request)
        from_task_id = body.get("from_task_id")
        db = SessionLocal()
        try:
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
        restated them over the builder's answer)."""
        from src import workflow_effects as we
        return dict(we.build_palette(_owner(request)) or {})

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
        """Four bodies, each its own door to one fact (design § 5):

          {name?, graph, base_version}   a content save; a new version only if
                                         the content moved; 409 if stale
          the same with ?check=true      the same answers, writing nothing
          {positions}                    where steps sit; never a version
          {pins}                         samples pinned on steps; never a version
        """
        body = await _body(request)
        sent = [key for key in ("graph", "positions", "pins") if key in body]
        if len(sent) != 1:
            raise WorkflowRefused(
                400, "Send one of: the document (graph, with base_version), positions, or pins.")
        if check and sent[0] != "graph":
            raise WorkflowRefused(400, "?check=true checks a document; send its graph.")
        db = SessionLocal()
        try:
            wf = store.owned_workflow(db, workflow_id, _owner(request))
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
            saved = store.save_document(
                db, wf, trigger, name=body.get("name"), graph=body["graph"],
                base_version=body.get("base_version"), check=check)
            if saved == "check":
                return {"ok": True, "check": True}
            return {"workflow": doc(db, wf, trigger), "saved": saved}
        finally:
            db.close()

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
                                          base_version=body.get("base_version"))
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
                return {
                    "outcome": TEST_NEEDS_CONFIRMATION,
                    "plan": _node_plan(checked, wf.owner, tasks_by_id, resources),
                    "effects": _node_effect_sentences(checked, tasks_by_id, resources),
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
        from src.interactive_gate import STARTED_BY_PERSON
        from src.task_scheduler import (
            ANSWER_ALLOW, ANSWER_DENY, ANSWER_LAPSED, StepAnswer, _resolve_task_timezone,
        )
        from src.tool_approvals import _normalized_owner, tool_approval_store
        from src.workflow_runs import _clock
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
            tool = waiting.get("tool") or "the action"
            label = rec.label or rec.node_id
            tz_name = _resolve_task_timezone(db, trigger) if trigger is not None else None
            task_id = run.task_id
        finally:
            db.close()
        pending = tool_approval_store.peek(approval_id)
        if pending is not None and (pending.owner != _normalized_owner(owner)
                                    or pending.session_id != session):
            # Not this workflow's card: nothing about it is said or consumed.
            raise WorkflowRefused(404, "No such question.")
        if not await task_scheduler._claim_for_resume(task_id):
            raise WorkflowRefused(409, "The workflow is busy for a moment. Answer again.")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        who = user or owner or "you"
        at = _clock(now, tz_name)
        if pending is None:
            verdict = StepAnswer(node_id, item, ANSWER_LAPSED,
                                 f"Nobody answered in time — {tool} was not done.")
            outcome = "lapsed"
        else:
            said = {}
            exact = tool_approval_store.consume(
                approval_id, decision=decision, owner=owner, session_id=session,
                allow_continuation=False, outcome=said)
            if decision == "deny":
                verdict = StepAnswer(node_id, item, ANSWER_DENY,
                                     f"Denied by {who} at {at}: {tool} — it was not done.")
                outcome = "denied"
            elif exact is None:
                verdict = StepAnswer(node_id, item, ANSWER_LAPSED,
                                     f"Nobody answered in time — {tool} was not done.")
                outcome = "lapsed"
            else:
                verdict = StepAnswer(node_id, item, ANSWER_ALLOW,
                                     f"Allowed once by {who} at {at}: {tool}",
                                     exact_approval=exact)
                outcome = "resumed"
        task_scheduler._spawn_resume(task_id, run.id, started_by=STARTED_BY_PERSON,
                                     answer=verdict)
        return {"ok": True, "outcome": outcome, "sentence": verdict.sentence,
                "step": label}

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
    The utility model, falling back to the default, as `POST /api/tasks/parse`
    asks."""
    import re
    from src.endpoint_resolver import resolve_endpoint
    from src.llm_core import llm_call_async
    from src.text_helpers import strip_think

    url, model, headers = resolve_endpoint("utility", owner=owner or None)
    if not (url and model):
        url, model, headers = resolve_endpoint("default", owner=owner or None)
    if not (url and model):
        raise WorkflowRefused(400, "No model is set up to write an example. Paste a sample instead.")
    system = (
        "You write ONE realistic, invented example of the data a workflow step is handed. "
        "Reply with ONLY a JSON object whose keys are exactly the fields listed, each with "
        "a short plausible value. No prose, no markdown fences.")
    try:
        raw = await llm_call_async(
            url=url, model=model, headers=headers, timeout=45, temperature=0.7, max_tokens=600,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": f"Step: {str(label)[:120]}\nFields: {', '.join(fields)}"}])
    except Exception as err:
        raise WorkflowRefused(502, f"The model did not write an example: {type(err).__name__}: {err}") from None
    text = strip_think(raw or "", prose=False, prompt_echo=False).strip()
    found = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(found.group(0) if found else text)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise WorkflowRefused(502, "The model's example could not be read as JSON. Try again, or paste one.")
    return data


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


def _node_effect_sentences(node, tasks_by_id, resources=None) -> list:
    from src.builtin_actions import EFFECT_SENTENCES
    from src.workflow_document import node_effects
    return [EFFECT_SENTENCES[e] for e in (node_effects(node, tasks_by_id, resources) or ())
            if e in EFFECT_SENTENCES]
