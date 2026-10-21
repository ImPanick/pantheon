# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B711`. What the minimal agent routes send, and what the pill says they sent.

Three agent sub-paths cannot carry a full preface — the document route, the
notes route, and the Pantheon-finetune general route — so each rebuilds the
person's memory into one short message. Until this row that rebuild read the
*prose* of the block `build_context_preface` had just written: it stripped the
block's own labels and collected its `- ` lines. A second implementation of
*what is in this message*, built out of the first one's output (`Law 14`).

**Two defects came out of that, and both were measured rather than argued.**

  * A memory whose text runs to a second line arrived with only its first line
    kept, because the join puts the continuation flush left with no marker.
    *"Prefers tea / and not coffee"* reached the model as *"Prefers tea"* —
    a reversal of meaning, not a truncation, and invisible because
    `memories_used` reported the whole memory.
  * Two memories with the same text collapsed into one, because the facts were
    deduplicated as strings. Five memories went in and four came out while the
    trace still named five, each with its own confidence and its own reason —
    and text is exactly the field `find_duplicates` compares *because* it is
    not unique.

**The row's own framing was wrong about the cap and it is worth saying so.**
It reads *"in two agent sub-paths the model sees at most five memories"* as
though five were a second, smaller budget. It is not: `MEMORY_CONTEXT_LIMIT`
is also five, so the two never disagreed on how many. They disagreed on
*which*, and on *what each one said* — which is the harder failure to see,
because a count that matches is a count nobody checks.

So the fix is not a cap and not an intersection after the fact. The preface
records what it injected, the routes read that, and the number is imported
from the one place that owns it. The two sides then agree by construction, and
the cases below drive both rather than comparing two readings of one string.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import chat_processor as cp
from src.chat_processor import (
    ChatProcessor, MEMORY_CONTEXT_LIMIT, MEMORY_FACTS_KEY,
    _attach_memory_facts, memory_bullets,
)
from src.agent_loop import _minimal_saved_memory_message, _saved_memory_facts
from src.prompt_security import own_context_message

ROOT = Path(__file__).resolve().parents[1]


class _Memory:
    def __init__(self, rows):
        self.rows = rows
        self.incremented = []

    def load(self, owner=None):
        return list(self.rows)

    def increment_uses(self, ids):
        self.incremented.extend(ids)


class _Docs:
    rag_manager = None


def _processor(rows):
    return ChatProcessor(memory_manager=_Memory(rows), personal_docs_manager=_Docs())


def _preface(rows, message):
    processor = _processor(rows)
    preface, _, _ = processor.build_context_preface(
        message=message, session=SimpleNamespace(), use_rag=False, use_memory=True)
    return processor, preface


def _sent_facts(preface):
    """The bullets the minimal route actually puts in front of the model."""
    message = _minimal_saved_memory_message(preface)
    if message is None:
        return []
    body = message["content"]
    body = body.split('"me" or "my":\n', 1)[1].rsplit("\n<<<", 1)[0]
    # Re-read the block the way a reader does: a bullet starts a fact and an
    # indented line continues it.
    facts = []
    for line in body.split("\n"):
        if line.startswith("- "):
            facts.append(line[2:])
        else:
            # Exactly the two spaces the renderer added, and nothing else —
            # so the round trip is byte for byte and the claim below is the
            # whole record rather than a tidied version of it.
            assert line.startswith("  "), f"continuation {line!r} has no indent"
            facts[-1] += "\n" + line[2:]
    return facts


# ── the two defects, each as the thing that went wrong ──────────────────────

def test_a_memory_that_runs_to_a_second_line_arrives_whole():
    """*"Prefers tea / and not coffee"* is one memory and it has a `not` in it.

    The old parse kept `- ` lines, so the qualifier was dropped and the model
    was told the opposite of half the record while the trace showed all of it.
    """
    rows = [{"id": "tea", "text": "Drinks tea in the morning\nand never coffee",
             "category": "preference", "pinned": True, "timestamp": 3}]
    _, preface = _preface(rows, "what do I drink in the morning?")
    sent = _sent_facts(preface)
    assert sent == ["Drinks tea in the morning\nand never coffee"]
    assert "never coffee" in "".join(sent), "the qualifier did not reach the model"


