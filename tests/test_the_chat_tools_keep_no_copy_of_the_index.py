# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1545` — the AI-interaction tools keep no copy of the RAG manager.

`app.py` called `src.ai_interaction.set_rag_manager(rag_manager,
personal_docs_mgr)` at boot, and the module stored both in globals that
nothing read. After `B1532` (an index that comes up after boot is searched),
that copy was the boot-time answer frozen: `None` on a box whose ChromaDB
started a minute late, forever. The one copy is `src.rag_singleton`
(`get_rag_manager()` / `rag_instance`); this holds that there is no second.
"""
import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_module_holds_no_rag_manager_of_its_own():
    mod = importlib.import_module("src.ai_interaction")
    for name in ("_rag_manager", "_personal_docs_manager", "set_rag_manager"):
        assert not hasattr(mod, name), (
            f"src.ai_interaction.{name} is back — a reader asks rag_singleton")


def test_the_app_installs_no_rag_manager_anywhere_but_the_singleton():
    """No module-level call in `app.py` hands the RAG manager to another
    module: the setters it calls are named, and none of them takes it."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    handed = []
    for node in tree.body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        name = getattr(call.func, "id", getattr(call.func, "attr", ""))
        if not name.lstrip("_").startswith("set_"):
            continue
        args = [a.id for a in call.args if isinstance(a, ast.Name)]
        if "rag_manager" in args or "rag" in name:
            handed.append(f"app.py:{node.lineno} {name}({', '.join(args)})")
    assert handed == [], handed
