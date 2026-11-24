# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spaces: a person's layered areas of work and life, enforced on the server.

The outline (*Spaces: layered chats and projects*, settled calls 11-13).
Apollo's main chat is the top layer; under it a person makes spaces (Market
Sniper, CyberKnox, Home), and a space can hold sub-spaces (CyberKnox > SBIR).
Each holds its own tasks, notebook, memory lines and Apollo chat.

How context moves, and where each rule lives:

  * **Own scope.** A task, a note and a line Apollo keeps carry the space they
    were made in (`space_id`, NULL for the top layer), and every read is
    filtered on owner *and* space.
  * **Layers.** A space reads its parents' context, up to the top layer. A
    parent sees a summary of its children (`children`), never their contents.
  * **Grants.** One space may be given read of another, one way, scoped to
    `memory` (Apollo's lines and notebook) or `outcomes` (what its finished
    tasks came to). A grant never lets the reader change anything; every use
    is logged (`log_use`) and a grant is revoked in one call.
  * **Airgap.** An airgapped space shares nothing in or out: it reads no parent
    and no grant, nothing reads it, and the person's stated rules don't reach
    it. Its sub-spaces live inside its edge with it. Apollo's lines from inside
    an edge are kept in a store of their own (`knows`), so no other part of
    Pantheon that reads Brain can see them. An airgapped space may also be
    pinned to local models (`local_only`), and nothing in it then runs on a
    paid API (`require_local`).

`scope()` is the one answer every reader asks: for a space and a kind of
content, which spaces it may read and through which grants. It is a server
rule, not a prompt, so it holds whatever model is running.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.apollo.errors import ApolloRefused

TOP = None                      # the top layer: Apollo's main chat
ALL = "all"                     # every space but the sealed ones
SCOPES = ("memory", "outcomes")
NAME_MAX = 60
DEPTH_MAX = 4
NOT_YOURS = "That space isn't one of yours."
LOCAL_ONLY = ("“{name}” keeps to local models, so nothing in it leaves this server. "
              "Switch to a local model to go on there.")


@dataclass
class Scope:
    """What one space may read of one kind of content.

    `space_id` is where the reader stands (None is the top layer), `edge` the
    airgapped space whose edge it is inside (None when it is in the open),
    `reads` every space it may read (itself first), and `grants` the grants
    that let it read the rest, as `(grant, source_id)`."""
    space_id: Optional[str]
    edge: Optional[str] = None
    local_only: bool = False
    reads: List[Optional[str]] = field(default_factory=list)
    grants: List[Tuple[Any, str]] = field(default_factory=list)
    names: Dict[Optional[str], str] = field(default_factory=dict)

    def via(self, space_id: Optional[str]):
        """The grant this scope reads `space_id` through, or None."""
        for g, src in self.grants:
            if src == space_id:
                return g
        return None


def _model():
    from core.database import ApolloSpace
    return ApolloSpace


def _all(db, owner: str) -> Dict[str, Any]:
    S = _model()
    return {s.id: s for s in db.query(S).filter(S.owner == owner).all()}


def get(db, owner: str, space_id: Any):
    S = _model()
    row = db.query(S).filter(S.id == str(space_id or ""), S.owner == owner).first()
    if row is None:
        raise ApolloRefused(NOT_YOURS, 404)
    return row


def resolve(db, owner: str, value: Any) -> Optional[str]:
    """A space named by a caller: None for the top layer (`None`, '', 'top'),
    else the id of one of the owner's own spaces."""
    if value in (None, "", "top"):
        return TOP
    return get(db, owner, value).id


def _chain(spaces: Dict[str, Any], space_id: Optional[str]) -> List[Any]:
    """The space and its parents, nearest first."""
    out, seen = [], set()
    at = spaces.get(space_id) if space_id else None
    while at is not None and at.id not in seen:
        out.append(at)
        seen.add(at.id)
        at = spaces.get(at.parent_id) if at.parent_id else None
    return out


