# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2025`. Words a model put around its answer broke a translation and a
calendar classification.

Translation: the reader's Translate (`POST /api/email/translate`) and the
`email_auto_translate` action asked for the text between `<<<TRANSLATION>>>`
and `<<<END>>>`, then ran `_extract_reply` first. That helper fences only
REPLY/SUMMARY/OUTPUT and deletes every `<<<END>>>`, so the search for the
pair could never match. "Here is the translation:", a repeated opener or a
note after `<<<END>>>` was cached in `email_translations` and shown as the
translation, and a reply that opened with reasoning ("We need to ...") came
back empty. Now both read the text after the first opener up to the next
`<<<END>>>`, once think blocks are gone, and nothing else is stripped from
it. `<<<SAME_LANGUAGE>>>` is still read where it was, and inside the markers.

Classification: `classify_events` took everything from the first `[` to the
last `]`, so an array followed by a note naming an item ("[1] could be
social") did not parse and the batch counted as failed. Now each `[` is
decoded on its own.

From upstream Odysseus 218d7624, which fixed the background action only and
in an order that reads markers named inside a think block; the reader's
route, the think-first order and the per-`[` scan are Pantheon's.
"""
import email.utils
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb

BODY = ("Hola Alicia, te escribo para confirmar la reunión del jueves a las diez "
        "en la oficina de la calle Mayor. Un saludo, Ana")
HELLO = "Hi Alicia, I am writing to confirm Thursday's meeting at ten."


def _route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


@pytest.fixture
def scheduled_db(tmp_path, monkeypatch):
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes

    db_path = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", db_path)
    email_helpers._init_scheduled_db()

    def cached():
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "SELECT owner, translation, same_language FROM email_translations"
            ).fetchall()
        finally:
            conn.close()

    return cached


# Each reply is one a person could get today; each was read wrong.
ROUTE_REPLIES = {
    "a preamble before the opener": (
        f"Here is the translation:\n<<<TRANSLATION>>>\n{HELLO}\n<<<END>>>",
        ("translation", HELLO)),
    "a note after the closer": (
        f"<<<TRANSLATION>>>\n{HELLO}\n<<<END>>>\nNote: I kept the informal tone.",
        ("translation", HELLO)),
    "the opener twice": (
        f"<<<TRANSLATION>>>\n<<<TRANSLATION>>>\n{HELLO}\n<<<END>>>",
        ("translation", HELLO)),
    "reasoning first that names the same-language marker": (
        "We need to check the language first. It is Spanish, so not <<<SAME_LANGUAGE>>>."
        f"\n\n<<<TRANSLATION>>>\n{HELLO}\n<<<END>>>",
        ("translation", HELLO)),
    "reasoning first, then a same-language verdict inside the markers": (
        "We need to check the language first.\n\n<<<TRANSLATION>>>\n<<<SAME_LANGUAGE>>>\n<<<END>>>",
        ("same_language", None)),
    "nothing between the markers, then a note": (
        "<<<TRANSLATION>>>\n<<<END>>>\nI could not translate this email.",
        ("error", "Empty response from model")),
}


@pytest.mark.parametrize("reply,outcome", list(ROUTE_REPLIES.values()), ids=list(ROUTE_REPLIES))
async def test_the_translate_button_shows_and_caches_only_the_translation(
        reply, outcome, scheduled_db, monkeypatch):
    import routes.email_routes as email_routes
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core

    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint",
                        lambda kind, owner=None: ("http://llm.test/v1", f"{kind}-model", {}))
    monkeypatch.setattr(endpoint_resolver, "resolve_utility_fallback_candidates",
                        lambda owner=None: [])

    async def model(_candidates, **_kwargs):
        return reply

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)
    translate = _route_endpoint(email_routes.setup_email_routes(), "/api/email/translate", "POST")

    result = await translate({"body": BODY, "subject": "Reunión", "from": "ana@example.com",
                              "target_language": "English"}, owner="alice")

    kind, value = outcome
    if kind == "translation":
        assert result.get("translation") == value, result
        assert scheduled_db() == [("alice", value, 0)]
    elif kind == "same_language":
        assert result.get("same_language") is True, result
        assert scheduled_db() == [("alice", "", 1)]
    else:
        assert result == {"success": False, "error": value}
        assert scheduled_db() == []


class _Mailbox:
    """INBOX with one message, for the action's IMAP calls."""

    def __init__(self, raw: bytes):
        self.raw = raw

    def select(self, *_args, **_kwargs):
        return "OK", [b"1"]

    def uid(self, command, *_args):
        if command == "SEARCH":
            return "OK", [b"7"]
        return "OK", [(b"7 (RFC822 {%d}" % len(self.raw), self.raw), b")"]

    def logout(self):
        return "BYE", []


async def test_the_background_translation_caches_only_the_translation(scheduled_db, monkeypatch):
    import routes.email_helpers as email_helpers
    import src.settings as settings
    import src.task_endpoint as task_endpoint
    from src.builtin_actions import action_email_auto_translate

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    cdb.EmailAccount.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(cdb.EmailAccount(id="acct", owner="alice", name="Personal", enabled=True))
        db.commit()
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(settings, "load_settings",
                        lambda: {"email_auto_translate": True, "email_translate_language": "English"})
    raw = (f"From: Ana <ana@example.com>\r\nTo: alice@example.com\r\nSubject: Reunión\r\n"
           f"Date: {email.utils.formatdate()}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
           f"{BODY}\r\n").encode("utf-8")
    monkeypatch.setattr(email_helpers, "_imap_connect", lambda _account_id=None, owner="": _Mailbox(raw))

    async def model(_messages, **_kwargs):
        return (f"Here is the translation:\n<<<TRANSLATION>>>\n{HELLO}\n<<<END>>>\n"
                "Note: I kept the informal tone.")

    monkeypatch.setattr(task_endpoint, "task_llm_call_async", model)
    try:
        message, ok = await action_email_auto_translate("alice")
    finally:
        engine.dispose()

    assert ok is True, message
    assert "cached 1 translation" in message
    assert scheduled_db() == [("alice", HELLO, 0)]


MARKED_REPLIES = {
    # a marker the model only named while reasoning is not the one read
    "think block naming both markers": (
        "<think>I must answer with <<<TRANSLATION>>> then <<<END>>>.</think>\n"
        "<<<TRANSLATION>>>\nHola.\n<<<END>>>", ("Hola.", False)),
    "think block naming the same-language marker": (
        "<think>It is Spanish, so not <<<SAME_LANGUAGE>>>.</think>\n"
        "<<<TRANSLATION>>>\nHello.\n<<<END>>>", ("Hello.", False)),
    # nothing is stripped from between the markers
    "a translation that opens like reasoning": (
        "<<<TRANSLATION>>>\nWe need to talk about the invoice.\n<<<END>>>",
        ("We need to talk about the invoice.", False)),
    "no closer": ("<<<TRANSLATION>>>\nHola.", ("Hola.", False)),
    # a reply with no markers is read as before
    "no markers": ("Hola, ¿qué tal?", ("Hola, ¿qué tal?", False)),
    "no markers after a think block": ("<think>Easy.</think>\nHola, ¿qué tal?",
                                       ("Hola, ¿qué tal?", False)),
    "same language alone": ("<<<SAME_LANGUAGE>>>", ("", True)),
    "same language after a sentence": ("The email is already in English.\n<<<SAME_LANGUAGE>>>",
                                       ("", True)),
    "nothing": ("", ("", False)),
}


@pytest.mark.parametrize("reply,expected", list(MARKED_REPLIES.values()), ids=list(MARKED_REPLIES))
def test_the_translation_is_what_stands_between_the_markers(reply, expected):
    from routes.email_helpers import _extract_translation

    assert _extract_translation(reply) == expected


@pytest.fixture
def calendar(monkeypatch):
    """Alice's calendar with one event the keyword rules leave to the model."""
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    for model in (cdb.CalendarCal, cdb.CalendarEvent):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager",
                        lambda: SimpleNamespace(is_configured=True))
    start = datetime.utcnow() + timedelta(days=2)
    with factory() as db:
        db.add(cdb.CalendarCal(id="alice-cal", owner="alice", name="Personal"))
        db.add(cdb.CalendarEvent(uid="sam", calendar_id="alice-cal", summary="Catch up with Sam",
                                 dtstart=start, dtend=start + timedelta(hours=1)))
        db.commit()
    yield factory
    engine.dispose()


