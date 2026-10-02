# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` — a workflow is one document. This module is the document, pure.

`D-2026-10-01-05` §1: a workflow is a named, versioned graph in its own table
(`core.database.Workflow`), started by one `ScheduledTask` with
`task_type="workflow"`, so every scheduling, gating, retry, timeout and dry-run
rule the engine has applies to it unchanged. What the trigger runs is this
document, walked by `TaskScheduler._run_workflow`.

Everything here is pure — no session, no network, no clock but `build_trigger`'s
stamp — so the save route, the engine at run, the dry run and the test of one
step all ask the same functions and cannot disagree (`Law 7`):

  * `parse_graph` — the stored JSON, read and shaped, or a `DocumentError`;
  * `validate_document` — the first reason this document may not run, or `None`,
    with the SAME sentence at save and at run. Loops are `P22-01`'s rule,
    `validate_graph`, asked about the document's own edges — not a second rule;
  * the walk: `entry_node`, `next_node`, `reachable_bfs`;
  * the stand-in a step runs as (`WorkflowNodeTask`, `node_stand_in`);
  * versions' fingerprint, positions, pins, and a chain made into a document.

**One vocabulary (`Law 14`).** Step kinds are the `task_type` values the
executors already take (`llm` / `research` / `action`) plus `run_task`; ports
are `EDGE_CONDITIONS`, imported; config keys are `ScheduledTask` column names.

