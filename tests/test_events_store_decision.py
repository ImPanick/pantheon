# SPDX-License-Identifier: AGPL-3.0-or-later
"""The store decision, and the two things that make it honest (`P14-06`).

`D-2026-09-18-01` decides that the events table stays in SQLite. A decision that
says *fine until it is not* is worth nothing on its own — somebody has to be
able to tell which side of "not" they are on, and the prune that keeps the table
inside its window has to not be worse than the growth it prevents.

Measured on the tree before this row:

  * nothing anywhere could say how many rows `events` held. `usage_summary` and
    `usage_over_time` both answer questions about `llm_round` inside a window;
    neither counts the table, and the operator-facing health surface had no row
    for the store at all.
  * `prune_events` was one `DELETE ... WHERE ts < cutoff`, run inline at the
    tail of `record_llm_round` — on the thread that has just finished somebody's
    chat turn. Over 550,000 expired rows that statement took **7.3 seconds**.

These drive the real functions against a real (file-backed) database.
"""
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, Event, utcnow_naive
from src import events as ev
from src import self_checks

SessionLocal = None


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """A private, file-backed database per test.

    The suite runs on `sqlite:///:memory:`, where every new connection is a NEW
    EMPTY database — `P14-01`'s tests learned that the expensive way. A file
    also means `store_status()` has a real file to stat, which is half of what
    it reports.
    """
    global SessionLocal
    engine = create_engine(f"sqlite:///{tmp_path}/store.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(core_db, "engine", engine)
    SessionLocal = maker
    ev._last_prune = 0.0
    ev._prune_unfinished = False
    yield
    SessionLocal = None
    ev._prune_unfinished = False
    engine.dispose()


def _add(n, *, age_days=0.0, kind="llm_round"):
    db = SessionLocal()
    ts = utcnow_naive() - timedelta(days=age_days)
    db.bulk_save_objects([
        Event(ts=ts, kind=kind, outcome="ok", input_tokens=10, output_tokens=5)
        for _ in range(n)
    ])
    db.commit()
    db.close()


def _count():
    db = SessionLocal()
    try:
        return db.query(Event).count()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The reading the decision needs
# ---------------------------------------------------------------------------

def test_store_status_counts_the_table_and_dates_it():
    _add(5, age_days=10)
    _add(7)
    st = ev.store_status()
    assert st["rows"] == 12
    assert st["oldest"] and st["newest"] and st["oldest"] < st["newest"]
    # The size an operator can picture, from the measured per-row cost.
    assert st["est_bytes"] == 12 * ev.MEASURED_BYTES_PER_ROW
    assert st["pressure"] == "ok"


def test_store_status_reports_the_database_file_it_actually_uses():
    """`db_bytes` is the whole file and is labelled as such.

    The events table shares a database with thirty other tables, so reporting
    the file size as the events table's own size would be a number that reads
    like evidence and is not. It is reported beside the estimate, never as it.
    """
    _add(3)
    st = ev.store_status()
    assert st["db_bytes"] and st["db_bytes"] > 0
    assert st["db_bytes"] != st["est_bytes"]


@pytest.mark.parametrize("rows,expected", [(4, "ok"), (10, "watch"), (20, "over")])
def test_pressure_is_measured_against_the_thresholds_the_decision_named(
        rows, expected, monkeypatch):
    monkeypatch.setattr(ev, "STORE_WATCH_ROWS", 10)
    monkeypatch.setattr(ev, "STORE_OVER_ROWS", 20)
    _add(rows)
    assert ev.store_status()["pressure"] == expected


def test_store_status_never_raises_when_the_table_is_gone(monkeypatch):
    """A health surface that can take the page down is one nobody leaves on."""
    Base.metadata.tables["events"].drop(bind=core_db.engine)
    st = ev.store_status()
    assert st["error"]
    assert st["rows"] == 0


# ---------------------------------------------------------------------------
# The prune, which is the thing that keeps the decision true
# ---------------------------------------------------------------------------

def test_a_prune_stops_on_its_budget_and_says_so():
    """The defect: one DELETE over a real backlog, on a person's turn.

    Before this row `prune_events` deleted every expired row in one statement
    and had no way to stop. 550,000 rows measured at 7.3 seconds.
    """
    _add(500, age_days=200)
    removed = ev.prune_events(days=90, budget_seconds=1e-9, batch_rows=100)
    assert removed == 100                    # one batch, then the budget
    assert ev.unfinished_prune() is True
    assert _count() == 400


def test_an_unfinished_prune_is_continued_by_the_next_write_not_a_day_later():
    """The rearm. Without it a budget turns a backlog into a permanent one.

    `_maybe_prune` is gated to once per 24 hours per process, so a prune that
    stops early and then respects that gate would drain 5,000 rows a day and
    never catch up on the backlog it was written for.
    """
    _add(300, age_days=200)
    ev.prune_events(days=90, budget_seconds=1e-9, batch_rows=100)
    assert ev.unfinished_prune() is True

    # A write now. The interval gate would normally refuse — it was armed by
    # the prune above, seconds ago.
    ev._last_prune = time.monotonic()
    assert ev.record_event("tool_call", name="bash") is True
    assert _count() < 201                    # the unexpired write, plus progress


def test_a_prune_that_finishes_inside_its_budget_reports_finished():
    _add(40, age_days=200)
    _add(3)
    removed = ev.prune_events(days=90)
    assert removed == 40
    assert ev.unfinished_prune() is False
    assert _count() == 3


def test_budget_zero_means_no_budget_not_no_work():
    """The escape hatch a migration or a test needs, and it is the honest one."""
    _add(250, age_days=200)
    assert ev.prune_events(days=90, budget_seconds=0, batch_rows=100) == 250
    assert _count() == 0


def test_retention_zero_still_keeps_everything():
    """`Law 1`. Batching must not quietly acquire a floor.

    `0` is a choice an operator makes — keep everything — and a prune that
    "helpfully" trimmed anyway would be the setting silently ignoring the value
    it was given.
    """
    _add(20, age_days=900)
    assert ev.prune_events(days=0) == 0
    assert _count() == 20


# ---------------------------------------------------------------------------
# The operator hears about it
# ---------------------------------------------------------------------------

def test_the_self_check_reports_the_store_and_names_the_window():
    _add(6)
    row = self_checks.events_store_size()
    assert row["status"] == self_checks.OK
    assert "6 events" in row["summary"]
    assert "90 days" in row["summary"] or "for ever" in row["summary"]


def test_keeping_everything_is_said_out_loud(monkeypatch):
    """`events_retention_days = 0` had no reader anywhere before this."""
    monkeypatch.setattr(ev, "_retention_days", lambda: 0)
    _add(4)
    assert "for ever" in self_checks.events_store_size()["summary"]


def test_a_store_over_the_threshold_is_attention_with_something_to_do(monkeypatch):
    """`P16-15`'s rule: a check that can go red must carry an action."""
    monkeypatch.setattr(ev, "STORE_WATCH_ROWS", 3)
    monkeypatch.setattr(ev, "STORE_OVER_ROWS", 5)
    _add(4)
    row = self_checks.events_store_size()
    assert row["status"] == self_checks.ATTENTION
    assert row["action"] and "events_retention_days" in row["action"]
    assert "D-2026-09-18-01" in row["action"]

    _add(4)
    worse = self_checks.events_store_size()
    assert worse["status"] == self_checks.STUCK
    assert worse["action"]


def test_the_store_check_is_registered_so_somebody_actually_sees_it():
    """A check nobody runs is the `H` rows again."""
    assert self_checks.events_store_size in self_checks.CHECKS
    names = {c["name"] for c in self_checks.run_self_checks()["checks"]}
    assert "events_store_size" in names
