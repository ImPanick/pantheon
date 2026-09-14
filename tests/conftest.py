# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared test configuration - ensure project root is on sys.path and stub heavy deps."""
import sys
import os
import types
import importlib.util
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing core.database below runs init_db() at import time, and its default
# (sqlite:///./data/app.db) can't be opened in a clean worktree because SQLite
# won't create the missing ./data parent dir - pytest then dies during
# collection, before any test module loads. Default to an in-memory DB for the
# test session so collection is deterministic and writes no repo-local
# artifacts. An explicit DATABASE_URL (a real test/CI database) is preserved.
# This only unblocks collection/import-time init; it does not provide a shared
# file-backed DB across processes - tests needing that must set DATABASE_URL.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Pre-import real heavy modules BEFORE any test file's module-level stubs can
# replace them with MagicMock. Some test files (e.g. test_llm_core_sanitize_*)
# stub sqlalchemy/core.database at module scope with `if mod not in sys.modules`,
# which fires during collection. If the real module hasn't been imported yet,
# the stub wins and contaminates every subsequent test that needs the real ORM.
#
# `src.agent_tools` is here because of `B18`, and it is the one name in every
# stub list that this block never carried. Six files stub it at module scope
# (`test_tool_output_prompt_injection.py:34`, `test_prompt_injection_audit.py:30`,
# `test_skill_index_prompt_injection.py:38`, `test_llm_core_sanitize_tool_calls.py:29`,
# `test_sanitize_preserves_reasoning.py:19`, `test_llm_core_reasoning_content_fallback.py:109`),
# and a `MagicMock` there is not one broken import — `src/agent_loop.py:64-76`,
# `src/tool_parsing.py:16` and `src/tool_schemas.py:17` bind `TOOL_TAGS`,
# `ToolBlock` and `parse_tool_blocks` BY VALUE at import, so the mock is baked
# into three more modules permanently. The full suite never saw it because
# `tests/test_a_refused_call_leaves_a_trace.py` sorts first in root collection
# order and imports the real module, which makes every `if mod not in
# sys.modules` guard downstream dead code. Any subset run — a shard, a `-k`,
# a `--lf`, a file list — re-arms all six. A subset of the six affected files
# did not merely fail: `parse_tool_blocks` as a mock never satisfies the agent
# loop's exit condition, so twelve tests ran to the lifted 100,000-round cap
# and the process was OOM-killed at 6 GB.
try:
    import sqlalchemy  # noqa: F401
    import sqlalchemy.orm  # noqa: F401
    import core.database  # noqa: F401
    import src.database
    import src.agent_tools  # noqa: F401  — B18
except ImportError:
    pass  # not installed - the stubs below will handle it

def _has_module(mod_name: str) -> bool:
    try:
        return importlib.util.find_spec(mod_name) is not None
    except (ImportError, ValueError):
        return False


# Stub optional dependencies only when they are not installed. Do not replace
# real FastAPI/Starlette/Pydantic modules: route tests import their subpackages.
for mod_name in [
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.types", "sqlalchemy.ext", "sqlalchemy.ext.declarative",
    "sqlalchemy.ext.hybrid", "sqlalchemy.sql", "sqlalchemy.sql.expression",
    "sqlalchemy.sql.sqltypes", "bcrypt", "pyotp",
    "httpx", "fastapi", "fastapi.responses", "fastapi.routing",
    "starlette", "starlette.responses", "starlette.middleware", "starlette.middleware.base",
    "pydantic",
]:
    if mod_name not in sys.modules and not _has_module(mod_name):
        sys.modules[mod_name] = MagicMock()

if "src.database" not in sys.modules:
    _db = types.ModuleType("src.database")
    _db.SessionLocal = MagicMock()
    _db.ModelEndpoint = MagicMock()
    sys.modules["src.database"] = _db

# Pre-import core.models before test_agent_loop.py's module-level stubs
# run (it replaces sys.modules['core.models'] with a MagicMock during
# collection, which breaks session import in subsequent tests).
import core.models  # noqa: E402

def pytest_configure(config):
    """Register the dynamic taxonomy ``sub_*`` markers before collection.

    The stable ``area_*`` markers are declared in ``pyproject.toml``. The
    per-file ``sub_*`` markers are derived from the test filenames here so that
    unknown-mark warnings still surface genuine typos outside the taxonomy. This
    only registers marker names; it imports no production module.
    """
    import pathlib
    from tests._taxonomy import discover_markers

    tests_dir = pathlib.Path(__file__).parent
    paths = list(tests_dir.rglob("test_*.py")) + list(tests_dir.rglob("*_test.py"))
    for marker_name in discover_markers(paths):
        if marker_name.startswith("sub_"):
            config.addinivalue_line("markers", f"{marker_name}: taxonomy sub-area marker")


def pytest_collection_modifyitems(config, items):
    """Tag each collected test with its taxonomy ``area_*`` and ``sub_*`` markers.

    Collection-time only: this adds markers and nothing else. It does not skip,
    reorder, or deselect tests, mutate fixtures or the environment, or import any
    production module. See ``tests/_taxonomy.py`` for the classification rules.
    """
    import pytest
    from tests._taxonomy import markers_for_path

    for item in items:
        path = getattr(item, "path", None) or item.fspath
        for marker_name in markers_for_path(path):
            item.add_marker(getattr(pytest.mark, marker_name))


