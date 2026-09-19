# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-00` for `P8-35`/`P8-36`/`P8-37` — the surface a person actually reaches.

`P8-00` says a row closes on someone reaching the capability unaided, not on
the capability existing. The browser halves of these three live in `static/**`,
which this change does not own, so the unaided surface here is the shell one:
`pantheon-mcp`, which already had `list`, `show`, `add`, `enable`, `disable`
and `delete` and now has `update`, `tools` and `call`.

MEASURED BEFORE: `pantheon-mcp --help` offered seven subcommands and not one of
them could change a stored server or call a tool. The only edit was
delete-and-re-add, which mints a new id.

These tests RUN A REAL MCP SERVER — a five-line FastMCP stdio server written
into `tmp_path` — and drive the CLI functions against it (`Law 20`). The hang
test uses a server that really does sleep, so the deadline is measured, not
mocked.
"""
from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp", reason="the MCP SDK is optional; these drive a real server")

from tests.helpers.cli_loader import load_script  # noqa: E402

TINY_SERVER = '''
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tiny")


@mcp.tool()
def echo(text: str) -> str:
    """Say it back."""
    return "echo: " + text


@mcp.tool()
def hang() -> str:
    """Never answers."""
    import time
    time.sleep(3600)
    return "never"


if __name__ == "__main__":
    mcp.run()
'''


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """The real CLI, wired to a real temp database and a real MCP server."""
    from core.database import Base, McpServer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import secret_storage

    monkeypatch.setattr(secret_storage, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(secret_storage, "_fernet", None)

    server_py = tmp_path / "tiny_server.py"
    server_py.write_text(TINY_SERVER, encoding="utf-8")

    engine = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)

    db = Factory()
    try:
        db.add(McpServer(id="tiny0001", name="Tiny", transport="stdio",
                         command=sys.executable, args=json.dumps([str(server_py)]),
                         env=json.dumps({"TINY_TOKEN": "t1"}), is_enabled=True,
                         disabled_tools=json.dumps(["hang"])))
        db.commit()
    finally:
        db.close()

    module = load_script("pantheon-mcp")
    monkeypatch.setattr(module, "SessionLocal", Factory)
    module._test_factory = Factory
    module._test_server_py = server_py
    return module


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def _args(**kw):
    base = dict(pretty=False, id="tiny0001", tool=None, args=None, timeout=None,
                name=None, transport=None, command=None, env=None, url=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# `pantheon-mcp tools` — what the server really offers
# ---------------------------------------------------------------------------


def test_tools_connects_and_reports_what_is_there(cli, capsys):
    cli.cmd_tools(_args())
    out = _out(capsys)
    assert out["tool_count"] == 2
    names = {t["name"]: t for t in out["tools"]}
    assert set(names) == {"echo", "hang"}
    assert names["hang"]["is_disabled"] is True
    assert names["echo"]["is_disabled"] is False


# ---------------------------------------------------------------------------
# `pantheon-mcp call` — `P8-36`
# ---------------------------------------------------------------------------


def test_call_actually_runs_the_tool(cli, capsys):
    cli.cmd_call(_args(tool="echo", args='{"text": "hi"}'))
    out = _out(capsys)
    assert out["ok"] is True
    assert out["stdout"] == "echo: hi"
    assert out["exit_code"] == 0
    assert out["tool_is_disabled"] is False


def test_call_names_the_tools_there_are_when_the_name_is_wrong(cli, capsys):
    with pytest.raises(SystemExit):
        cli.cmd_call(_args(tool="ecoh"))
    err = capsys.readouterr().err
    assert "ecoh" in err and "echo" in err


def test_call_refuses_non_object_arguments(cli, capsys):
    with pytest.raises(SystemExit):
        cli.cmd_call(_args(tool="echo", args='["hi"]'))
    assert "JSON object" in capsys.readouterr().err


def test_a_tool_hidden_from_the_agent_is_still_callable_and_says_so(cli, capsys):
    """`hang` is in `disabled_tools`; the operator testing their own server is
    not the model reaching past a switch they set."""
    cli.cmd_call(_args(tool="hang", timeout=1.5))
    out = _out(capsys)
    assert out["tool_is_disabled"] is True


# ---------------------------------------------------------------------------
# `P8-37` against a server that really hangs
# ---------------------------------------------------------------------------


def test_a_hung_tool_comes_back_instead_of_hanging_the_shell(cli, capsys):
    started = time.monotonic()
    cli.cmd_call(_args(tool="hang", timeout=2))
    elapsed = time.monotonic() - started
    out = _out(capsys)

    assert out["timed_out"] is True
    assert out["ok"] is False
    assert out["timeout"] == 2.0
    assert "2s" in out["error"]
    assert elapsed < 20, f"the deadline did not bound it ({elapsed:.1f}s)"


def test_the_deadline_cannot_be_switched_off_from_the_command_line(cli, capsys):
    cli.cmd_call(_args(tool="echo", args='{"text": "x"}', timeout=0))
    assert _out(capsys)["timeout"] == 120.0


# ---------------------------------------------------------------------------
# `pantheon-mcp update` — `P8-35`
# ---------------------------------------------------------------------------


def test_update_keeps_the_id_and_the_disabled_list(cli, capsys):
    from core.database import McpServer

    cli.cmd_update(_args(name="Tiny (renamed)", env='{"TINY_TOKEN": "t2"}'))
    out = _out(capsys)

    assert out["ok"] is True
    assert out["id"] == "tiny0001"
    assert out["id_changed"] is False
    assert out["before"]["name"] == "Tiny"
    assert out["after"]["name"] == "Tiny (renamed)"

    db = cli._test_factory()
    try:
        row = db.query(McpServer).filter(McpServer.id == "tiny0001").first()
        assert json.loads(row.env) == {"TINY_TOKEN": "t2"}
        assert json.loads(row.disabled_tools) == ["hang"]
    finally:
        db.close()


def test_update_leaves_untouched_fields_alone(cli, capsys):
    from core.database import McpServer

    cli.cmd_update(_args(name="Renamed"))
    capsys.readouterr()

    db = cli._test_factory()
    try:
        row = db.query(McpServer).filter(McpServer.id == "tiny0001").first()
        assert row.command == sys.executable
        assert json.loads(row.env) == {"TINY_TOKEN": "t1"}
    finally:
        db.close()


def test_the_edited_server_is_the_one_that_starts(cli, capsys):
    """The whole loop the row is about: edit, then call, without re-adding."""
    cli.cmd_update(_args(args=json.dumps([str(cli._test_server_py)])))
    capsys.readouterr()
    cli.cmd_call(_args(tool="echo", args='{"text": "after the edit"}'))
    assert _out(capsys)["stdout"] == "echo: after the edit"


def test_update_refuses_a_transport_switch_without_its_field(cli, capsys):
    from core.database import McpServer

    with pytest.raises(SystemExit):
        cli.cmd_update(_args(transport="http"))
    assert "url is required" in capsys.readouterr().err

    db = cli._test_factory()
    try:
        assert db.query(McpServer).filter(McpServer.id == "tiny0001").first().transport == "stdio"
    finally:
        db.close()


def test_update_refuses_malformed_json(cli, capsys):
    with pytest.raises(SystemExit):
        cli.cmd_update(_args(env='{"A": "b"'))
    assert "invalid --env" in capsys.readouterr().err


def test_update_on_an_unknown_id_says_so(cli, capsys):
    with pytest.raises(SystemExit):
        cli.cmd_update(_args(id="nosuch", name="x"))
    assert "no MCP server with id" in capsys.readouterr().err


def test_update_tells_the_operator_the_running_app_has_not_reloaded(cli, capsys):
    """`Law 15`. The CLI edits the row; the manager lives in the app process."""
    cli.cmd_update(_args(name="Renamed"))
    assert "reconnect" in _out(capsys)["note"].lower()
