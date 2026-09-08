# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-17` — the checker that counts handlers which swallow a failure.

The row it serves is a lesson in acceptance tests. It said "fail loudly", named
`bare except:` as the thing to count, and **there were zero of those when it was
written** — so its `Verify:` line passed on an unfixed tree, and the row would
have been ticked by anyone who ran it. It also carried three different counts of
the real population (199, then 250, then 314) because it was measured with
`grep -A1`, which miscounts multi-line handlers in both directions.

So the checker parses, and the tests below drive it against fixtures rather than
against the tree: a checker whose only evidence is "it passes on the repo it was
written for" is the same mistake one layer up.

Two rules, because a flat count would say the same thing about `except: pass`
around `os.unlink(tmp)` — where swallowing is the entire point — as about one
around a schema migration that then silently never runs.
"""

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-silent-failures.py"


def _load_checker(root: Path):
    """The real checker module, pointed at a fixture tree instead of the repo."""
    spec = importlib.util.spec_from_file_location("silent_failures_checker", _CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # not __main__, so main() does not run
    module.ROOT = root
    return module


def _scan(tmp_path: Path, source: str) -> tuple[list[str], list[str]]:
    """Run the checker's own scanner over a one-file fixture repo.

    A fixture rather than the repo: a checker whose only evidence is "it passes
    on the tree it was written for" is this row's own mistake one layer up.
    """
    (tmp_path / "mod.py").write_text(textwrap.dedent(source), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                   capture_output=True)
    return _load_checker(tmp_path).scan()


def test_a_silent_handler_around_a_write_is_the_hard_failure(tmp_path):
    unexplained, mutating = _scan(tmp_path, """
        def persist(path, data):
            try:
                path.write_text(data)
            except Exception:
                pass
    """)
    assert len(unexplained) == 1
    assert len(mutating) == 1


def test_a_silent_handler_around_a_teardown_is_not(tmp_path):
    # `except: pass` around `os.unlink(tmp)` is not a defect — the file being
    # gone already is the state it wants. Counting it the same way is how a
    # number stops meaning anything.
    unexplained, mutating = _scan(tmp_path, """
        import os

        def cleanup(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
    """)
    assert len(unexplained) == 1, "still counted in the ratchet"
    assert mutating == [], "but not the hard rule"


def test_a_teardown_beside_a_write_is_still_a_teardown(tmp_path):
    # The order matters: a `try` that removes the old file and writes the new
    # one is a replace, and the swallow covers both. Classifying on the write
    # alone would make every atomic-write helper a hard failure.
    _, mutating = _scan(tmp_path, """
        import os

        def replace(old, new, data):
            try:
                new.write_text(data)
                os.unlink(old)
            except Exception:
                pass
    """)
    assert mutating == []


@pytest.mark.parametrize("where", ["above", "beside", "inside"])
def test_a_comment_anywhere_in_the_handler_counts_as_an_explanation(tmp_path, where):
    # The bar is deliberately low — the bar is that a person looked at it.
    bodies = {
        "above": """
            def persist(path, data):
                try:
                    path.write_text(data)
                # the caller re-reads and retries; losing this write is fine
                except Exception:
                    pass
        """,
        "beside": """
            def persist(path, data):
                try:
                    path.write_text(data)
                except Exception:  # the caller re-reads and retries
                    pass
        """,
        "inside": """
            def persist(path, data):
                try:
                    path.write_text(data)
                except Exception:
                    # the caller re-reads and retries
                    pass
        """,
    }
    unexplained, mutating = _scan(tmp_path, bodies[where])
    assert unexplained == []
    assert mutating == []


def test_a_handler_that_does_anything_at_all_is_not_silent(tmp_path):
    # `pass` is the whole population. A handler that logs, re-raises, or
    # returns a fallback has said something, whatever else is wrong with it.
    unexplained, _ = _scan(tmp_path, """
        import logging
        logger = logging.getLogger(__name__)

        def persist(path, data):
            try:
                path.write_text(data)
            except Exception as exc:
                logger.warning("could not persist: %s", exc)

        def other(path, data):
            try:
                path.write_text(data)
            except Exception:
                raise
    """)
    assert unexplained == []


def test_a_multi_line_handler_is_counted_once(tmp_path):
    # The failure that gave this row three different numbers. `grep -A1` sees
    # the `except` line and the line after it, so a handler whose `pass` is two
    # lines down is missed and a `try` whose next line is another `except` is
    # double counted.
    unexplained, _ = _scan(tmp_path, """
        def persist(path, data):
            try:
                path.write_text(data)
            except (
                OSError,
                ValueError,
            ):
                pass
    """)
    assert len(unexplained) == 1


def test_silent_means_the_handler_does_nothing_at_all(tmp_path):
    # "silent" is `pass` *and nothing else*. A handler that starts with `pass`
    # and then does something has said something, and counting it would inflate
    # the ratchet with handlers that are already fine.
    unexplained, _ = _scan(tmp_path, """
        import logging
        logger = logging.getLogger(__name__)

        def persist(path, data):
            try:
                path.write_text(data)
            except Exception as exc:
                pass
                logger.warning("could not persist: %s", exc)
    """)
    assert unexplained == []


def test_the_hard_rule_fails_the_run_and_not_only_the_report(tmp_path, monkeypatch, capsys):
    # M8: `failed = False` on the mutating branch leaves the message printed and
    # the exit code green, which is the shape of a check nobody notices is off.
    (tmp_path / "mod.py").write_text(
        "def persist(path, data):\n"
        "    try:\n"
        "        path.write_text(data)\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    checker = _load_checker(tmp_path)
    monkeypatch.setattr(sys, "argv", ["check-silent-failures.py"])
    assert checker.main() == 1
    assert "Log it, surface it" in capsys.readouterr().out


def test_tests_are_not_scanned(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_a():\n    try:\n        save()\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    unexplained, _ = _scan(tmp_path, "x = 1\n")
    assert unexplained == []


# ── against the real tree ─────────────────────────────────────────────────────


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_CHECKER), *args],
                          cwd=str(_REPO), capture_output=True, text=True, timeout=180)


def test_no_silent_handler_in_the_tree_hides_a_mutation():
    proc = _run()
    assert proc.returncode == 0, proc.stdout
    assert "unexplained AND mutating 0 (max 0)" in proc.stdout


def test_the_ratchet_is_at_or_below_where_ci_holds_it():
    ci = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check-silent-failures.py --max 402" in ci, (
        "CI's ceiling moved; if it moved down that is the point, and this "
        "line moves with it"
    )
    proc = _run("--max", "402")
    assert proc.returncode == 0, proc.stdout


def test_the_ratchet_actually_bites():
    # A ceiling nobody has watched reject anything is a number in a file.
    proc = _run("--max", "0")
    assert proc.returncode == 1
    assert "only comes down" in proc.stdout
