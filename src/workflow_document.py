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
    with the SAME sentence at save and at run;
  * the walk: `ports_of`, `start_nodes`, `entry_node`, `next_node(s)`,
    `reachable_bfs`, `upstream_of`, `concurrent_arrivals`;
  * the stand-in a step runs as (`WorkflowNodeTask`, `node_stand_in`);
  * versions' fingerprint, positions, pins, and a chain made into a document;
  * what a step does: `node_effects`, `needs_test_confirmation`,
    `node_needs_model`, `plan_lines`.

**One vocabulary (`Law 14`).** The task kinds are the `task_type` values the
executors already take (`llm` / `research` / `action`) plus `run_task`; their
ports are `EDGE_CONDITIONS`, imported; their config keys are `ScheduledTask`
column names. `P22-10` … `P22-18` add ten kinds (Slices C and D) and the ports
the logic steps leave by (`workflow_logic`); none is renamed.

**Slices C and D (`SLICE-CD-DESIGN` § 1.3).** A step may lead to several steps
on one port (fan-out), the start may lead to several steps (start arrows
`{from: "start", port: "success", to}`), and two branches that can run at the
same time must meet at a Merge (`concurrent_arrivals`). Loops are found over
EVERY arrow (`find_loop`), which replaces `document_rows`' one-arrow-per-port
reading — that reading could not see a loop through a second arrow. References
(`workflow_refs`) are checked at save and again at run: each parses, names the
start or a step upstream, reads `item` only inside a For-each, and sits in a
`value` slot (`workflow_slots`). What a step may name — an Integration, an MCP
tool, a skill, an AI tool, the workstation — is checked against
`WorkflowResources`, built by the caller from what the person can reach.

`FORBIDDEN.md` Part 1: `GRAPH_VERSION`'s value, the `NODE_KINDS`, the port
words, the start key, the `WORKFLOW_VERSION_SOURCES` (three until `P22-19`,
six since) and `WORKFLOW_TASK_TYPE` are stored in rows; a rename orphans every
stored workflow. So are the `unchecked` key and its two origins (`P22-19`).
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
    EDGE_CONDITIONS,
    EDGE_WHEN_ERROR,
    EDGE_WHEN_SUCCESS,
    GraphRefusal,
    describe_graph_refusal,
    task_edges,
    validate_graph,
)
from src.workflow_logic import (
    CASE_PORT_PREFIX,
    JOIN_WORDS,
    JOINS,
    OPERATORS,
    PORT_OTHERWISE,
    PORT_THEN,
    case_port,
    describe_condition,
)
from src.workflow_refs import (
    NODE_ID_MAX,
    NODE_ID_RE,
    REF_ROOT_ITEM,
    REF_ROOT_STEPS,
    START_NODE,
    RefError,
    parse_template,
    references_in_text,
    single_ref,
)
from src.workflow_slots import (
    MAPPING_NEVER,
    config_leaves,
    path_text,
    slot_for,
)

# ── Stored values (`FORBIDDEN.md` Part 1) ────────────────────────────────────
GRAPH_VERSION = 1
# `ScheduledTask.task_type` of a workflow's trigger. A stored value ADDED, none
# renamed: `llm`, `research` and `action` keep their meaning.
WORKFLOW_TASK_TYPE = "workflow"
NODE_KIND_PROMPT = "llm"
NODE_KIND_RESEARCH = "research"
NODE_KIND_ACTION = "action"
NODE_KIND_RUN_TASK = "run_task"
# `P22-10` … `P22-18`. Added, none renamed.
NODE_KIND_IF = "if"
NODE_KIND_SWITCH = "switch"
NODE_KIND_SET = "set"
NODE_KIND_MERGE = "merge"
NODE_KIND_WAIT = "wait"
NODE_KIND_FOREACH = "foreach"
NODE_KIND_HTTP = "http"
NODE_KIND_MCP = "mcp"
NODE_KIND_SKILL = "skill"
NODE_KIND_CODE = "code"
TASK_KINDS = (NODE_KIND_PROMPT, NODE_KIND_RESEARCH, NODE_KIND_ACTION, NODE_KIND_RUN_TASK)
LOGIC_KINDS = (NODE_KIND_IF, NODE_KIND_SWITCH, NODE_KIND_SET)
FLOW_KINDS = (NODE_KIND_MERGE, NODE_KIND_WAIT, NODE_KIND_FOREACH)
EFFECT_KINDS = (NODE_KIND_HTTP, NODE_KIND_MCP, NODE_KIND_SKILL, NODE_KIND_CODE)
NODE_KINDS = TASK_KINDS + LOGIC_KINDS + FLOW_KINDS + EFFECT_KINDS
# The kinds that run through a stand-in and one of the three executors.
# `run_task` runs a real task instead (`TaskScheduler._run_workflow_node`).
STAND_IN_KINDS = (NODE_KIND_PROMPT, NODE_KIND_RESEARCH, NODE_KIND_ACTION)
# `SLICE-CD-DESIGN` § 0.6: the agent's own `api_call` and `mcp__` tools are an
# admin's (and a single-user install's), so their steps are too — the palette
# offers a person only what their agent can already reach (D's minor call).
ADMIN_ONLY_KINDS = (NODE_KIND_HTTP, NODE_KIND_MCP)
# What a For-each may repeat: one step of any kind but these (§ 1.4).
FOREACH_REFUSED_KINDS = (NODE_KIND_IF, NODE_KIND_SWITCH, NODE_KIND_MERGE,
                         NODE_KIND_WAIT, NODE_KIND_FOREACH)
# The kinds a model drives — `node_needs_model`'s answer, with a model-backed
# action, a Run task step and a For-each of one of these.
MODEL_KINDS = (NODE_KIND_PROMPT, NODE_KIND_RESEARCH, NODE_KIND_SKILL)

# Which outcome edge a task step leaves by. `EDGE_CONDITIONS`, imported, never
# typed again: "if it works" / "if it fails" are already drawn from these words.
PORTS = EDGE_CONDITIONS
PORT_SUCCESS = EDGE_WHEN_SUCCESS
PORT_ERROR = EDGE_WHEN_ERROR
# Every port word a document stores; a Switch's are `case:<id>` besides
# (`CASE_PORT_PREFIX`, `workflow_logic.case_port`).
PORT_WORDS = (PORT_SUCCESS, PORT_ERROR, PORT_THEN, PORT_OTHERWISE)
# The start item's key in `graph["start"]`, in a positions map, and as an
# arrow's `from`. Reserved: no step may be called this. `workflow_refs`'
# `START_NODE`, so `{{ steps.start… }}` and the start arrow are one word.
START_KEY = START_NODE
START_PORTS = (PORT_SUCCESS,)
# Where a kept version came from (`workflow_versions.source`). Named one by
# one so the store writes each by its name rather than restating the word
# (`src/workflow_store.py`, `Law 7`; added at the wave C merge).
VERSION_SOURCE_USER = "user"
VERSION_SOURCE_CONVERTED = "converted"
VERSION_SOURCE_RESTORED = "restored"
# `P22-19`, `P22-24`, `P22-20` (`SLICE-EF-DESIGN` § 1.2). A document the model
# drafted, one that arrived in a file, and a fix a person applied. Added, none
# renamed (`FORBIDDEN.md` Part 1 at the merge).
VERSION_SOURCE_DRAFTED = "drafted"
VERSION_SOURCE_IMPORTED = "imported"
VERSION_SOURCE_FIXED = "fixed"
WORKFLOW_VERSION_SOURCES = (VERSION_SOURCE_USER, VERSION_SOURCE_CONVERTED, VERSION_SOURCE_RESTORED,
                            VERSION_SOURCE_DRAFTED, VERSION_SOURCE_IMPORTED, VERSION_SOURCE_FIXED)

# `P22-19` / `P22-24` (`SLICE-EF-DESIGN` § 1.1). "A person has looked at this":
# a step the model drafted, or one that came in a file, carries
#   unchecked: {origin: "drafted" | "imported", at: ISO, needs: [{field, name, preset?, server?, tool?}]}
# until a person says it looks right (or changes it). D §4 lets an authored
# deterministic step run without a card because the AUTHOR decided it; a
# drafted step was decided by a model that read third-party text, an imported
# one by whoever wrote the file, so the mark keeps that premise true until a
# person has looked. The key, and the two origins, are stored values.
UNCHECKED_KEY = "unchecked"
ORIGIN_DRAFTED = "drafted"
ORIGIN_IMPORTED = "imported"
UNCHECKED_ORIGINS = (ORIGIN_DRAFTED, ORIGIN_IMPORTED)
# What one `needs` entry may say: the setting, and what it names.
NEED_KEYS = ("field", "name", "preset", "server", "tool")
NEEDS_MAX = 20
NEED_TEXT_MAX = 300

# The words the new kinds' settings store.
MERGE_ALL = "all"
MERGE_FIRST = "first"
MERGE_MODES = (MERGE_ALL, MERGE_FIRST)
WAIT_FOR = "for"
WAIT_UNTIL = "until"
WAIT_MODES = (WAIT_FOR, WAIT_UNTIL)
ON_ERROR_STOP = "stop"
ON_ERROR_CONTINUE = "continue"
FOREACH_ON_ERROR = (ON_ERROR_STOP, ON_ERROR_CONTINUE)
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
BODY_MODE_JSON = "json"
CODE_LANGUAGES = ("python", "bash")
ANSWER_TYPES = ("text", "number", "yes/no", "list")

