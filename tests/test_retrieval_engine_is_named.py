# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B61` — the product must not report a keyword guess as a vector result.

Semantic memory search runs against a ChromaDB *service*: a separate process,
probed with a 2s TCP connect. It can be up at install and down at any moment
after, and when it is down the code falls back to lexical scoring. Before this
row every layer above described that fallback as though the vector store had
answered, so the Brain got quietly worse at its one job and looked identical
while it happened.

These tests are about what the product *says*, not what it finds. Retrieval
quality is `P13-13`'s golden set; this is the honesty that makes that set
readable, because a scored run whose engine is unknown cannot be compared to
another.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import retrieval_engine
from src.chat_processor import ChatProcessor
from src.memory_provider import MemorySearchHit

_REPO = Path(__file__).resolve().parents[1]
_RENDERER = _REPO / "static" / "js" / "chatRenderer.js"


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


class _Vector:
    """A vector store that is up, and answers with whatever it was given."""

    def __init__(self, results, healthy=True):
        self._results = results
        self.healthy = healthy

    def search(self, query, k=5):
        return list(self._results)


def _processor(rows, vector=None):
    proc = ChatProcessor(memory_manager=_Memory(rows), personal_docs_manager=_Docs())
    proc.memory_vector = vector
    return proc


def _rows():
    return [
        {"id": "dark", "text": "User prefers dark mode in every editor.",
         "category": "preference", "timestamp": 10},
        {"id": "coffee", "text": "User likes dark roast coffee beans.",
         "category": "preference", "timestamp": 9},
    ]


# ── the run-level report ──────────────────────────────────────────────────────


def test_a_run_with_no_vector_store_says_keyword_not_nothing():
    report = {}
    _processor(_rows())._hybrid_retrieve("dark mode editor", _rows(), report=report)
    assert report["engine"] == retrieval_engine.KEYWORD
    assert report["vector_healthy"] is False


def test_a_run_with_a_live_vector_store_says_so():
    vector = _Vector([{"memory_id": "dark", "score": 0.8}])
    report = {}
    _processor(_rows(), vector)._hybrid_retrieve("dark mode editor", _rows(), report=report)
    assert report["engine"] == retrieval_engine.HYBRID
    assert report["vector_healthy"] is True
    assert report["vector_ids"] == ["dark"]


def test_a_healthy_index_that_matched_nothing_is_not_reported_as_down():
    # The distinction the resolver exists for. An empty index and an
    # unreachable service look identical from the result list and are
    # completely different problems: one is "nothing has been remembered yet",
    # the other is "the service is down and the Brain is degraded".
    report = {}
    _processor(_rows(), _Vector([]))._hybrid_retrieve("dark mode", _rows(), report=report)
    assert report["vector_healthy"] is True
    assert report["engine"] == retrieval_engine.HYBRID


def test_an_unhealthy_vector_store_is_keyword_even_though_one_is_attached():
    # `healthy` is False, so the object exists and must not be believed.
    report = {}
    _processor(_rows(), _Vector([{"memory_id": "dark", "score": 0.9}], healthy=False))._hybrid_retrieve(
        "dark mode", _rows(), report=report)
    assert report["engine"] == retrieval_engine.KEYWORD
    assert report["vector_healthy"] is False


@pytest.mark.parametrize("message, rows", [
    ("", []),
    ("dark mode", []),
    ("", [{"id": "a", "text": "x", "timestamp": 1}]),
])
def test_a_bail_out_still_reports_and_does_not_leave_a_stale_claim(message, rows):
    # The failure this guards: a report dict left untouched by an early return
    # reads as "no engine recorded", and the renderer's `m.engine === 'vector'`
    # check would treat the absence as "not degraded" — reporting a run that
    # never happened as a healthy one.
    report = {"engine": retrieval_engine.VECTOR, "vector_healthy": True}
    _processor(rows or _rows())._hybrid_retrieve(message, rows, report=report)
    assert report["engine"] == retrieval_engine.KEYWORD
    assert report["vector_healthy"] is False


def test_callers_that_do_not_want_a_report_are_unaffected():
    # The out-parameter shape, and the reason for it. The return value stays a
    # plain list of memory dicts; widening it to a tuple is what broke eleven
    # tests when `_build_base_prompt` did it.
    out = _processor(_rows())._hybrid_retrieve("dark mode editor", _rows())
    assert isinstance(out, list)
    assert all(isinstance(m, dict) for m in out)


# ── what reaches the person ───────────────────────────────────────────────────


def _used(message, rows, vector=None):
    proc = _processor(rows, vector)
    proc.build_context_preface(message=message, session=SimpleNamespace(),
                               use_rag=False, use_memory=True)
    return proc._last_used_memories


