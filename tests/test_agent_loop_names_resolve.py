"""Every name `stream_agent_loop` uses must exist where it is used.

`B38`. `H08`'s refactor moved `from src.runtime_limits import lift_cap as
_lift_cap` from the body of `stream_agent_loop` into a new helper, and left a
call to `_lift_cap` two thousand lines below, inside the per-round block. That
is a `NameError` on the first round of every request — the hot path of the whole
product — and it got past a passing targeted test file, sixteen passing
mutations and eight green checkers. Ninety-six full-suite failures caught it.

It is also the third of its family. `B32` and `B33` were both guarded code
referencing a name that was not in scope, where the guard swallowed the error
and the instrumentation silently never ran. This one had no guard, so it was
loud — which was luck, not design.

Python cannot catch this at import: a function body's free names are resolved
when the line runs, and `stream_agent_loop` is 2,800 lines with branches that a
test suite will not all reach. So resolve them statically instead. This is a
general check over the whole module, not a check for `_lift_cap`; a rule written
against the last incident does not catch the next one.
"""
import ast
import builtins
import pathlib

import pytest

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "src" / "agent_loop.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def _bound_names(node) -> set:
    """Every name this function body binds: parameters, assignments, imports,
    comprehension targets, `with ... as`, `except ... as`, nested defs."""
    out = set()
    def _params(args):
        got = set()
        if not args:
            return got
        for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)):
            got.add(a.arg)
        for a in (args.vararg, args.kwarg):
            if a:
                got.add(a.arg)
        return got

    out |= _params(getattr(node, "args", None))
    for child in ast.walk(node):
        # A lambda's parameters are bound names too, and missing them reported
        # `lambda m: m.group(1)` as an undefined `m`. Found by this test's own
        # first run — which is the argument for running a new checker over the
        # whole module before trusting a single one of its findings.
        if isinstance(child, ast.Lambda):
            out |= _params(child.args)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            out.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(child.name)
            if child is not node:
                out |= _bound_names(child)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(child, ast.ExceptHandler) and child.name:
            out.add(child.name)
        elif isinstance(child, ast.Global) or isinstance(child, ast.Nonlocal):
            out |= set(child.names)
    return out


def _module_level_names() -> set:
    out = set(dir(builtins))
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ([node.target] if not isinstance(node, ast.Assign) else node.targets):
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        out.add(n.id)
        elif isinstance(node, ast.Try):
            # module-level try/except import blocks
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        out.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    out.add(sub.id)
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        out.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    out.add(sub.id)
    return out


def _unresolved(func) -> set:
    known = _module_level_names() | _bound_names(func)
    used = {n.id for n in ast.walk(func)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return used - known


def _top_level_functions():
    return [n for n in TREE.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_stream_agent_loop_uses_no_name_it_cannot_see():
    """The function the incident was in, checked first and by name because it
    is the one every chat goes through."""
    func = next(f for f in _top_level_functions() if f.name == "stream_agent_loop")
    assert _unresolved(func) == set()


@pytest.mark.parametrize("name", sorted(f.name for f in _top_level_functions()))
def test_every_top_level_function_uses_names_it_can_see(name):
    """The rest of the module, one case each so a failure names the function.

    Deliberately not limited to `stream_agent_loop`: this class of defect is
    not special to it, and a check written against the last incident is a check
    that catches the last incident."""
    func = next(f for f in _top_level_functions() if f.name == name)
    unresolved = _unresolved(func)
    assert unresolved == set(), f"{name}() references undefined name(s): {sorted(unresolved)}"


def test_the_check_actually_catches_a_missing_name():
    """A scope checker that resolves everything is indistinguishable from one
    that resolves nothing. This is the incident, reduced."""
    # The name must be one the real module does not define, since `_unresolved`
    # checks against `agent_loop`'s globals. The first version of this control
    # used `_lift_cap` — the very name from the incident — and passed vacuously
    # the moment that name became a module-level function.
    missing = "_zz_name_that_agent_loop_does_not_define"
    assert missing not in _module_level_names(), "control name has been taken"
    broken = ast.parse(
        f"def f(a):\n"
        f"    b = a + 1\n"
        f"    return {missing}(b)\n"
    ).body[0]
    assert missing in _unresolved(broken)


def test_the_check_does_not_flag_a_local_import():
    ok = ast.parse(
        "def f(a):\n"
        "    from src.runtime_limits import lift_cap\n"
        "    return lift_cap(a)\n"
    ).body[0]
    assert _unresolved(ok) == set()
