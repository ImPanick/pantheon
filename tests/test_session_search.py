# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime, timedelta
import asyncio
import sqlite3
import threading
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.database import ChatMessage as DbChatMessage
from core.database import Session as DbSession
from src.session_search import SessionSearchResult, search_session_messages


def _db(with_fts=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    if with_fts:
        db.connection().exec_driver_sql(
            """
            CREATE VIRTUAL TABLE chat_messages_fts USING fts5(
                content,
                message_id UNINDEXED,
                session_id UNINDEXED,
                role UNINDEXED
            )
            """
        )
    return db


def _add_session(db, sid, owner="alice", archived=False, name=None):
    db.add(
        DbSession(
            id=sid,
            name=name or sid,
            endpoint_url="http://example.test",
            model="test-model",
            owner=owner,
            archived=archived,
            message_count=0,
        )
    )


def _add_message(db, sid, mid, role, content, when):
    db.add(DbChatMessage(id=mid, session_id=sid, role=role, content=content, timestamp=when))
    if _has_fts(db):
        db.connection().exec_driver_sql(
            "INSERT INTO chat_messages_fts(content, message_id, session_id, role) VALUES (?, ?, ?, ?)",
            (content, mid, sid, role),
        )


def _has_fts(db):
    return (
        db.connection()
        .exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_messages_fts'")
        .first()
        is not None
    )


def test_session_search_uses_fts_and_returns_context():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "s1", owner="alice", name="Jazz planning")
        _add_message(db, "s1", "m1", "user", "Before context about music", base)
        _add_message(db, "s1", "m2", "assistant", "We talked about modal jazz theory", base + timedelta(minutes=1))
        _add_message(db, "s1", "m3", "user", "After context about tasks", base + timedelta(minutes=2))
        db.commit()

        results = search_session_messages("modal jazz", owner="alice", db=db)

        assert [r.message_id for r in results] == ["m2"]
        assert results[0].session_name == "Jazz planning"
        assert results[0].context_before[0]["message_id"] == "m1"
        assert results[0].context_after[0]["message_id"] == "m3"
        assert "modal" in results[0].content_snippet.lower()
    finally:
        db.close()


def test_session_search_escapes_like_wildcards_in_fallback():
    db = _db(with_fts=False)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "s1", owner="alice")
        _add_message(db, "s1", "literal", "user", "The literal token is foo_bar.", base)
        _add_message(db, "s1", "wild", "user", "The wildcard-looking token is fooXbar.", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages("foo_bar", owner="alice", db=db)

        assert [r.message_id for r in results] == ["literal"]
    finally:
        db.close()


def test_session_search_owner_scope_includes_legacy_and_excludes_other_users():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "alice", owner="alice")
        _add_session(db, "legacy", owner=None)
        _add_session(db, "bob", owner="bob")
        _add_message(db, "alice", "m-alice", "user", "shared recall target", base)
        _add_message(db, "legacy", "m-legacy", "user", "shared recall target", base + timedelta(minutes=1))
        _add_message(db, "bob", "m-bob", "user", "shared recall target", base + timedelta(minutes=2))
        db.commit()

        results = search_session_messages("shared recall target", owner="alice", db=db)

        assert {r.message_id for r in results} == {"m-alice", "m-legacy"}
    finally:
        db.close()


def test_session_search_can_exclude_legacy_rows_for_authenticated_ui_scope():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "alice", owner="alice")
        _add_session(db, "legacy", owner=None)
        _add_message(db, "alice", "m-alice", "user", "exact owner target", base)
        _add_message(db, "legacy", "m-legacy", "user", "exact owner target", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages(
            "exact owner target",
            owner="alice",
            include_legacy_owner=False,
            db=db,
        )

        assert [r.message_id for r in results] == ["m-alice"]
    finally:
        db.close()


def test_session_search_ownerless_call_only_sees_legacy_rows():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "alice", owner="alice")
        _add_session(db, "legacy", owner=None)
        _add_message(db, "alice", "m-alice", "user", "ownerless search target", base)
        _add_message(db, "legacy", "m-legacy", "user", "ownerless search target", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages("ownerless search target", owner=None, db=db)

        assert [r.message_id for r in results] == ["m-legacy"]
    finally:
        db.close()


def test_session_search_falls_back_to_like_when_fts_has_no_substring_hits():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "s1", owner="alice")
        _add_message(db, "s1", "m1", "user", "We discussed customidentifier routing.", base)
        db.commit()

        results = search_session_messages("identifier", owner="alice", db=db)

        assert [r.message_id for r in results] == ["m1"]
        assert "identifier" in results[0].content_snippet
    finally:
        db.close()


