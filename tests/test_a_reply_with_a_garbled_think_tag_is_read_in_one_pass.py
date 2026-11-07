# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1920`. A model's reply with a long run around a think tag held the server
for seconds as it was saved.

A reply the chat saves (`save_assistant_response`, and `clean_thinking_for_save`
for a stopped one) goes through `_normalize_thinking` unless it opens with a
closed think block. That looks for reasoning a model wrote before a stray
`<think>` tag with
``^([\s\S]+?)\n*<think(?:ing)?>\s*([\s\S]*?)(?:</think(?:ing)?>)?\s*$``, and
two of its parts went back over one run from every place in it: `\n*`, from
every newline of a run that no tag follows, and the lazy reply with the `\s*$`
after it, from every tab of a run inside the reply. On the loaded test machine
160,000 newlines took 13 to 18 seconds in each place, and a reasoning line, a
tag, a letter and 60,000 tabs 24 to 26, and the regex holds the GIL.

Now `(?<![\s\S]\n)` lets the newlines start only at their first one, and the
reply runs to the end, with a closing tag taken off it after the match
(upstream Odysseus 3d91ad82). The same reasoning and reply come out: 3,000
generated replies read as the old pattern read them. Upstream's second flood,
the tag and then the tabs, is read at once by the old pattern too (`\s*` takes
the tabs and nothing makes it give them back), so the tabs here come after the
reply's first letter.
"""
from __future__ import annotations

import random
import re
import time
import uuid
from types import SimpleNamespace

import pytest

import routes.chat_helpers as chat_helpers
from routes.chat_helpers import clean_thinking_for_save, save_assistant_response

_BUDGET_S = 2.0  # the old pattern took 13 to 26 s on these floods here; the new one, milliseconds
_TABS = "\t" * 60_000
_FLOODS = {
    # (reply, what _normalize_thinking makes of it, the saved reply, its thinking)
    "newlines": ("a" + "\n" * 160_000 + "x", None, None, None),
    "tabs-in-the-reply": ("The user x\n<think>a" + _TABS + "b",
                          "<think>The user x</think>\na" + _TABS + "b", "a" + _TABS + "b", "The user x"),
}


def _normalized(reply):
    return chat_helpers._normalize_thinking(reply), None


def _cleaned_for_save(reply):
    content, metadata = clean_thinking_for_save(reply, {})
    return content, metadata.get("thinking")


def _saved(reply):
    session_id = "b1920-" + uuid.uuid4().hex
    session = SimpleNamespace(model="m", history=[])
    save_assistant_response(session, None, session_id, reply, {"model": "m"}, incognito=True)
    (message,) = chat_helpers._incognito_messages(session_id)
    return message["content"], (message.get("metadata") or {}).get("thinking")


_READERS = {"_normalize_thinking": _normalized, "clean_thinking_for_save": _cleaned_for_save,
            "save_assistant_response": _saved}


@pytest.fixture(autouse=True)
def _own_incognito_store(monkeypatch):
    monkeypatch.setattr(chat_helpers, "_INCOGNITO_CONTEXTS", {})


@pytest.mark.parametrize("reader", list(_READERS))
@pytest.mark.parametrize("flood", list(_FLOODS))
def test_a_reply_of_a_long_run_is_saved_in_one_pass(reader, flood):
    reply, normalized, saved, thinking = _FLOODS[flood]
    started = time.perf_counter()
    got = _READERS[reader](reply)
    assert time.perf_counter() - started < _BUDGET_S
    if reader == "_normalize_thinking":
        assert got == (normalized or reply, None)
    else:
        assert got == (saved or reply, thinking)


@pytest.mark.parametrize("reply, expected", [
    # upstream's three
    ("The user wants a hi.\n\n<think>Hey there!</think>", "<think>The user wants a hi.</think>\nHey there!"),
    ("I should greet.\n<thinking>  Hello  ", "<think>I should greet.</think>\nHello"),
    ("Plain answer <think>x</think>", "Plain answer <think>x</think>"),
    # a closer in another case, with whitespace after it
    ("The user asked twice.\n<think>Answer</THINKING>  \n", "<think>The user asked twice.</think>\nAnswer"),
    # only the last closer comes off, as before
    ("I will reply.<think>a</think></think>", "<think>I will reply.</think>\na</think>"),
    ("I can do it\n\n\n<think>\n\nDone.\n</think>\n\n", "<think>I can do it</think>\nDone."),
    ("Thinking: weigh it\n<think>Yes.", "<think>weigh it</think>\nYes."),
    # one newline before the tag is not reasoning
    ("\n<think>The user x</think>Reply", "\n<think>The user x</think>Reply"),
])
def test_reasoning_before_a_stray_think_tag_still_reads_as_it_did(reply, expected):
    assert chat_helpers._normalize_thinking(reply) == expected


def test_the_save_paths_still_keep_reasoning_before_a_stray_tag_as_thinking():
    reply = "The user wants a hi.\n\n<think>Hey there!</think>"
    assert _cleaned_for_save(reply) == ("Hey there!", "The user wants a hi.")
    assert _saved(reply) == ("Hey there!", "The user wants a hi.")


# The pattern before `B1920`, as the reference: a reply that opens with "The
# user x" and has a tag after it always reads as reasoning, then the reply.
_OLD_GARBLED = re.compile(r'^([\s\S]+?)\n*<think(?:ing)?>\s*([\s\S]*?)(?:</think(?:ing)?>)?\s*$',
                          re.IGNORECASE)
_PIECES = ["\n", "\n\n", " ", "\t", "\r", "\x0b", "\x1c", " ", "a", "Reply.", "<think>", "<THINKING>",
           "</think>", "</Thinking>", "</think >", "<thin", "k>", "<", ">", "/"]
_TAGS = ["<think>", "<thinking>", "<THINK>", "<Thinking>"]


def _as_the_old_pattern_read_it(reply):
    match = _OLD_GARBLED.match(reply)
    return "<think>" + match.group(1).strip() + "</think>\n" + match.group(2).strip()


def test_a_generated_reply_reads_as_the_old_pattern_read_it():
    rng = random.Random(1920)
    differ = []
    for _ in range(3_000):
        head = "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 8)))
        tail = "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 8)))
        reply = "The user x" + head + rng.choice(_TAGS) + tail
        if chat_helpers._normalize_thinking(reply) != _as_the_old_pattern_read_it(reply):
            differ.append(reply)
    assert differ == [], differ[:5]
