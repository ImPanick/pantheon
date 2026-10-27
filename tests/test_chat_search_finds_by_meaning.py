# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-15c` — keyword and meaning in one search box.

**Premise corrected 2026-08-27, and measured again here:** the keyword half
shipped (FTS5 and `LIKE` in `src/session_search.py`) and the vector half did
not exist — no collection indexed chat messages, so a search that shared no
word with the message it wanted found nothing. The row asked for three things:
a chat-message embedding lane, an index on write, and a backfill over existing
chats.

`src/chat_vector.py` is the lane — built the way `src/memory_vector.py` builds
memory's, on the in-process index when ChromaDB does not answer; messages are
indexed on save by its worker and the backfill catches up on the rest; and
`search_session_messages` fuses the two lists by rank, each result saying how
it was found. With no embedding model set up — this machine, and every fresh
install until someone links one (`Law 16`) — the search is the keyword search
it always was, and says so.

Driven: a real `LocalIndexClient` on a temp directory and the real
`build_embedding_lanes` with a small concept embedder standing in for the model
(a model is a download this environment refuses), a real temp SQLite with the
FTS table, the real `SessionManager` for the write and delete hooks, the real
app booted with no embedding model, and the shipped palette module under node.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from test_the_search_box_is_the_command_palette_js import _chats, _palette, box  # noqa: F401
from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parents[1]

#: The stand-in model: three concepts and a hashed spread for every other word,
#: so two messages about the same thing are near and two that merely share
#: filler are not.
_CONCEPTS = {
    "crash": 0, "crashed": 0, "exception": 0, "traceback": 0, "segfault": 0, "broke": 0, "error": 0,
    "holiday": 1, "vacation": 1, "beach": 1, "flight": 1, "trip": 1,
    "recipe": 2, "bake": 2, "pasta": 2, "dinner": 2,
}
_DIM = 3 + 61


class ConceptEmbedder:
    model = "concept-test"
    url = "test://concepts"

    def get_sentence_embedding_dimension(self):
        return _DIM

    def encode(self, texts, normalize_embeddings=True):
        out = []
        for text in texts:
            v = [0.0] * _DIM
            for word in re.findall(r"[a-z]+", str(text).lower()):
                if word in _CONCEPTS:
                    v[_CONCEPTS[word]] += 3.0
                else:
                    v[3 + int(hashlib.sha1(word.encode()).hexdigest(), 16) % 61] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


@pytest.fixture
def db(monkeypatch, tmp_path):
    import core.database as database
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, tmp = make_temp_sqlite(database.Base.metadata)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE VIRTUAL TABLE chat_messages_fts USING fts5("
                             "content, message_id UNINDEXED, session_id UNINDEXED, role UNINDEXED)")
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    import core.session_manager as sm_module
    monkeypatch.setattr(sm_module, "SessionLocal", SessionLocal, raising=False)
    s = SessionLocal()
    yield s
    s.close()
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _index(monkeypatch, tmp_path, *, model=True):
    """A fresh `ChatVectorIndex` on a real in-process index, made the one
    `session_search` asks, with its lanes built as the worker builds them."""
    from src import chat_vector, embedding_lanes
    from src.local_collection import LocalIndexClient

    monkeypatch.setattr(embedding_lanes, "index_client",
                        lambda: LocalIndexClient(str(tmp_path / "vectors")))

    def no_fastembed():
        raise embedding_lanes.ModelDownloadNotPermitted("the local embedding model is not downloaded")

    def custom():
        if not model:
            raise RuntimeError("HTTP embedding lane unavailable")
        return ConceptEmbedder()

    monkeypatch.setattr(embedding_lanes, "_build_fastembed_client", no_fastembed)
    monkeypatch.setattr(embedding_lanes, "_build_custom_client", custom)
    monkeypatch.setattr(chat_vector, "_BATCH_PAUSE_SECONDS", 0.0)
    index = chat_vector.ChatVectorIndex()
    monkeypatch.setattr(chat_vector, "chat_index", lambda: index)
    return index


def _session(db, sid, owner):
    from core.database import Session as DbSession

    db.add(DbSession(id=sid, name=f"chat {sid}", endpoint_url="http://example.test", model="m",
                     owner=owner, archived=False, message_count=0))