def test_session_search_merges_like_substring_hits_with_fts_hits():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "s1", owner="alice")
        _add_message(db, "s1", "m-token", "user", "The identifier token is standalone.", base)
        _add_message(db, "s1", "m-substring", "assistant", "We also discussed customidentifier routing.", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages("identifier", owner="alice", db=db)

        assert {r.message_id for r in results} == {"m-token", "m-substring"}
    finally:
        db.close()


def test_session_search_can_preserve_unrestricted_no_auth_route_scope():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "owned", owner="admin")
        _add_session(db, "legacy", owner=None)
        _add_message(db, "owned", "m-owned", "user", "no auth search target", base)
        _add_message(db, "legacy", "m-legacy", "user", "no auth search target", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages(
            "no auth search target",
            owner=None,
            restrict_owner=False,
            db=db,
        )

        assert {r.message_id for r in results} == {"m-owned", "m-legacy"}
    finally:
        db.close()


def test_session_search_excludes_archived_by_default():
    db = _db(with_fts=True)
    try:
        base = datetime(2026, 1, 1, 12, 0, 0)
        _add_session(db, "active", owner="alice")
        _add_session(db, "archived", owner="alice", archived=True)
        _add_message(db, "active", "m-active", "user", "archive filter target", base)
        _add_message(db, "archived", "m-archived", "user", "archive filter target", base + timedelta(minutes=1))
        db.commit()

        results = search_session_messages("archive filter target", owner="alice", db=db)

        assert [r.message_id for r in results] == ["m-active"]
    finally:
        db.close()


def test_chat_messages_fts_migration_backfills_and_tracks_inserts(tmp_path, monkeypatch):
    from core import database as cdb

    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        );
        INSERT INTO chat_messages(id, session_id, role, content)
        VALUES ('m1', 's1', 'user', 'backfilled transcript search');
        """
    )
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")

    cdb._migrate_chat_messages_fts()

    conn = sqlite3.connect(db_path)
    try:
        backfilled = conn.execute(
            "SELECT message_id FROM chat_messages_fts WHERE chat_messages_fts MATCH 'backfilled'"
        ).fetchall()
        assert backfilled == [("m1",)]

        conn.execute(
            "INSERT INTO chat_messages(id, session_id, role, content) VALUES (?, ?, ?, ?)",
            ("m2", "s1", "assistant", "triggered transcript search"),
        )
        triggered = conn.execute(
            "SELECT message_id FROM chat_messages_fts WHERE chat_messages_fts MATCH 'triggered'"
        ).fetchall()
        assert triggered == [("m2",)]
    finally:
        conn.close()


# ══ a restart does not read the transcript index once per message ═════════
#
# `B2018`. `_migrate_chat_messages_fts` runs in every process that imports
# `core.database`: the server when it starts, and every `scripts/pantheon-*`
# call. Its backfill asked the index, for each chat message, whether it held
# that message (`NOT EXISTS (SELECT 1 FROM chat_messages_fts fts WHERE
# fts.message_id = cm.id)`). `message_id` is UNINDEXED in the FTS5 table, so
# each question read the whole index, and the work grew with the square of the
# transcript even when nothing was missing: about a second at 2,000 messages
# and 25 seconds at 8,000 where this was measured. Now the ids the index holds
# are read once into a keyed temp table, and one join finds the messages it
# lacks. Ported from upstream Odysseus 84aa9a91, without its row-count gate and
# with the write lock taken before the index is read; the last two cases below
# say why.

# The backfill as it was before `B2018`, kept as the measure of "the same
# rows". Its CASE is the migration's `fts_content_expr_cm`.
_BACKFILL_BEFORE_B2018 = """
    INSERT INTO chat_messages_fts(content, message_id, session_id, role)
    SELECT CASE WHEN instr(COALESCE(cm.content, ''), ';base64,') > 0
                  OR instr(COALESCE(cm.content, ''), 'data:image/') > 0
                  OR instr(COALESCE(cm.content, ''), 'data:audio/') > 0
                THEN '[inline media omitted from search index]'
                ELSE COALESCE(cm.content, '') END,
           cm.id, cm.session_id, cm.role
    FROM chat_messages cm
    WHERE NOT EXISTS (
        SELECT 1 FROM chat_messages_fts fts
        WHERE fts.message_id = cm.id
    )