def test_two_memories_that_say_the_same_thing_are_two_memories():
    """Deduplicating by text is how five become four with the trace saying five.

    `find_duplicates` compares lower-cased text precisely *because* text is not
    unique, so a rebuild that treats it as a key is using the one field the
    product already decided it could not.
    """
    rows = [
        {"id": "a", "text": "Allergic to shellfish", "category": "fact",
         "pinned": True, "timestamp": 3},
        {"id": "b", "text": "Allergic to shellfish", "category": "fact",
         "pinned": True, "timestamp": 2},
    ]
    _, preface = _preface(rows, "am I allergic to shellfish?")
    facts = _saved_memory_facts(preface)
    assert [f["id"] for f in facts] == ["a", "b"]
    assert len(_sent_facts(preface)) == 2


# ── the claim the row is actually about ─────────────────────────────────────

@pytest.mark.parametrize("question,rows", [
    ("what do you know about me?", [
        {"id": "n", "text": "User's name is Felix.", "category": "identity",
         "pinned": True, "timestamp": 5},
        {"id": "v", "text": "Drives a blue van", "category": "fact",
         "pinned": False, "timestamp": 4},
        {"id": "t", "text": "Drinks tea\nand never coffee", "category": "preference",
         "pinned": True, "timestamp": 3},
    ]),
    ("tell me about my van", [
        {"id": "v", "text": "Drives a blue van", "category": "fact",
         "pinned": False, "timestamp": 4},
        {"id": "x", "text": "Van is a 2014 Transit", "category": "fact",
         "pinned": False, "timestamp": 3},
    ]),
])
def test_the_facts_sent_are_the_memories_the_trace_names(question, rows):
    """The whole row, as one assertion: same records, same order, same words.

    Driven on both sides — `build_context_preface` writes the trace and the
    minimal route builds the prompt — so this fails if either moves without
    the other.
    """
    processor, preface = _preface(rows, question)
    traced = processor._last_used_memories
    assert traced, "this case needs the preface to have injected something"
    assert [row["text"] for row in traced] == _sent_facts(preface)
    assert [row["id"] for row in traced] == [f["id"] for f in _saved_memory_facts(preface)]


def test_nothing_recalled_means_no_memory_message_at_all():
    """An empty block is not an honest one: a route with nothing to say says
    nothing rather than sending an empty list under a heading."""
    _, preface = _preface([], "what is a decorator?")
    assert _minimal_saved_memory_message(preface) is None
    assert _saved_memory_facts(preface) == []


# ── one budget, one value ───────────────────────────────────────────────────

def test_the_cap_is_the_prefaces_own_limit_and_moves_with_it(monkeypatch):
    """It was a bare `5` here and `MEMORY_CONTEXT_LIMIT = 5` there — one rule
    with two values the day somebody tunes either. Driven by tuning it."""
    rows = [{"id": str(i), "text": f"Fact number {i}", "category": "fact",
             "pinned": True, "timestamp": 10 - i} for i in range(8)]
    monkeypatch.setattr(ChatProcessor, "MEMORY_CONTEXT_LIMIT", 3)
    monkeypatch.setattr(ChatProcessor, "PINNED_MEMORY_LIMIT", 3)
    monkeypatch.setattr("src.agent_loop.MEMORY_CONTEXT_LIMIT", 3)
    processor, preface = _preface(rows, "list every fact number you know")
    assert len(processor._last_used_memories) <= 3
    assert len(_sent_facts(preface)) == len(processor._last_used_memories)


def test_the_two_modules_read_one_constant():
    """`agent_loop` imports the number rather than restating it."""
    import src.agent_loop as agent_loop
    assert agent_loop.MEMORY_CONTEXT_LIMIT is MEMORY_CONTEXT_LIMIT
    assert ChatProcessor.MEMORY_CONTEXT_LIMIT == MEMORY_CONTEXT_LIMIT
    source = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    body = source[source.index("def _minimal_saved_memory_message"):]
    body = body[:body.index("\ndef ", 1)]
    assert not re.search(r"\[:\s*5\s*\]", body), (
        "the cap is written out again instead of being the imported one")