`FORBIDDEN.md` Part 1 (added at this row's merge): `GRAPH_VERSION`'s value, the
four `NODE_KINDS`, the two `PORTS`, the three `WORKFLOW_VERSION_SOURCES` and
`WORKFLOW_TASK_TYPE` are stored in rows; a rename orphans every stored workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import NamedTuple

from src.event_bus import (
    EVENT_PAYLOAD_FIELDS,
    TASK_HANDOFF_FIELDS,
    TRIGGER_SOURCE_EVENT,
    TRIGGER_SOURCE_TASK,
    TRIGGER_SOURCE_WEBHOOK,
    WEBHOOK_PAYLOAD_FIELDS,
    build_trigger,
)
from src.task_scheduler import (
    CHAIN_CROSS_OWNER,
    CHAIN_CYCLE,
    EDGE_COLUMNS,
    EDGE_CONDITIONS,
    describe_graph_refusal,
    task_edges,
    validate_graph,
)

# ── Stored values (`FORBIDDEN.md` Part 1 at the merge) ──────────────────────
GRAPH_VERSION = 1
# `ScheduledTask.task_type` of a workflow's trigger. A stored value ADDED, none
# renamed: `llm`, `research` and `action` keep their meaning.
WORKFLOW_TASK_TYPE = "workflow"
NODE_KIND_PROMPT = "llm"
NODE_KIND_RESEARCH = "research"
NODE_KIND_ACTION = "action"
NODE_KIND_RUN_TASK = "run_task"
NODE_KINDS = (NODE_KIND_PROMPT, NODE_KIND_RESEARCH, NODE_KIND_ACTION, NODE_KIND_RUN_TASK)
# The kinds that run through a stand-in and one of the three executors.
# `run_task` runs a real task instead (`TaskScheduler._run_workflow_node`).
STAND_IN_KINDS = (NODE_KIND_PROMPT, NODE_KIND_RESEARCH, NODE_KIND_ACTION)
# Which outcome edge a step leaves by. `EDGE_CONDITIONS`, imported, never typed
# again: "if it works" / "if it fails" are already drawn from these words.
PORTS = EDGE_CONDITIONS
# The start item's key in `graph["start"]` and in a positions map. Reserved: no
# step may be called this.
START_KEY = "start"
# Where a kept version came from (`workflow_versions.source`). Named one by
# one so the store writes each by its name rather than restating the word
# (`src/workflow_store.py`, `Law 7`; added at the wave C merge).
VERSION_SOURCE_USER = "user"
VERSION_SOURCE_CONVERTED = "converted"
VERSION_SOURCE_RESTORED = "restored"
WORKFLOW_VERSION_SOURCES = (VERSION_SOURCE_USER, VERSION_SOURCE_CONVERTED, VERSION_SOURCE_RESTORED)

# What each kind of step may be configured with — `ScheduledTask` field names,
# read by the executors under those names (`node_stand_in`). `output_target`
# null means "only hand it to the next step", the default for a new step.
NODE_CONFIG_FIELDS = {
    NODE_KIND_PROMPT: ("prompt", "model", "endpoint_url", "character_id",
                       "crew_member_id", "max_steps", "output_target"),
    NODE_KIND_RESEARCH: ("prompt", "model", "endpoint_url", "output_target"),
    NODE_KIND_ACTION: ("action", "prompt", "output_target"),
    NODE_KIND_RUN_TASK: ("task_id",),
}

# ── The stand-in a step runs as (§2.2) ──────────────────────────────────────
#
# Every attribute the three executors and their callees read off `task`,
# measured by walking them (`tests/test_a_workflow_step_runs_as_a_task.py` holds
# it by AST and by driving each one): `_execute_action`, `_execute_llm_task`,
# `_execute_checkin`, `_run_agent_loop`, `_execute_research_task`,
# `_deliver_task_result` and its two deliverers, `_resolve_task_timezone`, and
# `SessionManager.ensure_task_session` (which writes `session_id`).
STAND_IN_FIELDS = (
    "id", "owner", "name", "prompt", "task_type", "action", "model",
    "endpoint_url", "session_id", "crew_member_id", "character_id", "tz_name",
    "max_steps", "output_target",
)

# ── Caps (mistake prevention, not a control — `Law 17`) ─────────────────────
#
# Twenty steps also bounds `validate_graph`, which enumerates PATHS: with two
# ports per step the worst DAG on 20 steps has a Fibonacci number of paths from
# any one start (~11k), which is cheap; on 200 it would not be.
WORKFLOW_MAX_NODES = 20
WORKFLOW_GRAPH_MAX_BYTES = 256 * 1024
NODE_LABEL_MAX = 120
NODE_ID_MAX = 64
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# ── Why a document may not run (`Law 10`: an enum, the sentence derived) ────
REFUSE_UNREADABLE = "unreadable"
REFUSE_TOO_BIG = "too_big"
REFUSE_VERSION = "version"
REFUSE_NO_STEPS = "no_steps"
REFUSE_TOO_MANY_STEPS = "too_many_steps"
REFUSE_BAD_ID = "bad_id"
REFUSE_DUPLICATE_ID = "duplicate_id"
REFUSE_BAD_KIND = "bad_kind"
REFUSE_BAD_LABEL = "bad_label"
REFUSE_BAD_SETTING = "bad_setting"
REFUSE_MISSING_SETTING = "missing_setting"
REFUSE_UNKNOWN_ACTION = "unknown_action"
REFUSE_ADMIN_ONLY = "admin_only"
REFUSE_UNKNOWN_TASK = "unknown_task"
REFUSE_WORKFLOW_TARGET = "workflow_target"
REFUSE_OWN_TRIGGER = "own_trigger"
REFUSE_UNKNOWN_CREW = "unknown_crew"
REFUSE_BAD_EDGE = "bad_edge"
REFUSE_TWO_ARROWS = "two_arrows"
REFUSE_CYCLE = CHAIN_CYCLE
REFUSE_SEVERAL_STARTS = "several_starts"
REFUSE_PIN_UNUSED = "pin_unused"
REFUSE_BAD_PIN = "bad_pin"
REFUSE_WORKFLOW_MEMBER = "workflow_member"
REFUSE_CROSS_OWNER = CHAIN_CROSS_OWNER

WORKFLOW_REFUSAL_REASONS = {
    REFUSE_UNREADABLE: "the workflow could not be read",
    REFUSE_TOO_BIG: f"the workflow is larger than {WORKFLOW_GRAPH_MAX_BYTES // 1024} KiB",
    REFUSE_VERSION: "the workflow was saved by a newer Pantheon",
    REFUSE_NO_STEPS: "the workflow has no steps",
    REFUSE_TOO_MANY_STEPS: f"the workflow has more than {WORKFLOW_MAX_NODES} steps",
    REFUSE_BAD_ID: "a step has an id that cannot be used",
    REFUSE_DUPLICATE_ID: "two steps have the same id",
    REFUSE_BAD_KIND: "a step is of a kind this Pantheon does not run",
    REFUSE_BAD_LABEL: "a step's name cannot be used",
    REFUSE_BAD_SETTING: "a step has a setting it does not take",
    REFUSE_MISSING_SETTING: "a step is missing what it needs to run",
    REFUSE_UNKNOWN_ACTION: "a step names an action this Pantheon does not have",
    REFUSE_ADMIN_ONLY: "a step runs an action only an admin may run",
    REFUSE_UNKNOWN_TASK: "a step runs a task that is not one of yours",
    REFUSE_WORKFLOW_TARGET: "a step runs another workflow",
    REFUSE_OWN_TRIGGER: "a step runs this workflow itself",
    REFUSE_UNKNOWN_CREW: "a step uses a crew member that is not one of yours",
    REFUSE_BAD_EDGE: "an arrow does not join two steps",
    REFUSE_TWO_ARROWS: "a step has two arrows for the same outcome",
    REFUSE_CYCLE: "the workflow loops back on itself",
    REFUSE_SEVERAL_STARTS: "more than one step has nothing leading to it",
    REFUSE_PIN_UNUSED: "the step is handed nothing, so a sample would never be used",
    REFUSE_BAD_PIN: "the sample is not a set of named fields",
    REFUSE_WORKFLOW_MEMBER: "the chain runs a workflow",
    REFUSE_CROSS_OWNER: "the chain reaches another owner's task",
}


class DocumentRefusal(NamedTuple):
    """Why a document may not run. `reason` is a `WORKFLOW_REFUSAL_REASONS` key
    — an enum, never a sentence; `node_ids` the steps it is about (empty when
    it is about the whole); `sentence` what a person is told, at save and at
    run alike."""
    reason: str
    node_ids: tuple
    sentence: str


class DocumentError(ValueError):
    """`parse_graph` (and the other shaping functions) could not use what they
    were given. Carries the `DocumentRefusal`."""

    def __init__(self, refusal: DocumentRefusal):
        super().__init__(refusal.sentence)
        self.refusal = refusal


def _refusal(reason: str, node_ids=(), detail: str | None = None) -> DocumentRefusal:
    lead = WORKFLOW_REFUSAL_REASONS[reason]
    lead = lead[:1].upper() + lead[1:]
    sentence = f"{lead}: {detail}" if detail else f"{lead}."
    if detail and not sentence.endswith((".", "?", "!")):
        sentence += "."
    return DocumentRefusal(reason, tuple(node_ids), sentence)


def _fail(reason: str, node_ids=(), detail: str | None = None):
    raise DocumentError(_refusal(reason, node_ids, detail))


def _called(node_or_label) -> str:
    if isinstance(node_or_label, dict):
        label = node_or_label.get("label") or node_or_label.get("id") or "?"
    else:
        label = node_or_label or "?"
    return f"“{label}”"


# ── Reading ──────────────────────────────────────────────────────────────────

def _position(value, where: str):
    if value is None:
        return None
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in value)):
        return [value[0], value[1]]
    _fail(REFUSE_UNREADABLE, detail=f"{where} has a position that is not two numbers")


