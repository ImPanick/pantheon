# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx6-export — an export is the whole chat, reasoning and tool calls included.

The owner, 2026-10-09, verbatim:

    chat exporting... I was trying to export the chat so you have it as a log
    with internal thoughts/reasoning from the LLM displayed... but it only
    exports 1 page (top portion of the chat) - never the FULL chat.. i had to
    "save to documents" which puts the chat into the docs... exporting it from
    the docs as a pdf doesnt work, only markdown and docx works.

Two halves, and both were true at once on `99134cf`:

* **The page is one page.** `sessions.js` asks `/api/history/{sid}` for 24
  messages on a desktop and 8 on a phone (`HISTORY_PAGE_LIMIT_DESKTOP`), and
  every item in the chat's Export menu built its own transcript out of
  `#chat-history`. That half is driven in Chromium by
  `tests/test_the_whole_chat_exports_in_a_browser.py`.
* **The route that has the whole chat carried only its words.** `GET
  /api/session/{sid}/export` read all of `session.history` and wrote the text
  of each message and nothing else — no `metadata.thinking`, no
  `metadata.round_thinking`, no `tool_events`. The reasoning is the part the
  owner was trying to capture, and it was the part the export dropped. That is
  what this file measures, through the real router over a real database.
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
from core.session_manager import SessionManager
from routes import session_routes
from routes.history import history_routes
from tests.helpers.signed_in import as_person

OWNER = "ada"
TURNS = 21  # 42 messages — more than the 24 a desktop page draws
T0 = datetime(2026, 10, 1, 9, 0, 0)
SID = "fx6-export-long"


def _database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[DbSession.__table__, DbChatMessage.__table__])
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed(db_factory, sid: str = SID, owner: str = OWNER, turns: int = TURNS) -> int:
    """A chat long enough to be paged, with reasoning and a tool call in it.

    The shapes are the ones the chat route saves: `thinking` alone for a reply
    with no rounds (Chat mode), `round_thinking` plus the joined `thinking` for
    an agent turn, and `tool_events` as `_shown_tool_row` keeps them.
    """
    db = db_factory()
    try:
        db.add(DbSession(id=sid, name="The long export chat", owner=owner,
                         endpoint_url="http://model.test/v1/chat/completions",
                         model="gemma-4-26b", message_count=2 * turns))
        n = 0
        for i in range(1, turns + 1):
            db.add(DbChatMessage(id=f"u-{i}", session_id=sid, role="user",
                                 content=f"Question {i}: what happens on step {i}?",
                                 timestamp=T0 + timedelta(minutes=2 * i)))
            n += 1
            meta = {"model": "gemma-4-26b"}
            if i % 3 == 1:
                meta["thinking"] = f"REASONING-{i}: look this up before answering step {i}."
            if i % 3 == 2:
                meta["round_thinking"] = [
                    f"REASONING-{i}-ROUND-1: plan the search for step {i}.",
                    f"REASONING-{i}-ROUND-2: read what came back for step {i}.",
                ]
                meta["thinking"] = "\n\n".join(meta["round_thinking"])
                meta["tool_events"] = [{
                    "type": "tool_output", "tool": "web_search", "round": 1,
                    "command": f"step {i} details",
                    "output": f"TOOLOUT-{i}: three sources about step {i}.",
                }]
            db.add(DbChatMessage(id=f"a-{i}", session_id=sid, role="assistant",
                                 content=f"Answer {i}: step {i} does the thing.",
                                 meta_data=json.dumps(meta),
                                 timestamp=T0 + timedelta(minutes=2 * i, seconds=30)))
            n += 1
        db.commit()
        return n
    finally:
        db.close()


def _app(monkeypatch, db_factory, person: str = OWNER):
    """The real export route, over this database, asked by `person`."""
    manager = SessionManager(sessions_file=":memory:")
    monkeypatch.setattr(session_routes, "SessionLocal", db_factory)
    monkeypatch.setattr(history_routes, "SessionLocal", db_factory)
    import core.session_manager as sm
    monkeypatch.setattr(sm, "SessionLocal", db_factory)
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(manager, {}))
    app.include_router(history_routes.setup_history_routes(manager))
    return TestClient(as_person(app, person))