"""
_INLINE_IMAGE = "the chart ![chart](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAE=)"


def _transcript_db(path, monkeypatch):
    """A database file with Pantheon's own `chat_messages` table, which the
    migration then works on."""
    from core import database as cdb

    engine = create_engine(f"sqlite:///{path}")
    DbChatMessage.__table__.create(engine)
    engine.dispose()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    return cdb


def _messages(first, count, *, image_every=0):
    rows = []
    for i in range(first, first + count):
        text = f"message {i} about the garden, the budget and the trip"
        if image_every and i % image_every == 0:
            text = f"{_INLINE_IMAGE} for message {i}"
        rows.append((f"m{i:05d}", f"s{i // 40}", "user" if i % 2 else "assistant", text))
    return rows


def _write(path, rows, *, past_the_index=False):
    """Store messages. `past_the_index` stores them with the insert trigger
    gone, as a message written before the index existed, or while another
    process was re-creating its triggers."""
    conn = sqlite3.connect(path)
    try:
        if past_the_index:
            conn.execute("DROP TRIGGER IF EXISTS chat_messages_fts_ai")
        conn.executemany(
            "INSERT INTO chat_messages(id, session_id, role, content) VALUES (?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def _index_rows(path):
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute(
            "SELECT message_id, session_id, role, content FROM chat_messages_fts").fetchall())
    finally:
        conn.close()


class _Sqlite:
    """`core.database`'s `sqlite3`, with its connections opened by `connect`."""

    def __init__(self, connect):
        self.connect = connect

    def __getattr__(self, name):
        return getattr(sqlite3, name)


def _a_restart(cdb, monkeypatch):
    """The migration once, as a start runs it: its work, in thousands of steps
    of SQLite's virtual machine (a measure a busy machine does not change), and
    its seconds."""
    thousands = [0]

    def tick():
        thousands[0] += 1
        return 0

    def connect(*args, **kwargs):
        conn = sqlite3.connect(*args, **kwargs)
        conn.set_progress_handler(tick, 1000)
        return conn

    with monkeypatch.context() as patch:
        patch.setattr(cdb, "sqlite3", _Sqlite(connect))
        started = time.perf_counter()
        cdb._migrate_chat_messages_fts()
        seconds = time.perf_counter() - started
    return thousands[0], seconds


def test_a_restart_does_not_read_the_whole_index_once_per_message(tmp_path, monkeypatch):
    """The defect. A restart over a complete index of 1,000 and then of 4,000
    messages leaves the index rows exactly as they were, and four times the
    messages cost about four times the work. Before `B2018` they cost sixteen
    times as much, and the restart at 4,000 took seconds."""
    measured = {}
    for count in (1000, 4000):
        path = tmp_path / f"app-{count}.db"
        cdb = _transcript_db(path, monkeypatch)
        _write(path, _messages(0, count))
        cdb._migrate_chat_messages_fts()   # the first start indexes them
        before = _index_rows(path)
        assert len(before) == count
        measured[count] = _a_restart(cdb, monkeypatch)
        assert _index_rows(path) == before, "a restart changed the index"
    (small, small_seconds), (large, large_seconds) = measured[1000], measured[4000]
    assert large / small < 8, (
        f"4 times the messages cost {large / small:.1f} times the work "
        f"({small_seconds:.2f}s at 1,000, {large_seconds:.2f}s at 4,000)")


def test_the_messages_the_index_lacks_are_added_as_the_old_backfill_added_them(
        tmp_path, monkeypatch):
    """The same rows as the statement it replaced, on 3,000 messages: 600
    stored through the triggers and 2,400 past them, a few with an inline
    image. Each message is indexed once, and a second start changes nothing."""
    through, past = _messages(0, 600, image_every=97), _messages(600, 2400, image_every=97)
    paths = {}
    for name in ("old", "new"):
        paths[name] = tmp_path / f"{name}.db"
        cdb = _transcript_db(paths[name], monkeypatch)
        cdb._migrate_chat_messages_fts()   # the index and its triggers, on no messages
        _write(paths[name], through)
        _write(paths[name], past, past_the_index=True)

    # Before `B2018`: the old statement, then the media scrub the migration
    # runs after it.
    conn = sqlite3.connect(paths["old"])
    try:
        conn.execute(_BACKFILL_BEFORE_B2018)
        cdb._scrub_legacy_chat_message_fts_media(conn)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{paths['new']}")
    cdb._migrate_chat_messages_fts()

    rows = _index_rows(paths["new"])
    assert rows == _index_rows(paths["old"])
    assert len(rows) == 3000 and len({row[0] for row in rows}) == 3000, (
        "a message is indexed twice, or not at all")
    assert not any(";base64," in row[3] for row in rows)
    cdb._migrate_chat_messages_fts()
    assert _index_rows(paths["new"]) == rows, "a second start changed the index"


