# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-39` — `mcp_servers.env` was the last plaintext secret column.

MEASURED ON THE TREE BEFORE THE CHANGE. `core/database.py:585` had
`env = Column(Text)`, and it was the only secret-bearing column in the schema
encrypted at no layer. Six were `EncryptedText` — `model_endpoints.api_key`
(`:533`), `provider_auth_sessions.access_token` / `.refresh_token` (`:571-572`),
`mcp_servers.oauth_tokens` (`:590`), `signatures.data_png` / `.svg`
(`:655/:658`) — and five more are `Column(String)` encrypted by hand at their
call sites: `email_accounts.imap_password` / `.smtp_password` /
`.oauth_access_token` / `.oauth_refresh_token`, and `webhooks.secret`. Eleven
encrypted; `env` was the twelfth and the only one in the clear.

That column holds whatever an MCP server reads out of its environment:
`GITHUB_TOKEN`, `BRAVE_API_KEY`, `GOOGLE_CLIENT_SECRET`, `SLACK_BOT_TOKEN`. A
stolen `app.db` therefore handed over every MCP credential while every
credential beside it held — and `pantheon-mcp show` already redacted these
values behind `--reveal`, so the product's own posture already said they were
secrets.

`src/secret_storage.py` and the `EncryptedText` decorator already exist and are
already the answer for the other nine (`Law 14`). Nothing here is a second
implementation; the column changes type and one startup migration rewrites the
rows that predate it.

**Storage only.** The decorator encrypts on bind and decrypts on result, so
every consumer still reads and writes a plain JSON string and no route body,
CLI output or connect call changes shape. These tests assert both halves:
ciphertext on disk, plaintext through the model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOKEN = "ghp_a-real-looking-token-0123456789"
ENV_JSON = json.dumps({"GITHUB_TOKEN": TOKEN, "LOG_LEVEL": "debug"})


@pytest.fixture
def keyed(tmp_path, monkeypatch):
    """A fresh Fernet key in a temp dir, so the test never touches `data/`."""
    from src import secret_storage

    monkeypatch.setattr(secret_storage, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(secret_storage, "_fernet", None)
    yield
    monkeypatch.setattr(secret_storage, "_fernet", None)


@pytest.fixture
def db(tmp_path, keyed):
    """A real on-disk SQLite file, because the claim is about the file."""
    from core.database import Base

    engine = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _raw_env(engine, server_id="abcd1234"):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT env FROM mcp_servers WHERE id = :i"), {"i": server_id}
        ).fetchone()
    return row[0] if row else None


def _add(Factory, **kw):
    from core.database import McpServer

    fields = dict(id="abcd1234", name="GitHub", transport="stdio", command="npx",
                  args='["-y", "@modelcontextprotocol/server-github"]', env=ENV_JSON,
                  is_enabled=True)
    fields.update(kw)
    session = Factory()
    try:
        session.add(McpServer(**fields))
        session.commit()
    finally:
        session.close()


def _get(Factory, server_id="abcd1234"):
    from core.database import McpServer

    session = Factory()
    try:
        return session.query(McpServer).filter(McpServer.id == server_id).first().env
    finally:
        session.close()


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_the_token_is_not_in_the_database_file(db, tmp_path):
    """The threat this addresses: a stolen backup / a leaked image layer."""
    engine, Factory = db
    _add(Factory)
    blob = (tmp_path / "app.db").read_bytes()
    assert TOKEN.encode() not in blob, "the MCP token is sitting in the file"
    assert b"GITHUB_TOKEN" not in blob, "even the key name leaks which secret it is"


def test_the_stored_value_is_a_fernet_envelope(db):
    engine, Factory = db
    _add(Factory)
    stored = _raw_env(engine)
    assert stored.startswith("enc:"), stored[:40]


def test_it_reads_back_as_the_same_json_string(db):
    """No wire or JSON shape change: every consumer does `json.loads(srv.env)`."""
    engine, Factory = db
    _add(Factory)
    assert _get(Factory) == ENV_JSON
    assert json.loads(_get(Factory))["GITHUB_TOKEN"] == TOKEN


def test_an_empty_env_is_still_an_empty_env(db):
    engine, Factory = db
    _add(Factory, env="{}")
    assert _get(Factory) == "{}"
    assert json.loads(_get(Factory)) == {}


def test_a_null_env_stays_null(db):
    """`nullable=True` and every consumer guards with `if srv.env`."""
    engine, Factory = db
    _add(Factory, env=None)
    assert _get(Factory) is None
    assert _raw_env(engine) is None


# ---------------------------------------------------------------------------
# Existing rows keep working — migrate, do not orphan
# ---------------------------------------------------------------------------


