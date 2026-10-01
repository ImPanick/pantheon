# SPDX-License-Identifier: AGPL-3.0-or-later
"""document_folders.py — `P21-01` / `P21-02`: one implementation of document folders.

The owner, 2026-10-01: *"I'd like to be able to make folders to sort through
documents, and keep things tidy and organized.. as well as giving the LLM the
ability to organize and make folders etc.."*

Two doors reach this module and they are the only two: the library's routes
(`routes/document/document_folder_routes.py`) and the agent's
`manage_documents` (`src/agent_tools/document_tools.py`). Both call the
functions below, so a person filing a document by hand and the agent filing one
for them run the same code, get the same refusals in the same words, and cannot
drift into two definitions of what a folder is (`Law 7`).

**The model, and why it is this one (`Law 14`).** Chats already have folders:
`sessions.folder`, one string per chat, added by `_migrate_add_folder_column`.
A chat folder is therefore *derived* — it exists while a chat is in it, and
`getFolderNames()` in `static/js/sessions.js` rebuilds the list from the loaded
chats. Documents get the same string, `documents.folder`, extended in the one
direction the owner asked for: it is a path, `"Clients/Acme"`, so folders nest.
What the derived model cannot do is keep a folder nobody has filed anything in
yet — make it, and it is gone — so `DocumentFolder` holds one row per path a
person (or the agent) made, ancestors included. Listing is the union of the two,
so a document whose folder has no row (written before the row existed, or by a
hand-edited database) still shows its folder rather than vanishing into Unfiled.

**Moving a document never counts as editing it.** Filing goes through an UPDATE
that writes `updated_at` back to itself, which is how SQLAlchemy skips the
column's `onupdate`. Without that, filing twenty documents made all twenty the
most recently edited in the library's default sort and printed "edited just
now" under each — a reorganisation reported as twenty edits.

**Owner scope.** Every query here is scoped to one owner, the same strict
equality `_owner_session_filter` applies to the library. `EVERY_OWNER` is the
routes' single-user / auth-off mode and nothing else passes it; the agent tool
refuses before calling in when it has no owner, as its other actions already do.
Another person's document is "not found" — the routes' wording, so a refusal
says nothing about whether the thing exists.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import false, func, or_

from core.database import ChatMessage, Document, DocumentFolder, utcnow_naive

logger = logging.getLogger(__name__)

SEPARATOR = "/"
MAX_NAME_LENGTH = 80
MAX_DEPTH = 8
MAX_DOCUMENTS_PER_MOVE = 500
MAX_STEPS = 200
#: The view of documents with no folder. A top-level folder of this name would
#: be a second "Unfiled" the library could not tell from the first, so the name
#: means *no folder* wherever a path is accepted.
UNFILED = "Unfiled"
REMOVE_MOVE_UP = "move_up"
REMOVE_DELETE = "delete"
REMOVE_CHOICES = (REMOVE_MOVE_UP, REMOVE_DELETE)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class _EveryOwner:
    """Single-user / auth-off mode: every row, like `_owner_session_filter`."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "EVERY_OWNER"


EVERY_OWNER = _EveryOwner()


class FolderError(Exception):
    """A refusal with the sentence a person reads and the HTTP status a route returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ── paths ────────────────────────────────────────────────────────────────────

def normalize_folder_path(raw: Any) -> Optional[str]:
    """The one spelling of a folder path, or None for Unfiled.

    Segments are trimmed and inner whitespace collapsed; empty segments drop out,
    so `"/Clients//Acme/"` is `"Clients/Acme"`. `None`, `""`, `"/"` and
    `"Unfiled"` all mean *no folder*. Refused, visibly, rather than silently
    repaired: control characters, `.`/`..`, a name over 80 characters, nesting
    deeper than 8, and anything inside a top-level "Unfiled".
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise FolderError("A folder path is text, like 'Clients/Acme'.")
    if _CONTROL.search(raw):
        raise FolderError("A folder name can't contain control characters.")
    segments = [re.sub(r"\s+", " ", part).strip() for part in raw.split(SEPARATOR)]
    segments = [part for part in segments if part]
    if not segments:
        return None
    if segments[0].casefold() == UNFILED.casefold():
        if len(segments) == 1:
            return None
        raise FolderError(
            f"'{UNFILED}' is where documents with no folder live, so it can't hold folders."
        )
    for part in segments:
        if part in (".", ".."):
            raise FolderError(f"'{part}' is not a folder name.")
        if len(part) > MAX_NAME_LENGTH:
            raise FolderError(f"A folder name can be at most {MAX_NAME_LENGTH} characters.")
    if len(segments) > MAX_DEPTH:
        raise FolderError(f"Folders nest at most {MAX_DEPTH} deep.")
    return SEPARATOR.join(segments)


