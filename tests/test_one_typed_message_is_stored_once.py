# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx7-dup (`B-NEW-4`) — one typed message is one row, through the real route.

The owner's own export (`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`,
lines 1 and 4) holds their *"Research: Find out the ins and outs of the new
Oldschool RuneScape Raids…"* twice, and the model's reasoning for the next turn
reads it twice — *"Second section: Research: … Third section: Repeat of research
request"* — so the duplicate was in the prompt, not only in the DOM.

Measured on `3b40a4e`, driving the booted product on 8782 against a recording
OpenAI-compatible model: **one send saves one row and sends one copy on every
path** — plain, `Research:`-prefixed, Chat mode, Agent mode, with and without
web search, through `/api/chat_stream` and through `/api/chat` (8 cases). What
stored the second copy was the **trim** that Retry, *Edit* and *Regenerate* do
before re-sending: each posted `keep_count` = the clicked bubble's index among
`#chat-history`'s `.msg` elements. That is not a row index. An agent turn draws
two `.msg` for one saved reply (`B-NEW-2`'s footer copy), so a two-turn agent
chat drew six bubbles for four rows and the trim ran one row late — keeping the
message it was asked to drop, after which the resend stored a second copy of
it. Measured: `chat_messages` held the typed text twice, a reload drew two
bubbles, and the next provider request carried it twice.

`/api/session/{id}/truncate` now also takes `from_user_message` and resolves it
against its own rows. This file drives that: the resolver on the shapes a real
history has, and the route over a real database — including the premise's own
guard, that the number the browser used to send would still keep the message.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, ChatMessage as DbChatMessage, Session as DbSession
from core.models import ChatMessage, Session as MemSession
from core.session_manager import SessionManager
from routes import session_routes
from routes.history import history_routes
from tests.helpers.signed_in import as_person

OWNER = "ada"
STRANGER = "bob"
SID = "fx7-dup-chat"
T0 = datetime(2026, 10, 9, 9, 0, 0)

RESEARCH = ("Research: Find out the ins and outs of the new Oldschool RuneScape Raids "
            "releasing on October 20th... its called the fractured archive.\n"
            "I mostly want to know, what are we going to expect to fight, and a strategy "
            "to defeat the mobs.")
FOLLOWUP = "Why are you searching for game content on imdb .. and old navy clothing store? Wtf"


# ── the resolver, on the shapes a real history has ──────────────────────────

def _resolve(session, spec):
    """The resolver, imported where it is called rather than at the top of the
    file, so these cases go red on a tree that has not got it yet instead of
    taking the whole module down with a collection error (`Law 20`)."""
    from routes.history.history_routes import _resolve_user_message_cut

    return _resolve_user_message_cut(session, spec)


def _session(*rows):
    """`rows` are `(role, content[, metadata])`, as `session.history` holds them."""
    history = [ChatMessage(role, content, metadata=(meta[0] if meta else None))
               for role, content, *meta in rows]
    return MemSession(id=SID, name="chat", endpoint_url="http://model.test/v1",
                      model="gemma-4-26b", history=history, owner=OWNER)


TWO_AGENT_TURNS = (
    ("user", RESEARCH),
    ("assistant", "Done.", {"round_thinking": ["plan", "read"]}),
    ("user", FOLLOWUP),
    ("assistant", "Done.", {"round_thinking": ["plan", "read"]}),
)


def test_the_newest_user_message_is_the_row_it_is_not_the_bubble():
    """The chat the browser drew as six bubbles. Row 2 is the message; the
    browser used to send 3, which is why the message survived its own trim."""
    session = _session(*TWO_AGENT_TURNS)
    keep, refusal = _resolve(session, {"index_from_end": 0, "text": FOLLOWUP})
    assert refusal is None
    assert keep == 2
    assert [m.role for m in session.history[:keep]] == ["user", "assistant"]
    assert FOLLOWUP not in [m.content for m in session.history[:keep]], \
        "the message being re-sent is not among the rows that are kept"


def test_one_further_back_is_one_user_message_further_back():
    session = _session(*TWO_AGENT_TURNS)
    keep, refusal = _resolve(session, {"index_from_end": 1, "text": RESEARCH})
    assert (keep, refusal) == (0, None)


def test_a_compacted_summary_is_counted_the_way_the_chat_counts_it():
    """A `hidden` compaction row is stored and never drawn (`/api/history`
    filters it out, and `sessions.js` draws only user and assistant rows), so
    the index the browser can count is the displayed one — and it still has to
    land on the right *stored* row."""
    session = _session(
        ("system", "[Conversation summary — 8 earlier messages were compacted]",
         {"compacted": True, "hidden": True}),
        ("assistant", "**Conversation compacted** — 8 messages summarized.", {"compacted": True}),
        ("user", RESEARCH),
        ("assistant", "Done."),
        ("user", FOLLOWUP),
        ("assistant", "Done."),
    )
    keep, refusal = _resolve(session, {"index_from_end": 0, "text": FOLLOWUP})
    assert refusal is None
    assert keep == 4, "the summary is kept — it is history, not a bubble"
    assert session.history[keep].content == FOLLOWUP


def test_a_row_the_chat_never_draws_is_not_counted_whatever_its_role():
    """The index space is the **displayed** one, for every role.

    `/api/history` drops a row whose metadata says `hidden` without looking at
    its role (both its paged and its whole-history branch), and the browser can
    only count what it was drawn. The one writer of `hidden` in the tree today
    makes a `system` row (`history_routes:951`, the compaction summary), so
    nothing in the product produces a hidden `user` row — this case pins the
    rule rather than a current shape, because a count that disagreed with the
    display by one row is exactly this lane's defect.
    """
    session = _session(
        ("user", "An earlier question"),
        ("assistant", "An earlier answer"),
        ("user", "[hidden continuation prompt]", {"hidden": True}),
        ("user", RESEARCH),
        ("assistant", "Done."),
        ("user", FOLLOWUP),
        ("assistant", "Done."),
    )
    drawn = [m for m in session.history if not (m.metadata or {}).get("hidden")]
    assert len(drawn) == 6, "the hidden row is not among the bubbles"
    # Counting the drawn user bubbles back from the newest: 0 is FOLLOWUP,
    # 1 is RESEARCH, 2 is the earlier question — never the hidden row.
    assert _resolve(session, {"index_from_end": 0, "text": FOLLOWUP})[0] == 5
    assert _resolve(session, {"index_from_end": 1, "text": RESEARCH})[0] == 3
    assert _resolve(session, {"index_from_end": 2, "text": "An earlier question"})[0] == 0
    assert _resolve(session, {"index_from_end": 3, "text": ""})[0] is None


def test_the_route_draws_no_hidden_row_of_any_role(chat, monkeypatch):
    """The other half of the rule above, from `/api/history` itself, so the two
    halves are measured against each other and not restated."""
    client, db_factory, _ = chat
    db = db_factory()
    try:
        db.add(DbChatMessage(id="u-hidden", session_id=SID, role="user",
                             content="[hidden continuation prompt]",
                             meta_data=json.dumps({"hidden": True}),
                             timestamp=T0 + timedelta(minutes=1, seconds=30)))
        db.commit()
    finally:
        db.close()
    page = client.get(f"/api/history/{SID}?limit=24").json()["history"]
    assert len(page) == 4, [m.get("content") for m in page]
    assert not any("hidden continuation" in str(m.get("content")) for m in page)
    whole = client.get(f"/api/history/{SID}").json()["history"]
    assert not any("hidden continuation" in str(m.get("content")) for m in whole)


def test_a_message_the_caller_names_that_this_chat_does_not_hold_is_refused():
    """The browser's count and the server's rows disagree only when the chat
    has moved on. Then nothing is cut, and the caller sends nothing."""
    session = _session(*TWO_AGENT_TURNS)
    keep, refusal = _resolve(
        session, {"index_from_end": 0, "text": "Something else entirely"})
    assert keep is None
    assert "reload" in refusal.lower()


def test_a_count_past_the_start_of_the_chat_is_refused_not_clamped():
    session = _session(*TWO_AGENT_TURNS)
    assert _resolve(session, {"index_from_end": 2, "text": ""})[0] is None
    assert _resolve(session, {"index_from_end": -1, "text": ""})[0] is None
    assert _resolve(session, {"index_from_end": "x"})[0] is None
    assert _resolve(session, {})[0] is None


def test_a_chat_with_no_user_message_yet_is_refused():
    session = _session(("assistant", "Welcome."))
    assert _resolve(session, {"index_from_end": 0, "text": "hi"})[0] is None


def test_the_same_words_twice_are_two_messages_and_the_newest_one_wins():
    """Two sends of the same text are two turns — the rule `B-NEW-2` set for a
    reply holds for a question. `index_from_end` says which, and the text check
    cannot tell them apart, so the count has to."""
    session = _session(("user", "again"), ("assistant", "ok"),
                       ("user", "again"), ("assistant", "ok"))
    assert _resolve(session, {"index_from_end": 0, "text": "again"})[0] == 2
    assert _resolve(session, {"index_from_end": 1, "text": "again"})[0] == 0


def test_a_message_whose_text_the_browser_shortened_still_matches():
    """The bubble strips its `[2 attachment(s)]` suffix and a photo turn's row
    is a JSON blob the display reduces to its text parts, so the check is a
    prefix match in either direction, not equality."""
    session = _session(
        ("user", json.dumps([{"type": "text", "text": "Look at these"},
                             {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]),
         {"attachments": [{"id": "u1"}, {"id": "u2"}]}),
        ("assistant", "Two cats."),
    )
    keep, refusal = _resolve(
        session, {"index_from_end": 0, "text": "Look at these"})
    assert (keep, refusal) == (0, None)


# ── the route, over a real database ─────────────────────────────────────────

def _database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[DbSession.__table__, DbChatMessage.__table__])
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed(db_factory):
    """The chat the browser drew as six `.msg` for four rows."""
    db = db_factory()
    try:
        db.add(DbSession(id=SID, name="OSRS raids", owner=OWNER,
                         endpoint_url="http://model.test/v1/chat/completions",
                         model="gemma-4-26b", message_count=4))
        rows = [("u-1", "user", RESEARCH, None),
                ("a-1", "assistant", "Done.", {"round_thinking": ["plan", "read"]}),
                ("u-2", "user", FOLLOWUP, None),
                ("a-2", "assistant", "Done.", {"round_thinking": ["plan", "read"]})]
        for n, (mid, role, content, meta) in enumerate(rows):
            db.add(DbChatMessage(id=mid, session_id=SID, role=role, content=content,
                                 meta_data=json.dumps(meta) if meta else None,
                                 timestamp=T0 + timedelta(minutes=n)))
        db.commit()
    finally:
        db.close()


def _client(monkeypatch, db_factory, person=OWNER):
    manager = SessionManager(sessions_file=":memory:")
    # `_verify_session_owner` reads the owner through its own module's factory.
    monkeypatch.setattr(session_routes, "SessionLocal", db_factory)
    monkeypatch.setattr(history_routes, "SessionLocal", db_factory)
    import core.session_manager as sm
    monkeypatch.setattr(sm, "SessionLocal", db_factory)
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(manager))
    return TestClient(as_person(app, person)), manager


