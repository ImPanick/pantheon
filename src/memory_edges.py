# SPDX-License-Identifier: AGPL-3.0-or-later
"""
memory_edges.py

Typed relations between memories, and the one place their names live.

`P13-02`. The boxed decision at the top of the `P13` phase cut the graph
*visual* and kept the graph *data*: "a `supersedes` edge makes retrieval
correct whether or not anyone ever looks at it, and a recorded `contradicts` is
worth having even if it is only ever read by a query." So there is no canvas,
no force layout and no node positions anywhere in this module — an edge here
earns its place by changing what comes back from a search, which is the row's
own test.

**Why this is its own module rather than a section of `src/memory.py`.**
`src/memory.py` imports `src/memory_retrieval.py` at module scope, and
retrieval is precisely where these relations have to be honoured, so the names
cannot live in either of the two files that need them. Carved out for the same
reason `src/retrieval_engine.py` was: it imports nothing from the project, so a
label describing a relation never depends on the subsystem that stores it.

**`P13-05` added the second reason a memory does not surface, and it is here
rather than in a module of its own.** `live()` below is already documented as
the one place that decides what retrieval, the audit and the boot-time index
rebuild are allowed to see — *"records kept on purpose that must not be shown,
re-audited, re-indexed or counted"* — and a memory nobody has committed yet is
exactly that. Two predicates for "does this memory surface" is how a proposal
ends up hidden from search and sent to a model anyway, which is the failure
`superseded_ids` already exists to prevent. So the module is wider than its name
by one concept, and saying so here is cheaper than a rename that would touch
four call sites to move two constants (`Law 2`).
"""

from __future__ import annotations

import time
from typing import Dict, List

# A supersedes B: B is stale and stops surfacing. Directional. This is what the
# audit writes instead of deleting the entry it merged away.
EDGE_SUPERSEDES = "supersedes"

# A contradicts B: both are live and they disagree. Symmetric, and stored ONCE
# — retrieval reads it from either end (`Law 7`: two copies of one fact go
# stale separately, and an edge that disagrees with its own mirror is worse
# than no edge).
EDGE_CONTRADICTS = "contradicts"

# A derived_from B: A was computed or rewritten out of B. Directional. B is not
# stale — it is just redundant in the same answer as A.
EDGE_DERIVED_FROM = "derived_from"

# A co_occurs B: these two are relevant together. Symmetric.
EDGE_CO_OCCURS = "co_occurs"

EDGE_TYPES = (EDGE_SUPERSEDES, EDGE_CONTRADICTS, EDGE_DERIVED_FROM, EDGE_CO_OCCURS)

# Stored once and read from both ends. The asymmetric two are not in here
# because their direction is their meaning.
SYMMETRIC_EDGE_TYPES = (EDGE_CONTRADICTS, EDGE_CO_OCCURS)


# ── commitment, `P13-05` ──────────────────────────────────────────────────────

# The memory binds: it is retrieved, audited, indexed and counted. This is the
# default and the honest reading of every record written before the row —
# they ARE binding, because they are being injected into prompts today.
STATUS_COMMITTED = "committed"

# Extraction proposed it and nobody has agreed yet. On the record, visible,
# gathering mentions, and invisible to everything that feeds a model. The
# phase preamble's argument for this state is a competitor's "Avoid" list with
# raw venting promoted to a rule at 95%: extraction and commitment were one
# event, so there was nothing between a sentence and a policy.
STATUS_PROPOSED = "proposed"

MEMORY_STATUSES = (STATUS_COMMITTED, STATUS_PROPOSED)


def status_of(memory) -> str:
    """One of `MEMORY_STATUSES`, and `STATUS_COMMITTED` for anything else.

    **Unrecognised reads as committed, and the direction of that default is the
    decision.** A memory store is a file a person can edit, so a typo in this
    field is reachable — and the failure mode of the other direction is that
    memories silently stop reaching the model, which is the least visible bug
    this product can have (`P0-05` shipped looking done for exactly that
    reason). A record that binds when it should not is wrong and obvious; a
    record that stops binding is wrong and invisible.
    """
    if not isinstance(memory, dict):
        return STATUS_COMMITTED
    value = memory.get("status")
    return value if value in MEMORY_STATUSES else STATUS_COMMITTED


def is_committed(memory) -> bool:
    """Whether this memory is allowed to change an answer. `P13-05`."""
    return status_of(memory) == STATUS_COMMITTED


def edges_of(memory) -> List[Dict]:
    """The well-formed edges on one record. Junk is skipped, never raised on.

    A memory store is a file a person can edit, so this is parsing, not
    validation of our own output.
    """
    if not isinstance(memory, dict):
        return []
    rows = memory.get("edges")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("type") not in EDGE_TYPES:
            continue
        target = row.get("target")
        if not target or not isinstance(target, str):
            continue
        out.append(row)
    return out


