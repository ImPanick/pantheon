# SPDX-License-Identifier: AGPL-3.0-or-later
"""No constructor passes, and no class attribute names, a column a table
model no longer declares.

**Measured:** `B1480` retired `CrewMember.is_active` and `sort_order` as
"read by nothing" — true, but `ensure_assistant_defaults` still *wrote* both,
so every new person's Assistant failed with `TypeError: 'is_active' is an
invalid keyword argument for CrewMember` and `GET /api/assistant/session`
answered 500. A column removal is a removal from every writer too, and the
writers are found by name: every call to a model imported from
`core.database`, read from the source, keyword by keyword.
"""

import ast
from pathlib import Path

import core.database as D
from sqlalchemy import inspect as sa_inspect

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("src", "routes", "core", "services", "scripts")


def _models():
    out = {}
    for name in dir(D):
        obj = getattr(D, name)
        if isinstance(obj, type) and issubclass(obj, D.Base) and obj is not D.Base \
                and hasattr(obj, "__table__"):
            out[name] = set(sa_inspect(obj).attrs.keys())
    return out


def _imported_models(tree, models):
    """`{local name: model name}` for the models this file imports from
    `core.database` — so `core.models.Session`, a different class with the
    same name, is not mistaken for the table."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database"):
            for a in node.names:
                if a.name in models:
                    out[a.asname or a.name] = a.name
    return out


def _files():
    yield ROOT / "app.py"
    for d in DIRS:
        yield from (ROOT / d).rglob("*.py")


def test_every_keyword_a_model_is_built_with_is_one_it_declares():
    models = _models()
    assert len(models) > 30 and "is_active" not in models["CrewMember"]
    bad, calls = [], 0
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        local = _imported_models(tree, models)
        if not local:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in local:
                model = local[node.func.id]
                calls += 1
                bad += [f"{path.relative_to(ROOT)}:{node.lineno} {model}({k.arg}=…)"
                        for k in node.keywords if k.arg and k.arg not in models[model]]
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id in local and not node.attr.startswith("_"):
                model = local[node.value.id]
                if node.attr not in models[model] and not hasattr(getattr(D, model), node.attr):
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {model}.{node.attr}")
    assert calls > 100, calls
    assert bad == [], "\n".join(bad)
