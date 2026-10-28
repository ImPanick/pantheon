# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1633` — two files that failed after other files in one process pass
after them.

Both failed in the full run on `baec0e3` and passed alone. Each was bisected
on `d1302586` with a probe plugin that records, at every collected file and
every finished test, which tool-stack modules changed identity in
`sys.modules` and whether the MCP singleton (`tool_utils._mcp_manager`, and
what `agent_tools` / `tool_execution.get_mcp_manager` answer) had appeared.

**The hired-run file.** All three cases of
`test_a_hired_run_with_no_document_in_hand_writes_nothing.py` failed with
their spy never called. Two files did it, at collection —
`test_function_call_non_object_args.py` and `test_unknown_tool_calls.py`. Each
popped `src.agent_tools`, `src.tool_parsing` and `src.tool_schemas`, imported
them again by hand and left the second copies in `sys.modules` (and as the
`src` package's attributes) for the rest of the session. The hired-run file,
collected before them, had bound the first `src.agent_tools` and patched its
`TOOL_HANDLERS`; the dispatcher imports the registry when it runs and read the
second. The hired-run file then either of the two: its 3 cases failed (3
failed, 13 passed with the first; 3 failed, 8 passed with the second).
`B983`'s shape, in two files `B983` did not reach. Fixed where it leaked: both
re-import through `tests/helpers/fresh_import.reimported_under_stubs`, which
gives `sys.modules` and the package attributes back as it found them.

**The retrieval-index file.** `test_without_rag_the_tool_answers_as_before`
was answered *"MCP server id rag is not connected"*: an `McpManager` was
installed. Collecting every file of the run changed nothing; running the 273
files that mention MCP, the app or `tool_utils` in 40-file batches changed
nothing; running the other 1,374 in 60-file batches, the singleton appeared
after `test_cleanup_panel.py::test_both_routes_are_actually_mounted`. It loads
`.pantheon/check-unreachable.py` and calls `app_routes()`, whose first line is
`import app` — in this process — and `app.py`'s body calls
`set_mcp_manager(McpManager())`. `B1180`'s leak, through a door its AST guard
(`test_importing_the_app_in_a_test_leaves_nothing_behind.py`, which reads
`tests/` for `import app`) cannot see. `test_embeddings_panel.py` calls
`app_routes()` the same way. Either file then the retrieval-index file: the
case fails (1 failed, 14 passed; 1 failed, 24 passed). Fixed where it leaked:
both import the app first through `import_app_in_this_test`, so the
checker's `import app` finds that one and the test gives it back; and the
per-file isolation sweep in `tests/conftest.py` now names a file that leaves
the app imported, so a third door is reported by the run that went through it.
"""
import importlib
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import conftest as suite_conftest

ROOT = Path(__file__).resolve().parent.parent
HIRED = "tests/test_a_hired_run_with_no_document_in_hand_writes_nothing.py"
REIMPORTERS = ("tests/test_function_call_non_object_args.py", "tests/test_unknown_tool_calls.py")
TOOL_STACK = ("src.agent_tools", "src.tool_parsing", "src.tool_schemas")
INDEX = "tests/test_the_eval_world_answers_a_retrieval_index.py"
CHECKER_CALLERS = ("tests/test_cleanup_panel.py", "tests/test_embeddings_panel.py")


def _pytest(tmp_path, *files):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--basetemp={tmp_path / 'bt'}", *files],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600)


# ── the hired-run file ──────────────────────────────────────────────────────


@pytest.mark.parametrize("reimporter", REIMPORTERS)
def test_the_hired_run_passes_with_a_reimporting_file_after_it(reimporter, tmp_path):
    """The row's `Verify:` for the first file, in the order that failed."""
    proc = _pytest(tmp_path, HIRED, reimporter)
    assert proc.returncode == 0, proc.stdout[-4000:]


@pytest.mark.parametrize("reimporter", REIMPORTERS)
def test_a_reimporting_file_gives_the_tool_stack_back(reimporter):
    """Held before — as a file collected earlier holds them — the three modules
    are the same objects after the file's body runs: by name, by import, and as
    the package's attribute."""
    held = {name: importlib.import_module(name) for name in TOOL_STACK}
    spec = importlib.util.spec_from_file_location(f"b1633_{Path(reimporter).stem}", ROOT / reimporter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, original in held.items():
        parent, _, child = name.rpartition(".")
        assert sys.modules.get(name) is original, f"{reimporter} left a second {name} in sys.modules"
        assert importlib.import_module(name) is original, f"{name}: import"
        assert getattr(sys.modules[parent], child) is original, f"{reimporter} left {parent}.{child} rebound"


# ── the retrieval-index file ────────────────────────────────────────────────


@pytest.mark.parametrize("caller", CHECKER_CALLERS)
def test_the_retrieval_index_passes_with_a_checker_caller_before_it(caller, tmp_path):
    """The row's `Verify:` for the second file, in the order that failed."""
    proc = _pytest(tmp_path, caller, INDEX)
    assert proc.returncode == 0, proc.stdout[-4000:]


def test_a_file_that_leaves_the_app_imported_is_named(monkeypatch):
    """The sweep at each file boundary names the file after which the app is
    imported — once, and not a module of another name or another file."""
    monkeypatch.setattr(suite_conftest, "_isolation",
                        {"file": None, "seen": set(), "leaks": {}, "on": True, "scans": 0})
    elsewhere = types.ModuleType("app")
    elsewhere.__file__ = str(ROOT / "tests" / "fixtures" / "app.py")
    monkeypatch.setitem(sys.modules, "app", elsewhere)
    suite_conftest._isolation_sweep("tests/a_file_with_its_own_app.py")
    assert suite_conftest._isolation["leaks"] == {}

    ours = types.ModuleType("app")
    ours.__file__ = str(ROOT / "app.py")
    monkeypatch.setitem(sys.modules, "app", ours)
    suite_conftest._isolation_sweep("tests/the_file_that_imported_it.py")
    suite_conftest._isolation_sweep("tests/a_later_file.py")
    leaks = suite_conftest._isolation["leaks"]
    assert list(leaks) == ["tests/the_file_that_imported_it.py"], leaks
    (entry,) = leaks["tests/the_file_that_imported_it.py"]
    assert entry.startswith("app (") and "import_app_in_this_test" in entry, entry
