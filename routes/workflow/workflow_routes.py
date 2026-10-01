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
    the status, and `{detail: sentence}`."""
    @functools.wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            result = handler(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
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
        own step log says steps ran and their records are not there — which a
        person is told, rather than shown a run that seems to have done
        nothing (`Law 10`).
        """
        from core.database import TaskRun, TaskRunNode
        from routes.task.task_routes import _run_to_dict
        from src.workflow_runs import node_record_to_dict
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
            return {
                "run": _run_to_dict(run),
                "version": version,
                "version_kept": kept,
                "graph": graph,
                "nodes": [node_record_to_dict(r) for r in recs],
                "cleared": not recs and store.ran_steps_without_records(run),
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
            alone = {"v": GRAPH_VERSION, START_KEY: {"position": None},
                     "nodes": [dict(node, pinned=None)], "edges": []}
            checked = store.nodes_of(store.check_document(
                db, alone, owner=wf.owner, own_task_id=trigger.id, rows=rows))[0]
            stored = store.stored_graph(wf)
            graph = _with_node(stored, checked)
            envelope, dropped = await _test_input(
                db, wf, trigger, stored, graph, checked, source, body.get("input"))
            tasks_by_id = rows[0]
            from src.workflow_document import needs_test_confirmation
            if needs_test_confirmation(checked, tasks_by_id) and not body.get("confirm"):
                return {
                    "outcome": TEST_NEEDS_CONFIRMATION,
                    "plan": _node_plan(checked, wf.owner, tasks_by_id),
                    "effects": _node_effect_sentences(checked, tasks_by_id),
                    "input_used": envelope, "dropped": dropped, "source": source,
                }
            name = wf.name
        finally:
            db.close()
        try:
            result = await task_scheduler.test_workflow_node(
                trigger, name, checked, input_envelope=envelope, timeout=None)
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


async def _test_input(db, wf, trigger, stored, graph, node, source, raw):
    """The envelope the step would really be handed, from the chosen source,
    and the keys a sample lost because the step is never handed them."""
    from src.workflow_document import build_pin
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
    if source == "custom":
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise WorkflowRefused(400, "Paste the sample to test with.")
        envelope, dropped = build_pin(graph, node_id, trigger, raw)
        return envelope, list(dropped or ())
    # example
    from src.workflow_document import node_input_shape
    fields = _declared_fields(node_input_shape(graph, node_id, trigger))
    if not fields:
        raise WorkflowRefused(
            400, f"{label} is handed nothing when it runs, so there is nothing to write an example of.")
    data = await _write_example(wf.owner, node.get("label") or node_id, fields)
    envelope, dropped = build_pin(graph, node_id, trigger, data)
    return envelope, list(dropped or ())


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


def _node_plan(node, owner, tasks_by_id) -> list:
    """What the step would do, as the dry run says it (`dry_run_plan`, the one
    planner): a run-task step is "Would run the task …" and that task's own
    plan, which is what testing it does."""
    from src.builtin_actions import dry_run_plan
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    kind = node.get("kind")
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


def _node_effect_sentences(node, tasks_by_id) -> list:
    from src.builtin_actions import EFFECT_SENTENCES
    from src.workflow_document import node_effects
    return [EFFECT_SENTENCES[e] for e in (node_effects(node, tasks_by_id) or ())
            if e in EFFECT_SENTENCES]