def parse_graph(raw) -> dict:
    """The stored document, read and shaped. Raises `DocumentError`.

    Takes the JSON text (`workflows.graph`) or an already-decoded dict (a
    request body). Checks the SHAPE — sizes, types, the version — and answers
    a fresh dict with exactly the schema's keys:
    `{v, start: {position}, nodes: [{id, kind, label, config, position, pinned}],
    edges: [{from, port, to}]}`. What the steps SAY is `validate_document`'s.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            _fail(REFUSE_UNREADABLE, detail="it is not text")
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > WORKFLOW_GRAPH_MAX_BYTES:
            _fail(REFUSE_TOO_BIG)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            _fail(REFUSE_UNREADABLE, detail="it is not JSON")
    elif isinstance(raw, dict):
        data = raw
        try:
            size = len(json.dumps(raw, default=str).encode("utf-8"))
        except (TypeError, ValueError):
            _fail(REFUSE_UNREADABLE, detail="it is not JSON")
        if size > WORKFLOW_GRAPH_MAX_BYTES:
            _fail(REFUSE_TOO_BIG)
    else:
        _fail(REFUSE_UNREADABLE, detail="it is empty")
    if not isinstance(data, dict):
        _fail(REFUSE_UNREADABLE, detail="it is not an object")
    v = data.get("v")
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(REFUSE_UNREADABLE, detail="it has no version")
    if v != GRAPH_VERSION:
        _fail(REFUSE_VERSION, detail=f"version {v}; this one reads version {GRAPH_VERSION}")
    nodes_in = data.get("nodes", [])
    edges_in = data.get("edges", [])
    start_in = data.get("start") or {}
    if not isinstance(nodes_in, list) or not isinstance(edges_in, list) \
            or not isinstance(start_in, dict):
        _fail(REFUSE_UNREADABLE, detail="its steps or arrows are not lists")
    nodes = []
    for index, node in enumerate(nodes_in, start=1):
        if not isinstance(node, dict):
            _fail(REFUSE_UNREADABLE, detail=f"step {index} is not an object")
        node_id, kind, label = node.get("id"), node.get("kind"), node.get("label")
        for name, value in (("id", node_id), ("kind", kind), ("name", label)):
            if not isinstance(value, str):
                _fail(REFUSE_UNREADABLE, detail=f"step {index} has no {name}")
        config = node.get("config")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            _fail(REFUSE_UNREADABLE, (node_id,), f"{_called(label)} has settings that are not an object")
        pinned = node.get("pinned")
        if pinned is not None and not isinstance(pinned, dict):
            _fail(REFUSE_UNREADABLE, (node_id,), f"{_called(label)} has a sample that is not an object")
        nodes.append({
            "id": node_id,
            "kind": kind,
            "label": label,
            "config": dict(config),
            "position": _position(node.get("position"), _called(label)),
            "pinned": pinned,
        })
    edges = []
    for index, edge in enumerate(edges_in, start=1):
        if not isinstance(edge, dict) or not all(
                isinstance(edge.get(k), str) for k in ("from", "port", "to")):
            _fail(REFUSE_UNREADABLE, detail=f"arrow {index} does not name where it goes")
        edges.append({"from": edge["from"], "port": edge["port"], "to": edge["to"]})
    return {
        "v": GRAPH_VERSION,
        "start": {"position": _position(start_in.get("position"), "the start")},
        "nodes": nodes,
        "edges": edges,
    }


def empty_graph() -> dict:
    """A new workflow's document: a start and nothing after it."""
    return {"v": GRAPH_VERSION, "start": {"position": None}, "nodes": [], "edges": []}


# ── The walk ─────────────────────────────────────────────────────────────────

def _nodes_by_id(g: dict) -> dict:
    return {node["id"]: node for node in g.get("nodes") or ()}


