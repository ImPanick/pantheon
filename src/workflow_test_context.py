# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1887` / `B1888` — what *Test this step* reads, in one place (`Law 7`).

A tested step's references (`{{ steps.<id>.data.… }}`, `{{ steps.start.… }}`)
read a context the walker never builds, because a test is one step and no
run. `TaskScheduler._test_context` built it like this: the input the person
chose — the last one, a pinned sample, a typed one, the model's example — went
in as `steps.start`, and every other step was its newest real record. For the
FIRST step that is right: what it is handed is what started the run. For any
other step it is wrong twice over (`test-input-replaces-start`), because what
that step is handed is the hand-off of the step before it
(`{task, result, data, …}`), not the trigger:

  * the pinned sample the picker offers as `{{ steps.<parent>.data.title }}`
    resolved to nothing in a test — readable only as
    `{{ steps.start.data.data.title }}`, which is wrong in a real run;
  * a later step that reads the trigger (`{{ steps.start.data.json… }}`)
    could never resolve in a test, even with *What it was handed in the last
    run*, although the real run resolves it.

And *Something I type here* could not reach what a step reads at all
(`test-custom-input-ignored`): an If after "Make greeting" whose condition
reads `{{ steps.make-greeting.data.greeting }}` was tested on the typed
`{"greeting": "goodbye"}` and went the same way whatever was typed — the
sample was cut to the hand-off's own fields and the reference still read the
last run.

