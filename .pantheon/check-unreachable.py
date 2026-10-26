#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Working code with no door. `P3-15`.

    python3 .pantheon/check-unreachable.py                # the inventory
    python3 .pantheon/check-unreachable.py --max-routes N   # CI's N: ci.yml
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
if str(ROOT / ".pantheon") not in sys.path:
    sys.path.insert(0, str(ROOT / ".pantheon"))
from ledger.source import mode_for, strip_comments, tracked_files  # noqa: E402

# Route prefixes whose caller is deliberately not the browser. Each entry says
# who calls it, because "something else probably uses this" is how a dead route
# stays in the tree for a year.
ALLOWED = {
    "/api/auth/": "the login page and every authenticated fetch; not a feature surface",
    "/api/mcp/": "MCP clients speak this directly; there is no page for it",
    "/api/tokens/": "API-token holders, and the tokens page manages a subset",
    "/metrics": "Prometheus (P16-12). Deliberately has no UI.",
    # `B1474`. A page, not a fetch: `static/js/codeRunner.js` frames it
    # (`iframe.src`) to run a Python block in an opaque-origin sandbox.
    "/python-sandbox": "codeRunner.js frames it for a Python block (`B1474`)",
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
    # `B212`, 2026-09-16: these three used to say "mounted by the framework",
    # which stopped being true when `app.py` took `/docs` and `/redoc` over to
    # serve them from vendored bytes. The schema has a caller in the tree and
    # it is not a browser, which is why no page links it.
    "/openapi.json": "src/tools/system.py's do_app_api (action: endpoints) fetches it over the loopback",
    "/docs": "the API browser, served by app.py from static/lib/swagger-ui; an operator types this URL",
    "/redoc": "kept as a route so a build that vendors ReDoc can serve it; answers 404 naming /docs until then",
    # `P2-24`. Same shape as the OAuth entry above: the browser never spells
    # this path. `GET /api/fonts/custom` returns each uploaded font's `url`, and
    # static/js/theme.js writes it into an `@font-face` `src`, so the caller is
    # the browser's font loader. A literal in the JS would be a second copy of
    # a path the server already owns.
    "/api/fonts/custom/{filename}": "the @font-face src theme.js builds from the url GET /api/fonts/custom returns",
    # `B370`. Three developer sandboxes, which their own text says are opened
    # by hand at `/static/<name>.html` and linked from nothing — the mount
    # answers that URL with a redirect here, so the route's caller is the
    # mount's redirect, not a literal any page could carry. Before `B370` the
    # mount served them itself, to a caller with no session.
    "/sandbox/": "developer sandboxes; /static/<name>.html redirects here (app.py DEVELOPER_SANDBOX_PAGES)",
    # `B1450`, the 2026-10-25 audit. An external agent surface, reached with a
    # scoped API token by the Codex plugin (`integrations/codex/scripts/
    # pantheon_api.py`, which refuses any other prefix) and the Claude Code
    # skill (`integrations/claude/skills/pantheon/`); the tokens page in
    # `settings.js` mints the tokens and hands out the two plugin zips.
    "/api/codex/": "the Codex plugin and Claude Code skill, by scoped API token (integrations/)",
    "/api/claude/": "the Claude Code skill's plugin.zip, offered by settings.js's agent-token cards",
    # A paired LAN device, by its own token (`companion/README.md`); `GET /pair`
    # is a page an admin opens by URL to pair one.
    "/api/companion/": "a paired LAN companion device, by token (companion/README.md)",
}

_FRONTEND_GLOBS = ("static/*.js", "static/js", "static/*.html")
_PARAM = re.compile(r"\{[^}]*\}")           # /api/x/{id}/y
_TEMPLATE = re.compile(r"\$\{[^}]*\}")      # `${API_BASE}/api/x/${id}/y`


def tracked(*globs):
    # `B571`: each path once, however many index stages a merge left it with.
    return [f for f in tracked_files(*globs, root=ROOT, check=False) if "/lib/" not in f]


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

_BARE = re.compile(r"/(?:metrics|docs|redoc|openapi\.json)\b")
#: Where a path starts inside a literal, and the characters that end it. A
#: literal may be a whole HTML fragment — `markdown.js` writes
#: `` `…style="--em:url('/api/emoji/${code}.svg')"…` `` — so the path is cut at
#: the first quote, space, bracket or angle bracket after `/api/`.
_PATH_IN_LITERAL = re.compile(r"/api/[^\s'\"`()<>\\]*")
#: A template hole, while a literal is being read. Not a character a URL holds.
_HOLE = "\x00"


