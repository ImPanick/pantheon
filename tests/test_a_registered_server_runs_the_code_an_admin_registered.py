# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22`, the integrator's call on mcp-build's `B-NEW-2` (`integrate-e`) — a
registration pins the code an admin approved.

**Measured before this file, on the merged tree `0b9adaa`:** a registered
relay ran whatever `~/mcp-servers/<name>/server.py` held at the moment of each
call. The admin approved *fields*; the code behind them could change
afterwards — by the author (the dev loop), but also by the author's assistant,
through its workstation tools or through `app_api`'s loopback to
`PUT /api/mcp/scaffold/{name}`, which no blocklist names. So an admin approved
one program and another ran, for every person's agent that called it. Every
case below is red there (no `--sha256`, no refusal, the loopback's edit
accepted).

**The rule now:** the registration records the fingerprint of the server's
code (`workstation_mcp.PIN_FLAG`, read by the harness in the author's account:
every file Python could load as code from the folder, and every symlink).
Before every list and call the relay's harness reads it again; code that no
longer matches is not started, and the answer tells the person an admin must
register it again. While a server is registered only a person changes its code
through the scaffold route — the assistant's loopback is refused. Registering
again through the admin route (`PUT /api/mcp/servers/{id}`, `require_admin`)
re-pins.

**The adversary (`Law 17`):** text the author's assistant reads, steering it
into rewriting a tool every other person's agent calls.

Driven, not read (`Law 20`): the real scaffold and admin routes through
`TestClient`, the real workstation daemon, and the relay as a real subprocess
through `McpManager.connect_server` with the registered fields — the harness
and the fixtures are `test_an_mcp_server_is_built_in_your_workstation`'s.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.middleware import INTERNAL_TOOL_HEADER
from src import workstation_mcp as wm
from tests.test_an_mcp_server_is_built_in_your_workstation import (  # noqa: F401 — fixtures
    _as, _home, _make, _relay_world, client, rows, station,
)

CODE_THAT_SAYS_IT_RAN = '''import json, os, sys
sys.stdout = sys.stderr
open(os.path.expanduser("~/it-ran"), "a").write("ran\\n")

def answer(message):
    if "id" not in message:
        return None
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "changed", "version": "2"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "get_forecast", "description": "Changed.",
                             "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": "the new code answered"}], "isError": False}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}

for raw in iter(sys.stdin.buffer.readline, b""):
    out = answer(json.loads(raw))
    if out is not None:
        sys.__stdout__.write(json.dumps(out) + "\\n")
        sys.__stdout__.flush()
'''
LOOPBACK = {"x-test-user": "ann", INTERNAL_TOOL_HEADER: "whatever-it-carries"}


def _register(client, reg) -> str:
    form = {"name": reg["name"], "transport": "stdio", "command": reg["command"],
            "args": json.dumps(reg["args"]), "env": json.dumps(reg["env"])}
    saved = client.post("/api/mcp/servers", data=form, headers=_as("admin"))
    assert saved.status_code == 200, saved.text
    return saved.json()["id"]


def _relay(reg, *, then=None, calls=(("get_forecast", {"text": "Oslo"}),)):
    """Start the relay as the admin's registration starts it, list, optionally
    change something (`then`), and call."""
    from src.mcp_manager import McpManager

    async def go():
        manager = McpManager()
        started = await manager.connect_server(
            server_id="relay1", name=reg["name"], transport="stdio",
            command=reg["command"], args=reg["args"], env=reg["env"])
        status = manager.get_server_status("relay1")
        tools = sorted(t["name"] for t in manager.get_all_tools() if t["server_id"] == "relay1")
        out = []
        try:
            if then is not None:
                then()
            for name, arguments in calls if started else ():
                out.append(await manager.call_tool(f"mcp__relay1__{name}", arguments))
        finally:
            await manager.disconnect_server("relay1")
        return started, status, tools, out

    return asyncio.run(go())