# What each kind of step may be configured with. For the task kinds these are
# `ScheduledTask` field names, read by the executors under those names
# (`node_stand_in`). `output_target` null means "only hand it to the next
# step", the default for a new step. Every one is declared `value` or `never`
# in `workflow_slots.NODE_SLOTS`, which a test holds field by field.
NODE_CONFIG_FIELDS = {
    NODE_KIND_PROMPT: ("prompt", "model", "endpoint_url", "character_id",
                       "crew_member_id", "max_steps", "output_target",
                       "tools", "answer_fields"),
    NODE_KIND_RESEARCH: ("prompt", "model", "endpoint_url", "output_target"),
    NODE_KIND_ACTION: ("action", "prompt", "output_target"),
    NODE_KIND_RUN_TASK: ("task_id",),
    NODE_KIND_IF: ("conditions", "join"),
    NODE_KIND_SWITCH: ("cases",),
    NODE_KIND_SET: ("fields",),
    NODE_KIND_MERGE: ("mode",),
    NODE_KIND_WAIT: ("mode", "minutes", "time", "tz"),
    NODE_KIND_FOREACH: ("list", "step", "on_error"),
    NODE_KIND_HTTP: ("integration", "method", "path", "headers", "query", "body", "body_mode"),
    NODE_KIND_MCP: ("tool", "args"),
    NODE_KIND_SKILL: ("skill", "prompt", "model", "endpoint_url", "max_steps", "output_target"),
    NODE_KIND_CODE: ("language", "source", "timeout_seconds", "input"),
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
# Twenty steps also bounds every walk here. `concurrent_arrivals` and
# `find_loop` do NOT enumerate paths (with fan-out the worst DAG on 20 steps has
# 2^18 of them): the loop check is one depth-first pass, and the merge rule a
# reachability over pairs of steps, at most 21² states.
WORKFLOW_MAX_NODES = 20
WORKFLOW_GRAPH_MAX_BYTES = 256 * 1024
NODE_LABEL_MAX = 120
CASE_LABEL_MAX = 60
CONDITIONS_MAX = 20
CASES_MAX = 20
SET_FIELDS_MAX = 50
ENTRIES_MAX = 50
MCP_ARGS_MAX = 100
AI_TOOLS_MAX = 64
ANSWER_FIELDS_MAX = 20
ANSWER_DESCRIPTION_MAX = 500
CODE_SOURCE_MAX = 20_000
CODE_TIMEOUT_RANGE = (1, 600)
_CASE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_HEADER_NAME_RE = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}")
_TIME_RE = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
# The For-each cap and the longest Wait: their built-in defaults and ranges
# are the walker's (`workflow_runs`, which resolves the two settings role →
# instance → default, `SLICE-CD-DESIGN` § 1.4) and arrive here resolved in
# `WorkflowResources`. Imported, not restated (`Law 7`, `integrate-d`: the
# merge held three copies — this module, `workflow_runs` and `settings.py`).
from src.workflow_runs import (  # noqa: E402
    FOREACH_MAX_ITEMS_DEFAULT as WORKFLOW_FOREACH_MAX_ITEMS_DEFAULT,
    FOREACH_MAX_ITEMS_RANGE as WORKFLOW_FOREACH_MAX_ITEMS_RANGE,
    WAIT_MAX_HOURS_DEFAULT as WORKFLOW_WAIT_MAX_HOURS_DEFAULT,
    WAIT_MAX_HOURS_RANGE as WORKFLOW_WAIT_MAX_HOURS_RANGE,
)

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
# `P22-09` … `P22-18`.
REFUSE_NEEDS_MERGE = "needs_merge"
REFUSE_MAPPED_NEVER = "mapped_never"
REFUSE_BAD_REFERENCE = "bad_reference"
REFUSE_NOT_UPSTREAM = "not_upstream"
REFUSE_UNKNOWN_INTEGRATION = "unknown_integration"
REFUSE_UNKNOWN_TOOL = "unknown_tool"
REFUSE_UNKNOWN_SKILL = "unknown_skill"
REFUSE_WORKSTATION = "workstation"
REFUSE_FOREACH_INNER = "foreach_inner"
# `P22-19`. Asked by the switch and by the walker, never by a save: a draft
# with marks is a document that may be edited, tested and dry-run, and not yet
# switched on (`SLICE-EF-DESIGN` § 1.1).
REFUSE_UNCHECKED = "unchecked"

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
    REFUSE_TWO_ARROWS: "a step has the same arrow twice",
    REFUSE_CYCLE: "the workflow loops back on itself",
    REFUSE_SEVERAL_STARTS: "more than one step has nothing leading to it",
    REFUSE_PIN_UNUSED: "the step is handed nothing, so a sample would never be used",
    REFUSE_BAD_PIN: "the sample is not a set of named fields",
    REFUSE_WORKFLOW_MEMBER: "the chain runs a workflow",
    REFUSE_CROSS_OWNER: "the chain reaches another owner's task",
    REFUSE_NEEDS_MERGE: "two branches that run at the same time reach one step",
    REFUSE_MAPPED_NEVER: "a setting only you can fill reads from another step",
    REFUSE_BAD_REFERENCE: "a step's text has a reference that cannot be read",
    REFUSE_NOT_UPSTREAM: "a step reads from a step that does not run before it",
    REFUSE_UNKNOWN_INTEGRATION: "a step uses an Integration that is not set up, or is switched off",
    REFUSE_UNKNOWN_TOOL: "a step uses a tool you cannot use here, or that is switched off",
    REFUSE_UNKNOWN_SKILL: "a step follows a skill that is not one of yours",
    REFUSE_WORKSTATION: "a Code step runs in your workstation, and it cannot run there now",
    REFUSE_FOREACH_INNER: "a For-each step repeats a kind of step it cannot repeat",
    REFUSE_UNCHECKED: "a step nobody has checked yet cannot run",
}


class DocumentRefusal(NamedTuple):
    """Why a document may not run. `reason` is a `WORKFLOW_REFUSAL_REASONS` key
    — an enum, never a sentence; `node_ids` the steps it is about (empty when
    it is about the whole); `sentence` what a person is told, at save and at
    run alike; `field` the setting it is about (`workflow_slots.path_text`,
    e.g. `prompt`, `conditions[0].op`), so the panel puts the sentence on that
    field — empty when it is about the step or the whole."""
    reason: str
    node_ids: tuple
    sentence: str
    field: str = ""


class DocumentError(ValueError):
    """`parse_graph` (and the other shaping functions) could not use what they
    were given. Carries the `DocumentRefusal`."""

    def __init__(self, refusal: DocumentRefusal):
        super().__init__(refusal.sentence)
        self.refusal = refusal


def _refusal(reason: str, node_ids=(), detail: str | None = None,
             field: str = "") -> DocumentRefusal:
    lead = WORKFLOW_REFUSAL_REASONS[reason]
    lead = lead[:1].upper() + lead[1:]
    sentence = f"{lead}: {detail}" if detail else f"{lead}."
    if detail and not sentence.endswith((".", "?", "!")):
        sentence += "."
    return DocumentRefusal(reason, tuple(node_ids), sentence, field)


def _fail(reason: str, node_ids=(), detail: str | None = None):
    raise DocumentError(_refusal(reason, node_ids, detail))


def _called(node_or_label) -> str:
    if isinstance(node_or_label, dict):
        label = node_or_label.get("label") or node_or_label.get("id") or "?"
    else:
        label = node_or_label or "?"
    return f"“{label}”"


# ── What a step may reach (`SLICE-CD-DESIGN` § 1.3) ─────────────────────────

WORKSTATION_UNCHECKED = "Pantheon could not check your workstation"


class WorkflowResources(NamedTuple):
    """What the person can reach, built by the caller (`workflow_effects.
    workflow_resources(owner)`) and asked by `validate_document`:

      * `integrations` — `{id: {name, enabled, …}}`, the Integrations set up;
      * `mcp_tools` — `{qualified name: {input_schema, disabled, is_readonly,
        …}}`, the MCP tools this person's agent can call;
      * `skills` — the skill names this person can follow;
      * `ai_tools` — the tool names an AI step may list (`ai_tool_choices`);
      * `workstation_why` — `None` when a Code step can run, else the sentence
        why not (off, not set up, not permitted);
      * `foreach_max_items`, `wait_max_hours` — the two settings, resolved.

    The defaults are an empty set of everything and a workstation that could
    not be checked, so a caller that passes nothing gets every effect step
    refused rather than waved through (fail closed)."""
    integrations: dict | None = None
    mcp_tools: dict | None = None
    skills: frozenset = frozenset()
    ai_tools: frozenset = frozenset()
    workstation_why: str | None = WORKSTATION_UNCHECKED
    foreach_max_items: int = WORKFLOW_FOREACH_MAX_ITEMS_DEFAULT
    wait_max_hours: int = WORKFLOW_WAIT_MAX_HOURS_DEFAULT


EMPTY_RESOURCES = WorkflowResources()


def _mcp_info(resources: WorkflowResources, tool) -> dict | None:
    info = (resources.mcp_tools or {}).get(tool) if isinstance(tool, str) else None
    return info if isinstance(info, dict) else None


def _mcp_schema(node: dict, resources: WorkflowResources):
    """The input schema of the MCP tool `node` calls — or, for a For-each, the
    tool its inner step calls."""
    config = node.get("config") or {}
    if node.get("kind") == NODE_KIND_FOREACH:
        inner = config.get("step")
        if not isinstance(inner, dict):
            return None
        node, config = inner, inner.get("config") or {}
    if node.get("kind") != NODE_KIND_MCP or not isinstance(config, dict):
        return None
    info = _mcp_info(resources, config.get("tool"))
    return info.get("input_schema") if info else None


# ── Reading ──────────────────────────────────────────────────────────────────

def _position(value, where: str):
    if value is None:
        return None
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in value)):
        return [value[0], value[1]]
    _fail(REFUSE_UNREADABLE, detail=f"{where} has a position that is not two numbers")


