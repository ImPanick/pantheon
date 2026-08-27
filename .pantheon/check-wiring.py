#!/usr/bin/env python3
"""Count element lookups that resolve to nothing — the drift metric.

A backend with no caller and an element id with no markup are the same disease:
something was built and never wired, and nothing in CI noticed because nothing
was broken. This counts the JS half of it.

    python3 .pantheon/check-wiring.py            # report
    python3 .pantheon/check-wiring.py --max 78   # fail if it grew

Scope, stated so the number means something (Law 5): static-string
`getElementById("...")` calls across tracked files under static/js, excluding
static/lib; minus ids present in any tracked .html; minus ids the JS itself
creates at runtime via id="...", .id = "...", or setAttribute("id", ...).
Dynamic lookups built from variables are invisible to this and always will be —
this is a floor on the drift, never a ceiling.
"""
import re
import signal
import sys
import pathlib
import subprocess
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tracked(*globs):
    out = subprocess.run(["git", "ls-files", *globs], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out if "/lib/" not in f]


def read(f):
    try:
        return (ROOT / f).read_text(errors="replace")
    except OSError:
        return ""


def main() -> int:
    limit = None
    if "--max" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max") + 1])

    html_ids = set()
    for f in tracked("*.html"):
        html_ids |= set(re.findall(r'id="([^"]+)"', read(f)))

    js_files = tracked("static/js")
    blob = "\n".join(read(f) for f in js_files)
    made = set(re.findall(r"""id=\\?["']([A-Za-z0-9_-]+)""", blob))
    made |= set(re.findall(r"""\.id\s*=\s*['"]([A-Za-z0-9_-]+)['"]""", blob))
    made |= set(re.findall(r"""setAttribute\(\s*['"]id['"]\s*,\s*['"]([A-Za-z0-9_-]+)['"]""", blob))

    where = {}
    for f in js_files:
        for i in re.findall(r"getElementById\(\s*['\"]([A-Za-z0-9_-]+)['\"]", read(f)):
            where.setdefault(i, set()).add(f)

    looked = set(where)
    known = html_ids | made
    dead = sorted(i for i in looked - known if len(i) > 3 and not i.startswith("__"))

    print(f"lookups {len(looked)}  ·  in markup {len(looked & html_ids)}  ·  "
          f"made at runtime {len(looked & made - html_ids)}  ·  UNRESOLVED {len(dead)}")
    print()
    for prefix, n in Counter(d.split("-")[0] for d in dead).most_common():
        ids = [d for d in dead if d.split("-")[0] == prefix]
        print(f"  {n:>3}  {prefix + '-*':<14} {', '.join(sorted(ids)[:4])}"
              f"{' …' if len(ids) > 4 else ''}")

    if limit is None:
        return 0
    if len(dead) > limit:
        print(f"\nFAIL — {len(dead)} unresolved, ceiling is {limit}. Law 13: nothing ships "
              f"half-wired. Wire it, or do not merge the half.")
        return 1
    if len(dead) < limit:
        print(f"\n{len(dead)} unresolved, under the ceiling of {limit}. Lower the ceiling.")
    return 0


if __name__ == "__main__":
    # `| head` closes the pipe; that is not an error worth a traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