def test_a_legacy_plaintext_row_still_reads_correctly(db):
    """Before the migration runs at all. `decrypt()` passes an unprefixed
    value straight through, so an upgrade that has not restarted yet still
    starts its MCP servers."""
    engine, Factory = db
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO mcp_servers (id, name, transport, command, env, is_enabled, "
            "created_at, updated_at) VALUES ('abcd1234', 'GitHub', 'stdio', 'npx', :e, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"e": ENV_JSON})
        conn.commit()
    assert _raw_env(engine) == ENV_JSON      # plaintext, as written
    assert _get(Factory) == ENV_JSON         # and readable


def test_the_startup_migration_rewrites_it(db, monkeypatch):
    engine, Factory = db
    import core.database as cdb

    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO mcp_servers (id, name, transport, command, env, is_enabled, "
            "created_at, updated_at) VALUES ('abcd1234', 'GitHub', 'stdio', 'npx', :e, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"e": ENV_JSON})
        conn.execute(text(
            "INSERT INTO mcp_servers (id, name, transport, command, env, is_enabled, "
            "created_at, updated_at) VALUES ('noenv999', 'Nothing', 'stdio', 'npx', NULL, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        conn.commit()

    monkeypatch.setattr(cdb, "engine", engine)
    cdb._migrate_encrypt_mcp_env()

    assert _raw_env(engine).startswith("enc:")
    assert _get(Factory) == ENV_JSON, "migrated and then unreadable is worse than plaintext"
    assert _raw_env(engine, "noenv999") is None


def test_the_migration_is_idempotent(db, monkeypatch):
    """It runs on every startup, and it must not encrypt the ciphertext."""
    engine, Factory = db
    import core.database as cdb

    _add(Factory)
    monkeypatch.setattr(cdb, "engine", engine)
    first = _raw_env(engine)
    cdb._migrate_encrypt_mcp_env()
    cdb._migrate_encrypt_mcp_env()
    assert _raw_env(engine) == first
    assert _get(Factory) == ENV_JSON


def test_the_migration_is_registered_at_startup(monkeypatch):
    """A migration nothing calls is a migration that never runs."""
    import core.database as cdb

    ran = []
    for name in [n for n in dir(cdb) if n.startswith("_migrate_")]:
        monkeypatch.setattr(cdb, name, (lambda n=name: lambda *a, **k: ran.append(n))())
    monkeypatch.setattr(cdb, "Base", type("B", (), {"metadata": type("M", (), {
        "create_all": staticmethod(lambda *a, **k: None)})()}))
    cdb.init_db()
    assert "_migrate_encrypt_mcp_env" in ran


# ---------------------------------------------------------------------------
# A wrong key degrades, it does not 500
# ---------------------------------------------------------------------------


def test_an_unreadable_row_degrades_to_unconfigured(db, monkeypatch, tmp_path):
    """`decrypt()` returns `""` on `InvalidToken`, and every consumer spells
    the read `json.loads(srv.env) if srv.env else {}` — so a rotated key costs
    a server its env, not the process."""
    engine, Factory = db
    _add(Factory)

    from src import secret_storage
    monkeypatch.setattr(secret_storage, "_KEY_PATH", tmp_path / ".other_key")
    monkeypatch.setattr(secret_storage, "_fernet", None)

    value = _get(Factory)
    assert value == ""
    assert (json.loads(value) if value else {}) == {}


# ---------------------------------------------------------------------------
# The paths that read it
# ---------------------------------------------------------------------------


def test_the_connect_path_still_gets_a_dict(db, monkeypatch):
    """`McpManager._connect_with_timeout` does `json.loads(srv.env)`."""
    import asyncio
    from core.database import McpServer
    from src.mcp_manager import McpManager

    engine, Factory = db
    _add(Factory)
    session = Factory()
    try:
        srv = session.query(McpServer).filter(McpServer.id == "abcd1234").first()
        seen = {}

        mgr = McpManager()

        async def _capture(**kw):
            seen.update(kw)
            return True

        mgr.connect_server = _capture
        asyncio.run(mgr._connect_with_timeout(srv))
    finally:
        session.close()

    assert seen["env"] == {"GITHUB_TOKEN": TOKEN, "LOG_LEVEL": "debug"}


def test_the_cli_still_redacts_on_read(db):
    """`pantheon-mcp show` hides values unless `--reveal`. Encryption at rest
    is a different control from redaction on screen; both still apply."""
    import importlib.util

    from core.database import McpServer

    engine, Factory = db
    _add(Factory)
    spec = importlib.util.spec_from_loader(
        "pantheon_mcp_cli",
        importlib.machinery.SourceFileLoader("pantheon_mcp_cli", str(ROOT / "scripts" / "pantheon-mcp")),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["pantheon_mcp_cli"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # pragma: no cover - only if the repo is not importable
        pytest.skip("pantheon-mcp is not importable in this environment")

    session = Factory()
    try:
        srv = session.query(McpServer).filter(McpServer.id == "abcd1234").first()
        redacted = module._serialize(srv, redact_env=True)
        revealed = module._serialize(srv, redact_env=False)
    finally:
        session.close()
        sys.modules.pop("pantheon_mcp_cli", None)

    assert redacted["env"] == {"GITHUB_TOKEN": "***", "LOG_LEVEL": "***"}
    assert revealed["env"]["GITHUB_TOKEN"] == TOKEN
