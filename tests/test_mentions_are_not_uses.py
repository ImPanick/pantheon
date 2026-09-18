# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-15` — how often the person *said* it, not how often the system *reached
for* it.

Extraction runs on the last six messages after every response, max two facts, so
the newest conversation is the most heavily mined and repetition across sessions
— the strongest durability signal available — was recorded nowhere.

**The defect was not that nothing counted. It was that the counting moment was
the discarding moment.** All three dedupe paths in the extractor located the
matching memory *precisely* — by vector similarity, by exact text, by Jaccard —
and then `continue`d. Same class as the thirteen `P4` rows: a value computed,
used for one branch, and never recorded.

And the `Law 14` trap this row had to walk around, found before anything was
written: **reinforcement already ships.** `increment_uses` is called on every
injected memory and the Brain's "Most used" sort is that signal on screen
(`P13-04`). `uses` counts recalls; this counts mentions; a memory the assistant
keeps injecting and a memory the person keeps raising are different kinds of
important, and one counter cannot mean both.
"""

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import memory_retrieval
from src.memory import MemoryManager

_REPO = Path(__file__).resolve().parents[1]
_MEMJS = _REPO / "static" / "js" / "memory.js"


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(str(tmp_path))


def _seed(manager, text="User deploys with Docker Compose on Sunday evenings."):
    # `add_entry` builds the record; it does not store it. The extractor appends
    # and saves, and so must this.
    entry = manager.add_entry(text, source="auto", category="fact")
    entries = manager.load_all_for_update()
    entries.append(entry)
    manager.save(entries)
    return entry


# ── the two counters stay apart ───────────────────────────────────────────────


def test_a_mention_is_not_a_use(manager):
    entry = _seed(manager)
    manager.record_mention(entry["id"], session_id="s1")
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["mentions"] == 1
    assert stored["uses"] == 0, "recording a mention must not touch the recall counter"


def test_a_use_is_not_a_mention(manager):
    entry = _seed(manager)
    manager.increment_uses([entry["id"]])
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["uses"] == 1
    assert stored["mentions"] == 0, "injecting a memory is not the person saying it"


def test_the_two_counters_can_disagree_completely(manager):
    # The case that makes the distinction worth its storage: a memory the
    # assistant leans on constantly and the person has mentioned once, beside
    # one the person raises every week and the assistant never picks.
    injected = _seed(manager, "User's build machine is a Ryzen 7900X.")
    repeated = _seed(manager, "User is allergic to shellfish.")
    for _ in range(9):
        manager.increment_uses([injected["id"]])
    for n in range(6):
        manager.record_mention(repeated["id"], session_id=f"s{n}")
    rows = {e["id"]: e for e in manager.load()}
    assert (rows[injected["id"]]["uses"], rows[injected["id"]]["mention_sessions"]) == (9, 0)
    assert (rows[repeated["id"]]["uses"], rows[repeated["id"]]["mention_sessions"]) == (0, 6)


# ── sessions, not repetitions ─────────────────────────────────────────────────


def test_saying_it_three_times_in_one_conversation_is_one_conversation(manager):
    # Extraction runs after *every response*, so without this a single chatty
    # session would look like overwhelming evidence of durability.
    entry = _seed(manager)
    for _ in range(3):
        manager.record_mention(entry["id"], session_id="same-session")
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["mentions"] == 3, "every restatement is still observed"
    assert stored["mention_sessions"] == 1, "but they are one conversation's worth of evidence"


def test_separate_conversations_count_separately(manager):
    entry = _seed(manager)
    for n in range(4):
        manager.record_mention(entry["id"], session_id=f"session-{n}")
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["mention_sessions"] == 4


def test_the_session_list_is_bounded_but_the_count_is_not(manager):
    # A memory raised weekly for two years must not grow an unbounded list of
    # session ids inside the store. The oldest id has already done its work.
    entry = _seed(manager)
    total = MemoryManager.MENTION_SESSION_MEMORY + 20
    for n in range(total):
        manager.record_mention(entry["id"], session_id=f"s{n}")
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["mention_sessions"] == total
    assert len(stored["mention_session_ids"]) == MemoryManager.MENTION_SESSION_MEMORY


def test_a_mention_with_no_session_still_counts_as_a_mention(manager):
    # Not every caller has a session. Losing the observation entirely because
    # the id was missing is the failure this row exists to end.
    entry = _seed(manager)
    manager.record_mention(entry["id"], session_id=None)
    stored = next(e for e in manager.load() if e["id"] == entry["id"])
    assert stored["mentions"] == 1
    assert stored["mention_sessions"] == 0


def test_an_unknown_id_changes_nothing(manager):
    _seed(manager)
    before = json.dumps(manager.load(), sort_keys=True)
    assert manager.record_mention("no-such-memory", "s1") is None
    assert json.dumps(manager.load(), sort_keys=True) == before


# ── the record's own history ──────────────────────────────────────────────────


def test_first_mentioned_is_backfilled_rather_than_left_empty(manager):
    # A memory that predates this row has no `first_mentioned`, and "we started
    # counting late" is a worse answer than the one the record already knows:
    # the timestamp *is* the first time it was said. Seeded as raw JSON, because
    # `add_entry` sets the field and would hide whether the backfill runs.
    Path(manager.memory_file).write_text(json.dumps([
        {"id": "legacy", "text": "An old memory.", "timestamp": 1700000000}]),
        encoding="utf-8")
    manager.record_mention("legacy", "s1")
    stored = next(e for e in manager.load() if e["id"] == "legacy")
    assert stored["first_mentioned"] == 1700000000
    assert stored["last_mentioned"] >= stored["first_mentioned"]


def test_a_backfilled_first_mention_is_not_overwritten_later(manager):
    # It is the *first*. A second mention that moved it would turn the field
    # into a duplicate of `last_mentioned`.
    Path(manager.memory_file).write_text(json.dumps([
        {"id": "legacy", "text": "An old memory.", "timestamp": 1700000000}]),
        encoding="utf-8")
    manager.record_mention("legacy", "s1")
    manager.record_mention("legacy", "s2")
    stored = next(e for e in manager.load() if e["id"] == "legacy")
    assert stored["first_mentioned"] == 1700000000


def test_every_memory_that_predates_this_row_reads_as_zero(manager):
    # Not one. The store cannot know how often a fact was said before anyone was
    # counting, and inventing a 1 would make an old memory look freshly
    # confirmed — a claim nothing supports.
    path = Path(manager.memory_file)
    path.write_text(json.dumps([
        {"id": "legacy", "text": "An old memory from before this row.",
         "timestamp": 1700000000}]), encoding="utf-8")
    stored = manager.load()[0]
    assert stored["mentions"] == 0
    assert stored["mention_sessions"] == 0
    assert stored["uses"] == 0


# ── the retrieval prior, and the cap that keeps it a tiebreaker ───────────────


def test_durability_needs_more_than_one_conversation():
    assert memory_retrieval._durability({"mention_sessions": 0}) == 0.0
    assert memory_retrieval._durability({"mention_sessions": 1}) == 0.0
    assert memory_retrieval._durability({"mention_sessions": 2}) > 0.0


def test_durability_saturates_so_repetition_cannot_run_away():
    # The gap between 1 and 3 conversations is evidence; the gap between 9 and
    # 11 is noise. A linear term would let a much-repeated fact drown a precise
    # one, which is the failure mode the cap exists to prevent.
    assert memory_retrieval._durability({"mention_sessions": 8}) == 1.0
    assert memory_retrieval._durability({"mention_sessions": 500}) == 1.0
    growth_early = (memory_retrieval._durability({"mention_sessions": 3})
                    - memory_retrieval._durability({"mention_sessions": 2}))
    growth_late = (memory_retrieval._durability({"mention_sessions": 7})
                   - memory_retrieval._durability({"mention_sessions": 6}))
    assert growth_early > growth_late


def test_durability_reads_sessions_and_never_uses():
    # The whole row in one assertion. If this ever reads `uses`, the two signals
    # have collapsed into one and the Brain has grown a number that means two
    # things.
    assert memory_retrieval._durability({"uses": 500, "mention_sessions": 0}) == 0.0
    assert memory_retrieval._durability({"uses": 0, "mention_sessions": 5}) > 0.0


def test_durability_cannot_outrank_relevance():
    # It shares recency's five percent rather than taking its own. A memory
    # raised in fifty conversations that has nothing to do with the question
    # must still lose to one that answers it.
    rows = [{"id": "relevant", "text": "The deployment key lives in the vault.",
             "timestamp": 1735689600, "mention_sessions": 0},
            {"id": "repeated", "text": "Completely unrelated note about tarmac.",
             "timestamp": 1735689600, "mention_sessions": 50}]
    manager = MemoryManager.__new__(MemoryManager)
    ranked = [m["id"] for m in manager.get_relevant_memories(
        "where is the deployment key", rows, max_items=5)]
    assert ranked[:1] == ["relevant"]


def test_two_equally_relevant_memories_are_broken_by_durability():
    # And the positive case, or the cap would be indistinguishable from the term
    # being absent. Same text, same age; only the count differs.
    rows = [{"id": "once", "text": "The deployment key lives in the vault.",
             "timestamp": 1735689600, "mention_sessions": 1},
            {"id": "often", "text": "The deployment key lives in the vault.",
             "timestamp": 1735689600, "mention_sessions": 6}]
    manager = MemoryManager.__new__(MemoryManager)
    ranked = manager.explain_relevant_memories("where is the deployment key", rows, max_items=5)
    assert [r["memory"]["id"] for r in ranked][:1] == ["often"]
    assert "separate conversations" in ranked[0]["reason"]


def test_recency_and_durability_share_one_slice_rather_than_taking_two():
    # Two capped tiebreakers added side by side make a ten percent tiebreaker,
    # which is not a tiebreaker any more.
    source = (_REPO / "src" / "memory_retrieval.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    assert "tiebreak = _W_RECENCY * max(recency, durability)" in code
    assert "_W_DURABILITY" not in code, "a second weight means a second slice"


# ── the Brain says which number is which ──────────────────────────────────────


_PILLS_HARNESS = """
    __FN__
    console.log(JSON.stringify(memoryCountPills(__MEMORY__)));