@pytest.fixture()
def seeded(monkeypatch):
    engine, db_factory = _database()
    count = _seed(db_factory)
    client = _app(monkeypatch, db_factory)
    try:
        yield client, db_factory, count
    finally:
        engine.dispose()


@pytest.fixture()
def exported(seeded):
    """The four formats of one seeded 42-message chat."""
    client, db_factory, count = seeded
    out = {"count": count, "client": client, "db": db_factory}
    for fmt in ("md", "txt", "json", "html"):
        res = client.get(f"/api/session/{SID}/export?fmt={fmt}")
        assert res.status_code == 200, (fmt, res.status_code, res.text[:300])
        out[fmt] = res
    return out


# ── the whole chat, not a page ───────────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["md", "txt", "json", "html"])
def test_every_format_holds_every_message(exported, fmt):
    body = exported[fmt].text
    lost = [i for i in range(1, TURNS + 1) if f"Question {i}:" not in body]
    assert lost == [], f"{fmt} lost questions {lost}"
    lost = [i for i in range(1, TURNS + 1) if f"Answer {i}:" not in body]
    assert lost == [], f"{fmt} lost answers {lost}"


@pytest.mark.parametrize("fmt", ["md", "txt", "json", "html"])
def test_every_format_holds_the_last_message(exported, fmt):
    assert f"Question {TURNS}:" in exported[fmt].text
    assert f"Answer {TURNS}:" in exported[fmt].text


def test_the_first_message_is_outside_the_page_the_chat_draws(exported):
    """What makes this a test of the whole chat and not of a long page:
    Question 1 is 42 messages back, and the browser is only ever handed 24
    (`sessions.js` `HISTORY_PAGE_LIMIT_DESKTOP`), so an export built from the
    rendered page cannot contain it."""
    client = exported["client"]
    page = client.get(f"/api/history/{SID}?limit=24").json()
    drawn = " ".join(str(m.get("content") or "") for m in page["history"])
    assert page["total"] == exported["count"] == 2 * TURNS
    assert len(page["history"]) == 24
    assert "Question 1:" not in drawn, "the page under test must not already hold it"
    for fmt in ("md", "txt", "json", "html"):
        assert "Question 1:" in exported[fmt].text, fmt


# ── the reasoning and the tool calls ────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["md", "txt", "json", "html"])
def test_every_format_carries_the_models_reasoning(exported, fmt):
    body = exported[fmt].text
    assert "REASONING-1: look this up before answering step 1." in body, \
        f"{fmt} dropped metadata.thinking"
    assert "REASONING-2-ROUND-1: plan the search for step 2." in body, \
        f"{fmt} dropped round_thinking"
    assert "REASONING-2-ROUND-2: read what came back for step 2." in body


@pytest.mark.parametrize("fmt", ["md", "txt", "json", "html"])
def test_every_format_carries_the_tool_calls_and_their_results(exported, fmt):
    body = exported[fmt].text
    assert "web_search" in body, f"{fmt} dropped the tool call"
    assert "step 2 details" in body, f"{fmt} dropped the tool's command"
    assert "TOOLOUT-2: three sources about step 2." in body, f"{fmt} dropped its output"


def test_the_json_export_keeps_role_and_content_and_adds_the_rest(exported):
    """`Law 1`: `role` and `content` are the keys this format has always
    carried. The reasoning and the tools are added beside them."""
    data = json.loads(exported["json"].text)
    assert list(data) == ["name", "model", "exported", "messages"]
    assert len(data["messages"]) == 2 * TURNS
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Question 1: what happens on step 1?"
    second = data["messages"][3]
    assert second["role"] == "assistant"
    assert second["content"] == "Answer 2: step 2 does the thing."
    assert second["round_thinking"] == [
        "REASONING-2-ROUND-1: plan the search for step 2.",
        "REASONING-2-ROUND-2: read what came back for step 2.",
    ]
    assert second["thinking"] == "\n\n".join(second["round_thinking"])
    assert second["tools"] == [{
        "tool": "web_search", "round": 1, "status": "done", "exit_code": None,
        "command": "step 2 details",
        "output": "TOOLOUT-2: three sources about step 2.", "stderr": "",
    }]


