# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Apollo knows about the person: lines in Brain, stated or inferred.

The outline: *rules you state go into Brain as you said them, and facts it
notices go in marked inferred until you confirm.* Brain already has the two
states this needs (`src.memory_edges`): `committed` is a line the person
stated or confirmed, `proposed` is one Apollo inferred and has not had
confirmed. The evidence behind an inference is the record's provenance quote,
and its date is the record's timestamp, so the "What Apollo knows about you"
page is a view of Brain, never a second store.

An inferred line informs a question or an offer; it never changes what Apollo
does until the person confirms it (`frame` says so to the model, and only
`confirm` here moves it). Forget means delete.

Brain is one file filtered by owner (`src/memory.py`); every function here
reads and writes only the owner's own lines, and nothing here ever calls
`claim_ownerless`.

Spaces (phase 3). A line carries the space it was kept in (`apollo_space`,
absent for the top layer), and a reader passes the `Scope` it stands in
(`src.apollo.spaces.scope`), so it sees only the spaces that scope may read.
A line kept inside an airgap's edge is not in Brain at all: it lives in that
edge's own store beside Brain (`apollo-sealed/<space id>/memory.json`), so no
other part of Pantheon that reads Brain can reach it. `move_lines` carries a
space's lines across when its airgap is turned on or off.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from src.apollo.errors import ApolloRefused

BASES = ("stated", "inferred")
CATEGORIES = ("fact", "rule", "preference")
TEXT_MAX = 500
EVIDENCE_MAX = 300
PRODUCER = "apollo"

SPACE_KEY = "apollo_space"

_lock = threading.Lock()
_manager = None
_sealed: Dict[str, Any] = {}


def manager():
    """The Brain store. Tests set `knows._manager` to one over a temp folder."""
    global _manager
    if _manager is None:
        from src.constants import DATA_DIR
        from src.memory import MemoryManager
        _manager = MemoryManager(DATA_DIR)
    return _manager


def store(edge: Optional[str] = None):
    """Brain, or the sealed store of the airgap whose edge is `edge`."""
    if not edge:
        return manager()
    base = os.path.dirname(os.path.abspath(manager().memory_file))
    key = (base, str(edge))
    found = _sealed.get(key)
    if found is None:
        from src.memory import MemoryManager
        if not all(c.isalnum() or c == "-" for c in str(edge)):
            raise ApolloRefused("That space can't keep lines.", 400)
        folder = os.path.join(base, "apollo-sealed", str(edge))
        os.makedirs(folder, exist_ok=True)
        found = _sealed[key] = MemoryManager(folder)
    return found


def _space(entry: Dict[str, Any]) -> Optional[str]:
    return entry.get(SPACE_KEY) or None


def _in(entry: Dict[str, Any], where) -> bool:
    return where is None or _space(entry) in where.reads


def _mine(entry: Dict[str, Any], where) -> bool:
    """A line the scope may change: its own space's or a parent's, never one
    it reads through a grant."""
    return where is None or (_in(entry, where) and where.via(_space(entry)) is None)


def _clean(text: Any, limit: int, what: str) -> str:
    words = " ".join(str(text or "").split())
    if not words:
        raise ApolloRefused(f"{what} needs some words.")
    if len(words) > limit:
        raise ApolloRefused(f"{what} is a line, {limit} characters at most.")
    return words


def basis_of(entry: Dict[str, Any]) -> str:
    from src.memory_edges import STATUS_PROPOSED, status_of
    return "inferred" if status_of(entry) == STATUS_PROPOSED else "stated"


def _visible(entry: Dict[str, Any], owner: str) -> bool:
    from src.memory_edges import STATUS_ARCHIVED, status_of
    if not isinstance(entry, dict) or entry.get("owner") != owner:
        return False
    if status_of(entry) == STATUS_ARCHIVED:
        return False
    return (entry.get("kind") or "memory") == "memory"


def to_line(entry: Dict[str, Any], where=None) -> Dict[str, Any]:
    prov = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    sid = _space(entry)
    line = {"id": entry.get("id"), "text": entry.get("text"), "basis": basis_of(entry),
            "category": entry.get("category") or "fact",
            "evidence": prov.get("quote") or None,
            "since": int(entry.get("timestamp") or 0),
            "by_apollo": prov.get("producer") == PRODUCER,
            "space_id": sid}
    if where is not None:
        line["space"] = where.names.get(sid, "Apollo")
        g = where.via(sid)
        line["via_grant"] = g.id if g is not None else None
    return line


