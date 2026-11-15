# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2140` — an open document or email reaches the model only when called on.

Owner ruling 2026-11-15: stored material is not sent each turn unless the person
attaches it or calls on it. Measured on `fix/agent-lean-turn` before the fix:
`_turn_targets_active_document` ended in a bare-word match ("word", "change",
"text", "line", "style", ...), so "In one word, what is the capital of France?"
sent the whole open document, uncapped; the email reader's block (header,
1,800-character preview, about 2,500 characters of rules) went with every turn
an email was open; and a Chat mode turn with a document open was promoted to a
full Agent request whatever it said. The route-level halves are in
`tests/test_what_is_open_and_attached_reaches_the_model.py`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import agent_loop
from src.attachment_refs import SAID_WITH_ATTACHMENTS
from src.open_item_reference import (
    calls_for_writing,
    names_title,
    refers_to_open_email,
    refers_to_open_item,
)

LONG = "Alpha. " * 400


def _doc(content=LONG, title="Field notes", language="markdown"):
    return SimpleNamespace(current_content=content, title=title, language=language, id="d1")


@pytest.mark.parametrize("words", [
    "this document needs a better ending",
    "rewrite the intro",
    "make it shorter",
    "Tighten the second step.",
    "fix the second paragraph",
    "add another stanza",
    "proofread",
    "suggest improvements",
    "any feedback on my essay?",
    "summarize this",
    "what does it say",
    "Use what I gave you and tell me the code word.",
])
def test_words_that_call_on_the_open_item(words):
    assert refers_to_open_item(words)


@pytest.mark.parametrize("words", [
    "In one word, what is the capital of France?",
    "change my calendar to friday",
    "make sure that the server works",
    "who am I?",
    "summarize the news",
    "thoughts on the election",
    "write a python script",
    "Thanks.",
    "",
])
def test_words_that_do_not(words):
    assert not refers_to_open_item(words)


def test_the_title_counts_and_a_generic_one_does_not():
    assert names_title("can you update the q3 plan please", "Q3 Plan")
    assert names_title("open roadmap", "roadmap.md")
    assert not names_title("hi there", "Untitled")
    assert not names_title("a new document please", "New document")


def test_a_long_document_needs_a_reference():
    doc = _doc()
    assert not agent_loop._turn_targets_active_document({"domains": set()}, "In one word, what is 2+2?", doc)
    # The documents domain alone no longer carries a long document.
    assert not agent_loop._turn_targets_active_document({"domains": {"documents"}}, "write a python script", doc)
    assert agent_loop._turn_targets_active_document({"domains": set()}, "rewrite the intro", doc)
    assert agent_loop._turn_targets_active_document({"domains": set()}, "What does Field Notes say about alpha?", doc)


def test_a_short_document_keeps_the_broad_reading():
    """Up to `ACTIVE_DOCUMENT_BROAD_READING_CHARS` the old reading stands, so
    "write a poem" into a near-empty editor still reaches it, at little cost."""
    doc = _doc(content="")
    assert agent_loop._turn_targets_active_document({"domains": {"documents"}}, "write a poem", doc)
    assert agent_loop._turn_targets_active_document({"domains": set()}, "one word answer", doc)


def test_a_continuation_carries_the_reference():
    doc = _doc()
    intent = {"domains": set(), "continuation": True, "retrieval_query": "rewrite the intro\nyes do it"}
    assert agent_loop._turn_targets_active_document(intent, "yes do it", doc)
    assert not agent_loop._turn_targets_active_document({"domains": set()}, "yes do it", doc)


def test_a_long_email_draft_answers_to_email_words_only():
    draft = _doc(content="To: a@b.c\nSubject: Hi\n---\n" + LONG, title="Re: Hi", language="email")
    assert agent_loop._turn_targets_active_document({"domains": set()}, "make the reply friendlier", draft)
    assert not agent_loop._turn_targets_active_document({"domains": set()}, "what time is it in Tokyo?", draft)


def test_an_open_email_is_called_on_by_email_words_or_a_reference():
    email = {"uid": "1", "subject": "Quarterly invoice", "from": "Dana"}
    t = agent_loop._turn_targets_active_email
    assert t({"domains": set()}, "reply and say thanks", email)
    assert t({"domains": set()}, "what does it say", email)
    assert t({"domains": set()}, "is the quarterly invoice paid?", email)
    assert t({"domains": {"email"}}, "anything new?", email)
    assert not t({"domains": set()}, "what is the capital of France?", email)
    assert not t({"domains": set()}, "what is the capital of France?", None)
    assert refers_to_open_email("forward it to Sam")


def test_the_reference_is_read_from_what_the_person_typed():
    """A PDF's text folded into the message is not the person calling on the
    draft beside the chat; the saved words are (`B2139`)."""
    folded = "what's the capital of France?\n\n[report.pdf]\nThis draft paragraph ..."
    msgs = [{"role": "user", "content": folded,
             "metadata": {SAID_WITH_ATTACHMENTS: "what's the capital of France?"}}]
    typed = agent_loop._persons_typed_words(msgs, folded)
    assert typed == "what's the capital of France?"
    assert not agent_loop._turn_targets_active_document({"domains": set()}, typed, _doc())
    assert agent_loop._persons_typed_words([{"role": "user", "content": "hi"}], "hi") == "hi"


def test_writing_words_still_promote_beside_a_document():
    """The route does not know the document's size, so "write a poem" there
    still promotes, and the loop's own reading then decides what is sent."""
    assert calls_for_writing("Write a packing list here.")
    assert not calls_for_writing("Thanks.")
