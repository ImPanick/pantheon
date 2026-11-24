# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2196` — nothing calls `datetime.utcnow()` or `datetime.utcfromtimestamp()`.

Both are deprecated since Python 3.12 and warn on every call on 3.14, the
interpreter CI and the image run, and "scheduled for removal in a future
version" says what a later bump does to a tree that still calls them: a call
that warns today raises `AttributeError` then, on whatever line a request
reaches it. There were 86 bare calls in the product and 43 in the suite.

They now ask `src.utc_clock.utcnow_naive()` (re-exported by `core.database`),
which returns the same naive UTC value the `DateTime` columns store, so no
comparison against a stored time changes. Read by `ast`, so a comment or a
docstring that names the old call is prose, not a call (`Law 20`).
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPRECATED = {"utcnow", "utcfromtimestamp"}


def _tracked_python() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                         text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return sorted(p for p in ROOT.rglob("*.py")
                      if not {"node_modules", "venv", ".venv", ".git"} & set(p.parts))
    return [ROOT / line for line in out.stdout.splitlines() if (ROOT / line).exists()]


def deprecated_calls(source: str) -> list[int]:
    """Line numbers of `<anything>.utcnow()` / `.utcfromtimestamp(...)` calls."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in DEPRECATED]


def test_the_detector_finds_a_call_and_ignores_prose():
    planted = (
        "import datetime as _dt\n"
        "# datetime.utcnow() in a comment\n"
        "def f():\n"
        "    '''datetime.utcnow() in a docstring'''\n"
        "    return _dt.datetime.utcnow(), _dt.datetime.utcfromtimestamp(0)\n"
    )
    assert deprecated_calls(planted) == [5, 5]


def test_no_tracked_python_calls_the_deprecated_utc_clock():
    found = []
    for path in _tracked_python():
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "utcnow" not in source and "utcfromtimestamp" not in source:
            continue
        found += [f"{path.relative_to(ROOT).as_posix()}:{n}" for n in deprecated_calls(source)]
    assert found == [], (
        "datetime.utcnow()/utcfromtimestamp() are deprecated and will be removed; "
        "use src.utc_clock.utcnow_naive() (naive UTC, what the columns store): "
        + ", ".join(found))


def test_the_replacement_is_the_value_the_columns_store():
    from datetime import datetime, timedelta, timezone

    from src.utc_clock import utcnow_naive

    now = utcnow_naive()
    assert now.tzinfo is None
    assert abs(now - datetime.now(timezone.utc).replace(tzinfo=None)) < timedelta(seconds=5)
