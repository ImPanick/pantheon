# SPDX-License-Identifier: AGPL-3.0-or-later
"""No tracked Python file raises a `SyntaxWarning` when it is parsed.

**Measured:** three test files carried an invalid escape (`\\w`, `\\d`, `\\.`)
in a non-raw string — two inside JavaScript pasted into a Python string — and
warned on every collection. Today that is a warning; Python has said it will
become an error, at which point each file stops importing and its tests
vanish from the run rather than fail in it. The fix is one character each; the
check is that the parser says nothing.
"""

import ast
import subprocess
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_tracked_python_file_parses_without_a_warning():
    files = subprocess.run(["git", "ls-files", "-z", "*.py"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split("\0")
    files = [f for f in files if f]
    assert len(files) > 1000, len(files)
    said = []
    for rel in files:
        path = ROOT / rel
        if not path.exists():
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SyntaxWarning)
            ast.parse(path.read_text(encoding="utf-8"), rel)
        said += [f"{rel}:{w.lineno} {w.message}" for w in caught if issubclass(w.category, SyntaxWarning)]
    assert said == [], "\n".join(said)
