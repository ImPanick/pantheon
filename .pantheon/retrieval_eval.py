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

# `P17-14`. The second thing in this product that retrieves by embedding is the
# TOOL selector, and until this row it had no number at all — which is how
# `.pantheon/GAP-ANALYSIS.md` could report `web_search` offered 37 times and
# called 0, and `create_document` offered once and called 19, with nothing to
# say whether that was the selector's fault or the tools'.
#
# It is scored HERE rather than in a second script, because it is the same
# question (did retrieval put the right thing in front of the model), the same
# provenance problem (a corpus somebody wrote is a fact about them), and the
# same failure to avoid — a second scorer is a second opinion to reconcile.
# What differs is the output shape, and only that: memory retrieval returns a
# RANKED LIST and tool selection returns a SET, so recall transfers and MRR
# does not. `score_selection` says so rather than inventing a rank.
_DEFAULT_TOOL_CORPUS = (Path(__file__).resolve().parent / "fixtures"
                        / "tool_selection_probe.json")

PROVENANCE_NOTE = {
    "fixture": "harness fixture — these numbers describe the scorer, not the product",
    "generated": "machine-drafted and NOT yet checked by a person — treat as a starting point",
    "curated": "an operator's own memories with probes they checked — a real measurement",
}


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") == "tools":
        return _load_tools(path, data)
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
    data.setdefault("kind", "memory")
    data.setdefault("provenance", "unknown")
    return data


def _load_tools(path: Path, data: dict) -> dict:
    """A tool-selection corpus, validated against the real tool surface.

    The names in `expect` and `reject` are checked against `TOOL_TAGS` — the
    register both call channels gate on — so a probe cannot quietly expect a
    tool that was renamed or never existed and score a miss forever.
    `expect` MAY be empty here, unlike a memory probe: *offer nothing extra*
    is the assertion for half this corpus, and a scorer that refuses to hold a
    selector to it can only ever measure recall.
    """
    if not isinstance(data.get("probes"), list) or not data["probes"]:
        raise SystemExit(f"{path}: `probes` must be a non-empty list")
    from src.agent_tools import TOOL_TAGS  # noqa: F401 — see `main`'s import order

    known = set(TOOL_TAGS)
    for probe in data["probes"]:
        if not str(probe.get("query") or "").strip():
            raise SystemExit(f"{path}: a probe has no `query`")
        for field in ("expect", "reject"):
            unknown = set(probe.get(field) or ()) - known
            if unknown:
                raise SystemExit(f"{path}: probe {probe['query']!r} names "
                                 f"{sorted(unknown)} in `{field}`, which is not "
                                 f"in TOOL_TAGS")
        if not probe.get("expect") and not probe.get("reject"):
            raise SystemExit(f"{path}: probe {probe['query']!r} asserts nothing")
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


def _semantic(corpus: dict, k: int) -> dict:
    """Embeddings only, in process, no ChromaDB service and no network.

    `P13-16` needed the ceiling measured before anything was built, and this is
    how: `fastembed` ships in `requirements.txt` (`B61`), runs local ONNX, and
    embedding twenty memories takes under two tenths of a second. Brute-force
    cosine over a personal Brain is arithmetic, not infrastructure.

    Raises `SkipEngine` when fastembed is not importable, so the report says so
    rather than quietly scoring one engine and calling it two.
    """
    try:
        import numpy as np
        from fastembed import TextEmbedding
    except ImportError as e:
        raise SkipEngine(f"fastembed unavailable ({e})") from e

    model = TextEmbedding()
    ids = [m["id"] for m in corpus["memories"]]
    mem = np.array(list(model.embed([m["text"] for m in corpus["memories"]])))
    mem /= np.linalg.norm(mem, axis=1, keepdims=True)
    queries = [p["query"] for p in corpus["probes"]]
    qs = np.array(list(model.embed(queries)))
    qs /= np.linalg.norm(qs, axis=1, keepdims=True)
    scores = qs @ mem.T
    return {q: [ids[j] for j in np.argsort(-scores[i])[:k]]
            for i, q in enumerate(queries)}


class SkipEngine(RuntimeError):
    """This engine cannot run here. Reported, never silently dropped."""


# `P13-14` changed what the first two names mean, and the change is the row.
# They were two ALGORITHMS — Jaccard-plus-keyword-lists against BM25-with-IDF —
# and the measurement that separated them (0.40/0.319 against 0.63/0.633, on
# this corpus, with no vector service) is what justified deleting the first.
# They are now two CALL PATHS into one scorer, and they are expected to agree.
#
# `semantic` is the third thing and it is not a call path at all: it is what the
# product does when the vector store is reachable, measured directly so the
# lexical numbers can be read against something rather than admired alone.
ENGINES = {"manager": _manager, "preface": _preface, "semantic": _semantic}

# The two that go through `src/memory_retrieval.py`. They must agree with each
# other; `semantic` is a different thing being measured and must not be held to
# that, nor to the "no engine may score perfectly" rule — for the lexical paths
# a perfect score would mean the corpus had gone soft, and for this one it is
# the ceiling `P13-16` needed to know.
CALL_PATHS = ("manager", "preface")

