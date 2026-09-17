# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B271` — the two shapes the `B18` collection guard cannot see.

`tests/conftest.py`'s `pytest_collection_finish` fails the session if a named
production module is a stub after collection, and the test for "is it a stub"
is `getattr(mod, "__file__", None) is None`. Both of `B202`'s defects walk
straight past it:

  * one is a **run-time** event — `routes.chat_helpers` is poisoned by a test,
    long after collection has finished;
  * one is about **attributes, not modules** — the poisoned module is the real
    one, with a real `__file__`, holding four `MagicMock`s bound by value:
    `maybe_compact`, `trim_for_context`, `load_prefs_for_user` and
    `effective_user`. Every later test in that session measured the chat
    privilege gate against a stand-in that answers truthily.

A predicate about `__file__` cannot have an opinion about either. The sweep in
`conftest.py` is about the objects instead, and this file drives it.

**The measurement the previous attempt at this row said it needed first.**
It was declined because "a check over every module's attributes at each test's
teardown would turn the whole suite red for one file's behaviour, and this
worktree cannot measure which files those are without an 11-minute run it was
told not to take". Both halves are answered here without one:

  * **Cost.** One sweep is **1.3 ms** over 271 loaded production modules and
    10,014 attributes. It runs once per test FILE, not once per test, so the
    whole suite pays about **1.2 s** — because attribution needs a boundary
    where nothing of the next file has run yet, and per-test would be 8,600
    sweeps to learn nothing a file name does not already say.
  * **Scale.** Run over the **100 test files that touch `sys.modules`** —
    1,507 tests, 149 s, which is the population where this defect can live —
    the sweep names **three files leaving four mocks behind**:
    `test_api_token_routes.py` (`routes.api_token_routes.ApiToken`),
    `test_editor_draft_payload.py` (`routes.editor_draft_routes.EditorDraft`
    and `.SessionLocal`) and `test_gallery_exif_orientation.py`
    (`routes.gallery.gallery_helpers.GalleryImage`). Three, not three hundred —
    so a strict mode is affordable, and `B413` is the row that clears them.
    A 125-file run names two of the three: pytest imports every test module
    at collection, so another file's module-scope code can take a binding out
    of view before the next boundary looks. The report is a **lower bound**
    on a given run, which is the right direction for something that reports
    rather than fails.

It **reports and does not fail**, which is what makes it shippable today:
`--strict-isolation` turns the report into a failure for whoever wants it,
which is the integrator on a full run.
"""
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import conftest as suite_conftest
import src.settings  # a real production module for the probes below

ROOT = Path(__file__).resolve().parent.parent


# ── the detector ─────────────────────────────────────────────────────────────


def test_a_mock_bound_into_a_real_module_is_found():
    """`B202`'s second shape: a real module, a real `__file__`, a fake attribute."""
    module = src.settings
    assert getattr(module, "__file__", None), "src.settings should be the real one"
    name = "_b271_probe_attribute"
    assert f"src.settings.{name}" not in suite_conftest._mock_bindings()
    setattr(module, name, MagicMock())
    try:
        found = suite_conftest._mock_bindings()
        assert found.get(f"src.settings.{name}") == "MagicMock"
    finally:
        delattr(module, name)
    assert f"src.settings.{name}" not in suite_conftest._mock_bindings()


def test_every_flavour_of_mock_counts(monkeypatch):
    """`AsyncMock` and a plain `Mock` poison a module exactly as well."""
    module = src.settings
    for factory in (MagicMock, AsyncMock):
        monkeypatch.setattr(module, "_b271_probe_flavour", factory(),
                            raising=False)
        assert "src.settings._b271_probe_flavour" in suite_conftest._mock_bindings()
        monkeypatch.undo()


def test_a_whole_module_replaced_by_a_mock_is_found(monkeypatch):
    """`B18`'s shape, seen by the same sweep — at run time rather than at
    collection, which is where `B202`'s first defect lived."""
    monkeypatch.setitem(sys.modules, "routes._b271_probe_module", MagicMock())
    found = suite_conftest._mock_bindings()
    assert found.get("routes._b271_probe_module") == "the module itself"


def test_a_module_outside_the_production_roots_is_not_the_suites_business():
    """A test may stub `chromadb` all day. What it may not do is leave a mock
    inside `src.`, `core.`, `routes.`, `integrations.` or `netagent.`."""
    sys.modules["_b271_not_production"] = MagicMock()
    try:
        assert "_b271_not_production" not in suite_conftest._mock_bindings()
    finally:
        del sys.modules["_b271_not_production"]


def test_the_sweep_attributes_a_leak_to_the_file_that_left_it(monkeypatch):
    """The `Verify:` line: *named by the suite, at the file that left it*."""
    monkeypatch.setattr(suite_conftest, "_isolation",
                        {"file": None, "seen": set(), "leaks": {}, "on": True,
                         "scans": 0})
    module = src.settings
    monkeypatch.setattr(module, "_b271_probe_attribution", MagicMock(),
                        raising=False)
    suite_conftest._isolation_sweep("tests/test_somebody_elses_file.py")
    leaks = suite_conftest._isolation["leaks"]
    assert "tests/test_somebody_elses_file.py" in leaks
    assert any("src.settings._b271_probe_attribution" in entry
               for entry in leaks["tests/test_somebody_elses_file.py"])


