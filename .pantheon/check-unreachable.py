#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Working code with no door. `P3-15`.

    python3 .pantheon/check-unreachable.py                # the inventory
    python3 .pantheon/check-unreachable.py --max-routes 60
    python3 .pantheon/check-unreachable.py --quiet

THE AUDIT THIS AUTOMATES RAN BY HAND AND PRODUCED THE 21 `H` ROWS.

On 2026-08-30 four read-only agents swept the backend, the frontend, the
configuration surface, and every place the product *claims* a capability. They
found a complete embedding-model manager with zero pixels (`H04`), session
cleanup with a dry-run nobody could reach (`H10`), and an email approval queue
the model told users about on a screen that did not exist (`H01`). None of them
was broken. Every one of them was already paid for.

That audit is this file's specification. Its findings are the acceptance test —
`tests/test_unreachable_surface.py` asserts the shapes are still detected — and
what it established is why the implementation looks the way it does:

**THE ROUTE COUNT IS 500, NOT 301.** `routes/*.py` at top level is 304; another
173 live in `routes/<subdir>/*.py` and 5 in `companion/`. Three of the audit's
best findings are in the half a naive scan omits. And a flat walk of `app.routes`
returns 69 — this FastAPI keeps included routers NESTED — so the walk here
recurses. That single detail is the difference between a checker that finds
`H04` and one that reports a clean tree.

**PATH MATCHING NEEDS MORE THAN A LITERAL SEARCH.** A frontend that writes

    fetch(`${API_BASE}/api/gallery/${id}/rename`)

shares no substring with `/api/gallery/{image_id}/rename`. Both sides are
normalised to a segment pattern — every parameter, template hole and variable
becomes `*` — and compared as patterns. The hand audit found that a second,
stricter pass disagreed with the first on 8 of 98 routes and was right all 8
times, so the strict comparison is the one implemented.