# What the deleted scorer measured on this corpus, kept as the floor. Not a
# ratchet on an uncalibrated number — `P3-20`'s mistake — because this one is
# calibrated by being a historical fact: it is what the product did before, and
# "never worse than what we removed" is the one comparison a deletion owes.
DELETED_SCORER_BASELINE = {"recall": 0.40, "mrr": 0.319}


# ── the tool selector, `P17-14` ───────────────────────────────────────────────


def _selector(corpus: dict, k: int) -> dict:
    """`ToolIndex.select_without_embeddings` — the selector with no vector store.

    The degraded path, and the one a person actually meets: it runs whenever
    ChromaDB is down, whenever the embedding backend exceeds the selection
    timeout, and on every run of a deployment that never had a vector service.
    `src/agent_loop.py` used to carry a second, drifted copy of it (`P17-14`);
    there is one now, and this scores it.

    `k` is unused and that is the shape of the thing being measured, not an
    oversight: a keyword/structural selector returns a set with no cutoff. The
    *size* of that set is reported instead, because "offered eleven of
    eighty-one" is the number `GAP-ANALYSIS.md` actually has.
    """
    from src.tool_index import ALWAYS_AVAILABLE, ToolIndex

    return {p["query"]: ToolIndex.select_without_embeddings(
        p["query"], set(ALWAYS_AVAILABLE)) for p in corpus["probes"]}


def _tool_semantic(corpus: dict, k: int) -> dict:
    """Embeddings only, over `BUILTIN_TOOL_DESCRIPTIONS`, in process.

    The ceiling, exactly as `_semantic` is for memory: what the selector would
    return if the vector lane were up and nothing else fired. Same model, same
    brute-force cosine, no ChromaDB — and the same `SkipEngine` when fastembed
    is not importable, so a missing dependency is reported rather than silently
    scoring one engine and calling it two.

    `ALWAYS_AVAILABLE` is unioned in because the product does that
    unconditionally, and leaving it out would score a selector that does not
    ship. It is also why `ask_user`, `update_plan` and `manage_memory` can
    never be a selector miss — `P17-14`'s classification turns on that.
    """
    try:
        import numpy as np
        from fastembed import TextEmbedding
    except ImportError as e:
        raise SkipEngine(f"fastembed unavailable ({e})") from e

    from src.tool_index import ALWAYS_AVAILABLE, BUILTIN_TOOL_DESCRIPTIONS

    names = list(BUILTIN_TOOL_DESCRIPTIONS)
    model = TextEmbedding()
    docs = np.array(list(model.embed([f"Tool: {n}\n{BUILTIN_TOOL_DESCRIPTIONS[n]}"
                                      for n in names])))
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    queries = [p["query"] for p in corpus["probes"]]
    qs = np.array(list(model.embed(queries)))
    qs /= np.linalg.norm(qs, axis=1, keepdims=True)
    scores = qs @ docs.T
    return {q: set(ALWAYS_AVAILABLE) | {names[j] for j in np.argsort(-scores[i])[:k]}
            for i, q in enumerate(queries)}


TOOL_ENGINES = {"selector": _selector, "semantic": _tool_semantic}


def score_selection(corpus: dict, offered: dict) -> dict:
    """Score a SET-valued selector. No MRR, and the absence is the point.

    Memory retrieval hands the injector a ranked list under a slot limit, so
    rank is not cosmetic and MRR measures something. Tool selection hands the
    model a set — every tool in it is in the request, in schema order, and
    there is no rank to be near the top of. Reporting an MRR here would mean
    inventing an order and then scoring it, which is the kind of number that
    survives by looking like the one next to it.

    What is reported instead:

      recall      the share of probes whose every `expect` was offered. A tool
                  that is not offered cannot be called, so this is the ceiling
                  on everything the call column can ever say.
      refusal     the share of probes that offered none of their `reject`.
                  This is the half `GAP-ANALYSIS.md` has no column for: 69 of
                  81 tools offered and never picked is a precision failure, and
                  a scorer that only measures recall rewards offering
                  everything.
      offered     the mean size of the offered set — `GAP-ANALYSIS.md`'s
                  "median 11 of 81", measured rather than recalled.
    """
    hits, clean, sizes, misses, spills = 0, 0, [], [], []
    for probe in corpus["probes"]:
        want = set(probe.get("expect") or ())
        avoid = set(probe.get("reject") or ())
        got = set(offered.get(probe["query"]) or ())
        sizes.append(len(got))
        if want <= got:
            hits += 1
        else:
            misses.append({"query": probe["query"], "missing": sorted(want - got),
                           "why": probe.get("why", "")})
        offered_bad = sorted(avoid & got)
        if offered_bad:
            spills.append({"query": probe["query"], "offered": offered_bad,
                           "why": probe.get("why", "")})
        else:
            clean += 1
    n = len(corpus["probes"])
    return {"n": n, "recall": hits / n, "refusal": clean / n,
            "offered": sum(sizes) / n, "hits": hits, "clean": clean,
            "misses": misses, "spills": spills}