def test_the_html_export_can_be_printed_on_paper(exported):
    """The chat's PDF item prints this file (`app.js` `_printWholeChat`), so it
    carries print rules of its own — ink-light, and no message split across a
    page break — and marks the reasoning and the tools as their own blocks."""
    body = exported["html"].text
    assert "@media print{" in body
    assert "break-inside:avoid" in body
    # 7 turns reasoned once and 7 reasoned in two rounds — one fold per round.
    assert body.count('<details class="think"') == 7 + 14
    assert body.count('<details class="tool"') == 7
    assert "<title>The long export chat</title>" in body


def test_reasoning_is_the_rounds_or_the_whole_never_both():
    """`Law 7`. A reply keeps its reasoning twice over — each round in
    `round_thinking` and the rounds joined in `thinking` — so a reader that
    takes both prints the same reasoning twice."""
    from routes.session_routes import _thinking_rounds
    rounds = ["first thought", "second thought"]
    assert _thinking_rounds({"round_thinking": rounds,
                             "thinking": "\n\n".join(rounds)}) == rounds
    assert _thinking_rounds({"thinking": "just the one"}) == ["just the one"]
    assert _thinking_rounds({"round_thinking": ["", ""], "thinking": "fallback"}) == ["fallback"]
    assert _thinking_rounds({}) == []
    assert _thinking_rounds({"thinking": "   "}) == []


def test_a_refused_or_failed_tool_call_says_which():
    from routes.session_routes import _tool_rows
    rows = _tool_rows({"tool_events": [
        {"tool": "bash", "round": 1, "output": "no such command", "exit_code": 127},
        {"tool": "bash", "round": 2, "output": "the policy refused it", "blocked": True},
        {"tool": "write_file", "round": 3, "output": "", "ask_user": {"resolved": False}},
        {"tool": "bash", "round": 4, "stdout": "lines", "stderr": "ValueError", "output": "lines"},
    ]})
    assert [r["status"] for r in rows] == ["failed", "refused", "waiting for approval", "done"]
    # `agentThread.toolOutputPanesHtml`'s rule: with an error, stdout is the
    # primary pane and stderr is kept beside it rather than merged away.
    assert rows[3]["output"] == "lines" and rows[3]["stderr"] == "ValueError"
    assert _tool_rows({}) == [] and _tool_rows({"tool_events": "nope"}) == []


def test_a_hidden_message_is_not_in_the_export(monkeypatch):
    """A compaction summary is context for the model, never a turn the person
    had; `/api/history` skips it and so does the export."""
    engine, db_factory = _database()
    db = db_factory()
    try:
        db.add(DbSession(id="s-hidden", name="hidden", owner=OWNER,
                         endpoint_url="http://model.test/v1", model="m", message_count=2))
        db.add(DbChatMessage(id="h1", session_id="s-hidden", role="user",
                             content="VISIBLE-ONE", timestamp=T0))
        db.add(DbChatMessage(id="h2", session_id="s-hidden", role="user",
                             content="HIDDEN-SUMMARY",
                             meta_data=json.dumps({"hidden": True}),
                             timestamp=T0 + timedelta(minutes=1)))
        db.commit()
    finally:
        db.close()
    try:
        body = _app(monkeypatch, db_factory).get("/api/session/s-hidden/export?fmt=md").text
    finally:
        engine.dispose()
    assert "VISIBLE-ONE" in body
    assert "HIDDEN-SUMMARY" not in body


# ── it is still a download, and still only yours ────────────────────────────

@pytest.mark.parametrize("fmt,ext,mime", [
    ("md", "md", "text/markdown"),
    ("txt", "txt", "text/plain"),
    ("json", "json", "application/json"),
    ("html", "html", "text/html"),
])
def test_an_export_is_still_an_attachment(exported, fmt, ext, mime):
    """`FORBIDDEN.md` Part 2 — an export is a download. Streaming it must not
    have cost the header that makes it one. (The nosniff header is the global
    middleware's and is pinned by `tests/test_security_headers*.py`; this app
    is built from routers alone, so it is not asserted here.)"""
    res = exported[fmt]
    cd = res.headers["content-disposition"]
    assert cd.startswith("attachment; filename=")
    assert cd.endswith(f".{ext}")
    assert res.headers["content-type"].startswith(mime)