def _message(db, sid, mid, role, content, minutes):
    from core.database import ChatMessage as DbChatMessage

    db.add(DbChatMessage(id=mid, session_id=sid, role=role, content=content,
                         timestamp=datetime(2026, 10, 1, 12, 0) + timedelta(minutes=minutes)))
    db.connection().exec_driver_sql(
        "INSERT INTO chat_messages_fts(content, message_id, session_id, role) VALUES (?, ?, ?, ?)",
        (content, mid, sid, role))


@pytest.fixture
def chats(db):
    _session(db, "a1", "alice")
    _message(db, "a1", "m-exc", "user", "Here is the exception I got when the build broke last night", 1)
    _message(db, "a1", "m-trip", "assistant", "Booked the beach holiday for May", 2)
    _session(db, "a2", "alice")
    _message(db, "a2", "m-literal", "user", "The app will crash on start with an error", 3)
    _session(db, "b1", "bob")
    _message(db, "b1", "m-bob", "user", "My server crashed with a traceback and a segfault", 4)
    db.commit()
    return db


def _search(db, query, **kw):
    from src.session_search import search_session_messages

    report: dict = {}
    found = search_session_messages(query, owner="alice", restrict_owner=True,
                                    include_legacy_owner=False, db=db, report=report, **kw)
    return found, report


def test_a_query_that_shares_no_word_finds_the_message_by_meaning(monkeypatch, tmp_path, chats):
    """The row's `Verify:`: *"crash"* is in no word of the build message, so the
    keyword search alone missed it; by meaning it is found, and says so."""
    keyword_only, _ = _search(chats, "segfault")
    assert keyword_only == [], "premise: no message of alice's holds the word"
    index = _index(monkeypatch, tmp_path)
    index._build()                       # the worker's first act: lanes, then the backfill
    found, report = _search(chats, "segfault")
    assert {r.message_id for r in found} == {"m-exc", "m-literal"}
    assert {r.match for r in found} == {"meaning"}
    assert report == {"meaning": True, "sentence": "Searched by keyword and by meaning."}
    assert "m-trip" not in {r.message_id for r in _search(chats, "traceback")[0]}, \
        "a nearest row that is not near is not a match (MEANING_FLOOR)"


def test_another_persons_messages_never_return(monkeypatch, tmp_path, chats):
    index = _index(monkeypatch, tmp_path)
    index._build()
    for q in ("traceback", "segfault crashed", "server crashed with a traceback"):
        assert "m-bob" not in {r.message_id for r in _search(chats, q)[0]}, q
    # And with the vector search left unnarrowed (the legacy-owner scope), the
    # read-back through `chat_messages` still holds the line.
    from src.session_search import search_session_messages
    wide = search_session_messages("traceback", owner="alice", restrict_owner=True,
                                   include_legacy_owner=True, db=chats)
    assert "m-bob" not in {r.message_id for r in wide}
    hits = index.search("traceback", 10, "alice")
    assert "m-bob" not in {h["message_id"] for h in hits}, "narrowed to alice's rows"


def test_a_message_found_both_ways_comes_first_and_once(monkeypatch, tmp_path, chats):
    index = _index(monkeypatch, tmp_path)
    index._build()
    found, _ = _search(chats, "crash")
    assert found[0].message_id == "m-literal" and found[0].match == "both"
    assert "crash" in found[0].content_snippet, "it keeps the keyword snippet, which marks the word"
    assert [r.message_id for r in found].count("m-literal") == 1
    assert {r.message_id: r.match for r in found}["m-exc"] == "meaning"


def test_with_no_embedding_model_it_searches_by_keyword_and_says_so(monkeypatch, tmp_path, chats):
    from src.chat_vector import KEYWORD_ONLY_SENTENCE
    from src.session_search import search_session_messages

    before = [r.message_id for r in search_session_messages(
        "crash", owner="alice", restrict_owner=True, include_legacy_owner=False, db=chats)]
    index = _index(monkeypatch, tmp_path, model=False)
    index._build()
    assert index.healthy is False
    found, report = _search(chats, "crash")
    assert [r.message_id for r in found] == before == ["m-literal"]
    assert found[0].match == "keyword"
    assert report == {"meaning": False, "sentence": KEYWORD_ONLY_SENTENCE}
    assert "Settings → Embeddings" in KEYWORD_ONLY_SENTENCE