def build_edge_index(memories) -> Dict[str, Dict]:
    """The graph, read once per query rather than per memory.

    Returns `{"superseded": set, "contradicts": {id: set}, "co_occurs":
    {id: set}, "derived_from": {derived_id: set(source_ids)}}`.

    **Edges pointing at ids that are not in `memories` are dropped**, and that
    is deliberate rather than defensive: an edge to a memory that has been
    deleted is not a relation any more, and honouring a `supersedes` edge whose
    target is gone would suppress nothing while looking like it did something.
    The one exception is `superseded`, which is a set of ids to *exclude* — an
    id that is not present cannot be excluded twice, so membership is harmless.
    """
    known = {m.get("id") for m in memories if isinstance(m, dict) and m.get("id")}
    index = {
        "superseded": set(),
        EDGE_CONTRADICTS: {},
        EDGE_CO_OCCURS: {},
        EDGE_DERIVED_FROM: {},
    }
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        mid = memory.get("id")
        if not mid:
            continue
        for edge in edges_of(memory):
            target = edge["target"]
            if target == mid or target not in known:
                # A self-edge is not a relation, and a dangling one is a
                # relation to something that no longer exists.
                continue
            kind = edge["type"]
            if kind == EDGE_SUPERSEDES:
                index["superseded"].add(target)
            elif kind == EDGE_DERIVED_FROM:
                index[EDGE_DERIVED_FROM].setdefault(mid, set()).add(target)
            else:
                # Symmetric: filled from both ends off one stored row.
                index[kind].setdefault(mid, set()).add(target)
                index[kind].setdefault(target, set()).add(mid)
    return index


def new_edge(edge_type: str, target_id: str, note: str = None) -> Dict:
    """One stored edge row. Constructed here so the shape has one author.

    `at` is when the relation was recorded, not when either memory was — the
    audit that notices a contradiction in March is evidence dated March about
    two facts from January, and collapsing those two dates loses the only thing
    that says how fresh the *judgement* is.
    """
    edge = {"type": edge_type, "target": target_id, "at": int(time.time())}
    if note:
        edge["note"] = str(note)[:200]
    return edge


def superseded_ids(memories) -> set:
    """Ids that some live memory says it supersedes.

    One source of truth for "this memory has been replaced", read by the
    scorer (which must not rank them) and by the audit (which must not
    re-examine them). Two independent definitions of *stale* is how a memory
    disappears from search and keeps being sent to a model anyway.
    """
    return set(build_edge_index(memories)["superseded"])


def live(memories, index: Dict = None) -> List[Dict]:
    """The memories that still surface. One predicate, four callers.

    Two reasons a record stays in the store and out of every prompt, and they
    arrived a row apart:

    * `P13-09` archives rather than deletes what an audit merged away, so the
      store holds entries that are kept on purpose and must not be shown,
      re-audited, re-indexed or counted;
    * `P13-05` lets extraction propose without binding, so the store holds
      entries nobody has agreed to yet.

    Both are here because the alternative is two predicates that disagree, and
    the way that fails is a memory hidden from search and sent to a model
    anyway. It is also why `src/app_initializer.py` — which rebuilds the vector
    index from the whole store at boot — needed no change for either row.

    `index` is an already-built edge index, passed by a caller that has one so
    the graph is not walked twice for one query. The **unconditional** filter
    matters as much as the sharing: the caller in `_rank` used to skip this
    entirely when nothing was superseded, which on a corpus with no edges at
    all — which is almost every corpus — would have let a proposal through.
    """
    stale = set((index or build_edge_index(memories))["superseded"])
    return [m for m in memories
            if is_committed(m) and not (isinstance(m, dict) and m.get("id") in stale)]


def attach(entry: Dict, edge_type: str, target_id: str, by_id: Dict,
           note: str = None) -> bool:
    """Record one relation on `entry`. Returns whether anything was written.

    **The only writer of edges in the tree**, deliberately. It works on dicts
    already in hand rather than loading and saving, because its one producer —
    the memory audit — is mid-rewrite of the whole store when it calls this,
    and a method that did its own read-modify-write would either save twice or
    save a view of the store that was already stale. A future caller that holds
    no entries wraps this in a load and a save; it does not grow a second
    version of the checks below (`Law 14`).

    Refused, silently and on purpose, because none of these is a relation:

    * an unknown `edge_type` — a typo must not become a fifth kind of edge;
    * a self-edge;
    * a target that is not in `by_id`. An edge to a memory that does not exist
      is the `≈1.0 edges per node` starburst the `P13` preamble is about: it
      looks like structure and points at nothing.

    Idempotent, including across the mirror of a symmetric type: after
    `attach(a, "contradicts", b)`, calling `attach(b, "contradicts", a)`
    writes nothing, because one relation stored twice is two records of one
    fact and the day an edit reaches one of them they disagree (`Law 7`).
    """
    if edge_type not in EDGE_TYPES:
        return False
    if not isinstance(entry, dict) or not target_id:
        return False
    source_id = entry.get("id")
    if not source_id or source_id == target_id or target_id not in (by_id or {}):
        return False
    rows = entry.get("edges")
    if not isinstance(rows, list):
        rows = []
        entry["edges"] = rows
    for row in edges_of(entry):
        if row["type"] == edge_type and row["target"] == target_id:
            return False
    if edge_type in SYMMETRIC_EDGE_TYPES:
        for row in edges_of(by_id[target_id]):
            if row["type"] == edge_type and row["target"] == source_id:
                return False
    rows.append(new_edge(edge_type, target_id, note))
    return True
