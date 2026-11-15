# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2132`: an earlier turn's attachments go with that turn, not every turn
after it, unless the person calls on them again.

The owner, 2026-11-15: *"Ensure documents and other storage materials aren't
constantly passed to the LLM per turn ... unless explicitly attached/called
upon by the user"*, *"documents, markdowns, pdf's, images etc... the whole
suite."* Measured on `fix/agent-lean-turn` before this: a PDF's extracted text
is folded into the message it came with (24,000 characters by default, up to
half the model's window) and that message went in every later request of the
chat; an image's base64 too while the session stayed in memory.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.attachment_refs import (EARLIER_ATTACHMENT_NOTE, SAID_WITH_ATTACHMENTS,
                                 earlier_attachments_as_references)

PDF_TEXT = "[Page 1 text]:\n" + "quarterly revenue figures " * 900
IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 40000}}


def _with_files(said, content, *names):
    return {"role": "user", "content": content, "metadata": {
        "attachments": [{"id": f"up{i}", "name": n, "mime": "application/pdf", "size": 1}
                        for i, n in enumerate(names)],
        SAID_WITH_ATTACHMENTS: said}}


def _chat(latest):
    return [
        {"role": "system", "content": "rules"},
        _with_files("summarise this", "summarise this\n\n" + PDF_TEXT, "Q3-report.pdf"),
        {"role": "assistant", "content": "Revenue rose."},
        _with_files("what's in this picture?",
                    [{"type": "text", "text": "what's in this picture?"}, IMAGE], "cat.png"),
        {"role": "assistant", "content": "A cat."},
        {"role": "user", "content": latest},
    ]


def _sent(messages):
    return "\n".join(str(m.get("content")) for m in messages)


def test_a_later_turn_sends_the_files_names_not_their_contents():
    before = _chat("thanks, now what's 2+2?")
    after = earlier_attachments_as_references(before)
    assert "quarterly revenue" not in _sent(after)
    assert "base64" not in _sent(after)
    assert "summarise this" in after[1]["content"] and "Q3-report.pdf" in after[1]["content"]
    assert EARLIER_ATTACHMENT_NOTE in after[1]["content"]
    assert len(_sent(after)) < len(_sent(before)) // 20
    assert before[1]["content"].endswith("figures "), "the session's own message was changed"


def test_the_newest_message_keeps_its_own_files():
    chat = _chat("x")
    chat[-1] = _with_files("and this one?", [{"type": "text", "text": "and this one?"}, IMAGE], "dog.png")
    after = earlier_attachments_as_references(chat)
    assert after[-1] is chat[-1]


def test_a_file_named_again_is_sent_again():
    after = earlier_attachments_as_references(_chat("compare Q3-report with last year"))
    assert "quarterly revenue" in after[1]["content"]
    assert "base64" not in _sent(after[2:]), "only the file named comes back"


def test_the_file_i_sent_calls_on_the_newest_files():
    after = earlier_attachments_as_references(_chat("look at the screenshot again, what colour is it?"))
    assert "base64" in _sent(after)
    assert "quarterly revenue" not in _sent(after)


def test_the_route_saves_what_the_person_wrote_beside_the_files():
    from routes.chat_helpers import PreprocessedMessage, add_user_message

    added = []
    sess = SimpleNamespace(id="s", add_message=added.append)
    pre = PreprocessedMessage(enhanced_message="summarise this",
                              user_content="summarise this\n\n" + PDF_TEXT,
                              text_for_context="summarise this", youtube_transcripts=[],
                              attachment_meta=[{"id": "up0", "name": "Q3-report.pdf"}])
    add_user_message(sess, SimpleNamespace(update_session_name_if_needed=lambda *a: None), pre)
    assert added[0].metadata[SAID_WITH_ATTACHMENTS] == "summarise this"


def test_the_chat_route_applies_it_after_the_history_is_read():
    import inspect
    from routes import chat_helpers
    src = inspect.getsource(chat_helpers.build_chat_context)
    assert "earlier_attachments_as_references(messages)" in src