def _mark(value, label, node_id):
    """`P22-19`. A step's `unchecked` mark, shaped — or `None` for no mark.

    Only its shape is checked here; who may set, keep or clear one is the
    store's (`workflow_store.create_from_document`, `_marks_kept`,
    `check_steps`). Anything that is not a mark this Pantheon writes is
    refused, so a mark can never carry something else into a stored row."""
    if value is None:
        return None
    where = _called(label)
    if (not isinstance(value, dict) or value.get("origin") not in UNCHECKED_ORIGINS
            or set(value) - {"origin", "at", "needs"}):
        _fail(REFUSE_UNREADABLE, (node_id,), f"{where} has a mark this Pantheon does not write")
    at = value.get("at")
    if at is not None and (not isinstance(at, str) or len(at) > 64):
        _fail(REFUSE_UNREADABLE, (node_id,), f"{where} has a mark with no time")
    needs_in = value.get("needs")
    needs_in = [] if needs_in is None else needs_in
    if not isinstance(needs_in, list) or len(needs_in) > NEEDS_MAX:
        _fail(REFUSE_UNREADABLE, (node_id,), f"{where} has a mark whose needs are not a list")
    needs = []
    for need in needs_in:
        if (not isinstance(need, dict) or set(need) - set(NEED_KEYS)
                or not all(isinstance(v, str) and len(v) <= NEED_TEXT_MAX for v in need.values())):
            _fail(REFUSE_UNREADABLE, (node_id,), f"{where} has a mark whose needs cannot be read")
        needs.append(dict(need))
    return {"origin": value["origin"], "at": at, "needs": needs}


def parse_graph(raw) -> dict:
    """The stored document, read and shaped. Raises `DocumentError`.

    Takes the JSON text (`workflows.graph`) or an already-decoded dict (a
    request body). Checks the SHAPE — sizes, types, the version — and answers
    a fresh dict with exactly the schema's keys:
    `{v, start: {position}, nodes: [{id, kind, label, config, position, pinned}],
    edges: [{from, port, to}]}`. What the steps SAY is `validate_document`'s.

    `P22-19`: a step that carries an `unchecked` mark keeps it, shaped
    (`_mark`); a step with none has no `unchecked` key at all (read it as
    null), so an ordinary save does not change a stored document's bytes.
    Every other key is still dropped.
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
        shaped = {
            "id": node_id,
            "kind": kind,
            "label": label,
            "config": dict(config),
            "position": _position(node.get("position"), _called(label)),
            "pinned": pinned,
        }
        mark = _mark(node.get(UNCHECKED_KEY), label, node_id)
        if mark is not None:
            shaped[UNCHECKED_KEY] = mark
        nodes.append(shaped)
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


# ── Ports ────────────────────────────────────────────────────────────────────

def ports_of(node) -> tuple:
    """The ports a step leaves by, in the order they are drawn and walked.

    | task kinds, `http`, `mcp`, `skill`, `code`, `foreach` | `success`, `error` |
    | `if`                                                  | `then`, `otherwise` |
    | `switch`                                              | `case:<id>` per case, then `otherwise` |
    | `set`, `merge`, `wait`                                | `success` |

    The start (`START_KEY`) leaves by `success`. An unknown kind has none."""
    if node == START_KEY:
        return START_PORTS
    if not isinstance(node, dict):
        return ()
    kind = node.get("kind")
    if kind in TASK_KINDS or kind in EFFECT_KINDS or kind == NODE_KIND_FOREACH:
        return PORTS
    if kind == NODE_KIND_IF:
        return (PORT_THEN, PORT_OTHERWISE)
    if kind == NODE_KIND_SWITCH:
        cases = (node.get("config") or {}).get("cases")
        ports = []
        for case in cases if isinstance(cases, list) else ():
            if isinstance(case, dict) and isinstance(case.get("id"), str) \
                    and _CASE_ID_RE.fullmatch(case["id"]):
                port = case_port(case["id"])
                if port not in ports:
                    ports.append(port)
        return (*ports, PORT_OTHERWISE)
    if kind in (NODE_KIND_SET, NODE_KIND_MERGE, NODE_KIND_WAIT):
        return (PORT_SUCCESS,)
    return ()


_PORT_PHRASES = {
    PORT_SUCCESS: "if it works",
    PORT_ERROR: "if it fails",
    PORT_THEN: "then",
    PORT_OTHERWISE: "otherwise",
}


def port_words(node, port: str) -> str:
    """The words a person reads for `port` out of `node`: "if it works", "if
    it fails", "then", "otherwise", or a Switch case's own label."""
    if isinstance(port, str) and port.startswith(CASE_PORT_PREFIX) and isinstance(node, dict):
        case_id = port[len(CASE_PORT_PREFIX):]
        for case in (node.get("config") or {}).get("cases") or ():
            if isinstance(case, dict) and case.get("id") == case_id:
                return str(case.get("label") or case_id)
        return case_id
    return _PORT_PHRASES.get(port, str(port))


def _when_words(node, port: str) -> str:
    """An arrow's `when` for `describe_graph_refusal`, which reads the two
    task words itself ("works" / "fails") and any other `when` as written —
    so a loop through a logic step's port is told "goes the “Urgent” way" at
    save and at run without editing that function (§ 1.3)."""
    if port in PORTS:
        return port
    return f"goes the “{port_words(node, port)}” way"


# ── The walk ─────────────────────────────────────────────────────────────────

def _nodes_by_id(g: dict) -> dict:
    return {node["id"]: node for node in g.get("nodes") or ()}


def _out_edges(g: dict, node_id: str) -> list:
    """Edges leaving `node_id` (or the start), in its `ports_of` order ("if it
    works" first), then in the order they are listed."""
    found = [e for e in g.get("edges") or () if e["from"] == node_id]
    node = START_KEY if node_id == START_KEY else _nodes_by_id(g).get(node_id)
    order = {port: i for i, port in enumerate(ports_of(node))}
    return sorted(found, key=lambda e: order.get(e["port"], len(order)))


def start_edges(g: dict) -> list:
    """The arrows out of the start, as listed. Empty for a document that keeps
    Slice B's single implied entry (`Law 1`)."""
    return [e for e in g.get("edges") or () if e["from"] == START_KEY]


def _entries(g: dict) -> list:
    """Steps no step leads to (an arrow from the start is not a step's)."""
    led_to = {e["to"] for e in g.get("edges") or () if e["from"] != START_KEY}
    return [n for n in g.get("nodes") or () if n["id"] not in led_to]


def start_nodes(g: dict) -> list:
    """The steps a run begins with: those the start's arrows lead to, in
    order; or, with no start arrows, the one step nothing leads to (the first
    of several, in a document `validate_document` refuses)."""
    by_id = _nodes_by_id(g)
    explicit = start_edges(g)
    if explicit:
        seen = []
        for edge in explicit:
            node = by_id.get(edge["to"])
            if node is not None and node not in seen:
                seen.append(node)
        return seen
    entries = _entries(g)
    return entries[:1]


def entry_node(g: dict):
    """The step the workflow starts at: the first of `start_nodes`. `None` for
    a document with no steps."""
    starts = start_nodes(g)
    return starts[0] if starts else None


def next_node(g: dict, node_id: str, port: str):
    """The first step the `port` arrows out of `node_id` lead to, or `None`."""
    found = next_nodes(g, node_id, port)
    return found[0] if found else None


def next_nodes(g: dict, node_id: str, port: str) -> list:
    """Every step the `port` arrows out of `node_id` lead to, in order — more
    than one where the step fans out (`P22-11`)."""
    by_id = _nodes_by_id(g)
    out = []
    for edge in g.get("edges") or ():
        if edge["from"] == node_id and edge["port"] == port:
            target = by_id.get(edge["to"])
            if target is not None and target not in out:
                out.append(target)
    return out


def reachable_bfs(g: dict) -> list:
    """Every step reachable from the start, each once, breadth first.

    `[{node, when, depth, parent}]` — the steps the start leads to first
    (`when` None, depth 0); `when` is the port of the arrow from its first
    parent in this order, which is wave B's chain dry run's rule
    (`plan_dry_chain`) on a document.
    """
    starts = start_nodes(g)
    if not starts:
        return []
    by_id = _nodes_by_id(g)
    out = [{"node": n, "when": None, "depth": 0, "parent": None} for n in starts]
    seen = {n["id"] for n in starts}
    frontier = list(starts)
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


def upstream_of(g: dict, node_id: str) -> frozenset:
    """The ids of every step with a path of arrows to `node_id` — the steps a
    reference in `node_id` may name (besides `start`). Not `node_id` itself,
    unless a loop leads back to it (which `validate_document` refuses)."""
    feeds = {}
    for edge in g.get("edges") or ():
        if edge["from"] != START_KEY:
            feeds.setdefault(edge["to"], set()).add(edge["from"])
    found = set()
    frontier = [node_id]
    while frontier:
        following = []
        for current in frontier:
            for pred in feeds.get(current, ()):
                if pred not in found:
                    found.add(pred)
                    following.append(pred)
        frontier = following
    return frozenset(found)