"""


def _pills(memory) -> list:
    """`memoryCountPills` itself, run rather than read.

    `Law 20`, and `B61`'s lesson before it could bite twice: a helper can be
    perfect and the pill still show nothing, so what the Brain says has to be
    data a test executes.
    """
    import subprocess
    import textwrap

    js = _MEMJS.read_text(encoding="utf-8")
    m = re.search(r"\nexport function memoryCountPills\(memory\) \{", js)
    assert m, "memoryCountPills not found in memory.js"
    start, i, depth = m.start() + 1, m.end(), 1
    while i < len(js) and depth:
        depth += (js[i] == "{") - (js[i] == "}")
        i += 1
    assert depth == 0, "memoryCountPills body did not close"
    fn = re.sub(r"^export\s+", "", js[start:i])
    script = (_PILLS_HARNESS.replace("__FN__", fn)
              .replace("__MEMORY__", json.dumps(memory)))
    proc = subprocess.run(["node", "--input-type=module"], input=textwrap.dedent(script),
                          capture_output=True, text=True, cwd=str(_REPO), timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_needs_node = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node binary not on PATH")


@_needs_node
def test_the_two_pills_are_built_from_two_different_fields():
    out = _pills({"uses": 11, "mention_sessions": 3})
    assert [p["text"] for p in out] == ["11×", "said in 3"], (
        "one number cannot mean both; these must read the two fields separately")
    assert [p["className"] for p in out] == ["memory-item-uses", "memory-item-mentions"]


@_needs_node
def test_a_memory_the_assistant_leans_on_shows_no_mentions_pill():
    assert [p["text"] for p in _pills({"uses": 9, "mention_sessions": 0})] == ["9×"]


@_needs_node
def test_a_memory_the_person_keeps_raising_shows_no_uses_pill():
    assert [p["text"] for p in _pills({"uses": 0, "mention_sessions": 6})] == ["said in 6"]


@_needs_node
def test_one_conversation_is_not_a_pattern_and_says_nothing():
    # A memory is created by being said once. "said in 1" beside every fresh
    # memory is noise, and noise trains people to stop reading the pill.
    assert _pills({"uses": 0, "mention_sessions": 1}) == []


@_needs_node
@pytest.mark.parametrize("memory", [{}, None, {"uses": None}, {"mention_sessions": "x"}])
def test_a_memory_with_nothing_to_count_renders_nothing(memory):
    assert _pills(memory) == []


@_needs_node
def test_each_pill_explains_itself_where_a_person_actually_looks():
    # The row's `Verify` asks for the difference to be stated in the UI, and a
    # tooltip is where somebody looks when two numbers sit side by side.
    uses, said = _pills({"uses": 11, "mention_sessions": 3})
    assert "Injected into chat context 11 times" in uses["title"]
    assert "3 separate conversations" in said["title"]
    assert "which counts how often it was injected" in said["title"], (
        "the mentions pill must name what it is *not*, or the pair is a riddle")


@_needs_node
def test_the_singular_reads_correctly():
    assert "1 time" in _pills({"uses": 1})[0]["title"]
    assert "1 times" not in _pills({"uses": 1})[0]["title"]


def test_most_said_is_its_own_sort_and_not_a_tweak_to_most_used():
    # The two orders answer different questions; merging them produces a list
    # nobody can interpret.
    js = _MEMJS.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith("//"))
    assert "sort === 'mentions'" in code
    assert "sort === 'uses'" in code
    html = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert html.count("Most said") == 2, "both sort selectors must offer it"
    assert "mentions" in js[js.index("_MEMORY_SORT_ICONS"):js.index("_memorySortIcon")], \
        "the sort needs its own icon or it renders as Newest"


# ── the recipe, not the ingredient ────────────────────────────────────────────
#
# `B61`'s lesson, applied before it could bite again: `record_mention` can be
# perfect and the extractor still never call it. All three dedupe paths have to
# be walked with a double that records, and the double has to be *asserted* —
# a stub nobody checks is how a caller quietly stops calling.

import asyncio          # noqa: E402
import importlib.util   # noqa: E402
import sys              # noqa: E402
import types            # noqa: E402


def _extractor():
    # Loaded by path so `services/__init__` (and the search stack behind it)
    # stays out of this. Same approach as the cross-tenant regression test.
    path = _REPO / "services" / "memory" / "memory_extractor.py"
    spec = importlib.util.spec_from_file_location("memory_extractor_mentions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub_llm(monkeypatch, facts_json):
    mod = types.ModuleType("src.llm_core")

    async def llm_call_async(*a, **k):
        return facts_json

    mod.llm_call_async = llm_call_async
    src_pkg = sys.modules.get("src") or types.ModuleType("src")
    monkeypatch.setitem(sys.modules, "src", src_pkg)
    monkeypatch.setitem(sys.modules, "src.llm_core", mod)


class _Session:
    owner = None
    session_id = "conversation-7"

    def get_context_messages(self):
        return [{"role": "user", "content": "Reminder, I am allergic to shellfish."},
                {"role": "assistant", "content": "Noted."}]


class _Manager:
    """A complete double. `record_mention` is here so the real path runs."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.recorded = []
        self._n = 0

    def load_all(self):
        return list(self.rows)

    def load_all_for_update(self):
        return list(self.rows)

    def load(self, owner=None):
        return [r for r in self.rows if r.get("owner") == owner]

    def find_duplicates(self, text, subset):
        t = text.strip().lower()
        return [r for r in subset if r.get("text", "").strip().lower() == t]

    def add_entry(self, text, source="auto", category="fact", owner=None,
                  confidence=None, provenance=None, status=None):
        # `P13-01` / `P13-03` / `P13-05` widened the real constructor; the
        # double mirrors it rather than swallowing extra kwargs, so the day a
        # caller passes something this fake cannot represent, the fake says so.
        # It said so, on `status`, which is why this line moved.
        self._n += 1
        entry = {"id": f"new-{self._n}", "text": text, "owner": owner,
                 "source": source, "category": category,
                 "confidence": confidence, "provenance": provenance,
                 "status": status or "committed"}
        self.rows.append(entry)
        return entry

    def record_mention(self, memory_id, session_id=None):
        self.recorded.append((memory_id, session_id))
        return {"id": memory_id}


