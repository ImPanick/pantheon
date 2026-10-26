# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B685` — the auth audit trail has a retention window of its own.

Measured on the tree this row started from: `prune_events` filtered on
`Event.ts < cutoff` alone, so `P11-08`'s audit rows (`kind="auth"`) expired on
the same `events_retention_days` as every model round, and a year of *who was
made an admin* cost a year of `llm_round` telemetry. Now
`auth_events_retention_days` sets the audit trail's window (unset follows the
general one, `0` keeps it) and the one batched, budgeted pass deletes each kind
on its own.

Driven against a real file-backed events table (`tests/test_events_store_decision.py`'s
fixture) and the real settings store.
"""
import importlib
import json
import time

import pytest

from src import events as ev
from tests.test_events_store_decision import _add, _count, _db  # noqa: F401


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    import src.constants
    import src.settings as settings
    importlib.reload(src.constants)
    importlib.reload(settings)

    def write(values):
        (tmp_path / "data" / "settings.json").write_text(json.dumps(values), encoding="utf-8")
        settings._invalidate_caches()

    yield write
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(settings)


def _kinds():
    from core.database import Event
    from tests import test_events_store_decision as store
    db = store.SessionLocal()
    try:
        return sorted(kind for (kind,) in db.query(Event.kind).all())
    finally:
        db.close()


def test_auth_rows_outlive_usage_rows_of_the_same_age_on_a_window_set_for_them(stored):
    stored({"events_retention_days": 30, "auth_events_retention_days": 365})
    _add(5, age_days=200, kind="llm_round")
    _add(3, age_days=200, kind=ev.AUTH_EVENT_KIND)

    assert ev.prune_events() == 5
    assert _kinds() == ["auth"] * 3


def test_past_its_own_window_an_auth_row_goes_too(stored):
    stored({"events_retention_days": 30, "auth_events_retention_days": 365})
    _add(2, age_days=400, kind=ev.AUTH_EVENT_KIND)
    _add(1, age_days=200, kind=ev.AUTH_EVENT_KIND)
    _add(4, age_days=10, kind="llm_round")

    assert ev.prune_events() == 2
    assert _kinds() == ["auth"] + ["llm_round"] * 4


def test_unset_it_follows_the_general_window_as_before(stored):
    stored({"events_retention_days": 90})
    _add(5, age_days=200, kind="llm_round")
    _add(3, age_days=200, kind=ev.AUTH_EVENT_KIND)
    _add(2, age_days=10, kind=ev.AUTH_EVENT_KIND)

    assert ev.prune_events() == 8
    assert _kinds() == ["auth"] * 2


def test_zero_keeps_the_audit_trail_while_usage_is_pruned(stored):
    stored({"events_retention_days": 30, "auth_events_retention_days": 0})
    _add(5, age_days=900, kind="llm_round")
    _add(3, age_days=900, kind=ev.AUTH_EVENT_KIND)

    assert ev.prune_events() == 5
    assert _kinds() == ["auth"] * 3


def test_keeping_everything_else_still_prunes_an_audit_window_someone_set(stored):
    stored({"events_retention_days": 0, "auth_events_retention_days": 30})
    _add(5, age_days=900, kind="llm_round")
    _add(3, age_days=900, kind=ev.AUTH_EVENT_KIND)

    assert ev.prune_events() == 3
    assert _kinds() == ["llm_round"] * 5


def test_the_pruner_still_finishes_inside_its_budget(stored):
    """Both kinds in one batched pass, held to the same half-second budget."""
    stored({"events_retention_days": 30, "auth_events_retention_days": 365})
    _add(3000, age_days=200, kind="llm_round")
    _add(500, age_days=200, kind=ev.AUTH_EVENT_KIND)

    started = time.monotonic()
    removed = ev.prune_events(batch_rows=500)
    elapsed = time.monotonic() - started

    assert elapsed < ev._PRUNE_BUDGET_SECONDS + 0.5
    assert removed > 0
    if ev.unfinished_prune():
        ev.prune_events(budget_seconds=0)
    assert _kinds() == ["auth"] * 500