def test_every_memory_shown_to_a_person_carries_the_engine_that_found_it():
    used = _used("dark mode editor", _rows())
    assert used, "nothing was recalled, so this test proves nothing"
    assert all("engine" in m for m in used)


def test_a_pinned_memory_is_reported_as_pinned_not_as_a_search_hit():
    # No engine chose it. Calling a pinned memory a keyword hit is the same lie
    # pointed the other way, and it is the one a reader would never question.
    rows = [{"id": "name", "text": "User's name is Felix.", "category": "identity",
             "pinned": True, "timestamp": 3}]
    used = _used("what is my name", rows)
    pinned = [m for m in used if m["type"] == "pinned"]
    assert pinned, "the pinned memory was not injected, so this test proves nothing"
    assert all(m["engine"] == retrieval_engine.PINNED for m in pinned)


def test_a_hybrid_run_labels_each_memory_by_what_actually_found_it():
    # The reason the label is per memory and not per run. The index is told
    # about `dark` only; the query also names `roast` and `beans` so BM25 pulls
    # `coffee` in on wording alone. A single run-level label would claim the
    # index found both.
    #
    # The first version of this test asked for "dark mode editor", which
    # recalled exactly one memory — so the loop over the others ran zero times
    # and a mutation labelling *everything* `vector` survived. A test whose
    # negative half never executes is not a test.
    #
    # `P13-16` moved the index score from `0.9` to `0.6`, and the reason is the
    # row: at `0.9` the vector hit scores `0.86` against the keyword hit's
    # `0.40`, and the selection step drops anything under half the best answer —
    # so `coffee` stopped coming back and the negative half stopped executing
    # again, for a new reason. `0.6` is still an unambiguous vector hit, well
    # clear of `_MIN_VECTOR`, and it keeps both memories in the result, which is
    # the only thing this test needs from the number.
    rows = _rows()
    used = _used("dark mode editor and dark roast coffee beans", rows,
                 _Vector([{"memory_id": "dark", "score": 0.6}]))
    recalled = {m["text"]: m["engine"] for m in used if m["type"] == "recalled"}
    by_id = {m["text"]: m["id"] for m in rows}
    labelled = {by_id[text]: engine for text, engine in recalled.items()}
    assert set(labelled) == {"dark", "coffee"}, (
        f"both memories must come back for this test to mean anything, got {set(labelled)}")
    assert labelled["dark"] == retrieval_engine.VECTOR
    assert labelled["coffee"] == retrieval_engine.KEYWORD


# ── the provider hit ──────────────────────────────────────────────────────────


def test_a_search_hit_says_which_engine_produced_it():
    # `score=None` on the fallback path was indistinguishable from a vector hit
    # that scored nothing, so no caller could tell the two apart. The score is
    # still None — the lexical scorer discards it and inventing one would be a
    # different lie — but the engine now says why.
    keyword = MemorySearchHit(memory=None, provider_id="native", score=None,
                              engine=retrieval_engine.KEYWORD)
    vector = MemorySearchHit(memory=None, provider_id="native", score=0.0,
                             engine=retrieval_engine.VECTOR)
    assert keyword.engine != vector.engine
    assert retrieval_engine.is_degraded(keyword.engine)
    assert not retrieval_engine.is_degraded(vector.engine)


class _ProviderMemory:
    """The real `MemoryManager` scorer, with the file I/O left out.

    Not a hand-rolled double. A double that satisfies `load` and then answers
    `get_relevant_memories` however the test finds convenient would let the
    fallback branch pass while doing something the real one does not — which is
    exactly the failure mode this file is about.
    """

    def __init__(self, rows):
        from src.memory import MemoryManager

        self.rows = rows
        self._real = MemoryManager.__new__(MemoryManager)

    def load(self, owner=None):
        return list(self.rows)

    def get_relevant_memories(self, *args, **kwargs):
        return self._real.get_relevant_memories(*args, **kwargs)


def _provider(vector=None):
    from src.memory_provider import NativeMemoryProvider

    provider = NativeMemoryProvider.__new__(NativeMemoryProvider)
    provider.memory_manager = _ProviderMemory([
        dict(r, owner=None) for r in _rows()])
    provider.memory_vector = vector
    return provider



async def test_the_provider_labels_a_real_vector_hit_as_a_vector_hit():
    hits = await _provider(_Vector([{"memory_id": "dark", "score": 0.7}])).recall("dark mode")
    assert hits, "the vector branch returned nothing, so this test proves nothing"
    assert all(h.engine == retrieval_engine.VECTOR for h in hits)



