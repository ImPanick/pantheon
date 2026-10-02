# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-07` — a workflow step's record: capped through `settings.role_limit`,
pruned on a finite window, read back in one shape (`src/workflow_runs.py`).

`B806` says `TaskRun` cannot hold what each step was handed and made; this is
the record that can, and its two limits are the product's, not the module's:
the cap resolves role profile → instance setting → built-in default
(`P12-01`), and the window is `workflow_node_records_days`. Driven on a real
SQLite file with the real resolver and a real role-limit provider installed
(`Law 20`).
"""

import json
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.settings as settings  # noqa: E402
from core.database import ScheduledTask, TaskRun, TaskRunNode  # noqa: E402
from src import workflow_runs as wr  # noqa: E402
from src.event_bus import build_task_handoff, build_trigger  # noqa: E402

C2_NODE_RECORD = {"id", "node_id", "kind", "label", "seq", "status", "attempt", "dry",
                  "port", "workflow_version", "started_at", "finished_at", "input",
                  "input_summary", "output", "error", "steps", "model"}


@pytest.fixture()
def db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'records.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    session = factory()
    session.add(ScheduledTask(id="wf", owner="alice", name="Morning", task_type="workflow"))
    session.add(ScheduledTask(id="wf2", owner="alice", name="Evening", task_type="workflow"))
    for run_id, task_id in (("r1", "wf"), ("r2", "wf"), ("r3", "wf2")):
        session.add(TaskRun(id=run_id, task_id=task_id, status="success"))
    session.commit()
    yield session
    session.close()
    settings.clear_role_limit_provider()


def _start(db, run_id="r1", node_id="n1", seq=1, handed=None, owner="alice", dry=False):
    return wr.record_node_start(db, run_id=run_id, node={"id": node_id, "kind": "llm",
                                                         "label": "Summarise"},
                                seq=seq, input_envelope=handed, workflow_version=2,
                                owner=owner, dry=dry)


def test_a_record_is_capped_by_the_owner_s_role_and_stays_valid_json(db):
    settings.set_role_limit_provider(
        lambda key, owner: 1000 if key == wr.NODE_RECORD_MAX_CHARS_SETTING and owner == "alice" else None)
    mail = build_trigger("event", "email_received", {"account": "work", "folder": "INBOX",
                                                     "message_key": "x" * 1900})
    big = build_task_handoff(task_name="Summarise", task_id="wf", run_id="r1",
                             status="success", result="y" * 1900)
    alice = _start(db, handed=big)
    bob = _start(db, node_id="n2", seq=2, handed=mail, owner="bob")
    wr.record_node_end(db, alice, status="success", text="z" * 5000, owner="alice")
    stored_in = json.loads(alice.input)
    stored_out = json.loads(alice.output)
    assert stored_in["truncated"] is True and stored_in["chars"] > 1000
    assert len(alice.input) <= 1000 and len(alice.output) <= 1000, "what is STORED fits the cap"
    assert stored_in["summary"].startswith("Continued from Summarise"), "a cut input still says what it was"
    assert stored_out["truncated"] is True and stored_out["chars"] > 5000
    # Bob's role says nothing: the built-in default (16000) keeps his whole.
    assert json.loads(bob.input)["data"]["message_key"] == "x" * 1900
    assert wr.node_record_max_chars("alice") == 1000
    assert wr.node_record_max_chars("bob") == wr.NODE_RECORD_MAX_CHARS_DEFAULT


def test_a_role_cannot_take_the_cap_below_its_floor(db):
    settings.set_role_limit_provider(lambda key, owner: 5)
    assert wr.node_record_max_chars("alice") == wr.NODE_RECORD_MAX_CHARS_RANGE[0]


def test_a_record_reads_back_in_exactly_the_shape_the_routes_serve(db):
    handed = build_trigger("event", "email_received", {"account": "work", "message_key": "42"})
    rec = _start(db, handed=handed)
    wr.record_node_end(db, rec, status="error", text="IMAP refused", error="IMAP refused",
                       steps=[{"kind": "progress", "detail": "Connecting"}], model="m",
                       port="error", owner="alice")
    out = wr.node_record_to_dict(rec)
    assert set(out) == C2_NODE_RECORD
    assert (out["status"], out["port"], out["error"], out["model"]) == (
        "error", "error", "IMAP refused", "m")
    assert out["input"]["data"] == {"account": "work", "message_key": "42"}
    assert out["input_summary"] == "Triggered by email_received — account=work, message_key=42"
    assert out["output"] == {"text": "IMAP refused", "data": None}
    assert out["steps"] == [{"kind": "progress", "detail": "Connecting"}]
    assert out["started_at"].endswith("Z") and out["finished_at"].endswith("Z")
    assert out["workflow_version"] == 2 and out["dry"] is False and out["attempt"] == 1
    nothing = wr.node_record_to_dict(_start(db, node_id="n2", seq=2))
    assert nothing["input"] is None and nothing["input_summary"].startswith("Nothing")


def test_the_last_record_of_a_step_is_its_newest_real_one_in_this_workflow(db):
    old = _start(db, run_id="r1")
    old.started_at = datetime(2026, 9, 1)
    new = _start(db, run_id="r2")
    new.started_at = datetime(2026, 9, 2)
    plan = _start(db, run_id="r2", dry=True)
    plan.started_at = datetime(2026, 9, 3)
    other = _start(db, run_id="r3")
    other.started_at = datetime(2026, 9, 4)
    db.commit()
    assert wr.last_node_record(db, "wf", "n1").id == new.id
    assert wr.last_node_record(db, "wf2", "n1").id == other.id
    assert wr.last_node_record(db, "wf", "n9") is None


def test_records_past_the_window_are_pruned_and_runs_are_not(db):
    now = datetime(2026, 10, 1, 12, 0)
    keep = _start(db, node_id="keep")
    keep.finished_at = now - timedelta(days=29)
    gone = _start(db, node_id="gone", seq=2)
    gone.finished_at = now - timedelta(days=31)
    running = _start(db, node_id="running", seq=3)
    running.started_at = now - timedelta(days=90)
    db.commit()
    assert wr.prune_node_records(db, days=30, now=now) == 1
    left = {r.node_id for r in db.query(TaskRunNode).all()}
    assert left == {"keep", "running"}
    assert db.query(TaskRun).count() == 3, "the runs' own rows are never touched"
    assert "30 days" in wr.records_cleared_sentence(30)
    assert wr.NODE_RECORDS_DAYS_SETTING in wr.records_cleared_sentence(30)


def test_the_prune_at_the_end_of_a_run_is_at_most_hourly(db, monkeypatch):
    monkeypatch.setattr(wr, "_last_prune", None)
    stale = _start(db, node_id="a")
    stale.finished_at = datetime.utcnow() - timedelta(days=400)
    db.commit()
    assert wr.maybe_prune_node_records(db) == 1
    again = _start(db, node_id="b", seq=2)
    again.finished_at = datetime.utcnow() - timedelta(days=400)
    db.commit()
    assert wr.maybe_prune_node_records(db) == 0, "within the hour: not again"
    monkeypatch.setattr(wr, "_last_prune", wr._last_prune - wr._PRUNE_INTERVAL_SECONDS - 1)
    assert wr.maybe_prune_node_records(db) == 1


def test_the_two_settings_are_the_module_s_numbers_in_every_table():
    """`Law 7`. The default and bounds live in `src/workflow_runs.py`; the
    settings tables import them, so the stored number, the clamp and the
    resolver cannot disagree."""
    assert settings.DEFAULT_SETTINGS[wr.NODE_RECORD_MAX_CHARS_SETTING] == wr.NODE_RECORD_MAX_CHARS_DEFAULT
    assert settings.DEFAULT_SETTINGS[wr.NODE_RECORDS_DAYS_SETTING] == wr.NODE_RECORDS_DAYS_DEFAULT
    assert settings.role_limit_ranges()[wr.NODE_RECORD_MAX_CHARS_SETTING] == wr.NODE_RECORD_MAX_CHARS_RANGE
    ranges = settings.int_setting_ranges()
    assert ranges[wr.NODE_RECORD_MAX_CHARS_SETTING] == wr.NODE_RECORD_MAX_CHARS_RANGE
    assert ranges[wr.NODE_RECORDS_DAYS_SETTING] == wr.NODE_RECORDS_DAYS_RANGE
    assert settings.clamp_int_setting(wr.NODE_RECORDS_DAYS_SETTING, 0) == 1
