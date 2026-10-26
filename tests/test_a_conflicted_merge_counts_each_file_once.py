# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B571` — a checker counts each file once, even in the middle of a merge.

On the `P11`/`P12` merge the gate failed three times with numbers nobody could
reproduce: `silent-failures` said 405 against a ceiling of 402 and `auth-map`
said *"admin decisions outside `require_admin` rose from 43 to 45"*. Both were
artefacts. `git ls-files` prints an unmerged path **once per index stage** —
three times for a conflicted file — and every checker fed that list straight
into a per-file scan, so `src/upload_handler.py`'s two silent handlers were
counted six times. Sixteen checkers and the release gate each spelled the
listing by hand; they now share `tracked_files` in `.pantheon/ledger/source.py`.

The row's `Verify` is the second test: a checker run with a deliberately
conflicted index reports what it reports with a clean one. The third stops an
eighteenth hand-spelled listing from coming back.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANTHEON = ROOT / ".pantheon"


def _git(*args, cwd):
    run = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                         text=True, timeout=60)
    return run


def _conflicted_repo(tmp_path: Path, rel: str, ours: str, theirs: str, resolved: str) -> Path:
    """A repository whose index holds `rel` at three stages, with `resolved`
    in the working tree and not yet added — the integrator's state between
    fixing the file and running the gate."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@example.invalid", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 0\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)
    _git("checkout", "-qb", "other", cwd=repo)
    path.write_text(theirs, encoding="utf-8")
    _git("commit", "-qam", "theirs", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    path.write_text(ours, encoding="utf-8")
    _git("commit", "-qam", "ours", cwd=repo)
    merge = _git("merge", "other", cwd=repo)
    assert merge.returncode != 0, "the fixture was meant to conflict"
    path.write_text(resolved, encoding="utf-8")
    return repo


def _source_module():
    spec = importlib.util.spec_from_file_location(
        "_b571_ledger_source", PANTHEON / "ledger" / "source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracked_files_lists_an_unmerged_path_once(tmp_path):
    repo = _conflicted_repo(tmp_path, "src/a.py", "x = 1\n", "x = 2\n", "x = 3\n")
    raw = _git("ls-files", cwd=repo).stdout.split()
    assert raw.count("src/a.py") == 3, raw  # the fixture is really conflicted
    assert _source_module().tracked_files(root=repo) == ["src/a.py"]
    assert _source_module().tracked_files("*.py", root=repo) == ["src/a.py"]


SILENT = '''\
def save_it(store):
    try:
        store.flush()
    except Exception:
        pass


def other(x):
    try:
        return int(x)
    except ValueError:
        pass
'''


def test_a_checker_counts_the_same_with_a_conflicted_index(tmp_path):
    """`silent-failures`, the checker that cried 405, run as CI runs it over a
    repository mid-merge and again once the file is added."""
    repo = _conflicted_repo(tmp_path, "src/handlers.py",
                            SILENT.replace("flush", "save"),
                            SILENT.replace("flush", "write"), SILENT)
    (repo / ".pantheon").mkdir()
    shutil.copy2(PANTHEON / "check-silent-failures.py", repo / ".pantheon")
    shutil.copytree(PANTHEON / "ledger", repo / ".pantheon" / "ledger",
                    ignore=shutil.ignore_patterns("__pycache__"))

    def count():
        run = subprocess.run([sys.executable, ".pantheon/check-silent-failures.py",
                              "--max", "999"], cwd=str(repo), capture_output=True,
                             text=True, timeout=120)
        found = re.search(r"unexplained (\d+) \(max", run.stdout)
        assert found, run.stdout + run.stderr
        return int(found.group(1))

    assert _git("ls-files", "src/handlers.py", cwd=repo).stdout.split().count(
        "src/handlers.py") == 3
    conflicted = count()
    _git("add", "src/handlers.py", cwd=repo)
    assert conflicted == count() == 2, conflicted


#: The one listing that is not `tracked_files`, with its reason. It may only
#: shrink.
HAND_LISTED = {
    # Reads `--others` as well as the index — a test file that exists and is
    # not yet added is still one the suite runs — and counts a *set*, so an
    # unmerged path cannot be counted twice there.
    ".pantheon/check-ledger.py": "B571",
}


def _ls_files_calls(path: Path) -> list:
    """Line numbers of every list/tuple literal spelling `git ls-files`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 2:
            first, second = node.elts[0], node.elts[1]
            if (isinstance(first, ast.Constant) and first.value == "git"
                    and isinstance(second, ast.Constant) and second.value == "ls-files"):
                found.append(node.lineno)
    return found


def test_no_checker_spells_the_listing_by_hand():
    """Read with `ast`, so a docstring describing `git ls-files` is not a
    call (`Law 20`). The helper itself is the one place it is spelled."""
    offenders = []
    checked = 0
    for path in sorted(PANTHEON.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == ".pantheon/ledger/source.py" or rel in HAND_LISTED:
            continue
        checked += 1
        offenders += [f"{rel}:{line}" for line in _ls_files_calls(path)]
    assert checked > 30, checked
    assert not offenders, (
        "a checker lists the tree with its own `git ls-files`; use "
        "`ledger.source.tracked_files`, which counts an unmerged path once "
        f"(`B571`): {offenders}")
    for rel in HAND_LISTED:
        assert _ls_files_calls(ROOT / rel), f"{rel} no longer lists by hand — drop it"
    assert _ls_files_calls(PANTHEON / "ledger" / "source.py"), "the scan sees nothing"
