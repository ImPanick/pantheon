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
        # `B1003`: the package attribute too. Importing `a.b` again sets `b` on
        # the package `a`, and `import a.b as c` / `from a import b` read that
        # attribute — so with only `sys.modules` restored, every file after
        # this test reached the re-imported copy by attribute and the original
        # by name (five modules seen split this way in one full run).
        parent_name, _, child = name.rpartition(".")
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None:
            # `B1049`: through the package's `__dict__`, the way `sys.modules`
            # is handled below. `setattr(parent, child, None)` for an attribute
            # that was not there made it `None` for the test — and
            # `from src import integrations` reads the attribute first, so it
            # got `None` and imported nothing — and pytest undoes a `setattr`
            # of an absent attribute with a bare `delattr`. A placeholder then
            # removed leaves it absent, and its undo deletes whatever the
            # re-import bound there, absent or not.
            namespace = vars(parent)
            if child in namespace:
                monkeypatch.setitem(namespace, child, namespace[child])
            else:
                monkeypatch.setitem(namespace, child, _PLACEHOLDER)
                namespace.pop(child, None)
        monkeypatch.setitem(sys.modules, name, _PLACEHOLDER)
        sys.modules.pop(name, None)


# `B1180`. What `app.py`'s body installs in other modules as it runs, through
# its seven module-level `set_*` calls: `(module, global)` pairs, each put back
# by `import_app_in_this_test`. Held equal to those calls by
# `tests/test_importing_the_app_in_a_test_leaves_nothing_behind.py`, so an
# eighth setter is a red test rather than a new leak.
APP_INSTALLS = {
    "_set_asst_sm": (("src.assistant_log", "_session_manager"),),
    "set_session_manager_instance": (("core.models", "_SESSION_MANAGER_INSTANCE"),),
    "set_task_scheduler": (("src.event_bus", "_task_scheduler"),),
    "set_mcp_manager": (("src.tool_utils", "_mcp_manager"),),
    "set_ai_session_manager": (("src.ai_interaction", "_session_manager"),
                               ("core.models", "_SESSION_MANAGER_INSTANCE")),
    "set_ai_memory_manager": (("src.ai_interaction", "_memory_manager"),
                              ("src.ai_interaction", "_memory_vector")),
    "set_ai_rag_manager": (("src.ai_interaction", "_rag_manager"),
                           ("src.ai_interaction", "_personal_docs_manager")),
}


def import_app_in_this_test(monkeypatch):
    """`import app` inside one test, and the process given back as it was.

    `B1180`. Two files imported the app in process and left two things behind
    for every file after them: the module in `sys.modules`, and the singletons
    its body installs — `set_mcp_manager(McpManager())` among them. With that
    manager left running, `workflow_effects._mcp_tools` (which expects none in
    a test, as its docstring says) read every server's tool overrides on the
    process's `sqlite:///:memory:` engine from each TestClient's portal thread;
    past five threads SQLAlchemy's `SingletonThreadPool` closes connections,
    the main thread's among them, and the in-memory database that held the
    tables went with it. Measured 2026-10-03 on `3e4888b`:
    `test_edit_image_routes.py` then `test_testing_one_step_runs_nothing_else.py`
    then `test_the_halves_are_one_product.py::test_the_two_limits_and_the_waiting_words_have_one_home`
    fails `no such table: mcp_servers`, each file alone passes, and
    `test_mail_arriving_runs_its_workflow_with_nobody_looking.py` in the first
    place does the same.

    So the import runs here, under the caller's `monkeypatch` (dropped first
    with `drop_for_fresh_import`, so it is this test's import whatever ran
    before), and at teardown `sys.modules` and every global in `APP_INSTALLS`
    are what they were. The app's other import-time effects — a root log
    handler, MIME types, `install_role_layer`, `load_dotenv` — are not put back.
    """
    import importlib

    for pairs in APP_INSTALLS.values():
        for module_name, name in pairs:
            module = importlib.import_module(module_name)
            monkeypatch.setattr(module, name, getattr(module, name))
    drop_for_fresh_import(monkeypatch, "app")
    return importlib.import_module("app")


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
