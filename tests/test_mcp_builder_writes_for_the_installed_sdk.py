# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1628` — MCP Builder writes its server for the MCP SDK that is installed,
so with mcp 2.x it passes its first test run.

Measured before the fix: step 1 of its runbook wrote a FastMCP server
(`from mcp.server.fastmcp import FastMCP`) before anything looked at the SDK.
`pip install mcp` has installed 2.x since 2026-07-28, and 2.x refuses that
import outright — `mcp/server/fastmcp.py` is a stub that raises
"No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was
renamed to MCPServer…". So every build on a current install spent one of its
two fixes recovering, and the evaluation set covered an SDK too old for
FastMCP but none too new. (A plain `ValueError` in a 2.x tool also reaches
the model as only "Error executing tool <name>": the sentence needs
`ToolError`.)

Now the runbook reads the installed version first and writes for it —
`MCPServer` on 2.x, `FastMCP` on 1.2 to 1.x, the version's README below that —
and its evaluation set's first case is a 2.x install that passes on the first
test. This file runs that case's own two files against the SDK this install
pins (`requirements.txt`, mcp 2.3.0), for real: the server over stdio, each
tool called once, in a fresh process each.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent

INSTALLED = importlib.metadata.version("mcp")


def _case_files(case_id: str):
    """What the case's model wrote: path → content, from its script."""
    cases = {c["id"]: c for c in E.load_evals(get_agent(None, "mcp-builder"))}
    out = {}
    for step in cases[case_id]["script"]:
        for tool, args in step.get("call", []):
            if tool == "write_file":
                out[os.path.basename(args["path"])] = args["content"]
    return cases[case_id], out


def _run_test(tmp_path, files) -> subprocess.CompletedProcess:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return subprocess.run([sys.executable, "test_server.py"], cwd=str(tmp_path), capture_output=True,
                          text=True, timeout=120)


def test_this_install_is_on_mcp_2():
    assert INSTALLED.split(".")[0] == "2", INSTALLED


def test_the_2x_case_passes_its_first_test_against_the_installed_sdk(tmp_path):
    case, files = _case_files("an-mcp-2-server-passes-its-first-test")
    world_version = next(r["output"] for r in case["world"]["shell"] if r["match"] == "importlib.metadata")
    assert world_version.startswith("mcp 2."), "the case is an mcp 2.x install"
    assert "from mcp.server.mcpserver import MCPServer" in files["server.py"]
    done = _run_test(tmp_path, files)
    assert done.returncode == 0, done.stderr[-2000:]
    lines = [ln for ln in done.stdout.splitlines() if ln.split(" ", 1)[0] in ("get_forecast", "list_places")]
    assert [ln.split(" ", 1)[0] for ln in lines] == ["get_forecast", "list_places"]
    assert all("is_error=False" in ln for ln in lines), done.stdout
    assert "rain, 11°C" in lines[0] and "'Leeds'" in lines[1] and "'York'" in lines[1]


def test_its_tool_error_reaches_the_model_as_its_sentence(tmp_path):
    """The 2.x way to fail with words: `ToolError`'s sentence arrives; a
    plain exception would arrive as only "Error executing tool …"."""
    _case, files = _case_files("an-mcp-2-server-passes-its-first-test")
    files["test_server.py"] = files["test_server.py"].replace(
        'print("list_places", await s.call_tool("list_places", {}))',
        'print("paris", await s.call_tool("get_forecast", {"place": "Paris"}))')
    done = _run_test(tmp_path, files)
    paris = next(ln for ln in done.stdout.splitlines() if ln.startswith("paris "))
    assert "is_error=True" in paris and "Paris is not a saved place." in paris


def test_the_fastmcp_server_the_old_step_wrote_is_refused_by_2x(tmp_path):
    """Why the version is read first: the 1.x server, on this install, dies
    at import — the recovery every build spent a fix on."""
    _case, files = _case_files("an-mcp-1-server-is-a-fastmcp-one")
    assert "from mcp.server.fastmcp import FastMCP" in files["server.py"]
    (tmp_path / "server.py").write_text(files["server.py"], encoding="utf-8")
    done = subprocess.run([sys.executable, "server.py"], cwd=str(tmp_path), capture_output=True, text=True,
                          timeout=60, stdin=subprocess.DEVNULL)
    assert done.returncode != 0
    assert "No module named 'mcp.server.fastmcp'" in done.stderr and "MCPServer" in done.stderr


@pytest.mark.parametrize("case_id,version", [("an-mcp-2-server-passes-its-first-test", "mcp 2.3.0"),
                                             ("an-mcp-1-server-is-a-fastmcp-one", "mcp 1.9.4")])
def test_each_case_reads_the_version_before_it_writes(case_id, version):
    """The order the runbook gives: the first call is the version, and no
    server is written before it."""
    case, _files = _case_files(case_id)
    calls = [c for step in case["script"] for c in step.get("call", [])]
    assert calls[0][0] == "bash" and "importlib.metadata" in calls[0][1]["command"]
    assert "test_server.py" not in calls[0][1]["command"]
    assert json.dumps(case["world"]).count(version) >= 1
