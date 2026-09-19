# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-47` — the scaffold's claim is that the file it writes *runs*.

Anybody can write a template. What makes this a scaffold rather than a
snippet is that the generated file completes an MCP handshake, lists its
tools and answers a call, through the same `McpManager` the app uses — so
these tests spawn it rather than reading it (`Law 20`).

The other half of the row is where it may be registered from, and that is
pinned here from both sides at once:

  * `_validate_mcp_command` — the agent path — must **refuse** the exact
    registration this scaffold produces. That refusal is the reported-RCE fix
    (`FORBIDDEN.md` Part 2) and this file fails the day it stops refusing.
  * `POST /api/mcp/servers` — the admin route, behind `require_admin` — must
    **accept** it, store the absolute path and spawn exactly that argv.

Nothing here weakens either. The scaffold registers nothing at all.
"""
from __future__ import annotations

import ast
import asyncio
import json
import keyword
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mcp_scaffold  # noqa: E402
from src.mcp_scaffold import (  # noqa: E402
    ScaffoldError,
    create_server,
    list_servers,
    normalise_server_name,
    normalise_tool_name,
    refusal_on_the_agent_path,
    registration_for,
    scaffold_root,
    server_dir,
    verify_server,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _has_mcp() -> bool:
    import importlib.util

    return importlib.util.find_spec("mcp") is not None


needs_mcp = pytest.mark.skipif(
    not _has_mcp(),
    reason="the `mcp` package is required to start a generated server",
)


def _read(record, filename="server.py") -> str:
    return Path(record["directory"], filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# It runs. This is the row.
# ---------------------------------------------------------------------------


@needs_mcp
def test_a_freshly_generated_server_starts_and_lists_its_tools(tmp_path):
    """The whole claim, driven: generate, spawn, handshake, list, stop."""
    record = create_server(
        "weather", tools=["get_forecast", "send_alert"], data_dir=str(tmp_path)
    )
    result = asyncio.run(verify_server("weather", data_dir=str(tmp_path)))
    assert result["error"] is None, result["error"]
    assert result["started"] is True
    assert result["tools"] == ["get_forecast", "send_alert"]
    assert record["tools"] == ["get_forecast", "send_alert"]


@needs_mcp
def test_a_generated_tool_answers_through_the_manager_the_agent_uses(tmp_path):
    """`McpManager.call_tool` — same method, same envelope as a real turn.

    A server that lists a tool and then cannot be called is the failure this
    catches; `list_tools` alone would not.
    """
    from src.mcp_manager import McpManager

    create_server("weather", tools=["get_forecast"], data_dir=str(tmp_path))
    registration = registration_for("weather", data_dir=str(tmp_path))

    async def go():
        manager = McpManager()
        started = await manager.connect_server(
            server_id="probe", name="weather", transport="stdio",
            command=registration["command"], args=registration["args"], env={},
        )
        assert started, manager.get_server_status("probe")
        try:
            return await manager.call_tool(
                "mcp__probe__get_forecast", {"text": "Tuesday"}
            )
        finally:
            await manager.disconnect_server("probe")

    envelope = asyncio.run(go())
    assert envelope["exit_code"] == 0
    assert "get_forecast" in envelope["stdout"]
    assert "Tuesday" in envelope["stdout"]


@needs_mcp
def test_a_server_that_does_not_start_is_reported_not_raised(tmp_path):
    """The check has to survive the person breaking their own file."""
    create_server("weather", data_dir=str(tmp_path))
    source = Path(server_dir("weather", data_dir=str(tmp_path)), "server.py")
    source.write_text(source.read_text() + "\nthis is not python(\n", encoding="utf-8")

    result = asyncio.run(verify_server("weather", data_dir=str(tmp_path)))
    assert result["started"] is False
    assert result["tools"] == []
    assert "standard error" in result["error"]


def test_checking_a_server_that_was_never_generated_says_so(tmp_path):
    result = asyncio.run(verify_server("nothing-here", data_dir=str(tmp_path)))
    assert result["started"] is False
    assert "server.py" in result["error"]


# ---------------------------------------------------------------------------
# Where it may be registered from — both sides of the same rule
# ---------------------------------------------------------------------------


def test_the_agent_path_refuses_the_registration_this_scaffold_produces(tmp_path):
    """`FORBIDDEN.md` Part 2, from the outside.

    This is why the row says "register through the admin route": the command
    is an interpreter *and* contains a path, and `manage_mcp` refuses both.
    If this test ever goes green-by-acceptance, the RCE fix has been weakened.
    """
    from src.agent_tools.admin_tools import _validate_mcp_command

    create_server("weather", data_dir=str(tmp_path))
    registration = registration_for("weather", data_dir=str(tmp_path))

    error = _validate_mcp_command(
        registration["command"], registration["args"], registration["env"]
    )
    assert error, "the agent path accepted an interpreter running an absolute path"
    assert "path" in error or "not allowed" in error or "allowlist" in error


def test_the_scaffold_says_the_refusal_the_validator_gives_rather_than_a_copy(tmp_path):
    """The explanation is asked of the rule, so it cannot drift from it.

    Driven by making the validator answer differently: with a bare, allowlisted
    command there is no refusal, and the sentence changes to say so. A
    hand-written string could not do that.
    """
    create_server("weather", data_dir=str(tmp_path))
    real = registration_for("weather", data_dir=str(tmp_path))
    assert refusal_on_the_agent_path(real).startswith("manage_mcp: refused")

    pretend = dict(real, command="mytool", args=[], env={})
    os.environ["PANTHEON_MCP_ALLOWED_COMMANDS"] = "mytool"
    try:
        assert refusal_on_the_agent_path(pretend).startswith("Nothing")
    finally:
        os.environ.pop("PANTHEON_MCP_ALLOWED_COMMANDS", None)


class _FakeRequest:
    """Enough of a request for `require_admin`, via the documented loopback
    header — the same shape `tests/test_a_server_you_could_not_start_is_not_added.py`
    uses. The admin gate itself is pinned there; this is about what the route
    does with the scaffold's fields once it has let you in."""

    def __init__(self):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

        self.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        self.state = SimpleNamespace(current_user="admin")
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))


