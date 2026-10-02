# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` / `P22-07` — the three workflow tables arrive on an install that
already has tasks and runs, and nothing it had moves (`Law 20`, `Law 1`).

The design adds three tables and ALTERs none (`Workflow`, `WorkflowVersion`,
`TaskRunNode`), so `init_db`'s `Base.metadata.create_all` is the whole
migration. That is a claim about a database that existed BEFORE the models,
which a test that builds its database with `create_all` cannot check. So the
old database is built by hand, with `sqlite3`: `scheduled_tasks` and
`task_runs` exactly as the pre-`P22` models declare them, rows in both, and no
workflow table. Then the real `create_all` runs against that file, and the
answers are read back from SQLite itself (`PRAGMA table_info`,
`PRAGMA foreign_key_list`) — not from the models that were just asserted.
"""

import ast
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateIndex, CreateTable

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

OLD_TABLES = ("scheduled_tasks", "task_runs")
NEW_TABLES = {
    "workflows": {"id", "owner", "name", "task_id", "graph", "version",
                  "source_chain", "created_at", "updated_at"},
    "workflow_versions": {"id", "workflow_id", "version", "name", "graph",
                          "fingerprint", "source", "created_at"},
    "task_run_nodes": {"id", "run_id", "node_id", "kind", "label", "seq", "status",
                       "attempt", "dry", "port", "reached_by", "depth",
                       "workflow_version", "started_at", "finished_at", "input",
                       "output", "error", "steps", "model"},
}


def _old_install(path: Path) -> None:
    """The two tables a pre-`P22` install has, with rows, by hand."""
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    con = sqlite3.connect(path)
    try:
        for name in OLD_TABLES:
            table = cdb.Base.metadata.tables[name]
            con.execute(str(CreateTable(table).compile(dialect=sqlite_dialect.dialect())))
            for index in table.indexes:
                con.execute(str(CreateIndex(index).compile(dialect=sqlite_dialect.dialect())))
        con.execute(
            "INSERT INTO scheduled_tasks (id, owner, name, prompt, task_type, "
            "trigger_type, status, created_at, updated_at) VALUES "
            "('t1', 'alice', 'Morning digest', 'Summarise my inbox', 'llm', "
            "'schedule', 'active', '2026-09-01 08:00:00', '2026-09-01 08:00:00')")
        con.execute(
            "INSERT INTO task_runs (id, task_id, started_at, finished_at, status, "
            "result) VALUES ('r1', 't1', '2026-09-30 08:00:00', "
            "'2026-09-30 08:01:00', 'success', 'Three new messages.')")
        con.commit()
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == set(OLD_TABLES), tables
    finally:
        con.close()


def _dump(con, table):
    return con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


@pytest.fixture()
def upgraded(tmp_path):
    path = tmp_path / "old.db"
    _old_install(path)
    con = sqlite3.connect(path)
    before = {t: _dump(con, t) for t in OLD_TABLES}
    schema_before = {t: con.execute(f"PRAGMA table_info({t})").fetchall() for t in OLD_TABLES}
    con.close()
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)       # what `init_db` does
    engine.dispose()
    return path, before, schema_before


def test_create_all_adds_the_three_tables_with_their_columns(upgraded):
    path, _before, _schema = upgraded
    con = sqlite3.connect(path)
    try:
        for table, expected in NEW_TABLES.items():
            got = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            assert got == expected, (table, got ^ expected)
    finally:
        con.close()


def test_the_foreign_keys_are_the_ones_the_design_needs(upgraded):
    """A step record goes with its run (CASCADE — the admin wipe and
    `ensure_defaults` bulk-delete runs); a version goes with its workflow
    (CASCADE); a deleted trigger leaves the document (SET NULL, `Law 1`)."""
    path, _before, _schema = upgraded
    con = sqlite3.connect(path)
    try:
        def fks(table):
            # (id, seq, table, from, to, on_update, on_delete, match)
            return {(r[3], r[2], r[4], r[6]) for r in con.execute(
                f"PRAGMA foreign_key_list({table})")}

        assert fks("task_run_nodes") == {("run_id", "task_runs", "id", "CASCADE")}
        assert fks("workflow_versions") == {("workflow_id", "workflows", "id", "CASCADE")}
        assert fks("workflows") == {("task_id", "scheduled_tasks", "id", "SET NULL")}
        unique = [r for r in con.execute("PRAGMA index_list(workflow_versions)") if r[2]]
        cols = [[c[2] for c in con.execute(f"PRAGMA index_info({r[1]})")] for r in unique]
        assert ["workflow_id", "version"] in cols, cols
    finally:
        con.close()


def test_the_old_tables_and_their_rows_are_untouched(upgraded):
    path, before, schema_before = upgraded
    con = sqlite3.connect(path)
    try:
        for table in OLD_TABLES:
            assert _dump(con, table) == before[table], table
            assert con.execute(f"PRAGMA table_info({table})").fetchall() == schema_before[table]
    finally:
        con.close()


def test_deleting_a_run_takes_its_step_records_and_nothing_else(upgraded):
    """With `foreign_keys=ON` (`core.database.set_sqlite_pragma` turns it on for
    every connection the app makes), a raw `DELETE FROM task_runs` — the shape
    of the admin wipe's bulk delete — removes that run's step records."""
    path, _before, _schema = upgraded
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("INSERT INTO task_runs (id, task_id, started_at, status) "
                    "VALUES ('r2', 't1', '2026-10-01 08:00:00', 'success')")
        for i, run in enumerate(("r1", "r1", "r2"), start=1):
            con.execute("INSERT INTO task_run_nodes (id, run_id, node_id, seq, status, "
                        "attempt, dry) VALUES (?, ?, ?, ?, 'success', 1, 0)",
                        (f"n{i}", run, f"step{i}", i))
        con.execute("INSERT INTO workflows (id, owner, name, task_id, graph, version, "
                    "created_at, updated_at) VALUES ('w1', 'alice', 'Morning digest', "
                    "'t1', '{}', 1, '2026-10-01 08:00:00', '2026-10-01 08:00:00')")
        con.execute("INSERT INTO workflow_versions (id, workflow_id, version, name, graph, "
                    "fingerprint, source, created_at) VALUES ('v1', 'w1', 1, 'Morning digest', "
                    "'{}', 'x', 'user', '2026-10-01 08:00:00')")
        con.commit()
        con.execute("DELETE FROM task_runs WHERE id = 'r1'")
        con.commit()
        left = [r[0] for r in con.execute("SELECT run_id FROM task_run_nodes ORDER BY id")]
        assert left == ["r2"]
        # The trigger deleted by a path that knows nothing of workflows: the
        # document and its versions stay, unlinked.
        con.execute("DELETE FROM task_runs")
        con.execute("DELETE FROM scheduled_tasks WHERE id = 't1'")
        con.commit()
        assert con.execute("SELECT task_id FROM workflows").fetchall() == [(None,)]
        assert con.execute("SELECT COUNT(*) FROM workflow_versions").fetchone() == (1,)
        assert con.execute("SELECT COUNT(*) FROM task_run_nodes").fetchone() == (0,)
    finally:
        con.close()


def test_init_db_still_creates_tables_before_any_column_migration():
    """`Law 20`, option 2: resolve `init_db` in the AST and read its calls in
    order — `Base.metadata.create_all` must come before every
    `_migrate_add_*` call, which is what makes `create_all` the whole migration
    for three new tables (nothing ALTERs them, and nothing needs to)."""
    tree = ast.parse((ROOT / "core" / "database.py").read_text(encoding="utf-8"))
    init = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_db")
    calls = []
    for stmt in init.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "create_all":
                    calls.append(("create_all", node.lineno))
                elif isinstance(func, ast.Name) and func.id.startswith("_migrate_add_"):
                    calls.append((func.id, node.lineno))
    names = [c[0] for c in sorted(calls, key=lambda c: c[1])]
    assert "create_all" in names
    assert names.index("create_all") == 0, names[:3]
    assert len(names) > 10, "the migrations moved out of init_db; re-read it"


def test_the_models_name_the_tables_this_test_built():
    assert cdb.Workflow.__tablename__ == "workflows"
    assert cdb.WorkflowVersion.__tablename__ == "workflow_versions"
    assert cdb.TaskRunNode.__tablename__ == "task_run_nodes"
    # No ALTER of an existing table: the old two have no workflow column.
    assert "workflow_id" not in cdb.ScheduledTask.__table__.columns
    assert "workflow_id" not in cdb.TaskRun.__table__.columns