def edge_of(spaces: Dict[str, Any], space_id: Optional[str]) -> Optional[str]:
    """The nearest airgapped space at or above `space_id`, or None."""
    for s in _chain(spaces, space_id):
        if s.airgapped:
            return s.id
    return None


def sealed_ids(db, owner: str) -> List[str]:
    """Every space inside an airgap's edge."""
    spaces = _all(db, owner)
    return [sid for sid in spaces if edge_of(spaces, sid)]


def _live_grants(db, owner: str, reader_id: str, scope: str) -> List[Any]:
    from core.database import ApolloGrant as G
    return (db.query(G)
            .filter(G.owner == owner, G.reader_id == reader_id, G.scope == scope,
                    G.revoked_at.is_(None))
            .order_by(G.created_at).all())


def scope(db, owner: str, space_id: Optional[str], kind: str = "memory") -> Scope:
    """What the space `space_id` may read of `kind`: itself, its parents up to
    an airgap's edge (or the top layer), and, in the open only, its grants."""
    spaces = _all(db, owner)
    if space_id is not None and space_id not in spaces:
        raise ApolloRefused(NOT_YOURS, 404)
    names = {TOP: "Apollo"}
    names.update({sid: s.name for sid, s in spaces.items()})
    edge = edge_of(spaces, space_id)
    reads: List[Optional[str]] = []
    for s in _chain(spaces, space_id):
        reads.append(s.id)
        if s.airgapped:
            break
    if edge is None:
        reads.append(TOP)
    if space_id is None:
        reads = [TOP]
    grants: List[Tuple[Any, str]] = []
    if edge is None and space_id is not None:
        for g in _live_grants(db, owner, space_id, kind):
            if g.source_id in spaces and edge_of(spaces, g.source_id) is None and g.source_id not in reads:
                grants.append((g, g.source_id))
                reads.append(g.source_id)
    local_only = bool(edge and spaces[edge].local_only)
    return Scope(space_id=space_id, edge=edge, local_only=local_only, reads=reads,
                 grants=grants, names=names)


def log_use(db, owner: str, grant: Any, what: str) -> None:
    """Record one read through `grant`, in a few words."""
    from core.database import ApolloGrantUse
    db.add(ApolloGrantUse(id=str(uuid.uuid4()), owner=owner, grant_id=grant.id,
                          what=" ".join(str(what or "").split())[:200] or "read"))
    db.flush()


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ApolloRefused("A space needs a name.")
    if len(name) > NAME_MAX:
        raise ApolloRefused(f"A space's name is {NAME_MAX} characters at most.")
    return name


def create(db, owner: str, name: Any, *, parent_id: Any = None, airgapped: bool = False,
           local_only: bool = False):
    """A new space under `parent_id` (or the top layer). A name is unique
    among its siblings; spaces nest four deep at most."""
    S = _model()
    if not owner:
        raise ApolloRefused("Spaces belong to a signed-in person.", 403)
    name = _clean_name(name)
    spaces = _all(db, owner)
    parent = get(db, owner, parent_id) if parent_id not in (None, "", "top") else None
    if parent is not None and len(_chain(spaces, parent.id)) >= DEPTH_MAX:
        raise ApolloRefused(f"Spaces nest {DEPTH_MAX} deep at most.")
    _unique(spaces, owner, name, parent.id if parent else None)
    if local_only and not airgapped:
        raise ApolloRefused("Only an airgapped space can be pinned to local models.")
    row = S(id=str(uuid.uuid4()), owner=owner, parent_id=parent.id if parent else None,
            name=name, airgapped=bool(airgapped), local_only=bool(local_only))
    db.add(row)
    db.flush()
    return row


def _unique(spaces: Dict[str, Any], owner: str, name: str, parent_id: Optional[str], *, but=None):
    for s in spaces.values():
        if s.id != but and s.parent_id == parent_id and s.name.lower() == name.lower():
            raise ApolloRefused(f"There's already a space called “{name}” there.", 409)


def rename(db, owner: str, space_id: Any, name: Any):
    row = get(db, owner, space_id)
    name = _clean_name(name)
    _unique(_all(db, owner), owner, name, row.parent_id, but=row.id)
    row.name = name
    db.flush()
    return row


