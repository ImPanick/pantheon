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

# Stubs THIS FILE installs on purpose, recorded rather than remembered. The
# `B271` sweep below asks "is any production module a stub?" and the honest
# answer has to exclude the ones the suite itself put there when a dependency
# is genuinely absent — otherwise the sweep fails a contributor's machine for
# doing exactly what conftest told it to do.
_DELIBERATE_STUBS: set = set()

if "src.database" not in sys.modules:
    _db = types.ModuleType("src.database")
    _db.SessionLocal = MagicMock()
    _db.ModelEndpoint = MagicMock()
    sys.modules["src.database"] = _db
    _DELIBERATE_STUBS.add("src.database")

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

# `B271`. The six names above are the ones a stub has actually been found in;
# the sweep below is the rule they are instances of. A hand-written list is the
# defect class the guard exists to name (`Law 13`) — its own comment says "add
# it to the pre-import block", which is a list being extended by hand each time
# somebody loses an afternoon. Every loaded module under these package roots is
# production code, and production code is never a stub.
_PRODUCTION_ROOTS = ("src.", "core.", "routes.", "integrations.", "netagent.")


def _module_stubs() -> list:
    """Loaded production modules that are not backed by a file.

    A real module has a `__file__`; a `MagicMock` and a bare `types.ModuleType`
    do not. That is an observation about the loaded object, not a search of
    anybody's source (`Law 20`).
    """
    return sorted(
        name for name, mod in list(sys.modules.items())
        if name.startswith(_PRODUCTION_ROOTS)
        and mod is not None
        and name not in _DELIBERATE_STUBS
        and getattr(mod, "__file__", None) is None
    )


def pytest_collection_finish(session):
    """`B18`'s six abort the session. Everything else the sweep finds is
    reported.

    The distinction is deliberate and it is the reason `B271` could ship at all.
    Those six have each cost a diagnosis — one of them a 6 GB OOM kill — and a
    stub in any of them makes the rest of the run meaningless, so the session
    stops with a sentence naming the module. A seventh module nobody has been
    burned by yet is a different bet: aborting a colleague's 11-minute run for
    it, at collection, before a single test has told them anything, is how a
    guard gets deleted. It is named in the report instead, and
    `--strict-isolation` turns it into a failure for whoever wants one.
    """
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
    others = [n for n in _module_stubs() if n not in stubbed]
    if others:
        _isolation["leaks"].setdefault("collection (module-scope stubs)", []).extend(
            f"{name} (no __file__)" for name in others)
        _isolation["seen"].update(others)


# ---------------------------------------------------------------------------
# `B271` — the two shapes the collection guard above cannot see
# ---------------------------------------------------------------------------
# `B202` found both of them and neither is a module-scope stub.
#
#   * one is a RUN-TIME event: `routes.chat_helpers` is poisoned by a test, long
#     after `pytest_collection_finish` has passed;
#   * one is about ATTRIBUTES, not modules: the poisoned module is the real one,
#     with a real `__file__`, holding four `MagicMock`s bound by value —
#     `maybe_compact`, `trim_for_context`, `load_prefs_for_user` and
#     `effective_user`. So every later test measured the chat privilege gate
#     against a stand-in that answers truthily.
#
# A predicate about `__file__` cannot have an opinion about either. This one is
# about the objects: production code never binds a `Mock`, so a `Mock` reachable
# from a production module's namespace at the end of a test FILE was left there
# by that file.
#
# **It reports and does not fail**, and that is the whole reason it can exist.
# The previous attempt at this row was declined because a check that fails the
# session for one file's behaviour turns the suite red for everybody while the
# owner of that file is elsewhere. A report costs nothing and can be read off
# any run; `--strict-isolation` turns it into a failure for whoever wants it,
# which is the integrator on a full run.
#
# Granularity is the test FILE, not the test: attribution needs a boundary
# where nothing of the next file has run yet, and `pytest_runtest_logstart` for
# the first test of a file is exactly that boundary. Per-test scanning would be
# ~8,600 sweeps instead of ~900 and buys nothing a file name does not already
# tell you.

