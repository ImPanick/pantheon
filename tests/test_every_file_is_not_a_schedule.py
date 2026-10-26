# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B502` / `B503` — the keyword selector reads what the words say.

`B502`. `_SCHEDULE_RE`'s first branch was `\\bevery\\s+\\w+`, typo-resilient on
purpose so *"every dya"* reaches `manage_tasks` — and so also a schedule in
*"check every file"* and *"run the tests every time i push"*, where `every` is a
quantifier. `GAP-ANALYSIS.md` measured `manage_tasks` offered in 17 of 39 runs
and called 0. Now `every <word>` is a schedule when the word is a **cadence** —
a unit of time or a day — with one typo allowed.

`B503`. The session hint set was contiguous phrases, so *"rename the last twelve
chats"* matched none of eighteen and the generic `rename` offered the document
family instead. Now a session verb, up to five words, then a session noun.

Driven through `ToolIndex.select_without_embeddings` — the deterministic half of
selection, which the suite planner pins on every window (`B1368`) — and scored
over the product's own probe corpus with `.pantheon/retrieval_eval.py`, the
harness `tests/test_the_selector_is_measured_not_asserted.py` uses (`Law 14`).
Red on the tree before this row: the two `every` probes spilled `manage_tasks`
and the rename probe missed both session tools.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.tool_index import ToolIndex

ROOT = Path(__file__).resolve().parent.parent
_CORPUS = ROOT / ".pantheon" / "fixtures" / "tool_selection_probe.json"


def _picks(query: str) -> set:
    return ToolIndex.select_without_embeddings(query, set())


def _eval_module():
    sys.path.insert(0, str(ROOT / ".pantheon"))
    spec = importlib.util.spec_from_file_location("_retrieval_eval_b502", ROOT / ".pantheon" / "retrieval_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── B502 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "check every file in the repo for a licence header",
    "run the tests every time i push a commit",
    "go through every one of them and fix the typos",
    "every item in the list needs a price",
    "it is every man for himself in this codebase",
])
def test_every_as_a_quantifier_is_not_a_schedule(query):
    assert "manage_tasks" not in _picks(query)


@pytest.mark.parametrize("query", [
    "back up the database every dya at 3am",       # the typo the regex was for
    "summarise my inbox every mornign",
    "check the feed every 2 hours",
    "water the plants every other day",
    "send me the report every monday",
    "ping the server every few minutes",
    "rotate the logs every week",
])
def test_every_as_a_cadence_still_is_one_typos_included(query):
    assert "manage_tasks" in _picks(query)


def test_one_letter_off_a_short_day_name_is_not_a_cadence():
    """The tolerance is a swap of two adjacent letters for a word of three
    letters or fewer, so "dya" is "day" and "man" is not "mon"."""
    assert ToolIndex.every_is_a_cadence("every dya")
    assert not ToolIndex.every_is_a_cadence("every man")
    assert not ToolIndex.every_is_a_cadence("every set of tests")


# ── B503 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "rename the last twelve chats to match their topics",
    "archive all my old sessions from last year",
    "delete the three chats about the move",
    "fork this conversation so I can try another approach",
    # Every phrase the pattern replaced in the hint set, still selected.
    "rename chat", "rename session", "rename the chat", "rename my chat",
    "rename the session", "archive chat", "archive session", "delete chat",
    "delete session", "fork chat", "fork session", "name the chats", "name my chats",
])
def test_a_session_verb_reaches_its_noun_across_the_words_between(query):
    assert {"list_sessions", "manage_session"} <= _picks(query)


def test_a_rename_with_no_chat_in_it_stays_with_the_documents():
    picks = _picks("rename this document to quarterly-report")
    assert "edit_document" in picks
    assert "manage_session" not in picks


# ── both, over the corpus ────────────────────────────────────────────────────

def test_the_refusal_probes_pass_and_recall_did_not_drop():
    """The row's own `Verify:` — the refusal probes pass, `every dya` still
    selects, and over the corpus refusal goes up rather than recall down."""
    ev = _eval_module()
    corpus = ev._load(_CORPUS)
    score = ev.score_selection(corpus, ev._selector(corpus, 5))
    assert score["spills"] == [], score["spills"]
    assert score["misses"] == [], score["misses"]
    assert score["recall"] == 1.0 and score["refusal"] == 1.0, score
    probes = {p["query"]: p for p in json.loads(_CORPUS.read_text(encoding="utf-8"))["probes"]}
    assert "back up the database every dya at 3am" in probes
