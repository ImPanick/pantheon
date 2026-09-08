# SPDX-License-Identifier: AGPL-3.0-or-later
"""
retrieval_engine.py

Which engine answered a memory search.

`B61`. Semantic memory search runs against a ChromaDB *service* — a separate
process, probed with a 2s TCP connect — so it can be up at install and down at
any moment after. When it is down the code falls back to lexical scoring, and
before this module every layer above described that fallback as though it were
the vector store: a variable literally named `vector_results`, a `score=None`
that cannot be told from a zero, and a docstring calling a core dependency
optional. The Brain got quietly worse at its one job and looked identical doing
it.

This module is the one place the names live. It imports nothing from the
project, on purpose and for the same reason `src/runtime_limits.py` does: a
label describing which subsystem answered must not depend on that subsystem
being importable.
"""

from __future__ import annotations

# A vector search answered. The embedding model produced the ranking.
VECTOR = "vector"

# Lexical scoring answered — BM25 over the memory corpus, or the older Jaccard
# scorer. No embedding was consulted, because none was reachable.
KEYWORD = "keyword"

# Both contributed to the ranking. This is the healthy default for the chat
# preface, which blends a vector score with BM25 and a recency tiebreaker.
HYBRID = "hybrid"

# A substring match. Not a ranking at all — the query appeared verbatim in the
# memory text. Cheap, exact, and it says nothing about relevance.
EXACT = "exact"

# Not retrieved. The memory was injected because it is pinned, so no engine
# chose it and no score describes it. Naming this is the point: a pinned memory
# reported as a keyword hit is the same lie in the other direction.
PINNED = "pinned"

ENGINES = (VECTOR, KEYWORD, HYBRID, EXACT, PINNED)

# How each engine is said to a person, in the retrieval trace and the Brain.
# Short, because it renders inside a pill beside a count.
LABELS = {
    VECTOR: "semantic",
    KEYWORD: "keyword only",
    HYBRID: "semantic + keyword",
    EXACT: "exact match",
    PINNED: "pinned",
}

# The engines that mean semantic search was NOT available. A caller deciding
# whether to warn reads this rather than testing for a string, because the set
# is the thing that changes when an engine is added.
DEGRADED = frozenset({KEYWORD, EXACT})


def resolve(*, vector_used: bool, keyword_used: bool) -> str:
    """The engine name for a run, from what actually contributed to it.

    Both flags are about what *ran*, not what was configured. A vector store
    that is healthy but returned nothing still counts as used: it answered, and
    the answer was empty. Reporting that as `keyword` would hide the case where
    the index is up and simply has nothing in it.
    """
    if vector_used and keyword_used:
        return HYBRID
    if vector_used:
        return VECTOR
    return KEYWORD


def label(engine: str) -> str:
    """Human-readable name, or the raw value if it is not one of ours."""
    return LABELS.get(engine, engine)


def is_degraded(engine: str) -> bool:
    """True when semantic search did not run and the caller should say so."""
    return engine in DEGRADED
