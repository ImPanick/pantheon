# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-04` — decay and archive, so the store stops growing noisier.

The row carries a dated premise correction — *reinforcement already ships* —
and re-measuring it is what found the work. It ships, and it shipped **half**:
`increment_uses` knew a memory had just been reached for and recorded only how
many times, never when. So the store could not answer the one question this row
asks, *"has anything retrieved this lately"*, about any record in it. That is
`P13-15`'s shape exactly — the moment the evidence arrived was the moment it
was discarded — and `P13-10`'s, one layer up.

Three properties, and each is a group below:

* a memory nobody reaches for **fades toward archive**, on dates the record
  already keeps, with a countdown a person can read before it happens;
* **nothing is ever silently dropped** — archived means on the record, out of
  every prompt, in the events table, and restorable through the act `P13-05`
  already built rather than a second one;
* **the store that predates this row survives it**, which is the obligation
  `P8-25` earned and `P13-12` discharged, in the shape this store takes: a
  hand-written pre-row `memory.json`, not an `ALTER TABLE`.

Nothing here asserts on source text (`Law 20`): every test calls the thing.
"""

import asyncio
import json
import time

import pytest

from src import memory_edges, memory_retrieval
from src.memory import (
    ARCHIVE_AFTER_DAYS,
    ARCHIVE_DUE,
    ARCHIVE_FADES,
    ARCHIVE_HELD,
    MemoryManager,
    archive_forecast,
    due_for_archive,
    last_evidence,
)
import services.memory.memory_extractor as mx


DAY = 86400
NOW = 1780000000.0


@pytest.fixture
def store(tmp_path):
    return MemoryManager(str(tmp_path))


def mem(mid, text="User drives a van", **extra):
    row = {"id": mid, "text": text, "category": "fact", "timestamp": int(NOW),
           "uses": 0, "status": memory_edges.STATUS_COMMITTED}
    row.update(extra)
    return row


def quiet(mid, days, **extra):
    """A committed memory whose most recent date is `days` ago."""
    return mem(mid, timestamp=int(NOW - days * DAY), **extra)


# ── the half of reinforcement that was missing ────────────────────────────────

def test_a_use_records_when_it_was_used(store):
    """The premise correction, measured.

    `uses` has always been incremented on injection. The date never was, so
    "a memory never retrieved" was a question the store held no field for.
    """
    entry = store.add_entry("User drives a van")
    store.save([entry])
    before = int(time.time())
    store.increment_uses([entry["id"]])
    row = store.load_all()[0]
    assert row["uses"] == 1
    assert row["last_used"] >= before


def test_a_new_memory_has_not_been_used_yet(store):
    # `None`, not "now": stamping creation as a use would make every new memory
    # look like it had already earned its place.
    assert store.add_entry("User drives a van")["last_used"] is None


def test_a_use_moves_the_date_and_a_mention_does_not(store):
    """`uses` and `mentions` stay apart, and so do their dates (`P13-15`)."""
    entry = store.add_entry("User drives a van")
    store.save([entry])
    store.record_mention(entry["id"], session_id="s1")
    assert store.load_all()[0].get("last_used") is None

    store.increment_uses([entry["id"]])
    after = store.load_all()[0]
    assert after["last_used"] is not None
    assert after["mentions"] == 1, "a use must not have moved the mention count"


# ── what counts as evidence ───────────────────────────────────────────────────

def test_the_newest_of_the_four_dates_wins():
    assert last_evidence(mem("a", timestamp=10, last_used=30,
                             last_mentioned=20, committed_at=25)) == 30
    assert last_evidence(mem("a", timestamp=10, last_mentioned=99)) == 99
    assert last_evidence(mem("a", timestamp=10, committed_at=50)) == 50


def test_a_record_with_no_usable_dates_is_not_read_as_ancient():
    # "Undated" is not "old", and guessing which is the one mistake this row
    # cannot make: the wrong guess archives somebody's memories.
    assert last_evidence({"id": "a", "text": "x"}) == 0
    assert last_evidence(None) == 0
    assert archive_forecast({"id": "a", "text": "x"}, NOW)["verdict"] == ARCHIVE_HELD


def test_junk_in_a_date_field_is_skipped_not_crashed_on():
    # memory.json is a file a person can edit.
    assert last_evidence(mem("a", timestamp=42, last_used="yesterday")) == 42


# ── the countdown ─────────────────────────────────────────────────────────────

def test_a_fresh_memory_has_its_full_window():
    out = archive_forecast(quiet("a", 0), NOW)
    assert out["verdict"] == ARCHIVE_FADES
    assert out["days"] == ARCHIVE_AFTER_DAYS


def test_the_countdown_falls_as_the_memory_goes_quiet():
    early = archive_forecast(quiet("a", 10), NOW)["days"]
    late = archive_forecast(quiet("a", 100), NOW)["days"]
    assert early > late > 0


def test_a_memory_past_the_window_is_due():
    """`due` is its own verdict, not `fades` with a zero on it.

    A mutation proved the two-field version carried a branch that could never
    change an answer — `days == 0` already decided it, because a held memory
    reports `None`. The state that means *archive this now* says so in the
    field that means it (`Law 10`), and the surface gets a sentence out of it:
    "due to fade" and "fades in 12 days" are different things to tell somebody.
    """
    out = archive_forecast(quiet("a", ARCHIVE_AFTER_DAYS + 1), NOW)
    assert out["verdict"] == ARCHIVE_DUE
    assert out["days"] == 0
    assert archive_forecast(quiet("a", 1), NOW)["verdict"] == ARCHIVE_FADES


def test_half_a_day_of_window_left_is_not_due():
    """The rounding direction is a correctness property, not cosmetics.

    `int()` on a window with half a day left reads `0`, and `0` is what the
    sweep archives on — a memory must not be archived by a rounding rule that
    was written to make a sentence read nicely.
    """
    out = archive_forecast(quiet("a", ARCHIVE_AFTER_DAYS - 0.5), NOW)
    assert out["days"] == 1
    assert due_for_archive([quiet("a", ARCHIVE_AFTER_DAYS - 0.5)], NOW) == []


def test_a_recent_use_resets_the_clock():
    old = quiet("a", ARCHIVE_AFTER_DAYS + 50)
    assert due_for_archive([old], NOW) == ["a"]
    old["last_used"] = int(NOW - DAY)
    assert due_for_archive([old], NOW) == []


def test_a_recent_restatement_resets_the_clock_too():
    old = quiet("a", ARCHIVE_AFTER_DAYS + 50)
    old["last_mentioned"] = int(NOW - DAY)
    assert due_for_archive([old], NOW) == []


# ── what is held, and why ─────────────────────────────────────────────────────

def test_a_pinned_memory_never_fades():
    """A thing a person typed beats a thing the system inferred.

    `setting_is_explicit` — `H06`, `H08`, `D-2026-09-08-02`, `D-2026-09-09-01`,
    `P13-05` — on its sixth application in this codebase.
    """
    row = quiet("a", ARCHIVE_AFTER_DAYS * 10, pinned=True)
    out = archive_forecast(row, NOW)
    assert out["verdict"] == ARCHIVE_HELD
    assert out["days"] is None
    assert due_for_archive([row], NOW) == []


def test_a_proposal_never_fades():
    # It is already invisible to every prompt, and archiving it would hide it
    # from the review queue `B710` still owes a surface.
    row = quiet("a", ARCHIVE_AFTER_DAYS * 10,
                status=memory_edges.STATUS_PROPOSED)
    assert archive_forecast(row, NOW)["verdict"] == ARCHIVE_HELD
    assert due_for_archive([row], NOW) == []


def test_archiving_is_idempotent_rather_than_a_repeating_event():
    row = quiet("a", ARCHIVE_AFTER_DAYS * 10,
                status=memory_edges.STATUS_ARCHIVED)
    assert archive_forecast(row, NOW)["verdict"] == ARCHIVE_HELD
    assert due_for_archive([row], NOW) == []


def test_a_superseded_memory_is_left_to_the_edge_that_already_hides_it():
    """Two unrelated reasons for one silence is a record nobody can read."""
    survivor = mem("new", "User drives a Transit",
                   edges=[memory_edges.new_edge(memory_edges.EDGE_SUPERSEDES, "old")])
    old = quiet("old", ARCHIVE_AFTER_DAYS * 10)
    assert due_for_archive([survivor, old], NOW) == []
    assert archive_forecast(old, NOW, superseded=True)["verdict"] == ARCHIVE_HELD


def test_a_memory_used_before_the_date_was_recorded_is_held(store):
    """The migration guard, and the reason it exists.

    `uses > 0` with no `last_used` is every memory in every store that existed
    before this row. Falling back to `timestamp` there would archive the
    *most-used* memories on an old install the first time anybody pressed
    Audit — which is the loudest possible version of the silent drop this row
    is about.
    """
    legacy = quiet("a", ARCHIVE_AFTER_DAYS * 3, uses=40)
    out = archive_forecast(legacy, NOW)
    assert out["verdict"] == ARCHIVE_HELD
    assert due_for_archive([legacy], NOW) == []

    # And it resolves itself the first time the memory is injected.
    store.save([legacy])
    store.increment_uses(["a"])
    assert store.load_all()[0]["last_used"] is not None
    assert due_for_archive(store.load_all(), NOW + ARCHIVE_AFTER_DAYS * DAY * 2) == ["a"]


def test_a_never_used_memory_is_not_protected_by_the_guard():
    # The guard is about an unknown date, not about age. `uses == 0` is a
    # recorded fact, and it is the row's own phrase: "never retrieved".
    assert due_for_archive([quiet("a", ARCHIVE_AFTER_DAYS + 1, uses=0)], NOW) == ["a"]


# ── archiving keeps everything ────────────────────────────────────────────────

def test_archiving_changes_the_status_and_nothing_else(store):
    edge = memory_edges.new_edge(memory_edges.EDGE_CO_OCCURS, "b")
    store.save([mem("a", "User drives a van", confidence=0.8, uses=3,
                    mentions=2, edges=[edge],
                    provenance={"producer": "x", "message_index": 1,
                                "quote": "I drive a van"})])
    store.archive(["a"], reason="quiet")
    row = store.load_all()[0]
    assert row["status"] == memory_edges.STATUS_ARCHIVED
    assert row["text"] == "User drives a van"
    assert row["confidence"] == 0.8
    assert row["uses"] == 3 and row["mentions"] == 2
    assert row["edges"] == [edge]
    assert row["provenance"]["quote"] == "I drive a van"
    assert row["archived_at"] and row["archived_reason"] == "quiet"


def test_an_archived_memory_stops_reaching_any_prompt(store):
    store.save([mem("a", "User drives a van")])
    assert memory_retrieval.retrieve("van", store.load_all())
    store.archive(["a"])
    assert memory_retrieval.retrieve("van", store.load_all()) == []
    assert memory_edges.live(store.load_all()) == []


def test_an_archived_memory_is_still_in_the_store_and_still_readable(store):
    store.save([mem("a", "User drives a van")])
    store.archive(["a"])
    rows = store.load_all()
    assert len(rows) == 1 and rows[0]["text"] == "User drives a van"


def test_archiving_twice_does_not_re_stamp_the_date(store):
    store.save([mem("a")])
    first = store.archive(["a"])
    assert [r["id"] for r in first] == ["a"]
    stamped = store.load_all()[0]["archived_at"]
    assert store.archive(["a"]) == []
    assert store.load_all()[0]["archived_at"] == stamped


def test_archive_will_not_touch_a_proposal(store):
    store.save([mem("a", status=memory_edges.STATUS_PROPOSED)])
    assert store.archive(["a"]) == []
    assert store.load_all()[0]["status"] == memory_edges.STATUS_PROPOSED


def test_archive_does_not_rewrite_the_store_when_it_cannot_read_it(store, monkeypatch):
    def _boom():
        from src.memory import MemoryStoreUnreadable
        raise MemoryStoreUnreadable("disk went away")

    store.save([mem("a")])
    raw = open(store.memory_file, encoding="utf-8").read()
    monkeypatch.setattr(store, "load_all_for_update", _boom)
    assert store.archive(["a"]) == []
    assert open(store.memory_file, encoding="utf-8").read() == raw


# ── restoring is the act that already exists ──────────────────────────────────

def test_restoring_is_commit_rather_than_a_second_mechanism(store):
    """`Law 14`, and it is why no restore endpoint was written.

    An archived memory is not committed, so `P13-05`'s gate — text check,
    duplicate check, event, vector add — *is* the act of binding it again.
    """
    store.save([mem("a", "User drives a van")])
    store.archive(["a"])
    out = mx.commit_memory(store, "a", by="felix")
    assert out["verdict"] == "committed"
    row = store.load_all()[0]
    assert row["status"] == memory_edges.STATUS_COMMITTED
    assert memory_retrieval.retrieve("van", store.load_all())


def test_restoring_refuses_when_something_live_already_says_it(store):
    # The gate is the whole point of reusing it: bringing back a memory another
    # entry has since replaced would undo a consolidation.
    store.save([mem("old", "User drives a van"),
                mem("new", "User drives a van")])
    store.archive(["old"])
    out = mx.commit_memory(store, "old")
    assert out["verdict"] == "refused"
    assert out["duplicate_of"] == "new"
    assert store.load_all()[0]["status"] == memory_edges.STATUS_ARCHIVED


# ── the sweep runs inside the pass that already exists ────────────────────────

def _audit(monkeypatch, manager, reply="[]", vector=None, owner=None):
    async def _fake_llm(*args, **kwargs):
        return reply

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _fake_llm)
    return asyncio.run(mx.audit_memories(manager, vector, "http://x", "m", owner=owner))


def test_the_audit_fades_what_has_gone_quiet_and_reports_it(store, monkeypatch):
    store.save([quiet("old", ARCHIVE_AFTER_DAYS + 10),
                mem("fresh", "User has a cat")])
    result = _audit(monkeypatch, store,
                    json.dumps([{"id": "fresh", "text": "User has a cat",
                                 "category": "fact"}]))
    assert result["archived"] == 1
    by_id = {r["id"]: r for r in store.load_all()}
    assert by_id["old"]["status"] == memory_edges.STATUS_ARCHIVED
    assert by_id["fresh"]["status"] == memory_edges.STATUS_COMMITTED


def test_a_faded_memory_is_not_counted_as_removed(store, monkeypatch):
    """`archived` is its own number and never folded into `removed`.

    `before - after` has meant "stopped surfacing" since long before this row,
    and a caller that reports "12 removed" when most of them are one click from
    being back is telling a person something frightening and false — which is
    the argument `P13-09` already made for `superseded`.
    """
    store.save([quiet("old", ARCHIVE_AFTER_DAYS + 10),
                mem("fresh", "User has a cat")])
    result = _audit(monkeypatch, store,
                    json.dumps([{"id": "fresh", "text": "User has a cat",
                                 "category": "fact"}]))
    assert result["before"] == 1, "the faded memory was gone before the tidy counted"
    assert result["before"] - result["after"] == 0
    assert result["archived"] == 1


def test_an_already_tidy_store_can_still_fade(store, monkeypatch):
    """The short-circuit is exactly the path a quiet store takes.

    The tidy fingerprint skips the LLM when nothing has changed — and a store
    where nothing has changed for six months is precisely the one this row
    fires on. A sweep behind that check would never run on the stores that need
    it most.
    """
    store.save([mem("keep", "User has a cat")])
    first = _audit(monkeypatch, store,
                   json.dumps([{"id": "keep", "text": "User has a cat",
                                "category": "fact"}]))
    assert not first.get("already_tidy")

    rows = store.load_all()
    rows[0]["timestamp"] = int(time.time() - (ARCHIVE_AFTER_DAYS + 10) * DAY)
    store.save(rows)

    def _no_llm(*args, **kwargs):
        raise AssertionError("the LLM must not be called on a quiet store")

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _no_llm)
    second = asyncio.run(mx.audit_memories(store, None, "http://x", "m"))
    assert second["archived"] == 1
    assert store.load_all()[0]["status"] == memory_edges.STATUS_ARCHIVED


def test_the_sweep_takes_the_memory_out_of_the_vector_index(store, monkeypatch):
    """`P13-09`'s hole, third sighting, and the short-circuit is the twist.

    A memory left in the index is still returned by `find_similar`, which is
    the extractor's first dedupe gate and does not go through the scorer — so
    the person's next restatement would be credited to a copy nothing can
    retrieve. The audit rebuilds from `live_memories` at the end, but the
    `already_tidy` return never reaches that line.
    """
    class Vector:
        healthy = True

        def __init__(self):
            self.removed = []
            self.rebuilt = None

        def remove(self, mid):
            self.removed.append(mid)

        def rebuild(self, rows):
            self.rebuilt = [r["id"] for r in rows]

    vector = Vector()
    store.save([mem("keep", "User has a cat")])
    _audit(monkeypatch, store,
           json.dumps([{"id": "keep", "text": "User has a cat", "category": "fact"}]),
           vector=vector)
    rows = store.load_all()
    rows[0]["timestamp"] = int(time.time() - (ARCHIVE_AFTER_DAYS + 10) * DAY)
    store.save(rows)
    vector.rebuilt = None

    def _no_llm(*args, **kwargs):
        raise AssertionError("the LLM must not be called on a quiet store")

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", _no_llm)
    asyncio.run(mx.audit_memories(store, vector, "http://x", "m"))
    assert vector.removed == ["keep"]
    assert vector.rebuilt is None, "the short-circuit returns before any rebuild"


def test_the_fade_is_recorded_where_the_commitment_is(store, monkeypatch):
    """*"Nothing is ever silently dropped"* — a change nobody can find later is
    silent however reversible it is. `P14-01` already owns this table."""
    seen = []

    import src.events as events
    monkeypatch.setattr(events, "record_event",
                        lambda kind, **kw: seen.append((kind, kw)))
    store.save([quiet("old", ARCHIVE_AFTER_DAYS + 10)])
    _audit(monkeypatch, store, "[]")
    archives = [row for row in seen if row[1].get("name") == "archive"]
    assert len(archives) == 1
    assert archives[0][0] == "memory"
    assert archives[0][1]["detail"]["memory_id"] == "old"


def test_a_failing_decay_sweep_does_not_take_the_tidy_with_it(store, monkeypatch):
    # The consolidation half has shipped since long before this row.
    store.save([mem("keep", "User has a cat")])
    monkeypatch.setattr(mx, "due_for_archive",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = _audit(monkeypatch, store,
                    json.dumps([{"id": "keep", "text": "User has a cat",
                                 "category": "fact"}]))
    assert "error" not in result
    assert result["archived"] == 0


# ── the store that predates this row ──────────────────────────────────────────

def test_a_store_written_before_this_row_still_works(tmp_path):
    """The migration proof, for the store the memories are actually in.

    `P13-03` established and `P13-05` re-measured that memory lives in
    `data/memory.json` and the SQL `memories` table has no reader that returns
    content — re-measured again for this row and it is still three non-test
    readers, none of which reads a memory to answer anything. So the obligation
    `P8-25` earned is discharged here rather than by an `ALTER TABLE`: a raw
    record with none of this row's fields loads, reads, ranks and fades.
    """
    raw = [{"id": "legacy", "text": "User drives a van", "category": "fact",
            "source": "user", "timestamp": int(NOW - 10 * DAY)}]
    (tmp_path / "memory.json").write_text(json.dumps(raw), encoding="utf-8")

    store = MemoryManager(str(tmp_path))
    rows = store.load_all()
    assert len(rows) == 1
    assert rows[0]["status"] == memory_edges.STATUS_COMMITTED
    assert "last_used" not in raw[0], "the fixture must not carry the new field"
    assert memory_retrieval.retrieve("van", rows), "it still answers questions"

    forecast = archive_forecast(rows[0], NOW)
    assert forecast["verdict"] == ARCHIVE_FADES
    assert forecast["days"] == ARCHIVE_AFTER_DAYS - 10

    store.increment_uses(["legacy"])
    assert store.load_all()[0]["last_used"] is not None


def test_an_old_store_full_of_used_memories_is_not_emptied_by_the_first_audit(
        tmp_path, monkeypatch):
    """The failure this row could most easily have shipped."""
    raw = [{"id": f"m{i}", "text": f"Fact number {i}", "category": "fact",
            "source": "auto", "uses": 5,
            "timestamp": int(time.time() - 400 * DAY)}
           for i in range(5)]
    (tmp_path / "memory.json").write_text(json.dumps(raw), encoding="utf-8")
    store = MemoryManager(str(tmp_path))

    result = _audit(monkeypatch, store, "[]")
    assert result["archived"] == 0
    assert all(r["status"] == memory_edges.STATUS_COMMITTED
               for r in store.load_all())


# ── the number reaches the surface ────────────────────────────────────────────

def _memory_list_route(manager, monkeypatch, caller=None):
    from unittest.mock import MagicMock

    import routes.memory_routes as mr

    monkeypatch.setattr(mr, "get_current_user", lambda request: caller,
                        raising=False)
    router = mr.setup_memory_routes(manager, MagicMock())
    for route in router.routes:
        if route.path == "/api/memory" and "GET" in route.methods:
            return route.endpoint
    raise AssertionError("no memory list route")


def test_the_list_says_when_each_memory_fades(store, monkeypatch):
    """Fading is visible *before* it happens, which is the whole difference
    between a decay policy and a silent drop.

    Dated off the wall clock rather than the fixture's `NOW`, because the route
    does not take a clock: the forecast a person reads is the one computed when
    they open the page.
    """
    real = time.time()
    store.save([mem("a", timestamp=int(real - 30 * DAY)),
                mem("b", timestamp=int(real - 5 * DAY), pinned=True)])
    rows = _memory_list_route(store, monkeypatch)(request=None)["memory"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["a"]["archive"]["verdict"] == ARCHIVE_FADES
    assert by_id["a"]["archive"]["days"] == ARCHIVE_AFTER_DAYS - 30
    assert by_id["b"]["archive"]["verdict"] == ARCHIVE_HELD
    assert by_id["b"]["archive"]["days"] is None
    assert by_id["b"]["archive"]["reason"]


def test_the_forecast_is_computed_and_never_stored(store, monkeypatch):
    # A stored copy of a derived value is a copy that is wrong tomorrow.
    store.save([mem("a", timestamp=int(time.time() - 30 * DAY))])
    _memory_list_route(store, monkeypatch)(request=None)
    on_disk = json.loads(open(store.memory_file, encoding="utf-8").read())
    assert "archive" not in on_disk[0]


def test_the_list_marks_a_superseded_memory_as_held_rather_than_fading(
        store, monkeypatch):
    store.save([mem("new", "User drives a Transit",
                    edges=[memory_edges.new_edge(memory_edges.EDGE_SUPERSEDES, "old")]),
                mem("old", timestamp=int(time.time() - (ARCHIVE_AFTER_DAYS + 10) * DAY))])
    rows = _memory_list_route(store, monkeypatch)(request=None)["memory"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["old"]["archive"]["verdict"] == ARCHIVE_HELD
