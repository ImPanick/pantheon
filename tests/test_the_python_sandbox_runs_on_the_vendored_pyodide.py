# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2215` — a person's Python block runs on the vendored Pyodide, driven.

Pyodide moved 0.27.5 -> 314.0.8 on 2026-11-24 (`D-2026-11-24-04`). Two changes
sit under Pantheon's runner and neither shows up as a file that changed:

  * `enableRunUntilComplete` is on by default from 0.27.7. Measured with the
    sandbox's own wrapper, 0.27.5 answered `loop.run_until_complete(f())` by
    printing a *pending Task* as though it were the result. 314.0.8 runs it
    where the runtime has JS Promise Integration and otherwise raises
    `RuntimeError: WebAssembly stack switching not supported`, which the wrapper
    prints as the block's traceback. Both are driven here: plain Node 22 is the
    "no stack switching" case, `--experimental-wasm-jspi` the other.
  * the runtime's JavaScript is `pyodide.asm.mjs`, which `pyodide.js` loads
    with `import()`. From the opaque-origin sandbox frame that is a CORS module
    load, so the vendored directory's `Access-Control-Allow-Origin: *` and a
    JavaScript `Content-Type` for `.mjs` are now load-bearing, and pinned.

**Not covered:** a browser. The harness takes Node's branch of `pyodide.js`;
the page's Worker takes the browser's.
"""
import ast
import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.middleware import SecurityHeadersMiddleware

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness" / "python_sandbox_pyodide.mjs"
LOCK = ROOT / "static" / "lib" / "pyodide" / "pyodide-lock.json"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _drive(*flags: str) -> dict:
    proc = subprocess.run(["node", *flags, str(HARNESS)], cwd=ROOT,
                          capture_output=True, text=True, timeout=240)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, f"exit={proc.returncode}\n{proc.stdout[-600:]}\n{proc.stderr[-600:]}"
    out = json.loads(lines[-1])
    assert out["ok"], out
    return out


@pytest.fixture(scope="module")
def plain():
    return _drive()


@pytest.fixture(scope="module")
def jspi():
    return _drive("--experimental-wasm-jspi")


@needs_node
def test_a_block_prints_and_an_error_is_its_traceback(plain):
    runs = plain["runs"]
    assert runs["hello"] == {"stdout": "hi 2\n", "stderr": ""}, runs["hello"]
    assert "threw" not in runs["error"], runs["error"]
    assert "ValueError: boom" in runs["error"]["stderr"], runs["error"]


@needs_node
def test_the_python_is_the_one_the_lock_file_names(plain):
    want = json.loads(LOCK.read_text(encoding="utf-8"))["info"]["python"]
    assert plain["runs"]["version"]["stdout"].strip() == want


@needs_node
def test_the_sandbox_says_run_until_complete_itself(plain):
    assert plain["options"].get("enableRunUntilComplete") is True, plain["options"]


@needs_node
def test_without_stack_switching_run_until_complete_says_so(plain):
    """Fails on 0.27.5: it printed `<PyodideTask pending ...>` as the answer."""
    run = plain["runs"]["runUntilComplete"]
    assert "threw" not in run, run
    assert "PyodideTask" not in run["stdout"], run
    assert "stack switching not supported" in run["stderr"], run


@needs_node
def test_with_stack_switching_run_until_complete_returns(jspi):
    run = jspi["runs"]["runUntilComplete"]
    assert run == {"stdout": "8\n", "stderr": ""}, run


def test_the_module_half_of_the_runtime_is_served_cross_origin():
    """`pyodide.asm.mjs` is fetched by `import()` from an opaque origin."""
    request = SimpleNamespace(
        url=SimpleNamespace(path="/static/lib/pyodide/pyodide.asm.mjs", scheme="http"),
        scope={"type": "http", "path": "/static/lib/pyodide/pyodide.asm.mjs", "root_path": ""},
        headers={}, state=SimpleNamespace(csp_script_hashes=()))
    response = SimpleNamespace(headers={})

    async def call_next(_req):
        return response

    asyncio.run(SecurityHeadersMiddleware(MagicMock()).dispatch(request, call_next))
    assert response.headers.get("Access-Control-Allow-Origin") == "*", response.headers


def test_mjs_is_served_as_javascript():
    """A module script with any other `Content-Type` is refused under `nosniff`."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    pairs = {(c.args[1].value, c.args[0].value) for c in ast.walk(tree)
             if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "add_type"
             and len(c.args) == 2 and all(isinstance(a, ast.Constant) for a in c.args)}
    mjs = {mime for ext, mime in pairs if ext == ".mjs"}
    assert mjs and all(m.endswith("javascript") for m in mjs), pairs