async def test_the_provider_labels_the_fallback_as_keyword_not_as_a_vector_hit():
    # The original defect in this file: `score=None` on the fallback path was
    # indistinguishable from a vector hit that scored nothing, so every caller
    # downstream treated a keyword guess as a semantic result.
    hits = await _provider(None).recall("dark mode editor")
    assert hits, "the fallback returned nothing, so this test proves nothing"
    assert all(h.engine == retrieval_engine.KEYWORD for h in hits)
    assert all(h.score is None for h in hits), (
        "the lexical scorer discards its score; inventing one here is a different lie")



async def test_a_caller_can_tell_the_two_apart_without_reading_the_score():
    # The point of the field. Both calls return hits; only `engine` separates
    # "the index answered" from "we matched on wording".
    vector = await _provider(_Vector([{"memory_id": "dark", "score": 0.7}])).recall("dark mode")
    keyword = await _provider(None).recall("dark mode editor")
    assert {h.engine for h in vector} != {h.engine for h in keyword}
    assert not any(retrieval_engine.is_degraded(h.engine) for h in vector)
    assert all(retrieval_engine.is_degraded(h.engine) for h in keyword)


# ── nothing may name an engine that did not run ───────────────────────────────


def test_no_identifier_calls_a_lexical_result_a_vector_one():
    # The original bug in its purest form: `src/ai_interaction.py` assigned
    # `get_relevant_memories(...)` — the lexical scorer, which consults no
    # embedding anywhere — to a variable named `vector_results`. A reader
    # checking whether semantic search reached the agent's memory tools would
    # have read that line and stopped looking.
    for path in sorted(_REPO.glob("src/*.py")) + sorted(_REPO.glob("mcp_servers/*.py")):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        for match in re.finditer(r"^\s*(\w*vector\w*)\s*=\s*(.+)$", code, re.M):
            assert "get_relevant_memories" not in match.group(2), (
                f"{path.name}: `{match.group(1)}` is assigned a lexical result"
            )


