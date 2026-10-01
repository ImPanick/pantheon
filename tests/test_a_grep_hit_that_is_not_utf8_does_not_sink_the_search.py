# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B963` (found by `P20-03`): with ripgrep on PATH, one matching line that was
not UTF-8 failed the whole `grep` — *'utf-8' codec can't decode byte 0xe9* —
and returned no matches at all. Driven through the real `grep` tool on the
host and through `grep_walk` itself (which the workstation runs as text), with
ripgrep present.
"""
from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from src.agent_tools import TOOL_HANDLERS
from src.agent_tools.codenav_walk import grep_walk

needs_rg = pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not on PATH")


def _tree(tmp_path):
    (tmp_path / "good.txt").write_text("needle good\n", encoding="utf-8")
    (tmp_path / "latin.txt").write_bytes("needle café\n".encode("latin-1"))
    return tmp_path


@needs_rg
def test_the_walk_keeps_the_good_hit(tmp_path):
    root = _tree(tmp_path)
    lines, err = grep_walk(str(root), "needle", False, None, 50, (), (), lambda p: False, 400)
    assert err is None
    assert any(l.endswith("good.txt:1:needle good") for l in lines), lines


@needs_rg
def test_the_tool_answers_with_the_good_hit(tmp_path, monkeypatch):
    import src.tool_execution as te
    root = _tree(tmp_path)
    monkeypatch.setattr(te, "_resolve_search_root", lambda raw, *a, **k: str(root), raising=False)
    result = asyncio.run(TOOL_HANDLERS["grep"](json.dumps({"pattern": "needle", "path": str(root)}),
                                              {}))
    assert "error" not in result, result
    assert "needle good" in result["output"]
