# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared session transcript search for UI and agent tools."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import bindparam, text

from core.database import ChatMessage as DBChatMessage
from core.database import Session as DBSession
from core.database import SessionLocal

logger = logging.getLogger(__name__)

SEARCH_ROLES = ("user", "assistant")


@dataclass(frozen=True)
class SessionSearchResult:
    message_id: str
    session_id: str
    session_name: str
    role: str
    content: str
    content_snippet: str
    timestamp: str | None
    context_before: list[dict[str, Any]]
    context_after: list[dict[str, Any]]
    #: `P9-15c`. How it was found: `keyword`, `meaning`, or `both` (`Law 10`).
    match: str = "keyword"

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "role": self.role,
            "content_snippet": self.content_snippet,
            "timestamp": self.timestamp,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "match": self.match,
        }


#: `P9-15c`. Reciprocal-rank fusion's constant: a result's score is the sum of
#: `1 / (RRF_K + rank)` over the lists it is in. 60 is the value the method was
#: published with, and it lets a message found both ways outrank one found
#: first by either alone without letting either list's scores — bm25 and
#: cosine, on scales that cannot be compared — decide anything.
RRF_K = 60


def _meaning_results(db, query: str, limit: int, owner: str | None, include_archived: bool,
                     restrict_owner: bool, include_legacy_owner: bool,
                     report: dict | None) -> list[SessionSearchResult]:
    """`P9-15c`. The messages whose meaning is nearest `query`, read back from
    `chat_messages` through the keyword search's own filters — so a vector
    whose message is gone, archived, or someone else's finds nothing. Empty,
    with `report` saying why, when there is no index to ask."""
    try:
        from src.chat_vector import chat_index

        index = chat_index()
        status = index.status()
        # Narrowed to the person's own rows where that is the whole scope; a
        # legacy-owner or unscoped search reads more and filters below.
        narrow = restrict_owner and not include_legacy_owner
        hits = index.search(query, limit if narrow else limit * 4,
                            owner if narrow else None, restrict=narrow) if status["meaning"] else None
    except Exception as e:  # noqa: BLE001 — a search by keyword still answers
        logger.warning("chat search by meaning failed: %s", e)
        status, hits = {"meaning": False,
                        "sentence": "Searched by keyword only: the search by meaning failed "
                                    "and the server's log says why."}, None
    if report is not None:
        report.update({"meaning": bool(status.get("meaning")) and hits is not None,
                       "sentence": status.get("sentence", "")})
    if not hits:
        return []
    order = [h["message_id"] for h in hits]
    q = (db.query(DBChatMessage, DBSession.name)
         .join(DBSession, DBChatMessage.session_id == DBSession.id)
         .filter(DBChatMessage.id.in_(order), DBChatMessage.role.in_(SEARCH_ROLES)))
    if not include_archived:
        q = q.filter(DBSession.archived == False)  # noqa: E712
    q = q.filter(~DBSession.name.like("SFT trace batch%"))
    if restrict_owner:
        q = _owner_filter(q, owner, include_legacy_owner)
    found = {msg.id: (msg, name) for msg, name in q.all()}
    rows = [(found[mid][0], found[mid][1], _snippet(found[mid][0].content or "", ""))
            for mid in order if mid in found][:limit]
    return [replace(r, match="meaning") for r in _rows_to_results(db, rows, "", 0)]


