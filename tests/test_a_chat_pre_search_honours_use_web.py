# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2017`. A chat sent with `use_web=false` still searched the web first.

`POST /api/chat_stream` reads `use_web` as the raw form string, and
`build_chat_context` handed the context preface `use_web and not skip_web`.
Any non-empty string is true in Python, so `use_web=false` (or `0`, `no`,
`off`) turned the chat pre-search on: the chat's model was asked to write a
search query from the person's message, and the query went to the search
provider. The same route reads the same field strictly for its web tools
(`web_search_enabled_for_turn`), so on that turn the tools were withheld while
the search ran anyway.

Now the pre-search reads the field with that gate's own rule,
`tool_toggle_enabled`: `true` in any case, or a real `True`, searches, and
nothing else does. `B97` keeps every toggle that grants tools or the network
that strict, so `use_web=1`, `yes` and `on` stop searching as well, on
purpose: the route already withheld the web tools for them. Nothing Pantheon
itself sends changes meaning. The composer appends `use_web='true'` only with
the web toggle on, and `/api/chat` parses a real bool.

Upstream Odysseus fixed the same line in 84aa9a91 with a looser reading (`1`,
`yes` and `on` mean yes) and added a skip for agent turns that mention mail,
the calendar or notes. That skip belongs to upstream's agent harness, which
Pantheon does not have, so it is not taken.

Driven (`Law 20`): the real `build_chat_context`, first with a preface that
records what it was asked, then with the real `ChatProcessor` behind it and
only the query-writing model call and the search provider stubbed. The
harness is the shape `tests/test_a_default_is_about_absence.py` uses for the
same call site.
"""
from types import SimpleNamespace

import pytest

import routes.chat_helpers as chat_helpers
from src.tool_policy import web_search_enabled_for_turn

QUESTION = "what is the weather in Lisbon this weekend?"


def _harness(monkeypatch):
    """`build_chat_context` with every stand-in a turn cannot be built
    without; `seen` holds what the preface was called with."""
    seen = {}

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message, user_content=message,
            text_for_context=message, youtube_transcripts=[], attachment_meta=[],
        )

    def fake_add_user_message(sess, chat_handler, preprocessed, incognito=False,
                              from_person=False):
        sess.messages.append({"role": "user", "content": preprocessed.user_content})

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 8192, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", lambda h, p: chat_helpers.PresetInfo(
        temperature=0.7, max_tokens=1024, system_prompt=None, character_name=None))
    monkeypatch.setattr(chat_helpers, "add_user_message", fake_add_user_message)
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {"memory_enabled": False})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id",
                        lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context",
                        lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://192.168.1.50:1234/v1", model="test-model",
        headers={}, messages=[],
    )
    sess.get_context_messages = lambda: list(sess.messages)

    def fake_build_context_preface(**kwargs):
        seen.update(kwargs)
        return [], [], []

    return seen, sess, SimpleNamespace(build_context_preface=fake_build_context_preface)


async def _pre_search_asked(monkeypatch, use_web):
    """What `use_web` the context preface receives for this form value."""
    seen, sess, processor = _harness(monkeypatch)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message=QUESTION, session_id="session-W",
        use_web=use_web,
    )
    return seen["use_web"]


# ══ the field, read at the call site ═══════════════════════════════════════

@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off"])
async def test_a_chat_sent_with_web_search_off_is_not_searched(monkeypatch, raw):
    """The defect. On the code before `B2017` every one of these reached the
    preface as `use_web=True`."""
    assert await _pre_search_asked(monkeypatch, raw) is False, raw


@pytest.mark.parametrize("raw", ["true", "True", "TRUE"])
async def test_a_chat_sent_with_web_search_on_is_still_searched(monkeypatch, raw):
    """`Law 1`. What the composer sends with the web toggle on still searches."""
    assert await _pre_search_asked(monkeypatch, raw) is True, raw


@pytest.mark.parametrize("raw,expected", [(True, True), (False, False), (None, False)],
                         ids=repr)
async def test_what_api_chat_sends_keeps_its_meaning(monkeypatch, raw, expected):
    """`/api/chat` parses `use_web` as `Optional[bool]`. Its three values mean
    what they meant: `None` used to be handed on as `None` and is now `False`,
    which the preface reads the same way, so the truth value is asserted."""
    assert bool(await _pre_search_asked(monkeypatch, raw)) is expected, raw


@pytest.mark.parametrize("raw", ["1", "yes", "on"])
async def test_one_yes_and_on_do_not_search_since_the_route_withholds_the_web_tools_for_them(
        monkeypatch, raw):
    """The narrowing, on record. `B97` keeps a toggle that grants the network
    strict, and the route's web gate (`web_search_enabled_for_turn`) already
    reads these as no; before `B2017` the pre-search read them as yes."""
    assert web_search_enabled_for_turn(None, raw) is False
    assert await _pre_search_asked(monkeypatch, raw) is False, raw


@pytest.mark.parametrize("raw", [
    "true", "True", "false", "False", "0", "1", "no", "yes", "off", "on", "",
    True, False, None,
], ids=repr)
async def test_the_pre_search_and_the_web_tools_read_use_web_the_same_way(monkeypatch, raw):
    """One field, one reading. The chat pre-search runs exactly when the same
    route would hand the turn its web tools for the same `use_web`."""
    asked = await _pre_search_asked(monkeypatch, raw)
    assert bool(asked) is web_search_enabled_for_turn(None, raw), raw


# ══ the real pre-search ═══════════════════════════════════════════════════

class _NoMemory:
    def load(self, owner=None):
        return []

    def increment_uses(self, ids):
        pass


@pytest.mark.parametrize("raw,searched", [
    ("false", False), ("0", False), ("true", True),
], ids=["false", "0", "true"])
async def test_the_search_provider_is_asked_only_when_the_chat_said_true(
        monkeypatch, raw, searched):
    """The real `ChatProcessor.build_context_preface` behind the real call
    site. Before `B2017`, `use_web='false'` sent the person's message to the
    chat's model for a query and the query to the search provider."""
    import src.chat_processor as chat_processor_module
    import src.llm_core as llm_core
    from src.chat_processor import ChatProcessor

    asked_for_a_query = []
    searches = []

    def fake_llm_call(url, model, messages, **kwargs):
        asked_for_a_query.append(messages[-1]["content"])
        return "Lisbon weather this weekend"

    def fake_search(query, time_filter=None, return_sources=False, report=None):
        searches.append(query)
        return "Sunny, 24 degrees.", [{"url": "https://weather.example/lisbon"}]

    monkeypatch.setattr(llm_core, "llm_call", fake_llm_call)
    monkeypatch.setattr(chat_processor_module, "comprehensive_web_search", fake_search)

    _seen, sess, _fake = _harness(monkeypatch)
    processor = ChatProcessor(memory_manager=_NoMemory(),
                              personal_docs_manager=SimpleNamespace(rag_manager=None))
    ctx = await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message=QUESTION, session_id="session-X",
        use_web=raw, use_rag="false",
    )
    sent = "\n".join(str(m.get("content") or "") for m in ctx.messages)
    assert bool(asked_for_a_query) is searched, raw
    assert bool(searches) is searched, raw
    assert bool(ctx.web_sources) is searched, raw
    assert ("Sunny, 24 degrees." in sent) is searched, raw
