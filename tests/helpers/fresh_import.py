# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop a module so the next import binds to whatever stubs are installed —
and put `sys.modules` back exactly as it was.

`monkeypatch.delitem(sys.modules, name, raising=False)` does **not** do the
second half. pytest's implementation records an undo entry only when the key was
actually there:

    if name not in dic:
        if raising:
            raise KeyError(name)
    else:
        self._setitem.append((dic, name, dic.get(name, notset)))
        del dic[name]

So on the common path — a module this file is the first to import — nothing is
recorded, the fresh import under the test's stubs lands in `sys.modules`, and it
is still there for every later file in the session. That is how
`routes.api_token_routes.ApiToken` came to be a `MagicMock` for the back half of
an 11,100-test run: the module in `sys.modules` was the real one by `__file__`
and a stub by contents, which is the exact shape `B202` and `B271` describe
(`B525`).

`monkeypatch.setitem` records either way — the previous value, or `notset` for
"was absent", which its undo turns into a delete. So setting a placeholder and
then removing the key ourselves gets the restore right in both cases.
"""
import sys

_PLACEHOLDER = object()


def drop_for_fresh_import(monkeypatch, *names):
    """Remove `names` from `sys.modules`, restoring them at teardown.

    Imported or not before the call, `sys.modules` is the same afterwards.
    Returns nothing: the point is the re-import the caller then does itself, so
    that the stubs it wants are the ones in place when the module body runs.
    """
    for name in names:
        monkeypatch.setitem(sys.modules, name, _PLACEHOLDER)
        sys.modules.pop(name, None)


class reimported_under_stubs:
    """A module-level re-import that leaves `sys.modules` as it found it.

    `B983`. Four files popped `src.agent_tools`, `src.tool_parsing`,
    `src.tool_schemas` and `src.tool_execution` at import time, put `MagicMock`s
    in for `core.auth` and friends when those were not loaded yet, and imported
    the four again — and left the second copies, and the mocks, for every file
    collected after them. A module that had bound the first `src.tool_execution`
    then set a workspace in a context variable the file tools (which import the
    dispatcher at call time, and so get the second) never read: 25 cases of
    `tests/test_the_agents_hands_are_in_the_workstation.py` failed after
    `test_fenced_invoke_no_raw_xml.py` alone, each passing on its own.

    Used as a `with` block around the imports; the file keeps the objects it
    imported, and everyone after it gets `sys.modules` back — the popped modules
    returned, the stubs removed, and anything first imported under the stubs
    dropped so the next importer binds the real dependencies::

        with reimported_under_stubs(pop=[...], stub_if_absent=[...]):
            import src.agent_tools
            from src.tool_parsing import parse_tool_blocks
    """

    def __init__(self, *, pop=(), stub_if_absent=()):
        self.pop = list(pop)
        self.stub_if_absent = list(stub_if_absent)

    def __enter__(self):
        from unittest.mock import MagicMock

        self._before = dict(sys.modules)
        for name in self.pop:
            sys.modules.pop(name, None)
        for name in self.stub_if_absent:
            if name not in sys.modules:
                sys.modules[name] = MagicMock()
        return self

    def __exit__(self, *exc):
        touched = {}
        for name in list(sys.modules):
            if name not in self._before:
                touched[name] = sys.modules.pop(name)
        for name, module in self._before.items():
            if sys.modules.get(name) is not module:
                touched[name] = sys.modules.get(name)
                sys.modules[name] = module
        # `sys.modules` is half of it. Importing `a.b` also sets `b` on the
        # package `a`, and `import a.b as c` reads that attribute — so without
        # this, a file collected later still got the second copy by attribute
        # while the code under test imported the first by name (measured:
        # the same 33 failures with `sys.modules` restored and this missing).
        for name, stale in touched.items():
            parent_name, _, child = name.rpartition(".")
            parent = sys.modules.get(parent_name) if parent_name else None
            if parent is None:
                continue
            if name in sys.modules:
                setattr(parent, child, sys.modules[name])
            elif getattr(parent, child, None) is stale:
                try:
                    delattr(parent, child)
                except AttributeError:
                    pass
        return False