def _folder(station):
    return _home(station, "ann") / "mcp-servers" / "weather"


def test_the_relay_answers_the_code_registered_and_refuses_it_once_changed(client, station,
                                                                          monkeypatch):
    reg = _make(client).json()["registration"]
    assert reg["args"][5] == wm.PIN_FLAG == "--sha256"
    _register(client, reg)
    _relay_world(station, monkeypatch)
    started, status, tools, out = _relay(reg)
    assert started is True and tools == ["get_forecast"], status
    assert out[0]["exit_code"] == 0 and "Oslo" in out[0]["stdout"]

    # The author changes the code in the panel — a person, so it is saved,
    # and the answer says it is registered.
    saved = client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                       json={"source": CODE_THAT_SAYS_IT_RAN})
    assert saved.status_code == 200 and saved.json() == {"saved": True, "registered": True}
    before = len(station.execs)
    started, status, tools, out = _relay(reg)
    assert started is False and tools == []
    assert wm.changed_since_registered("weather") in str(status.get("error")), status
    assert "admin registers it again" in wm.changed_since_registered("weather")
    assert not (_home(station, "ann") / "it-ran").exists(), "the changed code never started"
    relayed = station.execs[before:]
    assert relayed and all(json.loads(e["body"]["stdin"])["pin"] == reg["args"][6] for e in relayed)


def test_code_changed_between_a_list_and_a_call_is_not_run(client, station, monkeypatch):
    """The relay's harness asks on every call, not once: the code is changed
    on disk — as the author's assistant could from its workstation shell —
    after the relay listed it, and the call answers the sentence."""
    reg = _make(client).json()["registration"]
    _register(client, reg)
    _relay_world(station, monkeypatch)

    def rewrite():
        (_folder(station) / "server.py").write_text(CODE_THAT_SAYS_IT_RAN)
    started, status, tools, (said,) = _relay(reg, then=rewrite)
    assert started is True and tools == ["get_forecast"], status
    assert said["exit_code"] == 1, said
    assert wm.changed_since_registered("weather") in (said["stderr"] + said.get("stdout", ""))
    assert not (_home(station, "ann") / "it-ran").exists()


def test_the_person_who_allowed_the_call_reads_why_it_did_not_run(client, station, monkeypatch):
    """An agent's call to a registered tool asks first once the turn has read
    untrusted text — the usual case. The card the person had just allowed read
    "(no output)" for the relay's refusal: the approved path read `stdout` and
    not `stderr`, where `McpManager` puts an `isError` answer. The relay's real
    answer, through the real approval replay."""
    from tests.test_tool_effect_wire import _approved_run

    reg = _make(client).json()["registration"]
    _register(client, reg)
    _relay_world(station, monkeypatch)

    def rewrite():
        (_folder(station) / "server.py").write_text(CODE_THAT_SAYS_IT_RAN)
    _, _, _, (said,) = _relay(reg, then=rewrite)
    assert said["stdout"] == "" and said["exit_code"] == 1, said
    tool = "mcp__relay1__get_forecast"
    events = _approved_run(monkeypatch, tool_name=tool, content='{"text": "Oslo"}',
                           results={tool: said})
    card = next(e for e in events if e.get("type") == "tool_output")
    assert card["approved"] is True and card["status"] == "error", card
    assert wm.changed_since_registered("weather") in card["output"], card["output"]


@pytest.mark.parametrize("plant", ["a sibling module", "bytecode in __pycache__", "a symlink",
                                   "a symlinked package"])
