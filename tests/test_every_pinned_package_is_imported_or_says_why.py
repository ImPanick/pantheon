# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1548` — a runtime pin nothing imports says why it is installed.

`pydantic-settings` stayed pinned in `requirements.txt` after `B550` removed
the last `BaseSettings`, and nothing could tell a pin with no importer from one
with forty. `check-pins.py`'s third rule (`unimported_problems`) now holds that
every pin in the runtime file is imported by a Python file in the tree, or
carries a `# Not imported:` line directly above it saying why — and that such a
note is not left on a pin something does import.

Driven through the checker's own function, on the real tree and on a small
requirements file and source tree written here.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-pins.py"


@pytest.fixture(scope="module")
def pins():
    spec = importlib.util.spec_from_file_location("_pantheon_check_pins", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path, requirements: str):
    req = tmp_path / "requirements.txt"
    req.write_text(requirements, encoding="utf-8")
    src = tmp_path / "app.py"
    src.write_text('"""Notes: import pydantic_settings is how one would do it."""\n'
                   "import fastapi\nfrom httpx import Client\n", encoding="utf-8")
    return req, [src]


def test_the_real_tree_holds(pins):
    assert pins.unimported_problems() == []


def test_the_pin_the_row_found_says_why_it_stays(pins):
    """`pydantic-settings` is pinned because two other pins require it, and
    the file says so above it."""
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    number = next(i for i, line in enumerate(lines, 1)
                  if line.startswith("pydantic-settings=="))
    note = pins._comment_block_above(lines, number)
    assert note.startswith("Not imported:") and "mcp" in note, note


def test_a_pin_nothing_imports_fails(pins, tmp_path):
    req, sources = _tree(tmp_path, "fastapi==1.0\nhttpx==0.28.1\npydantic-settings==2.15.0\n")
    problems = pins.unimported_problems(req, sources)
    assert len(problems) == 1 and "`pydantic-settings`" in problems[0], problems
    # a docstring that says "import pydantic_settings" is not an import


def test_a_pin_that_says_why_passes(pins, tmp_path):
    req, sources = _tree(tmp_path, "fastapi==1.0\nhttpx==0.28.1\n"
                                   "# Not imported: mcp requires it.\n"
                                   "pydantic-settings==2.15.0\n")
    assert pins.unimported_problems(req, sources) == []


def test_a_reason_that_stopped_being_true_fails(pins, tmp_path):
    req, sources = _tree(tmp_path, "# Not imported: a framework loads it.\n"
                                   "fastapi==1.0\nhttpx==0.28.1\n")
    problems = pins.unimported_problems(req, sources)
    assert len(problems) == 1 and "no longer true" in problems[0], problems


def test_the_rule_runs_in_main(pins, capsys, monkeypatch):
    """A rule `main()` never calls is the shape a checker row exists to catch."""
    monkeypatch.setattr(pins, "unimported_problems", lambda: ["requirements.txt:1: planted"])
    monkeypatch.setattr(sys, "argv", ["check-pins.py"])
    assert pins.main() == 1
    assert "planted" in capsys.readouterr().out