@pytest.fixture()
def chat(monkeypatch):
    engine, db_factory = _database()
    _seed(db_factory)
    client, manager = _client(monkeypatch, db_factory)
    try:
        yield client, db_factory, manager
    finally:
        engine.dispose()


def _rows(db_factory):
    db = db_factory()
    try:
        return [(m.role, m.content) for m in db.query(DbChatMessage)
                .filter(DbChatMessage.session_id == SID)
                .order_by(DbChatMessage.timestamp).all()]
    finally:
        db.close()


def test_the_bubble_count_the_browser_used_to_send_keeps_the_message(chat):
    """The premise's own guard, and it must stay true: `keep_count` means rows,
    so the number the browser counted off the screen — 3 for a chat whose last
    user message is row 2 — leaves that message in place. A resend after this
    cut is the second copy."""
    client, db_factory, _ = chat
    res = client.post(f"/api/session/{SID}/truncate", json={"keep_count": 3})
    assert res.status_code == 200
    assert _rows(db_factory) == [("user", RESEARCH), ("assistant", "Done."), ("user", FOLLOWUP)]


def test_the_message_being_resent_is_gone_before_it_is_sent_again(chat):
    client, db_factory, _ = chat
    res = client.post(f"/api/session/{SID}/truncate",
                      json={"from_user_message": {"index_from_end": 0, "text": FOLLOWUP}})
    assert res.status_code == 200
    assert res.json()["kept"] == 2
    assert _rows(db_factory) == [("user", RESEARCH), ("assistant", "Done.")]


