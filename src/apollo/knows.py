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
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from src.apollo.errors import ApolloRefused

BASES = ("stated", "inferred")
CATEGORIES = ("fact", "rule", "preference")
TEXT_MAX = 500
EVIDENCE_MAX = 300
PRODUCER = "apollo"

_lock = threading.Lock()
_manager = None


def manager():
    """The Brain store. Tests set `knows._manager` to one over a temp folder."""
    global _manager
    if _manager is None:
        from src.constants import DATA_DIR
        from src.memory import MemoryManager
        _manager = MemoryManager(DATA_DIR)
    return _manager


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


def to_line(entry: Dict[str, Any]) -> Dict[str, Any]:
    prov = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    return {"id": entry.get("id"), "text": entry.get("text"), "basis": basis_of(entry),
            "category": entry.get("category") or "fact",
            "evidence": prov.get("quote") or None,
            "since": int(entry.get("timestamp") or 0),
            "by_apollo": prov.get("producer") == PRODUCER}


def remember(owner: str, text: Any, *, basis: str = "stated", category: str = "fact",
             evidence: Any = None) -> Dict[str, Any]:
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
    mgr = manager()
    with _lock:
        entries = mgr.load_all_for_update()
        for e in entries:
            if _visible(e, owner) and " ".join(str(e.get("text") or "").split()).lower() == words.lower():
                # Already known. A stated line confirms an inferred one.
                if basis == "stated" and basis_of(e) == "inferred":
                    e["status"] = STATUS_COMMITTED
                    e["committed_at"] = int(time.time())
                    e["committed_by"] = owner
                    mgr.save(entries)
                return to_line(e)
        entry = mgr.add_entry(words, source="user" if basis == "stated" else "auto",
                              category=category, owner=owner,
                              confidence=None if basis == "stated" else 0.6,
                              provenance=new_provenance(PRODUCER, quote=quote),
                              status=STATUS_COMMITTED if basis == "stated" else STATUS_PROPOSED)
        entries.append(entry)
        mgr.save(entries)
    return to_line(entry)


def what_apollo_knows(owner: str) -> List[Dict[str, Any]]:
    """Every line Brain holds for `owner`, newest first, stated or inferred."""
    lines = [to_line(e) for e in manager().load_all() if _visible(e, owner)]
    lines.sort(key=lambda line: (-line["since"], str(line["id"])))
    return lines


def _find(entries: List[Dict[str, Any]], owner: str, line_id: str) -> Dict[str, Any]:
    for e in entries:
        if _visible(e, owner) and e.get("id") == line_id:
            return e
    raise ApolloRefused("Apollo doesn't have that line about you.", 404)


def confirm(owner: str, line_id: str) -> Dict[str, Any]:
    """The person says an inferred line is right: it becomes stated."""
    from src.memory_edges import STATUS_COMMITTED
    mgr = manager()
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""))
        e["status"] = STATUS_COMMITTED
        e["committed_at"] = int(time.time())
        e["committed_by"] = owner
        mgr.save(entries)
    return to_line(e)


def edit(owner: str, line_id: str, text: Any) -> Dict[str, Any]:
    """The person rewrites a line. Their words make it stated."""
    from src.memory_edges import STATUS_COMMITTED
    words = _clean(text, TEXT_MAX, "A line")
    mgr = manager()
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""))
        e["text"] = words
        e["status"] = STATUS_COMMITTED
        e["committed_at"] = int(time.time())
        e["committed_by"] = owner
        mgr.save(entries)
    return to_line(e)


def forget(owner: str, line_id: str) -> bool:
    """Forget means delete: the line is gone from Brain, not marked old."""
    mgr = manager()
    with _lock:
        entries = mgr.load_all_for_update()
        e = _find(entries, owner, str(line_id or ""))
        entries = [x for x in entries if x is not e]
        mgr.save(entries)
    return True


def stated_rules(owner: str, limit: int = 30) -> List[str]:
    """The person's stated rules and preferences, newest first: what Apollo
    must follow. Inferred lines are left out on purpose."""
    out = [line["text"] for line in what_apollo_knows(owner)
           if line["basis"] == "stated" and line["category"] in ("rule", "preference")]
    return out[:limit]


def open_hunches(owner: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Inferred lines Apollo has not had confirmed, to voice as a question."""
    return [line for line in what_apollo_knows(owner) if line["basis"] == "inferred"][:limit]
