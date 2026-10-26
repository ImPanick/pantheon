# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a checker reads the tree: which files are ours, and their comments blanked.

Two helpers every census in `.pantheon/` needs, written once (`Law 14`), and
stdlib only — CI runs most checkers with the system `python3` and nothing
installed, so nothing here may import the product.

``tracked_files(*pathspecs, root=…)``
    `git ls-files` for the pathspecs, **each path once**. `B571`: during a
    conflicted merge `git ls-files` prints an unmerged path once per stage —
    three times — and sixteen checkers fed that list straight into a per-file
    scan, so on the `P11`/`P12` merge `silent-failures` said 405 against a
    ceiling of 402 and `auth-map` said 45 against 43, and neither number was
    real. Eighteen call sites each spelled the listing by hand; this is the
    one spelling. `-z`, so a path is never split on a space or quoted.

``strip_comments(text, …)`` / ``mode_for(path)``
    The one comment blanker, loaded from `.pantheon/check-specifiers.py` where
    it lives (`B84`, `B290`). `B410`: three checkers still carried
    `re.sub(r"/\\*.*?\\*/", …)`, which cannot tell a comment from a string, so
    `'image/*,video/*'` opens a "comment" the next `*/` in the file closes.
    Loaded lazily, so `check-specifiers.py` can import `tracked_files` from
    here without a cycle.

Checkers import it the way `check-ledger.py` imports `ledger.claims`::

    sys.path.insert(0, str(ROOT / ".pantheon"))
    from ledger.source import tracked_files
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPECIFIERS = ROOT / ".pantheon" / "check-specifiers.py"


def tracked_files(*pathspecs: str, root=None, check: bool = True) -> list[str]:
    """Tracked paths matching `pathspecs` (all of them when none), in git's
    order, each once however many index stages it has.

    `check=False` answers `[]` when git fails (no git, not a repository), for
    the callers that already treated a failed listing as an empty one; the
    default raises, as `check=True` did at the callers that asked for it.
    """
    args = ["git", "ls-files", "-z"]
    if pathspecs:
        args += ["--", *pathspecs]
    proc = subprocess.run(args, cwd=str(root or ROOT), capture_output=True,
                          text=True, check=check)
    if proc.returncode != 0:
        return []
    return list(dict.fromkeys(p for p in proc.stdout.split("\0") if p))


_blanker = None


def _specifiers():
    global _blanker
    if _blanker is None:
        spec = importlib.util.spec_from_file_location(
            "_pantheon_check_specifiers_for_checkers", _SPECIFIERS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _blanker = module
    return _blanker


def strip_comments(text: str, html: bool = False, *, mode: str = "",
                   embedded: bool = True) -> str:
    """`check-specifiers.strip_comments` — see its docstring."""
    return _specifiers().strip_comments(text, html, mode=mode, embedded=embedded)


def mode_for(path) -> str:
    """`check-specifiers.mode_for` — `js`, `css` or `html` for a file name."""
    return _specifiers().mode_for(path)