def find_loop(g: dict) -> GraphRefusal | None:
    """The first loop along ANY arrow, as `validate_graph` reports one: a
    `GraphRefusal(CHAIN_CYCLE, start, path)` whose `path` is exactly the loop,
    edges shaped `{from, to, when}` with `when` worded (`_when_words`).

    One depth-first pass from each step in document order, out-arrows in
    `ports_of` order — the order `validate_graph`'s path walk takes them, and
    a step it has finished cannot lead back to the path (any loop through it
    would have been found from it), so the first loop found is the one the
    old walk found on a document with one arrow per port."""
    by_id = _nodes_by_id(g)
    white, grey, black = 0, 1, 2
    colour = {node_id: white for node_id in by_id}
    on_path = []
    taken = []

    def visit(root: str, node_id: str):
        colour[node_id] = grey
        on_path.append(node_id)
        for edge in _out_edges(g, node_id):
            to = edge["to"]
            if to not in by_id:
                continue
            hop = {"from": node_id, "to": to, "when": _when_words(by_id[node_id], edge["port"])}
            if colour[to] == grey:
                return GraphRefusal(CHAIN_CYCLE, root, tuple(taken[on_path.index(to):] + [hop]))
            if colour[to] == white:
                taken.append(hop)
                found = visit(root, to)
                if found is not None:
                    return found
                taken.pop()
        colour[node_id] = black
        on_path.pop()
        return None

    for root in by_id:
        if colour[root] == white:
            found = visit(root, root)
            if found is not None:
                return found
    return None


class Arrival(NamedTuple):
    """Two arrows into `node_id` that can both fire in one run."""
    node_id: str
    first: dict
    second: dict


def _topo_order(g: dict) -> list | None:
    by_id = _nodes_by_id(g)
    indegree = {node_id: 0 for node_id in by_id}
    succ = {node_id: [] for node_id in by_id}
    for edge in g.get("edges") or ():
        if edge["from"] in by_id and edge["to"] in by_id:
            indegree[edge["to"]] += 1
            succ[edge["from"]].append(edge["to"])
    ready = [node_id for node_id in by_id if indegree[node_id] == 0]
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in succ[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order if len(order) == len(by_id) else None


def concurrent_arrivals(g: dict) -> list:
    """Every pair of arrows into one step that can BOTH fire in one run —
    `[Arrival(node_id, first, second)]`, arrows as `{from, port, to}`.

    Two arrivals are exclusive iff every pair of paths that delivers them
    leaves some shared step by different ports (a step leaves by exactly one
    port, so both cannot happen). Asked as a reachability rather than by
    listing paths: two walkers start together at the start and, the one
    earlier in topological order moving first (together, by ONE port, when
    they stand on the same step), every state `(a, b)` they can reach is a
    pair of consistent partial paths. Arrows `X1 -p1-> D` and `X2 -p2-> D`
    (X1 before X2) co-fire iff a walker stands on X1 while the other stands on
    a later step that reaches X2, or both stand on X1 and a `p1` arrow out of
    X1 reaches X2. `tests/test_a_workflow_branches_and_meets.py` holds it
    equal to the path-by-path rule on generated graphs.

    A document with a loop answers `[]` — `find_loop` refuses it first. With no
    start arrows, the start leads to the steps nothing leads to."""
    by_id = _nodes_by_id(g)
    order = _topo_order(g)
    if order is None or not order:
        return []
    index = {node_id: i for i, node_id in enumerate(order)}
    index[START_KEY] = -1
    out = {node_id: {} for node_id in index}
    arrows = []
    drawn = set()
    for edge in g.get("edges") or ():
        key = (edge["from"], edge["port"], edge["to"])
        if edge["from"] in index and edge["to"] in by_id and key not in drawn:
            drawn.add(key)
            arrows.append(edge)
            out[edge["from"]].setdefault(edge["port"], []).append(edge["to"])
    if not start_edges(g):
        for node in _entries(g):
            out[START_KEY].setdefault(PORT_SUCCESS, []).append(node["id"])
    reach = {}
    for node_id in reversed(order):
        found = {node_id}
        for targets in out[node_id].values():
            for t in targets:
                found |= reach[t]
        reach[node_id] = found
    states = {(START_KEY, START_KEY)}
    frontier = [(START_KEY, START_KEY)]
    while frontier:
        a, b = frontier.pop()
        if a == b:
            nxt = [(t1, t2) for targets in out[a].values() for t1 in targets for t2 in targets]
        elif index[a] < index[b]:
            nxt = [(t, b) for targets in out[a].values() for t in targets]
        else:
            nxt = [(a, t) for targets in out[b].values() for t in targets]
        for state in nxt:
            if state not in states:
                states.add(state)
                frontier.append(state)
    found = []
    for node_id in order:
        incoming = list({(e["from"], e["port"]): e for e in reversed(arrows)
                         if e["to"] == node_id}.values())[::-1]
        for i, e1 in enumerate(incoming):
            for e2 in incoming[i + 1:]:
                if e1["from"] == e2["from"]:
                    continue  # one step, two ports: it leaves by one
                x1, x2 = (e1, e2) if index[e1["from"]] < index[e2["from"]] else (e2, e1)
                a, b = x1["from"], x2["from"]
                together = any(s[0] == a and s[1] != START_KEY and index[s[1]] > index[a]
                               and b in reach.get(s[1], ()) for s in states)
                if not together and (a, a) in states:
                    together = any(b in reach.get(t, ()) for t in out[a].get(x1["port"], ()))
                if together:
                    found.append(Arrival(node_id, e1, e2))
    return found


# ── The rule ─────────────────────────────────────────────────────────────────

def _text(config: dict, key: str) -> str:
    value = config.get(key) if isinstance(config, dict) else None
    return value.strip() if isinstance(value, str) else ""


def _is_scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_json(value, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if _is_scalar(value):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json(v, depth + 1) for k, v in value.items())
    return False


def _check_text(key, value):
    if value is not None and not isinstance(value, str):
        return f"“{key}” must be text"
    return None


def _check_max_steps(key, value):
    from src.run_limits import AGENT_MAX_ROUNDS_RANGE

    lo, hi = AGENT_MAX_ROUNDS_RANGE
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                              or not lo <= value <= hi):
        return f"“{key}” must be a whole number from {lo} to {hi}"
    return None


def _check_whole(lo, hi):
    def check(key, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or not lo <= value <= hi):
            return f"“{key}” must be a whole number from {lo} to {hi}"
        return None
    return check


def _check_names(key, value):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) > AI_TOOLS_MAX
            or not all(isinstance(v, str) and v.strip() for v in value)):
        return f"“{key}” must be a list of up to {AI_TOOLS_MAX} tool names"
    if len(set(value)) != len(value):
        return f"“{key}” names a tool twice"
    return None


