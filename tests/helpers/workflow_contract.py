# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine's half of Slice B (`C1`), as thin fakes, for `wf-api`'s tests.

`/work/notes/SLICE-B-DESIGN.md` § 7 splits Slice B three ways. `wf-api` (the
routes, `src/workflow_store.py`, the browser's data layer) imports the engine's
names — contract **C1** — which `wf-engine` builds on its own branch at the
same time. Until the two merge, these tests need *something* behind each
import, so this module supplies the smallest stand-in that follows the design's
words for it, and **only where the real one is absent**:

  * `core.database.Workflow`, `WorkflowVersion`, `TaskRunNode` (§ 1.1) — on a
    declarative base of their own, so they never join the product's
    `Base.metadata` (a full-suite run would otherwise create three fake tables
    for every other test). Foreign keys name the real tables' columns, with
    the design's `ON DELETE` rules.
  * `src.workflow_document` (§ 1.2, § 4.1, C1's list) and `src.workflow_runs`.
  * `src.task_action_policy.admin_only_action_of` and
    `record_admin_refusal(..., action=)`.

`install(monkeypatch)` puts each fake in place through `monkeypatch`, so every
one is undone after the test. **After the merge the real modules exist and
`install` installs nothing**: the same tests then drive the real engine, and a
difference between this file's reading of the contract and wf-engine's shows
up as a red test at integration — which is the point of writing them against
the contract rather than against these fakes. The tests therefore assert what
C1 and C2 fix (statuses, shapes, which reason family, what was written), not
the fakes' own sentences. Every seam is listed in `/work/notes/wf-api.md`.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import types
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

import core.database as cdb
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── which halves are real ────────────────────────────────────────────────────

def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


REAL_MODELS = hasattr(cdb, "Workflow")
REAL_DOCUMENT = _module_present("src.workflow_document")
REAL_RUNS = _module_present("src.workflow_runs")


# ── the three tables (§ 1.1), only when core.database has none ───────────────

FakeBase = declarative_base()

if not REAL_MODELS:
    class Workflow(cdb.TimestampMixin, FakeBase):
        __tablename__ = "workflows"
        id = Column(String, primary_key=True)
        owner = Column(String, index=True)
        name = Column(String, nullable=False)
        task_id = Column(String, ForeignKey(cdb.ScheduledTask.__table__.c.id, ondelete="SET NULL"),
                         unique=True, nullable=True)
        graph = Column(Text, nullable=False)
        version = Column(Integer, nullable=False, default=1)
        source_chain = Column(Text, nullable=True)

    class WorkflowVersion(FakeBase):
        __tablename__ = "workflow_versions"
        id = Column(String, primary_key=True)
        workflow_id = Column(String, ForeignKey(Workflow.__table__.c.id, ondelete="CASCADE"),
                             index=True, nullable=False)
        version = Column(Integer, nullable=False)
        name = Column(String)
        graph = Column(Text)
        fingerprint = Column(String)
        source = Column(String)
        created_at = Column(DateTime, default=_utcnow)
        __table_args__ = (UniqueConstraint("workflow_id", "version"),)

    class TaskRunNode(FakeBase):
        __tablename__ = "task_run_nodes"
        id = Column(String, primary_key=True)
        run_id = Column(String, ForeignKey(cdb.TaskRun.__table__.c.id, ondelete="CASCADE"),
                        nullable=False)
        node_id = Column(String)
        kind = Column(String)
        label = Column(String)
        seq = Column(Integer)
        status = Column(String)
        attempt = Column(Integer, default=1)
        dry = Column(Boolean, default=False)
        port = Column(String, nullable=True)
        # Not in § 1.1, but in wf-engine's model (measured in its worktree
        # 2026-10-01): a dry record says how the plan reached the step, so the
        # dry reply's `when`/`depth` are read from it, not walked again.
        reached_by = Column(String, nullable=True)
        depth = Column(Integer, nullable=True)
        workflow_version = Column(Integer)
        started_at = Column(DateTime)
        finished_at = Column(DateTime)
        input = Column(Text)
        output = Column(Text)
        error = Column(Text)
        steps = Column(Text)
        model = Column(String)
        __table_args__ = (Index("ix_fake_task_run_nodes_run_seq", "run_id", "seq"),)
else:  # pragma: no cover - after the merge
    Workflow, WorkflowVersion, TaskRunNode = cdb.Workflow, cdb.WorkflowVersion, cdb.TaskRunNode


def models():
    """`(Workflow, WorkflowVersion, TaskRunNode)` — real or fake."""
    return Workflow, WorkflowVersion, TaskRunNode


def create_all(engine) -> None:
    """Every table these tests touch: the product's, then the fakes if any."""
    cdb.Base.metadata.create_all(engine)
    if not REAL_MODELS:
        FakeBase.metadata.create_all(engine)


# ── src.workflow_document (§ 1.2, § 4) ───────────────────────────────────────

def _document_module():
    from src.builtin_actions import BUILTIN_ACTION_META, BUILTIN_ACTIONS
    from src.event_bus import EVENT_PAYLOAD_FIELDS, TASK_HANDOFF_FIELDS, build_trigger
    from src.task_action_policy import is_admin_only_task_action
    from src.task_scheduler import EDGE_CONDITIONS

    m = types.ModuleType("src.workflow_document")
    m.__file__ = __file__ + "#fake-workflow_document"
    m.GRAPH_VERSION = 1
    m.NODE_KINDS = ("llm", "research", "action", "run_task")
    m.PORTS = EDGE_CONDITIONS
    m.NODE_CONFIG_FIELDS = {
        "llm": ("prompt", "model", "endpoint_url", "character_id", "crew_member_id",
                "max_steps", "output_target"),
        "research": ("prompt", "model", "endpoint_url", "output_target"),
        "action": ("action", "prompt", "output_target"),
        "run_task": ("task_id",),
    }
    m.STAND_IN_FIELDS = ("id", "owner", "name", "prompt", "task_type", "action", "model",
                         "endpoint_url", "session_id", "crew_member_id", "character_id",
                         "tz_name", "max_steps", "output_target")
    m.WORKFLOW_MAX_NODES = 20
    m.WORKFLOW_GRAPH_MAX_BYTES = 256 * 1024
    m.NODE_LABEL_MAX = 120
    m.START_KEY = "start"
    # The reason keys are wf-engine's (`1b3dbb5`, measured 2026-10-01), so a
    # test that names one names the real one; the words are this fake's own.
    m.WORKFLOW_REFUSAL_REASONS = {
        "unreadable": "this workflow could not be read",
        "too_big": "this workflow is too big to keep",
        "no_steps": "this workflow has no steps yet",
        "too_many_steps": "this workflow has more steps than a workflow may have",
        "bad_kind": "a step is not one this workflow can run",
        "missing_setting": "a step is missing something it needs",
        "unknown_action": "a step runs an action Pantheon does not have",
        "unknown_task": "a step runs a task that is not yours",
        "workflow_target": "a step runs a workflow",
        "own_trigger": "a step runs this workflow's own start",
        "unknown_crew": "a step is given to a crew member that is not yours",
        "bad_edge": "an arrow does not join two steps",
        "two_arrows": "a step has two arrows for one outcome",
        "several_starts": "a workflow starts in one place",
        "cycle": "these steps would run in a circle",
        "admin_only": "a step needs an admin",
        "pin_unused": "this step is handed nothing, so a sample would never be used",
        "bad_pin": "a sample must be an object",
        "workflow_member": "a workflow cannot be a step",
        "cross_owner": "the chain reaches a task that is not yours",
    }
    WEBHOOK_FIELDS = ("body", "json", "query", "headers")
    TEST_CONFIRM_EFFECTS = ("notifies", "touches-remote", "deletes", "rewrites", "runs-code")

    class DocumentRefusal(NamedTuple):
        reason: str
        node_ids: tuple
        sentence: str

    class DocumentError(ValueError):
        def __init__(self, refusal):
            super().__init__(refusal)
            self.refusal = refusal

    def refuse(reason, node_ids=(), detail=""):
        lead = m.WORKFLOW_REFUSAL_REASONS[reason]
        lead = lead[:1].upper() + lead[1:]
        return DocumentRefusal(reason, tuple(node_ids), f"{lead}{': ' + detail if detail else ''}.")

    def nodes_of(g):
        return [n for n in (g.get("nodes") or []) if isinstance(n, dict)]

    def parse_graph(raw):
        text = raw if isinstance(raw, str) else json.dumps(raw)
        if len(text.encode("utf-8")) > m.WORKFLOW_GRAPH_MAX_BYTES:
            raise DocumentError(refuse("too_big"))
        try:
            g = json.loads(text)
        except (TypeError, ValueError):
            raise DocumentError(refuse("unreadable")) from None
        if not isinstance(g, dict) or not isinstance(g.get("nodes", []), list) \
                or not isinstance(g.get("edges", []), list):
            raise DocumentError(refuse("unreadable"))
        seen, nodes = set(), []
        for n in g.get("nodes") or []:
            if not isinstance(n, dict) or not str(n.get("id") or "").strip():
                raise DocumentError(refuse("unreadable"))
            nid = str(n["id"])
            if nid in seen or n.get("kind") not in m.NODE_KINDS:
                raise DocumentError(refuse("bad_kind", (nid,)))
            seen.add(nid)
            config = n.get("config") if isinstance(n.get("config"), dict) else {}
            nodes.append({"id": nid, "kind": n["kind"],
                          "label": str(n.get("label") or "")[:m.NODE_LABEL_MAX],
                          "config": {k: v for k, v in config.items()
                                     if k in m.NODE_CONFIG_FIELDS[n["kind"]]},
                          "position": n.get("position"), "pinned": n.get("pinned")})
        edges = []
        for e in g.get("edges") or []:
            if not isinstance(e, dict):
                raise DocumentError(refuse("unreadable"))
            edges.append({"from": str(e.get("from")), "port": e.get("port"), "to": str(e.get("to"))})
        start = g.get(m.START_KEY) if isinstance(g.get(m.START_KEY), dict) else {}
        return {"v": m.GRAPH_VERSION, m.START_KEY: {"position": start.get("position")},
                "nodes": nodes, "edges": edges}

    def entries(g):
        led = {e["to"] for e in g.get("edges") or []}
        return [n for n in nodes_of(g) if n["id"] not in led]

    def validate_document(graph, *, owner, tasks_by_id, crew_ids, owner_is_admin, own_task_id):
        nodes = nodes_of(graph)
        if not nodes:
            return refuse("no_steps")
        if len(nodes) > m.WORKFLOW_MAX_NODES:
            return refuse("too_many_steps")
        ids = {n["id"] for n in nodes}
        for n in nodes:
            c = n.get("config") or {}
            k = n["kind"]
            if k in ("llm", "research") and not str(c.get("prompt") or "").strip():
                return refuse("missing_setting", (n["id"],), f"“{n['label']}” needs a prompt")
            if k == "action":
                if not c.get("action"):
                    return refuse("missing_setting", (n["id"],), f"“{n['label']}” needs an action")
                if c.get("action") not in BUILTIN_ACTIONS:
                    return refuse("unknown_action", (n["id"],))
                if is_admin_only_task_action("action", c.get("action")) and not owner_is_admin:
                    return refuse("admin_only", (n["id"],))
                params = (BUILTIN_ACTION_META.get(c["action"]) or {}).get("params") or []
                if any(p.get("required") for p in params) and not str(c.get("prompt") or "").strip():
                    return refuse("missing_setting", (n["id"],))
            if k == "run_task":
                target_id = str(c.get("task_id") or "")
                if not target_id:
                    return refuse("missing_setting", (n["id"],))
                if target_id == own_task_id:
                    return refuse("own_trigger", (n["id"],))
                target = tasks_by_id.get(target_id)
                if target is None or getattr(target, "owner", None) != owner:
                    return refuse("unknown_task", (n["id"],))
                if (target.task_type or "") == "workflow":
                    return refuse("workflow_target", (n["id"],))
            if c.get("crew_member_id") and c["crew_member_id"] not in crew_ids:
                return refuse("unknown_crew", (n["id"],))
        seen = set()
        for e in graph.get("edges") or []:
            if e["from"] not in ids or e["to"] not in ids or e.get("port") not in m.PORTS:
                return refuse("bad_edge")
            if (e["from"], e["port"]) in seen:
                return refuse("two_arrows", (e["from"],))
            seen.add((e["from"], e["port"]))
        out = {}
        for e in graph.get("edges") or []:
            out.setdefault(e["from"], []).append(e["to"])

        def loop(node, path):
            if node in path:
                return path[path.index(node):]
            for nxt in out.get(node, ()):
                found = loop(nxt, path + [node])
                if found:
                    return found
            return None
        for n in nodes:
            found = loop(n["id"], [])
            if found:
                return refuse("cycle", found)
        roots = entries(graph)
        if len(roots) > 1:
            return refuse("several_starts", tuple(n["id"] for n in roots))
        return None

    def content_fingerprint(name, graph):
        nodes = sorted(({"id": n["id"], "kind": n.get("kind"), "label": n.get("label"),
                         "config": n.get("config") or {}} for n in nodes_of(graph)),
                       key=lambda n: n["id"])
        edges = sorted((e.get("from"), e.get("port"), e.get("to")) for e in graph.get("edges") or [])
        body = json.dumps({"name": name, "nodes": nodes, "edges": edges}, sort_keys=True)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def without_pins(graph):
        out = copy.deepcopy(graph)
        for n in nodes_of(out):
            n["pinned"] = None
        return out

    def merge_positions(graph, positions):
        out = copy.deepcopy(graph)
        for n in nodes_of(out):
            if n["id"] in positions:
                n["position"] = list(positions[n["id"]])
        if m.START_KEY in positions:
            out.setdefault(m.START_KEY, {})["position"] = list(positions[m.START_KEY])
        return out

    def by_id(g):
        return {n["id"]: n for n in nodes_of(g)}

    class InputShape(NamedTuple):
        source: object
        name: object
        fields: tuple

    def entry_node(g):
        roots = entries(g)
        return roots[0] if roots else None

    def next_node(g, node_id, port):
        for e in g.get("edges") or []:
            if e["from"] == node_id and e.get("port") == port:
                return by_id(g).get(e["to"])
        return None

    def reachable_bfs(g):
        """The real one's shape: `[{node, when, depth, parent}]`."""
        first = entry_node(g)
        if first is None:
            return []
        nodes = by_id(g)
        out, seen, frontier = [], {first["id"]}, [(first["id"], None, 0, None)]
        while frontier:
            nxt = []
            for node_id, when, depth, parent in frontier:
                out.append({"node": nodes[node_id], "when": when, "depth": depth, "parent": parent})
                for port in m.PORTS:
                    for e in g.get("edges") or []:
                        if e["from"] == node_id and e.get("port") == port and e["to"] not in seen:
                            seen.add(e["to"])
                            nxt.append((e["to"], port, depth + 1, node_id))
            frontier = nxt
        return out

    def node_input_shape(graph, node_id, trigger_task):
        """The real one's answer: `(source, name, fields)`, `(None, None, ())`
        for a first step that is handed nothing."""
        found = next((e for e in reachable_bfs(graph) if e["node"]["id"] == node_id), None)
        if found is None:
            return InputShape("task", None, TASK_HANDOFF_FIELDS)
        if found["parent"] is not None:
            parent = by_id(graph).get(found["parent"]) or {}
            return InputShape("task", parent.get("label") or found["parent"], TASK_HANDOFF_FIELDS)
        kind = getattr(trigger_task, "trigger_type", None) or "schedule"
        if kind == "event":
            event = getattr(trigger_task, "trigger_event", None)
            return InputShape("event", event, EVENT_PAYLOAD_FIELDS.get(event, ()))
        if kind == "webhook":
            return InputShape("webhook", "webhook", WEBHOOK_FIELDS)
        return InputShape(None, None, ())

    def build_pin(graph, node_id, trigger_task, data):
        """As the real one: a step handed nothing takes no sample, and a
        sample is an object — each refused with a `DocumentError`."""
        shape = node_input_shape(graph, node_id, trigger_task)
        if shape.source is None:
            raise DocumentError(refuse("pin_unused", (node_id,)))
        if not isinstance(data, dict):
            raise DocumentError(refuse("bad_pin", (node_id,)))
        dropped = tuple(sorted(k for k in data if k not in shape.fields))
        return build_trigger(shape.source, shape.name or node_id, data, fields=shape.fields), dropped

    def node_effects(node, tasks_by_id):
        k = node.get("kind")
        if k == "action":
            meta = BUILTIN_ACTION_META.get((node.get("config") or {}).get("action")) or {}
            return tuple(meta.get("effects") or ())
        if k == "run_task":
            return ("runs-task",)
        return ("calls-model", "writes")

    def needs_test_confirmation(node, tasks_by_id):
        if node.get("kind") == "run_task":
            return True
        return bool(set(node_effects(node, tasks_by_id)) & set(TEST_CONFIRM_EFFECTS))

    def chain_to_document(rows, head_id, *, positions=None):
        """As the real one: the engine's chain rule (`validate_graph` from the
        head, with its owner), a member that is a workflow refused, and notes
        saying what was made and what else leads in."""
        from src.task_scheduler import (
            CHAIN_CROSS_OWNER, CHAIN_CYCLE, describe_graph_refusal, task_edges, validate_graph,
        )
        all_rows = list(rows)
        rows = {r.id: r for r in all_rows}
        head_row = rows[head_id]
        owner = getattr(head_row, "owner", None)
        refusal = validate_graph(all_rows, starts=[head_id], owner=owner,
                                 max_depth=m.WORKFLOW_MAX_NODES + 1)
        if refusal is not None:
            names = {r.id: r.name for r in all_rows if getattr(r, "owner", None) == owner}
            if refusal.reason == CHAIN_CYCLE:
                raise DocumentError(DocumentRefusal(
                    "cycle", (), describe_graph_refusal(refusal, names, first=head_id)))
            if refusal.reason == CHAIN_CROSS_OWNER:
                raise DocumentError(DocumentRefusal(
                    "cross_owner", (), describe_graph_refusal(refusal, names)))
            raise DocumentError(refuse("too_many_steps"))
        order, seen, frontier = [], {head_id}, [head_id]
        while frontier:
            nxt = []
            for tid in frontier:
                order.append(tid)
                for col in ("then_task_id", "else_task_id"):
                    to = getattr(rows[tid], col, None)
                    if to in rows and to not in seen:
                        seen.add(to)
                        nxt.append(to)
            frontier = nxt
        for tid in order:
            if (rows[tid].task_type or "") == "workflow":
                raise DocumentError(refuse("workflow_member", detail=f"“{rows[tid].name}” is a workflow"))
        ids = {tid: f"n{i + 1}" for i, tid in enumerate(order)}
        nodes, edges = [], []
        for tid in order:
            t = rows[tid]
            kind = t.task_type or "llm"
            config = {k: getattr(t, k, None) for k in m.NODE_CONFIG_FIELDS[kind]
                      if getattr(t, k, None) not in (None, "")}
            pos = (positions or {}).get(tid)
            nodes.append({"id": ids[tid], "kind": kind, "label": t.name, "config": config,
                          "position": list(pos) if pos else None, "pinned": None})
            for col, port in (("then_task_id", "success"), ("else_task_id", "error")):
                to = getattr(t, col, None)
                if to in ids:
                    edges.append({"from": ids[tid], "port": port, "to": ids[to]})
        head = rows[head_id]
        trigger = {k: getattr(head, k, None) for k in (
            "schedule", "scheduled_time", "scheduled_day", "scheduled_date", "cron_expression",
            "trigger_type", "trigger_event", "trigger_count", "tz_name", "max_retries",
            "timeout_seconds", "notifications_enabled")}
        graph = {"v": m.GRAPH_VERSION, m.START_KEY: {"position": None}, "nodes": nodes,
                 "edges": edges}
        notes = [f"Made from {len(order)} step{'s' if len(order) != 1 else ''}, "
                 f"starting with “{head.name}”."]
        for name in sorted({r.name for r in all_rows if r.id not in seen
                            and getattr(r, "owner", None) == owner
                            and any(e["to"] in seen for e in task_edges(r))}):
            notes.append(f"“{name}” also leads into this chain. It is not part of the "
                         f"workflow and keeps running as it does now.")
        if (getattr(head, "trigger_type", None) or "schedule") == "webhook":
            notes.append("The workflow has its own webhook address. The chain's old "
                         "address only answers while the chain is on.")
        return graph, trigger, notes

    for fn in (DocumentRefusal, DocumentError, InputShape, parse_graph, validate_document,
               content_fingerprint, without_pins, merge_positions, node_input_shape, build_pin,
               entry_node, next_node, reachable_bfs, node_effects, needs_test_confirmation,
               chain_to_document):
        setattr(m, fn.__name__, fn)
    m.TEST_CONFIRM_EFFECTS = TEST_CONFIRM_EFFECTS
    return m


# ── src.workflow_runs ────────────────────────────────────────────────────────

def _runs_module():
    from src.event_bus import trigger_summary

    m = types.ModuleType("src.workflow_runs")
    m.__file__ = __file__ + "#fake-workflow_runs"

    def _json(raw):
        try:
            return json.loads(raw) if raw else None
        except (TypeError, ValueError):
            return raw

    def _iso(v):
        return v.isoformat() + "Z" if v else None

    def node_record_to_dict(rec):
        data = _json(rec.input)
        return {
            "id": rec.id, "node_id": rec.node_id, "kind": rec.kind, "label": rec.label,
            "seq": rec.seq, "status": rec.status, "attempt": rec.attempt, "dry": bool(rec.dry),
            "port": rec.port, "workflow_version": rec.workflow_version,
            "started_at": _iso(rec.started_at), "finished_at": _iso(rec.finished_at),
            "input": data,
            "input_summary": trigger_summary(data) if isinstance(data, dict) else "",
            "output": _json(rec.output), "error": rec.error, "steps": _json(rec.steps) or [],
            "model": rec.model,
        }

    def last_node_record(db, task_id, node_id):
        return (db.query(TaskRunNode).join(cdb.TaskRun, cdb.TaskRun.id == TaskRunNode.run_id)
                .filter(cdb.TaskRun.task_id == task_id, TaskRunNode.node_id == node_id,
                        TaskRunNode.dry.is_(False))
                .order_by(TaskRunNode.started_at.desc()).first())

    def maybe_prune_node_records(db):
        return 0

    m.node_record_to_dict = node_record_to_dict
    m.last_node_record = last_node_record
    m.maybe_prune_node_records = maybe_prune_node_records
    return m


# ── src.task_action_policy additions ─────────────────────────────────────────

def _admin_only_action_of(db, task):
    """C1: the task's own admin-only action, or the first admin-only action
    step in its document."""
    from src.task_action_policy import is_admin_only_task_action
    if (getattr(task, "task_type", None) or "") == "workflow":
        wf = db.query(Workflow).filter(Workflow.task_id == task.id).first()
        graph = json.loads(wf.graph) if wf is not None and wf.graph else {}
        for n in graph.get("nodes") or []:
            action = (n.get("config") or {}).get("action")
            if n.get("kind") == "action" and is_admin_only_task_action("action", action):
                return action
        return None
    if is_admin_only_task_action(task.task_type, task.action):
        return task.action
    return None


def _record_admin_refusal_with(real):
    def record_admin_refusal(db, task, *, run_id=None, action=None):
        if action is None:
            return real(db, task, run_id=run_id)
        from src.task_action_policy import admin_refusal_message
        msg = admin_refusal_message(action)
        now = _utcnow()
        run = cdb.TaskRun(id=str(uuid.uuid4()), task_id=task.id, started_at=now,
                          status="skipped", result=msg, error=msg, finished_at=now)
        db.add(run)
        task.status = "paused"
        task.next_run = None
        db.commit()
        return msg
    return record_admin_refusal


# ── putting them in place ────────────────────────────────────────────────────

_DOC = None
_RUNS = None


def install(monkeypatch) -> dict:
    """Install every fake whose real half is absent. Returns what was faked,
    so a test (and the note) can say which seams were in play."""
    global _DOC, _RUNS
    import src
    import src.task_action_policy as tap
    faked = {}
    if not REAL_MODELS:
        for name, model in (("Workflow", Workflow), ("WorkflowVersion", WorkflowVersion),
                            ("TaskRunNode", TaskRunNode)):
            monkeypatch.setattr(cdb, name, model, raising=False)
        faked["models"] = True
    if not REAL_DOCUMENT:
        _DOC = _DOC or _document_module()
        monkeypatch.setitem(sys.modules, "src.workflow_document", _DOC)
        monkeypatch.setattr(src, "workflow_document", _DOC, raising=False)
        faked["workflow_document"] = True
    if not REAL_RUNS:
        _RUNS = _RUNS or _runs_module()
        monkeypatch.setitem(sys.modules, "src.workflow_runs", _RUNS)
        monkeypatch.setattr(src, "workflow_runs", _RUNS, raising=False)
        faked["workflow_runs"] = True
    if not hasattr(tap, "admin_only_action_of"):
        monkeypatch.setattr(tap, "admin_only_action_of", _admin_only_action_of, raising=False)
        faked["admin_only_action_of"] = True
    import inspect
    if "action" not in inspect.signature(tap.record_admin_refusal).parameters:
        monkeypatch.setattr(tap, "record_admin_refusal",
                            _record_admin_refusal_with(tap.record_admin_refusal))
        faked["record_admin_refusal"] = True
    return faked


def document():
    """`src.workflow_document` as installed — call after `install`."""
    import importlib
    return importlib.import_module("src.workflow_document")
