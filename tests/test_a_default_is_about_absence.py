# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B152` — `use_rag=0` meant yes, and a default is about absence.

`routes/chat_helpers.py` judged the one HTTP field in this tree that defaults
ON with `(str(use_rag).lower() != "false") if use_rag is not None else True`.
Every spelling except the literal `false` turned retrieval **on**, so a caller
who wrote `use_rag=0`, `use_rag=no` or `use_rag=off` got retrieval anyway, with
nothing logged and nothing in the API saying so.

`B97` held the site rather than converting it, and the reason it gave was real:
this is the only conversion in that row that can take behaviour away instead of
widening. **The hold conflated two things.** A default answers when the field
did not say; it is not a licence to overrule a field that did say. Keeping the
default ON and honouring an explicit *no* are not in tension, and
`request_flag(raw, default=True)` is both at once.

**`B2134`, owner ruling 2026-11-15: absence now means no.** Stored material
reaches the model only when the person attaches it or calls on it, and an
absent `use_rag` searched the person's documents on every API turn and sent up
to 10,000 characters of matches. The rule this file is about stands, one value
over: a default answers only when the field did not say, and now it answers
no. The composer sends the chip's state either way (`static/js/chat.js`).

Every test here drives the real code: the resolver itself, and the real
`build_chat_context` call site through the harness
`tests/test_kv_cache_invalidation_2927.py` already established for it (`Law 14`
— that harness exists, so this file borrows its shape rather than inventing a
second one). Nothing greps a file (`Law 20`) and nothing reloads a module
(`B130`).
"""

import logging
from types import SimpleNamespace

import pytest


# ══ the resolver, driven ═══════════════════════════════════════════════════

# Every value that changes meaning, and it is the whole change. Each of these
# answered **yes** until 2026-09-16 and answers no now, which is what the
# caller wrote.
CHANGED = ("0", "no", "off", "NO", " Off ", 0)

# Every value whose answer is the same before and after. `Law 1` — the row is a
# correction at four spellings, not a new policy for the field.
UNCHANGED_ON = ("true", "1", "yes", "on", 1, 2, -1, True)

# `B2134`: the caller did not say, and the answer to that is now no.
UNSAID = (None, "", "   ", "maybe", {})
UNCHANGED_OFF = ("false", "FALSE", False)


@pytest.mark.parametrize("raw", CHANGED)
def test_a_caller_who_wrote_no_is_told_no(raw):
    """The row. Before the fix every one of these returned `True`."""
    from routes.chat_helpers import rag_requested
    assert rag_requested(raw) is False, raw


@pytest.mark.parametrize("raw", UNCHANGED_ON)
def test_a_caller_who_wrote_yes_is_told_yes(raw):
    from routes.chat_helpers import rag_requested
    assert rag_requested(raw) is True, raw


@pytest.mark.parametrize("raw", UNSAID)
def test_absent_blank_and_unrecognised_mean_the_default_which_is_now_no(raw):
    """An absent field, a blank one and a word nobody recognises all mean *the
    caller did not say*. `B2134`: the answer to that is no, because retrieval
    sends stored material the person did not call on."""
    from routes.chat_helpers import rag_requested
    assert rag_requested(raw) is False, raw


@pytest.mark.parametrize("raw", UNCHANGED_OFF)
def test_the_spelling_that_already_worked_still_works(raw):
    from routes.chat_helpers import rag_requested
    assert rag_requested(raw) is False, raw


def test_an_object_is_not_an_answer():
    """`B190`'s regression, at the site `B97` did not convert. A request field
    that is an arbitrary object *did not say*, so it gets the default — it must
    not be read as a definite yes or no by its own truthiness."""
    from routes.chat_helpers import rag_requested
    assert rag_requested(object()) is False
    assert rag_requested({}) is False
    assert rag_requested([]) is False


def test_the_field_answers_with_the_shared_http_rule_and_not_a_fourth_one():
    """`B97`'s four boundaries stay four. This site now calls the owner of the
    HTTP boundary with its own default rather than spelling a fifth rule."""
    from src.env_flags import request_flag
    from routes.chat_helpers import rag_requested
    for raw in CHANGED + UNCHANGED_ON + UNCHANGED_OFF + UNSAID:
        assert rag_requested(raw) == request_flag(raw, default=False), raw


# ══ the upgrade says so before it does it ══════════════════════════════════

def test_the_change_is_announced_at_the_moment_it_takes_effect(monkeypatch, caplog):
    """`B96`'s remedy, one boundary over. The value lives in the caller's
    request, not in a file this process can rewrite, so the honest half is to
    say it out loud when a call is one the old rule read the other way."""
    import routes.chat_helpers as H
    for raw in ("0", "no", "off"):
        monkeypatch.setattr(H, "_warned_use_rag_spelling", False)
        with caplog.at_level(logging.WARNING, logger="routes.chat_helpers"):
            caplog.clear()
            assert H.rag_requested(raw) is False
        assert any("use_rag" in r.message for r in caplog.records), raw


@pytest.mark.parametrize("raw", ("false", "FALSE", False))
def test_the_spelling_that_already_meant_no_is_not_warned_about(monkeypatch, caplog, raw):
    """It only speaks on calls this actually changes. `str(x).lower() ==
    "false"` is exactly the set the old rule already turned off."""
    import routes.chat_helpers as H
    monkeypatch.setattr(H, "_warned_use_rag_spelling", False)
    with caplog.at_level(logging.WARNING, logger="routes.chat_helpers"):
        caplog.clear()
        assert H.rag_requested(raw) is False
    assert not caplog.records, raw


def test_a_caller_hears_it_once_and_not_on_every_turn(monkeypatch, caplog):
    import routes.chat_helpers as H
    monkeypatch.setattr(H, "_warned_use_rag_spelling", False)
    with caplog.at_level(logging.WARNING, logger="routes.chat_helpers"):
        caplog.clear()
        for _ in range(5):
            H.rag_requested("0")
    assert len([r for r in caplog.records if "use_rag" in r.message]) == 1


# ══ the real call site ═════════════════════════════════════════════════════
#
# `B190` is the cautionary tale for this surface: `B97`'s unification was right
# and still carried a regression no test in any converted file could see,
# because the callers that needed the lost answer lived elsewhere. So the
# resolver above is not the evidence on its own — this drives
# `build_chat_context` and reads what actually reaches the retrieval step.

def _harness(monkeypatch, chat_helpers):
    """The shape `tests/test_kv_cache_invalidation_2927.py` established, cut
    down to the one thing this file asks: what `use_rag` does
    `build_context_preface` receive?"""
    seen = {}

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message, user_content=message,
            text_for_context=message, youtube_transcripts=[], attachment_meta=[],
        )

    def fake_extract_preset(chat_handler, preset_id):
        return chat_helpers.PresetInfo(
            temperature=0.7, max_tokens=1024,
            system_prompt="You are Pantheon.", character_name=None,
        )

    def fake_add_user_message(sess, chat_handler, preprocessed, incognito=False,
                              from_person=False):  # `B1005`'s seal flag
        sess.messages.append({"role": "user", "content": preprocessed.user_content})

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 8192, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", fake_extract_preset)
    monkeypatch.setattr(chat_helpers, "add_user_message", fake_add_user_message)
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id",
                        lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context",
                        lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://192.168.1.50:1234/v1", model="test-model",
        headers={}, messages=[], get_context_messages=lambda: list(sess.messages),
    )

    def fake_build_context_preface(**kwargs):
        seen.update(kwargs)
        return [{"role": "system", "content": "You are Pantheon."}], [], []

    return seen, sess, SimpleNamespace(build_context_preface=fake_build_context_preface)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,expected", [
    ("0", False), ("no", False), ("off", False), ("false", False),
    ("true", True), ("1", True),
])
async def test_the_retrieval_step_is_told_what_the_caller_asked_for(
        monkeypatch, raw, expected):
    """The four `False` rows are the defect: on the tree before this change
    `use_rag='0'`, `'no'` and `'off'` all arrived here as `use_rag=True`."""
    import routes.chat_helpers as chat_helpers
    monkeypatch.setattr(chat_helpers, "_warned_use_rag_spelling", True)
    seen, sess, processor = _harness(monkeypatch, chat_helpers)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="what did I write about vector stores?",
        session_id="session-B", use_rag=raw,
    )
    assert seen["use_rag"] is expected, raw


@pytest.mark.asyncio
async def test_a_caller_who_says_nothing_gets_no_retrieval(monkeypatch):
    """`B2134` (owner ruling 2026-11-15). Until then the field defaulted ON
    and an omitted `use_rag` reached the preface as nothing, so the preface's
    own default (yes) searched the person's documents. Now the answer is always
    said, and for a caller who said nothing it is no; the preface's own default
    is no as well, so no caller of it is surprised by a search."""
    import routes.chat_helpers as chat_helpers
    seen, sess, processor = _harness(monkeypatch, chat_helpers)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="hello there, what is in my notes?",
        session_id="session-C",
    )
    assert seen["use_rag"] is False

    import src.chat_processor as CP
    import inspect
    assert inspect.signature(CP.ChatProcessor.build_context_preface) \
        .parameters["use_rag"].default is False


@pytest.mark.asyncio
async def test_incognito_still_overrides_an_explicit_yes(monkeypatch):
    """`Law 1`. The three suppressions that sit under the field — incognito, a
    blocked tool-preprocessing policy, a research spin-off — are unchanged and
    still win over anything the caller sent."""
    import routes.chat_helpers as chat_helpers
    seen, sess, processor = _harness(monkeypatch, chat_helpers)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="what is in my personal documents?",
        session_id="session-D", use_rag="true", incognito=True,
    )
    assert seen["use_rag"] is False


# ══ a suppression wins over a field nobody sent ═══════════════════════════
#
# `B1788`. The four suppressions above set the effective answer to no, and the
# preface was told only when the caller had sent `use_rag` (or the turn was a
# spin-off or low-signal). The composer sends nothing while the RAG chip is on
# and `/api/chat` never sends the field, so an incognito turn, or one whose
# policy blocks every tool, reached the preface without `use_rag`; its default
# is yes, and the person's documents were searched and put in front of the
# model. Now a no is always said; a plain turn with the field omitted still
# leaves the keyword off (the `B152` test above).
# Upstream Odysseus 2a413814 (#7025) fixed it by always forwarding the value,
# which turns `test_a_caller_who_says_nothing_still_gets_retrieval` red.

@pytest.mark.asyncio
async def test_incognito_stops_retrieval_when_the_caller_said_nothing(monkeypatch):
    import routes.chat_helpers as chat_helpers
    seen, sess, processor = _harness(monkeypatch, chat_helpers)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="what is in my personal documents?",
        session_id="session-E", incognito=True,
    )
    assert seen.get("use_rag") is False


@pytest.mark.asyncio
async def test_a_turn_that_may_not_use_tools_stops_retrieval_when_the_caller_said_nothing(
        monkeypatch):
    import routes.chat_helpers as chat_helpers
    seen, sess, processor = _harness(monkeypatch, chat_helpers)
    await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="what is in my personal documents?",
        session_id="session-F", allow_tool_preprocessing=False,
    )
    assert seen.get("use_rag") is False


class _Index:
    """The personal-documents index, with one document above the threshold."""

    def __init__(self):
        self.searched = []

    def search(self, message, k=5, owner=None):
        self.searched.append(message)
        return [{"similarity": 0.99, "metadata": {"filename": "lease.txt"},
                 "document": "Pets are allowed with a deposit."}]


@pytest.mark.asyncio
@pytest.mark.parametrize("turn,searched", [
    ({"use_rag": "true"}, True),
    ({}, False),
    ({"use_rag": "true", "incognito": True}, False),
    ({"use_rag": "true", "allow_tool_preprocessing": False}, False),
], ids=["asked", "not-asked", "incognito", "no-tools"])
async def test_the_documents_are_searched_only_on_a_turn_that_may_search_them(
        monkeypatch, turn, searched):
    """The real `ChatProcessor.build_context_preface` behind the real call
    site. `B2134`: a turn that did not ask (`use_rag` omitted) is not searched;
    the composer sends `true` with the chip on."""
    import routes.chat_helpers as chat_helpers
    from src.chat_processor import ChatProcessor

    _seen, sess, _fake = _harness(monkeypatch, chat_helpers)
    index = _Index()
    processor = ChatProcessor(
        memory_manager=SimpleNamespace(load=lambda owner=None: [],
                                       increment_uses=lambda ids: None),
        personal_docs_manager=SimpleNamespace(rag_manager=index),
    )
    ctx = await chat_helpers.build_chat_context(
        sess=sess, request=SimpleNamespace(), chat_handler=SimpleNamespace(),
        chat_processor=processor, message="what did the lease say about pets?",
        session_id="session-G", **turn,
    )
    sent = "\n".join(str(m.get("content") or "") for m in ctx.messages)
    assert bool(index.searched) is searched
    assert ("Pets are allowed with a deposit." in sent) is searched
    assert bool(ctx.rag_sources) is searched