class _RecordingManager:
    """An `McpManager` that records the spawn instead of performing it.

    Whether the file runs is settled by the spawning tests above; this one is
    about the values surviving the route.
    """

    def __init__(self):
        self.last = None

    async def connect_server(self, **kwargs):
        self.last = kwargs
        return True

    def get_server_status(self, server_id):
        return {"status": "connected", "tool_count": 1, "error": None}


def test_the_admin_route_accepts_it_and_stores_the_absolute_path(tmp_path):
    """The other door, driven end to end.

    The scaffold's registration goes into `POST /api/mcp/servers` exactly as
    it comes out, and what reaches the spawn is the interpreter plus the one
    absolute argument — not a rewritten, relative or truncated form.
    """
    import unittest.mock as mock

    from core.database import Base, McpServer
    from routes.mcp.mcp_routes import setup_mcp_routes
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    create_server("weather", tools=["get_forecast"], data_dir=str(tmp_path))
    registration = registration_for("weather", data_dir=str(tmp_path))

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)

    manager = _RecordingManager()
    router = setup_mcp_routes(manager)
    endpoint = next(
        route.endpoint for route in router.routes
        if route.path == "/api/mcp/servers" and "POST" in getattr(route, "methods", set())
    )

    with mock.patch("routes.mcp.mcp_routes.SessionLocal", Factory):
        asyncio.run(endpoint(
            request=_FakeRequest(),
            name=registration["name"],
            transport=registration["transport"],
            command=registration["command"],
            args=json.dumps(registration["args"]),
            env=json.dumps(registration["env"]),
            url="",
            oauth_file="",
            oauth_config="",
        ))

    assert manager.last["command"] == registration["command"]
    assert manager.last["args"] == registration["args"]
    assert os.path.isabs(manager.last["args"][0])

    session = Factory()
    try:
        row = session.query(McpServer).one()
        assert row.name == "weather"
        assert row.transport == "stdio"
        assert row.command == registration["command"]
        assert json.loads(row.args) == registration["args"]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# It is written to the volume, and it cannot be a built-in
