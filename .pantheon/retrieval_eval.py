#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""P13-13 — score memory retrieval, so "better" stops being an adjective.

`P14-02` already records `asked` and `returned` per search. *Returned 5* is not
*returned the right 5*, so before this script there was no number anywhere that
could tell one retrieval engine from another, and every option in `P13-11` would
have shipped on taste — the unverifiable self-referential claim `Law 9` forbids.

Two metrics, both standard, both cheap:

  recall@k  the share of probes whose expected memory appears in the top k.
            "Did we get it at all."
  MRR       mean of 1/rank over the first expected memory. "And how near the
            top." A system that always answers correctly at rank 5 scores 1.0
            on recall@5 and 0.2 on MRR, and the difference is the whole point:
            memory is injected under a slot limit, so rank is not cosmetic.

Both engines are scored over ONE corpus, with no vector service, because that
is the comparison that matters: the vector store is a separate process and the
degraded path is the one a person actually meets.

  --corpus PATH   a corpus file (default: the fixture beside this script)
  --engine NAME   `lexical`, `hybrid`, or `both` (default)
  --k N           cutoff for recall@k (default 5)
  --generate MEM  read a real memory.json and write a DRAFT corpus to stdout

ON PROVENANCE, which is the part that matters. The corpus carries a
`provenance` field and this script prints it in the header, because a number
computed over hand-written probes is a fact about the person who wrote them.
`fixture` means exactly that and its numbers belong to the harness, not to the
product. Only `curated` — an operator's own memories, with probes they checked —
supports a claim about how well this product remembers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_DEFAULT_CORPUS = Path(__file__).resolve().parent / "fixtures" / "retrieval_probe.json"

PROVENANCE_NOTE = {
    "fixture": "harness fixture — these numbers describe the scorer, not the product",
    "generated": "machine-drafted and NOT yet checked by a person — treat as a starting point",
    "curated": "an operator's own memories with probes they checked — a real measurement",
}


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("memories", "probes"):
        if not isinstance(data.get(key), list) or not data[key]:
            raise SystemExit(f"{path}: `{key}` must be a non-empty list")
    known = {m["id"] for m in data["memories"]}
    for probe in data["probes"]:
        missing = set(probe.get("expect") or ()) - known
        if missing:
            raise SystemExit(f"{path}: probe {probe['query']!r} expects unknown ids {sorted(missing)}")
        if not probe.get("expect"):
            raise SystemExit(f"{path}: probe {probe['query']!r} expects nothing")
    data.setdefault("provenance", "unknown")
    return data


# ── the two engines, each reduced to `query -> ranked memory ids` ─────────────


def _manager(corpus: dict, k: int) -> dict:
    """`MemoryManager.get_relevant_memories` — the Brain, the agent, the provider."""
    from src.memory import MemoryManager

    manager = MemoryManager.__new__(MemoryManager)  # no data dir, no file I/O
    out = {}
    for probe in corpus["probes"]:
        rows = manager.get_relevant_memories(
            probe["query"], [dict(m) for m in corpus["memories"]],
            threshold=0.05, max_items=k)
        out[probe["query"]] = [r["id"] for r in rows]
    return out


def _preface(corpus: dict, k: int) -> dict:
    """`ChatProcessor._hybrid_retrieve` — what the chat preface injects."""
    from src.chat_processor import ChatProcessor

    proc = ChatProcessor.__new__(ChatProcessor)
    proc.memory_vector = None
    out = {}
    for probe in corpus["probes"]:
        rows = proc._hybrid_retrieve(
            probe["query"], [dict(m) for m in corpus["memories"]], k=k)
        out[probe["query"]] = [r["id"] for r in rows]
    return out


# `P13-14` changed what these two names mean, and the change is the row.
# They were two ALGORITHMS — Jaccard-plus-keyword-lists against BM25-with-IDF —
# and the measurement that separated them (0.40/0.319 against 0.63/0.633, on
# this corpus, with no vector service) is what justified deleting the first.
# They are now two CALL PATHS into one scorer, and they are expected to agree.
# Scoring both is still worth the milliseconds: the day they disagree, a second
# scorer has grown back, which is the defect `Law 13` names and the reason this
# row existed.
ENGINES = {"manager": _manager, "preface": _preface}

# What the deleted scorer measured on this corpus, kept as the floor. Not a
# ratchet on an uncalibrated number — `P3-20`'s mistake — because this one is
# calibrated by being a historical fact: it is what the product did before, and
# "never worse than what we removed" is the one comparison a deletion owes.
DELETED_SCORER_BASELINE = {"recall": 0.40, "mrr": 0.319}


# ── scoring ───────────────────────────────────────────────────────────────────