def test_equal_row_counts_do_not_hide_a_message_the_index_lacks(tmp_path, monkeypatch):
    """Why upstream's row-count gate is not taken. A message deleted while
    another process was re-creating the triggers keeps its index row, and one
    stored at such a moment gets none. The two tables then hold the same
    number of rows, and a gate on the counts would never index the second
    message. The old backfill indexed it, and so does this one."""
    path = tmp_path / "app.db"
    cdb = _transcript_db(path, monkeypatch)
    cdb._migrate_chat_messages_fts()
    _write(path, [("kept", "s1", "user", "the kept message"),
                  ("gone", "s1", "assistant", "the deleted message")])
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TRIGGER chat_messages_fts_ad")
        conn.execute("DELETE FROM chat_messages WHERE id = 'gone'")
        conn.commit()
    finally:
        conn.close()
    _write(path, [("unseen", "s1", "user", "the walrus nobody indexed")], past_the_index=True)
    conn = sqlite3.connect(path)
    try:
        counts = [conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("chat_messages", "chat_messages_fts")]
    finally:
        conn.close()
    assert counts == [2, 2]

    cdb._migrate_chat_messages_fts()

    conn = sqlite3.connect(path)
    try:
        found = conn.execute(
            "SELECT message_id FROM chat_messages_fts WHERE chat_messages_fts MATCH 'walrus'"
        ).fetchall()
    finally:
        conn.close()
    assert found == [("unseen",)]


def test_a_start_waits_for_a_write_in_progress_as_the_old_backfill_did(tmp_path, monkeypatch):
    """Another process is writing when the backfill begins: the server, say,
    while a `scripts/pantheon-*` call starts. The one statement before `B2018`
    took the write lock first, so it waited for that write and then indexed.
    Reading the index's ids first and asking for the lock after is refused at
    once ("database is locked") and that start skips its backfill, so the lock
    still comes first."""
    path = tmp_path / "app.db"
    cdb = _transcript_db(path, monkeypatch)
    cdb._migrate_chat_messages_fts()
    _write(path, _messages(0, 50), past_the_index=True)

    other = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    finishing = threading.Timer(0.3, other.execute, args=("COMMIT",))
    writing = threading.Event()

    class _Connection(sqlite3.Connection):
        def executescript(self, script):
            cursor = super().executescript(script)
            if not writing.is_set():   # the triggers are in place; the backfill is next
                other.execute("BEGIN IMMEDIATE")
                writing.set()
                finishing.start()
            return cursor

    try:
        with monkeypatch.context() as patch:
            patch.setattr(cdb, "sqlite3", _Sqlite(
                lambda *args, **kwargs: sqlite3.connect(*args, factory=_Connection, **kwargs)))
            cdb._migrate_chat_messages_fts()
    finally:
        if writing.is_set():
            finishing.join()
        other.close()
    assert writing.is_set(), "the other write never began"
    assert len(_index_rows(path)) == 50, "the start skipped its backfill"


def test_search_chats_formats_shared_results(monkeypatch):
    from src import session_search
    from src.tool_implementations import do_search_chats

    # `P9-15c`: the tool passes `report` for the keyword-only sentence.
    def fake_search(query, limit=20, owner=None, include_archived=False, context_messages=1, db=None,
                    report=None):
        return [
            SessionSearchResult(
                message_id="m2",
                session_id="s1",
                session_name="Design notes",
                role="assistant",
                content="We discussed session search.",
                content_snippet="We discussed session search.",
                timestamp="2026-01-01T12:00:00",
                context_before=[{"message_id": "m1", "role": "user", "content": "Can you find old chats?", "timestamp": None}],
                context_after=[{"message_id": "m3", "role": "user", "content": "That helps.", "timestamp": None}],
            )
        ]

    monkeypatch.setattr(session_search, "search_session_messages", fake_search)

    out = asyncio.run(do_search_chats("session search", owner="alice"))

    assert "Design notes" in out["results"]
    assert "Match (assistant): We discussed session search." in out["results"]
    assert "Before (user): Can you find old chats?" in out["results"]
    assert "After (user): That helps." in out["results"]