def subtree(spaces: Dict[str, Any], space_id: str) -> List[str]:
    """`space_id` and every space under it."""
    out, todo = [], [space_id]
    while todo:
        at = todo.pop()
        out.append(at)
        todo.extend(s.id for s in spaces.values() if s.parent_id == at)
    return out


def set_airgap(db, owner: str, space_id: Any, on: bool, *, move_lines=None) -> Any:
    """Turn a space's airgap on or off.

    On: every grant into or out of it (and its sub-spaces) is revoked, and
    Apollo's lines there move into the edge's own store. Off: its lines move
    back to Brain, still kept to the space; revoked grants stay revoked, and
    the local-models pin comes off with the airgap."""
    from core.database import ApolloGrant as G, utcnow_naive
    row = get(db, owner, space_id)
    spaces = _all(db, owner)
    inside = subtree(spaces, row.id)
    before = {sid: edge_of(spaces, sid) for sid in inside}
    row.airgapped = bool(on)
    if not row.airgapped:
        row.local_only = False
    db.flush()
    after = {sid: edge_of(spaces, sid) for sid in inside}
    if row.airgapped:
        for g in (db.query(G).filter(G.owner == owner, G.revoked_at.is_(None))
                  .filter((G.reader_id.in_(inside)) | (G.source_id.in_(inside))).all()):
            g.revoked_at = utcnow_naive()
        db.flush()
    if move_lines is None:
        from src.apollo import knows
        move_lines = knows.move_lines
    for sid in inside:
        if before[sid] != after[sid]:
            move_lines(owner, sid, before[sid], after[sid])
    return row


def set_local_only(db, owner: str, space_id: Any, on: bool):
    row = get(db, owner, space_id)
    if on and not row.airgapped:
        raise ApolloRefused("Only an airgapped space can be pinned to local models.")
    row.local_only = bool(on)
    db.flush()
    return row


def remove(db, owner: str, space_id: Any) -> None:
    """Delete an empty space: no sub-spaces, tasks, notes or lines in it.
    Its grants go with it."""
    from core.database import ApolloGrant as G, ApolloNote, ApolloTask
    row = get(db, owner, space_id)
    spaces = _all(db, owner)
    if any(s.parent_id == row.id for s in spaces.values()):
        raise ApolloRefused("Move or delete the spaces inside it first.", 409)
    if db.query(ApolloTask).filter(ApolloTask.owner == owner, ApolloTask.space_id == row.id).first():
        raise ApolloRefused("It still holds tasks. Finish or move them first.", 409)
    if db.query(ApolloNote).filter(ApolloNote.owner == owner, ApolloNote.space_id == row.id).first():
        raise ApolloRefused("It still holds notes. Settle or move them first.", 409)
    from src.apollo import knows
    if knows.lines_in(owner, row.id, edge_of(spaces, row.id)):
        raise ApolloRefused("Apollo still keeps lines there. Forget them first.", 409)
    db.query(G).filter(G.owner == owner, (G.reader_id == row.id) | (G.source_id == row.id)).delete(
        synchronize_session=False)
    db.delete(row)
    db.flush()


def grant(db, owner: str, reader_id: Any, source_id: Any, kind: Any):
    """Give `reader_id` read of `source_id`'s `kind`. One way, read only, and
    never into or out of an airgap."""
    from core.database import ApolloGrant as G
    if kind not in SCOPES:
        raise ApolloRefused("A grant reads memory or outcomes.")
    reader = get(db, owner, reader_id)
    source = get(db, owner, source_id)
    if reader.id == source.id:
        raise ApolloRefused("A space already reads itself.")
    spaces = _all(db, owner)
    if edge_of(spaces, reader.id) or edge_of(spaces, source.id):
        raise ApolloRefused("An airgapped space shares nothing in or out, so it takes no grants.", 409)
    if source.id in [s.id for s in _chain(spaces, reader.id)]:
        raise ApolloRefused(f"“{reader.name}” already reads “{source.name}”, which is above it.")
    for g in _live_grants(db, owner, reader.id, kind):
        if g.source_id == source.id:
            return g
    row = G(id=str(uuid.uuid4()), owner=owner, reader_id=reader.id, source_id=source.id,
            scope=kind)
    db.add(row)
    db.flush()
    return row