def _model_answers(monkeypatch, reply):
    from src import builtin_actions, llm_core, task_endpoint

    monkeypatch.setattr(task_endpoint, "resolve_task_candidates",
                        lambda **_kwargs: [("http://llm.test/v1", "model", {})])
    monkeypatch.setattr("src.ai_interaction._memory_manager", None)

    async def quiet(_label):
        return False

    async def model(_candidates, **_kwargs):
        return reply

    monkeypatch.setattr(builtin_actions, "wait_for_interactive_quiet", quiet)
    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)


async def test_a_note_after_the_classification_does_not_fail_the_batch(calendar, monkeypatch):
    from src import builtin_actions

    _model_answers(monkeypatch, '[{"i": 0, "type": "social", "importance": "high"}]\n'
                                "Note: [1] could also be social.")

    message, ok = await builtin_actions.action_classify_events("alice")

    assert ok is True, message
    assert "1 via LLM" in message and "failed" not in message, message
    with calendar() as db:
        event = db.get(cdb.CalendarEvent, "sam")
        assert (event.event_type, event.importance, event.color) == \
            ("social", "high", builtin_actions._TYPE_COLORS["social"])


ANSWER = [{"i": 0, "type": "social", "importance": "high"}]
ANSWER_TEXT = '[{"i": 0, "type": "social", "importance": "high"}]'
CLASSIFIER_REPLIES = {
    "a note naming an item": (ANSWER_TEXT + "\nNote: [1] could also be social.", ANSWER),
    "the array twice": (ANSWER_TEXT + "\n" + ANSWER_TEXT, ANSWER),
    "a bracket in the preamble": ("Results [JSON]:\n" + ANSWER_TEXT, ANSWER),
    "the events echoed first": (
        'EVENTS: [{"i": 0, "title": "Catch up with Sam", "when": "", "loc": ""}]\n' + ANSWER_TEXT,
        ANSWER),
    # objects with other keys are still taken, as the old parse took them
    "other keys": ('[{"i": 0, "kind": "social"}]', [{"i": 0, "kind": "social"}]),
    "no array": ("Nothing to classify.", None),
    "no objects": ("[1, 2] and [3]", None),
}


@pytest.mark.parametrize("raw,expected", list(CLASSIFIER_REPLIES.values()),
                         ids=list(CLASSIFIER_REPLIES))
def test_the_classification_is_found_whatever_surrounds_it(raw, expected):
    from src.builtin_actions import _classification_array

    assert _classification_array(raw) == expected