def normalize_folder_name(raw: Any) -> str:
    """One segment, for a rename. A '/' here would be a move wearing a rename's name."""
    if isinstance(raw, str) and SEPARATOR in raw.strip().strip(SEPARATOR):
        raise FolderError("A folder name can't contain '/'. To put it somewhere else, move it.")
    name = normalize_folder_path(raw.strip(SEPARATOR) if isinstance(raw, str) else raw)
    if name is None:
        raise FolderError("A folder needs a name.")
    return name


def folder_name(path: str) -> str:
    return path.rsplit(SEPARATOR, 1)[-1]


def parent_of(path: str) -> Optional[str]:
    return path.rsplit(SEPARATOR, 1)[0] if SEPARATOR in path else None


def lineage(path: str) -> List[str]:
    """`"a/b/c"` → `["a", "a/b", "a/b/c"]`."""
    parts = path.split(SEPARATOR)
    return [SEPARATOR.join(parts[:i]) for i in range(1, len(parts) + 1)]


def join_path(parent: Optional[str], name: str) -> str:
    return f"{parent}{SEPARATOR}{name}" if parent else name


def within(path: Optional[str], root: str) -> bool:
    return bool(path) and (path == root or path.startswith(root + SEPARATOR))


def rebase(path: str, old_root: str, new_root: Optional[str]) -> Optional[str]:
    """Re-root `path` from `old_root` to `new_root` (None = the top / Unfiled)."""
    suffix = path[len(old_root):]
    if new_root:
        return new_root + suffix
    return suffix.lstrip(SEPARATOR) or None


def where(path: Optional[str]) -> str:
    """How a location reads in a sentence: a folder path, or Unfiled."""
    return path or UNFILED


def _sort_key(path: str):
    return tuple(part.casefold() for part in path.split(SEPARATOR))


# ── queries ──────────────────────────────────────────────────────────────────

def _scoped(query, model, owner):
    if owner is EVERY_OWNER:
        return query
    if not owner:
        return query.filter(false())
    return query.filter(model.owner == owner)


def _row_owner(owner) -> Optional[str]:
    return None if owner is EVERY_OWNER else owner


def _in_subtree(column, root: str):
    # `substr`, not `LIKE`: a folder may be called "50%_off", and LIKE would read
    # both of those characters as wildcards and match folders it should not.
    return or_(column == root,
               func.substr(column, 1, len(root) + 1) == root + SEPARATOR)


def _active(query):
    return query.filter(Document.is_active == True)  # noqa: E712 — SQL, not Python


def _stored_path(value: Any) -> Optional[str]:
    """Read a stored folder value, tolerating a spelling this module did not write."""
    try:
        return normalize_folder_path(value)
    except FolderError:
        return value or None


def _paths_within(db, owner, root: str) -> set:
    """Every folder at or under `root`: made ones and ones only a document names."""
    paths = {
        row.path for row in
        _scoped(db.query(DocumentFolder), DocumentFolder, owner)
        .filter(_in_subtree(DocumentFolder.path, root)).all()
    }
    for (value,) in (_active(_scoped(db.query(Document.folder), Document, owner))
                     .filter(_in_subtree(Document.folder, root)).distinct().all()):
        path = _stored_path(value)
        if path:
            paths.add(path)
    every = set()
    for path in paths:
        every.update(p for p in lineage(path) if within(p, root))
    return every


def folder_exists(db, owner, path: str) -> bool:
    return bool(_paths_within(db, owner, path))


def _existing(db, owner, raw_path: Any) -> str:
    path = normalize_folder_path(raw_path)
    if path is None:
        raise FolderError("Say which folder — Unfiled is not a folder.")
    if not folder_exists(db, owner, path):
        raise FolderError(f"Folder '{path}' not found", 404)
    return path


def _ensure_rows(db, owner, path: str) -> List[str]:
    """Make `path` and every folder above it exist. Returns the paths it made."""
    made = []
    for step in lineage(path):
        found = (_scoped(db.query(DocumentFolder.id), DocumentFolder, owner)
                 .filter(DocumentFolder.path == step).first())
        if found is None:
            db.add(DocumentFolder(id=str(uuid.uuid4()), owner=_row_owner(owner), path=step))
            db.flush()
            made.append(step)
    return made


def _refile(db, doc: Document, folder: Optional[str]) -> None:
    """Set a document's folder without touching `updated_at` (see module header)."""
    db.query(Document).filter(Document.id == doc.id).update(
        {Document.folder: folder, Document.updated_at: doc.updated_at},
        synchronize_session="evaluate",
    )


def _make(db, owner, path: Optional[str]) -> List[str]:
    """`_ensure_rows`, reporting only folders that did not exist before.

    A folder only a document named already existed as far as a person can see —
    the library listed it — so giving it a row is not "making" it.
    """
    if not path:
        return []
    fresh = [p for p in lineage(path) if not folder_exists(db, owner, p)]
    _ensure_rows(db, owner, path)
    return fresh


