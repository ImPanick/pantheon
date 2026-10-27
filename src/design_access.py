# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-09` · Who may look at, comment on, or change a design or a design
system — checked in this one place.

The owner (2026-10-24): *"These designs are to be user scoped, and may invite
other users as collaborators."* A design (files in its owner's project) or a
design system (`DesignSystem`) is its owner's. The owner invites another
account **by name** as:

* **viewer** — sees it, its versions, its notes, who has it open;
* **commenter** — and adds notes. A note is a note: it changes no file;
* **editor** — and changes it as the owner does: adjust, tweak, keep a
  version, step back, keep a variant; a design system's name and tokens.

Only the owner shares, changes a share or revokes it, makes a design, removes
a design system or hands a design to a branch (`P26-08`).

**The one door.** A route names a design either as the caller's own — their
project and the slug — or by a share's id, which this module finds only when
**the caller is its invitee**. There is no third spelling: a project path or a
system id that is not yours reaches your own (empty) folder or no row, never
someone else's. So a stranger's request is *not found* — 404, the same answer
as a design that does not exist — and the role is enforced here, by the
server, before the route touches a file (`Law 17`: the adversary is another
account on the install, asking with a share id or a path that is not theirs,
or a commenter whose client was told to hide a button it can still press).

**Presence** is in memory: who opened or looked at it in the last minute.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

KINDS = ("design", "system")
ROLES = ("viewer", "commenter", "editor")
RANK = {"viewer": 1, "commenter": 2, "editor": 3, "owner": 4}
SHARES_MAX = 50
NOTE_MAX = 2000
NOTES_MAX = 500
PRESENCE_S = 60
ROLE_WORDS = {"viewer": "look at it", "commenter": "comment on it", "editor": "change it", "owner": "own it"}


class AccessRefused(ValueError):
    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


@dataclass(frozen=True)
class Access:
    """What the caller may do with one design or design system, and whose
    it is — the owner's name opens the owner's project (`design_files._Fs`)."""
    kind: str
    owner: Optional[str]
    project: str
    ref: str
    role: str
    share_id: Optional[str] = None
    name: str = ""

    @property
    def mine(self) -> bool:
        return self.role == "owner"

    def key(self) -> tuple:
        return (self.kind, self.owner or "", self.project or "", self.ref)


NOT_FOUND = {"design": "There is no such design.", "system": "There is no such design system."}


def account_exists(name: str) -> bool:
    """Whether `name` is an account on this install. Its own function so the
    one lookup is the one place a test stands in for the user database."""
    try:
        from src.auth_manager_access import shared_auth_manager
        users = getattr(shared_auth_manager(), "users", {}) or {}
    except Exception:  # noqa: BLE001 — no user database is no account to share with
        return False
    return name in users


# ── the one check ───────────────────────────────────────────────────────────

def design_access(db, user: Optional[str], *, project: Any = "", slug: Any = "", share: Any = None) -> Access:
    """The caller's own design (`project`, `slug`), or a design shared with
    them by `share`'s id — or 404."""
    from core.database import DesignShare
    if share:
        row = (db.query(DesignShare)
               .filter(DesignShare.id == str(share), DesignShare.kind == "design",
                       DesignShare.invitee == (user or "")).first()) if user else None
        if row is None:
            raise AccessRefused(NOT_FOUND["design"], 404)
        return Access("design", row.owner, row.project, row.ref, row.role, row.id, row.name)
    return Access("design", user, str(project or "").strip(), str(slug or "").strip().lower(), "owner")


def system_access(db, user: Optional[str], system_id: Any) -> Access:
    """A design system that is the caller's own, or shared with them — or 404."""
    from core.database import DesignShare, DesignSystem
    from src.design_systems import account
    sid = str(system_id or "")
    row = db.query(DesignSystem).filter(DesignSystem.id == sid).first()
    if row is None:
        raise AccessRefused(NOT_FOUND["system"], 404)
    if row.account == account(user):
        return Access("system", user, "", sid, "owner", None, row.name)
    share = (db.query(DesignShare)
             .filter(DesignShare.kind == "system", DesignShare.ref == sid,
                     DesignShare.invitee == (user or "")).first()) if user else None
    if share is None:
        raise AccessRefused(NOT_FOUND["system"], 404)
    return Access("system", share.owner, "", sid, share.role, share.id, row.name)


