# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B131` — two MCP servers stopped starting, and nothing in this suite could see it.

`B74` gave `rag_server.py` and `email_server.py` a
`from src.tool_schemas import mcp_tool_schema` as their first `src` import.
`src/tool_schemas.py` imports `src.agent_tools` at its top, and
`src/agent_tools/__init__.py:164` imports `FUNCTION_TOOL_SCHEMAS` back out of
`src.tool_schemas` — a cycle that resolves only if `agent_tools` is imported
first. So both servers died at import with

    ImportError: cannot import name 'FUNCTION_TOOL_SCHEMAS' from partially
    initialized module 'src.tool_schemas'

and `builtin_mcp.py` logged *"Built-in MCP server failed to connect"* and
carried on. **Eleven email tools and RAG were down from the moment `B74` landed
until it was found on a deployment, five pushes later.**

**Why the whole suite was blind, which is the finding worth keeping.** These
servers are spawned as *fresh interpreters* by `builtin_mcp.py`. Every test, and
`.pantheon/check-mcp-schemas.py`, imports them into a process where
`src.agent_tools` is **already loaded** — `tests/conftest.py` pre-imports it,
and that pre-import is `B18`'s own fix. One defect's remedy hid another's
symptom. `check-mcp-schemas.py` calling `list_tools()` proved the schemas were
right and could not notice the module never loaded in the one process that
matters.

So this test does the only thing that shows it: a subprocess with nothing
pre-imported, importing the server the way the app spawns it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Every server `src/builtin_mcp.py` spawns, plus `memory_server`, which it no
# longer spawns (`B67`) but which is still supported standalone and carries the
# same import.
SERVERS = ("rag_server", "email_server", "image_gen_server", "memory_server")


def _import_in_fresh_process(module: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '.'); import mcp_servers.{module}"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )


@pytest.mark.parametrize("module", SERVERS)
def test_the_server_imports_in_a_process_that_has_imported_nothing_else(module):
    """The exact condition `builtin_mcp.py` spawns them under."""
    result = _import_in_fresh_process(module)
    assert result.returncode == 0, (
        f"mcp_servers/{module}.py cannot be imported on its own — "
        f"`builtin_mcp.py` spawns it exactly this way and would log "
        f"'failed to connect' and carry on:\n{result.stderr[-3000:]}"
    )


@pytest.mark.parametrize("module", SERVERS)
def test_the_server_serves_its_tools_in_a_fresh_process(module):
    """Importing is not enough: the schema derivation `B74` added runs inside
    `list_tools()`, so the cycle could also bite there."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, asyncio, json; sys.path.insert(0, '.')\n"
         f"import mcp_servers.{module} as M\n"
         "print(json.dumps([t.name for t in asyncio.run(M.list_tools())]))"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    import json
    names = json.loads(result.stdout.strip().splitlines()[-1])
    assert names, f"{module} served no tools"


def test_the_import_order_guard_is_what_makes_that_work():
    """Pins the mechanism so nobody tidies the guard away as a stray import.

    Read as code with comments stripped (`Law 20` — the long comment above each
    guard names `src.agent_tools` many times, and a substring search would pass
    on the explanation alone).
    """
    import re

    for module in ("rag_server", "email_server", "memory_server"):
        source = (ROOT / "mcp_servers" / f"{module}.py").read_text(encoding="utf-8")
        code = re.sub(r"(?m)^\s*#.*$", "", source)
        agent_tools = code.index("import src.agent_tools")
        tool_schemas = code.index("from src.tool_schemas import")
        assert agent_tools < tool_schemas, (
            f"{module}: `src.tool_schemas` is imported before `src.agent_tools`, "
            f"which is the cycle `B131` is about"
        )
