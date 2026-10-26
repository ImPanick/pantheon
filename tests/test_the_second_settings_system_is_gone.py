# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B550` — `src/config.py`'s second settings system is gone, on its audit.

The row's `Verify:` is "either something outside `src/config.py` reads each
declared field, or each unread field is removed with the audit that proved it
dead recorded on this row — and an AST recount of `config.<section>` attribute
reads across non-test Python returns the same seven sites, all inside
`src/config.py`". The recount was run before the removal (7 sites, all inside
the file — the audit is written into `src/config.py`'s header); this file keeps
asking the question so a second settings system cannot quietly come back:

  * no tracked non-test Python reads `config.data|llm|search|security`;
  * `src/config.py` binds no environment prefix (`BaseSettings` is gone), so a
    malformed `LLM_REQUEST_TIMEOUT` no longer stops the app importing it —
    driven in a subprocess with exactly that variable set;
  * the module still does the one thing that ran: the data directories exist
    after it is imported;
  * `setup_search_routes` takes no `config` it never read.
"""
import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SECTIONS = {"data", "llm", "search", "security"}


def _tracked_python():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
    return [p for p in out if not p.startswith("tests/") and "/tests/" not in p]


def test_no_python_reads_a_config_section():
    sites = []
    for rel in _tracked_python():
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in _SECTIONS
                    and isinstance(node.value, ast.Name) and node.value.id == "config"):
                sites.append(f"{rel}:{node.lineno} config.{node.attr}")
    assert sites == []


def test_the_module_binds_no_environment_prefix():
    tree = ast.parse((ROOT / "src" / "config.py").read_text(encoding="utf-8"))
    bases = [ast.unparse(b) for n in ast.walk(tree) if isinstance(n, ast.ClassDef) for b in n.bases]
    assert "BaseSettings" not in bases
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert "SettingsConfigDict" not in calls


def test_a_malformed_prefixed_variable_no_longer_stops_the_import(tmp_path):
    """Before `B550`, `LLMConfig` validated `LLM_REQUEST_TIMEOUT` as an int at
    import, so a value nothing read failed the boot."""
    env = {**os.environ, "LLM_REQUEST_TIMEOUT": "thirty seconds",
           "DATA_MAX_UPLOAD_SIZE": "ten megabytes", "PANTHEON_DATA_DIR": str(tmp_path / "data"),
           "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-c", "import src.config"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    # And what did run still runs: the directories it has always made.
    for sub in ("", "uploads", "personal_docs", os.path.join("personal_docs", "runbook")):
        assert (tmp_path / "data" / sub).is_dir(), sub


def test_the_search_routes_take_no_config_they_never_read():
    from routes.search.search_routes import setup_search_routes
    assert list(inspect.signature(setup_search_routes).parameters) == []
