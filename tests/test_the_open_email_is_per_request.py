# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2153`. The email open beside the chat reaches the agent per request, as
`active_email=` on the loop. A second, process-wide copy — `set_active_email`
in `src/tool_implementations.py` — was written on every chat turn and read by
nothing, and held one person's open email where every other person's request
could have read it.

What is pinned: the module holds no such state any more, and the chat route
still hands the per-request copy to the loop (scoped to the handler, not the
file, `Law 20`)."""
from __future__ import annotations

import ast
from pathlib import Path

import src.tool_implementations as ti

ROOT = Path(__file__).resolve().parents[1]


def test_no_process_wide_open_email_is_kept():
    for name in ("set_active_email", "get_active_email", "clear_active_email",
                 "_active_email_ref"):
        assert not hasattr(ti, name), f"{name} is process-wide state"


def test_the_chat_route_passes_the_open_email_to_the_loop_per_request():
    tree = ast.parse((ROOT / "routes" / "chat_routes.py").read_text(encoding="utf-8"))
    passes = [kw for node in ast.walk(tree) if isinstance(node, ast.Call)
              for kw in node.keywords
              if kw.arg == "active_email" and isinstance(kw.value, ast.Name)
              and kw.value.id == "active_email_ctx"]
    assert passes, "the per-request open email no longer reaches the agent loop"
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
              and n.module == "src.tool_implementations"
              and any(a.name.endswith("active_email") for a in n.names)]
    assert not writes