def revoke(db, owner: str, grant_id: Any):
    from core.database import ApolloGrant as G, utcnow_naive
    row = db.query(G).filter(G.id == str(grant_id or ""), G.owner == owner).first()
    if row is None:
        raise ApolloRefused("That grant isn't one of yours.", 404)
    if row.revoked_at is None:
        row.revoked_at = utcnow_naive()
        db.flush()
    return row


def children(db, owner: str, space_id: Optional[str]) -> List[Dict[str, Any]]:
    """What a parent sees of its children: counts, never contents. An
    airgapped child shows only whether something there needs the person."""
    from core.database import ApolloTask
    spaces = _all(db, owner)
    kids = sorted((s for s in spaces.values() if s.parent_id == space_id), key=lambda s: s.name.lower())
    out = []
    for k in kids:
        ids = subtree(spaces, k.id)
        rows = (db.query(ApolloTask.state)
                .filter(ApolloTask.owner == owner, ApolloTask.space_id.in_(ids),
                        ApolloTask.state != "done").all())
        needs = sum(1 for (st,) in rows if st == "needs_you")
        if edge_of(spaces, k.id) and not edge_of(spaces, space_id):
            out.append({"id": k.id, "name": k.name, "sealed": True, "needs_you": needs > 0})
        else:
            out.append({"id": k.id, "name": k.name, "sealed": False,
                        "open": len(rows), "needs_you": needs})
    return out


def to_dict(row, spaces: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "parent_id": row.parent_id,
            "depth": len(_chain(spaces, row.id)) - 1,
            "airgapped": bool(row.airgapped), "local_only": bool(row.local_only),
            "sealed": bool(edge_of(spaces, row.id)), "session_id": row.session_id,
            "path": " › ".join(s.name for s in reversed(_chain(spaces, row.id)))}


def tree(db, owner: str) -> List[Dict[str, Any]]:
    """Every space, parents before children, siblings by name."""
    spaces = _all(db, owner)
    out: List[Dict[str, Any]] = []

    def walk(parent: Optional[str]):
        for s in sorted((x for x in spaces.values() if x.parent_id == parent), key=lambda x: x.name.lower()):
            out.append(to_dict(s, spaces))
            walk(s.id)
    walk(None)
    return out


def context(db, owner: str, space_id: Any) -> Dict[str, Any]:
    """The space's Context list: what it reads from, what reads from it, and
    the last uses of its grants."""
    from core.database import ApolloGrant as G, ApolloGrantUse as U
    row = get(db, owner, space_id)
    spaces = _all(db, owner)
    reads_from: List[Dict[str, Any]] = []
    sc = scope(db, owner, row.id, "memory")
    for sid in sc.reads[1:]:
        if sc.via(sid) is None:
            reads_from.append({"space_id": sid, "name": sc.names.get(sid, "Apollo"), "how": "above"})
    live = (db.query(G).filter(G.owner == owner, G.revoked_at.is_(None),
                               (G.reader_id == row.id) | (G.source_id == row.id))
            .order_by(G.created_at).all())
    sealed = bool(edge_of(spaces, row.id))
    read_by: List[Dict[str, Any]] = []
    for g in live:
        if sealed:
            continue
        item = {"grant_id": g.id, "scope": g.scope}
        if g.reader_id == row.id and g.source_id in spaces:
            reads_from.append({**item, "space_id": g.source_id, "name": spaces[g.source_id].name, "how": "grant"})
        elif g.source_id == row.id and g.reader_id in spaces:
            read_by.append({**item, "space_id": g.reader_id, "name": spaces[g.reader_id].name, "how": "grant"})
    for k in children(db, owner, row.id):
        if not k["sealed"]:
            read_by.append({"space_id": k["id"], "name": k["name"], "how": "below"})
    ids = [g.id for g in live]
    uses = []
    if ids:
        for u in (db.query(U).filter(U.owner == owner, U.grant_id.in_(ids))
                  .order_by(U.used_at.desc()).limit(10).all()):
            uses.append({"grant_id": u.grant_id, "what": u.what,
                         "at": u.used_at.isoformat() + "Z" if u.used_at else None})
    return {"space": to_dict(row, spaces), "reads_from": reads_from, "read_by": read_by,
            "children": children(db, owner, row.id), "uses": uses}