# ---------------------------------------------------------------------------


def test_generated_servers_live_under_the_data_dir_not_beside_the_builtins():
    """The row's first constraint. `DATA_DIR` is the mount; the source tree is
    baked into the image, so a file written next to `memory_server.py` is gone
    at the next image update while its registration survives."""
    from src.constants import DATA_DIR
    from src.runtime_paths import get_app_root

    root = scaffold_root()
    assert root.startswith(os.path.abspath(DATA_DIR) + os.sep)
    assert root != os.path.join(get_app_root(), "mcp_servers")


def test_no_builtin_server_lives_where_a_generated_one_would():
    """"Generated servers cannot be built-ins" as a property rather than a
    promise: every `_BUILTIN_SERVERS` script is app-root-relative, and none of
    them resolves inside the scaffold root."""
    from src.builtin_mcp import _BUILTIN_SERVERS
    from src.runtime_paths import get_app_root

    root = os.path.realpath(scaffold_root())
    for script, _name in _BUILTIN_SERVERS.values():
        assert not os.path.isabs(script)
        resolved = os.path.realpath(os.path.join(get_app_root(), script))
        assert not resolved.startswith(root + os.sep)


# ---------------------------------------------------------------------------
# Names: the directory, and the tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["../../etc/evil", "..", "./../x", "weather/../../y", "a\\..\\b", "  Weather  "],
)
def test_a_name_can_never_leave_the_scaffold_root(raw, tmp_path):
    """Two independent guards: `slugify` maps every non-alphanumeric run to a
    dash before the regex sees it, and `server_dir` realpath-contains the
    result anyway. A refusal is as good an outcome as a contained path."""
    root = os.path.realpath(scaffold_root(str(tmp_path)))
    try:
        path = server_dir(raw, data_dir=str(tmp_path))
    except ScaffoldError:
        return
    assert os.path.realpath(path).startswith(root + os.sep)


@pytest.mark.parametrize("raw", ["", "   ", "---", "!!!", "/", "."])
def test_an_unusable_server_name_is_refused_with_an_example(raw, tmp_path):
    with pytest.raises(ScaffoldError) as caught:
        normalise_server_name(raw)
    assert "weather" in str(caught.value)


def test_a_tool_name_with_a_double_underscore_is_refused():
    """`FORBIDDEN.md` Part 1 pins `mcp__{server_id}__{tool_name}`, and its sole
    parse is one `split("__", 2)` (`P8-44`). A tool called `a__b` would be
    addressed as a tool on another server."""
    with pytest.raises(ScaffoldError) as caught:
        normalise_tool_name("get__thing")
    assert "mcp__" in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    ["call_tool", "list_tools", "server", "main", "TOOLS", "json", "asyncio"],
)
def test_a_tool_that_would_shadow_the_generated_wiring_is_refused(raw):
    with pytest.raises(ScaffoldError):
        normalise_tool_name(raw)


@pytest.mark.parametrize("raw", ["import", "class", "return", "lambda"])
def test_a_python_keyword_is_refused_as_a_tool_name(raw):
    assert keyword.iskeyword(raw)
    with pytest.raises(ScaffoldError):
        normalise_tool_name(raw)


@pytest.mark.parametrize(
    "raw", ["Get_Forecast", "get forecast", "get-forecast", "2fast", "", "x" * 60]
)
def test_a_tool_name_that_is_not_an_identifier_is_refused(raw):
    with pytest.raises(ScaffoldError):
        normalise_tool_name(raw)


def test_asking_for_the_same_tool_twice_is_refused_by_name(tmp_path):
    with pytest.raises(ScaffoldError) as caught:
        create_server("weather", tools=["get_forecast", "get_forecast"],
                      data_dir=str(tmp_path))
    assert "get_forecast" in str(caught.value)
    assert not os.path.exists(server_dir("weather", data_dir=str(tmp_path)))


