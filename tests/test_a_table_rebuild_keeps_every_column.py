# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1481` — relaxing `scheduled_tasks`' NOT NULLs keeps every column it has.

`_migrate_add_task_automation_columns` rebuilt the table when `prompt`,
`schedule` or `scheduled_time` was still NOT NULL — from a column list written
before most of today's columns, so on a database old enough to need it every
column beyond that list was dropped with its data. And it renamed the old table
first, which in today's SQLite rewrites other tables' foreign keys to follow it
to the name about to be dropped. `_rebuild_relaxing_not_null` edits the three
constraints in the table's own CREATE statement and rebuilds in SQLite's order.

Every case builds the OLD table by hand (a legacy schema is a historical fact).
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, text

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402

_OLD = """
CREATE TABLE scheduled_tasks (
    id VARCHAR NOT NULL,
    owner VARCHAR,
    name VARCHAR NOT NULL,
    prompt TEXT NOT NULL,
    schedule VARCHAR NOT NULL,
    scheduled_time VARCHAR NOT NULL,
    crew_member_id VARCHAR,
    max_steps INTEGER,
    else_task_id VARCHAR REFERENCES scheduled_tasks(id) ON DELETE SET NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""


def _db(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute(_OLD)
    c.execute("CREATE INDEX ix_scheduled_tasks_owner ON scheduled_tasks (owner)")
    c.execute("CREATE TABLE task_runs (id VARCHAR PRIMARY KEY, "
              "task_id VARCHAR REFERENCES scheduled_tasks(id) ON DELETE CASCADE)")
    c.execute("INSERT INTO scheduled_tasks VALUES ('t1','ada','Nightly','p','daily','02:00',"
              "'crew-9',12,NULL,'2026-01-01')")
    c.execute("INSERT INTO task_runs VALUES ('r1','t1')")
    c.commit()
    c.close()
    return path


def test_every_column_and_row_survives_and_the_three_are_nullable(tmp_path):
    path = _db(tmp_path)
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert cdb._rebuild_relaxing_not_null(conn, "scheduled_tasks",
                                              ("prompt", "schedule", "scheduled_time")) is True
        conn.commit()
    c = sqlite3.connect(path)
    info = {r[1]: r for r in c.execute("PRAGMA table_info(scheduled_tasks)")}
    assert list(info) == ["id", "owner", "name", "prompt", "schedule", "scheduled_time",
                          "crew_member_id", "max_steps", "else_task_id", "created_at"]
    assert [info[k][3] for k in ("prompt", "schedule", "scheduled_time")] == [0, 0, 0]
    assert info["name"][3] == 1 and info["created_at"][3] == 1, "only the three are relaxed"
    assert c.execute("SELECT crew_member_id, max_steps FROM scheduled_tasks").fetchone() == ("crew-9", 12)
    # the index came back, and another table's foreign key still names this one
    idx = [r[1] for r in c.execute("PRAGMA index_list(scheduled_tasks)")]
    assert "ix_scheduled_tasks_owner" in idx
    fk = c.execute("SELECT sql FROM sqlite_master WHERE name='task_runs'").fetchone()[0]
    assert "REFERENCES scheduled_tasks" in fk and "_old_" not in fk and "_rebuild_" not in fk
    c.execute("INSERT INTO scheduled_tasks (id, name, created_at) VALUES ('t2', 'no prompt', '2026-01-02')")
    c.close()


def test_a_constraint_it_cannot_find_changes_nothing(tmp_path):
    path = tmp_path / "odd.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE scheduled_tasks (id VARCHAR PRIMARY KEY, prompt TEXT "
              "CONSTRAINT p_nn NOT NULL)")
    c.commit()
    c.close()
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert cdb._rebuild_relaxing_not_null(conn, "scheduled_tasks", ("prompt",)) is False
        assert conn.execute(text("SELECT count(*) FROM sqlite_master WHERE name='scheduled_tasks'")).scalar() == 1
