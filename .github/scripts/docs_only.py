#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B434` — the shortcut that reported a green test run on no tests.

`.github/workflows/ci.yml`'s `python-tests` job skips pytest when every changed
file is documentation. That is a sensible saving and it was implemented as:

    changed=$(git diff --name-only "$BASE" "$HEAD" 2>/dev/null || git diff --name-only HEAD~1 HEAD)
    non_docs=$(echo "$changed" | grep -Ev '^(docs/|.*\\.md$|\\.github/[^/]+\\.md$)' || true)
    if [ -z "$non_docs" ]; then docs_only=true

**Read the empty case.** When `changed` is empty — a push whose `before` is the
zero sha, a force-push whose base is gone, a `git diff` that failed for any
reason at all — `echo ""` feeds `grep` one blank line, `$(…)` strips it, and
`non_docs` is empty. Empty means *docs-only*, so pytest is skipped and
**`Python tests (pytest)` reports success having run nothing.** The job whose
name is the strongest claim in the Checks tab is the one with the hole in it.

The two questions had been collapsed into one. "Is every changed file
documentation?" and "could the change set be computed at all?" have different
safe answers, and the shell gave the second one the first one's answer.

So the decision lives here, where it can be called with a list and asked:

    is_docs_only(["docs/setup.md"])    -> True    skip pytest
    is_docs_only(["src/app.py"])       -> False   run pytest
    is_docs_only([])                   -> False   we do not know, so run them

Fail-closed is `False`, not a crash: a run that cannot work out what changed
must still *do the work*, because the whole point of the gate is that it ran.
Refusing outright would trade a false green for a red that tells a contributor
nothing about their change.

As a CLI it prints `docs_only=true|false` on stdout — the step redirects that
straight into `$GITHUB_OUTPUT` — and says why on stderr, where a person reading
the log will find it:

    python3 .github/scripts/docs_only.py --changed-from "$RUNNER_TEMP/changed.txt" >> "$GITHUB_OUTPUT"
    git diff --name-only A B | python3 .github/scripts/docs_only.py

It reads no environment variable of its own. The workflow owns the redirect,
which keeps this a pure function of its argument and keeps a GitHub-owned name
out of the register `.pantheon/check-env-declared.py` holds this project to.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable, Sequence

# The patterns the shell used, kept exactly: `docs/` anywhere in the tree, any
# `.md` file, and a top-level markdown file under `.github/`. Widening this set
# is widening what can be skipped without a test run, so it is a decision with
# a diff rather than a regex somebody tweaks in passing.
DOCS_PATTERNS = (
    re.compile(r"^docs/"),
    re.compile(r".*\.md$"),
    re.compile(r"^\.github/[^/]+\.md$"),
)


def is_documentation(path: str) -> bool:
    return any(p.match(path) for p in DOCS_PATTERNS)


def is_docs_only(changed: Sequence[str]) -> bool:
    """True only when there is at least one changed file and all of them are
    documentation.

    The `at least one` is the whole row. An empty sequence is not a change made
    entirely of documentation — it is a change nobody could measure — and the
    honest answer to *may I skip the tests* is no.
    """
    paths = [p.strip() for p in changed if p and p.strip()]
    if not paths:
        return False
    return all(is_documentation(p) for p in paths)


def explain(changed: Sequence[str]) -> str:
    paths = [p.strip() for p in changed if p and p.strip()]
    if not paths:
        return ("the changed-file list is empty, so this run cannot show that "
                "the change is documentation — running the suite")
    other = [p for p in paths if not is_documentation(p)]
    if other:
        return (f"{len(other)} of {len(paths)} changed files are not "
                f"documentation ({', '.join(other[:5])}) — running the suite")
    return (f"all {len(paths)} changed files are documentation — skipping the "
            f"suite")


def _read(source: Iterable[str]) -> list[str]:
    return [line.strip() for line in source if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--changed-from", metavar="FILE",
                    help="file holding one changed path per line; `-` for stdin")
    ap.add_argument("paths", nargs="*", help="changed paths, if not from a file")
    args = ap.parse_args(argv)

    if args.paths:
        changed = _read(args.paths)
    elif args.changed_from and args.changed_from != "-":
        try:
            with open(args.changed_from, encoding="utf-8") as handle:
                changed = _read(handle)
        except OSError as exc:
            # Fail-closed again: a list we could not read is not a docs-only
            # change, and saying so beats exiting non-zero on a job whose real
            # work is still ahead of it.
            print(f"could not read {args.changed_from}: {exc}", file=sys.stderr)
            changed = []
    else:
        changed = _read(sys.stdin)

    answer = is_docs_only(changed)
    print(explain(changed), file=sys.stderr)
    print(f"docs_only={'true' if answer else 'false'}")
    print(f"changed_count={len(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