def _out_edges(g: dict, node_id: str) -> list:
    """Edges leaving `node_id`, in `PORTS` order ("if it works" first)."""
    found = [e for e in g.get("edges") or () if e["from"] == node_id]
    order = {port: i for i, port in enumerate(PORTS)}
    return sorted(found, key=lambda e: order.get(e["port"], len(order)))


def _entries(g: dict) -> list:
    led_to = {e["to"] for e in g.get("edges") or ()}
    return [n for n in g.get("nodes") or () if n["id"] not in led_to]


def entry_node(g: dict):
    """The step the workflow starts at: the one nothing leads to. `None` for a
    document with no steps (or, in a document `validate_document` refuses, the
    first of several)."""
    entries = _entries(g)
    return entries[0] if entries else None


def next_node(g: dict, node_id: str, port: str):
    """The step the `port` arrow out of `node_id` leads to, or `None`."""
    by_id = _nodes_by_id(g)
    for edge in g.get("edges") or ():
        if edge["from"] == node_id and edge["port"] == port:
            return by_id.get(edge["to"])
    return None


def reachable_bfs(g: dict) -> list:
    """Every step reachable from the entry, each once, breadth first.

    `[{node, when, depth, parent}]` — the entry first (`when` None, depth 0);
    `when` is the port of the arrow from its first parent in this order, which
    is wave B's chain dry run's rule (`plan_dry_chain`) on a document.
    """
    start = entry_node(g)
    if start is None:
        return []
    by_id = _nodes_by_id(g)
    out = [{"node": start, "when": None, "depth": 0, "parent": None}]
    seen = {start["id"]}
    frontier = [start]
    depth = 0
    while frontier:
        depth += 1
        following = []
        for node in frontier:
            for edge in _out_edges(g, node["id"]):
                target = by_id.get(edge["to"])
                if target is None or target["id"] in seen:
                    continue
                seen.add(target["id"])
                following.append(target)
                out.append({"node": target, "when": edge["port"], "depth": depth,
                            "parent": node["id"]})
        frontier = following
    return out


class _Row:
    """A step as `validate_graph` reads a task: `id`, `owner` and the
    `EDGE_COLUMNS` columns. The document's arrows, projected (`P22-01`'s rule
    asked about a document, not a second rule)."""
    __slots__ = ("id", "owner", *EDGE_COLUMNS.values())

    def __init__(self, node_id, edges):
        self.id = node_id
        self.owner = None
        for port, column in EDGE_COLUMNS.items():
            setattr(self, column, edges.get(port))


def document_rows(g: dict) -> list:
    """The document's steps as rows `validate_graph` and `task_edges` read."""
    rows = []
    for node in g.get("nodes") or ():
        edges = {e["port"]: e["to"] for e in _out_edges(g, node["id"])
                 if e["port"] in EDGE_COLUMNS}
        rows.append(_Row(node["id"], edges))
    return rows


# ── The rule ─────────────────────────────────────────────────────────────────

def _setting_problem(kind: str, config: dict) -> str | None:
    """A config key this kind does not take, or a value of the wrong type."""
    from src.run_limits import AGENT_MAX_ROUNDS_RANGE

    allowed = NODE_CONFIG_FIELDS.get(kind, ())
    for key, value in config.items():
        if key not in allowed:
            return f"“{key}”"
        if key == "max_steps":
            lo, hi = AGENT_MAX_ROUNDS_RANGE
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or not lo <= value <= hi):
                return f"“max_steps” must be a whole number from {lo} to {hi}"
        elif value is not None and not isinstance(value, str):
            return f"“{key}” must be text"
    return None


