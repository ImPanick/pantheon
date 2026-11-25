# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2150`, `B2151`. Two first-party modules imported a top-level name that is
not a package of this repository: `src/research_handler.py` tried `from
research_engine import ...` on every boot (a legacy engine that is in no tree,
requirement or image), and `src/rag_manager.py` tried a bare `from rag_vector
import ...` before the package path. A bare top-level import executes whatever
file of that name sits first on `sys.path`, so a stray `research_engine.py` in
the directory Pantheon was started from ran inside the server.

Driven, not grepped: a planted module records that it ran, and the handler is
built the way `app.py` builds it.
"""
from __future__ import annotations

import importlib
import sys


def _plant(tmp_path, name: str, marker) -> None:
    (tmp_path / f"{name}.py").write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "class ResearchOrchestrator:\n"
        "    def __init__(self, *a, **k): pass\n"
        "class Config:\n"
        "    def __init__(self, *a, **k): pass\n",
        encoding="utf-8",
    )


def test_building_the_research_handler_runs_no_research_engine_file(tmp_path, monkeypatch):
    marker = tmp_path / "ran.txt"
    plant = tmp_path / "plant"
    plant.mkdir()
    _plant(plant, "research_engine", marker)
    monkeypatch.syspath_prepend(str(plant))
    monkeypatch.delitem(sys.modules, "research_engine", raising=False)

    rh = importlib.import_module("src.research_handler")
    monkeypatch.setattr(rh, "RESEARCH_DATA_DIR", tmp_path / "research")
    handler = rh.ResearchHandler()

    assert not marker.exists(), "a research_engine.py on sys.path ran inside the server"
    assert "research_engine" not in sys.modules
    assert not hasattr(handler, "_legacy_engine")


def test_a_failed_deep_research_falls_back_to_the_basic_search(tmp_path, monkeypatch):
    """What the legacy branch stood in front of still answers: a DeepResearcher
    failure reaches `_handle_research_failure`."""
    import asyncio

    rh = importlib.import_module("src.research_handler")
    monkeypatch.setattr(rh, "RESEARCH_DATA_DIR", tmp_path / "research")
    handler = rh.ResearchHandler()
    seen = {}

    def _basic(query, error):
        seen["args"] = (query, error)
        return "basic"

    monkeypatch.setattr(handler, "_handle_research_failure", _basic)
    out = asyncio.run(handler._fallback_research("q", "http://x", "m", 10, "boom"))
    assert out == "basic"
    assert seen["args"] == ("q", "boom")


def test_no_first_party_module_imports_the_flat_layouts_names():
    """The flat layout's bare names, as imports, anywhere in the server's code."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    flat = {"research_engine", "rag_vector", "rag_manager"}
    hits = []
    for base in ("src", "routes", "core", "services", "mcp_servers"):
        for path in (root / base).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in flat:
                    hits.append(f"{path.relative_to(root)}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    hits += [f"{path.relative_to(root)}:{node.lineno}"
                             for a in node.names if a.name in flat]
    for path in [root / "app.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in flat:
                hits.append(f"app.py:{node.lineno}")
    assert not hits, hits