def test_chromadb_is_not_described_as_optional_because_it_ships_by_default():
    # `requirements-optional.txt` records the move in so many words, and the
    # row this test belongs to was filed partly because a docstring still said
    # otherwise. The claim and the requirements file have to agree.
    reqs = (_REPO / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^chromadb-client\b", reqs, re.M), "chromadb-client left requirements.txt"
    assert re.search(r"^fastembed\b", reqs, re.M), "fastembed left requirements.txt"
    client = (_REPO / "src" / "chroma_client.py").read_text(encoding="utf-8")
    assert "it's an optional dependency" not in client
    assert "Install the optional" not in client


# ── the two copies of the vocabulary ──────────────────────────────────────────


def test_the_browser_and_the_server_agree_on_what_each_engine_is_called():
    # Two copies because one is Python and one is a browser. This is the test
    # that lets that be true: an engine added on one side and forgotten on the
    # other fails here rather than rendering a raw identifier at a person.
    text = _RENDERER.read_text(encoding="utf-8")
    match = re.search(r"const MEMORY_ENGINE_LABELS = \{(.*?)\};", text, re.S)
    assert match, "MEMORY_ENGINE_LABELS not found in chatRenderer.js"
    js = dict(re.findall(r"(\w+):\s*'([^']*)'", match.group(1)))
    assert js == retrieval_engine.LABELS, (
        "the browser and the server disagree about engine names"
    )


# ── the pill, executed rather than read ───────────────────────────────────────

_DEGRADED_HARNESS = """
    __FN__
    console.log(JSON.stringify(memoryRecallDegraded(__MEMS__)));
"""

_PARTS_HARNESS = """
    __FN__
    __PARTS__
    console.log(JSON.stringify(memoryPillParts(__MEMS__)));
"""


def _js_function(name: str) -> str:
    text = _RENDERER.read_text(encoding="utf-8")
    match = re.search(rf"\nexport function {re.escape(name)}\([^)]*\) \{{", text)
    assert match, f"{name} not found in chatRenderer.js"
    start, i, depth = match.start() + 1, match.end(), 1
    while i < len(text) and depth:
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    assert depth == 0, f"{name} body did not close"
    return re.sub(r"^export\s+", "", text[start:i])


def _node(script: str):
    import json as _json
    import subprocess
    import textwrap

    proc = subprocess.run(["node", "--input-type=module"], input=textwrap.dedent(script),
                          capture_output=True, text=True, cwd=str(_REPO), timeout=30)
    assert proc.returncode == 0, proc.stderr
    return _json.loads(proc.stdout.strip().splitlines()[-1])


def _pill_parts(mems) -> list:
    """`memoryPillParts` itself — what the pill actually says.

    Testing `memoryRecallDegraded` alone proves the ingredient and not the
    recipe: a mutation that computed the warning correctly and then never put
    it on the pill survived every test of the helper.
    """
    import json as _json

    script = (_PARTS_HARNESS
              .replace("__FN__", _js_function("memoryRecallDegraded"))
              .replace("__PARTS__", _js_function("memoryPillParts"))
              .replace("__MEMS__", _json.dumps(mems)))
    return _node(script)


def _degraded(mems) -> bool:
    """`memoryRecallDegraded` itself, lifted out of the renderer and run.

    The same shape `P3-10` established for `notes.js`. A test that greps
    chatRenderer.js for the word `keyword` is testing the file, not the
    behaviour (`Law 20`), and this is the one piece of `B61` a person actually
    reads — so it is the piece that most needs executing.
    """
    import json as _json
    import subprocess
    import textwrap

    text = _RENDERER.read_text(encoding="utf-8")
    match = re.search(r"\nexport function memoryRecallDegraded\(mems\) \{", text)
    assert match, "memoryRecallDegraded not found in chatRenderer.js"
    start, i, depth = match.start() + 1, match.end(), 1
    while i < len(text) and depth:
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    assert depth == 0, "memoryRecallDegraded body did not close"
    fn = re.sub(r"^export\s+", "", text[start:i])

    script = _DEGRADED_HARNESS.replace("__FN__", fn).replace("__MEMS__", _json.dumps(mems))
    proc = subprocess.run(["node", "--input-type=module"], input=textwrap.dedent(script),
                          capture_output=True, text=True, cwd=str(_REPO), timeout=30)
    assert proc.returncode == 0, proc.stderr
    return _json.loads(proc.stdout.strip().splitlines()[-1])


_HAS_NODE = __import__("shutil").which("node") is not None
_needs_node = pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")


@_needs_node
def test_the_pill_warns_when_every_recalled_memory_came_from_wording_alone():
    # The user-visible half of the whole row. Without it the Brain gets quietly
    # worse at its one job and the pill looks identical while it happens.
    assert _degraded([{"type": "recalled", "engine": "keyword"}]) is True


@_needs_node
def test_the_pill_stays_quiet_when_the_index_answered():
    assert _degraded([{"type": "recalled", "engine": "vector"}]) is False


@_needs_node
def test_one_vector_hit_is_enough_to_prove_the_service_is_up():
    # A hybrid run has both, and it is not degraded — the service answered.
    # Warning here would train people to ignore the warning.
    assert _degraded([{"type": "recalled", "engine": "vector"},
                      {"type": "recalled", "engine": "keyword"}]) is False


@_needs_node
def test_a_message_with_only_pinned_memories_is_not_degraded():
    # Nothing was searched, so there is nothing to warn about. Pinned memories
    # were injected, not found.
    assert _degraded([{"type": "pinned", "engine": "pinned"},
                      {"type": "pinned", "engine": "pinned"}]) is False


@_needs_node
@pytest.mark.parametrize("mems", [[], None, [None], [{}], [{"type": "recalled"}]])
def test_nothing_shaped_wrong_makes_the_pill_claim_a_failure(mems):
    # The pill renders on every assistant message. A warning raised by a
    # missing field would be a false alarm on the most common path there is,
    # and a false degradation warning is worse than none — it points at the
    # vector service when the vector service is fine.
    assert _degraded(mems) is False


@_needs_node
def test_a_pinned_memory_never_raises_a_search_warning_whatever_engine_it_carries():
    # `type` is authoritative, not `engine`. This arrives over a wire, and a
    # pinned memory that somehow carries `keyword` must still not warn: nothing
    # searched for it. Without this the type check is dead weight a mutation
    # removes for free.
    assert _degraded([{"type": "pinned", "engine": "keyword"}]) is False


@_needs_node
def test_the_warning_actually_reaches_the_pill():
    # The recipe, not the ingredient. The helper can be perfect and the pill
    # still say nothing, which is exactly what the row is about.
    assert _pill_parts([{"type": "recalled", "engine": "keyword"}]) == ["1 recalled", "keyword only"]


@_needs_node
def test_the_pill_counts_before_it_warns():
    # Order matters: the count is what the pill is for and the warning is a
    # qualifier on it. "keyword only, 2 recalled" reads as a different claim.
    parts = _pill_parts([{"type": "pinned", "engine": "pinned"},
                         {"type": "recalled", "engine": "keyword"}])
    assert parts == ["1 pinned", "1 recalled", "keyword only"]


@_needs_node
def test_a_healthy_run_says_nothing_extra():
    assert _pill_parts([{"type": "recalled", "engine": "vector"}]) == ["1 recalled"]