def _fuse(keyword: list[SessionSearchResult], meaning: list[SessionSearchResult],
          limit: int) -> list[SessionSearchResult]:
    """`P9-15c`. One list from two, by reciprocal-rank fusion (`RRF_K`). A
    message in both keeps its keyword snippet — the words the person typed,
    marked — and is tagged `both`. With no meaning list this is the keyword
    list unchanged."""
    if not meaning:
        return keyword[:limit]
    score: dict[str, float] = {}
    pick: dict[str, SessionSearchResult] = {}
    for results in (keyword, meaning):
        for rank, r in enumerate(results):
            score[r.message_id] = score.get(r.message_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            if r.message_id in pick:
                pick[r.message_id] = replace(pick[r.message_id], match="both")
            else:
                pick[r.message_id] = r
    ordered = sorted(pick, key=lambda mid: -score[mid])
    return [pick[mid] for mid in ordered[:limit]]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _message_to_context(msg: DBChatMessage) -> dict[str, Any]:
    return {
        "message_id": msg.id,
        "role": msg.role,
        "content": msg.content or "",
        "timestamp": _iso(msg.timestamp),
    }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(content: str, query: str, radius: int = 60) -> str:
    content = content or ""
    query = query or ""
    if not query:
        return content[: radius * 2]

    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[: radius * 2]

    start = max(0, idx - radius)
    end = min(len(content), idx + len(query) + radius)
    return ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")


def _sanitize_fts_query(query: str) -> str | None:
    """Convert free text into a conservative FTS5 MATCH query.

    User input can contain FTS5 operators or punctuation that raises
    sqlite3.OperationalError. For transcript search we do not need advanced
    syntax in v1, so keep only words and balanced quoted phrases.
    """
    parts: list[str] = []
    for match in re.finditer(r'"([^"]+)"|[\w][\w._-]*', query, flags=re.UNICODE):
        phrase = match.group(1)
        if phrase is not None:
            phrase = phrase.strip()
            if phrase:
                parts.append('"' + phrase.replace('"', '""') + '"')
            continue

        token = match.group(0).strip("._-")
        if not token:
            continue
        if any(ch in token for ch in "._-"):
            parts.append('"' + token.replace('"', '""') + '"')
        else:
            parts.append(token)

    if not parts:
        return None
    return " ".join(parts)


def _is_sqlite_session(db) -> bool:
    try:
        bind = db.get_bind()
        return getattr(getattr(bind, "dialect", None), "name", None) == "sqlite"
    except Exception:
        return False


def _has_fts_table(db) -> bool:
    if not _is_sqlite_session(db):
        return False
    try:
        row = db.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_messages_fts' LIMIT 1")
        ).first()
        return row is not None
    except Exception as e:
        logger.debug("chat_messages_fts availability check failed: %s", e)
        return False


def _owner_filter(query, owner: str | None, include_legacy_owner: bool):
    if owner is None:
        return query.filter(DBSession.owner.is_(None))
    if not include_legacy_owner:
        return query.filter(DBSession.owner == owner)
    return query.filter((DBSession.owner == owner) | (DBSession.owner.is_(None)))