**IT REPORTS, IT DOES NOT ACCUSE.** A route with no frontend caller is not
necessarily dead: an API token holder, a CLI, a webhook receiver or the agent's
own `app_api` tool may be the caller. So this prints an inventory and holds a
ceiling, in the shape `check-wiring` and `check-outbound` already use. The
`ALLOWED` map below names the callers that are not the frontend — each entry a
decision, with the reason.
"""
import ast
import json
import pathlib
import re
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Route prefixes whose caller is deliberately not the browser. Each entry says
# who calls it, because "something else probably uses this" is how a dead route
# stays in the tree for a year.
ALLOWED = {
    "/api/auth/": "the login page and every authenticated fetch; not a feature surface",
    "/api/mcp/": "MCP clients speak this directly; there is no page for it",
    "/api/tokens/": "API-token holders, and the tokens page manages a subset",
    "/metrics": "Prometheus (P16-12). Deliberately has no UI.",
    "/api/diagnostics/": "the diagnostics panel plus `pantheon-*` CLI tooling",
    "/api/webhooks/incoming": "external senders — a receiver has no caller here by definition",
    # P18-01/P18-04. The browser no longer holds this path: it reads it from
    # `GET /api/email/oauth/providers`, whose whole purpose is that "which
    # hosts can be linked, and where does the flow start" is answered by the
    # module that enforces it rather than restated in JavaScript (`Law 13` —
    # the two spellings disagreed, and picking Gmail showed no button while
    # Google Workspace showed one). Making the caller dynamic is what removed
    # the literal this checker matches on, so the route reads as orphaned and
    # is not. The provider endpoint itself stays statically reachable, which is
    # what keeps this from hiding a genuinely dead pair.
    # P18-05 made the provider a path parameter, so the key moved with it. The
    # URL a browser hits did not change — `/api/email/oauth/google/authorize`
    # still resolves — but this checker reads the route table, where the path is
    # now the pattern.
    "/api/email/oauth/{provider_id}/authorize": "settings.js follows the `authorize` path served by /api/email/oauth/providers",
    "/openapi.json": "FastAPI mounts this itself; it is the schema, not a feature",
    "/docs": "FastAPI's own Swagger UI, mounted by the framework",
    "/redoc": "FastAPI's own ReDoc UI, mounted by the framework",
}

_FRONTEND_GLOBS = ("static/*.js", "static/js", "static/*.html")
_PARAM = re.compile(r"\{[^}]*\}")           # /api/x/{id}/y
_TEMPLATE = re.compile(r"\$\{[^}]*\}")      # `${API_BASE}/api/x/${id}/y`


def tracked(*globs):
    out = subprocess.run(["git", "ls-files", *globs], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out if "/lib/" not in f]


def normalise(path: str) -> str:
    """A path as a segment pattern: every hole becomes `*`.

    This is the whole reason a literal search does not work. `/api/gallery/{id}`
    and `` `${API_BASE}/api/gallery/${x}` `` share no useful substring and are
    the same route.
    """
    path = _TEMPLATE.sub("*", path)
    path = _PARAM.sub("*", path)
    path = re.sub(r"//+", "/", path)
    path = path.split("?")[0].split("#")[0]
    if len(path) > 1:
        path = path.rstrip("/")
    segments = [("*" if not s or s == "*" else s) for s in path.split("/")]
    return "/".join(segments)


# ── the routes ──────────────────────────────────────────────────────────────

def app_routes() -> list:
    """Every mounted route, by importing the app and RECURSING.

    A flat `app.routes` returns 69 on this codebase because included routers are
    kept nested; recursion returns ~505. The audit's note about that is the
    single most load-bearing sentence in `P3-15`.
    """
    sys.path.insert(0, str(ROOT))
    import app as app_module                                   # noqa: F401

    found = []

    seen = set()

    def walk(node, depth=0):
        if depth > 8 or id(node) in seen:
            return
        seen.add(id(node))
        for route in getattr(node, "routes", []) or []:
            path = getattr(route, "path", None)
            methods = sorted(getattr(route, "methods", set()) or [])
            if path:
                found.append((path, methods))
            # An included router is wrapped, and the wrapper's name and shape
            # are version-specific. On this FastAPI it is `_IncludedRouter`,
            # whose `routes`/`router`/`app` are all None and whose real content
            # hangs off `original_router` — which is why a flat walk returns 69
            # and the naive recursion returns the same 69 while looking like it
            # tried. Every plausible attribute is followed rather than the one
            # this version happens to use.
            for attr in ("original_router", "router", "app", "routes"):
                inner = getattr(route, attr, None)
                if inner is None or inner is node:
                    continue
                if attr == "routes":
                    for sub in inner or []:
                        walk(sub, depth + 1)
                else:
                    walk(inner, depth + 1)

    walk(app_module.app)
    return found


def routes_from_source() -> list:
    """Fallback: every `@router.<verb>("...")` decorator in the tree.

    Used when the app will not import (a missing optional dependency, a
    half-configured checkout). It over-counts — a route on a router nobody
    mounts still appears — which is the safe direction for a checker whose job
    is to find things nobody reaches.
    """
    found = []
    for entry in ("routes", "companion", "app.py"):
        base = ROOT / entry
        files = [base] if base.is_file() else sorted(base.rglob("*.py")) if base.is_dir() else []
        for f in files:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            prefix = ""
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                    for kw in node.keywords:
                        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                            prefix = str(kw.value.value)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    verb = getattr(dec.func, "attr", "")
                    if verb not in ("get", "post", "put", "delete", "patch"):
                        continue
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        found.append((prefix + str(dec.args[0].value), [verb.upper()]))
    return found


# ── the callers ─────────────────────────────────────────────────────────────

_URLISH = re.compile(r"""['"`]([^'"`\n]*?/api/[^'"`\n]*?)['"`]""")
_BARE = re.compile(r"""['"`](/(?:metrics|docs|redoc|openapi\.json)[^'"`\n]*)['"`]""")


def frontend_paths() -> set:
    """Every `/api/...`-shaped string the frontend mentions, as a pattern."""
    seen = set()
    for f in tracked(*_FRONTEND_GLOBS):
        try:
            text = (ROOT / f).read_text(errors="replace")
        except OSError:
            continue
        for match in list(_URLISH.findall(text)) + list(_BARE.findall(text)):
            idx = match.find("/api/")
            path = match[idx:] if idx >= 0 else match
            seen.add(normalise(path))
            # A caller may hold the head and build the tail, or vice versa. The
            # hand audit needed a head-plus-tail probe as its second pass; this
            # is that, kept cheap: every prefix of the pattern is recorded, so a
            # route whose tail is assembled elsewhere still counts as reached.
            parts = normalise(path).split("/")
            for i in range(3, len(parts)):
                seen.add("/".join(parts[:i]))
    return seen


def unreachable():
    """(findings, total, source) — routes no frontend string resolves to."""
    try:
        routes, source = app_routes(), "app"
    except Exception as exc:                                   # pragma: no cover
        print(f"note: could not import the app ({type(exc).__name__}: {exc}); "
              f"falling back to a source scan", file=sys.stderr)
        routes, source = routes_from_source(), "source"

    called = frontend_paths()
    findings = []
    seen_paths = set()
    for path, methods in routes:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if any(path.startswith(prefix) for prefix in ALLOWED):
            continue
        pattern = normalise(path)
        if pattern in called:
            continue
        findings.append((path, methods))
    return sorted(findings), len(seen_paths), source


def main() -> int:
    quiet = "--quiet" in sys.argv
    ceiling = None
    if "--max-routes" in sys.argv:
        ceiling = int(sys.argv[sys.argv.index("--max-routes") + 1])

    findings, total, source = unreachable()

    if not quiet:
        print(f"routes {total} (via {source})  ·  no frontend caller {len(findings)}"
              + (f"  ·  ceiling {ceiling}" if ceiling is not None else ""))
        print()
        by_area = {}
        for path, methods in findings:
            area = "/".join(path.split("/")[:3]) or path
            by_area.setdefault(area, []).append((path, methods))
        for area in sorted(by_area, key=lambda a: (-len(by_area[a]), a)):
            rows = by_area[area]
            print(f"  {len(rows):>3}  {area}")
            for path, methods in sorted(rows)[:4]:
                print(f"        {','.join(methods) or '-':<18} {path}")
            if len(rows) > 4:
                print(f"        … and {len(rows) - 4} more")

    if ceiling is not None and len(findings) > ceiling:
        print(f"\nFAIL — {len(findings)} routes with no frontend caller, ceiling is "
              f"{ceiling}.\nEither wire it, delete it, or add its real caller to "
              f"ALLOWED with the reason.")
        return 1
    if not quiet:
        print("\nThis is an inventory, not an accusation: an API token, a CLI, a "
              "webhook\nsender or the agent's own app_api tool may be the caller. "
              "The ceiling is\nwhat stops the list growing while nobody looks.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
