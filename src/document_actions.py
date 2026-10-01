# SPDX-License-Identifier: AGPL-3.0-or-later
"""
document_actions.py

Reusable document actions callable from both REST routes and the task scheduler.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


_JUNK_TITLES = {
    "untitled", "untitled document", "new document", "document",
    "new email", "new mail", "new message", "reply", "fwd", "re:",
    "test", "testing", "asdf", "asd", "foo", "bar", "baz",
    "tmp", "temp", "scratch", "scratchpad", "draft", "delete",
    "remove", "junk", "trash", "xxx", "abc", "qwerty",
}


def _norm_title(t: str) -> str:
    """Normalize a title for grouping: trim, collapse whitespace, lowercase."""
    t = t if isinstance(t, str) else ""
    return re.sub(r"\s+", " ", t.strip()).lower()


def _content_fingerprint(content: str) -> str:
    """A stable fingerprint of document content for duplicate detection.

    Strips bits that differ between otherwise-identical copies — chiefly the
    `upload_id` of a re-imported PDF and the random `id=` of annotations — so
    that N imports of the same file collapse to one fingerprint. Whitespace is
    collapsed and the result lowercased.
    """
    c = content if isinstance(content, str) else ""
    c = re.sub(r'upload_id="[^"]*"', "upload_id", c)          # pdf_source re-imports
    c = re.sub(r"\bid=ann-[A-Za-z0-9_-]+", "id=ann", c)        # annotation ids
    c = re.sub(r"\s+", " ", c).strip().lower()
    return c


def _real_len(content: str) -> int:
    """Length of content with markdown noise stripped — a 'completeness' proxy."""
    content = content if isinstance(content, str) else ""
    stripped = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
    stripped = re.sub(r"[*_`>\-=]+", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return len(stripped)


def tidy_verdicts(docs, now=None) -> dict:
    """What the tidy rules would remove from `docs`, and why. Removes nothing.

    `B994`. The rules were inside `run_document_tidy`, which deleted as it
    judged, so the only way to learn what a tidy would do was to let it. The
    agent's tidy now asks first (`manage_documents tidy` shows the list as a
    plan the person approves), so the judging is its own function and both
    callers read the same verdicts (`Law 7`).

    Returns ``{"junk": [(doc, reason)], "duplicates": [(keeper, [copies])],
    "kept": n}`` — junk in the order given, duplicate groups in first-seen
    order, `kept` the number of documents (one per duplicate group) that stay.

    Conservative rules (no length-based deletion — short notes are valid):
    - Empty / whitespace-only / placeholder ("# Untitled")
    - Title is a throwaway name (test, asdf, …) or the content itself is one
    - Email reply-chain with no original content
    - Duplicates: docs sharing the same normalized title AND the same content
      fingerprint (ignoring volatile upload/annotation ids). The most complete
      copy (longest real content, then most recent) is kept; the rest go.
    """
    now = now or datetime.now(timezone.utc)
    junk = []
    survivors = []  # docs that pass the junk rules, considered for dedup

    for doc in docs:
        created = doc.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        # Skip freshly created documents to avoid deleting them while the user is actively editing
        if created and (now - created).total_seconds() < 900:  # 15 minutes
            survivors.append(doc)
            continue

        content = (doc.current_content or "").strip()
        title = (doc.title or "").strip().lower()
        is_fresh_empty = (
            not content
            and created is not None
            and (now - created).total_seconds() < 1800
        )
        if is_fresh_empty:
            survivors.append(doc)
            continue

        # Strip markdown noise to get "real" character count
        stripped = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)  # headers
        stripped = re.sub(r"[*_`>\-=]+", "", stripped)  # markdown chars
        stripped = re.sub(r"\s+", " ", stripped).strip()

        # Detect emails-saved-as-documents (quote chains with no original content)
        lines = [ln for ln in content.split("\n") if ln.strip()]
        quoted_lines = [ln for ln in lines if ln.lstrip().startswith(">")]
        header_lines = [ln for ln in lines if re.match(r"^On .+ wrote:?\s*$", ln.strip())]
        non_quote_content = "\n".join(
            ln for ln in lines
            if not ln.lstrip().startswith(">")
            and not re.match(r"^On .+ wrote:?\s*$", ln.strip())
        ).strip()
        quote_ratio = len(quoted_lines) / max(len(lines), 1)

        reason = ""
        if not content or content in ("", "# Untitled"):
            reason = "empty"
        elif title in _JUNK_TITLES:
            # If you named it "test" or "asdf" etc, you don't care about it
            reason = f"junk title '{title}'"
        elif stripped.lower() in _JUNK_TITLES:
            reason = "throwaway content"
        # No length-based deletion: short notes are legitimate content.
        elif (quoted_lines or header_lines) and len(non_quote_content) < 50 and quote_ratio > 0.4:
            # Email reply chain with no original content
            reason = "email quote-chain only"

        if reason:
            junk.append((doc, reason))
        else:
            survivors.append(doc)

    # --- Duplicate pass: group survivors by (normalized title, content
    # fingerprint) and keep only the most complete copy of each group. ---
    groups: dict = {}
    for doc in survivors:
        key = (_norm_title(doc.title), _content_fingerprint(doc.current_content))
        groups.setdefault(key, []).append(doc)

    duplicates = []
    for _key, members in groups.items():
        if len(members) < 2:
            continue
        # Keep the most complete (longest real content), then most recent.
        def _updated(d):
            return d.updated_at or d.created_at
        # Sort key must be total-order safe: a document with both
        # updated_at and created_at NULL would otherwise make Python
        # compare None against a datetime on a real-length tie, raising
        # TypeError and aborting the whole tidy run. Rank "has a
        # timestamp" before the timestamp itself so a None is never
        # compared against a datetime.
        members.sort(
            key=lambda d: (
                _real_len(d.current_content),
                _updated(d) is not None,
                _updated(d) or datetime.min,
            ),
            reverse=True,
        )
        duplicates.append((members[0], members[1:]))

    return {"junk": junk, "duplicates": duplicates, "kept": len(groups)}


#: Why the tidy rules would remove a document, as its line on a plan says it.
#: `B994` wrote it for the agent's card; `B1006` shows the same line to the
#: person from the scheduled tidy, so it is said once, here (`Law 7`).
TIDY_DUPLICATE_REASON = "a duplicate — the fullest copy stays"


def tidy_reasons(docs) -> dict:
    """`{document id: why}` for every document the tidy rules would remove,
    in the order `tidy_verdicts` names them (junk first, then each group's
    extra copies). The one reading of the verdicts both tidies use."""
    verdicts = tidy_verdicts(docs)
    reasons = {}
    for doc, reason in verdicts["junk"]:
        reasons[doc.id] = reason
    for _keeper, copies in verdicts["duplicates"]:
        for doc in copies:
            reasons[doc.id] = TIDY_DUPLICATE_REASON
    return reasons


# ── `B1006` · the scheduled tidy proposes; the person applies ───────────────
#
# The owner, 2026-10-01 (`D-2026-10-01-03`): *propose, don't delete.* The
# seeded "Documents Tidy" task (`HOUSEKEEPING_DEFAULTS["tidy_documents"]`, run
# after every fifth new document, seeded active for every owner) used to
# `db.delete` — a hard delete, not the library's — everything the rules named,
# with nothing shown to anyone. It now builds the same list and asks.
#
# It asks through `P21-02`'s plan, not beside it (`Law 14`): the list is one
# `delete` step, run inside a transaction, read and rolled back
# (`document_folders.run_steps`), held as a plan sealed to each document's
# content, and applied by `document_folders.apply_plan` only on the person's
# own "Apply the plan" — which `B1005` made a message sealed as theirs. A plan
# lives in a chat, because that is where its answer is read; the tidy's chat is
# the owner's "Documents Tidy" chat in Tasks, one per owner, and it keeps the
# record: what was proposed, what the person answered, what happened.
#
# The person is told by a notification on the scheduler's queue (`Law 14`: the
# channel every task already speaks through), carrying the list so the browser
# can show it and answer it (`static/js/documentPlanNotice.js`); the answer goes
# to `POST /api/document-folders/plans/{id}/answer`, which only a person can
# call. A proposal waits a week and the next tidy replaces it.

TIDY_CHAT_NAME = "Documents Tidy"
TIDY_CHAT_FOLDER = "Tasks"
#: How long a scheduled proposal waits. The agent's plans wait 30 minutes,
#: because the person is in the chat that asked; nobody is waiting on this one.
TIDY_PLAN_TTL_SECONDS = 7 * 24 * 60 * 60
_TIDY_CHAT_NAMESPACE = uuid.UUID("6f1c2d3e-b106-4d0c-9e1a-5d0c1d7a0b06")


def tidy_chat_id(owner: str) -> str:
    """The owner's Documents Tidy chat — the same id every run, so one chat
    holds every proposal and the next replaces the last (`propose_plan`)."""
    return str(uuid.uuid5(_TIDY_CHAT_NAMESPACE, f"documents-tidy:{owner}"))


def _ensure_tidy_chat(owner: str) -> str:
    from core.database import SessionLocal, Session as DbSession, utcnow_naive

    session_id = tidy_chat_id(owner)
    db = SessionLocal()
    try:
        if db.query(DbSession.id).filter(DbSession.id == session_id).first() is None:
            now = utcnow_naive()
            db.add(DbSession(id=session_id, name=TIDY_CHAT_NAME, owner=owner,
                             folder=TIDY_CHAT_FOLDER, endpoint_url="", model="",
                             created_at=now, updated_at=now))
            db.commit()
    finally:
        db.close()
    return session_id


def post_to_tidy_chat(session_id: str, role: str, content: str, metadata=None) -> None:
    """Persist one message in a tidy chat, as a row.

    Not through the session manager: a chat it has cached is re-read when it
    holds fewer messages than the table (`SessionManager.get_session`), so a row
    is seen by the next reader either way — and a row is the one write that
    lands in the database this module is pointed at, whatever singleton a
    caller left behind. The chat's counters move as `_persist_message` moves
    them, so it surfaces in the sidebar as a chat with news.
    """
    from core.database import SessionLocal, ChatMessage, Session as DbSession, utcnow_naive

    db = SessionLocal()
    try:
        now = utcnow_naive()
        db.add(ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role=role,
                           content=content, timestamp=now,
                           meta_data=json.dumps(metadata) if metadata else None))
        row = db.query(DbSession).filter(DbSession.id == session_id).first()
        if row is not None:
            row.message_count = (row.message_count or 0) + 1
            row.last_message_at = now
            row.updated_at = now
        db.commit()
    finally:
        db.close()


def propose_document_tidy(owner: str):
    """The scheduled tidy's proposal for *owner*, or ``None`` with nothing to
    propose. Deletes nothing.

    Judges only *owner*'s live documents — the ones a person can see and so
    can be asked about, the agent's tidy's scope (`B994`). Returns ``(plan,
    judged)``; the plan's ``review`` is what the notification and the answer
    route show.
    """
    from core.database import SessionLocal, Document
    from src import document_folders as F
    from src.agent_tools.document_tools import MAX_CHANGES_PER_CALL

    if not owner:
        raise ValueError("a tidy proposal is one person's")
    db = SessionLocal()
    try:
        docs = (db.query(Document)
                .filter(Document.owner == owner)
                .filter(Document.is_active == True)  # noqa: E712 — SQL
                .all())
        judged = len(docs)
        reasons = tidy_reasons(docs)
        if not reasons:
            return None, judged
        ids = list(reasons)
        more = max(0, len(ids) - MAX_CHANGES_PER_CALL)
        ids = ids[:MAX_CHANGES_PER_CALL]
        steps = [{"action": "delete", "document_ids": ids}]
        try:
            changes = F.run_steps(db, owner, steps)
        finally:
            db.rollback()   # nothing happens until the person says so
    finally:
        db.close()
    for c in changes:
        if c.get("change") == "deleted":
            c["reason"] = reasons.get(c.get("id"))
    session_id = _ensure_tidy_chat(owner)
    shown = F.shown_changes(changes)
    count = F.deletes(changes)
    word = "document" if count == 1 else "documents"
    review = {
        "kind": "document_plan",
        "title": TIDY_CHAT_NAME,
        "summary": (f"{count} {word} look like clutter. Nothing is deleted until you say so."),
        "question": (f"Delete these {count} {word}? A deleted document can't be brought "
                     "back from the library."),
        "items": [{"label": c.get("title") or "Untitled", "note": c.get("reason") or ""}
                  for c in shown],
        "more": more,
        "count": count,
        "approve": F.PLAN_APPROVE_LABEL,
        "decline": F.PLAN_DECLINE_LABEL,
    }
    plan = F.propose_plan(owner, session_id, steps, changes,
                          ttl_seconds=TIDY_PLAN_TTL_SECONDS, review=review)
    review["plan_id"] = plan.plan_id
    lines = "\n".join("- " + F.describe_change(c) for c in shown)
    tail = (f"\nThat is the first {len(ids)} of {len(ids) + more}; the next tidy offers the rest."
            if more else "")
    post_to_tidy_chat(session_id, "assistant", (
        f"Documents Tidy would delete {count} of your {judged} documents. "
        f"Nothing has been deleted.\n{lines}{tail}\n"
        "Pantheon asks you on screen; until you choose, everything stays."))
    return plan, judged


def _notify_tidy_proposal(owner: str, plan, task_name: str = TIDY_CHAT_NAME) -> bool:
    """Put the proposal on the scheduler's notification queue for *owner*."""
    try:
        from src.event_bus import get_task_scheduler

        scheduler = get_task_scheduler()
        if scheduler is None:
            return False
        scheduler.add_notification(task_name or TIDY_CHAT_NAME, "success", None,
                                   owner=owner, body=plan.review.get("summary"),
                                   review=dict(plan.review))
        return True
    except Exception:
        logger.warning("Documents Tidy: the proposal for %s could not be put on screen",
                       owner, exc_info=True)
        return False