def remember(owner: str, text: Any, *, basis: str = "stated", category: str = "fact",
             evidence: Any = None, where=None) -> Dict[str, Any]:
    """Write one line to Brain for `owner`. An inferred line needs its evidence:
    the thing Apollo saw, in a few words, so the person can judge the hunch."""
    from src.memory import new_provenance
    from src.memory_edges import STATUS_COMMITTED, STATUS_PROPOSED
    if not owner:
        raise ApolloRefused("Apollo remembers things for a signed-in person only.", 403)
    if basis not in BASES:
        raise ApolloRefused("A line Apollo keeps is stated or inferred.")
    if category not in CATEGORIES:
        raise ApolloRefused("A line Apollo keeps is a fact, a rule or a preference.")
    words = _clean(text, TEXT_MAX, "A line")
    quote = None
    if basis == "inferred":
        quote = _clean(evidence, EVIDENCE_MAX, "An inferred line's evidence")
    elif evidence:
        quote = _clean(evidence, EVIDENCE_MAX, "Evidence")
    space_id = where.space_id if where is not None else None
    mgr = store(where.edge if where is not None else None)
    with _lock:
        entries = mgr.load_all_for_update()
        for e in entries:
            if (_visible(e, owner) and _space(e) == space_id
                    and " ".join(str(e.get("text") or "").split()).lower() == words.lower()):
                # Already known. A stated line confirms an inferred one.
                if basis == "stated" and basis_of(e) == "inferred":
                    e["status"] = STATUS_COMMITTED
                    e["committed_at"] = int(time.time())
                    e["committed_by"] = owner
                    mgr.save(entries)
                return to_line(e, where)
        entry = mgr.add_entry(words, source="user" if basis == "stated" else "auto",
                              category=category, owner=owner,
                              confidence=None if basis == "stated" else 0.6,
                              provenance=new_provenance(PRODUCER, quote=quote),
                              status=STATUS_COMMITTED if basis == "stated" else STATUS_PROPOSED)
        if space_id:
            entry[SPACE_KEY] = space_id
        entries.append(entry)
        mgr.save(entries)
    return to_line(entry, where)


def what_apollo_knows(owner: str, where=None) -> List[Dict[str, Any]]:
    """Every line kept for `owner` that `where` may read, newest first, stated
    or inferred. With no scope: every line in Brain (none sealed)."""
    mgr = store(where.edge if where is not None else None)
    lines = [to_line(e, where) for e in mgr.load_all() if _visible(e, owner) and _in(e, where)]
    lines.sort(key=lambda line: (-line["since"], str(line["id"])))
    return lines


def _find(entries: List[Dict[str, Any]], owner: str, line_id: str, where=None) -> Dict[str, Any]:
    for e in entries:
        if _visible(e, owner) and e.get("id") == line_id:
            if not _in(e, where):
                break
            if not _mine(e, where):
                raise ApolloRefused("That line belongs to a space this one only reads, "
                                    "so change it there.", 409)
            return e
    raise ApolloRefused("Apollo doesn't have that line about you.", 404)


def confirm(owner: str, line_id: str, where=None) -> Dict[str, Any]:
    """The person says an inferred line is right: it becomes stated."""
    from src.memory_edges import STATUS_COMMITTED
    mgr = store(where.edge if where is not None else None)
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""), where)
        e["status"] = STATUS_COMMITTED
        e["committed_at"] = int(time.time())
        e["committed_by"] = owner
        mgr.save(entries)
    return to_line(e, where)


def edit(owner: str, line_id: str, text: Any, where=None) -> Dict[str, Any]:
    """The person rewrites a line. Their words make it stated."""
    from src.memory_edges import STATUS_COMMITTED
    words = _clean(text, TEXT_MAX, "A line")
    mgr = store(where.edge if where is not None else None)
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""), where)
        e["text"] = words
        e["status"] = STATUS_COMMITTED
        e["committed_at"] = int(time.time())
        e["committed_by"] = owner
        mgr.save(entries)
    return to_line(e, where)


def forget(owner: str, line_id: str, where=None) -> bool:
    """Forget means delete: the line is gone from Brain, not marked old."""
    mgr = store(where.edge if where is not None else None)
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""), where)
        entries = [x for x in entries if x is not e]
        mgr.save(entries)
    return True


def stated_rules(owner: str, limit: int = 30, where=None) -> List[str]:
    """The person's stated rules and preferences, newest first: what Apollo
    must follow. Inferred lines are left out on purpose, and so are a granted
    space's rules: a grant informs, it never binds."""
    out = [line["text"] for line in what_apollo_knows(owner, where)
           if line["basis"] == "stated" and line["category"] in ("rule", "preference")
           and not line.get("via_grant")]
    return out[:limit]


def open_hunches(owner: str, limit: int = 5, where=None) -> List[Dict[str, Any]]:
    """Inferred lines Apollo has not had confirmed, to voice as a question.
    Only its own space's and its parents': a granted space's hunches are that
    space's to ask about."""
    return [line for line in what_apollo_knows(owner, where)
            if line["basis"] == "inferred" and not line.get("via_grant")][:limit]


def lines_in(owner: str, space_id: str, edge: Optional[str]) -> int:
    """How many lines are kept in `space_id`."""
    return sum(1 for e in store(edge).load_all() if _visible(e, owner) and _space(e) == space_id)


def move_lines(owner: str, space_id: str, from_edge: Optional[str], to_edge: Optional[str]) -> int:
    """Carry `space_id`'s lines from one store to another, when an airgap at or
    above it is turned on or off. Written to the new store before they leave
    the old one, so a failure leaves a copy, never a loss."""
    if (from_edge or None) == (to_edge or None):
        return 0
    src, dst = store(from_edge), store(to_edge)
    with _lock:
        have = src.load_all_for_update()
        going = [e for e in have if isinstance(e, dict) and e.get("owner") == owner
                 and _space(e) == space_id]
        if not going:
            return 0
        there = dst.load_all_for_update()
        ids = {e.get("id") for e in there if isinstance(e, dict)}
        there.extend(e for e in going if e.get("id") not in ids)
        dst.save(there)
        src.save([e for e in have if not any(e is g for g in going)])
    return len(going)