def test_the_backfill_catches_up_and_a_second_run_finds_nothing_to_do(monkeypatch, tmp_path, chats):
    index = _index(monkeypatch, tmp_path)
    index._build()
    lane = index.lanes()[0]
    assert lane.count() == 4, "every searchable message, each person's"
    assert index.backfill() == {"indexed": 0, "missing": 0}
    lane.collection.delete(ids=["m-trip"])            # a run cut short, or a dropped write
    assert index.backfill() == {"indexed": 1, "missing": 1}
    assert lane.count() == 4
    held = lane.collection.get(ids=["m-exc"], include=["metadatas", "documents"])
    assert held["metadatas"][0] == {"owner": "alice", "session_id": "a1"}
    assert not any(held.get("documents") or []), "the index keeps no message text"


def test_a_saved_message_is_indexed_and_a_deleted_chat_leaves_the_index(monkeypatch, tmp_path, db):
    from core.models import ChatMessage
    from core.session_manager import SessionManager

    index = _index(monkeypatch, tmp_path)
    manager = SessionManager()
    manager.create_session("s-new", "New chat", "http://example.test", "m", owner="alice")
    manager.add_message("s-new", ChatMessage("user", "nothing indexed before the app starts it"))
    index._build()
    lane = index.lanes()[0]
    assert lane.count() == 1, "the backfill found the message saved before the start"
    index.start()                                      # what `app.py` does
    manager.add_message("s-new", ChatMessage("user", "Booked a beach trip for the holiday"))
    deadline = time.monotonic() + 10
    while lane.count() < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lane.count() == 2, "indexed by the worker when it was saved"
    from src.session_search import search_session_messages
    found = search_session_messages("vacation", owner="alice", restrict_owner=True,
                                    include_legacy_owner=False, db=db)
    assert [r.match for r in found] == ["meaning"]
    assert manager.delete_session("s-new")
    assert lane.collection.get(where={"session_id": "s-new"})["ids"] == []


# ── the real app, with no embedding model on this machine ───────────────────

_PROBE = r'''
answer = client(ADMIN).get("/api/search", params={"q": "anything", "chats": 1}).json()
RESULT["meaning"] = answer.get("meaning")
RESULT["keys"] = sorted(answer)
RESULT["plain"] = client(ADMIN).get("/api/search", params={"q": "anything"}).json()
'''


def test_the_app_with_no_embedding_model_searches_by_keyword_and_says_why(tmp_path):
    from src.chat_vector import KEYWORD_ONLY_SENTENCE, STARTING_SENTENCE

    out = gated_app_probe(tmp_path, _PROBE, {"EMBEDDING_URL": "", "PANTHEON_ALLOW_MODEL_DOWNLOAD": "0"})
    assert out["keys"] == ["chats", "meaning", "results"]
    assert out["meaning"]["meaning"] is False
    assert out["meaning"]["sentence"] in (KEYWORD_ONLY_SENTENCE, STARTING_SENTENCE)
    assert out["plain"] == [], "the list form `/find` reads is unchanged"


# ── the box: the shipped palette under node ──────────────────────────────────

def test_the_box_says_how_a_chat_was_found_and_when_it_could_not_look_by_meaning(box):  # noqa: F811
    from src.chat_vector import KEYWORD_ONLY_SENTENCE

    out = _palette(box, """
        answer('crash', { status: 200, meaning: { meaning: true, sentence: 'Searched by keyword and by meaning.' },
          body: [row('s1', 'Build', 'Here is the exception I got', { match: 'meaning' }),
                 row('s2', 'Start', 'The app will crash on start', { match: 'both' })] });
        answer('zzqx', { status: 200, body: [],
          meaning: { meaning: false, sentence: %s } });
        open(); type('crash'); await chatsArrive(); const both = read();
        type('zzqx'); await chatsArrive(); const none = read();
        console.log(JSON.stringify({ both, none }));
    """ % repr(KEYWORD_ONLY_SENTENCE))
    rows = [o for g in _chats(out["both"]["groups"]) for o in g["options"]]
    assert [o["how"] for o in rows] == [" · by meaning", None]
    assert rows[1]["marks"] == ["crash"]
    assert re.match(r"^\d+ results?$", out["both"]["status"]), out["both"]["status"]
    assert out["none"]["status"] == f"Nothing matches “zzqx”. {KEYWORD_ONLY_SENTENCE}"