def need(access: Access, at_least: str) -> Access:
    """`access`, if its role reaches `at_least`; otherwise a 403 that says
    what the person may do and who can change it."""
    if RANK.get(access.role, 0) >= RANK[at_least]:
        return access
    what = "design" if access.kind == "design" else "design system"
    if at_least == "owner":
        raise AccessRefused(f"Only {access.owner}, whose {what} it is, can do that.", 403)
    raise AccessRefused(f"You can {ROLE_WORDS[access.role]}, not {ROLE_WORDS[at_least]}: {access.owner} "
                        f"shared this {what} with you as a {access.role}. Ask them to make you "
                        f"{'an' if at_least == 'editor' else 'a'} {at_least}.", 403)


# ── sharing (the owner's) ───────────────────────────────────────────────────

def _clean_role(raw: Any) -> str:
    role = str(raw or "").strip().lower()
    if role not in ROLES:
        raise AccessRefused("“role” is viewer, commenter or editor.")
    return role


def share(db, user: Optional[str], access: Access, invitee: Any, role: Any) -> Dict[str, Any]:
    """Invite `invitee` by name, or change their role. The owner's only."""
    from core.database import DesignShare
    need(access, "owner")
    name = str(invitee or "").strip()
    if not name:
        raise AccessRefused("Type the name of the account to invite.")
    if name == user:
        raise AccessRefused("It is yours already.")
    if not account_exists(name):
        raise AccessRefused(f"There is no account named “{name[:60]}” on this Pantheon.", 404)
    role = _clean_role(role)
    q = db.query(DesignShare).filter(DesignShare.kind == access.kind, DesignShare.owner == user,
                                     DesignShare.project == access.project, DesignShare.ref == access.ref)
    row = q.filter(DesignShare.invitee == name).first()
    if row is None:
        if q.count() >= SHARES_MAX:
            raise AccessRefused(f"One {access.kind} is shared with at most {SHARES_MAX} accounts.")
        row = DesignShare(id=uuid.uuid4().hex, kind=access.kind, owner=user, project=access.project,
                          ref=access.ref, invitee=name)
        db.add(row)
    row.role = role
    row.name = (access.name or access.ref)[:120]
    db.commit()
    return public_share(row)


def shares_of(db, user: Optional[str], access: Access) -> List[Dict[str, Any]]:
    from core.database import DesignShare
    need(access, "owner")
    rows = (db.query(DesignShare)
            .filter(DesignShare.kind == access.kind, DesignShare.owner == user,
                    DesignShare.project == access.project, DesignShare.ref == access.ref)
            .order_by(DesignShare.invitee).all())
    return [public_share(r) for r in rows]


def revoke(db, user: Optional[str], share_id: str) -> None:
    """The owner takes a share back. Another person's share is not found."""
    from core.database import DesignShare
    row = db.query(DesignShare).filter(DesignShare.id == str(share_id), DesignShare.owner == (user or "")).first()
    if row is None or not user:
        raise AccessRefused("There is no such share of yours.", 404)
    db.delete(row)
    db.commit()


def shared_with(db, user: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """*Shared with me*: every design and design system someone shared with
    the caller, with whose it is and what the caller may do."""
    from core.database import DesignShare
    if not user:
        return {"designs": [], "systems": []}
    rows = db.query(DesignShare).filter(DesignShare.invitee == user).order_by(DesignShare.name).all()
    out: Dict[str, List[Dict[str, Any]]] = {"designs": [], "systems": []}
    for r in rows:
        out["designs" if r.kind == "design" else "systems"].append(
            {"share": r.id, "kind": r.kind, "name": r.name or r.ref, "owner": r.owner, "role": r.role,
             "slug": r.ref if r.kind == "design" else None, "system": r.ref if r.kind == "system" else None})
    return out


def public_share(row) -> Dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "invitee": row.invitee, "role": row.role, "name": row.name}