**The rule now**, built here and asked by the scheduler (a test that runs)
and by the test route (`context_only`, a test that only says what it would
read):

  1. `steps.start` is always the trigger. For a step the start leads to, the
     input the person chose IS the trigger. For any other step it is the
     trigger of its last run (`TaskRun.trigger_envelope`, `B1861`) when the
     person chose *last*, else the sample pinned on a first step, else the
     trigger of the newest run.
  2. Every other step is what it made: with *last*, the records of the run
     the tested step last ran in first, then each step's newest record, then
     a pinned sample; with any other source a pinned sample first (the
     person pinned it to test with — n8n's rule too), then the records.
  3. The step before it (its first parent, the one `node_input_shape` names)
     made what the chosen input says it made: the hand-off's `result` is its
     text, its `data` its data.
  4. `outputs` — what the person typed for the steps it reads, keyed by step
     id (`start` too), each `{"data": …, "text": "…"}` — goes on top of all
     of it. The test route builds the step's input from the parent's entry
     too, so what the step is handed and what its references read are one
     answer (`workflow_routes._test_outputs`).

`reads` says, for each step the tested step's settings name, what the test
read and from where (`ORIGINS`), so the panel can show it and pre-fill one
editor per step.

**Not a control** (`Law 17`): the person testing is the owner of the
workflow, who can already run all of it. Nothing here widens what a reference
may read — the document rule (`_upstream_problem`) still decides that at
save, and a test runs the step the save rule checked.
"""

from __future__ import annotations

import json

# Where a value a test read came from (`reads[].origin`). Words a person's
# panel shows, so `Law 10`: one reading each.
ORIGIN_TYPED = "typed"          # `outputs`, what the person typed for that step
ORIGIN_HANDED = "handed"        # the input chosen for the test (its parent / the start)
ORIGIN_PIN = "pin"              # a sample pinned on a step it leads to
ORIGIN_LAST_RUN = "last_run"    # a real run's record
ORIGIN_NONE = "none"            # nothing: the reference reads nothing
ORIGINS = (ORIGIN_TYPED, ORIGIN_HANDED, ORIGIN_PIN, ORIGIN_LAST_RUN, ORIGIN_NONE)

START_LABEL = "What started it"
# The keys one `outputs` entry may carry: what a step made, as the walker's
# context holds it (`RunState.context`).
OUTPUT_KEYS = ("data", "text")
OUTPUTS_MAX_CHARS = 200_000


class OutputsRefused(ValueError):
    """`outputs` that cannot be used, with the sentence the person is told."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def _start_key() -> str:
    from src.workflow_document import START_KEY
    return START_KEY


def _nodes(graph) -> dict:
    return {str(n.get("id")): n for n in (graph or {}).get("nodes") or () if isinstance(n, dict)}


def _label(graph, node_id: str) -> str:
    if node_id == _start_key():
        return START_LABEL
    node = _nodes(graph).get(node_id) or {}
    return str(node.get("label") or node_id)


def parent_of(graph, node_id: str):
    """The step whose hand-off `node_id` is handed — its first parent
    breadth first (`workflow_document.reachable_bfs`, the one `node_input_shape`
    names) — or `None` for a step the start leads to, or one not reachable."""
    from src.workflow_document import reachable_bfs

    found = next((e for e in reachable_bfs(graph or {}) if e["node"]["id"] == node_id), None)
    return None if found is None else found["parent"]


def is_first(graph, node_id: str) -> bool:
    """Is `node_id` handed what started the run (a step the start leads to)?"""
    from src.workflow_document import reachable_bfs

    found = next((e for e in reachable_bfs(graph or {}) if e["node"]["id"] == node_id), None)
    return found is not None and found["parent"] is None


def referenced_steps(node) -> list:
    """The step ids `node`'s settings read (`start` included), each once, in
    the order they are first named. A text that does not parse names none
    (the save rule says why, not this)."""
    from src.workflow_refs import REF_ROOT_STEPS, RefError, parse_template
    from src.workflow_slots import config_leaves

    out = []
    for _path, text in config_leaves((node or {}).get("config") or {}):
        if "{{" not in text:
            continue
        try:
            refs = parse_template(text).refs
        except RefError:
            continue
        for ref in refs:
            if ref.root == REF_ROOT_STEPS and ref.node not in out:
                out.append(ref.node)
    return out


def check_outputs(graph, node_id: str, outputs) -> dict:
    """`outputs` as `{step id: {"data": …, "text": "…"}}`, or `OutputsRefused`.

    Only the start and the steps before `node_id` (`upstream_of`) — what the
    document rule lets it read — may be given; each entry is an object of
    `data` (any JSON) and `text` (text), nothing else, so `{"greeting": …}`
    typed straight in is told the shape rather than read as something it is
    not (`Law 10`)."""
    from src.workflow_document import upstream_of

    if outputs is None:
        return {}
    if not isinstance(outputs, dict):
        raise OutputsRefused("What the steps before it made is a JSON object, keyed by step id.")
    try:
        size = len(json.dumps(outputs))
    except (TypeError, ValueError):
        raise OutputsRefused("What the steps before it made could not be read as JSON.") from None
    if size > OUTPUTS_MAX_CHARS:
        raise OutputsRefused(f"What the steps before it made is longer than "
                             f"{OUTPUTS_MAX_CHARS:,} characters.")
    allowed = set(upstream_of(graph or {}, node_id)) | {_start_key()}
    out = {}
    for step_id, entry in outputs.items():
        step_id = str(step_id)
        if step_id not in allowed:
            raise OutputsRefused(
                f"“{step_id}” is not the start or a step before {_label(graph, node_id)!s}, "
                f"so this step never reads it.")
        if not isinstance(entry, dict) or not entry or set(entry) - set(OUTPUT_KEYS):
            raise OutputsRefused(
                f"What {_label(graph, step_id)} made is given as "
                f"{{\"data\": …, \"text\": \"…\"}}.")
        text = entry.get("text")
        if text is not None and not isinstance(text, str):
            raise OutputsRefused(f"The text {_label(graph, step_id)} made must be text.")
        out[step_id] = {"data": entry.get("data"), "text": text or ""}
    return out


def handoff_from(graph, parent_id: str, made: dict, *, task_id: str = "") -> dict:
    """The hand-off envelope `parent_id` would hand on, having made `made`
    (`{data, text}`) — the walker's own builder (`build_task_handoff`)."""
    from src.event_bus import build_task_handoff

    return build_task_handoff(task_name=_label(graph, parent_id), task_id=task_id,
                              run_id="", status="success", result=made.get("text") or "",
                              payload=made.get("data"))


def record_output(db, rec):
    """`{text, data}` a finished record made, whole — a record cut to its
    cap is read from the copy kept whole beside it (`B1890`,
    `workflow_runs.whole_output`) — or `None` when there is nothing whole to
    read."""
    from src import workflow_runs as wr

    if rec is None or rec.status not in wr.STEP_FINISHED:
        return None
    return wr.whole_output(db, rec)


def _pinned_outputs(graph) -> dict:
    """`{step id: {text, data}}` from the samples pinned on the steps each
    leads to — exactly what the picker offers as `pin` (`available_fields`)."""
    nodes = _nodes(graph)
    out = {}
    for edge in (graph or {}).get("edges") or ():
        source, target = str(edge.get("from")), str(edge.get("to"))
        if source in out or source == _start_key():
            continue
        pinned = (nodes.get(target) or {}).get("pinned")
        handed = pinned.get("data") if isinstance(pinned, dict) else None
        if isinstance(handed, dict) and ("result" in handed or "data" in handed):
            out[source] = {"text": handed.get("result") or "", "data": handed.get("data")}
    return out


def _pinned_start(graph):
    from src.workflow_document import start_nodes

    for node in start_nodes(graph or {}):
        pinned = node.get("pinned")
        if isinstance(pinned, dict) and isinstance(pinned.get("data"), dict):
            return pinned
    return None


def _run_trigger(db, rec, graph):
    """The trigger of the run `rec` is in: the one kept whole on its row
    (`B1861`), else — a run from before that column — the input of a step
    the start led to in that run, when it was kept whole."""
    from src import workflow_runs as wr

    if rec is None:
        return None
    kept = wr.stored_run_trigger(db, rec.run_id)
    if kept is not None:
        return kept
    firsts = set(wr.start_targets(graph or {}))
    for other in wr.run_node_records(db, rec.run_id):
        if other.node_id in firsts and getattr(other, "item", None) is None and not other.dry:
            value = wr._loads(other.input)
            if isinstance(value, dict) and not wr.is_truncated(value):
                return value
    return None


def _newest_start_trigger(db, task_id, graph):
    """The trigger of the newest run any first step ran in."""
    from datetime import datetime

    from src import workflow_runs as wr

    best = None
    for first in wr.start_targets(graph or {}):
        rec = wr.last_node_record(db, task_id, first)
        if rec is not None and (best is None or (rec.started_at or datetime.min)
                                > (best.started_at or datetime.min)):
            best = rec
    return _run_trigger(db, best, graph)


def _same_run_outputs(db, run_id: str) -> dict:
    from src import workflow_runs as wr

    out = {}
    for rec in wr.run_node_records(db, run_id):
        if getattr(rec, "item", None) is not None or getattr(rec, "dry", False):
            continue
        made = record_output(db, rec)
        if made is not None:
            out[rec.node_id] = (made, rec)
    return out


def build(db, *, task_id, graph, node: dict, envelope, source: str | None = None,
          outputs: dict | None = None) -> tuple:
    """`(ctx, reads)` for testing `node` in `graph` — the rule in the module's
    docstring. `envelope` is the input the step is handed in the test,
    `source` the `TEST_SOURCES` word it came from (`None` reads as a source
    that is not *last*), `outputs` what `check_outputs` answered."""
    from src import workflow_runs as wr
    from src.event_bus import TRIGGER_SOURCE_TASK, trigger_summary

    start = _start_key()
    node_id = str(node.get("id"))
    graph = graph or {}
    outputs = dict(outputs or {})
    steps, origin = {}, {}

    def put(step_id, made, where, status="success"):
        steps[step_id] = {"status": status, "text": made.get("text") or "",
                          "data": made.get("data")}
        origin[step_id] = where

    last_rec = wr.last_node_record(db, task_id, node_id) if task_id else None
    others = [i for i in _nodes(graph) if i != node_id]
    pins = _pinned_outputs(graph)
    from_last = source == "last"
    if from_last and last_rec is not None:
        for step_id, (made, rec) in _same_run_outputs(db, last_rec.run_id).items():
            if step_id in others:
                put(step_id, made, ORIGIN_LAST_RUN, rec.status)
    for step_id in others:
        if step_id in steps:
            continue
        if not from_last and step_id in pins:
            put(step_id, pins[step_id], ORIGIN_PIN)
            continue
        rec = wr.last_node_record(db, task_id, step_id) if task_id else None
        made = record_output(db, rec)
        if made is not None:
            put(step_id, made, ORIGIN_LAST_RUN, rec.status)
        elif step_id in pins:
            put(step_id, pins[step_id], ORIGIN_PIN)

    first = is_first(graph, node_id)
    given = envelope if isinstance(envelope, dict) else None
    if first:
        trigger, start_origin = given, ORIGIN_HANDED
    else:
        trigger, start_origin = None, ORIGIN_NONE
        if from_last and last_rec is not None:
            trigger = _run_trigger(db, last_rec, graph)
            start_origin = ORIGIN_LAST_RUN
        if trigger is None and not from_last:
            trigger = _pinned_start(graph)
            start_origin = ORIGIN_PIN
        if trigger is None and task_id:
            trigger = _newest_start_trigger(db, task_id, graph)
            start_origin = ORIGIN_LAST_RUN
        if trigger is None:
            start_origin = ORIGIN_NONE
    steps[start] = {"status": "success", "data": (trigger or {}).get("data") if trigger else None,
                    "text": trigger_summary(trigger) if trigger else ""}
    origin[start] = start_origin if trigger is not None else ORIGIN_NONE

    parent = None if first else parent_of(graph, node_id)
    if parent is not None and given is not None and given.get("source") == TRIGGER_SOURCE_TASK:
        handed = given.get("data") if isinstance(given.get("data"), dict) else {}
        put(parent, {"text": handed.get("result") or "", "data": handed.get("data")}, ORIGIN_HANDED,
            handed.get("status") or "success")

    for step_id, made in outputs.items():
        if step_id == start:
            steps[start] = {"status": "success", "data": made.get("data"),
                            "text": made.get("text") or steps[start].get("text") or ""}
            origin[start] = ORIGIN_TYPED
        else:
            put(step_id, made, ORIGIN_TYPED)

    ctx = {"steps": json.loads(json.dumps(steps, default=str))}
    reads = []
    for step_id in referenced_steps(node):
        entry = ctx["steps"].get(step_id)
        reads.append({"node_id": step_id, "label": _label(graph, step_id),
                      "origin": origin.get(step_id, ORIGIN_NONE) if entry else ORIGIN_NONE,
                      "data": entry.get("data") if entry else None,
                      "text": entry.get("text") if entry else ""})
    return ctx, reads


__all__ = [
    "ORIGIN_TYPED", "ORIGIN_HANDED", "ORIGIN_PIN", "ORIGIN_LAST_RUN", "ORIGIN_NONE", "ORIGINS",
    "OutputsRefused", "check_outputs", "handoff_from", "parent_of", "is_first",
    "referenced_steps", "record_output", "build",
]
