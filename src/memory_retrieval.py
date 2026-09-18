# SPDX-License-Identifier: AGPL-3.0-or-later
"""
memory_retrieval.py

The memory scorer. One of them.

`P13-14`. Before this module there were two, and the better one served the
fewer surfaces. `ChatProcessor._hybrid_retrieve` — BM25 over the memory corpus,
with corpus IDF, an optional vector score and recency as a tiebreaker — fed the
chat preface and nothing else. `MemoryManager.get_relevant_memories` — Jaccard
token overlap plus four hand-written keyword lists — fed the Brain panel's
search, its debug endpoint, the agent's own MCP `memory_search`, the memory
provider's fallback, and `ai_interaction`. **So the agent got the worse one.**

Measured before anything was deleted, on `.pantheon/fixtures/retrieval_probe.json`
with no vector service, which is the degraded path a person actually meets:

    lexical (Jaccard + keyword lists)   recall@5 0.40   MRR 0.319
    hybrid  (BM25 + corpus IDF)         recall@5 0.63   MRR 0.633

That is `Law 9` satisfied — the deletion rests on a number rather than on the
observation that BM25 is obviously better, which is an adjective. `P13-13` built
that harness first for exactly this reason.

This is `Law 13`/`Law 14`, not a `Law 1` subtraction: the capability survives and
improves, and what goes is a duplicate implementation. The same argument `P3-10`
used to delete `calendar/reminders.js`, with the same obligation — the safety
case is executable, and it is `tests/test_retrieval_eval_measures_something.py`.

Two views over one scoring pass:

    retrieve(...)  the memories, best first. What five callers want.
    explain(...)   the same selection with the score and the reason kept.
                   `H11`'s contract: `POST /api/memory/debug` promises to say
                   which memories would be triggered, and could only ever answer
                   the WHICH because the score that produced it was computed and
                   discarded on the last line.

The reasons are written from what the code does, not from what it is supposed to
do. That discipline is what found `B40` when `H11` was built, and it is why the
identity boost below says "admitted ahead of anything matched on words" rather
than anything more flattering.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter

from src import memory_edges, retrieval_engine, text_stemmer

# ── tokens ────────────────────────────────────────────────────────────────────

STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need ought dare "
    "i me my mine we us our ours you your yours he him his she her hers "
    "it its they them their theirs this that these those "
    "and but or nor not no so if then else than too also very "
    "in on at to for of by with from up out about into over after "
    "what when where which who whom how why all each every some any "
    "just very really actually like well also still already even "
    "oh ok okay yes yeah hey hi hello thanks thank please sorry "
    "much more most own other another such only same here there "
    "because while during before until since through between both "
    "few many several some none nothing something anything everything "
    "get got make made go going went been come came take took "
    "know think want let say tell give see look find way thing "
    "don doesn didn won wouldn couldn shouldn wasn weren isn aren haven hasn "
    "don't doesn't didn't won't wouldn't couldn't shouldn't "
    "it's i'm i've i'll i'd you're you've you'll he's she's we're we've they're they've "
    "that's there's here's what's who's how's let's can't".split()
)

_WORD = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")


def content_tokens(text: str) -> list:
    """Meaningful content words: no stopwords, min 3 chars, lowercase, stemmed.

    `B62`. Stemming is applied here rather than at the call sites so the query
    and the corpus are reduced by the same rules — a stemmed query against
    unstemmed memories matches less than either alone.

    Stopwords are filtered **twice, around the stemmer**, and both passes earn
    their place. Filtering before stops `does` being bent into `doe` and
    escaping the list; filtering after catches the inflected forms the list does
    not itself carry — `having` is not in it, `have` is, and stemming is what
    connects them.
    """
    words = [w for w in _WORD.findall((text or "").lower())
             if len(w) >= 3 and w not in STOPWORDS]
    return [s for s in (text_stemmer.stem(w) for w in words) if s not in STOPWORDS]


# ── the shape of the question ─────────────────────────────────────────────────

# What a query is *about*, used only to break ties between memories that already
# scored. These are the same three tests the scorer has always applied inline;
# naming them is what lets `POST /api/memory/debug` report a query type that is
# actually the one used, rather than a second classifier that agrees by
# coincidence (`Law 14` — `src/memory.py`'s `classify_query` is the other one,
# and this module does not import it because the two answer different questions:
# that one drives nothing now, this one drives the boost below).
_INTENT_CUES = (
    ("identity", ("name", "who am i", "my name"), 1.4),
    ("contact", ("phone", "email", "address", "contact"), 1.3),
    # `P13-14`. Carried across from the deleted scorer, which boosted task-shaped
    # memories by 30% on task-shaped questions. Dropping it while moving would
    # have been a silent behaviour change wearing a refactor's clothes, and this
    # is the one group the surviving scorer did not already have.
    ("task", ("todo", "task", "remind", "meeting", "appointment", "schedule",
              "deadline"), 1.3),
    ("preference", ("like", "prefer", "favorite"), 1.2),
)

# A memory's own text can qualify it for a boost even when its stored category
# does not, because categories are assigned by an LLM at extraction time and a
# memory reading "her name is Ada" is an identity memory whatever it was filed
# as.
#
# `P13-14`: all four lists are now populated, and three of them came from the
# scorer this replaced. The surviving scorer tested only `@` for contact and
# nothing at all for preference or task, so those boosts fired **only** when
# extraction had filed the memory under exactly the right category — and
# extraction files almost everything as `fact`. A boost gated on a category
# almost nothing carries is a boost that fires for nobody, which is the same
# defect as the four dead keyword lists, reached from the other side.
_INTENT_TEXT_MARKS = {
    "identity": ("name is", "i am", "called", "named", "call me", "my name"),
    "contact": ("@", ".com", "phone", "number", "address", "http", "www", "tel:"),
    "task": ("todo", "task", "remind", "meeting", "appointment", "deadline",
             "schedule", "need to"),
    "preference": ("like", "love", "hate", "dislike", "prefer", "favorite",
                   "enjoy", "interested"),
}

# BM25 constants. `k1` controls term-frequency saturation and `b` how hard
# document length is normalised; these are the standard defaults and the term
# frequency here is binary anyway, because a memory is one short sentence and a
# word appearing twice in it says nothing.
_K1, _B = 1.5, 0.75

# BM25 is unbounded; this divisor maps a realistic score onto roughly 0..1 so it
# can be mixed with a cosine similarity. It is a scaling choice, not a threshold.
_KEYWORD_SCALE = 6.0

# The smallest corpus IDF is allowed to believe in.
#
# `P13-14`. IDF asks how surprising a term is *in general*, and it estimates that
# from how many documents contain it — so on a tiny corpus it has no sample to
# estimate from and collapses. A term unique to one memory scores idf 0.288 when
# there is one memory and 2.639 when there are twenty, a factor of nine, and the
# relevance gate below is a fixed number: **on a corpus of one or two memories
# nothing clears it and retrieval returns nothing at all.**
#
# That is a real defect and not a rounding error. A person's first week with this
# product is exactly the small-corpus case, and "the Brain remembers nothing
# until you have given it twenty things" is not a behaviour anyone chose.
#
# Smoothing the denominator toward a floor is the standard answer: below ten
# documents the corpus is treated as ten, which leaves every realistic corpus
# untouched — the golden set's twenty memories score identically before and
# after — and stops a two-memory corpus reporting that nothing is distinctive.
#
# **Found by the suite, not by the golden set**, whose fixture carries twenty
# memories and therefore could not see this. A measurement harness has a shape,
# and its shape is a blind spot.
_MIN_IDF_CORPUS = 10

# Weights. Recency is capped at 5% and is a tiebreaker only — never the primary
# signal, because "most recent" is what a memory system degrades into when
# nothing else works and it feels like relevance while being nothing of the kind.
_W_VECTOR, _W_KEYWORD, _W_RECENCY = 0.55, 0.40, 0.05
_W_KEYWORD_ALONE = 0.95

# `P13-15`. Durability: how many separate conversations the person has raised
# this in. A fact stated in eleven conversations over three months is something
# they live with; one stated once is a guess, and until this row the store held
# them identically.
#
# It **shares** recency's 5% rather than taking its own, via `max()` at the call
# site. Two capped tiebreakers added side by side make a 10% tiebreaker, which
# is not a tiebreaker any more — and the relevance terms keep exactly the weight
# they had, so this row cannot quietly re-rank anybody's existing memories.
# "Most mentioned wins" is "most recent wins" with a better argument.
#
# Logarithmic, because the interesting distinction is *one conversation versus
# several*: the gap between 1 and 3 is evidence, the gap between 9 and 11 is
# noise, and a linear term would let a much-repeated fact drown a precise one.
# Saturating at 8 means a fact raised in eight separate conversations is as
# durable as this scorer will ever call anything.
_DURABILITY_SATURATION = 8.0

# Gates. A memory must clear real relevance, not just recency.
_MIN_VECTOR, _MIN_KEYWORD, _MIN_FINAL = 0.20, 0.08, 0.12

# What a verbatim match is worth. Carried across from the scorer `P13-14`
# replaces, at the value it used, because changing a number while moving it is
# how a refactor hides a behaviour change.
_VERBATIM_SCORE = 0.8


def _query_intent(query: str) -> str | None:
    lowered = (query or "").lower()
    for intent, cues, _boost in _INTENT_CUES:
        if any(cue in lowered for cue in cues):
            return intent
    return None


def _intent_boost(intent: str | None, memory: dict) -> float:
    if not intent:
        return 1.0
    boost = next(b for name, _c, b in _INTENT_CUES if name == intent)
    if memory.get("category") == intent:
        return boost
    text = (memory.get("text") or "").lower()
    if any(mark in text for mark in _INTENT_TEXT_MARKS.get(intent, ())):
        return boost
    return 1.0


# ── scoring ───────────────────────────────────────────────────────────────────


def _bm25(query_tokens, mem_tokens, doc_freq, n_docs, avg_len):
    """BM25 over one memory. Binary term frequency; memories are one sentence."""
    if not mem_tokens or not query_tokens:
        return 0.0, set()
    shared = {t for t in query_tokens if t in mem_tokens}
    if not shared:
        return 0.0, shared
    mem_len = len(mem_tokens)
    score = 0.0
    for token in shared:
        df = doc_freq.get(token, 0)
        idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
        score += idf * ((_K1 + 1) / (1 + _K1 * (1 - _B + _B * mem_len / avg_len)))
    return score, shared


def _vector_scores(query, memories, vector, k):
    """What the index said, or nothing, plus whether it was reachable at all."""
    healthy = bool(vector and getattr(vector, "healthy", False))
    if not healthy:
        return {}, False
    known = {m.get("id") for m in memories}
    out = {}
    for row in vector.search(query, k=min(k * 3, 20)) or ():
        mid = row.get("memory_id") if isinstance(row, dict) else None
        if mid in known:
            out[mid] = max(row.get("score") or 0.0, 0.0)
    return out, True


def _rank(query, memories, k, vector, report, now):
    """One scoring pass. Returns `[(score, memory, reason)]`, best first."""
    if report is not None:
        # Written before every early return. A report left empty by a bail-out
        # reads as "vector search answered", which is the class of lie `B61`
        # exists to end.
        report.update({"engine": retrieval_engine.KEYWORD,
                       "vector_healthy": False, "vector_ids": []})
    if not memories or not (query or "").strip():
        return []

    # `P13-02`. The graph is read once per query, before anything is scored,
    # because its first rule removes candidates rather than reordering them: a
    # superseded memory does not rank badly, it does not rank. Applied here
    # rather than at each call site so every surface gets it — the Brain's
    # search and debug endpoints, the agent's MCP `memory_search`, the memory
    # provider's fallback, `ai_interaction` and the chat preface all come
    # through this one scorer (`P13-14`), and an edge honoured by some of them
    # is worse than one honoured by none.
    graph = memory_edges.build_edge_index(memories)
    if graph["superseded"]:
        memories = memory_edges.live(memories)
        if not memories:
            return []

    query_tokens = set(content_tokens(query))
    vectors, healthy = _vector_scores(query, memories, vector, k)

    if report is not None:
        # `healthy` and not `vectors`: an index that is up and matched nothing
        # still answered, and reporting that as keyword-only would hide an empty
        # index behind a missing service — two different problems.
        report["vector_healthy"] = healthy
        report["engine"] = retrieval_engine.resolve(
            vector_used=healthy, keyword_used=bool(query_tokens))
        report["vector_ids"] = sorted(vectors)

    if not query_tokens and not healthy:
        # Nothing to match on and nothing to match with. `who am i` lands here:
        # every one of its words is a stopword, so a lexical engine has no query
        # left at all. That is not a bug in the tokenizer, it is the strongest
        # single argument that a downed vector service is a real degradation.
        #
        # Except for a verbatim match, which needs no tokens at all — and this
        # early return would otherwise be the one place the exact-phrase rule
        # silently does not apply. Found by a test asserting the rule was
        # unconditional, which it was not.
        verbatim_rows = [(_VERBATIM_SCORE, memory,
                          _reason(0.0, 0.0, set(), 1.0, None, False, 0, verbatim=True))
                         for memory in memories if _verbatim(query, memory)]
        return _apply_edges(verbatim_rows, {}, k, graph, memories)

    doc_freq = Counter()
    tokens_by_id = {}
    for memory in memories:
        tokens = set(content_tokens(memory.get("text", "")))
        tokens_by_id[memory.get("id")] = tokens
        doc_freq.update(tokens)
    # `avg_len` uses the real count — average document length is measured, not
    # estimated, and there is nothing to smooth. Only IDF gets the floor.
    avg_len = max(sum(len(t) for t in tokens_by_id.values()) / len(memories), 1)
    n_docs = max(len(memories), _MIN_IDF_CORPUS)

    intent = _query_intent(query)
    ranked = []
    # `P13-02`. Every memory's score and reason, cleared or not. A contradiction
    # partner has to be able to surface beside the memory it contradicts even
    # when it shares no words with the question — that is the whole point of
    # recording the contradiction — and it has to surface with **its own**
    # score rather than borrowing the score of whatever pulled it in, which
    # would be `H11`'s defect (a number that explains nothing) wearing a
    # relation.
    pool = {}
    for memory in memories:
        mid = memory.get("id")
        vector_score = vectors.get(mid, 0.0)
        raw, shared = _bm25(query_tokens, tokens_by_id.get(mid, set()),
                            doc_freq, n_docs, avg_len)
        keyword = min(raw / _KEYWORD_SCALE, 1.0) if raw > 0 else 0.0
        boost = _intent_boost(intent, memory)
        keyword = min(keyword * boost, 1.0)

        days_old = max((now - (memory.get("timestamp") or 0)) / 86400, 0)
        recency = 1.0 / (1.0 + days_old * 0.05)
        durability = _durability(memory)

        # The relevance gates, and the one thing allowed past them. A verbatim
        # match can score nothing on BM25 — "12 Bridge Street" is three tokens
        # of which two are common — so gating it out before the check below
        # would drop the strongest signal there is.
        cleared = (vector_score >= _MIN_VECTOR or keyword >= _MIN_KEYWORD) if healthy \
            else (keyword >= _MIN_KEYWORD)
        # Recency and durability share one 5% slice rather than taking 5% each.
        # Two capped tiebreakers added side by side is a 10% tiebreaker, which
        # is not a tiebreaker any more.
        tiebreak = _W_RECENCY * max(recency, durability)
        if healthy:
            final = (_W_VECTOR * vector_score) + (_W_KEYWORD * keyword) + tiebreak
        else:
            final = (_W_KEYWORD_ALONE * keyword) + tiebreak

        # `P13-14`, carried across from the scorer this replaces rather than
        # lost with it (`Law 1`). A query that appears in a memory word for word
        # is the one case where wording is not a proxy for relevance — it *is*
        # the relevance — and no amount of IDF weighting reproduces it, because
        # a common word in a verbatim phrase still carries a low IDF.
        verbatim = _verbatim(query, memory)
        if verbatim:
            final = max(final, _VERBATIM_SCORE)

        row = (final, memory, _reason(
            vector_score, keyword, shared, boost, intent, healthy, days_old, verbatim,
            int(memory.get("mention_sessions", 0) or 0)))
        if mid:
            pool[mid] = row
        # The gates are unchanged and still decide what RANKS. What changed is
        # that a memory failing them is now scored and kept aside rather than
        # dropped on the floor, so `_apply_edges` can surface it as the other
        # half of a contradiction with a real number beside it.
        if not cleared and not verbatim:
            continue
        if final <= _MIN_FINAL:
            continue
        ranked.append(row)

    ranked.sort(key=lambda row: row[0], reverse=True)
    return _apply_edges(ranked, pool, k, graph, memories)


def _snippet(memory: dict, limit: int = 60) -> str:
    """A memory named the way a person would recognise it, not by its uuid."""
    text = (memory.get("text") or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _apply_edges(ranked, pool, k, graph, memories):
    """The edge rules, applied to a ranked list, cut to `k`. `P13-02`.

    Three of the four edge types act here; the fourth, `supersedes`, has
    already acted by removing its targets from the corpus before anything was
    scored.

    * **`derived_from`** — when a memory and the memory it was derived from
      both qualify, only the derived one takes a slot. Not a suppression of the
      source in general: a source that ranks on its own, with nothing derived
      from it in the results, is returned normally. Compared by rank position
      rather than by iteration order, so the rule does not depend on which one
      the loop happens to reach first.

    * **`contradicts`** — both sides surface, and the conflict is named. The
      partner is pulled from the whole live corpus rather than from what
      already ranked, because the entire reason to record a contradiction is
      that the other side might not match the question: *"user lives in
      Berlin"* and *"user lives in Munich"* share every word, but *"allergic to
      shellfish"* and *"had prawns last night"* share none. **A memory whose
      partner does not fit in `k` still says so in its reason** — the slot
      budget is allowed to hide the other side, it is not allowed to hide that
      there is one.

    * **`co_occurs`** — a partner that *already cleared the relevance gates*
      and fell below the cut is pulled up beside what it accompanies. Only from
      `ranked`, never from the corpus, and with no score change: this reorders
      inside the qualified set and never promotes something that did not
      qualify. That restraint is the row's own test ("an edge that only exists
      to be drawn is not worth storing") applied honestly — the alternative is
      a boost with an invented constant, and `P13-13`'s golden set is the
      instrument that would have to justify one.

    Pull-ins are one hop. A partner's own partners are not chased, because a
    chain of contradictions is a corpus problem and not a query's job to walk.
    """
    if k <= 0:
        return []
    by_id = {m.get("id"): m for m in memories if isinstance(m, dict) and m.get("id")}
    contradicts = graph.get(memory_edges.EDGE_CONTRADICTS) or {}
    co_occurs = graph.get(memory_edges.EDGE_CO_OCCURS) or {}
    derived_from = graph.get(memory_edges.EDGE_DERIVED_FROM) or {}

    rank_pos = {}
    for position, (_score, memory, _why) in enumerate(ranked):
        mid = memory.get("id")
        if mid and mid not in rank_pos:
            rank_pos[mid] = position

    # `B derived_from A` stored on B; this is the lookup the other way, which
    # is the direction the rule reads in.
    derived_children = {}
    for child, sources in derived_from.items():
        for source in sources:
            derived_children.setdefault(source, set()).add(child)

    selected, taken = [], set()

    def _take(row, reason_override=None):
        score, memory, why = row
        mid = memory.get("id")
        # Guarded on a truthy id, not on membership alone. A memory with no id
        # cannot be a duplicate of another memory with no id — putting `None`
        # in the set would return the first such row and silently drop every
        # other one, which is how an id-less test corpus (or a store someone
        # hand-edited) would come back one memory long.
        if mid:
            if mid in taken:
                return
            taken.add(mid)
        selected.append((score, memory, reason_override or why))

    for position, row in enumerate(ranked):
        if len(selected) >= k:
            break
        memory = row[1]
        mid = memory.get("id")
        if mid in taken:
            continue

        # `derived_from`: something derived from this ranked above it.
        if any(rank_pos.get(child, len(ranked)) < position
               for child in derived_children.get(mid, ())):
            continue

        partners = [p for p in sorted(contradicts.get(mid, ())) if p in by_id]
        if partners:
            named = ", ".join(f'"{_snippet(by_id[p])}"' for p in partners[:2])
            more = f" (+{len(partners) - 2} more)" if len(partners) > 2 else ""
            _take(row, f"{row[2]}; contradicted by {named}{more}, "
                       f"which is recorded rather than resolved")
        else:
            _take(row)

        for partner_id in partners:
            if len(selected) >= k or partner_id in taken:
                continue
            partner_row = pool.get(partner_id)
            partner = partner_row[1] if partner_row else by_id[partner_id]
            score = partner_row[0] if partner_row else 0.0
            _take((score, partner, ""),
                  f'included because it contradicts "{_snippet(memory)}", '
                  f"which matched this question")

        for partner_id in sorted(co_occurs.get(mid, ())):
            if len(selected) >= k or partner_id in taken:
                continue
            if partner_id not in rank_pos:
                continue  # never cleared the gates; a relation is not a boost
            partner_row = pool.get(partner_id)
            if not partner_row:
                continue
            _take(partner_row,
                  f'{partner_row[2]}; recorded as coming up together with '
                  f'"{_snippet(memory)}"')

    return selected[:k]


def _durability(memory: dict) -> float:
    """0..1, from how many separate conversations this has come up in.

    `mention_sessions` and not `mentions`: extraction runs after every response,
    so saying one thing three times inside one conversation is one
    conversation's worth of evidence. And not `uses`, which counts how often the
    *system* reached for this — a memory the assistant keeps injecting and a
    memory the person keeps raising are different kinds of important.
    """
    sessions = int(memory.get("mention_sessions", 0) or 0)
    # `max(sessions, 1)` rather than an early return for 0 and 1. A guard would
    # be belt-and-braces — `log(1)` is already 0, so one conversation scores
    # nothing whichever way it is written — and a branch that cannot change an
    # answer is a branch a mutation deletes for free. `P13-14`'s `cutoff` and
    # `B62`'s seven undistinguishable stemmer rules are the same lesson.
    return min(math.log(max(sessions, 1)) / math.log(_DURABILITY_SATURATION), 1.0)


def _verbatim(query: str, memory: dict) -> bool:
    """The query appears in the memory word for word."""
    q = (query or "").strip().lower()
    return bool(q) and q in (memory.get("text") or "").lower()


def _reason(vector_score, keyword, shared, boost, intent, healthy, days_old,
            verbatim=False, sessions=0) -> str:
    """Why this memory was chosen, from what the code did.

    `H11`'s discipline. A reason reverse-engineered from a final score is a
    guess dressed as a diagnostic; each clause below names a term that actually
    contributed.
    """
    if verbatim:
        # Said first and alone: it is the whole explanation, and burying it in a
        # list of contributing terms would misdescribe why this was chosen.
        return "the query appears in this memory word for word"
    parts = []
    if vector_score > 0:
        parts.append(f"means something close to the question ({vector_score:.2f} similarity)")
    elif healthy:
        parts.append("the index was searched and did not match this")
    if shared:
        words = ", ".join(sorted(shared)[:4])
        more = f" (+{len(shared) - 4} more)" if len(shared) > 4 else ""
        parts.append(f"shares {words}{more}")
    elif not vector_score:
        parts.append("no words in common with the query")
    if boost > 1.0:
        parts.append(f"reads as a {intent} question and this memory answers that kind"
                     f" (×{boost:g} on the wording score)")
    if not healthy:
        parts.append("matched on wording alone — semantic search was unavailable")
    if sessions > 1:
        parts.append(f"raised in {sessions} separate conversations, which counts for at most 5%")
    elif days_old > 365:
        parts.append(f"{int(days_old // 365)}y old, which counts for at most 5%")
    return "; ".join(parts) or "scored above the floor on wording"


# ── the two views ─────────────────────────────────────────────────────────────


def retrieve(query: str, memories: list, k: int = 5, *,
             vector=None, report: dict | None = None, now: float | None = None) -> list:
    """The memories relevant to `query`, best first.

    `report`, when given, is filled with which engine answered (`B61`). It is an
    out-parameter rather than a wider return type because callers and their test
    doubles unpack this list directly, and widening a return value they do not
    read is how the `_build_base_prompt` 3-tuple broke eleven tests.
    """
    return [memory for _score, memory, _why in
            _rank(query, memories, k, vector, report, now if now is not None else time.time())]


def explain(query: str, memories: list, k: int = 5, *,
            vector=None, report: dict | None = None, now: float | None = None) -> list:
    """The same selection, with the score and the reason kept. `H11`.

    Returns `[{"memory": dict, "score": float, "reason": str}]`, best first.
    One scoring pass, not two: a diagnostic that re-scores is a diagnostic that
    can disagree with the thing it is explaining.
    """
    return [{"memory": memory, "score": round(score, 4), "reason": why}
            for score, memory, why in
            _rank(query, memories, k, vector, report, now if now is not None else time.time())]


def query_intent(query: str) -> str | None:
    """How the retriever read the question, as the retriever actually read it.

    Exported so `POST /api/memory/debug` reports the intent that drove the
    ranking rather than a second classifier that agrees by coincidence.
    """
    return _query_intent(query)