def _created(paths: Iterable[str]) -> List[Dict[str, Any]]:
    return [{"change": "created", "kind": "folder", "from": None, "to": p} for p in paths]


# ── reading ──────────────────────────────────────────────────────────────────

def list_folders(db, owner, *, archived: bool = False) -> Dict[str, Any]:
    """Every folder with its counts, plus the Unfiled count and the total.

    `count` is documents directly in the folder, `total` includes its subfolders.
    Counted in the same view the library is showing — active, and archived or
    not to match — so a folder's number is the number of cards it opens onto.
    """
    paths = {row.path for row in _scoped(db.query(DocumentFolder), DocumentFolder, owner).all()}
    q = _active(_scoped(db.query(Document.folder, func.count(Document.id)), Document, owner))
    if archived:
        q = q.filter(Document.archived == True)  # noqa: E712
    else:
        q = q.filter(or_(Document.archived == False, Document.archived.is_(None)))  # noqa: E712
    direct: Dict[str, int] = {}
    unfiled = 0
    for value, n in q.group_by(Document.folder).all():
        path = _stored_path(value)
        if path is None:
            unfiled += n
            continue
        direct[path] = direct.get(path, 0) + n
        paths.add(path)
    every = set()
    for path in paths:
        every.update(lineage(path))
    folders = []
    for path in sorted(every, key=_sort_key):
        folders.append({
            "path": path,
            "name": folder_name(path),
            "parent": parent_of(path),
            "depth": path.count(SEPARATOR),
            "count": direct.get(path, 0),
            "total": sum(n for p, n in direct.items() if within(p, path)),
        })
    return {"folders": folders, "unfiled": unfiled, "all": unfiled + sum(direct.values())}


# ── changing ─────────────────────────────────────────────────────────────────
#
# None of these commit. A caller runs one or several and commits once, so a
# reorganisation is one transaction and a refused step leaves nothing behind.
# Each returns `changes`: one entry per thing that moved, appeared or went,
# shaped `{change, kind, from, to, ...}` with `change` one of created · moved ·
# removed · deleted — an enum, because "did this delete anything" must not be
# read off a boolean whose polarity a card could get backwards (`Law 10`).

def create_folder(db, owner, raw_path: Any, *, exist_ok: bool = False) -> Dict[str, Any]:
    path = normalize_folder_path(raw_path)
    if path is None:
        raise FolderError("A folder needs a name.")
    if folder_exists(db, owner, path) and not exist_ok:
        raise FolderError(
            f"There is already a folder called '{folder_name(path)}' "
            f"{_location_phrase(parent_of(path))}.", 409)
    return {"path": path, "changes": _created(_make(db, owner, path))}


def _location_phrase(parent: Optional[str]) -> str:
    return f"in '{parent}'" if parent else "at the top level"


def _relocate(db, owner, old: str, new: str) -> Dict[str, Any]:
    """Move folder `old` (and everything in it) to `new`, as one unit."""
    if within(new, old):
        raise FolderError("A folder can't be moved into itself or one of its own folders.")
    if folder_exists(db, owner, new):
        raise FolderError(
            f"There is already a folder called '{folder_name(new)}' "
            f"{_location_phrase(parent_of(new))}.", 409)
    above = parent_of(new)
    fresh = [p for p in lineage(above) if not folder_exists(db, owner, p)] if above else []
    # Every document, deleted ones included: a document restored later should
    # come back into the folder as it is now called, not as it was.
    docs = (_scoped(db.query(Document), Document, owner)
            .filter(_in_subtree(Document.folder, old)).all())
    inside = 0
    for doc in docs:
        _refile(db, doc, rebase(_stored_path(doc.folder) or old, old, new))
        if doc.is_active:
            inside += 1
    rows = (_scoped(db.query(DocumentFolder), DocumentFolder, owner)
            .filter(_in_subtree(DocumentFolder.path, old)).all())
    for row in rows:
        row.path = rebase(row.path, old, new)
    db.flush()
    _ensure_rows(db, owner, new)
    return {
        "path": new,
        "changes": _created(fresh) + [{"change": "moved", "kind": "folder", "from": old,
                                       "to": new, "documents": inside}],
    }


def rename_folder(db, owner, raw_path: Any, raw_name: Any) -> Dict[str, Any]:
    path = _existing(db, owner, raw_path)
    new = join_path(parent_of(path), normalize_folder_name(raw_name))
    if new == path:
        return {"path": path, "changes": []}
    return _relocate(db, owner, path, new)


def move_folder(db, owner, raw_path: Any, raw_to: Any) -> Dict[str, Any]:
    path = _existing(db, owner, raw_path)
    to = normalize_folder_path(raw_to)
    # Into itself or a folder inside it: refused once, in `_relocate`.
    new = join_path(to, folder_name(path))
    if new == path:
        return {"path": path, "changes": []}
    return _relocate(db, owner, path, new)