_isolation = {"file": None, "seen": set(), "leaks": {}, "on": True, "scans": 0,
              "mapped": {}}


def pytest_addoption(parser):
    parser.addoption(
        "--strict-isolation", action="store_true", default=False,
        help="B271: fail the session if a test file leaves a Mock bound into a "
             "production module (reported either way).",
    )
    parser.addoption(
        "--no-isolation-report", action="store_true", default=False,
        help="B271: skip the per-file sweep entirely.",
    )


def _scan_production_namespaces():
    """One pass over production modules; two answers.

    `(mocks, mapped)` — `mocks` is `qualified name -> what it is` for every Mock
    reachable from production, and `mapped` is `qualified name -> id(class)` for
    every SQLAlchemy-mapped class bound there. Both sweeps want the same walk
    over the same dicts, and doing it twice at ~900 file boundaries buys nothing
    (`Law 14`).
    """
    from unittest.mock import NonCallableMock

    mocks = {}
    mapped = {}
    for name, mod in list(sys.modules.items()):
        if not name.startswith(_PRODUCTION_ROOTS) or mod is None:
            continue
        if isinstance(mod, NonCallableMock):
            mocks[name] = "the module itself"
            continue
        namespace = getattr(mod, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for attr, value in list(namespace.items()):
            if isinstance(value, NonCallableMock):
                mocks[f"{name}.{attr}"] = type(value).__name__
            elif isinstance(value, type) and hasattr(value, "__mapper__"):
                mapped[f"{name}.{attr}"] = id(value)
    return mocks, mapped


def _mock_bindings() -> dict:
    """`qualified name -> what it is` for every Mock reachable from production."""
    return _scan_production_namespaces()[0]


# ---------------------------------------------------------------------------
# `B523` — the same leak, wearing a real class
# ---------------------------------------------------------------------------
# The Mock sweep above is a predicate about `unittest.mock`, and the worst
# instance of this defect found so far was not a Mock. A scheduler test built a
# nine-column stand-in for `ScheduledTask` against its own `declarative_base()`
# and assigned it onto `core.database` — a genuine mapped class, invisible to
# the Mock scan, left bound for the remaining 282 files of the session. The
# real model has `schedule`, `cron_expression` and `trigger_type`; the stand-in
# does not, so `tests/test_task_schedule_floor.py` failed in the full suite
# while passing on its own, and the give-away was buried in a `TypeError` about
# a keyword argument.
#
# Substituting a mapped class is never a legitimate thing to leave behind — the
# tables are one thing and the classes that map them are one thing (`Law 13`).
# So this is reported on identity: same qualified name, different object, at a
# file boundary where the file that did it can still be named.


def _isolation_sweep(finished_file):
    if not _isolation["on"] or finished_file is None:
        return
    _isolation["scans"] += 1
    mocks, mapped = _scan_production_namespaces()
    for where, kind in mocks.items():
        if where in _isolation["seen"]:
            continue
        _isolation["seen"].add(where)
        _isolation["leaks"].setdefault(finished_file, []).append(f"{where} ({kind})")
    # `setdefault`, not `[...]`: the sweep owns its own bookkeeping slot, so a
    # caller that hands it a state dict does not have to know about it.
    known = _isolation.setdefault("mapped", {})
    for where, ident in mapped.items():
        was = known.get(where)
        known[where] = ident
        if was is None or was == ident or where in _isolation["seen"]:
            continue
        _isolation["seen"].add(where)
        _isolation["leaks"].setdefault(finished_file, []).append(
            f"{where} (a different mapped class than the one the session started with)")


def pytest_runtest_logstart(nodeid, location):
    path = location[0]
    if _isolation["file"] == path:
        return
    _isolation_sweep(_isolation["file"])
    _isolation["file"] = path


def pytest_sessionstart(session):
    _isolation["on"] = not session.config.getoption("--no-isolation-report")


def pytest_sessionfinish(session, exitstatus):
    _isolation_sweep(_isolation["file"])
    _isolation["file"] = None
    if _isolation["leaks"] and session.config.getoption("--strict-isolation"):
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    leaks = _isolation["leaks"]
    if leaks:
        strict = config.getoption("--strict-isolation")
        terminalreporter.write_sep(
            "=", "B271/B523: stand-ins left bound in production modules",
            red=strict,
            yellow=not strict)
        for where, names in sorted(leaks.items()):
            terminalreporter.write_line(f"{where} left:")
            for name in names:
                terminalreporter.write_line(f"    {name}")
        terminalreporter.write_line(
            "Every later test in this session measured those names against a "
            "stand-in. Use `monkeypatch.setattr`, which undoes itself."
            + ("" if strict else "  (--strict-isolation makes this a failure)"))
    missing = _declared_dependency_gaps()
    if missing:
        terminalreporter.write_sep(
            "=", "B325: this environment does not satisfy requirements.txt",
            yellow=True)
        for line in missing:
            terminalreporter.write_line(f"    {line}")
        terminalreporter.write_line(
            f"{len(missing)} of {_DECLARED_COUNT[0]} declared core dependencies. "
            "Every test that would exercise one of these is skipping, stubbed, "
            "or passing through the import guard written for 'dependency "
            "absent' — a green run is evidence about a smaller product.")


# ---------------------------------------------------------------------------
# `B325` — what a green run did not cover
# ---------------------------------------------------------------------------
# The environment this suite passes in does not satisfy `requirements.txt`, and
# nothing said so. Measured 2026-09-16 in the agent container: six of the 31
# core dependencies are not installed at all and thirteen more are at a version
# other than the pin. So every test that would exercise CalDAV sync, the Chroma
# HTTP client, TOTP QR rendering, YouTube transcripts or a Postgres
# `DATABASE_URL` is skipping, stubbed, or passing because the import guard it
# hits is the one written for "dependency absent".
#
# **Reported, never failed.** A contributor without Postgres must still be able
# to run the suite — that is the whole reason those imports are guarded. What
# was missing is not a gate, it is a sentence at the end of the run telling a
# reader of a green result what it did not cover.

_DECLARED_COUNT = [0]


def _declared_dependency_gaps() -> list:
    import re as _re

    requirements = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "requirements.txt")
    try:
        with open(requirements, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []

    try:
        from importlib.metadata import PackageNotFoundError, version as _version
    except ImportError:  # pragma: no cover - 3.7
        return []

    def _parts(text):
        return tuple(int(p) if p.isdigit() else p
                     for p in _re.split(r"[.\-+]", text) if p != "")

    gaps = []
    declared = 0
    for raw in lines:
        spec = raw.split("#")[0].strip()
        if not spec:
            continue
        declared += 1
        name = _re.split(r"[<>=!~\[;]", spec, 1)[0].strip()
        try:
            have = _version(name)
        except PackageNotFoundError:
            gaps.append(f"{name}: declared {spec.split(name, 1)[-1] or '(any)'}, NOT INSTALLED")
            continue
        except Exception:  # pragma: no cover - metadata oddities
            continue
        # `B620`. `==` is a pin and `>=` is a floor, and only one of the two is
        # satisfied by a newer release. This was one `<` covering both, so an
        # environment holding a version **above** an exact pin was reported as
        # satisfying it — the one case the footer exists to describe. Measured
        # 2026-09-18: `mcp` 2.2.0 against a declared `mcp==1.30.0` makes all four
        # built-in MCP servers fail at import, and the footer named 17 gaps with
        # `mcp` not among them. `B325`'s own row says "at a version other than
        # the pin"; the code said "below it" (`Law 10`).
        want = _re.search(r"(==|>=)\s*([0-9][^,;\s]*)", spec)
        if not want:
            continue
        operator, target = want.group(1), want.group(2)
        try:
            behind = _parts(have) < _parts(target)
        except TypeError:  # pragma: no cover - unorderable version parts
            behind = False
        if behind or (operator == "==" and _parts(have) != _parts(target)):
            gaps.append(f"{name}: {have} installed, {spec} declared")
    _DECLARED_COUNT[0] = declared
    return gaps
