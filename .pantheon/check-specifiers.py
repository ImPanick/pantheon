#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
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
'…'`, dynamic `import('…')`, `<script src="…">`, `<link rel="…preload" href="…">`
and service-worker precache entry in tracked `.js` and `.html` files under
`static/`, excluding `static/lib/`. Specifiers are resolved relative to the
importing file and compared by path; a module counts as forked when the same
path is reached under two or more distinct query strings (a bare import and a
versioned one are two). Absolute `http(s)://` and protocol-relative URLs are out
of scope — they are not this tree's modules.

**The last two entered scope on 2026-09-14 (`B58`, absorbing `B09`), and this
checker reported `FORKED 0` until they did.** The rule was already right; it was
looking at four of the six places a URL is written. Widening it found four
forked assets that had been there the whole time:

  * `static/js/chat.js` — preloaded at `?v=20260815toolapproval4` and executed
    at `?v=20260829trustladder1`. The HTTP cache and the module map are keyed on
    the full URL, query included, so the second-largest module in the shell
    (372 KB) was fetched **twice on every cold load**, both on the critical
    path. `git log -L` says the preload line has not been edited since the fork
    baseline while the script tag has been bumped twice — the bump happened
    twice without anybody knowing the second copy existed.
  * `admin.js`, `emailInbox.js`, `sidebar-layout.js` — precached bare in
    `static/sw.js` and imported with a version. `sw.js`'s fetch handler matches
    with `cache.match(e.request)` and **no `ignoreSearch`**, so those three
    entries were downloaded at install and could never be served to anything.
    That is the third recurrence of the defect `P3-11` closed eight of and
    `B54` closed nine of, and no row had named it.

`FORBIDDEN.md`'s own cache-buster control could not have caught the first:
`tests/test_tool_approval_frontend_routing.py` asserts the version string is a
**substring** of `index.html`, and it is — at line 3256. A substring test cannot
see a *second* copy under a different string. Only a set comparison can, which
is the argument for widening this file rather than adding an assertion there.
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
# `B58`. A `modulepreload` opens a real request for a real URL; a stale one is a
# second copy of the module fetched and thrown away.
LINK_RE = re.compile(
    r"""<link[^>]*\srel=["'](?:module)?preload["'][^>]*\shref=["']([^"']+\.js(?:\?[^"']*)?)["']"""
)
LINK_REV_RE = re.compile(
    r"""<link[^>]*\shref=["']([^"']+\.js(?:\?[^"']*)?)["'][^>]*\srel=["'](?:module)?preload["']"""
)
# `B58`. The service worker's precache list is a list of URLs it will fetch and
# then try to serve — and its fetch handler matches without `ignoreSearch`, so an
# entry whose query does not match the importer's is downloaded and never used.
PRECACHE_RE = re.compile(r"""["'](/static/[^"']+\.js(?:\?[^"']*)?)["']""")


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
        matches = (list(IMPORT_RE.finditer(text))
                   + list(SCRIPT_RE.finditer(text))
                   + list(LINK_RE.finditer(text))
                   + list(LINK_REV_RE.finditer(text)))
        if f.endswith("sw.js"):
            matches += list(PRECACHE_RE.finditer(text))
        for m in matches:
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