def file_documents(db, owner, document_ids: Any, raw_to: Any) -> Dict[str, Any]:
    """File documents into a folder (made if missing), or into Unfiled.

    All or nothing: if any id is not one of the caller's documents, nothing
    moves and the refusal names it. A partial filing a person did not ask for
    is a second mess to sort out.
    """
    to = normalize_folder_path(raw_to)
    if isinstance(document_ids, str):
        document_ids = [document_ids]
    if not isinstance(document_ids, (list, tuple)):
        raise FolderError("Say which documents to move, as a list of ids.")
    ids: List[str] = []
    for value in document_ids:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    if not ids:
        raise FolderError("Say which documents to move.")
    if len(ids) > MAX_DOCUMENTS_PER_MOVE:
        raise FolderError(f"Move at most {MAX_DOCUMENTS_PER_MOVE} documents at a time.")
    docs = (_active(_scoped(db.query(Document), Document, owner))
            .filter(Document.id.in_(ids)).all())
    found = {doc.id: doc for doc in docs}
    for doc_id in ids:
        if doc_id not in found:
            raise FolderError(f"Document '{doc_id}' not found", 404)
    changes = _created(_make(db, owner, to))
    for doc_id in ids:
        doc = found[doc_id]
        before = _stored_path(doc.folder)
        if before == to:
            continue
        _refile(db, doc, to)
        changes.append({"change": "moved", "kind": "document", "id": doc.id,
                        "title": doc.title or "Untitled", "from": before, "to": to})
    return {"to": to, "changes": changes}


def remove_folder(db, owner, raw_path: Any, contents: Any = None, *,
                  dry_run: bool = False) -> Dict[str, Any]:
    """Remove a folder. What is in it moves up a level or is deleted with it.

    The choice is never assumed. A folder holding anything is refused until the
    caller says `move_up` or `delete`, and the refusal — like the dry run the
    library asks for first — says how many documents and folders that is. A
    deleted document is the library's own delete (`is_active` false), not a row
    removal.
    """
    path = _existing(db, owner, raw_path)
    docs = (_active(_scoped(db.query(Document), Document, owner))
            .filter(_in_subtree(Document.folder, path)).all())
    below = sorted((p for p in _paths_within(db, owner, path) if p != path), key=_sort_key)
    parent = parent_of(path)
    summary = {
        "path": path,
        "parent": parent,
        "documents": len(docs),
        "archived": sum(1 for d in docs if d.archived),
        "folders": len(below),
        "contents": contents if contents in REMOVE_CHOICES else None,
    }
    if dry_run:
        return {**summary, "changes": []}
    holds = bool(docs or below)
    if holds and contents not in REMOVE_CHOICES:
        up = (f"moves them up into '{parent}'" if parent else
              "moves its documents to Unfiled and its folders to the top level")
        raise FolderError(
            f"'{folder_name(path)}' holds {count_phrase(len(docs), len(below))}. "
            f"Say what happens to them: '{REMOVE_MOVE_UP}' {up}, "
            f"'{REMOVE_DELETE}' deletes them with it.")
    changes: List[Dict[str, Any]] = []
    if holds and contents == REMOVE_DELETE:
        for doc in docs:
            changes.append(_deleted(doc))
            doc.is_active = False
        for sub in below:
            changes.append({"change": "removed", "kind": "folder", "from": sub, "to": None})
        (_scoped(db.query(DocumentFolder), DocumentFolder, owner)
         .filter(_in_subtree(DocumentFolder.path, path))
         .delete(synchronize_session="fetch"))
    elif holds:
        children = [p for p in below if parent_of(p) == path]
        for child in children:
            inside = sum(1 for d in docs if within(_stored_path(d.folder), child))
            changes.append({"change": "moved", "kind": "folder", "from": child,
                            "to": rebase(child, path, parent), "documents": inside})
        every = (_scoped(db.query(Document), Document, owner)
                 .filter(_in_subtree(Document.folder, path)).all())
        for doc in every:
            before = _stored_path(doc.folder) or path
            after = rebase(before, path, parent)
            _refile(db, doc, after)
            if doc.is_active and before == path:
                changes.append({"change": "moved", "kind": "document", "id": doc.id,
                                "title": doc.title or "Untitled", "from": path, "to": after})
        # The folder's own row goes first and is flushed, because a child can
        # land on its exact path: removing "a/a" moves "a/a/a" up to "a/a".
        (_scoped(db.query(DocumentFolder), DocumentFolder, owner)
         .filter(DocumentFolder.path == path).delete(synchronize_session="fetch"))
        db.flush()
        rows = sorted((_scoped(db.query(DocumentFolder), DocumentFolder, owner)
                       .filter(_in_subtree(DocumentFolder.path, path)).all()),
                      key=lambda r: _sort_key(r.path))
        for row in rows:
            target = rebase(row.path, path, parent)
            taken = (_scoped(db.query(DocumentFolder.id), DocumentFolder, owner)
                     .filter(DocumentFolder.path == target).first())
            if taken is not None:
                db.delete(row)       # merges into the folder already there
            else:
                row.path = target
            db.flush()
    else:
        (_scoped(db.query(DocumentFolder), DocumentFolder, owner)
         .filter(DocumentFolder.path == path).delete(synchronize_session="fetch"))
    db.flush()
    if parent:
        # Removing the last thing in a folder must not remove the folder above it.
        _ensure_rows(db, owner, parent)
    changes.append({"change": "removed", "kind": "folder", "from": path, "to": None})
    return {**summary, "changes": changes}