def _text(config: dict, key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


def validate_document(graph: dict, *, owner: str | None, tasks_by_id: dict,
                      crew_ids, owner_is_admin: bool,
                      own_task_id: str | None) -> DocumentRefusal | None:
    """The first reason this document may not run, or `None`. Pure.

    Asked at save (the workflow routes, against the person's own tasks and
    crew) and again at run (the walker, against the same, read fresh), so a
    task deleted or a role lost between the two is caught where it matters,
    in the same words. `graph` is `parse_graph`'s answer. `tasks_by_id` is the
    owner's tasks, by id; `crew_ids` the owner's crew member ids.

    Loops are `P22-01`'s rule: `validate_graph` over `document_rows`, from
    every step, with a depth cap no simple path can reach — so only a loop is
    found — and `describe_graph_refusal`'s sentence, naming steps by label.
    """
    from src.builtin_actions import BUILTIN_ACTION_META, BUILTIN_ACTIONS
    from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS, admin_refusal_message

    nodes = list(graph.get("nodes") or ())
    edges = list(graph.get("edges") or ())
    if not nodes:
        return _refusal(REFUSE_NO_STEPS, detail="add a step after the start")
    if len(nodes) > WORKFLOW_MAX_NODES:
        return _refusal(REFUSE_TOO_MANY_STEPS,
                        detail=f"it has {len(nodes)}. Split it, or run part of it "
                               f"as its own task")
    crew_ids = set(crew_ids or ())
    tasks_by_id = tasks_by_id or {}
    seen = set()
    for node in nodes:
        node_id, kind, label = node["id"], node["kind"], node["label"]
        if (not node_id or len(node_id) > NODE_ID_MAX or not _NODE_ID_RE.match(node_id)
                or node_id == START_KEY or node_id.startswith("__")):
            return _refusal(REFUSE_BAD_ID, (node_id,),
                            f"{_called(node)} is called {node_id!r}")
        if node_id in seen:
            return _refusal(REFUSE_DUPLICATE_ID, (node_id,), f"{node_id!r}")
        seen.add(node_id)
        if not label.strip():
            return _refusal(REFUSE_BAD_LABEL, (node_id,), "every step needs a name")
        if len(label) > NODE_LABEL_MAX:
            return _refusal(REFUSE_BAD_LABEL, (node_id,),
                            f"{_called(label[:40] + '…')} is longer than "
                            f"{NODE_LABEL_MAX} characters")
        if kind not in NODE_KINDS:
            return _refusal(REFUSE_BAD_KIND, (node_id,), f"{_called(node)} is a {kind!r} step")
        config = node.get("config") or {}
        problem = _setting_problem(kind, config)
        if problem:
            return _refusal(REFUSE_BAD_SETTING, (node_id,), f"{_called(node)}: {problem}")
        if kind in (NODE_KIND_PROMPT, NODE_KIND_RESEARCH) and not _text(config, "prompt"):
            what = "what to ask" if kind == NODE_KIND_PROMPT else "the question to research"
            return _refusal(REFUSE_MISSING_SETTING, (node_id,), f"{_called(node)} needs {what}")
        if kind == NODE_KIND_ACTION:
            action = _text(config, "action")
            if not action:
                return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                                f"{_called(node)} needs an action")
            if action not in BUILTIN_ACTIONS:
                return _refusal(REFUSE_UNKNOWN_ACTION, (node_id,), f"{_called(node)} runs {action!r}")
            if action in ADMIN_ONLY_TASK_ACTIONS and not owner_is_admin:
                return _refusal(REFUSE_ADMIN_ONLY, (node_id,),
                                f"{_called(node)}. {admin_refusal_message(action)}")
            for param in (BUILTIN_ACTION_META.get(action) or {}).get("params") or ():
                if param.get("required") and not _text(config, "prompt"):
                    return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                                    f"{_called(node)} needs its {(param.get('label') or 'input').lower()}")
        if kind == NODE_KIND_RUN_TASK:
            target_id = _text(config, "task_id")
            if not target_id:
                return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                                f"{_called(node)} needs a task to run")
            if own_task_id and target_id == own_task_id:
                return _refusal(REFUSE_OWN_TRIGGER, (node_id,), f"{_called(node)}")
            target = tasks_by_id.get(target_id)
            # Another owner's task and a missing one are the same answer: the
            # sentence never says which, so it is not a way to learn ids.
            if target is None or getattr(target, "owner", None) != owner:
                return _refusal(REFUSE_UNKNOWN_TASK, (node_id,), f"{_called(node)}")
            if (getattr(target, "task_type", None) or "llm") == WORKFLOW_TASK_TYPE:
                return _refusal(REFUSE_WORKFLOW_TARGET, (node_id,),
                                f"{_called(node)} runs “{getattr(target, 'name', None) or target_id}”, "
                                f"which is a workflow. Run its steps here instead")
            target_action = getattr(target, "action", None)
            if ((getattr(target, "task_type", None) or "llm") == NODE_KIND_ACTION
                    and target_action in ADMIN_ONLY_TASK_ACTIONS and not owner_is_admin):
                return _refusal(REFUSE_ADMIN_ONLY, (node_id,),
                                f"{_called(node)}. {admin_refusal_message(target_action)}")
        crew = _text(config, "crew_member_id")
        if crew and crew not in crew_ids:
            return _refusal(REFUSE_UNKNOWN_CREW, (node_id,), f"{_called(node)}")
    by_id = _nodes_by_id(graph)
    taken = set()
    for edge in edges:
        if edge["from"] not in by_id or edge["to"] not in by_id:
            return _refusal(REFUSE_BAD_EDGE,
                            tuple(i for i in (edge["from"], edge["to"]) if i in by_id),
                            "it points at a step that is not in the workflow")
        if edge["port"] not in PORTS:
            return _refusal(REFUSE_BAD_EDGE, (edge["from"],),
                            f"the arrow out of {_called(by_id[edge['from']])} is "
                            f"neither “if it works” nor “if it fails”")
        key = (edge["from"], edge["port"])
        if key in taken:
            word = "works" if edge["port"] == PORTS[0] else "fails"
            return _refusal(REFUSE_TWO_ARROWS, (edge["from"],),
                            f"{_called(by_id[edge['from']])} has two “if it {word}” arrows. "
                            f"Remove one")
        taken.add(key)
    loop = validate_graph(document_rows(graph), starts=[n["id"] for n in nodes],
                          owner=None, max_depth=len(nodes) + 1)
    if loop is not None:
        sentence = describe_graph_refusal(
            loop, names={n["id"]: n["label"] for n in nodes},
            lead=WORKFLOW_REFUSAL_REASONS[REFUSE_CYCLE])
        ids = tuple(dict.fromkeys(e["from"] for e in loop.path))
        return DocumentRefusal(REFUSE_CYCLE, ids, sentence)
    entries = _entries(graph)
    if len(entries) > 1:
        named = ", ".join(_called(n) for n in entries[:4])
        return _refusal(REFUSE_SEVERAL_STARTS, tuple(n["id"] for n in entries),
                        f"{named}. Connect each to the step before it, or remove it")
    return None


