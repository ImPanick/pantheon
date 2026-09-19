# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-42` — an empty env dict asked the SDK for a *minimal* environment.

MEASURED ON THE TREE BEFORE THE CHANGE. `src/mcp_manager.py:285` read

    env={**os.environ, **env} if env else None,

and `None` is not "no overrides" to the MCP SDK. `StdioServerParameters.env is
None` makes `stdio_client` call `get_default_environment()`, which inherits
exactly `DEFAULT_INHERITED_ENV_VARS`. On this machine that list is

    ['HOME', 'LOGNAME', 'PATH', 'SHELL', 'TERM', 'USER']

— six names. `PATH` and `HOME` are in it, which is why the premise was
corrected once already: the failure is *not* "the server cannot find python".
What is missing is `PYTHONPATH`, `NODE_PATH`, `NPM_CONFIG_CACHE` and every
proxy variable, and only when the env dict is empty, which is the default the
form produces. So the server starts, and then cannot import its own package or
cannot reach the network from behind a corporate proxy — while the same server
with one unrelated variable set works, because one entry made the dict truthy.

This file spawns a REAL MCP server over the REAL stdio transport and asks it
what environment it got (`Law 20`). Nothing here reads the source.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_manager import McpManager  # noqa: E402

pytest.importorskip("mcp.server.fastmcp")

# The four names this row is about, plus one arbitrary sentinel to show the
# rule is about inheritance and not about a hard-coded allowlist of our own.
_PROBED = ("PYTHONPATH", "HTTPS_PROXY", "NO_PROXY", "NPM_CONFIG_CACHE",
           "PANTHEON_ENV_PROBE_SENTINEL", "PATH", "HOME")

_SERVER = '''
import json, os
from mcp.server.fastmcp import FastMCP

app = FastMCP("env-probe")


@app.tool()
def env_report() -> str:
    """Report the environment this subprocess was started with."""
    return json.dumps({k: os.environ.get(k) for k in %r})


if __name__ == "__main__":
    app.run()
''' % (list(_PROBED),)


def _probe(manager: McpManager, script: Path, env):
    async def run():
        ok = await manager.connect_server(
            server_id="envprobe",
            name="Env probe",
            transport="stdio",
            command=sys.executable,
            args=[str(script)],
            env=env,
        )
        assert ok, manager.get_server_status("envprobe")
        try:
            result = await manager.call_tool("mcp__envprobe__env_report", {}, timeout=30)
        finally:
            await manager.disconnect_server("envprobe")
        return result

    return asyncio.run(run())


@pytest.fixture()
def script(tmp_path):
    path = tmp_path / "env_probe_server.py"
    path.write_text(_SERVER)
    return path


@pytest.fixture()
def parent_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("NPM_CONFIG_CACHE", str(tmp_path / "npm"))
    monkeypatch.setenv("PANTHEON_ENV_PROBE_SENTINEL", "carried")
    return None


def test_the_sdk_default_really_does_drop_these(parent_env):
    """The trap, stated as a fact about the SDK rather than a claim about us.

    If this ever fails the row's premise has expired and the fix below is
    unnecessary — which is worth knowing loudly.
    """
    from mcp.client.stdio import DEFAULT_INHERITED_ENV_VARS, get_default_environment

    minimal = get_default_environment()
    for name in ("PYTHONPATH", "HTTPS_PROXY", "NO_PROXY", "NPM_CONFIG_CACHE",
                 "PANTHEON_ENV_PROBE_SENTINEL"):
        assert name not in DEFAULT_INHERITED_ENV_VARS
        assert name not in minimal, f"{name} unexpectedly survives the SDK default"


@pytest.mark.parametrize("empty", [{}, None])
def test_an_empty_env_inherits_pythonpath_and_the_proxy(script, parent_env, empty):
    """The row's `Verify:`, driven end to end against a real subprocess."""
    result = _probe(McpManager(), script, empty)
    assert result["exit_code"] == 0, result
    got = json.loads(result["stdout"])

    assert got["PYTHONPATH"] == os.environ["PYTHONPATH"]
    assert got["HTTPS_PROXY"] == "http://proxy.corp.invalid:8080"
    assert got["NO_PROXY"] == "localhost,127.0.0.1"
    assert got["NPM_CONFIG_CACHE"] == os.environ["NPM_CONFIG_CACHE"]
    assert got["PANTHEON_ENV_PROBE_SENTINEL"] == "carried"
    # The two that were never the casualties still arrive, so the fix did not
    # trade one half of the environment for the other.
    assert got["PATH"] == os.environ["PATH"]
    assert got["HOME"] == os.environ["HOME"]


def test_one_unrelated_variable_no_longer_changes_the_answer(script, parent_env):
    """The tell that made this so hard to diagnose.

    Before, a server with `{"ANYTHING": "1"}` inherited everything and the same
    server with `{}` inherited six names. The two now agree.
    """
    with_one = json.loads(_probe(McpManager(), script, {"ANYTHING": "1"})["stdout"])
    with_none = json.loads(_probe(McpManager(), script, {})["stdout"])
    with_one.pop("ANYTHING", None)
    assert with_one == with_none


def test_an_explicit_override_still_wins(script, parent_env):
    """Overrides were never broken and must not become broken."""
    out = json.loads(_probe(McpManager(), script, {"PYTHONPATH": "/only/this"})["stdout"])
    assert out["PYTHONPATH"] == "/only/this"
    assert out["HTTPS_PROXY"] == "http://proxy.corp.invalid:8080"