def test_a_leak_is_reported_once_and_not_against_every_later_file(monkeypatch):
    """Otherwise one file's mistake reads as forty files' mistakes, and the
    report becomes the thing people turn off."""
    monkeypatch.setattr(suite_conftest, "_isolation",
                        {"file": None, "seen": set(), "leaks": {}, "on": True,
                         "scans": 0})
    module = src.settings
    monkeypatch.setattr(module, "_b271_probe_once", MagicMock(), raising=False)
    suite_conftest._isolation_sweep("tests/first.py")
    suite_conftest._isolation_sweep("tests/second.py")
    assert "tests/second.py" not in suite_conftest._isolation["leaks"]


def test_the_sweep_can_be_turned_off_and_costs_nothing_when_it_is(monkeypatch):
    monkeypatch.setattr(suite_conftest, "_isolation",
                        {"file": None, "seen": set(), "leaks": {}, "on": False,
                         "scans": 0})
    suite_conftest._isolation_sweep("tests/whatever.py")
    assert suite_conftest._isolation["scans"] == 0


# ── the module-stub guard, widened ───────────────────────────────────────────


def test_the_collection_guard_is_no_longer_a_hand_written_list(monkeypatch):
    """`Law 13`. Six names extended by hand is the defect the guard names.

    The sweep is over every loaded module under the production roots, so a
    seventh module nobody thought of is found by the same rule as the six. What
    differs is the consequence: the six abort the session, because a stub in one
    of them makes the rest of the run meaningless and one of them has cost a
    6 GB OOM kill. A seventh is reported. Aborting somebody's 11-minute run at
    collection, for a module nobody has been burned by, before a single test has
    told them anything, is how a guard gets deleted.
    """
    assert suite_conftest._module_stubs() == [], (
        "a production module is a stub right now: "
        f"{suite_conftest._module_stubs()}")
    monkeypatch.setitem(sys.modules, "core._b271_probe_stub",
                        types.ModuleType("core._b271_probe_stub"))
    assert "core._b271_probe_stub" in suite_conftest._module_stubs()


def test_a_seventh_stub_is_reported_and_does_not_abort_collection(monkeypatch):
    """The consequence, not just the detection."""
    monkeypatch.setattr(suite_conftest, "_isolation",
                        {"file": None, "seen": set(), "leaks": {}, "on": True,
                         "scans": 0})
    monkeypatch.setitem(sys.modules, "routes._b271_probe_seventh",
                        types.ModuleType("routes._b271_probe_seventh"))
    suite_conftest.pytest_collection_finish(session=None)   # must not raise
    leaks = suite_conftest._isolation["leaks"]
    assert any("routes._b271_probe_seventh" in entry
               for entries in leaks.values() for entry in entries)


def test_the_named_six_still_abort_the_session(monkeypatch):
    """They have each cost a diagnosis. A report is not enough for those."""
    import pytest as _pytest

    monkeypatch.setitem(sys.modules, "src.tool_parsing",
                        types.ModuleType("src.tool_parsing"))
    with _pytest.raises(_pytest.UsageError, match="src.tool_parsing"):
        suite_conftest.pytest_collection_finish(session=None)


def test_the_stubs_conftest_installs_on_purpose_are_not_reported():
    """A contributor without SQLAlchemy gets `src.database` stubbed by
    `conftest.py` itself. Failing them for doing what conftest told them to do
    is how a guard gets deleted."""
    for name in suite_conftest._DELIBERATE_STUBS:
        assert name not in suite_conftest._module_stubs()


def test_the_named_six_are_still_real_here():
    """The `B18` list is kept beside the sweep: those six are the ones a stub
    has actually been found in, and the pre-import block exists for them."""
    for name in suite_conftest._MUST_BE_REAL_AFTER_COLLECTION:
        module = sys.modules.get(name)
        if module is None or name in suite_conftest._DELIBERATE_STUBS:
            continue
        assert getattr(module, "__file__", None) is not None, name


# ── end to end ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("strict", [False, True])
def test_a_file_that_leaks_is_named_in_the_run_that_ran_it(tmp_path, strict):
    """A real pytest session, with a real leaking file, in a subprocess.

    Driving the hook rather than asserting on `conftest.py`'s source, and in
    its own process so the leak it creates cannot reach this one.
    """
    leaky = ROOT / "tests" / "_b271_leaky_probe_test.py"
    leaky.write_text(
        "import sys\n"
        "from unittest.mock import MagicMock\n"
        "def test_it_leaks():\n"
        "    import src.settings\n"
        "    src.settings._b271_left_behind = MagicMock()\n"
        "def test_a_second_test_in_the_same_file():\n"
        "    assert True\n",
        encoding="utf-8")
    try:
        argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
                str(leaky), str(ROOT / "tests" / "test_the_root_roadmap_explains_itself.py")]
        if strict:
            argv.append("--strict-isolation")
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=300)
    finally:
        leaky.unlink()
    assert "B271: mocks left bound in production modules" in proc.stdout
    assert "_b271_leaky_probe_test.py left:" in proc.stdout
    assert "src.settings._b271_left_behind" in proc.stdout
    assert (proc.returncode != 0) is strict, (
        "the report must not fail a run unless --strict-isolation asked it to")