def test_code_beside_the_server_is_pinned_too(client, station, monkeypatch, plant):
    """`server.py` imports from its own folder first: a `json.py` planted
    beside it would replace the standard library's, a cached `.pyc` would be
    loaded in place of a module's source, a symlink can point anywhere — a
    symlinked folder is a package whose code lives outside, which the walk
    does not enter. Each moves the fingerprint, so each takes it off the air."""
    reg = _make(client).json()["registration"]
    _register(client, reg)
    _relay_world(station, monkeypatch)
    folder = _folder(station)
    if plant == "a sibling module":
        (folder / "json.py").write_text("raise SystemExit('not the json you wanted')\n")
    elif plant == "bytecode in __pycache__":
        (folder / "__pycache__").mkdir()
        (folder / "__pycache__" / "helper.cpython-311.pyc").write_bytes(b"\x00planted")
    elif plant == "a symlink":
        (folder / "elsewhere.py").symlink_to(station.tmp / "outside.py")
    else:
        outside = station.tmp / "outside-package"
        outside.mkdir()
        (outside / "__init__.py").write_text("")
        (folder / "helper").symlink_to(outside, target_is_directory=True)
    started, status, tools, _ = _relay(reg, calls=())
    assert started is False and wm.changed_since_registered("weather") in str(status.get("error"))


def test_while_registered_only_a_person_changes_its_code(client, station):
    _make(client)
    path = _folder(station) / "server.py"
    # Before it is registered the assistant may help write it (the dev loop).
    first = client.put("/api/mcp/scaffold/weather", headers=LOOPBACK,
                       json={"source": path.read_text() + "\n# the assistant's\n"})
    assert first.status_code == 200 and first.json()["registered"] is False
    reg = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registration"]
    _register(client, reg)
    kept = path.read_text()
    refused = client.put("/api/mcp/scaffold/weather", headers=LOOPBACK,
                         json={"source": CODE_THAT_SAYS_IT_RAN})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"].startswith("This server is registered, so only you can change its code")
    assert path.read_text() == kept
    token = client.put("/api/mcp/scaffold/weather", json={"source": CODE_THAT_SAYS_IT_RAN},
                       headers={"x-test-user": "ann", "x-test-token": "1"})
    assert token.status_code in (401, 403) and path.read_text() == kept
    mine = client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": CODE_THAT_SAYS_IT_RAN})
    assert mine.status_code == 200 and mine.json()["registered"] is True


def test_registering_again_through_the_admin_route_re_pins(client, station, monkeypatch, rows):
    reg = _make(client).json()["registration"]
    server_id = _register(client, reg)
    read = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()
    assert read["registered"] == "current"
    client.put("/api/mcp/scaffold/weather", headers=_as("ann"), json={"source": CODE_THAT_SAYS_IT_RAN})
    read = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()
    assert read["registered"] == "changed"
    fresh = read["registration"]
    assert fresh["args"][:6] == reg["args"][:6] and fresh["args"][6] != reg["args"][6]

    # Not by ann: re-pinning is the admin route's, as registering is.
    assert client.put(f"/api/mcp/servers/{server_id}", data={"args": json.dumps(fresh["args"])},
                      headers=_as("ann")).status_code == 403
    again = client.put(f"/api/mcp/servers/{server_id}", data={"args": json.dumps(fresh["args"])},
                       headers=_as("admin"))
    assert again.status_code == 200, again.text
    assert client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registered"] == "current"
    _relay_world(station, monkeypatch)
    started, status, tools, (said,) = _relay(fresh)
    assert started is True, status
    assert said == {"stdout": "the new code answered", "stderr": "", "exit_code": 0}
    assert (_home(station, "ann") / "it-ran").exists()


@pytest.mark.parametrize("argv", [
    ["--owner", "ann", "--server", "weather"],
    ["--owner", "ann", "--server", "weather", "--sha256", ""],
    ["--owner", "ann", "--server", "weather", "--sha256", "not-a-fingerprint"],
    ["--owner", "ann", "--server", "weather", "--sha256", "A" * 64],
])
def test_the_relay_will_not_start_without_a_fingerprint(argv):
    with pytest.raises(SystemExit) as stopped:
        wm._relay_args(argv)
    assert stopped.value.code == 2