def score(corpus: dict, ranked: dict, k: int) -> dict:
    hits, reciprocal, misses = 0, 0.0, []
    for probe in corpus["probes"]:
        expect = set(probe["expect"])
        order = ranked.get(probe["query"], [])
        rank = next((i + 1 for i, mid in enumerate(order[:k]) if mid in expect), None)
        if rank:
            hits += 1
            reciprocal += 1.0 / rank
        else:
            # Where it did land matters: rank 9 is a ranking problem and
            # "absent entirely" is a recall problem, and they are fixed
            # differently.
            deeper = next((i + 1 for i, mid in enumerate(order) if mid in expect), None)
            misses.append({"query": probe["query"], "expect": sorted(expect),
                           "got": order[:3], "found_at": deeper, "why": probe.get("why", "")})
    n = len(corpus["probes"])
    return {"n": n, f"recall@{k}": hits / n, "mrr": reciprocal / n,
            "hits": hits, "misses": misses}


def _report(name: str, result: dict, k: int, verbose: bool) -> None:
    print(f"  {name:<10} recall@{k} {result[f'recall@{k}']:.2f}"
          f"   MRR {result['mrr']:.3f}"
          f"   ({result['hits']}/{result['n']})")
    if verbose and result["misses"]:
        for miss in result["misses"]:
            where = f"rank {miss['found_at']}" if miss["found_at"] else "not returned"
            print(f"      MISS  {miss['query']!r} -> {where}")
            print(f"            wanted {miss['expect']}, got {miss['got'] or '[]'}")
            if miss["why"]:
                print(f"            {miss['why']}")


# ── drafting a corpus from real memories ──────────────────────────────────────


def _generate(memory_path: Path) -> dict:
    """A DRAFT corpus from an operator's own memory.json.

    Deliberately mechanical. It writes one probe per memory, seeded from that
    memory's own words, and marks the whole file `generated` — which
    `PROVENANCE_NOTE` renders as *not yet checked by a person*. A person then
    rewrites each `query` into what they would actually have typed, and only
    then is the file worth calling `curated`. Nothing here pretends a template
    can guess how somebody asks a question; the value is that the ids, the
    corpus and the file shape are correct so the human part is only the writing.
    """
    rows = json.loads(memory_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"{memory_path}: expected a non-empty list of memories")
    memories, probes = [], []
    for row in rows:
        if not row.get("id") or not row.get("text"):
            continue
        memories.append({"id": row["id"], "text": row["text"],
                         "category": row.get("category", "fact"),
                         "timestamp": row.get("timestamp", 0)})
        probes.append({"query": "REWRITE ME — how would you actually ask for this? "
                                f"({row['text']})",
                       "expect": [row["id"]],
                       "why": ""})
    return {"provenance": "generated",
            "note": "Drafted by retrieval_eval.py --generate. Every query says "
                    "REWRITE ME because a template cannot guess how a person "
                    "asks. Rewrite them, delete the ones that are not real "
                    "questions, then set provenance to `curated`.",
            "memories": memories, "probes": probes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS)
    ap.add_argument("--engine", choices=[*ENGINES, "both"], default="both")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--generate", type=Path, metavar="MEMORY_JSON")
    ap.add_argument("--verbose", action="store_true", help="print every miss and why it was chosen")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.generate:
        json.dump(_generate(args.generate), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    corpus = _load(args.corpus)
    names = list(ENGINES) if args.engine == "both" else [args.engine]
    results = {name: score(corpus, ENGINES[name](corpus, args.k), args.k) for name in names}

    if args.json:
        json.dump({"provenance": corpus["provenance"],
                   "results": {n: {k: v for k, v in r.items() if k != "misses"}
                               for n, r in results.items()}},
                  sys.stdout, indent=2)
        print()
        return 0

    print(f"retrieval eval · {args.corpus.name} · {len(corpus['memories'])} memories, "
          f"{len(corpus['probes'])} probes · no vector service")
    print(f"provenance: {corpus['provenance']} — "
          f"{PROVENANCE_NOTE.get(corpus['provenance'], 'unrecognised, treat with suspicion')}")
    print()
    for name in names:
        _report(name, results[name], args.k, args.verbose)
    print()
    if corpus["provenance"] != "curated":
        print("This is not a measurement of how well Pantheon remembers. Run")
        print("  .pantheon/retrieval_eval.py --generate data/memory.json > mine.json")
        print("rewrite the queries, set provenance to `curated`, and score that.")
    # A report, never a gate. A ratchet on a number nobody has calibrated is
    # `P3-20`'s mistake, and the first honest thing to know is what today's
    # number even is.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