def test_a_refused_cut_removes_nothing(chat):
    """409 and four rows: a trim that cannot be resolved must not become a trim
    at 0, which would take the whole chat, nor one at the wrong row."""
    client, db_factory, _ = chat
    before = _rows(db_factory)
    res = client.post(f"/api/session/{SID}/truncate",
                      json={"from_user_message": {"index_from_end": 0, "text": "not this one"}})
    assert res.status_code == 409
    assert "reload" in res.text.lower()
    assert _rows(db_factory) == before


def test_a_cut_with_nothing_to_cut_at_is_a_bad_request(chat):
    client, db_factory, _ = chat
    before = _rows(db_factory)
    res = client.post(f"/api/session/{SID}/truncate", json={})
    assert res.status_code == 400
    assert _rows(db_factory) == before


def test_a_cut_is_not_a_way_into_someone_elses_chat(monkeypatch):
    """`_verify_session_owner` runs before anything is read or removed."""
    engine, db_factory = _database()
    _seed(db_factory)
    try:
        client, _ = _client(monkeypatch, db_factory, person=STRANGER)
        res = client.post(f"/api/session/{SID}/truncate",
                          json={"from_user_message": {"index_from_end": 0, "text": FOLLOWUP}})
        assert res.status_code in (403, 404), res.status_code
        assert len(_rows(db_factory)) == 4
    finally:
        engine.dispose()


