# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1118` — `import src.tool_schemas` first failed with a circular import.

`src/agent_tools/__init__.py` is a facade: it defines `ToolBlock` and
`TOOL_TAGS`, then re-exported `src.tool_parsing` and `src.tool_schemas` eagerly.
Both of those import `ToolBlock` and `TOOL_TAGS` back out of the facade at their
top. Entered through the facade, that resolves; entered through either module,
the facade's re-export asked a half-built module for a name it had not reached
yet. **Measured on `7a7f9b2`**, each in a fresh interpreter:

    import src.tool_schemas   ImportError: cannot import name 'FUNCTION_TOOL_SCHEMAS'
                              from partially initialized module 'src.tool_schemas'
    import src.tool_parsing   ImportError: cannot import name 'parse_tool_blocks'
                              from partially initialized module 'src.tool_parsing'

The row names the first; the second is the same cause (`email_server.py`'s
`B131` comment: "there is a second cycle through `src.tool_parsing` behind it").
It had already cost an outage (`B131`: two MCP servers would not start) and a
number that moved with import order (`B830`: `known_tool_names()` answered 83
in a cold process and 85 once `src.agent_loop` was loaded — measured on
`7a7f9b2`; it was 82/84 when `B830` was written).

The facade now re-exports those ten names lazily (`__getattr__`), the shape
`src/tool_implementations.py` already uses to break its own facade cycle
(`Law 14`), so nothing in the facade's import reaches back into a module that
may be half-built.

`Law 20`: each case is a fresh interpreter importing in the order under test —
the condition the suite itself cannot see in-process, because `tests/conftest.py`
pre-imports `src.agent_tools` (`B18`), which is exactly the order that worked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Every name the facade re-exports from the two modules, and where it lives.
REEXPORTED = {
    "parse_tool_blocks": "src.tool_parsing",
    "strip_tool_blocks": "src.tool_parsing",
    "_TOOL_NAME_MAP": "src.tool_parsing",
    "_TOOL_BLOCK_RE": "src.tool_parsing",
    "_TOOL_CALL_RE": "src.tool_parsing",
    "_XML_TOOL_CALL_RE": "src.tool_parsing",
    "_XML_INVOKE_RE": "src.tool_parsing",
    "_XML_PARAM_RE": "src.tool_parsing",
    "FUNCTION_TOOL_SCHEMAS": "src.tool_schemas",
    "function_call_to_tool_block": "src.tool_schemas",
}


def _fresh(code: str) -> subprocess.CompletedProcess:
    """`code` in an interpreter that has imported nothing of this project."""
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=180)


def _same_objects_after(first: str) -> dict:
    """Import `first` before anything else, then report, for every re-exported
    name, whether the facade hands out the very object its module holds."""
    code = (
        "import importlib, json, sys\n"
        f"import {first}\n"
        "import src.agent_tools as facade\n"
        f"names = {json.dumps(REEXPORTED)}\n"
        "out = {n: getattr(facade, n) is getattr(importlib.import_module(m), n)\n"
        "       for n, m in names.items()}\n"
        "from src.agent_tools import ToolBlock\n"
        "from src.tool_schemas import function_call_to_tool_block\n"
        "block = function_call_to_tool_block('bash', json.dumps({'command': 'ls'}))\n"
        "out['converts'] = isinstance(block, ToolBlock) and block.tool_type == 'bash'\n"
        "print(json.dumps(out))\n"
    )
    result = _fresh(code)
    assert result.returncode == 0, (
        f"`import {first}` first cannot be imported:\n{result.stderr[-3000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("first", ["src.tool_schemas", "src.tool_parsing", "src.agent_tools"])
def test_either_import_order_works_and_hands_out_one_object(first):
    """The row's `Verify:` — either import order works — for the two modules
    in the cycle and for the facade (the order that always worked, kept). The
    facade's names are the modules' own objects, not copies, whichever came
    first (`Law 7`), and a native call still converts to a `ToolBlock`."""
    same = _same_objects_after(first)
    assert same.pop("converts") is True
    assert same == {name: True for name in REEXPORTED}, same


def test_the_tool_list_does_not_depend_on_what_was_imported_first():
    """`B830`'s symptom, gone with its cause: the tool names Pantheon knows are
    the same in a cold process as once the agent loop is loaded."""
    result = _fresh(
        "import json\n"
        "from src.tool_policy import known_tool_names\n"
        "cold = sorted(known_tool_names())\n"
        "import src.agent_loop  # noqa: F401\n"
        "warm = sorted(known_tool_names())\n"
        "print(json.dumps({'cold': cold, 'warm': warm}))\n"
    )
    assert result.returncode == 0, result.stderr[-3000:]
    lists = json.loads(result.stdout.strip().splitlines()[-1])
    assert lists["cold"] == lists["warm"], sorted(set(lists["warm"]) - set(lists["cold"]))
