# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` end to end, on the real workstation image: a server built from the
browser's door lands in the author's real Unix account, starts on the image's
own `python3` — which has no `mcp` package, the reason the template is
standard library — answers *Try*, and, through the relay started exactly as
an admin's registration starts it, answers the agent's call **as the author's
account and nobody else's**.

Opt-in, like the image test it borrows its fixtures from
(`tests/test_the_workstation_image_is_a_real_ubuntu_machine.py`): it runs only
when Docker answers and `PANTHEON_WORKSTATION_E2E=1`.
`PANTHEON_WORKSTATION_E2E_IMAGE=<tag>` uses an image already built. The
container and its volumes are removed afterwards by that module's fixture.

    PANTHEON_WORKSTATION_E2E=1 PANTHEON_WORKSTATION_E2E_IMAGE=pantheon-workstation:e2e \\
        python -m pytest tests/test_an_mcp_server_runs_in_a_real_workstation_e2e.py
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest

from core.auth import AuthManager as _RealAuthManager
from src import workstation_mcp as wm
from src.workstation_access import account_of
from test_the_workstation_image_is_a_real_ubuntu_machine import (  # noqa: F401 — fixtures
    image, pytestmark, station)

_PASSWORD = "a-long-test-password-1"

WHO = '''import json, os, pwd, sys
sys.stdout = sys.stderr

def answer(message):
    if "id" not in message:
        return None
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "who", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "who", "description": "Who runs this, and what it can read.",
                             "inputSchema": {"type": "object"}}]}
    else:
        target = (params.get("arguments") or {}).get("peek", "")
        try:
            os.listdir(target)
            peek = "read it"
        except OSError as exc:
            peek = type(exc).__name__
        try:
            import mcp  # noqa: F401
            sdk = "present"
        except ImportError:
            sdk = "absent"
        text = json.dumps({"user": pwd.getpwuid(os.getuid()).pw_name, "uid": os.getuid(),
                           "home": os.path.expanduser("~"), "peek": peek, "mcp": sdk,
                           "secret": os.environ.get("PANTHEON_PROBE_SECRET", "absent")})
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}

for raw in iter(sys.stdin.buffer.readline, b""):
    out = answer(json.loads(raw))
    if out is not None:
        sys.__stdout__.write(json.dumps(out) + "\\n")
        sys.__stdout__.flush()
'''


@pytest.fixture
def world(station, tmp_path, monkeypatch):
    """Pantheon's side, pointed at the real container: settings in process for
    the routes' functions, a data directory for the relay's own process, and
    an auth file in which `e2e-ann` may use the workstation and `e2e-bob` may
    too (so his home exists and is someone else's)."""
    import src.settings as S
    from workstation import protocol as P

    token = station.token()
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    data = tmp_path / "pantheon-data"
    data.mkdir()
    settings = {"workstation_enabled": True, "workstation_url": station.url,
                "workstation_token": token, "workstation_sudo": False}
    (data / "settings.json").write_text(json.dumps(settings))
    auth = _RealAuthManager(str(data / "auth.json"))
    assert auth.setup("admin", _PASSWORD)
    for name in ("e2e-ann", "e2e-bob"):
        assert auth.create_user(name, _PASSWORD)
        assert auth.set_privileges(name, {"can_use_workstation": True})
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(data))
    monkeypatch.setenv("PANTHEON_PROBE_SECRET", "pantheon-side-only")
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: settings[key] if key in settings else real(key, default))
    import core.auth
    monkeypatch.setattr(core.auth, "AuthManager", lambda *a, **k: auth)
    wm._LAST_CHECK.clear()
    return {"auth": auth, "token": token}


def _run(coro):
    return asyncio.run(coro)


def test_built_checked_and_tried_in_a_real_account_with_no_mcp_package(world, station):
    ann = account_of("e2e-ann")
    made = _run(wm.ws_create("e2e-ann", "weather", ["get_forecast"], "Forecasts"))
    assert made["registration"]["args"][1:] == ["--owner", "e2e-ann", "--server", "weather"]
    check = _run(wm.ws_verify("e2e-ann", "weather"))
    assert check["started"] is True, check
    assert check["tools"] == ["get_forecast"]
    tried = _run(wm.ws_try("e2e-ann", "weather", "get_forecast", {"text": "Oslo"}))
    assert tried["ok"] is True, tried
    assert tried["stdout"] == "get_forecast has not been written yet. It was called with text='Oslo'"
    client = station.client()
    owned = _run(client.exec(ann, "stat -c '%U %a' ~/mcp-servers ~/mcp-servers/weather/server.py; "
                                  "python3 -c 'import mcp' 2>/dev/null; echo mcp=$?"))
    lines = owned["stdout"].splitlines()
    assert [ln.split()[0] for ln in lines[:2]] == [ann, ann]
    assert lines[2] == "mcp=1"  # the image's python3 has no SDK


def test_the_relay_answers_the_agent_as_the_authors_account_and_nobody_elses(world, station):
    from src.mcp_manager import McpManager

    ann, bob = account_of("e2e-ann"), account_of("e2e-bob")
    _run(station.client().ensure(bob))
    _run(wm.ws_create("e2e-ann", "who", ["who"], ""))
    _run(wm.ws_write_source("e2e-ann", "who", WHO))
    reg = wm.ws_registration("e2e-ann", "who")

    async def go() -> Dict[str, Any]:
        manager = McpManager()
        started = await manager.connect_server(
            server_id="relay-e2e", name=reg["name"], transport="stdio",
            command=reg["command"], args=reg["args"], env=reg["env"])
        try:
            said = await manager.call_tool("mcp__relay-e2e__who",
                                           {"peek": f"/home/{bob}", "owner": "e2e-bob"})
        finally:
            await manager.disconnect_server("relay-e2e")
        return {"started": started, "status": manager.get_server_status("relay-e2e"), "said": said}

    out = _run(go())
    assert out["started"] is True, out["status"]
    told = json.loads(out["said"]["stdout"])
    assert told["user"] == ann and told["home"] == f"/home/{ann}"
    assert told["uid"] != 0
    assert told["peek"] == "PermissionError"  # bob's home is not ann's to read
    assert told["mcp"] == "absent"
    assert told["secret"] == "absent"