# ---------------------------------------------------------------------------
# Outbound limiter isolation
# ---------------------------------------------------------------------------
# `src.rate_limiter.outbound` is a single process-wide limiter, deliberately —
# politeness belongs to the destination host, not to the feature calling it, so
# two features must not each get their own allowance. That makes it shared
# mutable state across the whole suite: a test that drives a host into cooldown
# would leave every later test talking to that host raising OutboundRateLimited,
# and it would fail only in a full sweep, never alone. This project has already
# lost an afternoon to exactly that shape once (see test_trust_rung_gate.py).
#
# Pacing itself is left ON. Zeroing the interval here would make the tests that
# exist to prove pacing works pass without proving anything.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_outbound_limiter(tmp_path):
    """Reset the shared limiter, and give it a throwaway state file.

    `P15-09` made cooldowns survive a restart, which means `reset()` and every
    penalty now WRITE. Without this redirect the suite would drop thousands of
    writes into the developer's real data directory, and — worse — a stale file
    from a previous run would restore a cooldown into an unrelated test, giving
    exactly the cross-test coupling the reset above exists to prevent.

    The private flags are cleared too: `reset()` sets `_loaded` on purpose, so
    that clearing a cooldown is not immediately undone by a reload, and a test
    of the loader needs to start from a limiter that has not loaded yet.
    """
    try:
        from src.rate_limiter import outbound
        from src import constants as _constants
    except Exception:
        yield
        return

    original = getattr(_constants, "OUTBOUND_STATE_FILE", None)
    # In a SUBDIRECTORY: `tmp_path` is the test's own working directory, and a
    # file dropped at its root breaks every test that globs or indexes it.
    _constants.OUTBOUND_STATE_FILE = str(tmp_path / "_limiter_state" / "outbound_state.json")

    def _clear():
        outbound.reset()
        outbound._loaded = False
        outbound._last_written = None

    _clear()
    try:
        yield
    finally:
        _clear()
        if original is not None:
            _constants.OUTBOUND_STATE_FILE = original


@_pytest.fixture(autouse=True)
def _reset_run_context():
    """Clear the per-turn ContextVars between tests (`P4-25`, `P14-02`).

    `mark_turn_start()` sets a run id and a clock and is deliberately
    idempotent within a turn — the first call wins, so a retry inside one
    request neither restarts the clock nor splits the receipt. That is correct
    in production and a trap in a test suite: pytest runs everything in one
    context, so a test that marks a turn leaves the next module's tests inside
    it.

    It cost one cross-module failure to find. `test_duration_is_null_and_that_is
    _honest` asserts a round has no duration when nobody started a clock, and it
    went red only when a diagnostic-bundle test that seeds a run happened to
    sort before it. Fixing it in the one offending helper would have left the
    trap armed for the next person; this is the level that closes it.
    """
    try:
        from src import events as _ev
    except Exception:
        yield
        return

    def _clear():
        for var in ("_turn_started", "_run_id"):
            holder = getattr(_ev, var, None)
            if holder is not None:
                holder.set(None)
        try:
            from src import llm_core as _lc
            _lc._run_config_recorded.set(False)
            # `P17-08` added the second half of the latch. Resetting one and
            # not the other leaves a test's first tools-bearing capture looking
            # like the previous test's upgrade, already spent.
            _lc._run_config_had_tools.set(False)
        except Exception:
            pass

    _clear()
    try:
        yield
    finally:
        _clear()


# `B18`. The pre-import above defuses the six stubs that exist today; this
# stops the seventh from being silent. A stub installed at module scope lands
# during COLLECTION, before the first test runs, so by the time anything fails
# the cause is several files away and the symptom is a `TypeError` about a
# `MagicMock` — or, for twelve tests in `test_external_context_tool_gate.py`,
# a 6 GB OOM kill rather than a failure at all.
#
# The check is cheap and it is a real observation, not a grep: a stub has no
# `__file__`. It passes today because collection ends with every one of these
# names bound to a real module; if that stops being true the session stops
# with a sentence naming the module, instead of a mystery in whichever shard
# happened to run without `test_a_refused_call_leaves_a_trace.py`.
_MUST_BE_REAL_AFTER_COLLECTION = (
    "src.agent_tools",
    "src.tool_parsing",
    "src.tool_schemas",
    "core.models",
    "core.database",
    "src.database",
)


def pytest_collection_finish(session):
    import pytest

    stubbed = [
        name
        for name in _MUST_BE_REAL_AFTER_COLLECTION
        if (mod := sys.modules.get(name)) is not None
        and getattr(mod, "__file__", None) is None
    ]
    if stubbed:
        raise pytest.UsageError(
            "B18: "
            + ", ".join(stubbed)
            + " is a stub after collection. A test module replaced it in "
            "sys.modules at module scope and nothing put the real one back — "
            "add it to the pre-import block at the top of tests/conftest.py."
        )
