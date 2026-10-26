# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1480`, `B641` — a column is written and read, or it is not declared.

The 2026-10-25 database audit found columns that were written and never read,
or read and never written: `comparisons.metrics_a`/`metrics_b` (neither),
`task_runs.tokens_used` (served as null forever), `notes.ai_classification` and
`ai_content_hash` (filled by a classify route that does not exist),
`calendar_events.last_pinged` (its writer went with `B1470`),
`scheduled_tasks.email_results`, `signatures.svg` (accepted and saved as None),
three `crew_members` columns, and `email_urgency_alerts` keeping each urgent
email's subject, sender and the model's reason for a table whose only reader asks
which messages were already alerted about. An install that has these columns
keeps them; the models no longer declare them and nothing writes them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import core.database as db

ROOT = Path(__file__).resolve().parents[1]

GONE = [
    (db.Comparison, "metrics_a"), (db.Comparison, "metrics_b"),
    (db.TaskRun, "tokens_used"),
    (db.Note, "ai_classification"), (db.Note, "ai_content_hash"),
    (db.CalendarEvent, "last_pinged"),
    (db.ScheduledTask, "email_results"),
    (db.Signature, "svg"),
    (db.CrewMember, "user_name"), (db.CrewMember, "is_active"), (db.CrewMember, "sort_order"),
]


@pytest.mark.parametrize("model, column", GONE, ids=lambda v: getattr(v, "__name__", v))
def test_the_dead_column_is_not_declared(model, column):
    assert column not in model.__table__.columns


def test_the_apis_no_longer_promise_them():
    notes = (ROOT / "routes" / "note" / "note_routes.py").read_text(encoding="utf-8")
    tasks = (ROOT / "routes" / "task" / "task_routes.py").read_text(encoding="utf-8")
    sigs = (ROOT / "routes" / "signature_routes.py").read_text(encoding="utf-8")
    assert '"ai_classification"' not in notes and '"tokens_used"' not in tasks
    assert "svg:" not in sigs and "svg=" not in sigs


def test_an_urgent_email_leaves_only_that_it_was_alerted_about():
    pollers = (ROOT / "routes" / "email_pollers.py").read_text(encoding="utf-8")
    i = pollers.index("INSERT OR REPLACE INTO email_urgency_alerts")
    stmt = pollers[i:i + 200]
    assert "(message_id, owner, created_at)" in stmt
    for leaked in ("subject", "sender", "reason"):
        assert leaked not in stmt


def test_a_fresh_database_and_its_second_start_migrate_without_a_warning(tmp_path):
    """`B1480` stopped declaring `signatures.svg`, and the start-up migration
    that encrypts signatures still selected it — so every database made since
    logged *"Signature encryption migration skipped: no such column: svg"* on
    every start, and an old database's plaintext was the one thing it was for.
    A migration that names a column the model no longer declares is the same
    defect, so: a fresh database, started twice, says nothing at WARNING."""
    import os
    import subprocess
    import sys
    code = ("import logging, sys; logging.basicConfig(level=logging.WARNING, stream=sys.stdout); "
            "from core.database import init_db; init_db(); init_db()")
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PANTHEON_DATA_DIR"] = str(tmp_path)
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    noisy = [line for line in (done.stdout + done.stderr).splitlines()
             if "migration" in line.lower() and ("skipped" in line or "failed" in line)]
    assert noisy == [], noisy