class _Vector:
    def __init__(self, match_id=None):
        self.healthy = match_id is not None
        self._match_id = match_id

    def find_similar(self, text, threshold=0.72):
        return self._match_id

    def add(self, mid, text):
        pass


def _run(monkeypatch, rows, fact, vector):
    mm = _Manager(rows)
    _stub_llm(monkeypatch, json.dumps([{"text": fact, "category": "fact"}]))
    asyncio.run(_extractor().extract_and_store(
        _Session(), mm, vector, endpoint_url="http://x", model="m"))
    return mm


_STORED = [{"id": "shellfish", "text": "User is allergic to shellfish.", "owner": None}]


def test_the_vector_dedup_path_records_the_restatement(monkeypatch):
    mm = _run(monkeypatch, _STORED, "User cannot eat shellfish.", _Vector("shellfish"))
    assert mm.recorded == [("shellfish", "conversation-7")], (
        "the vector path found the match and discarded the observation")


def test_the_exact_text_dedup_path_records_the_restatement(monkeypatch):
    mm = _run(monkeypatch, _STORED, "User is allergic to shellfish.", _Vector(None))
    assert mm.recorded == [("shellfish", "conversation-7")]


def test_the_fuzzy_dedup_path_records_the_restatement(monkeypatch):
    # Same fact, different wording, no vector store — the path an install
    # without a running ChromaDB actually takes.
    mm = _run(monkeypatch, _STORED, "The user is allergic to shellfish.", _Vector(None))
    assert mm.recorded == [("shellfish", "conversation-7")]