# ── Versions, positions, pins ───────────────────────────────────────────────

def without_pins(graph: dict) -> dict:
    """A copy with every step's sample removed — what a kept version holds."""
    out = json.loads(json.dumps(graph, default=str))
    for node in out.get("nodes") or ():
        node["pinned"] = None
    return out


def content_fingerprint(name: str, graph: dict) -> str:
    """What has to move before a save is an edit (`P8-10`'s rule).

    The name, every step's id, kind, label and settings, and the arrows.
    NOT where a step sits, not its pinned sample, not where the start sits —
    the bookkeeping exclusion `services/memory/skills.py` makes for a skill —
    and not the order steps or arrows are listed in, which changes nothing a
    run does.
    """
    nodes = sorted(
        ({"id": n.get("id"), "kind": n.get("kind"), "label": n.get("label"),
          "config": n.get("config") or {}} for n in graph.get("nodes") or ()),
        key=lambda n: str(n["id"]))
    edges = sorted(
        ({"from": e.get("from"), "port": e.get("port"), "to": e.get("to")}
         for e in graph.get("edges") or ()),
        key=lambda e: (str(e["from"]), str(e["port"]), str(e["to"])))
    body = json.dumps({"name": (name or "").strip(), "v": graph.get("v"),
                       "nodes": nodes, "edges": edges},
                      sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def merge_positions(graph: dict, positions: dict) -> dict:
    """A copy with the given positions applied: `{step id | START_KEY: [x, y]}`.

    An id the document no longer has is ignored (a position saved for a step
    deleted in another tab). A position that is not two numbers is refused.
    """
    out = json.loads(json.dumps(graph, default=str))
    by_id = _nodes_by_id(out)
    for key, value in (positions or {}).items():
        if key == START_KEY:
            out.setdefault("start", {})["position"] = _position(value, "the start")
        elif key in by_id:
            by_id[key]["position"] = _position(value, _called(by_id[key]))
    return out


class InputShape(NamedTuple):
    """What a step is handed when it really runs. `source` is a
    `TRIGGER_SOURCE_*` word, or `None` when it is handed nothing (a first step
    on a schedule, or started by hand); `name` is the envelope's `event`;
    `fields` the keys its `data` may carry."""
    source: str | None
    name: str | None
    fields: tuple


def node_input_shape(graph: dict, node_id: str, trigger_task) -> InputShape:
    """The envelope `node_id` would be handed: the trigger's for the first step
    (an event's declared fields, a webhook's four), the step before it's hand-
    off for any other (`TASK_HANDOFF_FIELDS`, named for its first parent)."""
    found = next((e for e in reachable_bfs(graph) if e["node"]["id"] == node_id), None)
    if found is None:
        # Not reachable from the start — a step in a draft, not connected
        # yet. Once it is, it is handed the step before it's hand-off.
        return InputShape(TRIGGER_SOURCE_TASK, None, TASK_HANDOFF_FIELDS)
    if found["parent"] is not None:
        parent = _nodes_by_id(graph).get(found["parent"]) or {}
        return InputShape(TRIGGER_SOURCE_TASK, parent.get("label") or found["parent"],
                          TASK_HANDOFF_FIELDS)
    trigger_type = getattr(trigger_task, "trigger_type", None) or "schedule"
    if trigger_type == "event":
        event = getattr(trigger_task, "trigger_event", None)
        return InputShape(TRIGGER_SOURCE_EVENT, event, EVENT_PAYLOAD_FIELDS.get(event, ()))
    if trigger_type == "webhook":
        return InputShape(TRIGGER_SOURCE_WEBHOOK, TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS)
    return InputShape(None, None, ())


def build_pin(graph: dict, node_id: str, trigger_task, data) -> tuple:
    """`(envelope, dropped_keys)` — a sample for `node_id`, in the shape it
    would really be handed, built by `build_trigger` (the one envelope
    builder). Keys that shape does not declare are dropped, and named so the
    person can be told which. A step that is handed nothing takes no sample.
    """
    shape = node_input_shape(graph, node_id, trigger_task)
    node = _nodes_by_id(graph).get(node_id) or {"id": node_id}
    if shape.source is None:
        _fail(REFUSE_PIN_UNUSED, (node_id,),
              f"{_called(node)} is the first step and the workflow does not start "
              f"on an event or a webhook")
    if not isinstance(data, dict):
        _fail(REFUSE_BAD_PIN, (node_id,), f"it needs fields named {', '.join(shape.fields)}")
    dropped = tuple(sorted(k for k in data if k not in shape.fields))
    envelope = build_trigger(shape.source, shape.name or node_id, data, fields=shape.fields)
    return envelope, dropped


# ── What a step does, for *Test this step* (`P22-08`) ───────────────────────

def node_effects(node: dict, tasks_by_id: dict | None = None) -> tuple:
    """What running this step would do, in `ACTION_EFFECTS` words — the step
    itself, not where its result is sent (a test never delivers). A Run task
    step's are its task's."""
    from src.builtin_actions import (
        BUILTIN_ACTION_META, EFFECT_CALLS_MODEL, EFFECT_WRITES,
    )

    kind = node.get("kind")
    config = node.get("config") or {}
    if kind == NODE_KIND_ACTION:
        return tuple((BUILTIN_ACTION_META.get(config.get("action") or "") or {})
                     .get("effects") or ())
    if kind == NODE_KIND_RESEARCH:
        return (EFFECT_CALLS_MODEL, EFFECT_WRITES)
    if kind == NODE_KIND_PROMPT:
        return (EFFECT_CALLS_MODEL,)
    if kind == NODE_KIND_RUN_TASK:
        target = (tasks_by_id or {}).get(config.get("task_id"))
        if target is None:
            return ()
        as_node = {"kind": getattr(target, "task_type", None) or NODE_KIND_PROMPT,
                   "config": {"action": getattr(target, "action", None)}}
        if as_node["kind"] not in STAND_IN_KINDS:
            return ()
        return node_effects(as_node)
    return ()


def needs_test_confirmation(node: dict, tasks_by_id: dict | None = None) -> bool:
    """Does testing this step show its plan and ask before it runs for real?

    An action whose effects meet `TEST_CONFIRM_EFFECTS`; a Run task step
    always, because it really runs another task, with its own delivery and
    chain. A Prompt or Research step does not: its effects are a model call
    and a report, and a Prompt step's tools are gated per call as in chat.
    Mistake prevention, not a control (`Law 17`).
    """
    from src.builtin_actions import TEST_CONFIRM_EFFECTS

    kind = node.get("kind")
    if kind == NODE_KIND_RUN_TASK:
        return True
    if kind == NODE_KIND_ACTION:
        return bool(set(node_effects(node, tasks_by_id)) & set(TEST_CONFIRM_EFFECTS))
    return False


# ── The stand-in ─────────────────────────────────────────────────────────────

class WorkflowNodeTask:
    """What one step runs as: the fields of a `ScheduledTask` the executors
    read, and no others. `__slots__`, so a read of anything else raises
    `AttributeError` — an executor that starts reading a new column fails a
    test instead of silently reading `None` off a namespace. Not a row: it is
    never added to a session, so nothing an executor sets on it is saved
    except what the walker copies back (`session_id`)."""

    __slots__ = STAND_IN_FIELDS

    def __init__(self, **values):
        unknown = set(values) - set(STAND_IN_FIELDS)
        if unknown:
            raise TypeError(f"not a stand-in field: {sorted(unknown)}")
        for field in STAND_IN_FIELDS:
            setattr(self, field, values.get(field))

    def __repr__(self):  # pragma: no cover - diagnostics
        return f"WorkflowNodeTask({self.name!r}, {self.task_type!r})"


def node_stand_in(trigger, workflow_name: str, node: dict) -> WorkflowNodeTask:
    """The task a Prompt, Research or Action step runs as.

    `id` and `owner` are the trigger's, so a delivery, a library link and
    `X-Pantheon-Ref` name the workflow; `name` is "workflow · step". A Prompt
    or Action step shares the trigger's chat (`session_id`); a Research step
    starts with none, because a report is keyed by its session and two
    Research steps sharing one would overwrite each other.
    """
    kind = node.get("kind")
    if kind not in STAND_IN_KINDS:
        raise ValueError(f"a {kind!r} step does not run as a stand-in")
    config = node.get("config") or {}
    allowed = NODE_CONFIG_FIELDS[kind]

    def cfg(key):
        if key not in allowed:
            return None
        value = config.get(key)
        return value if value not in ("",) else None

    return WorkflowNodeTask(
        id=trigger.id,
        owner=trigger.owner,
        name=f"{workflow_name} · {node.get('label') or node.get('id')}",
        task_type=kind,
        action=cfg("action"),
        prompt=cfg("prompt"),
        model=cfg("model"),
        endpoint_url=cfg("endpoint_url"),
        crew_member_id=cfg("crew_member_id"),
        character_id=cfg("character_id"),
        max_steps=cfg("max_steps"),
        output_target=cfg("output_target"),
        tz_name=getattr(trigger, "tz_name", None),
        session_id=None if kind == NODE_KIND_RESEARCH else getattr(trigger, "session_id", None),
    )


# ── A chain made into a document (`P22-06`) ─────────────────────────────────

# The trigger task's fields a converted workflow copies from the chain's head:
# how and when it starts, its time zone, retries, time limit and notifications.
# What it RUNS goes into the first step instead.
TRIGGER_FIELDS = (
    "trigger_type", "schedule", "scheduled_time", "scheduled_day",
    "scheduled_date", "cron_expression", "trigger_event", "trigger_count",
    "tz_name", "max_retries", "timeout_seconds", "notifications_enabled",
)


def _node_from_row(row, node_id: str) -> dict:
    kind = getattr(row, "task_type", None) or NODE_KIND_PROMPT
    config = {}
    for key in NODE_CONFIG_FIELDS.get(kind, ()):
        value = getattr(row, key, None)
        if value not in (None, ""):
            config[key] = value
    label = (getattr(row, "name", None) or node_id).strip() or node_id
    return {"id": node_id, "kind": kind, "label": label[:NODE_LABEL_MAX],
            "config": config, "position": None, "pinned": None}


def chain_to_document(rows, head_id: str, *, positions=None) -> tuple:
    """`(graph, trigger_fields, notes)` — the chain from `head_id`, as a document.

    `rows` is the owner's tasks (every one an arrow could reach, and any that
    lead into the chain from outside it); the chain is what `head_id`'s arrows
    reach, each task once, breadth first, as `P22-01`'s engine runs it. Each
    task becomes a step with its own settings (`NODE_CONFIG_FIELDS`, the same
    column names) and each arrow an arrow on the same port; `trigger_fields`
    is the head's `TRIGGER_FIELDS`. Nothing is written and nothing is changed:
    the chain keeps running exactly as before until a person switches the
    workflow on (`D-2026-10-01-05` §1).

    Refused (`DocumentError`) where the engine would refuse the chain or the
    document could not hold it: a loop, another owner's task, a member that is
    itself a workflow, more than `WORKFLOW_MAX_NODES` steps. `positions` maps
    task id to `[x, y]` (the canvas's), carried onto the steps.
    """
    by_task = {row.id: row for row in rows}
    head = by_task.get(head_id)
    if head is None:
        _fail(REFUSE_UNKNOWN_TASK, detail="the chain's first task")
    owner = getattr(head, "owner", None)
    refusal = validate_graph(list(rows), starts=[head_id], owner=owner,
                             max_depth=WORKFLOW_MAX_NODES + 1)
    if refusal is not None:
        names = {r.id: getattr(r, "name", None) for r in rows
                 if getattr(r, "owner", None) == owner}
        if refusal.reason == CHAIN_CYCLE:
            raise DocumentError(DocumentRefusal(
                REFUSE_CYCLE, (), describe_graph_refusal(refusal, names, first=head_id)))
        if refusal.reason == CHAIN_CROSS_OWNER:
            raise DocumentError(DocumentRefusal(
                REFUSE_CROSS_OWNER, (), describe_graph_refusal(refusal, names)))
        _fail(REFUSE_TOO_MANY_STEPS, detail=f"a workflow holds at most {WORKFLOW_MAX_NODES}")
    order = [head]
    seen = {head_id}
    frontier = [head]
    while frontier:
        following = []
        for row in frontier:
            for edge in task_edges(row):
                target = by_task.get(edge["to"])
                if target is None or target.id in seen:
                    continue
                seen.add(target.id)
                order.append(target)
                following.append(target)
        frontier = following
    if len(order) > WORKFLOW_MAX_NODES:
        _fail(REFUSE_TOO_MANY_STEPS, detail=f"it has {len(order)}")
    for row in order:
        if (getattr(row, "task_type", None) or "llm") == WORKFLOW_TASK_TYPE:
            _fail(REFUSE_WORKFLOW_MEMBER, detail=f"“{row.name}” is a workflow, and a "
                                                 f"workflow cannot be a step")
    node_of = {row.id: f"n{i}" for i, row in enumerate(order, start=1)}
    positions = positions or {}
    nodes = []
    for row in order:
        node = _node_from_row(row, node_of[row.id])
        pos = positions.get(row.id)
        if pos is not None:
            node["position"] = _position(pos, _called(node))
        nodes.append(node)
    edges = []
    for row in order:
        for edge in task_edges(row):
            if edge["to"] in node_of:
                edges.append({"from": node_of[row.id], "port": edge["when"],
                              "to": node_of[edge["to"]]})
    notes = [f"Made from {len(order)} step{'s' if len(order) != 1 else ''}, "
             f"starting with “{head.name}”."]
    outside = sorted({r.name for r in rows if r.id not in seen
                      and getattr(r, "owner", None) == owner
                      and any(e["to"] in seen for e in task_edges(r))})
    for name in outside:
        notes.append(f"“{name}” also leads into this chain. It is not part of the "
                     f"workflow and keeps running as it does now.")
    if (getattr(head, "trigger_type", None) or "schedule") == "webhook":
        notes.append("The workflow has its own webhook address. The chain's old "
                     "address only answers while the chain is on.")
    trigger_fields = {key: getattr(head, key, None) for key in TRIGGER_FIELDS}
    graph = {"v": GRAPH_VERSION, "start": {"position": None}, "nodes": nodes, "edges": edges}
    return graph, trigger_fields, notes