def literal_texts(text: str, mode: str = "js") -> list:
    """Every string and template literal in `text`, comments excluded, each
    with its template holes replaced by `_HOLE`.

    `B720`. This used to be one regex over the raw file —
    ``['"`]([^'"`\n]*?/api/…)['"`]`` — and it was wrong in both directions:
    a backtick is a quote to it, so `` `DELETE /api/…` `` written in a JSDoc
    block read as a caller exactly as a `fetch` does; and it stopped at the
    first quote *inside* a literal, so
    ``fetch(`/api/x/${String(id == null ? '' : id)}`)`` yielded a pattern
    that was not the route's. The walk that already knows where comments,
    strings, regexes and template holes are — `check-specifiers.py`'s
    `strip_comments`, the one blanker (`Law 14`) — reports the literals, and
    this reads them.
    """
    found = []
    strip_comments(text, mode=mode, literals=found)
    out = []
    for quote, start, end, holes in found:
        if quote != "`":
            body = text[start + 1:end]
            out.append(body[:-1] if body.endswith((quote, "\n")) else body)
            continue
        parts, at = [], start + 1
        for a, b in holes:
            parts += [text[at:a], _HOLE]
            at = b
        parts.append(text[at:end - 1])
        out.append("".join(parts))
    return out


def literal_patterns(literal: str) -> set:
    """The route patterns one literal reaches, every prefix included.

    `B804` / `B760`: a template whose literal path is followed by a hole —
    ``/api/tasks/${id}/run${force ? '?force=true' : ''}`` — reaches the path
    its literal prefix spells, because a hole appended to the last segment is
    a query string or a suffix the route does not see. Without that the last
    segment read `run*` and matched nothing, and a live route was listed as
    having no caller. A hole that IS a whole segment stays a parameter.
    """
    paths = _PATH_IN_LITERAL.findall(literal)
    if not paths and _BARE.match(literal):
        paths = [literal]
    candidates = set()
    for path in paths:
        path = re.sub(_HOLE + "+", _HOLE, path).split("?")[0].split("#")[0]
        candidates.add(path)
        if path.endswith(_HOLE) and not path.endswith("/" + _HOLE):
            candidates.add(path[:-1])
    seen = set()
    for each in candidates:
        pattern = normalise(each.replace(_HOLE, "*"))
        seen.add(pattern)
        # A caller may hold the head and build the tail, or vice versa. The
        # hand audit needed a head-plus-tail probe as its second pass; this
        # is that, kept cheap: every prefix of the pattern is recorded, so a
        # route whose tail is assembled elsewhere still counts as reached.
        parts = pattern.split("/")
        for i in range(3, len(parts)):
            seen.add("/".join(parts[:i]))
    return seen


def frontend_paths() -> set:
    """Every `/api/...`-shaped literal the frontend's CODE holds, as a pattern.

    Comments are not callers (`B720`, `B760`): a route whose only mention in
    `static/` is a sentence about it is reported as having none.
    """
    seen = set()
    for f in tracked(*_FRONTEND_GLOBS):
        try:
            text = (ROOT / f).read_text(errors="replace")
        except OSError:
            continue
        for literal in literal_texts(text, mode_for(f)):
            seen |= literal_patterns(literal)
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
    # `P23-01`. A window's URL (`/brain`, `/settings/shortcuts`, …) is the app
    # shell at an address the browser writes itself — `static/js/backStack.js`
    # puts the top window's path in the history entry, and a reload or a link
    # navigates there — so no fetch in the frontend names it. The set is
    # `app.py`'s own `PAGE_ROUTES` (and only when the app was imported: the
    # source-scan fallback still counts them, the safe direction).
    pages = set(getattr(sys.modules.get("app"), "PAGE_ROUTES", ()) or ())
    findings = []
    seen_paths = set()
    for path, methods in routes:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if any(path.startswith(prefix) for prefix in ALLOWED):
            continue
        if pages and path.strip("/").split("/")[0] in pages and "GET" in methods:
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
        # `B596`. The likeliest reader of this message is an agent whose route's
        # caller is on another branch, and the answer is not in the numbers.
        print(f"\nFAIL — {len(findings)} routes with no frontend caller, ceiling is "
              f"{ceiling}.\nEither wire it, delete it, or add its real caller to "
              f"ALLOWED with the reason.\nIf the caller is on another branch, the two "
              f"land in one merge and neither lands alone — never raise the ceiling\n"
              f"for an unwired half (.pantheon/ORCHESTRATION.md § A route and its "
              f"caller land in one merge, B596).")
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
