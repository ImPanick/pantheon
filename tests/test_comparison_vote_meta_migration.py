# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-12` — `comparisons.vote_meta` has to exist in a database that predates it.

`Law 7`: `blind_mapping` held three different facts depending on which endpoint
wrote the row. Declared as the left/right mapping for a blind comparison, used
that way by `POST /api/compare/start` and `POST /api/compare/{id}/vote`,
repurposed by `POST /api/compare/record` to carry `{"models": [...]}` because
`model_a`/`model_b` cannot hold three, and extended by `H12` with `costs` and
`mode`. `_history_row` told the shapes apart by which keys were present.

Giving the vote payload its own column is only half the fix. The other half is
that the rows already in the table have to move with it, and that the column
has to exist on an install created before it was declared — `P8-25` is the row
where a column was declared and never migrated, which passes on a fresh dev box
and raises `OperationalError` on every upgraded one. So, per `Law 20`, every
test below builds the **old** table by hand.
"""

import json
import sqlite3

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402


# The `comparisons` shape as it was BEFORE `vote_meta`. Written out rather than
# derived from the model, because a legacy schema is a historical fact and
# deriving it from today's declaration would make this test agree with the
# code by construction.
_LEGACY_COMPARISONS = """
CREATE TABLE comparisons (
    id            VARCHAR NOT NULL,
    session_id    VARCHAR,
    owner         VARCHAR,
    prompt        TEXT NOT NULL,
    model_a       VARCHAR NOT NULL,
    model_b       VARCHAR NOT NULL,
    endpoint_a    VARCHAR NOT NULL,
    endpoint_b    VARCHAR NOT NULL,
    response_a    TEXT,
    response_b    TEXT,
    metrics_a     TEXT,
    metrics_b     TEXT,
    winner        VARCHAR,
    is_blind      BOOLEAN,
    blind_mapping TEXT,
    voted_at      DATETIME,
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""

# What `POST /api/compare/record` used to write into `blind_mapping`.
_VOTE_BLOB = json.dumps({"models": ["m1", "m2", "m3"],
                         "costs": [0.1, None, 0.3], "mode": "arena"})
# What `POST /api/compare/start` writes into the same column, and still does.
_MAPPING_BLOB = json.dumps({"left": "b", "right": "a"})
# A shape no writer in this tree has ever produced, and therefore one nobody
# can say the meaning of. A hand-edited database can hold it.
_AMBIGUOUS_BLOB = json.dumps({"left": "a", "right": "b", "models": ["m1", "m2"]})


def _insert(conn, comp_id, blind_mapping):
    conn.execute(
        "INSERT INTO comparisons (id, prompt, model_a, model_b, endpoint_a, "
        "endpoint_b, is_blind, blind_mapping, created_at, updated_at) "
        "VALUES (?, 'p', 'm1', 'm2', '', '', 1, ?, "
        "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
        (comp_id, blind_mapping),
    )


def _legacy_db(tmp_path):
    """A database created before `vote_meta` existed, holding both shapes."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_COMPARISONS)
        _insert(conn, "vote-row", _VOTE_BLOB)
        _insert(conn, "start-row", _MAPPING_BLOB)
        _insert(conn, "bare-row", None)
        _insert(conn, "corrupt-row", "not json at all")
        _insert(conn, "ambiguous-row", _AMBIGUOUS_BLOB)
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(comparisons)")]
    finally:
        conn.close()


def _cells(path, comp_id):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT blind_mapping, vote_meta FROM comparisons WHERE id = ?",
            (comp_id,)).fetchone()
    finally:
        conn.close()


def test_a_database_without_the_column_rejects_the_write_the_row_describes(tmp_path):
    """The defect, stated as a test: this is what an upgraded install does."""
    path = _legacy_db(tmp_path)
    assert "vote_meta" not in _columns(path)

    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO comparisons (id, prompt, model_a, model_b, "
                "endpoint_a, endpoint_b, vote_meta, created_at, updated_at) "
                "VALUES ('new', 'p', 'a', 'b', '', '', '{}', "
                "'2026-01-02 00:00:00', '2026-01-02 00:00:00')"
            )
    finally:
        conn.close()


def test_the_migration_adds_vote_meta_to_a_database_that_never_had_it(monkeypatch, tmp_path):
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_comparison_vote_meta_column()

    cols = _columns(path)
    assert "vote_meta" in cols, f"migration did not add the column; table is {cols}"

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO comparisons (id, prompt, model_a, model_b, endpoint_a, "
            "endpoint_b, vote_meta, created_at, updated_at) "
            "VALUES ('new', 'p', 'a', 'b', '', '', ?, "
            "'2026-01-02 00:00:00', '2026-01-02 00:00:00')",
            (json.dumps({"models": ["a", "b"]}),),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT vote_meta FROM comparisons WHERE id='new'").fetchone()[0]
        assert json.loads(stored) == {"models": ["a", "b"]}
    finally:
        conn.close()


def test_the_migration_moves_a_vote_payload_out_of_blind_mapping(monkeypatch, tmp_path):
    """The `Law 7` half. Adding a column beside a cell that still holds the
    same fact leaves two sources of truth, and the copy nobody updates is the
    one somebody reads."""
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_comparison_vote_meta_column()

    blind, meta = _cells(path, "vote-row")
    assert json.loads(meta) == json.loads(_VOTE_BLOB), "the payload was not carried across"
    assert blind is None, (
        "the payload was copied but not cleared — the column still holds two "
        "meanings, which is the defect this row is about")


def test_the_migration_leaves_a_real_blind_mapping_alone(monkeypatch, tmp_path):
    """The other writer's rows are not vote payloads and must not move.

    A `{"left": ...}` blob is what makes `POST /api/compare/{id}/vote` able to
    say which side was which. Moving or clearing it would break the reveal on
    every unvoted blind comparison in the table.
    """
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_comparison_vote_meta_column()

    blind, meta = _cells(path, "start-row")
    assert json.loads(blind) == {"left": "b", "right": "a"}
    assert meta is None

    # Neither does it invent one where there was nothing, or choke on junk.
    assert _cells(path, "bare-row") == (None, None)
    assert _cells(path, "corrupt-row") == ("not json at all", None)

    # And it does not guess at the shape nobody can read. A blob carrying both
    # a mapping and a model list was written by no code in this tree; moving it
    # would silently pick one of two readings, and clearing the cell would take
    # a working blind comparison's mapping with it.
    ambiguous_blind, ambiguous_meta = _cells(path, "ambiguous-row")
    assert json.loads(ambiguous_blind) == json.loads(_AMBIGUOUS_BLOB)
    assert ambiguous_meta is None


def test_the_migration_is_idempotent(monkeypatch, tmp_path):
    """`init_db` runs every migration on every boot."""
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_comparison_vote_meta_column()
    cdb._migrate_add_comparison_vote_meta_column()

    assert _columns(path).count("vote_meta") == 1
    blind, meta = _cells(path, "vote-row")
    assert blind is None and json.loads(meta) == json.loads(_VOTE_BLOB)


def test_init_db_runs_the_migration():
    """A migration nobody calls is the same defect wearing a fix (`Law 13`).

    The file is parsed and `init_db`'s own body walked rather than grepped: the
    name also appears in this test and in two comments, and `Law 20` is about
    exactly that difference. Parsed from the path rather than through
    `inspect.getsource`, which resolves a function by the line number recorded
    at import and then reads the file from disk (`Law 19`).
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
    assert "_migrate_add_comparison_vote_meta_column" in called
    # The one it is modelled on still runs too.
    assert "_migrate_add_supports_tools_column" in called


def test_the_model_declares_the_column_the_migration_adds():
    """Declaration and migration are two halves of one fact (`Law 7`).

    A migration that adds a column the model does not declare is invisible to
    every query; a model that declares a column no migration adds is `P8-25`.
    Read off the mapped table rather than the source text, so a declaration
    that exists but does not map cannot pass.
    """
    assert "vote_meta" in cdb.Comparison.__table__.columns


def test_the_vote_endpoint_no_longer_crashes_on_a_row_the_other_path_wrote():
    """What the two meanings actually cost, as a test. `P13-12`.

    `vote_comparison` indexes `mapping["left"]` and `mapping["right"]`
    unconditionally — the reveal block runs even for a tie — so a row whose
    `blind_mapping` holds `{"models": [...]}` was a `KeyError`, which is a 500
    rather than a 4xx. It is reachable because `RecordVoteRequest.winner` is a
    plain `str`: an empty one is valid, it is falsy, and it slips past the
    "Already voted" guard that otherwise hides the mismatch.
    """
    from routes.compare.compare_routes import _blind_mapping

    class _Row:
        id = "cmp-1"
        blind_mapping = _VOTE_BLOB

    mapping = _blind_mapping(_Row())
    assert mapping["left"] in ("a", "b") and mapping["right"] in ("a", "b")

    class _Real:
        id = "cmp-2"
        blind_mapping = _MAPPING_BLOB

    assert _blind_mapping(_Real()) == {"left": "b", "right": "a"}
