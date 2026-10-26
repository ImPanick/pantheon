# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1018` — a waiting document plan survives a restart.

`src/document_folders.py` held waiting plans in a process dict (`_plans`), so a
restart forgot every one. For the agent's 30-minute plans `P21-02` judged that
acceptable; the scheduled Documents Tidy's proposal (`B1006`) waits seven days
for a person who may not open Pantheon for most of them. Measured on
`03f50081` with this file's drive: a tidy proposed in one process, answered
from another — what a restart is — got `404 "That tidy is no longer waiting"`,
deleted nothing (fail-closed), and nothing offered it again until the tidy next
ran (after five more new documents).

Now a waiting plan is a row in `document_plans`, read by the same
`pending_plan` / `waiting_review(s)`.

Driven (`Law 20`) across a real process boundary: the tidy is proposed by the
real `document_actions.propose_document_tidy` in a separate Python process
over a SQLite file; this process — which has never held the plan — lists it
through the real `GET /api/document-folders/plans` and answers it through the
real `POST …/answer` (the person's route, `test_the_documents_tidy_asks_first`'s
harness), and the documents are deleted. A lapsed plan is still refused.
"""
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.test_the_documents_tidy_asks_first import (  # noqa: F401  (fixtures by name)
    F, answer, cdb, routed, waiting,
)

ROOT = Path(__file__).resolve().parents[1]

# The first process: Bob's library, and the scheduled tidy's proposal made in it.
_BEFORE = r"""
import json, sys, uuid
from datetime import datetime
import core.database as cdb
cdb.Base.metadata.create_all(cdb.engine)
LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)
db = cdb.SessionLocal()
ids = {}
for key, title, content in [("junk", "test", "something"), ("empty", "Untitled", ""),
                            ("keep", "Budget 2026", "real numbers")]:
    doc_id = "d-" + uuid.uuid4().hex[:10]
    ids[key] = doc_id
    db.add(cdb.Document(id=doc_id, title=title, current_content=content, owner="bob",
                        is_active=True, created_at=LONG_AGO, updated_at=LONG_AGO))
db.commit()
db.close()
from src import document_actions
plan, judged, kept = document_actions.propose_document_tidy("bob")
print(json.dumps({"plan_id": plan.plan_id, "count": plan.review["count"], "ids": ids}))
"""


@pytest.fixture
def restarted(tmp_path, monkeypatch):
    """A plan proposed in another process, and this process pointed at its
    database — with nothing of that process's memory."""
    db_file = tmp_path / "app.db"
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_file}",
               PANTHEON_DATA_DIR=str(tmp_path / "data"))
    proc = subprocess.run([sys.executable, "-c", _BEFORE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    before = json.loads(proc.stdout.strip().splitlines()[-1])
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(cdb, "SessionLocal", sessionmaker(bind=engine, autoflush=False,
                                                          autocommit=False))
    return before


def _alive(doc_id):
    db = cdb.SessionLocal()
    try:
        return bool(db.query(cdb.Document).filter(cdb.Document.id == doc_id).one().is_active)
    finally:
        db.close()


def test_review_still_finds_the_tidy_after_a_restart_and_applying_it_works(restarted, routed):
    """`Fix:` held in a table, read by the same `pending_plan` /
    `waiting_review(s)`."""
    plan_id = restarted["plan_id"]
    assert restarted["count"] == 2
    listed = waiting("bob")
    assert [p["plan_id"] for p in listed] == [plan_id], "the restart forgot the waiting tidy"
    assert listed[0]["count"] == 2
    res = answer(plan_id, F.PLAN_APPROVE_LABEL)
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "applied"
    ids = restarted["ids"]
    assert not _alive(ids["junk"]) and not _alive(ids["empty"]) and _alive(ids["keep"])
    assert waiting("bob") == [], "applied, and no longer waiting"
    assert answer(plan_id, F.PLAN_APPROVE_LABEL).status_code == 404


def test_a_plan_that_lapsed_is_still_refused(restarted, routed, monkeypatch):
    start = F.utcnow_naive()
    monkeypatch.setattr(F, "utcnow_naive", lambda: start + timedelta(days=8))
    assert waiting("bob") == []
    res = answer(restarted["plan_id"], F.PLAN_APPROVE_LABEL)
    assert res.status_code == 404
    assert all(_alive(i) for i in restarted["ids"].values()), "a lapsed plan deleted something"


def test_keep_after_a_restart_deletes_nothing_and_ends_it(restarted, routed):
    res = answer(restarted["plan_id"], F.PLAN_DECLINE_LABEL)
    assert res.status_code == 200, res.text
    assert all(_alive(i) for i in restarted["ids"].values())
    assert waiting("bob") == []
