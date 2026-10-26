# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1032` — a turn the teacher answered counts the student's tokens too.

A reply two runs made is saved as one (`merge_runs`, `B939`): the teacher's
figures as the reply's own, the student's under `earlier_runs`.
`accumulate_token_usage` read the reply's figures only, so a takeover added the
teacher's input and output tokens to the chat's totals and wrote one
`llm_round` event for it — and never the student's, whose run had been paid
for all the same. Now each run is counted: its tokens in the totals and one
event of its own.

Driven: the real `accumulate_token_usage` and the real `record_llm_round` over
a real SQLite file, given the record the route saves for a takeover — built
by the real `merge_runs` from a student's record and a teacher's.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Event
from core.database import Session as DbSession
from src.agent_stops import merge_runs

STUDENT = {"model": "small", "input_tokens": 100, "output_tokens": 10, "round_texts": ["I can't find it."]}
TEACHER = {"model": "big", "input_tokens": 50, "output_tokens": 5, "round_texts": ["It is under /data."]}


@pytest.fixture()
def chat(monkeypatch, tmp_path):
    import routes.chat_helpers as chat_helpers
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(chat_helpers, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="small",
                     total_input_tokens=0, total_output_tokens=0))
    db.commit()
    db.close()

    def read():
        d = factory()
        try:
            row = d.query(DbSession).filter(DbSession.id == "c1").first()
            events = [(e.model, e.input_tokens, e.output_tokens, e.outcome)
                      for e in d.query(Event).filter(Event.kind == "llm_round").order_by(Event.id).all()]
            return (row.total_input_tokens, row.total_output_tokens), events
        finally:
            d.close()

    return chat_helpers.accumulate_token_usage, read


def test_a_takeover_adds_the_students_tokens_and_the_teachers(chat):
    accumulate, read = chat
    record = merge_runs(STUDENT, TEACHER)
    assert record["input_tokens"] == 50 and record["earlier_runs"][0]["input_tokens"] == 100
    accumulate("c1", record)
    totals, events = read()
    assert totals == (150, 15)
    assert events == [("small", 100, 10, "ok"), ("big", 50, 5, "ok")]


def test_a_teacher_that_failed_is_an_error_and_its_student_is_not(chat):
    accumulate, read = chat
    accumulate("c1", merge_runs(STUDENT, dict(TEACHER, failed=True)), outcome="error")
    totals, events = read()
    assert totals == (150, 15)
    assert [e[3] for e in events] == ["ok", "error"]


def test_a_reply_of_one_run_is_counted_as_it_was(chat):
    accumulate, read = chat
    accumulate("c1", dict(STUDENT))
    assert read() == ((100, 10), [("small", 100, 10, "ok")])