# -- chats ------------------------------------------------------------------

def chat_for(db, owner: str, space_id: Optional[str]) -> str:
    """The Apollo chat of a space, made the first time it's asked for; the top
    layer's is Apollo's own chat."""
    from core.database import CrewMember, Session as DbSession, utcnow_naive
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner, CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    if space_id is None:
        if crew is None or not crew.session_id:
            raise ApolloRefused("Your Apollo chat isn't set up yet. Open Apollo once first.", 409)
        return crew.session_id
    row = get(db, owner, space_id)
    if row.session_id and db.query(DbSession.id).filter(DbSession.id == row.session_id,
                                                         DbSession.owner == owner).first():
        return row.session_id
    base = None
    if crew is not None and crew.session_id:
        base = db.query(DbSession).filter(DbSession.id == crew.session_id).first()
    now = utcnow_naive()
    sid = str(uuid.uuid4())
    sess = DbSession(id=sid, name=f"{(crew.name if crew else None) or 'Apollo'} · {row.name}",
                     endpoint_url=(base.endpoint_url if base else "") or "",
                     model=(base.model if base else "") or "",
                     owner=owner, mode="agent", folder="Apollo",
                     created_at=now, updated_at=now)
    if crew is not None:
        sess.crew_member_id = crew.id
    db.add(sess)
    row.session_id = sid
    db.flush()
    return sid


def space_of_session(db, owner: Optional[str], session_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """`(True, space_id)` when `session_id` is one of `owner`'s Apollo chats
    (space_id None for the top layer); `(False, None)` otherwise."""
    if not owner or not session_id:
        return False, None
    from core.database import CrewMember
    S = _model()
    if (db.query(CrewMember.id)
            .filter(CrewMember.owner == owner, CrewMember.is_default_assistant == True,  # noqa: E712
                    CrewMember.session_id == session_id).first()):
        return True, None
    row = db.query(S).filter(S.owner == owner, S.session_id == session_id).first()
    if row is not None:
        return True, row.id
    return False, None


def local_only_for_session(db, owner: Optional[str], session_id: Optional[str]) -> Optional[str]:
    """The name of the local-only space `session_id` works in (its Apollo chat,
    or the chat of one of its tasks), or None when nothing pins it."""
    if not owner or not session_id:
        return None
    spaces = _all(db, owner)
    if not any(s.local_only for s in spaces.values()):
        return None
    ok, sid = space_of_session(db, owner, session_id)
    if not ok:
        from core.database import ApolloTask
        t = (db.query(ApolloTask)
             .filter(ApolloTask.owner == owner, ApolloTask.session_id == session_id).first())
        sid = t.space_id if t is not None else None
    return _local_only_name(spaces, sid)


def local_only_for_space(db, owner: Optional[str], space_id: Optional[str]) -> Optional[str]:
    """The name of the local-only space `space_id` sits in (itself or the
    edge above it), or None. `B2241`: the reasoning cache asks it for an
    Apollo goal run, which has a space and no chat of its own."""
    if not owner or not space_id:
        return None
    return _local_only_name(_all(db, owner), space_id)


def _local_only_name(spaces: Dict[str, Any], space_id: Optional[str]) -> Optional[str]:
    edge = edge_of(spaces, space_id)
    if edge and spaces[edge].local_only:
        return spaces[edge].name
    return None


def require_local(name: Optional[str], endpoint_url: Optional[str]) -> None:
    """Refuse a paid model inside a local-only space."""
    if not name:
        return
    from src.apollo import budget as B
    if B.billed(endpoint_url):
        raise ApolloRefused(LOCAL_ONLY.format(name=name), 409)