def test_the_in_memory_history_is_cut_with_the_rows(chat):
    """`truncate_messages` cuts both, and the next turn builds its context from
    the in-memory list — a row removed from one and left in the other is the
    duplicate again, one layer down."""
    client, db_factory, manager = chat
    client.post(f"/api/session/{SID}/truncate",
                json={"from_user_message": {"index_from_end": 0, "text": FOLLOWUP}})
    session = manager.get_session(SID)
    assert [m.content for m in session.history] == [RESEARCH, "Done."]
    assert session.message_count == 2


def test_one_typed_message_is_one_row_after_the_cut_and_the_resend(chat):
    """The whole defect, end to end on the server's side: trim, re-send, count.
    Two rows with the same text is what the owner's export shows."""
    client, db_factory, manager = chat
    res = client.post(f"/api/session/{SID}/truncate",
                      json={"from_user_message": {"index_from_end": 0, "text": FOLLOWUP}})
    assert res.status_code == 200
    # What the resend does: `add_user_message` (`routes/chat_helpers.py:522`)
    # appends one `user` ChatMessage and persists it. Through the manager, which
    # is the same append and the same `_persist_message` — `Session.add_message`
    # would reach for the process-wide singleton instead of this test's manager.
    manager.add_message(SID, ChatMessage("user", FOLLOWUP))
    stored = [content for role, content in _rows(db_factory) if role == "user"]
    assert stored.count(FOLLOWUP) == 1, f"the typed message is stored {stored.count(FOLLOWUP)} times"
    assert stored == [RESEARCH, FOLLOWUP]