def _report_selection(name: str, result: dict, verbose: bool) -> None:
    print(f"  {name:<10} recall {result['recall']:.2f}"
          f"   refusal {result['refusal']:.2f}"
          f"   offered {result['offered']:.1f} tools/query"
          f"   ({result['hits']}/{result['n']}, {result['clean']}/{result['n']})")
    if not verbose:
        return
    for miss in result["misses"]:
        print(f"      MISS  {miss['query']!r} did not offer {miss['missing']}")
        if miss["why"]:
            print(f"            {miss['why']}")
    for spill in result["spills"]:
        print(f"      SPILL {spill['query']!r} offered {spill['offered']}")
        if spill["why"]:
            print(f"            {spill['why']}")


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


def _main_tools(args) -> int:
    """`--kind tools`. Same corpus discipline, same provenance warning.

    Kept as its own function rather than branching through `main` because the
    two retrievers report different columns — a set has no MRR — and a printer
    that switches on a flag halfway down is how one of them ends up quietly
    reporting the other's number.
    """
    corpus = _load(args.corpus)
    if corpus.get("kind") != "tools":
        raise SystemExit(f"{args.corpus}: --kind tools needs a corpus declaring "
                         f'"kind": "tools"')
    names = list(TOOL_ENGINES) if args.engine == "both" else [args.engine]
    unknown = [n for n in names if n not in TOOL_ENGINES]
    if unknown:
        raise SystemExit(f"--kind tools has no engine {unknown[0]!r}; "
                         f"choose from {sorted(TOOL_ENGINES)}")
    results, skipped = {}, {}
    for name in names:
        try:
            results[name] = score_selection(corpus, TOOL_ENGINES[name](corpus, args.k))
        except SkipEngine as e:
            skipped[name] = str(e)

    if args.json:
        json.dump({"kind": "tools", "provenance": corpus["provenance"],
                   "skipped": skipped,
                   "results": {n: {k: v for k, v in r.items()
                                   if k not in ("misses", "spills")}
                               for n, r in results.items()}},
                  sys.stdout, indent=2)
        print()
        return 0

    from src.agent_tools import TOOL_TAGS  # noqa: F401 — import order, see below

    print(f"tool-selection eval · {args.corpus.name} · {len(corpus['probes'])} "
          f"probes · {len(TOOL_TAGS)} tools in the surface · no ChromaDB service")
    print(f"provenance: {corpus['provenance']} — "
          f"{PROVENANCE_NOTE.get(corpus['provenance'], 'unrecognised, treat with suspicion')}")
    print()
    for name in results:
        _report_selection(name, results[name], args.verbose)
    for name, why in skipped.items():
        print(f"  {name:<10} not scored — {why}")
    print()
    if corpus["provenance"] != "curated":
        print("These probes were written here, not typed by an operator. The "
              "numbers describe the selector on the shapes we chose; run it "
              "against your own deployment's asks before quoting them.")
    # A report, never a gate — the same call `P13-13` made for memory and for
    # the same reason: a ratchet on a number nobody has calibrated is `P3-20`'s
    # mistake. `tests/test_the_selector_is_measured_not_asserted.py` is where
    # the specific properties this row fixed are held.
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=None)
    ap.add_argument("--engine", choices=[*ENGINES, *TOOL_ENGINES, "both"], default="both")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--generate", type=Path, metavar="MEMORY_JSON")
    # `P17-14`. Default `memory`, so the invocation CI already runs keeps
    # meaning what it meant. The tool selector is the other retriever in this
    # product and it had no number at all until this row.
    ap.add_argument("--kind", choices=("memory", "tools"), default="memory",
                    help="which retriever to score (default: memory)")
    ap.add_argument("--verbose", action="store_true", help="print every miss and why it was chosen")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.generate:
        json.dump(_generate(args.generate), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    if args.corpus is None:
        args.corpus = _DEFAULT_TOOL_CORPUS if args.kind == "tools" else _DEFAULT_CORPUS

    if args.kind == "tools":
        return _main_tools(args)

    corpus = _load(args.corpus)
    names = list(ENGINES) if args.engine == "both" else [args.engine]
    results, skipped = {}, {}
    for name in names:
        try:
            results[name] = score(corpus, ENGINES[name](corpus, args.k), args.k)
        except SkipEngine as e:
            skipped[name] = str(e)



    if args.json:
        json.dump({"provenance": corpus["provenance"], "skipped": skipped,
                   "results": {n: {k: v for k, v in r.items() if k != "misses"}
                               for n, r in results.items()}},
                  sys.stdout, indent=2)
        print()
        return 0

    # "no ChromaDB service" and not "no vector service": `semantic` below runs
    # the embedding model in this process, which is the whole point of `P13-21`.
    print(f"retrieval eval · {args.corpus.name} · {len(corpus['memories'])} memories, "
          f"{len(corpus['probes'])} probes · no ChromaDB service")
    print(f"provenance: {corpus['provenance']} — "
          f"{PROVENANCE_NOTE.get(corpus['provenance'], 'unrecognised, treat with suspicion')}")
    print()
    for name in results:
        _report(name, results[name], args.k, args.verbose)
    for name, why in skipped.items():
        print(f"  {name:<10} not scored — {why}")
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
