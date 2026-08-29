#!/usr/bin/env python3
"""Count modules imported under more than one URL — the accidental-fork metric.

ES module identity is keyed on the RESOLVED URL, query string included, and this
tree has no import map. So `./tasks.js` and `./js/tasks.js?v=20260723…` are two
different modules. The browser instantiates both, each with its own copy of every
module-level variable, and neither knows the other exists.

Nothing breaks loudly when this happens. A registry populated through one
specifier is simply empty when read through the other, and the feature that
depended on it does nothing — quietly, forever. That is Law 14's failure mode
arrived at by accident: a second scaffolding nobody chose to build.

    python3 .pantheon/check-specifiers.py           # report
    python3 .pantheon/check-specifiers.py --max 0   # fail if any module forks

Scope, stated so the number means something (Law 5): every static `import … from
'…'`, dynamic `import('…')` and `<script src="…">` in tracked `.js` and `.html`
files under `static/`, excluding `static/lib/`. Specifiers are resolved relative
to the importing file and compared by path; a module counts as forked when the
same path is reached under two or more distinct query strings (a bare import and
a versioned one are two). Absolute `http(s)://` and protocol-relative URLs are
out of scope — they are not this tree's modules.
"""
import collections
import pathlib
import re
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

IMPORT_RE = re.compile(
    r"""(?:^|[^\w.])(?:import\s*\(?\s*|from\s+)['"]([^'"]+\.js(?:\?[^'"]*)?)['"]"""
)
SCRIPT_RE = re.compile(r"""<script[^>]*\ssrc=["']([^"']+\.js(?:\?[^"']*)?)["']""")


def tracked():
    out = subprocess.run(["git", "ls-files", "static"], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out
            if f.endswith((".js", ".html")) and not f.startswith("static/lib/")]


def resolve(importer: str, spec: str):
    """Return the repo-relative path a specifier points at, or None if out of scope."""
    if spec.startswith(("http://", "https://", "//")):
        return None
    path, _, _query = spec.partition("?")
    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        base = pathlib.PurePosixPath(importer).parent
        resolved = (base / path).as_posix()
        while "/../" in resolved:
            resolved = re.sub(r"[^/]+/\.\./", "", resolved, count=1)
        resolved = resolved.replace("./", "")
    if "static/lib/" in resolved:
        return None
    return resolved


def scan():
    """path -> {query: [importer, ...]}. A bare import has query ''."""
    seen = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in tracked():
        text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        for m in list(IMPORT_RE.finditer(text)) + list(SCRIPT_RE.finditer(text)):
            spec = m.group(1)
            path = resolve(f, spec)
            if path is None:
                continue
            _, _, query = spec.partition("?")
            seen[path][query].append(f)
    return seen


def main() -> int:
    limit = None
    if "--max" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max") + 1])

    seen = scan()
    forked = {p: q for p, q in seen.items() if len(q) > 1}
    total_specs = sum(len(q) for q in seen.values())

    print(f"modules {len(seen)}  ·  specifiers {total_specs}  ·  FORKED {len(forked)}")
    if forked:
        print()
        for path in sorted(forked):
            print(f"    {path}")
            for query in sorted(forked[path]):
                label = "(bare)" if not query else "?" + query
                where = ", ".join(sorted(set(forked[path][query])))
                print(f"        {label:<34} {where}")

    if limit is not None and len(forked) > limit:
        print(f"\nFAIL: {len(forked)} forked, ceiling is {limit}.")
        print("Every listed module is instantiated twice in the browser, with two")
        print("copies of its state. Pick ONE specifier per module and use it everywhere.")
        return 1
    return 0


if __name__ == "__main__":
    # `| head` closes the pipe; not an error worth a traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
