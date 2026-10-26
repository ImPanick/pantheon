# SPDX-License-Identifier: AGPL-3.0-or-later
"""Patch the token estimator everywhere it is bound, or fail naming where not.

`B743`. `src.model_context.estimate_tokens` is one function with several
names: every module that does `from src.model_context import estimate_tokens`
at import holds its own reference, so a test that patches
`chat_routes.estimate_tokens` to make counting predictable leaves
`chat_helpers.shaping_stats` measuring with the REAL estimator — and the
assertion then fails against numbers nobody chose, or passes because the real
figure happens to match. It cost half an hour on `P4-13`.

So the binders are found, not listed: an AST pass over the production trees
names every module that binds the function at import (a new one is found the
day it is written), each is imported, and every binding that still holds the
real estimator is patched — `src.model_context`'s own included, for the
modules that import the name inside a function at call time. A binding still
holding the real estimator afterwards fails the call, by name.

The property is that no counter is left measuring with the REAL estimator, not
that every counter holds this one stand-in: a binding the caller already
replaced with its own (a test that sets `agent_loop`'s and then calls a shared
helper that patches the rest) is left as the caller set it. The real one is
recognised by what it is, not by identity, so a second copy of
`src.model_context` (a re-import under stubs) is caught too.
"""
import ast
import functools
import importlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_TREES = ("src", "routes", "core", "services", "integrations", "netagent", "workstation")
_SOURCE = "src.model_context"
_NAME = "estimate_tokens"


def _module_level(body):
    """Statements that run at import: descends into `if`/`try`/`with`, never
    into a function or class body (those import at call time)."""
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            for field in ("body", "orelse", "finalbody"):
                yield from _module_level(getattr(node, field, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                yield from _module_level(handler.body)


@functools.lru_cache(maxsize=1)
def import_time_binders() -> tuple:
    """`(module, local name)` for every production module that binds
    `estimate_tokens` when it is imported."""
    found = []
    for tree in _TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            try:
                parsed = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in _module_level(parsed.body):
                if isinstance(node, ast.ImportFrom) and node.module == _SOURCE:
                    for alias in node.names:
                        if alias.name == _NAME:
                            rel = path.relative_to(ROOT).with_suffix("")
                            module = ".".join(rel.parts)
                            if module.endswith(".__init__"):
                                module = module[: -len(".__init__")]
                            found.append((module, alias.asname or alias.name))
    return tuple(found)


def _is_the_real_estimator(value) -> bool:
    return (inspect.isfunction(value) and value.__module__ == _SOURCE
            and value.__qualname__ == _NAME)


def patch_estimator(monkeypatch, fake):
    """Make `fake` the token estimator for every counter still on the real
    one, undone at teardown.

    Returns the qualified names it patched. Raises `AssertionError` naming any
    import-time binder that still holds the real estimator afterwards.
    """
    importlib.import_module(_SOURCE)
    for module_name, _ in import_time_binders():
        importlib.import_module(module_name)

    patched = []
    for name, module in list(sys.modules.items()):
        namespace = getattr(module, "__dict__", None)
        if module is None or not isinstance(namespace, dict):
            continue
        if not (name == _SOURCE or name.startswith(tuple(t + "." for t in _TREES))):
            continue
        for attr, value in list(namespace.items()):
            if _is_the_real_estimator(value):
                monkeypatch.setattr(module, attr, fake)
                patched.append(f"{name}.{attr}")

    missed = [f"{module}.{attr}" for module, attr in import_time_binders()
              if _is_the_real_estimator(getattr(sys.modules.get(module), attr, None))]
    assert not missed, (
        "B743: these modules still count tokens with the real estimator, which "
        "this patch did not reach: " + ", ".join(missed))
    return sorted(patched)
