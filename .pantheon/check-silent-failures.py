#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-17` — handlers that swallow a failure and say nothing about it.

The original row said "several paths where the app could quit silently" and
offered `bare except:` as its acceptance test. There are **zero** bare excepts
in non-test Python and there were when the row was written, so that test passed
on an unfixed tree — a row that gets ticked without a fix. The real population
is `except ...: pass`, and grep cannot count it: `grep -A1` miscounts
multi-line handlers in both directions, which is how the row carried three
different numbers and no scope.

So this parses. Two rules, because a flat count would say the same thing about
`except: pass` around `os.unlink(tmp)` — where swallowing is the entire point —
as about one around a schema migration that then silently never runs:

  HARD (max 0)  a silent handler whose `try` **changes something** — a write, a
                commit, a send, a delete — and that is not a teardown, and that
                carries no comment. These are the ones where the user asked for
                something, it did not happen, and nothing anywhere says so.

  RATCHET       every silent handler with no explanation. It may fall and may
                not rise. Most of the remainder are parse-with-fallback and
                cleanup, where swallowing is right and a comment is the whole
                fix; the number coming down is somebody reading one and
                deciding, which is not work a script can do for them.

"Explained" means a comment anywhere from the line above the `except` to the
`pass` itself. Not a high bar deliberately: the bar is that a person looked.

Usage:  python3 .pantheon/check-silent-failures.py [--max N] [--list]
"""
from __future__ import annotations

import argparse
import ast
import io
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = ("tests/", ".pantheon/")

# A `try` that only tears things down is *supposed* to swallow: the file is
# already gone, the task is already finished, the connection is already closed.
TEARDOWN = (
    "unlink", "remove", "rmtree", "close", "cancel", "kill", "terminate",
    "cleanup", "discard", "shutdown", "stop", "join", "rollback", "disconnect",
)

# A `try` that changes state somebody will look for later.
MUTATION = (
    "save", "write", "commit", "send", "persist", "delete", "insert",
    "update", "execute", "flush", "post", "put", "patch",
)


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split() if not f.startswith(SKIP_PREFIXES)]


def _comment_lines(src: str) -> set[int]:
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


def _called_names(body: list[ast.stmt]) -> str:
    module = ast.Module(body=body, type_ignores=[])
    return " ".join(
        ast.unparse(n.func).lower()
        for n in ast.walk(module) if isinstance(n, ast.Call)
    )


def scan() -> tuple[list[str], list[str]]:
    """(unexplained, unexplained-and-mutating), each `path:line`."""
    unexplained: list[str] = []
    mutating: list[str] = []
    for rel in _tracked():
        src = (ROOT / rel).read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        comments = _comment_lines(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not (len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)):
                    continue
                span = set(range(handler.lineno - 1, handler.body[0].lineno + 1))
                if comments & span:
                    continue
                where = f"{rel}:{handler.lineno}"
                unexplained.append(where)
                called = _called_names(node.body)
                if any(k in called for k in TEARDOWN):
                    continue
                if any(k in called for k in MUTATION):
                    mutating.append(where)
    return unexplained, mutating


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=402,
                    help="ceiling for unexplained silent handlers (may fall, never rise)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    unexplained, mutating = scan()
    print(f"silent handlers  unexplained {len(unexplained)} (max {args.max})  ·  "
          f"unexplained AND mutating {len(mutating)} (max 0)")

    failed = False
    if mutating:
        failed = True
        print("\n  These swallow a failure that changed nothing when it should have "
              "changed something. Log it, surface it, or say in a comment why "
              "losing it is correct:")
        for m in mutating:
            print(f"    {m}")
    if len(unexplained) > args.max:
        failed = True
        print(f"\n  The unexplained count rose from {args.max} to {len(unexplained)}. "
              "This ratchet only comes down: explain the new handler, or do not "
              "write a silent one.")
    if args.list:
        print()
        for u in unexplained:
            print(f"  {u}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
