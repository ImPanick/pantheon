# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B823`: the casual-greeting predicate and its two regexes exist once.

They were byte-identical in `src/agent_loop.py` and `routes/chat_helpers.py`,
and the two copies gated different things (stale context for tool retrieval;
memory, skills, RAG and docs for the route). The day one blocklist grew a
word, the product would have suppressed skills for a message it still pulled
memory for. The count is `ast`-based (`Law 20`): the two definitions differed
only in a docstring and a comment, which a substring search cannot tell from
code.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("_is_casual_low_signal", "_CASUAL_OPENING_RE", "_CASUAL_BLOCKLIST_RE")


def _definitions():
    """Every top-level def/assignment of the three names across the product's
    Python (src/, routes/, services/, app.py) — imports are not definitions."""
    found = {name: [] for name in NAMES}
    files = [ROOT / "app.py"]
    for sub in ("src", "routes", "services", "core"):
        files.extend((ROOT / sub).rglob("*.py"))
    for path in files:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
                found[node.name].append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in found:
                        found[target.id].append(str(path.relative_to(ROOT)))
    return found


def test_each_name_is_defined_exactly_once():
    found = _definitions()
    for name, where in found.items():
        assert len(where) == 1, f"{name} defined {len(where)} times: {where}"
        assert where == ["src/casual_signal.py"], where


def test_the_loop_and_the_route_ask_the_same_predicate():
    # Drive it: both callers resolve to the one object, so widening the
    # blocklist in one place widens it for both gates.
    from src import agent_loop, casual_signal
    from routes import chat_helpers

    assert agent_loop._is_casual_low_signal is casual_signal._is_casual_low_signal
    assert chat_helpers._is_casual_low_signal is casual_signal._is_casual_low_signal
    assert agent_loop._CASUAL_BLOCKLIST_RE is chat_helpers._CASUAL_BLOCKLIST_RE

    for text, expected in (
        ("hey man", True),
        ("thanks!", True),
        ("hi can you search the web for llama.cpp", False),
        ("please summarise this file", False),
        ("", False),
    ):
        assert agent_loop._is_casual_low_signal(text) is expected, text
        assert chat_helpers._is_casual_low_signal(text) is expected, text