async def run_document_tidy(owner: str, task_name: str = TIDY_CHAT_NAME) -> str:
    """The scheduled `tidy_documents` action: propose, never delete (`B1006`).

    The rules are `tidy_verdicts`, as they were. What they name becomes a plan
    in the owner's Documents Tidy chat and a notification; nothing is deleted
    here. An owner-less task judges nobody's documents — it used to judge
    every owner's (`if owner: … else: db.query(Document).all()`).
    """
    from src.builtin_actions import TaskNoop

    if not owner:
        raise TaskNoop("Documents Tidy has no owner, so it judged no one's documents. "
                       "Nothing was deleted.")
    plan, judged = propose_document_tidy(owner)
    if plan is None:
        # Nothing to propose: a `skipped` run that says what was looked at.
        raise TaskNoop(f"scanned {judged} document(s), no junk")
    _notify_tidy_proposal(owner, plan, task_name)
    count = plan.review["count"]
    examples = "; ".join(f"{i['label'][:40]} ({i['note']})" for i in plan.review["items"][:5])
    extra = f" (+{count - 5} more)" if count > 5 else ""
    # Said of the run, so it stays true after the person answers: the run row
    # outlives the question, and the answer is recorded in the tidy's chat.
    return (f"Asked you about deleting {count} of {judged}: {examples}{extra}. "
            "This run deleted nothing.")