def _context_for_message(db, msg: DBChatMessage, count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if count <= 0 or not msg.timestamp:
        return [], []
    return _contexts_by_id(db, [(msg.id, msg.session_id)], count).get(msg.id, ([], []))


# `P23-07` (`PERF-M-13`). The messages around every hit, in two statements
# whatever the number of hits. `_context_for_message` asked twice per hit — the
# messages before, the messages after — and both the FTS and the LIKE path
# asked for every hit of their own, including the ones the merge then threw
# away: measured by the perf audit on 8,000 messages, `?q=reminders&limit=20`
# was 84 statements, 82 of them `SELECT chat_messages…`. Now one window query
# numbers each hit session's messages and returns only the rows near a hit, and
# one more reads those rows. A little slack around each hit lets the rule stay
# exactly what it was — the nearest `count` messages strictly before and
# strictly after the hit's timestamp — when neighbours share a timestamp.
_CONTEXT_NEIGHBOURS_SQL = text(
    """
    WITH numbered AS (
        SELECT id, session_id,
               ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp, id) AS rn
        FROM chat_messages
        WHERE session_id IN :sessions AND role IN ('user', 'assistant')
    ),
    anchors AS (
        SELECT id AS anchor_id, session_id, rn FROM numbered WHERE id IN :hits
    )
    SELECT a.anchor_id AS anchor_id, n.id AS id, n.rn - a.rn AS offset
    FROM anchors a
    JOIN numbered n ON n.session_id = a.session_id
     AND n.rn BETWEEN a.rn - :span AND a.rn + :span
    """
).bindparams(bindparam("sessions", expanding=True), bindparam("hits", expanding=True))


def _contexts_by_id(db, hits, count: int) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """`{message_id: (before, after)}` for `hits`, an iterable of
    `(message_id, session_id)`."""
    hits = [(mid, sid) for mid, sid in hits if mid and sid]
    if count <= 0 or not hits:
        return {}
    pairs = db.execute(_CONTEXT_NEIGHBOURS_SQL, {
        "sessions": sorted({sid for _, sid in hits}),
        "hits": sorted({mid for mid, _ in hits}),
        "span": count * 2 + 2,
    }).fetchall()
    ids = {row.id for row in pairs}
    msgs = {m.id: m for m in db.query(DBChatMessage).filter(DBChatMessage.id.in_(ids)).all()} if ids else {}
    around: dict[str, list[tuple[int, DBChatMessage]]] = {}
    for row in pairs:
        found = msgs.get(row.id)
        if found is not None:
            around.setdefault(row.anchor_id, []).append((row.offset, found))
    out = {}
    for anchor_id, rows in around.items():
        anchor = msgs.get(anchor_id)
        stamp = anchor.timestamp if anchor is not None else None
        if not stamp:
            out[anchor_id] = ([], [])
            continue
        rows.sort(key=lambda r: r[0])
        before = [m for off, m in rows if off < 0 and m.timestamp and m.timestamp < stamp][-count:]
        after = [m for off, m in rows if off > 0 and m.timestamp and m.timestamp > stamp][:count]
        out[anchor_id] = ([_message_to_context(m) for m in before], [_message_to_context(m) for m in after])
    return out


def _rows_to_results(db, rows: Iterable[tuple[DBChatMessage, str, str]], query: str, context_messages: int) -> list[SessionSearchResult]:
    rows = list(rows)
    contexts = _contexts_by_id(db, ((msg.id, msg.session_id) for msg, _, _ in rows), context_messages)
    results: list[SessionSearchResult] = []
    for msg, session_name, snippet in rows:
        before, after = contexts.get(msg.id, ([], [])) if msg.timestamp else ([], [])
        content = msg.content or ""
        results.append(
            SessionSearchResult(
                message_id=msg.id,
                session_id=msg.session_id,
                session_name=session_name or "Untitled",
                role=msg.role,
                content=content,
                content_snippet=snippet or _snippet(content, query),
                timestamp=_iso(msg.timestamp),
                context_before=before,
                context_after=after,
            )
        )
    return results


def _with_context(db, results: list[SessionSearchResult], count: int) -> list[SessionSearchResult]:
    """`P23-07`: the merged results, given their context in one pass."""
    contexts = _contexts_by_id(db, ((r.message_id, r.session_id) for r in results if r.timestamp), count)
    return [replace(r, context_before=contexts[r.message_id][0], context_after=contexts[r.message_id][1])
            if r.message_id in contexts else r for r in results]


def _search_like(
    db,
    query: str,
    limit: int,
    owner: str | None,
    include_archived: bool,
    context_messages: int,
    restrict_owner: bool,
    include_legacy_owner: bool,
) -> list[SessionSearchResult]:
    safe_q = _escape_like(query)
    q = (
        db.query(DBChatMessage, DBSession.name)
        .join(DBSession, DBChatMessage.session_id == DBSession.id)
        .filter(
            DBChatMessage.content.ilike(f"%{safe_q}%", escape="\\"),
            DBChatMessage.role.in_(SEARCH_ROLES),
        )
    )
    if not include_archived:
        q = q.filter(DBSession.archived == False)
    q = q.filter(~DBSession.name.like("SFT trace batch%"))
    if restrict_owner:
        q = _owner_filter(q, owner, include_legacy_owner)
    rows = q.order_by(DBChatMessage.timestamp.desc()).limit(limit).all()
    shaped = ((msg, session_name, _snippet(msg.content or "", query)) for msg, session_name in rows)
    return _rows_to_results(db, shaped, query, context_messages)


def _fetch_messages_by_id(db, message_ids):
    """Fetch (message, session_name) for many message ids in a single query.

    The FTS search returns a list of hit ids; fetching each row on its own was an
    N+1 query (one SELECT per hit). Batch them with one IN(...) query and return
    a lookup so the caller can reassemble results in hit (relevance) order.
    """
    if not message_ids:
        return {}
    rows = (
        db.query(DBChatMessage, DBSession.name)
        .join(DBSession, DBChatMessage.session_id == DBSession.id)
        .filter(DBChatMessage.id.in_(message_ids))
        .all()
    )
    return {msg.id: (msg, session_name) for msg, session_name in rows}


def _search_fts(
    db,
    query: str,
    limit: int,
    owner: str | None,
    include_archived: bool,
    context_messages: int,
    restrict_owner: bool,
    include_legacy_owner: bool,
) -> list[SessionSearchResult] | None:
    fts_query = _sanitize_fts_query(query)
    if not fts_query or not _has_fts_table(db):
        return None

    archived_clause = "" if include_archived else "AND s.archived = 0"
    if not restrict_owner:
        owner_clause = ""
    elif owner is None:
        owner_clause = "AND s.owner IS NULL"
    elif not include_legacy_owner:
        owner_clause = "AND s.owner = :owner"
    else:
        owner_clause = "AND (s.owner = :owner OR s.owner IS NULL)"
    params: dict[str, Any] = {"fts_query": fts_query, "limit": limit}
    if restrict_owner and owner is not None:
        params["owner"] = owner

    sql = text(
        f"""
        SELECT
            m.id AS message_id,
            snippet(chat_messages_fts, 0, '', '', '...', 24) AS content_snippet
        FROM chat_messages_fts
        JOIN chat_messages m ON m.id = chat_messages_fts.message_id
        JOIN sessions s ON s.id = m.session_id
        WHERE chat_messages_fts MATCH :fts_query
          {archived_clause}
          {owner_clause}
          AND s.name NOT LIKE 'SFT trace batch%'
          AND m.role IN ('user', 'assistant')
        ORDER BY bm25(chat_messages_fts), m.timestamp DESC
        LIMIT :limit
        """
    )

    try:
        hits = db.execute(sql, params).fetchall()
    except Exception as e:
        logger.debug("FTS session search failed; falling back to LIKE: %s", e)
        return None

    if not hits:
        return None

    by_id = _fetch_messages_by_id(db, [hit[0] for hit in hits])
    rows = []
    for hit in hits:
        found = by_id.get(hit[0])
        if found:
            msg, session_name = found
            rows.append((msg, session_name, hit[1] or ""))
    return _rows_to_results(db, rows, query, context_messages)


def search_session_messages(
    query: str,
    limit: int = 20,
    owner: str | None = None,
    include_archived: bool = False,
    context_messages: int = 1,
    restrict_owner: bool = True,
    include_legacy_owner: bool = True,
    db=None,
    report: dict | None = None,
) -> list[SessionSearchResult]:
    """Search session transcripts by keyword (FTS5 when available, `LIKE`
    otherwise) and by meaning, in one list.

    `owner=None` is deliberately treated as legacy/null-owner scope rather
    than global access.

    `P9-15c`. The meaning half asks `src.chat_vector` for the nearest messages
    and the two lists are fused by rank (`_fuse`); each result says how it was
    found (`match`). With no embedding model set up there is nothing to ask,
    the answer is the keyword search exactly as before, and `report` — when
    given — carries `{"meaning": bool, "sentence": str}`, the sentence the
    search box shows the person.
    """
    query = (query or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit or 20), 100))
    context_messages = max(0, min(int(context_messages or 0), 3))

    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        # `P23-07` (`PERF-M-13`): both paths find hits without context; the
        # merged list gets its context once, below.
        fts_results = _search_fts(
            db,
            query,
            limit,
            owner,
            include_archived,
            0,
            restrict_owner,
            include_legacy_owner,
        )
        like_results = _search_like(
            db,
            query,
            limit,
            owner,
            include_archived,
            0,
            restrict_owner,
            include_legacy_owner,
        )
        keyword: list[SessionSearchResult] = []
        seen: set[str] = set()
        for result in [*(fts_results or []), *like_results]:
            if result.message_id in seen:
                continue
            seen.add(result.message_id)
            keyword.append(result)
            if len(keyword) >= limit:
                break
        meaning = _meaning_results(db, query, limit, owner, include_archived,
                                   restrict_owner, include_legacy_owner, report)
        return _with_context(db, _fuse(keyword, meaning, limit), context_messages)
    finally:
        if owns_db:
            db.close()


