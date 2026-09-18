# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-25` — `task_runs.steps` has to exist in a database that predates it.

The column was declared on `TaskRun` and never migrated. On a fresh dev box
`create_all` builds the table with it and everything passes; on every install
that was created before the declaration landed, the column is simply absent and
the first write raises `OperationalError: table task_runs has no column named
steps`. That asymmetry is the whole defect, so the test builds the *old* table
by hand — `Law 20`: a migration test run against a schema that already has the
column is a test of `create_all`, not of the migration.
"""

import json
import sqlite3

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402


# The `task_runs` shape as it was BEFORE either of the two columns that were
# added to it by migration. `model` is here because the migration that adds it
# runs immediately before the one under test in `init_db`, and a legacy
# database has neither; running both is the only way to know the new one did
# not break the old one.
_LEGACY_TASK_RUNS = """
CREATE TABLE task_runs (
    id          VARCHAR NOT NULL,
    task_id     VARCHAR NOT NULL,
    started_at  DATETIME NOT NULL,
    finished_at DATETIME,
    status      VARCHAR,
    result      TEXT,
    error       TEXT,
    tokens_used INTEGER,
    PRIMARY KEY (id)
)
"""


def _legacy_db(tmp_path):
    """A database created before `steps` (and before `model`) existed."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_TASK_RUNS)
        conn.execute(
            "INSERT INTO task_runs (id, task_id, started_at, status, result) "
            "VALUES ('run-old', 'task-old', '2026-01-01 00:00:00', 'success', 'done')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(task_runs)")]
    finally:
        conn.close()


def test_a_database_without_the_column_rejects_the_write_the_row_describes(tmp_path):
    """The defect, stated as a test: this is what an upgraded install does."""
    path = _legacy_db(tmp_path)
    assert "steps" not in _columns(path)

    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO task_runs (id, task_id, started_at, steps) "
                "VALUES ('run-new', 'task-old', '2026-01-02 00:00:00', '[]')"
            )
    finally:
        conn.close()


def test_the_migration_adds_steps_to_a_database_that_never_had_it(monkeypatch, tmp_path):
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_task_run_model_column()
    cdb._migrate_add_task_run_steps_column()

    cols = _columns(path)
    assert "steps" in cols, f"migration did not add the column; table is {cols}"
    assert "model" in cols, "the migration beside it stopped working"

    # The row that was already there survives, unset rather than lost.
    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT steps FROM task_runs WHERE id='run-old'").fetchone()[0] is None

        steps = [{"round": 1, "tool": "web_search", "status": "ok"}]
        conn.execute(
            "INSERT INTO task_runs (id, task_id, started_at, steps) "
            "VALUES ('run-new', 'task-old', '2026-01-02 00:00:00', ?)",
            (json.dumps(steps),),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT steps FROM task_runs WHERE id='run-new'").fetchone()[0]
        assert json.loads(stored) == steps
    finally:
        conn.close()


def test_the_migration_is_idempotent(monkeypatch, tmp_path):
    """`init_db` runs every migration on every boot."""
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_task_run_steps_column()
    cdb._migrate_add_task_run_steps_column()

    assert _columns(path).count("steps") == 1


def test_init_db_runs_the_migration():
    """A migration nobody calls is the same defect wearing a fix (`Law 13`).

    The file is parsed and `init_db`'s own body walked, rather than grepped:
    the name also appears in this test and in a comment, and `Law 20` is about
    exactly that difference. Parsed from the path rather than through
    `inspect.getsource`, which resolves a function by the line number recorded
    at import and reads the file from disk (`Law 19`).
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(cdb.__file__).read_text(encoding="utf-8"))
    init_db = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "init_db"
    )
    called = {
        node.func.id
        for node in ast.walk(init_db)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_migrate_add_task_run_steps_column" in called
    # The one it is modelled on still runs too.
    assert "_migrate_add_task_run_model_column" in called