def test_more_tools_than_it_makes_in_one_go_is_refused_before_anything_is_written(tmp_path):
    tools = [f"tool_{n}" for n in range(mcp_scaffold.MAX_TOOLS + 1)]
    with pytest.raises(ScaffoldError):
        create_server("weather", tools=tools, data_dir=str(tmp_path))
    assert not os.path.exists(server_dir("weather", data_dir=str(tmp_path)))


# ---------------------------------------------------------------------------
# Nothing it writes can be text somebody typed
# ---------------------------------------------------------------------------


_HOSTILE = [
    '"""\nimport os\nos.system("id")\n"""',
    "'''\nSERVER_NAME = 'other'\n'''",
    'x" \nimport socket\n#',
    "\\\" + __import__('os').system('id') + \"",
    "line one\nline two\r\nline three",
    "\x00\x07 nul and bell",
    "back\\slash and   separator",
]


@pytest.mark.parametrize("text", _HOSTILE)
def test_hostile_text_in_a_description_cannot_become_code(text, tmp_path):
    """`_py_literal` is `json.dumps`, whose output is a double-quoted literal
    with no raw newline and every quote and backslash escaped — and Python
    reads `\\uXXXX` the way JSON writes it. So the generated module's top-level
    statements are the same set whatever is typed."""
    record = create_server("weather", tools=["get_thing"], description=text,
                           data_dir=str(tmp_path))
    tree = ast.parse(_read(record))

    assigned = [
        node.targets[0].id for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    ]
    assert assigned == ["SERVER_NAME", "SERVER_DESCRIPTION", "TOOLS", "HANDLERS", "server"]

    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"__future__", "asyncio", "json", "mcp.server",
                        "mcp.server.stdio", "mcp.types"}


@pytest.mark.parametrize("text", _HOSTILE)
def test_hostile_text_survives_intact_rather_than_being_mangled(text, tmp_path):
    """Escaping that loses the text is a different bug from escaping that
    fails. The description comes back out of the generated file byte for byte
    (after the strip `create_server` documents)."""
    record = create_server("weather", description=text, data_dir=str(tmp_path))
    source = _read(record)
    line = next(l for l in source.splitlines() if l.startswith("SERVER_DESCRIPTION = "))
    assert ast.literal_eval(line.split(" = ", 1)[1]) == text.strip()


@needs_mcp
def test_a_server_generated_from_hostile_text_still_starts(tmp_path):
    """The escaping must not merely be safe — the file still has to run."""
    create_server("weather", tools=["get_thing"], description=_HOSTILE[0],
                  data_dir=str(tmp_path))
    result = asyncio.run(verify_server("weather", data_dir=str(tmp_path)))
    assert result["started"] is True, result["error"]
    assert result["tools"] == ["get_thing"]


# ---------------------------------------------------------------------------
# It never destroys
# ---------------------------------------------------------------------------


def test_a_second_run_refuses_rather_than_overwriting_the_code_you_wrote(tmp_path):
    record = create_server("weather", data_dir=str(tmp_path))
    source = Path(record["directory"], "server.py")
    mine = source.read_text() + "\n# the afternoon I spent on this\n"
    source.write_text(mine, encoding="utf-8")

    with pytest.raises(ScaffoldError) as caught:
        create_server("weather", data_dir=str(tmp_path))
    assert "already exists" in str(caught.value)
    assert source.read_text() == mine


def test_the_generated_server_is_not_world_readable(tmp_path):
    """It is about to be run as the app user and it will hold whatever the
    person puts in it."""
    record = create_server("weather", data_dir=str(tmp_path))
    mode = os.stat(Path(record["directory"], "server.py")).st_mode & 0o777
    assert mode & 0o077 == 0


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------


def test_listing_an_install_that_has_generated_nothing_is_empty_not_an_error(tmp_path):
    assert list_servers(data_dir=str(tmp_path / "never-made")) == []


