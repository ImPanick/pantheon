# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B854` — a stub that is not a package hides which dependency is missing.

`tests/conftest.py` stands in for a dependency that is not installed, so that a
contributor with half the requirements still gets a run. It did that by putting
a `MagicMock` in `sys.modules` under each of nineteen dotted names, written out
by hand — and `unittest.mock` raises `AttributeError` for every dunder it does
not implement, so such a stub has no `__path__` and no `__spec__`. The import
machinery reads BOTH off the **parent** before it consults any finder. So a
submodule that was not on the list did not report a missing dependency; it
reported `'starlette' is not a package`, which is a sentence about the stub.

`core/middleware.py` imports `starlette.routing`. It was not on the list.

That is not a papercut: CI's `Law 16 — no egress on a fresh install` job
installs pytest and nothing else, on purpose, because that IS the fresh
install — and it therefore died in `conftest.py` before collecting a single
test, every time, for the whole life of the repository. Nobody could read the
red X until the repo went public and a run completed for the first time.

The list of nineteen names is `Law 13`'s defect class exactly: a thing that has
to be registered in one more place each time. The list stays, because those
names must exist EAGERLY, before a test module's own module-scope stub can win
the race. What closes the class is that a stub is now a real package and a
finder manufactures whatever is asked for beneath a root that is genuinely
absent. This file drives that machinery rather than reading conftest's source
(`Law 20`).
"""
import importlib
import sys
from unittest.mock import MagicMock

import pytest

import conftest as suite_conftest


ROOT = "pantheon_b854_absent_dependency"


@pytest.fixture
def stubbed_root():
    """A root that genuinely does not exist, stubbed the way conftest stubs one."""
    finder = suite_conftest._AbsentDependencyFinder({ROOT})
    sys.modules[ROOT] = suite_conftest._stub_module(ROOT)
    sys.meta_path.append(finder)
    try:
        yield ROOT
    finally:
        sys.meta_path.remove(finder)
        for name in [n for n in sys.modules if n == ROOT or n.startswith(ROOT + ".")]:
            del sys.modules[name]


def test_a_magicmock_is_not_a_package():
    """The root cause, observed rather than recalled."""
    mock = MagicMock()
    with pytest.raises(AttributeError):
        mock.__path__
    with pytest.raises(AttributeError):
        mock.__spec__


def test_the_old_shape_still_fails_the_way_it_failed():
    """A bare mock in `sys.modules` makes a missing submodule lie about itself."""
    sys.modules[ROOT] = MagicMock()
    try:
        with pytest.raises(ModuleNotFoundError) as caught:
            importlib.import_module(f"{ROOT}.routing")
        assert "is not a package" in str(caught.value)
    finally:
        del sys.modules[ROOT]


def test_a_stub_root_is_a_package(stubbed_root):
    stub = sys.modules[stubbed_root]
    assert stub.__path__ == []
    assert stub.__spec__ is not None
    assert stub.__spec__.submodule_search_locations is not None


def test_a_submodule_nobody_listed_imports(stubbed_root):
    module = importlib.import_module(f"{stubbed_root}.routing")
    assert module is sys.modules[f"{stubbed_root}.routing"]
    assert f"{stubbed_root}.routing" in suite_conftest._STUBBED_SUBMODULES


def test_the_import_that_started_this_works(stubbed_root):
    """`from <root>.routing import get_route_path` — the exact failing line."""
    namespace: dict = {}
    exec(f"from {stubbed_root}.routing import get_route_path", namespace)
    assert namespace["get_route_path"] is not None


def test_it_goes_as_deep_as_it_is_asked(stubbed_root):
    """`starlette.middleware.base` is three levels; nothing says four is safe."""
    module = importlib.import_module(f"{stubbed_root}.a.b.c")
    assert module is not None
    assert sys.modules[f"{stubbed_root}.a"].__path__ == []


def test_the_finder_answers_only_for_roots_it_was_given():
    finder = suite_conftest._AbsentDependencyFinder({ROOT})
    assert finder.find_spec("json") is None
    assert finder.find_spec("json.decoder") is None
    assert finder.find_spec("starlette.routing") is None
    assert finder.find_spec(f"{ROOT}.anything") is not None


def test_it_is_a_no_op_when_the_dependency_is_installed():
    """Nothing is manufactured for a dependency that is really there.

    This suite runs with the requirements installed, so `_ABSENT_ROOTS` is
    empty and conftest registered no finder at all. If that stops being true
    the assertion below says so, instead of a mock quietly standing in for a
    real library in ten thousand tests.
    """
    for root in suite_conftest._STUB_ROOTS:
        if root in suite_conftest._ABSENT_ROOTS:
            continue
        module = sys.modules.get(root) or importlib.import_module(root)
        assert getattr(module, "__file__", None) is not None, (
            f"{root} is installed and conftest replaced it with a stub"
        )

    if not suite_conftest._ABSENT_ROOTS:
        assert not any(
            isinstance(f, suite_conftest._AbsentDependencyFinder)
            for f in sys.meta_path
        )