def forget_system(db, system_id: str) -> None:
    """A removed design system takes its shares and notes with it."""
    from core.database import DesignNote, DesignShare
    db.query(DesignShare).filter(DesignShare.kind == "system", DesignShare.ref == system_id).delete()
    db.query(DesignNote).filter(DesignNote.kind == "system", DesignNote.ref == system_id).delete()


# ── notes ───────────────────────────────────────────────────────────────────

def _item(q, model, access: Access):
    return q.filter(model.kind == access.kind, model.owner == (access.owner or ""),
                    model.project == access.project, model.ref == access.ref)


def notes(db, access: Access) -> List[Dict[str, Any]]:
    from core.database import DesignNote
    need(access, "viewer")
    rows = _item(db.query(DesignNote), DesignNote, access).order_by(DesignNote.created_at).all()
    return [public_note(r) for r in rows]


def add_note(db, user: Optional[str], access: Access, text: Any, selector: Any = None) -> Dict[str, Any]:
    """A note, with its author. A commenter's is a note and only a note."""
    from core.database import DesignNote
    need(access, "commenter")
    body = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    if not body:
        raise AccessRefused("Write the note first.")
    if len(body) > NOTE_MAX:
        raise AccessRefused(f"A note is at most {NOTE_MAX} characters.")
    sel = re.sub(r"\s+", " ", str(selector or "")).strip()[:300] or None
    if _item(db.query(DesignNote), DesignNote, access).count() >= NOTES_MAX:
        raise AccessRefused(f"A {access.kind} holds at most {NOTES_MAX} notes; remove some first.")
    row = DesignNote(id=uuid.uuid4().hex, kind=access.kind, owner=access.owner or "", project=access.project,
                     ref=access.ref, author=user or "", text=body, selector=sel)
    db.add(row)
    db.commit()
    return public_note(row)


def remove_note(db, user: Optional[str], note_id: str, access: Access) -> None:
    """Its author removes a note, or the owner does; nobody else."""
    from core.database import DesignNote
    need(access, "viewer")
    row = _item(db.query(DesignNote), DesignNote, access).filter(DesignNote.id == str(note_id)).first()
    if row is None:
        raise AccessRefused("There is no such note.", 404)
    if not (access.mine or (user and row.author == user)):
        raise AccessRefused(f"That note is {row.author}'s; only they or {access.owner} can remove it.", 403)
    db.delete(row)
    db.commit()


def public_note(row) -> Dict[str, Any]:
    return {"id": row.id, "author": row.author, "text": row.text, "selector": row.selector,
            "at": row.created_at.isoformat() + "Z" if row.created_at else None}


def notes_for_brief(db, access: Access) -> List[Dict[str, Any]]:
    """Every note, for a brief the agent follows (`P26-08`) — no role check:
    the caller already holds the access it names."""
    from core.database import DesignNote
    rows = _item(db.query(DesignNote), DesignNote, access).order_by(DesignNote.created_at).all()
    return [public_note(r) for r in rows]


# ── presence ────────────────────────────────────────────────────────────────

_seen_lock = threading.Lock()
_seen: Dict[tuple, Dict[str, float]] = {}


def seen(access: Access, user: Optional[str]) -> List[str]:
    """Mark `user` as having it open now; answer everyone who has, the last
    minute, the caller included."""
    now = time.time()
    with _seen_lock:
        who = _seen.setdefault(access.key(), {})
        if user:
            who[user] = now
        for name in [n for n, t in who.items() if now - t > PRESENCE_S]:
            who.pop(name, None)
        if len(_seen) > 2000:
            for k in [k for k, v in _seen.items() if not v]:
                _seen.pop(k, None)
        return sorted(who)


__all__ = ["Access", "AccessRefused", "design_access", "system_access", "need", "share", "shares_of",
           "revoke", "shared_with", "notes", "add_note", "remove_note", "seen", "notes_for_brief",
           "forget_system", "ROLES"]