def search_session_titles(
    query: str,
    limit: int = 8,
    owner: str | None = None,
    restrict_owner: bool = True,
    include_legacy_owner: bool = True,
    hidden_names: Iterable[str] = (),
    db=None,
) -> list[dict[str, Any]]:
    """`B1249`. The chats whose **name** holds every word typed, newest first.

    The message search above reads `chat_messages` only, so a chat named by
    hand or by the auto-namer was found only through a word that happened to be
    in one of its messages: Ctrl+K *What the survey says* — the chat's own
    title — answered nothing. The browser's list is a page (`list_page`), so
    the title lane is asked of the database, where every chat is, with the
    message search's own rules: the caller's own chats (``owner``, as
    `search_session_messages` scopes them), never an archived one or an SFT
    batch, never a name the sidebar hides (``hidden_names``).

    Each word is a case-insensitive substring of the name (``LIKE``, escaped),
    all of them required, so *survey what* finds it too.
    """
    words = [w for w in re.split(r"\s+", (query or "").strip()) if w]
    if not words:
        return []
    limit = max(1, min(int(limit or 8), 50))
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        from sqlalchemy import func

        recency = func.coalesce(DBSession.last_message_at, DBSession.updated_at, DBSession.created_at)
        q = db.query(DBSession.id, DBSession.name, recency.label("active"))
        for word in words:
            q = q.filter(DBSession.name.ilike(f"%{_escape_like(word)}%", escape="\\"))
        q = q.filter(DBSession.archived == False)  # noqa: E712
        q = q.filter(~DBSession.name.like("SFT trace batch%"))
        hidden = [n for n in hidden_names if n]
        if hidden:
            q = q.filter(func.trim(func.coalesce(DBSession.name, "")).notin_(hidden))
        if restrict_owner:
            q = _owner_filter(q, owner, include_legacy_owner)
        rows = q.order_by(recency.desc(), DBSession.id).limit(limit).all()
        return [{"session_id": sid, "session_name": name or "Untitled",
                 "last_active": active.isoformat() if hasattr(active, "isoformat") else (active or None)}
                for sid, name, active in rows]
    finally:
        if owns_db:
            db.close()