def _check_answer_fields(key, value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > ANSWER_FIELDS_MAX:
        return f"“{key}” must be a list of up to {ANSWER_FIELDS_MAX} fields"
    names = set()
    for field in value:
        if not isinstance(field, dict) or set(field) - {"name", "type", "description"}:
            return f"each of “{key}” is a name, a type and a description"
        name = field.get("name")
        if not isinstance(name, str) or not _FIELD_NAME_RE.fullmatch(name):
            return (f"an answer field is called {name!r}; a name is letters, digits and _, "
                    f"starting with a letter")
        if name in names:
            return f"two answer fields are called {name!r}"
        names.add(name)
        if field.get("type") not in ANSWER_TYPES:
            return f"the answer field {name!r} must be one of {', '.join(ANSWER_TYPES)}"
        description = field.get("description")
        if description is not None and (not isinstance(description, str)
                                        or len(description) > ANSWER_DESCRIPTION_MAX):
            return (f"the answer field {name!r} has a description that is not text of up to "
                    f"{ANSWER_DESCRIPTION_MAX} characters")
    return None


def _condition_problem(condition) -> str | None:
    if not isinstance(condition, dict) or set(condition) - {"left", "op", "right"}:
        return "each condition is a field, a test and a value"
    if not isinstance(condition.get("op"), str):
        return "each condition needs a test"
    if not _is_scalar(condition.get("left")):
        return "a condition's field must be text"
    right = condition.get("right")
    if not (_is_scalar(right) or (isinstance(right, list) and len(right) <= 100
                                  and all(_is_scalar(r) for r in right))):
        return "a condition's value must be text, a number, yes/no or a list of them"
    return None


def _check_conditions(key, value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > CONDITIONS_MAX:
        return f"“{key}” must be a list of up to {CONDITIONS_MAX} conditions"
    for condition in value:
        problem = _condition_problem(condition)
        if problem:
            return problem
    return None


def _check_cases(key, value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > CASES_MAX:
        return f"“{key}” must be a list of up to {CASES_MAX} ways"
    for case in value:
        if not isinstance(case, dict) or set(case) - {"id", "label", "join", "conditions"}:
            return "each way is a name, its conditions and whether all or any must hold"
        if not isinstance(case.get("id"), str) or not isinstance(case.get("label"), str):
            return "each way needs an id and a name"
        if case.get("join") is not None and not isinstance(case.get("join"), str):
            return "a way's “join” must be text"
        problem = _check_conditions("conditions", case.get("conditions"))
        if problem:
            return problem
    return None


def _check_entries(key, value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > ENTRIES_MAX:
        return f"“{key}” must be a list of up to {ENTRIES_MAX} names and values"
    for entry in value:
        if not isinstance(entry, dict) or set(entry) - {"name", "value"}:
            return f"each of “{key}” is a name and a value"
        if not isinstance(entry.get("name"), str):
            return f"each of “{key}” needs a name"
        if not _is_json(entry.get("value")):
            return f"a value in “{key}” is not text, a number, yes/no or a list"
    return None


def _check_args(key, value):
    if value is None:
        return None
    if not isinstance(value, dict) or len(value) > MCP_ARGS_MAX:
        return f"“{key}” must be a set of up to {MCP_ARGS_MAX} named arguments"
    if not _is_json(value):
        return f"“{key}” holds something that is not JSON"
    return None


def _check_step(key, value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"kind", "label", "config"}:
        return f"“{key}” must be one step: a kind, a name and its settings"
    if not isinstance(value.get("kind"), str):
        return f"“{key}” needs a kind"
    if value.get("label") is not None and not isinstance(value.get("label"), str):
        return f"“{key}”'s name must be text"
    if value.get("config") is not None and not isinstance(value.get("config"), dict):
        return f"“{key}”'s settings must be an object"
    return None


_FIELD_CHECKS = {
    "max_steps": _check_max_steps,
    "tools": _check_names,
    "answer_fields": _check_answer_fields,
    "conditions": _check_conditions,
    "cases": _check_cases,
    "fields": _check_entries,
    "headers": _check_entries,
    "query": _check_entries,
    "body": _check_entries,
    "input": _check_entries,
    "args": _check_args,
    "step": _check_step,
    "timeout_seconds": _check_whole(*CODE_TIMEOUT_RANGE),
    "minutes": _check_whole(1, WORKFLOW_WAIT_MAX_HOURS_RANGE[1] * 60),
}


def _setting_problem(kind: str, config: dict) -> str | None:
    """A config key this kind does not take, or a value of the wrong shape.
    A For-each's inner step is checked as a step of its own kind."""
    allowed = NODE_CONFIG_FIELDS.get(kind, ())
    for key, value in config.items():
        if key not in allowed:
            return f"“{key}”"
        problem = _FIELD_CHECKS.get(key, _check_text)(key, value)
        if problem:
            return problem
    if kind == NODE_KIND_FOREACH and isinstance(config.get("step"), dict):
        inner = config["step"]
        if inner.get("kind") in NODE_CONFIG_FIELDS:
            problem = _setting_problem(inner["kind"], inner.get("config") or {})
            if problem:
                return f"the step it repeats: {problem}"
    return None


# The words a person reads for a setting, for a refusal's sentence. The panel
# puts the sentence on the field itself (`DocumentRefusal.field`).
_FIELD_WORDS = {
    "prompt": "Prompt", "model": "Model", "endpoint_url": "Endpoint",
    "character_id": "Persona", "crew_member_id": "Crew member", "max_steps": "Step cap",
    "output_target": "Where the result goes", "tools": "Tools",
    "answer_fields": "Answer fields", "action": "Action", "task_id": "Task",
    "conditions": "Condition", "join": "All or any", "cases": "Way", "fields": "Field",
    "mode": "Mode", "minutes": "Minutes", "time": "Time", "tz": "Time zone",
    "list": "List", "step": "Step", "on_error": "If an item fails",
    "integration": "Integration", "method": "Method", "path": "Path", "headers": "Header",
    "query": "Query", "body": "Body", "body_mode": "Body", "tool": "Tool",
    "args": "Argument", "skill": "Skill", "language": "Language", "source": "Code",
    "timeout_seconds": "Time limit", "input": "Input",
}


def field_words(node: dict, path) -> str:
    """The setting at `path` in words: an action's parameter label, an HTTP
    entry or MCP argument by its name, else the field's own word."""
    from src.builtin_actions import BUILTIN_ACTION_META

    path = tuple(path)
    if not path:
        return "Settings"
    kind = node.get("kind")
    config = node.get("config") or {}
    if kind == NODE_KIND_FOREACH and path[:2] == ("step", "config") and len(path) > 2 \
            and isinstance(config.get("step"), dict):
        return f"the step it repeats, {field_words(config['step'], path[2:])}"
    if kind == NODE_KIND_ACTION and path[0] == "prompt":
        params = (BUILTIN_ACTION_META.get(config.get("action") or "") or {}).get("params") or ()
        return next((p.get("label") for p in params if p.get("label")), "Settings")
    if kind == NODE_KIND_MCP and path[0] == "args" and len(path) > 1:
        return f"“{path[1]}”"
    if path[0] in ("query", "body", "headers", "input", "fields") and len(path) > 1 \
            and isinstance(path[1], int):
        try:
            name = config[path[0]][path[1]]["name"]
        except (KeyError, IndexError, TypeError):
            name = None
        if isinstance(name, str) and name:
            return f"{_FIELD_WORDS[path[0]]} “{name}”"
    if path[0] in ("conditions", "cases") and len(path) > 1 and isinstance(path[1], int):
        return f"{_FIELD_WORDS[path[0]]} {path[1] + 1}"
    return _FIELD_WORDS.get(path[0], str(path[0]))


def _reference_problem(node: dict, resources: WorkflowResources) -> DocumentRefusal | None:
    """`P22-09`, the part that needs no arrows: every text in a `never` setting
    holds no reference; every text in a `value` setting parses; `item` is read
    only by the step inside a For-each."""
    node_id = node["id"]
    schema = _mcp_schema(node, resources)
    for path, text in config_leaves(node.get("config") or {}):
        slot = slot_for(node, path, mcp_schema=schema)
        field = path_text(path)
        if slot.mapping == MAPPING_NEVER:
            if references_in_text(text):
                return _refusal(REFUSE_MAPPED_NEVER, (node_id,),
                                f"{_called(node)}, {field_words(node, path)}. {slot.why}", field)
            continue
        try:
            template = parse_template(text)
        except RefError as exc:
            return _refusal(REFUSE_BAD_REFERENCE, (node_id,),
                            f"{_called(node)}, {field_words(node, path)}. {exc.sentence}", field)
        inside = node.get("kind") == NODE_KIND_FOREACH and path[:2] == ("step", "config")
        for ref in template.refs:
            if ref.root == REF_ROOT_ITEM and not inside:
                return _refusal(REFUSE_BAD_REFERENCE, (node_id,),
                                f"{_called(node)}, {field_words(node, path)}, reads {ref.text}, "
                                f"which only the step inside a For-each has", field)
    return None


def _upstream_problem(node: dict, graph: dict, by_id: dict) -> DocumentRefusal | None:
    """`P22-09`, the part that needs the arrows: a reference names the start or
    a step upstream of the step it is in — never itself, never one after it
    or beside it, never one that is not there."""
    node_id = node["id"]
    upstream = None
    for path, text in config_leaves(node.get("config") or {}):
        if "{{" not in text:
            continue
        try:
            refs = parse_template(text).refs
        except RefError:
            continue  # a `never` text with a `{{` that is not a reference
        for ref in refs:
            if ref.root != REF_ROOT_STEPS or ref.node == START_KEY:
                continue
            if upstream is None:
                upstream = upstream_of(graph, node_id)
            if ref.node in upstream:
                continue
            words = field_words(node, path)
            if ref.node == node_id:
                why = f"{_called(node)}, {words}, reads from itself ({ref.text})"
            elif ref.node not in by_id:
                why = f"{_called(node)}, {words}, reads from “{ref.node}”, which is not a step here"
            else:
                why = (f"{_called(node)}, {words}, reads from {_called(by_id[ref.node])}, "
                       f"which does not run before it. Draw an arrow from it, or pick a field "
                       f"from a step before this one")
            return _refusal(REFUSE_NOT_UPSTREAM, (node_id,), why, path_text(path))
    return None


def _conditions_semantics(node, conditions, join, where: str) -> DocumentRefusal | None:
    node_id = node["id"]
    if not conditions:
        return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                        f"{_called(node)} needs a condition{where}")
    if join is not None and join not in JOINS:
        return _refusal(REFUSE_BAD_SETTING, (node_id,),
                        f"{_called(node)}: “join” must be all or any")
    for condition in conditions:
        if condition.get("op") not in OPERATORS:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: {condition.get('op')!r} is not a test this "
                            f"Pantheon has")
    return None


def _inner_kind_problem(node: dict) -> DocumentRefusal | None:
    """A For-each's step is of a kind this Pantheon runs, and one a For-each
    may repeat — asked before its settings are read, so the person is told
    the kind, not what an unknown kind's settings fall closed to."""
    inner = (node.get("config") or {}).get("step")
    if node.get("kind") != NODE_KIND_FOREACH or not isinstance(inner, dict):
        return None
    inner_kind = inner.get("kind")
    if references_in_text(inner_kind):
        return None  # `_reference_problem` says it: the kind is the author's to type
    if inner_kind not in NODE_KINDS:
        return _refusal(REFUSE_BAD_KIND, (node["id"],),
                        f"{_called(node)} repeats a {inner_kind!r} step", "step.kind")
    if inner_kind in FOREACH_REFUSED_KINDS:
        return _refusal(REFUSE_FOREACH_INNER, (node["id"],),
                        f"{_called(node)} repeats a step of kind {inner_kind!r}. It can "
                        f"repeat one step of any kind but If, Switch, Merge, Wait and "
                        f"For-each", "step.kind")
    return None


def _kind_problem(node: dict, *, owner, tasks_by_id, crew_ids, owner_is_admin,
                  own_task_id, resources: WorkflowResources) -> DocumentRefusal | None:
    """What one step of its kind needs to run, or why it cannot."""
    from src.builtin_actions import BUILTIN_ACTION_META, BUILTIN_ACTIONS
    from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS, admin_refusal_message

    node_id, kind = node["id"], node["kind"]
    config = node.get("config") or {}
    if kind in (NODE_KIND_PROMPT, NODE_KIND_RESEARCH) and not _text(config, "prompt"):
        what = "what to ask" if kind == NODE_KIND_PROMPT else "the question to research"
        return _refusal(REFUSE_MISSING_SETTING, (node_id,), f"{_called(node)} needs {what}")
    if kind == NODE_KIND_PROMPT:
        for tool in config.get("tools") or ():
            if tool not in (resources.ai_tools or ()):
                return _refusal(REFUSE_UNKNOWN_TOOL, (node_id,),
                                f"{_called(node)} lists {tool!r}", "tools")
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
    if kind == NODE_KIND_IF:
        found = _conditions_semantics(node, config.get("conditions"), config.get("join"), "")
        if found:
            return found
    if kind == NODE_KIND_SWITCH:
        cases = config.get("cases") or []
        if not cases:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs at least one way to go")
        ids = set()
        for case in cases:
            if not _CASE_ID_RE.fullmatch(case["id"]) or case["id"] in ids:
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)}: two ways share the id {case['id']!r}, or it "
                                f"cannot be used")
            ids.add(case["id"])
            label = case["label"].strip()
            if not label or len(label) > CASE_LABEL_MAX:
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)}: each way needs a name of up to "
                                f"{CASE_LABEL_MAX} characters")
            found = _conditions_semantics(node, case.get("conditions"), case.get("join"),
                                          f" for “{label}”")
            if found:
                return found
    if kind == NODE_KIND_SET:
        fields = config.get("fields") or []
        if not fields:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a field to make")
        if len(fields) > SET_FIELDS_MAX:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)} makes more than {SET_FIELDS_MAX} fields")
        names = set()
        for field in fields:
            if not _FIELD_NAME_RE.fullmatch(field["name"]) or field["name"] in names:
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)}: a field is called {field['name']!r}, twice or "
                                f"in a way a reference cannot read. A name is letters, digits "
                                f"and _, starting with a letter")
            names.add(field["name"])
    if kind == NODE_KIND_MERGE:
        if config.get("mode") is not None and config.get("mode") not in MERGE_MODES:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: it waits for all of its branches or the first")
    if kind == NODE_KIND_WAIT:
        mode = config.get("mode")
        if mode not in WAIT_MODES:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs how long to wait, or until when")
        if mode == WAIT_FOR:
            minutes = config.get("minutes")
            most = resources.wait_max_hours * 60
            if minutes is None or not 1 <= minutes <= most:
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)} waits from 1 minute to {resources.wait_max_hours} "
                                f"hours (the “workflow_wait_max_hours” setting)", "minutes")
        else:
            if not isinstance(config.get("time"), str) or not _TIME_RE.fullmatch(config["time"]):
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)} waits until a time written like 08:00", "time")
            tz = config.get("tz")
            if tz:
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(tz)
                except Exception:  # noqa: BLE001 - any failure is "not a zone"
                    return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                    f"{_called(node)}: {tz!r} is not a time zone", "tz")
    if kind == NODE_KIND_FOREACH:
        if single_ref(config.get("list")) is None:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a list: pick one field that is a list, from "
                            f"a step before it", "list")
        if config.get("on_error") is not None and config.get("on_error") not in FOREACH_ON_ERROR:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: when an item fails it stops or goes on")
        inner = config.get("step")
        if not isinstance(inner, dict):
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a step to repeat")
        inner_kind = inner.get("kind")
        found = _inner_kind_problem(node)
        if found:
            return found
        as_node = {"id": node_id, "kind": inner_kind,
                   "label": inner.get("label") or node.get("label"),
                   "config": inner.get("config") or {}}
        found = _kind_problem(as_node, owner=owner, tasks_by_id=tasks_by_id,
                              crew_ids=crew_ids, owner_is_admin=owner_is_admin,
                              own_task_id=own_task_id, resources=resources)
        if found:
            return found._replace(field=f"step.config.{found.field}" if found.field else "step")
    if kind in ADMIN_ONLY_KINDS and not owner_is_admin:
        word = "sends an HTTP request" if kind == NODE_KIND_HTTP else "calls an MCP tool"
        return _refusal(REFUSE_ADMIN_ONLY, (node_id,),
                        f"{_called(node)} {word}, and only an admin's agent can")
    if kind == NODE_KIND_HTTP:
        integration = _text(config, "integration")
        if not integration:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs an Integration", "integration")
        info = (resources.integrations or {}).get(integration)
        if not isinstance(info, dict) or info.get("enabled", True) is False:
            return _refusal(REFUSE_UNKNOWN_INTEGRATION, (node_id,), f"{_called(node)}",
                            "integration")
        if (config.get("method") or "GET") not in HTTP_METHODS:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: the method is one of {', '.join(HTTP_METHODS)}",
                            "method")
        path = config.get("path") or ""
        if not path.startswith("/") or "://" in path or "#" in path:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: the path starts with / and holds no address or #",
                            "path")
        if config.get("body_mode") not in (None, BODY_MODE_JSON):
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: the body is sent as JSON", "body_mode")
        for key in ("headers", "query", "body"):
            names = set()
            for index, entry in enumerate(config.get(key) or ()):
                name = entry["name"]
                if (not name or name in names
                        or (key == "headers" and not _HEADER_NAME_RE.fullmatch(name))):
                    return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                    f"{_called(node)}: {_FIELD_WORDS[key]} names must be "
                                    f"filled in and different", f"{key}[{index}].name")
                names.add(name)
    if kind == NODE_KIND_MCP:
        tool = _text(config, "tool")
        if not tool:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a tool", "tool")
        info = _mcp_info(resources, tool)
        if info is None or info.get("disabled"):
            return _refusal(REFUSE_UNKNOWN_TOOL, (node_id,), f"{_called(node)} calls {tool!r}",
                            "tool")
    if kind == NODE_KIND_SKILL:
        skill = _text(config, "skill")
        if not skill:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a skill to follow", "skill")
        if skill not in (resources.skills or ()):
            return _refusal(REFUSE_UNKNOWN_SKILL, (node_id,), f"{_called(node)} follows {skill!r}",
                            "skill")
    if kind == NODE_KIND_CODE:
        if config.get("language") not in CODE_LANGUAGES:
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs a language: Python or bash", "language")
        source = config.get("source") or ""
        if not source.strip():
            return _refusal(REFUSE_MISSING_SETTING, (node_id,),
                            f"{_called(node)} needs code to run", "source")
        if len(source) > CODE_SOURCE_MAX:
            return _refusal(REFUSE_BAD_SETTING, (node_id,),
                            f"{_called(node)}: the code is longer than {CODE_SOURCE_MAX:,} "
                            f"characters", "source")
        names = set()
        for index, entry in enumerate(config.get("input") or ()):
            if not _FIELD_NAME_RE.fullmatch(entry["name"]) or entry["name"] in names:
                return _refusal(REFUSE_BAD_SETTING, (node_id,),
                                f"{_called(node)}: each input needs its own name, letters, "
                                f"digits and _", f"input[{index}].name")
            names.add(entry["name"])
        if resources.workstation_why:
            return _refusal(REFUSE_WORKSTATION, (node_id,),
                            f"{_called(node)}. {resources.workstation_why}")
    crew = _text(config, "crew_member_id")
    if crew and crew not in crew_ids:
        return _refusal(REFUSE_UNKNOWN_CREW, (node_id,), f"{_called(node)}")
    return None