def answer_review(plan, answer: str) -> dict:
    """The person's answer to a plan offered on a notification (`B1006`).

    The answer is recorded in the plan's chat the way the chat route records a
    person's message — sealed as theirs (`B1005`) — and then the plan is
    applied by `document_folders.apply_plan`, which reads it back from there
    and re-runs the steps against the documents as they are now. So this is
    not a second way to approve a plan: it is a second door for the person to
    say the answer the one way reads, and the route that calls it lets only a
    person through (`auth_helpers.request_is_a_person`). The outcome is said in
    the chat too, so the chat reads as the record of what happened.
    """
    from core.database import SessionLocal
    from src import document_folders as F
    from src.tool_approval_scopes import PERSON_MESSAGE_SEAL_FIELD, seal_person_message

    seal = seal_person_message(plan.session_id, answer)
    post_to_tidy_chat(plan.session_id, "user", answer,
                      {PERSON_MESSAGE_SEAL_FIELD: seal} if seal else None)
    db = SessionLocal()
    try:
        try:
            out = F.apply_plan(db, plan.owner, plan.session_id, plan.plan_id)
        except F.FolderError as e:
            db.rollback()
            if answer == F.PLAN_APPROVE_LABEL:
                outcome, message = "refused", e.message
            else:
                outcome, message = "declined", "Nothing was deleted."
            post_to_tidy_chat(plan.session_id, "assistant", message)
            return {"outcome": outcome, "message": message, "changes": []}
        db.commit()
    finally:
        db.close()
    changes = out["changes"]
    F.forget_deleted(changes)
    shown = F.shown_changes(changes)
    count = F.deletes(changes)
    message = f"Deleted {count} document{'' if count == 1 else 's'}."
    lines = "\n".join("- " + F.describe_change(c) for c in shown)
    post_to_tidy_chat(plan.session_id, "assistant", (
        f"{message}\n{lines}\nDeleted documents can't be brought back from the library."))
    return {"outcome": "applied", "message": message, "changes": shown}
