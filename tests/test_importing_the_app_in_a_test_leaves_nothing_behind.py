# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1180` — a test that imports the app in process gives the process back.

`test_the_halves_are_one_product.py::test_the_two_limits_and_the_waiting_words_have_one_home`
failed after a particular run of other files and passed alone. **Measured
2026-10-03 on `3e4888b`**, bisecting `integrate-g`'s 216-file order: it takes
one file of each kind, in this order —

  1. a file that imports `app` in process (`test_edit_image_routes.py`, or
     `test_mail_arriving_runs_its_workflow_with_nobody_looking.py`; the other
     two app importers in that run boot it out of process and do not leak).
     `app.py`'s body calls `set_mcp_manager(McpManager())`, and nothing put it
     back, so every later file ran with an MCP manager installed;
  2. `test_testing_one_step_runs_nothing_else.py`, whose routes reach
     `workflow_effects._mcp_tools` — which expects no manager in a test — and,
     finding one, read every server's tool overrides on the process's
     `sqlite:///:memory:` engine from each TestClient's portal thread. Past
     five threads SQLAlchemy's `SingletonThreadPool` closes connections, the
     main thread's among them, and the in-memory database that held the
     tables (made by the app's import, on the main thread) went with it;
  3. the case, which reads the global database on the main thread:
     `no such table: mcp_servers`.

Fixed where it leaked: both in-process importers now import the app through
`tests/helpers/fresh_import.import_app_in_this_test`, which drops it for a
fresh import (`drop_for_fresh_import`) and puts back `sys.modules` and the
singletons the app's `set_*` calls install.
"""
import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.fresh_import import APP_INSTALLS, import_app_in_this_test

ROOT = Path(__file__).resolve().parent.parent
_CASE = ("tests/test_the_halves_are_one_product.py::"
         "test_the_two_limits_and_the_waiting_words_have_one_home")


@pytest.mark.parametrize("importer", [
    "tests/test_edit_image_routes.py",
    "tests/test_mail_arriving_runs_its_workflow_with_nobody_looking.py",
])
def test_the_order_that_failed_passes(importer):
    """The row's `Verify:`. On `3e4888b` each order failed the case with
    `no such table: mcp_servers` (1 failed, 27 passed for the first)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider",
         importer, "tests/test_testing_one_step_runs_nothing_else.py", _CASE],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-4000:]
    assert "FAILED" not in proc.stdout, proc.stdout[-4000:]


def _installed():
    return {(m, n): getattr(importlib.import_module(m), n)
            for pairs in APP_INSTALLS.values() for m, n in pairs}


def test_the_helper_gives_back_what_the_import_installed():
    """Inside the test the app is imported and its MCP manager is the one
    installed; after it, every global it installed and `sys.modules` are what
    they were."""
    from src.tool_utils import get_mcp_manager
    before, had_app = _installed(), sys.modules.get("app")
    with pytest.MonkeyPatch.context() as mp:
        app_module = import_app_in_this_test(mp)
        assert get_mcp_manager() is app_module.mcp_manager
        assert sys.modules["app"] is app_module
    assert _installed() == before
    assert sys.modules.get("app") is had_app


def _module_level_setters(path: Path) -> set:
    """The names of the `set_*` functions a module calls in its own body."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.value.func.id for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id.lstrip("_").startswith("set_")}


def test_every_setter_the_app_calls_is_one_the_helper_puts_back():
    """`APP_INSTALLS` names what each of `app.py`'s module-level `set_*` calls
    installs. A new one there is a new global left behind until it is named."""
    assert _module_level_setters(ROOT / "app.py") == set(APP_INSTALLS)


def test_no_test_imports_the_app_in_process_but_through_the_helper():
    """A third file with a plain `import app` would leak again. Import
    statements only — a probe that boots the app out of process carries
    `import app` in a string, which is not an import here."""
    plain = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "app" for a in node.names):
                plain.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module == "app" and not node.level:
                plain.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert plain == [], plain