def test_a_genuinely_new_fact_is_stored_and_not_recorded_as_a_restatement(monkeypatch):
    # The negative control. Without it every test above passes on an extractor
    # that calls `record_mention` for everything it sees.
    mm = _run(monkeypatch, _STORED, "User drives a diesel van for site visits.", _Vector(None))
    assert mm.recorded == []
    assert any(r["text"] == "User drives a diesel van for site visits." for r in mm.rows)


def test_a_restatement_is_still_not_stored_twice(monkeypatch):
    # The dedup must keep doing its original job. Recording the mention is
    # additive; if it also started storing duplicates the row would have traded
    # one defect for a worse one.
    mm = _run(monkeypatch, _STORED, "User is allergic to shellfish.", _Vector(None))
    assert len(mm.rows) == 1


def test_the_lookup_and_the_predicate_are_one_implementation():
    # `_is_text_duplicate` kept its yes/no shape for callers outside this module
    # (`Law 1`) and must stay one line over the lookup rather than a second copy
    # of the comparison (`Law 14`).
    mod = _extractor()
    rows = [{"text": "User is allergic to shellfish."}]
    assert mod._text_duplicate_of("The user is allergic to shellfish.", rows) is rows[0]
    assert mod._is_text_duplicate("The user is allergic to shellfish.", rows) is True
    assert mod._text_duplicate_of("Completely different.", rows) is None
    assert mod._is_text_duplicate("Completely different.", rows) is False