def validate_document(graph: dict, *, owner: str | None, tasks_by_id: dict,
                      crew_ids, owner_is_admin: bool,
                      own_task_id: str | None,
                      resources: WorkflowResources | None = None) -> DocumentRefusal | None:
    """The first reason this document may not run, or `None`. Pure.

    Asked at save (the workflow routes, against the person's own tasks and
    crew) and again at run (the walker, against the same, read fresh), so a
    task deleted or a role lost between the two is caught where it matters,
    in the same words. `graph` is `parse_graph`'s answer. `tasks_by_id` is the
    owner's tasks, by id; `crew_ids` the owner's crew member ids; `resources`
    what the person can reach (`WorkflowResources`; none given is none
    reachable, so every effect step is refused — fail closed).

    In order: each step's id, name, kind and settings' shape; the references
    in its settings (`mapped_never`, `bad_reference`); what its kind needs;
    then the arrows (`bad_edge`, `two_arrows`), loops over every arrow
    (`find_loop`, told in `describe_graph_refusal`'s words, naming steps by
    label), a step nothing leads to, two branches meeting outside a Merge
    (`concurrent_arrivals`), and last what each reference names
    (`not_upstream`).
    """
    resources = resources if isinstance(resources, WorkflowResources) else EMPTY_RESOURCES
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
        if (not node_id or len(node_id) > NODE_ID_MAX or not NODE_ID_RE.fullmatch(node_id)
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
        found = _inner_kind_problem(node) or _reference_problem(node, resources)
        if found:
            return found
        found = _kind_problem(node, owner=owner, tasks_by_id=tasks_by_id, crew_ids=crew_ids,
                              owner_is_admin=owner_is_admin, own_task_id=own_task_id,
                              resources=resources)
        if found:
            return found
    by_id = _nodes_by_id(graph)
    taken = set()
    for edge in edges:
        if edge["from"] == START_KEY:
            if edge["to"] not in by_id:
                return _refusal(REFUSE_BAD_EDGE, (),
                                "it points at a step that is not in the workflow")
            if edge["port"] not in START_PORTS:
                return _refusal(REFUSE_BAD_EDGE, (edge["to"],),
                                f"the arrow out of the start leaves by {edge['port']!r}; the "
                                f"start has one way out")
        else:
            if edge["from"] not in by_id or edge["to"] not in by_id:
                return _refusal(REFUSE_BAD_EDGE,
                                tuple(i for i in (edge["from"], edge["to"]) if i in by_id),
                                "it points at a step that is not in the workflow")
            source = by_id[edge["from"]]
            if edge["port"] not in ports_of(source):
                if ports_of(source) == PORTS:
                    detail = (f"the arrow out of {_called(source)} is "
                              f"neither “if it works” nor “if it fails”")
                else:
                    ways = ", ".join(f"“{port_words(source, p)}”" for p in ports_of(source))
                    detail = (f"the arrow out of {_called(source)} leaves by "
                              f"{edge['port']!r}, and it leaves by {ways}")
                return _refusal(REFUSE_BAD_EDGE, (edge["from"],), detail)
        key = (edge["from"], edge["port"], edge["to"])
        if key in taken:
            source = by_id.get(edge["from"])
            where = "the start" if edge["from"] == START_KEY else _called(source)
            return _refusal(REFUSE_TWO_ARROWS, (edge["from"],),
                            f"{where} → {_called(by_id[edge['to']])}, "
                            f"{port_words(source, edge['port'])}, is drawn twice. Remove one")
        taken.add(key)
    loop = find_loop(graph)
    if loop is not None:
        sentence = describe_graph_refusal(
            loop, names={n["id"]: n["label"] for n in nodes},
            lead=WORKFLOW_REFUSAL_REASONS[REFUSE_CYCLE])
        ids = tuple(dict.fromkeys(e["from"] for e in loop.path))
        return DocumentRefusal(REFUSE_CYCLE, ids, sentence)
    entries = _entries(graph)
    if start_edges(graph):
        led_from_start = {e["to"] for e in start_edges(graph)}
        unled = [n for n in entries if n["id"] not in led_from_start]
        if unled:
            named = ", ".join(_called(n) for n in unled[:4])
            return _refusal(REFUSE_SEVERAL_STARTS, tuple(n["id"] for n in unled),
                            f"{named}. Connect each to the start or to the step before it, "
                            f"or remove it")
    elif len(entries) > 1:
        named = ", ".join(_called(n) for n in entries[:4])
        return _refusal(REFUSE_SEVERAL_STARTS, tuple(n["id"] for n in entries),
                        f"{named}. Connect each to the step before it, or remove it")
    for arrival in concurrent_arrivals(graph):
        target = by_id[arrival.node_id]
        if target["kind"] == NODE_KIND_MERGE:
            continue
        # § 1.3's sentence, whole: the reason's lead would read as a list.
        sentence = (f"Two branches that run at the same time both reach {_called(target)}. "
                    f"Put a Merge step before it.")
        return DocumentRefusal(REFUSE_NEEDS_MERGE,
                               (arrival.node_id, arrival.first["from"], arrival.second["from"]),
                               sentence)
    for node in nodes:
        found = _upstream_problem(node, graph, by_id)
        if found:
            return found
    return None


# ── Versions, positions, pins ───────────────────────────────────────────────

def without_pins(graph: dict) -> dict:
    """A copy with every step's sample removed — what a kept version holds."""
    out = json.loads(json.dumps(graph, default=str))
    for node in out.get("nodes") or ():
        node["pinned"] = None
    return out


def version_graph(graph: dict) -> dict:
    """`P22-19`. What a kept version holds: `without_pins`, and no step's
    `unchecked` mark. A mark is the CURRENT document's state, not its content
    (`content_fingerprint` leaves it out), so a version never carries one and
    a restore never brings one back (`workflow_store._marks_kept` decides what
    a restore keeps)."""
    out = without_pins(graph)
    for node in out.get("nodes") or ():
        if isinstance(node, dict):
            node.pop(UNCHECKED_KEY, None)
    return out


def marked_nodes(graph: dict) -> list:
    """The steps that carry an `unchecked` mark, in document order."""
    return [n for n in graph.get("nodes") or ()
            if isinstance(n, dict) and isinstance(n.get(UNCHECKED_KEY), dict)]


def unchecked_refusal(graph: dict) -> DocumentRefusal | None:
    """`P22-19` (`SLICE-EF-DESIGN` § 1.1). Why this document may not be switched
    on or run for real while a step carries a mark, or `None`.

    Asked by `workflow_store.switch_workflow` (so the task route's resume and
    `manage_tasks resume`, which go through it, are refused too) and by the
    walker before a real run's first step — which covers a marked document
    written straight to the database while its trigger is on. NOT asked by a
    save, the dry run or *Test this step*: checking a step is exactly when
    you want to test it."""
    marked = marked_nodes(graph)
    if not marked:
        return None
    origins = {n[UNCHECKED_KEY].get("origin") for n in marked}
    if origins == {ORIGIN_IMPORTED}:
        who = "A file brought in"
    elif origins == {ORIGIN_DRAFTED}:
        who = "The model drafted"
    else:
        who = "The model drafted, or a file brought in,"
    count = len(marked)
    named = ", ".join(_called(n) for n in marked[:6]) + (" …" if count > 6 else "")
    which = "it" if count == 1 else "each one"
    sentence = (f"{who} {count} step{'s' if count != 1 else ''} nobody has checked yet: "
                f"{named}. Open {which} and press Looks right (or change it), then switch it on.")
    return DocumentRefusal(REFUSE_UNCHECKED, tuple(n["id"] for n in marked), sentence)


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
    """The envelope `node_id` would be handed: the trigger's for a step the
    start leads to (an event's declared fields, a webhook's four), the step
    before it's hand-off for any other (`TASK_HANDOFF_FIELDS`, named for its
    first parent)."""
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


# ── What a step does, for *Test this step* (`P22-08`) and the dry run ───────

def node_effects(node: dict, tasks_by_id: dict | None = None,
                 resources: WorkflowResources | None = None) -> tuple:
    """What running this step would do, in `ACTION_EFFECTS` words — the step
    itself, not where its result is sent (a test never delivers). A Run task
    step's are its task's; a For-each's are the step it repeats.

    `P22-13` … `P22-18`: an HTTP request other than GET, and an MCP tool not
    known to be read-only (`resources`; none given is not known), change
    something that is not this machine; Code runs code; a skill calls a
    model; a logic step, a Merge and a Wait do nothing outside the run."""
    from src.builtin_actions import (
        BUILTIN_ACTION_META, EFFECT_CALLS_MODEL, EFFECT_RUNS_CODE,
        EFFECT_TOUCHES_REMOTE, EFFECT_WRITES,
    )

    kind = node.get("kind")
    config = node.get("config") or {}
    if kind == NODE_KIND_ACTION:
        return tuple((BUILTIN_ACTION_META.get(config.get("action") or "") or {})
                     .get("effects") or ())
    if kind == NODE_KIND_RESEARCH:
        return (EFFECT_CALLS_MODEL, EFFECT_WRITES)
    if kind in (NODE_KIND_PROMPT, NODE_KIND_SKILL):
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
    if kind == NODE_KIND_HTTP:
        return () if (config.get("method") or "GET") == "GET" else (EFFECT_TOUCHES_REMOTE,)
    if kind == NODE_KIND_MCP:
        info = _mcp_info(resources or EMPTY_RESOURCES, config.get("tool"))
        return () if info and info.get("is_readonly") is True else (EFFECT_TOUCHES_REMOTE,)
    if kind == NODE_KIND_CODE:
        return (EFFECT_RUNS_CODE,)
    if kind == NODE_KIND_FOREACH:
        inner = config.get("step")
        if not isinstance(inner, dict) or inner.get("kind") == NODE_KIND_FOREACH:
            return ()
        return node_effects(inner, tasks_by_id, resources)
    return ()


def needs_test_confirmation(node: dict, tasks_by_id: dict | None = None,
                            resources: WorkflowResources | None = None) -> bool:
    """Does testing this step show its plan and ask before it runs for real?

    An action, HTTP, MCP, Code or For-each step whose effects meet
    `TEST_CONFIRM_EFFECTS` (so HTTP other than GET, an MCP tool not read-only,
    and Code always ask); a Run task step always, because it really runs
    another task, with its own delivery and chain. A Prompt, Research, AI,
    skill or logic step does not: its effects are a model call and a report,
    and a model's tools are gated per call as in chat. Mistake prevention,
    not a control (`Law 17`).
    """
    from src.builtin_actions import TEST_CONFIRM_EFFECTS

    kind = node.get("kind")
    if kind == NODE_KIND_RUN_TASK:
        return True
    if kind in (NODE_KIND_ACTION, NODE_KIND_HTTP, NODE_KIND_MCP, NODE_KIND_CODE,
                NODE_KIND_FOREACH):
        if kind == NODE_KIND_FOREACH:
            inner = (node.get("config") or {}).get("step")
            if isinstance(inner, dict) and inner.get("kind") == NODE_KIND_RUN_TASK:
                return True
        return bool(set(node_effects(node, tasks_by_id, resources)) & set(TEST_CONFIRM_EFFECTS))
    return False


def node_needs_model(node: dict) -> bool:
    """Does this step call a model, and so need the run's model slot?

    Replaces the walker's `kind != action → True` (`SLICE-CD-DESIGN` § 0.9),
    which would have queued every deterministic step for a model: a Prompt,
    Research, AI or skill step does; an action does when it is model-backed
    (`MODEL_BACKED_ACTIONS`, `P8-22`'s one statement); a Run task step may (its
    task runs inside this run's slot); a For-each does when the step it
    repeats does. HTTP, MCP, Code, If, Switch, Set, Merge and Wait do not."""
    from src.builtin_actions import MODEL_BACKED_ACTIONS

    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    if kind in MODEL_KINDS or kind == NODE_KIND_RUN_TASK:
        return True
    if kind == NODE_KIND_ACTION:
        return (config.get("action") or "") in MODEL_BACKED_ACTIONS
    if kind == NODE_KIND_FOREACH:
        inner = config.get("step")
        return (isinstance(inner, dict) and inner.get("kind") != NODE_KIND_FOREACH
                and node_needs_model(inner))
    return kind not in NODE_KINDS  # a kind this build does not know: queue, as an unknown task


def _shown(value) -> str:
    """A setting as the plan shows it: text as typed (references and all —
    never a value), anything else as JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


# `P22-18`. What a Code step does, in the words for where it runs (`B967`):
# the person's own workstation account — not "as the user Pantheon runs as",
# which is an action's command (`EFFECT_SENTENCES[EFFECT_RUNS_CODE]`). Its
# plan and *Test this step*'s effects both say this (`integrate-d`: they said
# "in your workstation, as you" and then "as the user Pantheon runs as").
CODE_EFFECT_SENTENCE = "runs your code in your own workstation account, not on this machine"


def plan_lines(node: dict, resources: WorkflowResources | None = None) -> list:
    """What this step would do, as lines, for the dry run. Executes nothing
    and resolves nothing: `never` settings are shown verbatim and `value`
    settings as written — their references, never what they would read
    (`SLICE-CD-DESIGN` § 1.3). The task kinds are `dry_run_plan`'s lines (one
    planner, `Law 7`)."""
    from src.builtin_actions import (
        EFFECT_SENTENCES, EFFECT_TOUCHES_REMOTE, dry_run_plan,
    )

    resources = resources if isinstance(resources, WorkflowResources) else EMPTY_RESOURCES
    kind = node.get("kind")
    config = node.get("config") or {}
    lines = []
    if kind in STAND_IN_KINDS:
        lines = dry_run_plan(task_type=kind, action=config.get("action"),
                             prompt=config.get("prompt"), model=config.get("model"),
                             endpoint_url=config.get("endpoint_url"))
        if kind != NODE_KIND_ACTION and config.get("prompt") and "{{" in config["prompt"]:
            lines.append(f"Its prompt, as written: {config['prompt']}")
        if kind == NODE_KIND_PROMPT and config.get("tools") is not None:
            tools = ", ".join(config["tools"]) or "none"
            lines.append(f"Tools it may use: {tools}")
        if kind == NODE_KIND_PROMPT and config.get("answer_fields"):
            names = ", ".join(f["name"] for f in config["answer_fields"])
            lines.append(f"It answers with the fields: {names}")
    elif kind == NODE_KIND_RUN_TASK:
        lines.append(f"Would run the task {config.get('task_id')!r}, as its own run with its "
                     f"own history.")
    elif kind == NODE_KIND_IF:
        join = JOIN_WORDS.get(config.get("join") or "all", "all of these")
        tests = "; ".join(describe_condition(c) for c in config.get("conditions") or ())
        lines.append(f"Would go the “then” way if {join} hold: {tests}. Otherwise the "
                     f"“otherwise” way.")
    elif kind == NODE_KIND_SWITCH:
        lines.append("Would go the first way that matches:")
        for case in config.get("cases") or ():
            join = JOIN_WORDS.get(case.get("join") or "all", "all of these")
            tests = "; ".join(describe_condition(c) for c in case.get("conditions") or ())
            lines.append(f"“{case.get('label')}” if {join} hold: {tests}")
        lines.append("and the “otherwise” way if none does.")
    elif kind == NODE_KIND_SET:
        lines.append("Would make these fields:")
        for field in config.get("fields") or ():
            lines.append(f"{field.get('name')} ← {_shown(field.get('value'))}")
    elif kind == NODE_KIND_MERGE:
        lines.append("Would go on as soon as the first branch arrives."
                     if config.get("mode") == MERGE_FIRST else
                     "Would wait for every branch that leads here, then go on with all of them.")
    elif kind == NODE_KIND_WAIT:
        if config.get("mode") == WAIT_UNTIL:
            zone = config.get("tz") or "the trigger's time zone"
            lines.append(f"Would wait until {config.get('time')} ({zone}), or as soon after as "
                         f"Pantheon is idle.")
        else:
            minutes = config.get("minutes")
            lines.append(f"Would wait {minutes} minute{'s' if minutes != 1 else ''}, or as soon "
                         f"after as Pantheon is idle.")
    elif kind == NODE_KIND_FOREACH:
        inner = config.get("step") if isinstance(config.get("step"), dict) else {}
        what = inner.get("label") or inner.get("kind") or "its step"
        lines.append(f"Would repeat “{what}” for each item of {config.get('list')}, in order, "
                     f"at most {resources.foreach_max_items} items.")
        lines.append("If an item fails it goes on to the next."
                     if config.get("on_error") == ON_ERROR_CONTINUE else
                     "If an item fails it stops there.")
        if inner.get("kind") != NODE_KIND_FOREACH:
            for line in plan_lines(inner, resources):
                lines.append(f"  {line}")
    elif kind == NODE_KIND_HTTP:
        integration = config.get("integration")
        info = (resources.integrations or {}).get(integration) if isinstance(integration, str) \
            else None
        name = (info or {}).get("name") or integration
        lines.append(f"Would call {name} — {config.get('method') or 'GET'} "
                     f"{config.get('path') or '/'}")
        for entry in config.get("headers") or ():
            lines.append(f"Header {entry.get('name')}: as you typed it")
        for entry in config.get("query") or ():
            lines.append(f"Query {entry.get('name')}: {_shown(entry.get('value'))}")
        for entry in config.get("body") or ():
            lines.append(f"Body {entry.get('name')}: {_shown(entry.get('value'))}")
        if (config.get("method") or "GET") != "GET":
            lines.append(f"It would: {EFFECT_SENTENCES[EFFECT_TOUCHES_REMOTE]}")
    elif kind == NODE_KIND_MCP:
        lines.append(f"Would call the tool {config.get('tool')}")
        for name, value in (config.get("args") or {}).items():
            lines.append(f"{name}: {_shown(value)}")
        if node_effects(node, None, resources):
            lines.append(f"It would: {EFFECT_SENTENCES[EFFECT_TOUCHES_REMOTE]}")
    elif kind == NODE_KIND_SKILL:
        lines.append(f"Would follow the skill “{config.get('skill')}”.")
        lines.append("It would: call a model, and whatever the tools it is allowed to call "
                     "then do.")
        if config.get("prompt"):
            lines.append(f"Its prompt, as written: {config['prompt']}")
    elif kind == NODE_KIND_CODE:
        source = config.get("source") or ""
        count = len(source.splitlines())
        language = "Python" if config.get("language") == "python" else "bash"
        lines.append(f"Would run {count} line{'s' if count != 1 else ''} of {language} in your "
                     f"workstation, as you.")
        for entry in config.get("input") or ():
            lines.append(f"Hands it {entry.get('name')}: {_shown(entry.get('value'))}")
        lines.append(f"It would: {CODE_EFFECT_SENTENCE}")
    else:
        lines.append(f"A {kind!r} step is not one this Pantheon runs.")
    return lines


def _sends(node: dict, resources: WorkflowResources) -> list:
    """Where one step sends something, as phrases — empty for a step that
    sends nothing anywhere. See `destination_lines`."""
    from src.builtin_actions import (
        BUILTIN_ACTION_META, EFFECT_SENTENCES, EFFECT_TOUCHES_REMOTE,
    )

    kind = node.get("kind")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    out = []
    if kind == NODE_KIND_HTTP:
        integration = config.get("integration")
        info = (resources.integrations or {}).get(integration) if isinstance(integration, str) \
            else None
        name = (info or {}).get("name") or integration
        out.append(f"sends {config.get('method') or 'GET'} {config.get('path') or '/'} to {name}")
    elif kind == NODE_KIND_MCP:
        tool = config.get("tool")
        info = _mcp_info(resources, tool) or {}
        said = (f"{info['server_name']}: {info['name']}" if info.get("server_name") and info.get("name")
                else str(tool))
        schema = info.get("input_schema") if isinstance(info.get("input_schema"), dict) else None
        # The arguments that decide where it goes — the ones only a person
        # types (`never`); what it says (`value`) is left to the plan.
        fixed = [f"{name}: {_shown(value)}" for name, value in (config.get("args") or {}).items()
                 if slot_for(node, ("args", name), mcp_schema=schema).mapping == MAPPING_NEVER]
        out.append(f"sends to {said}" + (f" — {', '.join(fixed)}" if fixed else ""))
    elif kind == NODE_KIND_CODE:
        out.append(f"{CODE_EFFECT_SENTENCE}, and the code reaches whatever that account can")
    elif kind == NODE_KIND_ACTION:
        effects = (BUILTIN_ACTION_META.get(config.get("action") or "") or {}).get("effects") or ()
        if EFFECT_TOUCHES_REMOTE in effects:
            out.append(f"runs the action {config.get('action')}, which "
                       f"{EFFECT_SENTENCES[EFFECT_TOUCHES_REMOTE]}")
    target = config.get("output_target")
    if isinstance(target, str) and target.strip():
        out.append(f"delivers its result to {target}")
    return out


def destination_lines(graph: dict, resources: WorkflowResources | None = None) -> list:
    """`P22-19` / `P22-24` (`SLICE-EF-DESIGN` § 1.6). Where a document would
    send something, one line per step that sends — and only those (`integrate-e`,
    wb-canvas-e's `B-NEW-3`: this was every step's whole `plan_lines`, so a
    three-step draft answered three paragraphs about conditions and prompts,
    and the one line that mattered was hard to find). What a drafted or
    imported workflow answers as `destinations`, so a destination the model or
    a file chose is read before anything runs.

    A step sends when it runs without asking again once a person has checked
    it (`D-2026-10-01-05` §4) and what it does leaves the run: an HTTP request
    (any method — a GET carries its path and query to the Integration), an MCP
    call (its server and tool, and every argument only a person types — the
    channel, the address), Code (it runs in the workstation and reaches what
    the account reaches), an action that changes something elsewhere, and any
    step that delivers its result (`output_target`). A For-each says its inner
    step's. An AI step's own tool calls are not here: the run asks before any
    of them writes (`P22-16`/`P22-17`). The whole plan is still the dry run's,
    and each step's banner shows it."""
    resources = resources if isinstance(resources, WorkflowResources) else EMPTY_RESOURCES
    out = []
    for node in graph.get("nodes") or ():
        if not isinstance(node, dict):
            continue
        sends = _sends(node, resources)
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        inner = config.get("step") if isinstance(config.get("step"), dict) else None
        if node.get("kind") == NODE_KIND_FOREACH and inner is not None:
            sends += [f"repeats “{inner.get('label') or inner.get('kind') or 'its step'}”, which {s}"
                      for s in _sends(inner, resources)]
        if sends:
            out.append(f"{_called(node)} " + "; ".join(sends) + ".")
    return out


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