# ── the renderer ────────────────────────────────────────────────────────────

def test_a_continuation_is_indented_under_its_bullet():
    """Flush left, a memory's second line is a new item to any reader —
    including the model, which is the half that stayed after the parser was
    fixed."""
    assert memory_bullets(["One line", "Two\nlines"]) == "- One line\n- Two\n  lines"
    assert memory_bullets(["", "   ", "kept"]) == "- kept"
    # Exactly two spaces, nothing else touched — a memory that indents its own
    # continuation keeps that indent, so removing the marker gives the record
    # back rather than a tidied one.
    assert memory_bullets(["Head\n    own indent"]) == "- Head\n      own indent"


@pytest.mark.parametrize("label", ["saved memory: pinned context",
                                   "saved memory: retrieved context"])
def test_the_preface_uses_that_renderer_on_both_of_its_blocks(label):
    """Driven, not grepped: a multi-line memory on either path comes out
    indented, so the list the model reads is unambiguous on the full route as
    well as the minimal one.

    **One block per case, deliberately.** Written over both blocks joined, this
    passed with either one of them reverted to the old join — the other
    supplied the indented line the assertion was looking for. Two blocks is two
    claims.
    """
    rows = [
        {"id": "p", "text": "Pinned fact\nwith a second line", "category": "identity",
         "pinned": True, "timestamp": 5},
        {"id": "r", "text": "Recalled van fact\nwith a second line", "category": "fact",
         "pinned": False, "timestamp": 4},
    ]
    _, preface = _preface(rows, "tell me about my van and who I am")
    block = next((m["content"] for m in preface
                  if (m.get("metadata") or {}).get("source") == label), None)
    assert block is not None, f"{label} was not injected, so this case proves nothing"
    bullets = block[block.index("\n- "):].rsplit("\n<<<", 1)[0]
    stray = [line for line in bullets.strip("\n").split("\n")
             if not (line.startswith("- ") or line.startswith("  "))]
    assert not stray, (
        f"{label} offers {stray} to the model as its own fact, with no bullet "
        "and no indent — a memory's second line reading as a memory")
    assert "\n  with a second line" in bullets


# ── the record on the message ───────────────────────────────────────────────

def test_the_preface_records_what_each_block_was_built_from():
    rows = [{"id": "p", "text": "Pinned fact", "category": "identity",
             "pinned": True, "timestamp": 5}]
    _, preface = _preface(rows, "who am I?")
    blocks = [m for m in preface
              if str((m.get("metadata") or {}).get("source") or "").startswith("saved memory:")]
    assert blocks, "nothing was injected, so there is nothing to record"
    for block in blocks:
        recorded = block["metadata"][MEMORY_FACTS_KEY]
        assert recorded and all(set(row) == {"id", "text"} for row in recorded)


def test_a_block_nobody_recorded_still_reads_as_well_as_it_used_to():
    """The fallback. Some other caller's saved-memory block has no record on
    it, and the old parse is all there is — so it keeps the old parse, with the
    old limits, and reports `id` as unknown rather than inventing one."""
    bare = own_context_message("saved memory: somewhere else",
                               "Context:\n- One\n- Two")
    assert _saved_memory_facts([bare]) == [{"id": None, "text": "One"},
                                           {"id": None, "text": "Two"}]


def test_a_recorded_block_is_not_also_read_as_prose():
    """Both at once would double every fact. The record wins and the prose is
    not consulted — checked by making them disagree."""
    message = own_context_message("saved memory: pinned context",
                                  "Context:\n- From the prose")
    _attach_memory_facts(message, [{"id": "m1", "text": "From the record"}])
    assert _saved_memory_facts([message]) == [{"id": "m1", "text": "From the record"}]


def test_a_message_that_is_not_saved_memory_is_not_read_at_all():
    """The label is what scopes this. A web page or a document that happens to
    contain bullets is not the person's Brain."""
    page = {"role": "user", "content": "Context:\n- Not a memory",
            "metadata": {"source": "web page"}}
    assert _saved_memory_facts([page]) == []
    assert _minimal_saved_memory_message([page]) is None
