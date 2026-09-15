# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify `src.tool_utils` cannot reach a module that might be half-initialised.

`tool_utils` exists to break a circular import. If someone adds an import from
`src.settings`, `src.database`, or any other project module that itself imports
from the project, the cycle this module exists to break silently returns a
partially-initialized module. This test catches that statically.

**THE RULE USED TO BE AN ALLOWLIST OF ONE NAME, AND IT WAS THE WRONG SHAPE.**
It permitted `src.constants` and nothing else — so `src.runtime_limits`, a
stdlib-only module whose own docstring says *"Imports nothing from the project
(stdlib only), so it is safe to import anywhere, including lazily from
src.tool_utils"*, failed a rule it provably satisfies. The import was written by
somebody who had read the rule and checked they were allowed.

So the test now enforces the **invariant** rather than a proxy for it. Written
first at depth one — *whatever `tool_utils` imports must import nothing* — which
failed immediately, because `src.constants` imports `src.runtime_paths`. The
allowlist had been hiding that the permitted module was not itself a leaf.

The real invariant is **transitive**: follow every `src.` import as far as it
goes and the closure must never come back to `tool_utils`. That is the cycle,
stated directly. Strictly stronger than the allowlist in both directions — it
stops being wrong about a safe module, and it starts catching what an allowlist
never could: somebody adding a heavy import to `constants`, `runtime_paths` or
`runtime_limits` later and reopening the cycle from the far end, three hops away
from the file this rule is about.
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent


def _project_imports(module_path: pathlib.Path) -> set:
    """Every `src.*` module this file imports, at any depth in its AST.

    Function-local imports count. A deferred import still resolves during
    startup if it is called while the cycle is resolving, and `tool_utils`
    wraps its one such import in a bare `except Exception: pass` — so the
    failure mode is silent rather than loud, which is worse.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src."):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    found.add(alias.name)
    return found


def _path_for(module: str) -> pathlib.Path:
    return REPO / (module.replace(".", "/") + ".py")


def _closure(start: str) -> set:
    """Every `src.` module reachable from *start*, transitively."""
    seen, stack = set(), [start]
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _path_for(module)
        if path.exists():
            stack.extend(_project_imports(path) - seen)
    return seen


def test_nothing_tool_utils_reaches_imports_it_back():
    """The cycle, asserted as a cycle rather than as a list of names."""
    reached = _closure("src.tool_utils") - {"src.tool_utils"}
    for module in sorted(reached):
        onward = _project_imports(_path_for(module)) if _path_for(module).exists() else set()
        assert "src.tool_utils" not in onward, (
            f"{module} imports src.tool_utils, which is the cycle this module "
            f"exists to break"
        )


def test_the_closure_stays_small_and_named():
    """A second pair of eyes, not a duplicate of the first test.

    The rule above catches a cycle. It would stay green while the closure grew
    to half the project, and a large closure is how a cycle eventually arrives.
    Naming the set makes each addition a deliberate edit; the cycle test above
    is what says the addition is safe.
    """
    assert _closure("src.tool_utils") == {
        "src.tool_utils",
        "src.constants",
        # `B91`. The vocabulary for environment truthiness. It is in this
        # closure deliberately and it is why that module imports nothing but
        # `os`: `src.constants` and `src.runtime_limits` both read a boolean
        # variable, both are in here already, and the alternative was a third
        # and fourth private `_truthy` that disagreed with each other — which is
        # the defect `B91` is, arriving inside the one closure that must stay
        # small.
        "src.env_flags",
        "src.runtime_limits",
        "src.runtime_paths",
    }, sorted(_closure("src.tool_utils"))
