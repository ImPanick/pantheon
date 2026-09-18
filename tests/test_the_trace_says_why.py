# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-10` — when memory changes an answer, say which memories **and why**.

**Premise corrected, again, and in the direction of more work rather than
less.** The row was collapsed on 2026-08-31 into "one field on `P13-01`", on the
reading that the trace was wired end to end and only lacked a confidence
number. Measured at `ad7c6f3`: the payload that reaches `.memory-used-pill`
carries `text`, `category`, `type`, `engine` and `confidence`, and carries
neither the memory's **id** nor the **reason** — which is the row's own word
*why*. The reason is not missing because nobody built it: `H11` built it, every
ranked row already carries one, `POST /api/memory/debug` already renders it, and
`memory_retrieval.retrieve` drops it on the last line because its callers want a
list of memories. So this is `H11`'s defect one layer up — computed, correct,
and thrown away at the boundary — and it is the third time this phase has found
it.

Nothing here asserts on markup. The pill is `static/**` and belongs to another
agent this wave (`B712`); what is asserted is that the payload the pill reads
carries the two fields, per memory, on both paths.
"""

from types import SimpleNamespace

from src import memory_retrieval, retrieval_engine
from src.chat_processor import ChatProcessor


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


def _trace(rows, message):
    proc = _processor(rows)
    proc.build_context_preface(message=message, session=SimpleNamespace(),
                               use_rag=False, use_memory=True)
    return proc._last_used_memories


def mem(mid, text, **extra):
    row = {"id": mid, "text": text, "category": "fact", "timestamp": 1780000000}
    row.update(extra)
    return row


# ── the scorer already knows why; the trace has to carry it ───────────────────

def test_the_ranked_rows_reach_the_caller_through_the_report():
    # The seam. `retrieve` returns memories because five call sites unpack them
    # that way, so the score and the reason ride on the out-parameter `B61`
    # already established rather than on a widened return type.
    corpus = [mem("van", "User drives a diesel van for site visits"),
              mem("cat", "User's cat is called Bramble")]
    report = {}
    memory_retrieval.retrieve("what van do I drive", corpus, k=5, report=report)
    assert [row["id"] for row in report["selected"]] == ["van"]
    assert "van" in report["selected"][0]["reason"]
    assert report["selected"][0]["score"] > 0


def test_the_report_rows_are_the_rows_that_were_returned():
    # Not "everything that scored". A trace listing memories the model never
    # saw is worse than no trace, because it is believed.
    corpus = [mem("a", "User drives a diesel van"),
              mem("b", "User drives to site in a van every Tuesday"),
              mem("c", "User's cat is called Bramble")]
    report = {}
    got = memory_retrieval.retrieve("van", corpus, k=1, report=report)
    assert [m["id"] for m in got] == [row["id"] for row in report["selected"]]


def test_the_reason_is_the_one_the_debug_endpoint_gives():
    # One scoring pass, one reason. A trace that re-derives its own explanation
    # is a second diagnostic that can disagree with the first (`P13-14`).
    corpus = [mem("van", "User drives a diesel van for site visits"),
              mem("cat", "User's cat is called Bramble")]
    report = {}
    memory_retrieval.retrieve("what van do I drive", corpus, k=5, report=report)
    explained = memory_retrieval.explain("what van do I drive", corpus, k=5)
    assert [row["reason"] for row in report["selected"]] == \
        [row["reason"] for row in explained]


def test_an_empty_run_reports_an_empty_list_rather_than_no_key():
    # `B61`'s rule about `engine`, applied to this key: absent on some paths
    # means every reader writes a default, and the default is the answer nobody
    # measured.
    report = {}
    memory_retrieval.retrieve("", [mem("a", "User drives a van")], k=5, report=report)
    assert report["selected"] == []


# ── and it has to survive the trip to the payload ─────────────────────────────

def test_a_recalled_memory_carries_its_reason_into_the_trace():
    rows = [mem("van", "User drives a diesel van for site visits"),
            mem("cat", "User's cat is called Bramble")]
    trace = _trace(rows, "what van do I drive")
    recalled = [r for r in trace if r["type"] == "recalled"]
    assert recalled, trace
    assert recalled[0]["reason"], "the trace still says which and not why"
    assert "van" in recalled[0]["reason"]


def test_a_recalled_memory_carries_its_id_into_the_trace():
    # Without it nothing downstream can open the memory the pill names, and the
    # panel has to match on text — which is not unique and is the same mistake
    # `_minimal_saved_memory_message` makes in the agent loop.
    rows = [mem("van", "User drives a diesel van for site visits")]
    trace = _trace(rows, "what van do I drive")
    assert [r["id"] for r in trace] == ["van"]


def test_a_pinned_memory_says_it_was_pinned_rather_than_borrowing_a_score():
    # `B61` again, in the other direction: nothing ranked a core pinned memory,
    # so a reason describing a match would be invented. The honest answer is
    # that it is always available, and it is said in those words.
    rows = [mem("who", "User's name is Felix Arden", category="identity",
                pinned=True)]
    trace = _trace(rows, "explain how python decorators work")
    assert [r["engine"] for r in trace] == [retrieval_engine.PINNED]
    assert "pinned" in trace[0]["reason"].lower()
    assert "similarity" not in trace[0]["reason"]


def test_a_pinned_memory_that_had_to_match_says_how_it_matched():
    # The other half of `_select_pinned_memories`: a non-core pinned memory is
    # retrieved rather than always sent, so it has a real reason and reporting
    # it as "always available" would be the same lie as the previous test's.
    rows = [mem("who", "User's name is Felix Arden", category="identity",
                pinned=True, timestamp=9),
            mem("van", "User drives a diesel van for site visits",
                pinned=True, timestamp=8)]
    trace = _trace(rows, "what van do I drive")
    by_id = {r["id"]: r for r in trace}
    assert "van" in by_id, trace
    assert "van" in by_id["van"]["reason"]


def test_every_trace_row_has_the_same_keys_on_both_paths():
    # A payload whose shape depends on how the memory got there forces the
    # reader to branch, and the branch nobody wrote is the one that renders
    # `undefined`.
    rows = [mem("who", "User's name is Felix Arden", category="identity",
                pinned=True, timestamp=9),
            mem("van", "User drives a diesel van for site visits", timestamp=8)]
    trace = _trace(rows, "what van do I drive")
    assert len(trace) == 2, trace
    assert {frozenset(r) for r in trace} == {frozenset(trace[0])}
    for row in trace:
        assert set(row) >= {"id", "text", "category", "type", "engine",
                            "confidence", "reason"}