def file_new_document(db, owner, doc: Document, path: Optional[str]) -> None:
    """`B997`. A document an import is making lands in the folder that was open.

    The folder is made (with its parents) if it has gone since the library drew
    it — `file_documents`' rule for a destination — and the caller commits, so
    the document and its folder arrive together or not at all. A new document is
    not "moved", so there is no change to report and no `updated_at` to protect.
    """
    if not path:
        return
    _ensure_rows(db, owner, path)
    doc.folder = path


def _deleted(doc: Document) -> Dict[str, Any]:
    """The change a deleted document makes, sealed to the content it had.

    `B994`. `digest` is what `apply_plan` compares, with the rest of the
    fingerprint: a plan to delete an empty "Untitled" must not delete it after
    the person has typed into it. It never reaches the card or the model
    (`shown_changes`) — a hash says nothing to either.
    """
    from src.tool_approvals import document_content_digest
    return {"change": "deleted", "kind": "document", "id": doc.id,
            "title": doc.title or "Untitled", "from": _stored_path(doc.folder), "to": None,
            "digest": document_content_digest(doc.current_content)}


def delete_documents(db, owner, document_ids: Any) -> Dict[str, Any]:
    """`B994`. Delete documents — the library's own delete (`is_active` false).

    All or nothing, like `file_documents`: one id that is not the caller's
    refuses the lot, in the routes' words, and nothing is deleted.
    """
    if isinstance(document_ids, str):
        document_ids = [document_ids]
    if not isinstance(document_ids, (list, tuple)):
        raise FolderError("Say which documents to delete, as a list of ids.")
    ids: List[str] = []
    for value in document_ids:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    if not ids:
        raise FolderError("Say which documents to delete.")
    if len(ids) > MAX_DOCUMENTS_PER_MOVE:
        raise FolderError(f"Delete at most {MAX_DOCUMENTS_PER_MOVE} documents at a time.")
    docs = (_active(_scoped(db.query(Document), Document, owner))
            .filter(Document.id.in_(ids)).all())
    found = {doc.id: doc for doc in docs}
    for doc_id in ids:
        if doc_id not in found:
            raise FolderError(f"Document '{doc_id}' not found", 404)
    changes = []
    for doc_id in ids:
        doc = found[doc_id]
        changes.append(_deleted(doc))
        doc.is_active = False
    return {"changes": changes}


def forget_deleted(changes: Iterable[Dict[str, Any]]) -> None:
    """The housekeeping `DELETE /api/document/{id}` does (#1160), after commit.

    Called by whoever commits — never inside a step, because a plan runs its
    steps and rolls them back, and a plan to delete the open document used to
    clear the open-document pointer although nothing was deleted (`B994`).
    """
    for c in changes or ():
        if c.get("change") != "deleted" or c.get("kind") != "document":
            continue
        try:
            from src.agent_tools.document_tools import clear_active_document
            clear_active_document(c.get("id"))
        except Exception:
            logger.debug("clear_active_document(%s) failed", c.get("id"), exc_info=True)