@pytest.mark.parametrize("entry", [None, {}, {"id": ""}, "not-a-dict", 7])
def test_a_malformed_match_never_reaches_the_counter(entry):
    # The dedup paths hand over whatever they matched. A vector store returning
    # a stale id, or a row that lost its id in a migration, must not become a
    # mention against `None` — which would either raise or, worse, silently
    # credit nothing.
    mod = _extractor()
    calls = []

    class _Recorder:
        def record_mention(self, memory_id, session_id=None):
            calls.append(memory_id)

    mod._note_restatement(_Recorder(), entry, _Session(), "some fact")
    assert calls == []


def test_a_well_formed_match_does_reach_the_counter():
    # The positive control. Without it the guard test above passes on a
    # `_note_restatement` that never calls anything at all.
    mod = _extractor()
    calls = []

    class _Recorder:
        def record_mention(self, memory_id, session_id=None):
            calls.append((memory_id, session_id))

    mod._note_restatement(_Recorder(), {"id": "m1"}, _Session(), "some fact")
    assert calls == [("m1", "conversation-7")]


def test_a_counter_failure_never_costs_the_user_their_facts(monkeypatch):
    # The guard, and why it is broad. A store that cannot be written is a bad
    # day; an extraction batch lost because a *counter* raised is a worse one.
    class _Broken(_Manager):
        def record_mention(self, memory_id, session_id=None):
            raise RuntimeError("disk full")

    mm = _Broken(_STORED)
    _stub_llm(monkeypatch, json.dumps([
        {"text": "User is allergic to shellfish.", "category": "fact"},
        {"text": "User drives a diesel van.", "category": "fact"}]))
    asyncio.run(_extractor().extract_and_store(
        _Session(), mm, _Vector(None), endpoint_url="http://x", model="m"))
    assert any(r["text"] == "User drives a diesel van." for r in mm.rows), (
        "a failing counter took the rest of the batch down with it")


def test_the_renderer_calls_the_builder_rather_than_counting_for_itself():
    """A wiring assertion, and deliberately not a behaviour test.

    `memoryCountPills` is executed by the tests above; the three lines that turn
    its output into spans are inside a DOM builder and cannot be run without a
    DOM. Mutation testing found exactly that gap — a mutant that iterated an
    empty list instead of calling the builder survived every test of the builder
    — which is the ingredient-not-the-recipe family again.

    So this checks the wire, in the same spirit as `B61`'s rule that no
    identifier may name an engine that did not run: it cannot prove the spans
    look right, only that the one function that knows what they say is the one
    being asked. Comments are stripped, because the prose above the call site
    names the very thing being matched (`Law 20`, and my own trap twice now).
    """
    js = _MEMJS.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith("//"))
    calls = re.findall(r"memoryCountPills\(([^)]*)\)", code)
    assert calls.count("memory") >= 1, "the renderer stopped asking for the pills"
    # And nothing else may count them. A second site reading `uses` or
    # `mention_sessions` into a span is how the Brain grows a third number.
    body = code[code.index("for (const pill of memoryCountPills"):]
    assert "mention_sessions" not in body.split("function ")[0]
