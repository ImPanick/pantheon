# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1510` — a person's chats are `list_page`'s answer, and there is no second door.

`SessionManager.get_sessions_for_user` filtered `self.sessions` — the boot
cache of the newest 100 chats of *every* owner — by owner. That was `B1224`'s
defect twice over (Tidy and the agent's `list_sessions` read it, so a person
whose chats were older than someone else's last 100 had none), and once
`B1224` moved both to `list_page` nothing in the product called it;
`routes/auth_routes.py` named it in a comment only. The row's `Verify:` allows
either a real caller or its deletion with the tests that only test it. No test
called it, so it is deleted alone.

What is pinned: the method is gone from the class, and no Python under the
product's directories reaches for it by attribute or by name — an AST walk, not
a substring, so a comment that tells this history does not count as a caller
(`Law 20`). `list_page` itself is pinned by
`tests/test_tidy_and_the_agent_see_every_chat.py`.
"""
import ast
from pathlib import Path

from core.session_manager import SessionManager

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ("app.py", "core", "routes", "src", "services", "integrations", "mcp_servers", "workstation", "netagent")
GONE = "get_sessions_for_user"


def _python_files():
    for part in PRODUCT:
        path = ROOT / part
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_cache_only_door_is_gone():
    assert not hasattr(SessionManager, GONE)


def test_nothing_in_the_product_reaches_for_it():
    callers = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Attribute) and node.attr == GONE) \
                or (isinstance(node, ast.Name) and node.id == GONE) \
                or (isinstance(node, ast.Constant) and node.value == GONE)
            if named:
                callers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert callers == []