def test_a_filename_is_still_sanitised(exported):
    res = exported["client"].get(
        f"/api/session/{SID}/export?fmt=md&filename=../../etc/pa ss wd")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == "attachment; filename=.._.._etc_pa_ss_wd"


def test_an_export_route_is_not_a_way_to_read_someone_elses_chat(monkeypatch):
    """`_verify_session_owner` runs before a byte is produced — a streamed body
    must not have moved the check after the response started."""
    engine, db_factory = _database()
    db = db_factory()
    try:
        db.add(DbSession(id="s-theirs", name="not yours", owner="somebody-else",
                         endpoint_url="http://model.test/v1", model="m", message_count=1))
        db.add(DbChatMessage(id="t1", session_id="s-theirs", role="user",
                             content="THEIR-SECRET", timestamp=T0))
        db.commit()
    finally:
        db.close()
    client = _app(monkeypatch, db_factory, person=OWNER)
    try:
        for fmt in ("md", "txt", "json", "html"):
            res = client.get(f"/api/session/s-theirs/export?fmt={fmt}")
            assert res.status_code == 404, fmt
            assert "THEIR-SECRET" not in res.text
        # And nobody at all is refused before the lookup.
        nobody = _app(monkeypatch, db_factory, person=None)
        assert nobody.get("/api/session/s-theirs/export?fmt=md").status_code == 401
    finally:
        engine.dispose()


def test_an_unknown_session_is_404_not_an_empty_file(seeded):
    client, _db, _count = seeded
    assert client.get("/api/session/no-such-session/export?fmt=md").status_code == 404


# ── it streams ──────────────────────────────────────────────────────────────

def test_the_body_is_produced_a_message_at_a_time(monkeypatch):
    """Why streaming rather than paging: `get_session` already hydrates the
    whole history, so the export's cost was never the rows — it was joining
    them into a second full copy as one string and handing that to a third as
    the response body. Each format is a generator now, so the body never holds
    more than one message and a chat too large to build as one string still
    exports whole. Paging would have meant a second reader of the history with
    its own offsets, and an export the caller has to stitch back together is
    an export that can be cut (`Law 14`).

    Called directly, not through the client, because what is under test is the
    shape of the object the route returns and when it does its work.
    """
    import asyncio

    from starlette.responses import StreamingResponse
    from tests.helpers.signed_in import PersonRequest

    engine, db_factory = _database()
    _seed(db_factory)
    manager = SessionManager(sessions_file=":memory:")
    monkeypatch.setattr(session_routes, "SessionLocal", db_factory)
    import core.session_manager as sm
    monkeypatch.setattr(sm, "SessionLocal", db_factory)
    router = session_routes.setup_session_routes(manager, {})
    handler = next(r.endpoint for r in router.routes
                   if getattr(r, "path", "") == "/api/session/{sid}/export")
    try:
        res = handler(PersonRequest(OWNER), SID, fmt="md")
        assert isinstance(res, StreamingResponse), type(res)

        async def _first_two():
            out = []
            async for piece in res.body_iterator:
                out.append(piece)
                if len(out) == 2:
                    break
            return out

        first_two = asyncio.run(_first_two())
    finally:
        engine.dispose()
    # Two pieces off the front, and neither is the whole conversation: the
    # body is produced as it is read, not before.
    assert len(first_two) == 2
    joined = "".join(p if isinstance(p, str) else p.decode() for p in first_two)
    assert "Conversation: The long export chat" in joined
    assert f"Question {TURNS}:" not in joined, "the whole body was built up front"


def test_the_reader_every_format_shares_is_a_generator():
    """`Law 7`: one reader of the history, and it yields."""
    import inspect
    from routes.session_routes import _transcript_entries
    assert inspect.isgeneratorfunction(_transcript_entries)
