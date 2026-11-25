# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2173`: naive UTC "now" is defined once.

`core.database.utcnow_naive` was the canonical helper, and fourteen modules
carried a private copy of its one line (`_now`, `_utcnow`, `_utcnow_naive` —
six of them in the new Apollo code). The definition now lives in
`src/utc_clock.py`, which imports nothing heavier than `datetime`, and
`core.database` re-exports it. The two private names tests freeze
(`task_scheduler._utcnow`, `services.search.ranking._utcnow_naive`) are the
same function under the seam's name.

Before the change fifteen modules define the function.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BODY = "datetime.now(timezone.utc).replace(tzinfo=None)"


def _definitions() -> list[str]:
    found = []
    for root in ("src", "routes", "core", "services", "mcp_servers", "workstation", "netagent"):
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef) or node.args.args:
                    continue
                body = [b for b in node.body
                        if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
                if (len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None
                        and ast.unparse(body[0].value) == BODY):
                    found.append(f"{path.relative_to(REPO).as_posix()}:{node.name}")
    return found


def test_naive_utc_now_is_defined_once():
    assert _definitions() == ["src/utc_clock.py:utcnow_naive"]


def test_every_name_for_it_is_the_one_function():
    from core.database import utcnow_naive as canonical
    from services.search import ranking
    from src import task_scheduler
    from src.utc_clock import utcnow_naive

    assert canonical is utcnow_naive
    assert task_scheduler._utcnow is utcnow_naive
    assert ranking._utcnow_naive is utcnow_naive
    now = utcnow_naive()
    assert now.tzinfo is None


def test_the_clock_does_not_pull_the_database():
    code = ("import sys; import src.utc_clock; "
            "print(any(m == 'sqlalchemy' or m.startswith('sqlalchemy.') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == "False"