def test_the_cli_creates_checks_and_lists(tmp_path, capsys):
    """`main` is the whole of `scripts/pantheon-mcp-new`; driving it is driving
    the script."""
    data_dir = str(tmp_path)
    code = mcp_scaffold.main(
        ["weather", "--tool", "get_forecast", "--data-dir", data_dir,
         "--no-self-test", "--pretty"]
    )
    assert code == 0
    created = json.loads(capsys.readouterr().out)
    assert created["tools"] == ["get_forecast"]
    assert created["self_test"]["ran"] is False
    assert any("--check" in step for step in created["next"])

    assert mcp_scaffold.main(["--list", "--data-dir", data_dir, "--pretty"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in listed["servers"]] == ["weather"]

    assert mcp_scaffold.main(["--data-dir", data_dir]) == 2  # no name: help, not a crash
    capsys.readouterr()


def test_the_cli_refuses_a_bad_name_with_a_sentence_and_a_nonzero_code(tmp_path, capsys):
    code = mcp_scaffold.main(["!!!", "--data-dir", str(tmp_path), "--no-self-test"])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not work as a server name" in captured.err


@needs_mcp
def test_the_cli_exit_code_tracks_whether_the_server_actually_started(tmp_path, capsys):
    data_dir = str(tmp_path)
    assert mcp_scaffold.main(["weather", "--data-dir", data_dir]) == 0
    capsys.readouterr()

    source = Path(server_dir("weather", data_dir=data_dir), "server.py")
    source.write_text(source.read_text() + "\nbroken(\n", encoding="utf-8")
    assert mcp_scaffold.main(["weather", "--check", "--data-dir", data_dir]) == 1
    checked = json.loads(capsys.readouterr().out)
    assert checked["self_test"]["started"] is False
    # A failure says one thing. It must not also tell you to register it.
    assert checked["next"][0].startswith("It did not start")
    assert not any("Register it" in step for step in checked["next"])


def test_the_readme_carries_the_fields_the_admin_form_asks_for(tmp_path):
    """`P8-00`: the person comes back to this folder a week later, and the
    instructions have to be where they are, not in a terminal they closed."""
    record = create_server("weather", tools=["get_forecast"], data_dir=str(tmp_path))
    readme = _read(record, "README.md")
    registration = record["register"]

    assert "MCP Tool Server" in readme
    assert registration["command"] in readme
    assert registration["args"][0] in readme
    assert "pantheon-mcp add" in readme
    assert record["the_assistant_cannot_do_this_for_you"] in readme


def test_a_symlink_planted_in_the_scaffold_root_cannot_redirect_a_write(tmp_path):
    """The case `_NAME_RE` cannot see, which is why the realpath check is there
    as well as the regex: the name is perfectly ordinary and the path is not."""
    root = Path(scaffold_root(str(tmp_path)))
    root.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "weather").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ScaffoldError):
        server_dir("weather", data_dir=str(tmp_path))
    assert list(elsewhere.iterdir()) == []


def test_a_description_longer_than_a_sentence_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ScaffoldError) as caught:
        create_server("weather", description="x" * (mcp_scaffold.MAX_DESCRIPTION_CHARS + 1),
                      data_dir=str(tmp_path))
    assert str(mcp_scaffold.MAX_DESCRIPTION_CHARS) in str(caught.value)
    assert not os.path.exists(server_dir("weather", data_dir=str(tmp_path)))


@needs_mcp
def test_the_probe_closes_without_complaining_about_the_task_it_opened_in(tmp_path, caplog):
    """`asyncio.timeout`, not `asyncio.wait_for`.

    `wait_for` runs the coroutine in a new Task, so `connect_server`'s
    AsyncExitStack is entered there and closed here — anyio then refuses the
    exit and `disconnect_server` logs "Error closing MCP server ...: Attempted
    to exit cancel scope in a different task". The probe process still dies,
    so the only visible difference is a warning on every successful run.
    """
    import logging

    create_server("weather", data_dir=str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="src.mcp_manager"):
        result = asyncio.run(verify_server("weather", data_dir=str(tmp_path)))
    assert result["started"] is True
    assert "cancel scope" not in caplog.text
    assert "Error closing MCP server" not in caplog.text