def shown_changes(changes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The change list as a person or a model reads it: without the seal."""
    return [{k: v for k, v in c.items() if k != "digest"} for c in changes]


# ── words ────────────────────────────────────────────────────────────────────

def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def count_phrase(documents: int, folders: int) -> str:
    """`'3 documents and 1 folder'` — the sentence a removal says before it acts."""
    parts = []
    if documents:
        parts.append(_n(documents, "document"))
    if folders:
        parts.append(_n(folders, "folder"))
    return " and ".join(parts) if parts else "nothing"


def counted_changes(changes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What a person would have to put back by hand. Making a folder is not one."""
    return [c for c in changes if c.get("change") != "created"]


def summarize_changes(changes: Iterable[Dict[str, Any]], *, past: bool = False) -> str:
    """`'moves 12 documents, removes 1 folder and deletes 3 documents'`.

    `past=True` for what was done (`'moved 12 documents …'`), the default for
    what a plan would do.
    """
    tally: Dict[tuple, int] = {}
    for c in changes:
        key = (c.get("change"), c.get("kind"))
        tally[key] = tally.get(key, 0) + 1
    order = [
        (("moved", "document"), ("moves", "moved"), "document"),
        (("moved", "folder"), ("moves", "moved"), "folder"),
        (("created", "folder"), ("makes", "made"), "folder"),
        (("removed", "folder"), ("removes", "removed"), "folder"),
        (("deleted", "document"), ("deletes", "deleted"), "document"),
    ]
    parts = [f"{verbs[1 if past else 0]} {_n(tally[key], noun)}"
             for key, verbs, noun in order if tally.get(key)]
    if not parts:
        return "changed nothing" if past else "changes nothing"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def describe_change(c: Dict[str, Any]) -> str:
    """One line per change, the line a tool card lists so a person can undo by hand."""
    change, kind = c.get("change"), c.get("kind")
    if kind == "document":
        title = c.get("title") or "Untitled"
        if change == "moved":
            return f'moved "{title}": {where(c.get("from"))} → {where(c.get("to"))}'
        if change == "deleted":
            why = f" — {c['reason']}" if c.get("reason") else ""
            return f'deleted "{title}" (was in {where(c.get("from"))}){why}'
    if kind == "folder":
        if change == "created":
            return f"made folder {c.get('to')}"
        if change == "moved":
            inside = c.get("documents") or 0
            tail = f" (with the {_n(inside, 'document')} in it)" if inside else ""
            return f"moved folder {c.get('from')} → {where(c.get('to'))}{tail}"
        if change == "removed":
            return f"removed folder {c.get('from')}"
    return str(c)


# ── steps and plans (`P21-02`) ───────────────────────────────────────────────
#
# `P9-10`'s house rule is that a destructive AI operation is previewed before it
# runs. For the agent's folder work the threshold is the row's "more than a
# handful": a call whose changes a person would have to undo one by one — more
# than five moved or removed things — is not applied; nor, since `B994`, is any
# call that deletes a document, however few (`needs_plan` says why). It is run inside the
# transaction, its change list read, and rolled back; the list becomes a plan,
# shown on the tool card, and the existing `ask_user` card (`P4` — the one any
# tool result can raise) asks the person to apply it. Nothing new is drawn.
#
# What makes the approval real rather than advisory is where `apply_plan` reads
# the answer: from the chat's own last message, persisted by the chat route
# before the agent runs. The card sends the option's label as that message, so
# "Apply the plan", typed or clicked, after the plan was made, is the yes; any
# other answer is a no, and so is no answer. The agent cannot approve its own
# plan, because it does not write the person's messages — which was true of
# the chat route and false of five other writers of user messages until
# `B1005` made the answer only a message sealed as the person's (`plan_answer`).
#
# And the plan is the change list, not just the steps. `apply_plan` re-runs the
# steps and refuses if they would now do something different from what the
# person read — a document added to a folder after the plan was shown would
# otherwise be deleted with it, unseen. The same seal `_approved_document_version_error`
# puts on a document edit, for the same reason.

PLAN_THRESHOLD = 5
PLAN_TTL_SECONDS = 30 * 60
PLAN_APPROVE_LABEL = "Apply the plan"
PLAN_DECLINE_LABEL = "Don't change anything"
STEP_ACTIONS = ("create_folder", "rename_folder", "move_folder", "move", "remove_folder",
                "delete")


def _destination(step: Dict[str, Any], *, fallback_key: Optional[str] = None) -> Any:
    """Where a move goes. A missing `to` is refused, never read as Unfiled.

    `{"action": "move", "folder": "Clients"}` with no `to` is a model that put
    the destination in the wrong key, and reading the absence as "Unfiled" would
    empty a folder it meant to fill. An explicit `to: ""` (or null) is Unfiled.
    """
    if "to" in step:
        return step.get("to")
    if fallback_key and fallback_key in step:
        return step.get(fallback_key)
    raise FolderError("Say where to: 'to' is a folder path like 'Clients/Acme', "
                      "or '' for Unfiled / the top level.")


def run_step(db, owner, step: Dict[str, Any]) -> Dict[str, Any]:
    action = str(step.get("action") or "").strip().casefold()
    if action == "create_folder":
        return create_folder(db, owner, step.get("folder"), exist_ok=True)
    if action == "rename_folder":
        return rename_folder(db, owner, step.get("folder"), step.get("name"))
    if action == "move_folder":
        return move_folder(db, owner, step.get("folder"), _destination(step))
    if action == "move":
        ids = step.get("document_ids")
        if ids is None:
            ids = step.get("document_id") or step.get("id")
        return file_documents(db, owner, ids, _destination(step, fallback_key="folder"))
    if action == "remove_folder":
        return remove_folder(db, owner, step.get("folder"), step.get("contents"))
    if action == "delete":
        ids = step.get("document_ids")
        if ids is None:
            ids = step.get("document_id") or step.get("id")
        return delete_documents(db, owner, ids)
    raise FolderError(f"'{action or '(none)'}' is not a folder step — use one of: "
                      + ", ".join(STEP_ACTIONS) + ".")


def run_steps(db, owner, steps: Any) -> List[Dict[str, Any]]:
    """Run steps in order in the caller's transaction; return every change."""
    if not isinstance(steps, list) or not steps:
        raise FolderError("Give the reorganisation as a list of steps.")
    if len(steps) > MAX_STEPS:
        raise FolderError(f"At most {MAX_STEPS} steps at once.")
    changes: List[Dict[str, Any]] = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise FolderError(f"Step {i} is not an object.")
        try:
            changes.extend(run_step(db, owner, step)["changes"])
        except FolderError as e:
            if len(steps) == 1:
                raise
            raise FolderError(f"Step {i} ({step.get('action')}): {e.message}", e.status)
        db.flush()
    return changes


def deletes(changes: Iterable[Dict[str, Any]]) -> int:
    """How many documents a change list deletes."""
    return sum(1 for c in changes
               if c.get("change") == "deleted" and c.get("kind") == "document")


def needs_plan(changes: Iterable[Dict[str, Any]]) -> bool:
    """Whether a call waits for the person: more than five moves or removals,
    or any deleted document at all.

    `B994`, the owner's call (`D-2026-10-01-02`: *"a big move or a delete still
    waits for their approval"*). The two thresholds differ because what undoes
    them differs. A move is on the card as `moved "X": A → B`, and the person
    can put it back from the library in one drag — five of those is a handful,
    and a sixth is where undoing by hand becomes a chore (`P21-02`). A delete
    has no way back: the library has no bin and no restore, so a deleted
    document is gone from everything the person can reach. One is already too
    many to take on the agent's word, so one asks — the named delete as well as
    the tidy, in a plan of one. Removing an empty folder deletes nothing and is
    undone by making it again, so it counts as a removal, not a delete.
    """
    changes = list(changes)
    return len(counted_changes(changes)) > PLAN_THRESHOLD or deletes(changes) > 0


def _fingerprint(changes: Iterable[Dict[str, Any]]) -> tuple:
    # `digest` is None for everything but a deleted document (`_deleted`).
    return tuple((c.get("change"), c.get("kind"), c.get("id"), c.get("from"), c.get("to"),
                  c.get("digest"))
                 for c in changes)


def plan_question(changes: Iterable[Dict[str, Any]]) -> str:
    """The `ask_user` card's question for a plan — what it does, in one line."""
    changes = list(changes)
    gone = deletes(changes)
    if gone and gone == len(counted_changes(changes)):
        return (f"Delete {_n(gone, 'document')}? Listed above — a deleted document "
                "can't be brought back from the library.")
    tail = (" Deleted documents can't be brought back from the library."
            if gone else "")
    return f"Reorganise your documents? This {summarize_changes(changes)}, as listed above.{tail}"


@dataclass
class FolderPlan:
    plan_id: str
    owner: str
    session_id: str
    steps: List[Dict[str, Any]]
    changes: List[Dict[str, Any]]
    created_at: datetime = field(default_factory=utcnow_naive)
    expires_at: float = field(default_factory=lambda: time.monotonic() + PLAN_TTL_SECONDS)
    #: `B1006`. What a person is shown to answer a plan nobody asked for in a
    #: chat — the scheduled tidy's — from a notification. ``None`` for the
    #: agent's plans, which are answered on the card in the chat that asked.
    review: Optional[Dict[str, Any]] = None


_plans: Dict[str, FolderPlan] = {}
_plans_lock = threading.Lock()


def _purge_plans_locked(now: float) -> None:
    for plan_id in [k for k, p in _plans.items() if p.expires_at <= now]:
        _plans.pop(plan_id, None)


def propose_plan(owner: str, session_id: str, steps: List[Dict[str, Any]],
                 changes: List[Dict[str, Any]], *, ttl_seconds: Optional[float] = None,
                 review: Optional[Dict[str, Any]] = None) -> FolderPlan:
    """Hold a plan for this chat. A newer plan in the same chat replaces it.

    `ttl_seconds` and `review` are `B1006`'s: the scheduled tidy's plan waits
    longer than the agent's 30 minutes, and carries what its notification shows.
    """
    with _plans_lock:
        _purge_plans_locked(time.monotonic())
        for plan_id in [k for k, p in _plans.items()
                        if p.owner == owner and p.session_id == session_id]:
            _plans.pop(plan_id, None)
        plan = FolderPlan(plan_id=secrets.token_urlsafe(9), owner=owner,
                          session_id=session_id, steps=list(steps), changes=list(changes),
                          review=review)
        if ttl_seconds is not None:
            plan.expires_at = time.monotonic() + ttl_seconds
        _plans[plan.plan_id] = plan
        return plan


def pending_plan(plan_id: Any, owner: str, session_id: Optional[str]) -> Optional[FolderPlan]:
    with _plans_lock:
        _purge_plans_locked(time.monotonic())
        plan = _plans.get(str(plan_id or ""))
        if plan is None or plan.owner != owner or plan.session_id != session_id:
            return None
        return plan


def discard_plan(plan_id: str) -> None:
    with _plans_lock:
        _plans.pop(plan_id, None)


def _answerable_by(plan: FolderPlan, owner: Any) -> bool:
    return plan.review is not None and (owner is EVERY_OWNER or plan.owner == owner)


def waiting_review(plan_id: Any, owner: Any) -> Optional[FolderPlan]:
    """`B1006`. A plan waiting for its person on a notification — the
    scheduled tidy's — if it is *owner*'s. An agent's plan is not answered
    here: it is answered on the card in the chat that asked."""
    with _plans_lock:
        _purge_plans_locked(time.monotonic())
        plan = _plans.get(str(plan_id or ""))
        return plan if plan is not None and _answerable_by(plan, owner) else None


def waiting_reviews(owner: Any) -> List[FolderPlan]:
    """Every such plan still waiting for *owner*, oldest first."""
    with _plans_lock:
        _purge_plans_locked(time.monotonic())
        return sorted((p for p in _plans.values() if _answerable_by(p, owner)),
                      key=lambda p: p.created_at)


def _row_metadata(message: ChatMessage) -> Dict[str, Any]:
    try:
        meta = json.loads(message.meta_data or "{}")
    except (TypeError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def plan_answer(db, plan: FolderPlan) -> str:
    """`approved` · `declined` · `unanswered` — what the PERSON said in the chat.

    `B1005`. This read the chat's newest user message, and a user message is
    not the person's: `inject_messages`, `POST …/message`, `send_to_session`
    from another chat, a scheduled task's delivery, `edit-message` and the chat
    route on the agent's own loopback all write one. Now only a message sealed
    as the person's counts (`tool_approval_scopes.person_said_at`) — sealed by
    the chat route for a person's own request, or by a plan's answer route —
    and only when the seal says it was said after the plan was made; every
    other row is passed over as if it were not there. The newest such message
    is the answer: the yes, exactly, or a no; none is no answer yet.

    The rows are bounded by their stored timestamp first (a person's message is
    stored after it is sealed, so it is never older than its seal); the seal's
    own moment decides, because a compaction re-stamps every row it keeps.
    """
    from src.tool_approval_scopes import person_said_at

    rows = (db.query(ChatMessage)
            .filter(ChatMessage.session_id == plan.session_id)
            .filter(ChatMessage.role == "user")
            .filter(ChatMessage.timestamp >= plan.created_at)
            .order_by(ChatMessage.timestamp.desc())
            .all())
    for message in rows:
        said = person_said_at(_row_metadata(message), plan.session_id, message.content)
        if said is None or said < plan.created_at:
            continue
        if (message.content or "").strip() == PLAN_APPROVE_LABEL:
            return "approved"
        return "declined"
    return "unanswered"


def apply_plan(db, owner: str, session_id: Optional[str], plan_id: Any) -> Dict[str, Any]:
    plan = pending_plan(plan_id, owner, session_id)
    if plan is None:
        raise FolderError(
            "No plan with that id is waiting in this chat — plans last "
            f"{PLAN_TTL_SECONDS // 60} minutes. Propose the reorganisation again.", 404)
    answer = plan_answer(db, plan)
    if answer == "unanswered":
        raise FolderError("The person has not answered the plan yet, so nothing was "
                          "changed. Wait for their answer.", 409)
    if answer == "declined":
        discard_plan(plan.plan_id)
        raise FolderError(f"The person did not choose '{PLAN_APPROVE_LABEL}', so nothing "
                          "was changed.", 409)
    changes = run_steps(db, owner, plan.steps)
    if _fingerprint(changes) != _fingerprint(plan.changes):
        discard_plan(plan.plan_id)
        raise FolderError("Your documents changed after this plan was shown, so none of it "
                          "was applied. Propose it again to see what it would do now.", 409)
    discard_plan(plan.plan_id)
    # The same changes in the same order (the fingerprint says so); what the
    # plan's card gave as each one's reason — a tidy's "empty", "a duplicate"
    # — is said again on the card that reports them done.
    for done, shown in zip(changes, plan.changes):
        if shown.get("reason"):
            done["reason"] = shown["reason"]
    return {"plan_id": plan.plan_id, "changes": changes}
