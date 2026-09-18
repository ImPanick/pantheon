#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-02b` / `P11-02d` — the admin-gate map, held against the source.

Both rows asked for a table and nothing else: *"produce the mapping before
changing any of them"*, *"nothing here should be changed before that exists"*.
A markdown table is exactly the artefact this tracker keeps getting wrong.
`P11-02b` said **84** sites until 2026-08-28 while its own phase preamble said
103 thirty lines above it; `P11-02d` names `chat_routes.py:338/367` as the
place chat does its admin check and those two lines are `_candidate_index` and
`_message_plain_text`. Neither number was ever re-derived, and `Law 9` is the
rule they broke: a row cannot be ticked on a claim nobody can re-check.

So the map is `.pantheon/P11-AUTH-MAP.md` and this is the thing that re-checks
it. Everything the map asserts about the tree is recomputed here from the tree.

Four populations, derived:

  A  every `require_admin` site. Resolved through `import ... as`, because
     `routes/webhook/webhook_routes.py` imports it as `_require_admin` and a
     grep for `require_admin(` misses all five of its calls — which is most of
     the gap between the row's 103 and the real number.

  B  every route in the fifteen files of `P11-02d`, with what actually gates
     it: `AUTH_EXEMPT_EXACT` in `app.py` for the middleware exemption, and a
     call-graph closure inside the module for the handler's own check. The
     closure is the point. `assistant_routes.py` calls `get_current_user`
     from a one-line `_owner()` helper and every one of its six handlers looked
     ungated to a per-handler grep; `chat_routes.py` reaches
     `_verify_session_owner` the same way.

  C  a ratchet on admin decisions made some OTHER way — `is_admin(...)` and
     `owner_is_admin_or_single_user(...)` called directly. `require_admin` is
     one gate with many call sites; these are the separate implementations.
     `routes/auth_routes.py` holds 22 of them and is the entire
     user-administration surface, invisible to any audit that greps for
     `require_admin`. The ceiling may fall as they move onto the role model
     and may not rise: a further way to ask "is this person an admin" is the
     thing `P11-02` exists to stop.

  D  a hole that is filed. Every `intended` cell in the map's route table
     starts `yes` or `no`, and a `no` must name a `Bxxx`. An unfiled hole
     cannot sit in the map quietly, which is the failure mode a table is for.

**Sites are keyed by file and enclosing function, never by line number.** All
107 keys are unique that way (this checker fails if that ever stops being
true). A line number in a committed table is the one field that goes stale on
every unrelated edit above it, and a map that fails CI for a reason that is
not about auth is a map somebody deletes. `--list` prints the live lines.

Usage:  python3 .pantheon/check-auth-map.py [--max N] [--list]
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / ".pantheon" / "P11-AUTH-MAP.md"

SKIP_PREFIXES = ("tests/", ".pantheon/")

#: The four answers `P11-02b` asks for. A site is one of these or the map is wrong.
TIERS = (
    "superuser",
    "operator",
    "power-user",
    "only-because-nothing-finer-existed",
)

#: The fifteen files of `P11-02d`, in the row's own order.
ROUTE_FILES = (
    "routes/assistant_routes.py",
    "routes/auth_routes.py",
    "routes/chat_routes.py",
    "routes/cleanup/cleanup_routes.py",
    "routes/compare/compare_routes.py",
    "routes/editor_draft_routes.py",
    "routes/emoji_routes.py",
    "routes/font_routes.py",
    "routes/hwfit_routes.py",
    "routes/prefs_routes.py",
    "routes/search/search_routes.py",
    "routes/signature_routes.py",
    "routes/stt_routes.py",
    "routes/tts_routes.py",
    "routes/workspace_routes.py",
)

#: Names that decide, or resolve, who the caller is. A handler that reaches one
#: of these — directly or through a helper in the same module — is making an
#: auth call of its own, which is the exact question `P11-02d` asks.
AUTH_NAMES = frozenset({
    "get_current_user", "_get_current_user", "effective_user",
    "require_user", "require_authenticated_request", "require_privilege",
    "require_admin", "_require_admin", "owner_filter",
    "storage_owner_for_request", "require_api_token_scope",
    "require_chat_api_token_scope", "owner_is_admin_or_single_user",
    "is_admin", "_verify_session_owner",
})

#: The other ways this codebase answers "is this person an admin".
OTHER_GATE_NAMES = frozenset({"is_admin", "owner_is_admin_or_single_user"})

HTTP_METHODS = frozenset({
    "get", "post", "put", "delete", "patch", "head", "options", "websocket",
})


class Site(NamedTuple):
    """One `require_admin` gate.

    A `NamedTuple` rather than a dataclass on purpose. The house pattern for
    driving a checker from a test is `exec_module` **without** registering the
    module in `sys.modules` (`tests/test_silent_failures_are_counted_honestly.py`),
    and `@dataclass` resolves its annotations through
    `sys.modules[cls.__module__]`, which is `None` in that case and raises at
    import. A checker that cannot be imported the way this repo imports
    checkers is a checker only its own CI line can exercise.
    """
    file: str
    func: str
    line: int
    kind: str      # "direct" | "depends"
    route: str     # "POST /api/x", or "" when the site is not on a route

    @property
    def key(self) -> tuple[str, str]:
        return (self.file, self.func)


class Route(NamedTuple):
    """One HTTP route in one of the fifteen files."""
    file: str
    method: str
    path: str      # router prefix + decorator path, where the prefix is derivable
    func: str
    line: int
    auth: frozenset[str]

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


# ── source ──────────────────────────────────────────────────────────────────

def tracked_python(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split() if not f.startswith(SKIP_PREFIXES)]


def _parse(root: Path, rel: str, *, containing: str | None = None) -> ast.Module | None:
    """Parse one module, or `None` if it will not parse or cannot matter.

    `containing` is a cheap pre-filter and it is sound rather than
    approximate: a `require_admin` call cannot exist in a file whose text does
    not contain the string `require_admin`, and an aliased one cannot either —
    the alias is bound by an `import` that names it. Without this, the rules
    below parse every tracked module twice for nothing.
    """
    try:
        source = (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if containing is not None and containing not in source:
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _called_name(node: ast.Call) -> str | None:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _decorator_route(dec: ast.expr) -> tuple[str, str] | None:
    """('POST', '/x') for `@router.post("/x")`, else None."""
    if not isinstance(dec, ast.Call):
        return None
    f = dec.func
    if not isinstance(f, ast.Attribute) or f.attr not in HTTP_METHODS:
        return None
    if not dec.args or not isinstance(dec.args[0], ast.Constant):
        return None
    if not isinstance(dec.args[0].value, str):
        return None
    return (f.attr.upper(), dec.args[0].value)


def module_prefix(tree: ast.Module) -> str:
    """The one mount prefix this module's routes share, or "" when there is not one.

    Ambiguity is answered with "", never with a guess: `routes/codex_routes.py`
    builds two routers under different prefixes and `routes/device_flow.py`
    takes its prefix as an argument, so neither module has *a* prefix and the
    map carries the decorator path alone for both.
    """
    constants: set[str] = set()
    dynamic = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node) != "APIRouter":
            continue
        for kw in node.keywords:
            if kw.arg != "prefix":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                constants.add(kw.value.value)
            else:
                dynamic = True
    if dynamic or len(constants) != 1:
        return ""
    return constants.pop()


def _function_routes(tree: ast.Module) -> dict[int, tuple[str, str]]:
    """FunctionDef lineno -> (METHOD, decorator path) for every decorated route."""
    found: dict[int, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            route = _decorator_route(dec)
            if route:
                found[node.lineno] = route
    return found


def _enclosing(tree: ast.Module) -> dict[int, list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    """id(node) -> the function stack it sits inside, outermost first."""
    stack_of: dict[int, list] = {}

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack_of[id(child)] = stack
                walk(child, stack + [child])
            else:
                stack_of[id(child)] = stack
                walk(child, stack)

    walk(tree, [])
    return stack_of


def require_admin_aliases(tree: ast.Module) -> set[str]:
    """Every local name bound to `core.middleware.require_admin` in this module.

    `routes/webhook/webhook_routes.py` does `from core.middleware import
    require_admin as _require_admin`, so five real gates answer to a name a
    grep for `require_admin(` never sees. `routes/shell_routes.py` defines its
    OWN `_require_admin` and is deliberately not caught here — a second
    implementation is a different finding, and it is counted in rule C.
    """
    names = {"require_admin"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("middleware"):
            for alias in node.names:
                if alias.name == "require_admin":
                    names.add(alias.asname or alias.name)
    return names


def require_admin_sites(root: Path = ROOT, rels: list[str] | None = None) -> list[Site]:
    """Every `require_admin` gate in the tree, direct call or FastAPI dependency."""
    if rels is None:
        rels = tracked_python(root)
    sites: list[Site] = []
    for rel in rels:
        tree = _parse(root, rel, containing="require_admin")
        if tree is None:
            continue
        aliases = require_admin_aliases(tree)
        # A module that defines its own `require_admin` (none do today) would
        # otherwise have its definition counted as a use of itself.
        local_defs = {
            n.lineno for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in aliases
        }
        stack_of = _enclosing(tree)
        routes = _function_routes(tree)
        prefix = module_prefix(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            kind = None
            if name in aliases and node.lineno not in local_defs:
                kind = "direct"
            elif name == "Depends" and node.args:
                arg = node.args[0]
                inner = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", None)
                if inner in aliases:
                    kind = "depends"
            if kind is None:
                continue
            stack = stack_of.get(id(node)) or []
            func = stack[-1].name if stack else "<module>"
            route = ""
            for enclosing in reversed(stack):
                if enclosing.lineno in routes:
                    method, path = routes[enclosing.lineno]
                    route = f"{method} {prefix}{path}"
                    break
            sites.append(Site(rel, func, node.lineno, kind, route))
    sites.sort(key=lambda s: (s.file, s.line))
    return sites


def _call_graph(tree: ast.Module) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called = {
            n for n in (_called_name(c) for c in ast.walk(node) if isinstance(c, ast.Call))
            if n
        }
        graph.setdefault(node.name, set()).update(called)
    return graph


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    out: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for called in graph.get(name, ()):
            out.add(called)
            if called in graph:
                stack.append(called)
    return out


def routes_in(root: Path, rel: str) -> list[Route]:
    """Every route in one module, with the auth names its handler can reach.

    Reachability, not a per-handler grep: the auth call is frequently one
    helper away, and a grep over the handler body reports six gated routes as
    ungated in `assistant_routes.py` alone.
    """
    tree = _parse(root, rel)
    if tree is None:
        return []
    prefix = module_prefix(tree)
    graph = _call_graph(tree)
    # A `dependencies=[Depends(f)]` on the router applies to every route it
    # carries. `chat_routes.py` gates its whole surface that way.
    router_deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node) == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "dependencies":
                    for c in ast.walk(kw.value):
                        if isinstance(c, ast.Call) and _called_name(c) == "Depends" and c.args:
                            arg = c.args[0]
                            inner = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", None)
                            if inner:
                                router_deps.add(inner)
    out: list[Route] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            found = _decorator_route(dec)
            if not found:
                continue
            method, path = found
            auth = (_reachable(graph, node.name) | router_deps) & AUTH_NAMES
            out.append(Route(rel, method, f"{prefix}{path}", node.name, node.lineno,
                             frozenset(auth)))
    out.sort(key=lambda r: r.line)
    return out


def auth_exempt(root: Path = ROOT) -> tuple[set[str], list[re.Pattern]]:
    """`AUTH_EXEMPT_EXACT` / `_PREFIXES` / `_PATTERNS`, read out of `app.py`.

    Read, not copied. This is the list that decides whether a route needs a
    session at all, and a second copy of it here would be the `Law 7`
    duplicate that goes stale in exactly the direction nobody notices.
    """
    tree = _parse(root, "app.py")
    exact: set[str] = set()
    prefixes: list[str] = []
    patterns: list[re.Pattern] = []
    if tree is None:
        return exact, patterns
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "AUTH_EXEMPT_EXACT" in targets:
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    exact.add(elt.value)
        if "AUTH_EXEMPT_PREFIXES" in targets:
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    prefixes.append(elt.value)
        if "AUTH_EXEMPT_PATTERNS" in targets:
            for elt in getattr(node.value, "elts", []):
                for c in ast.walk(elt):
                    if isinstance(c, ast.Call) and _called_name(c) == "compile" and c.args:
                        first = c.args[0]
                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                            patterns.append(re.compile(first.value))
    for p in prefixes:
        patterns.append(re.compile(re.escape(p) + r"(/.*)?$"))
    return exact, patterns


def is_exempt(path: str, exact: set[str], patterns: list[re.Pattern]) -> bool:
    """Whether AuthMiddleware lets this path through unauthenticated.

    Path only, never method — `_is_auth_exempt` in `app.py` takes one argument
    and that is not a detail: `/api/auth/settings` is on the list for the
    pre-login page's sake, and `POST /api/auth/settings` writes every app
    setting under the same path. The write is exempt here too, and only its
    own in-handler admin check stands behind it.
    """
    if path in exact:
        return True
    return any(p.match(path) for p in patterns)


def other_admin_gates(root: Path = ROOT, rels: list[str] | None = None) -> list[str]:
    """Admin decisions taken without `require_admin` — rule C's ratchet.

    The call inside `require_admin` itself is excluded by span, because that
    one IS `require_admin`.
    """
    if rels is None:
        rels = tracked_python(root)
    found: list[str] = []
    for rel in rels:
        tree = _parse(root, rel, containing="is_admin")
        if tree is None:
            continue
        skip: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "require_admin":
                skip.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name in OTHER_GATE_NAMES and node.lineno not in skip:
                found.append(f"{rel}:{node.lineno} {name}")
    return found


# ── the map ─────────────────────────────────────────────────────────────────

_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
#: The one spelling a tier count may be written in outside the summary table.
_TIER_PROSE = re.compile(
    r"(\d+)\s+(" + "|".join(re.escape(t) for t in TIERS) + r")\s+sites?\b")
_TICKED = re.compile(r"^`(?P<v>[^`]+)`$")
_BROW = re.compile(r"\bB\d{2,4}\b")


def _cells(line: str) -> list[str] | None:
    m = _ROW.match(line.rstrip())
    if not m:
        return None
    cells = [c.strip() for c in m.group("cells").split("|")]
    if all(set(c) <= {"-", ":", " "} and c for c in cells):
        return None  # the `|---|---|` separator
    return cells


def _bare(cell: str) -> str:
    m = _TICKED.match(cell)
    return m.group("v") if m else cell


class ParsedMap(NamedTuple):
    sites: dict          # (file, func) -> row
    tier_summary: dict   # tier -> claimed count
    site_total: str      # the claimed `derived:` line, raw
    other_total: str     # the claimed `derived-others:` line, raw
    routes: dict         # file -> "METHOD path" -> row
    route_counts: dict   # file -> claimed route count


def parse_map(text: str) -> ParsedMap:
    """Read the map. Section by `##`, tier by `###`, file by `#### <path>`."""
    sites: dict[tuple[str, str], dict] = {}
    tier_summary: dict[str, int] = {}
    site_total = ""
    other_total = ""
    routes: dict[str, dict[str, dict]] = {}
    route_counts: dict[str, int] = {}

    section = ""
    tier = ""
    route_file = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
            tier = ""
            route_file = ""
            continue
        if line.startswith("#### "):
            route_file = _bare(line[5:].strip())
            continue
        if line.startswith("### "):
            tier = _bare(line[4:].split("—")[0].strip())
            continue
        if line.lower().startswith("derived:"):
            site_total = line[len("derived:"):].strip()
            continue
        if line.lower().startswith("derived-others:"):
            other_total = line[len("derived-others:"):].strip()
            continue
        m = re.match(r"^routes:\s*(\d+)\s*$", line, re.I)
        if m and route_file:
            route_counts[route_file] = int(m.group(1))
            continue
        cells = _cells(line)
        if not cells:
            continue
        head = _bare(cells[0]).lower()
        if section.startswith("a ") or section.startswith("a·") or section.startswith("a ·"):
            if tier == "tier summary" and len(cells) >= 2 and _bare(cells[1]).isdigit():
                tier_summary[_bare(cells[0])] = int(_bare(cells[1]))
                continue
            if head in ("file", "tier"):
                continue
            if tier in TIERS and len(cells) >= 4:
                key = (_bare(cells[0]), _bare(cells[1]))
                sites[key] = {
                    "file": _bare(cells[0]), "func": _bare(cells[1]),
                    "route": _bare(cells[2]), "protects": cells[3], "tier": tier,
                }
            continue
        if section.startswith("b"):
            if head in ("route", "method"):
                continue
            if route_file and len(cells) >= 4:
                routes.setdefault(route_file, {})[_bare(cells[0])] = {
                    "route": _bare(cells[0]), "handler": _bare(cells[1]),
                    "gate": _bare(cells[2]), "intended": cells[3],
                }
    return ParsedMap(sites, tier_summary, site_total, other_total, routes, route_counts)


def _gate_from_source(route: Route, exact: set[str], patterns: list[re.Pattern]) -> str:
    base = "exempt" if is_exempt(route.path, exact, patterns) else "middleware"
    if not route.auth:
        return base
    return base + " + " + " + ".join(sorted(route.auth))


def problems(root: Path, text: str, *, max_other: int) -> tuple[list[str], dict]:
    """Every way the map and the tree disagree, plus the numbers for the summary."""
    out: list[str] = []
    parsed = parse_map(text)

    # ── A ────────────────────────────────────────────────────────────────────
    sites = require_admin_sites(root)
    by_key: dict[tuple[str, str], Site] = {}
    for site in sites:
        if site.key in by_key:
            out.append(
                f"{site.file}:{site.line}: a second require_admin site in `{site.func}` "
                f"(the first is line {by_key[site.key].line}). The map keys on "
                "file + function, so give one of them its own helper or the two "
                "cannot be told apart."
            )
            continue
        by_key[site.key] = site

    for key, site in sorted(by_key.items()):
        row = parsed.sites.get(key)
        if row is None:
            out.append(
                f"{site.file}:{site.line}: `require_admin` in `{site.func}` "
                f"({site.route or 'no route'}) is in no tier table. Add it to "
                "P11-AUTH-MAP.md § A with a tier, or the RBAC refactor will not "
                "know this gate exists."
            )
            continue
        if row["route"] != (site.route or "—"):
            out.append(
                f"{site.file}: `{site.func}` is mapped as `{row['route']}` and the "
                f"source says `{site.route or '—'}`."
            )
        if not row["protects"]:
            out.append(f"{site.file}: `{site.func}` has an empty `protects` cell.")

    for key in sorted(set(parsed.sites) - set(by_key)):
        out.append(
            f"{key[0]}: the map has `{key[1]}` and there is no `require_admin` "
            "there any more — drop the row so the map stays a description of the tree."
        )

    counted = {tier: 0 for tier in TIERS}
    for row in parsed.sites.values():
        if row["tier"] not in TIERS:
            out.append(
                f"{row['file']}: `{row['func']}` is tiered `{row['tier']}`, which is "
                f"not one of {', '.join(TIERS)}."
            )
            continue
        counted[row["tier"]] += 1
    for tier in TIERS:
        claimed = parsed.tier_summary.get(tier)
        if claimed is None:
            out.append(f"§ A's tier summary has no row for `{tier}`.")
        elif claimed != counted[tier]:
            out.append(
                f"§ A's tier summary says {claimed} `{tier}` sites and the tables "
                f"below it hold {counted[tier]}."
            )

    # Every *prose* restatement of a tier count, too. The summary table being
    # right is not much use when the paragraph under it says something else,
    # and this file argues from those numbers — "45 gates retired without
    # touching one of the 37" is the row's conclusion, not decoration. One
    # spelling, `N tier sites`, checked wherever it appears (`Law 8`).
    for claimed, tier in _TIER_PROSE.findall(text):
        if int(claimed) != counted[tier]:
            out.append(
                f"the map says `{claimed} {tier} sites` in prose and there are "
                f"{counted[tier]}."
            )

    direct = sum(1 for s in sites if s.kind == "direct")
    depends = len(sites) - direct
    want_total = f"direct {direct} · Depends {depends} · total {len(sites)}"
    if parsed.site_total != want_total:
        out.append(
            f"§ A's `derived:` line says `{parsed.site_total}` and the tree says "
            f"`{want_total}`."
        )

    # ── B ────────────────────────────────────────────────────────────────────
    exact, patterns = auth_exempt(root)
    if not exact:
        out.append("app.py yielded no AUTH_EXEMPT_EXACT entries — the exemption "
                   "check below is not evidence about anything.")
    live_routes = 0
    for rel in ROUTE_FILES:
        found = routes_in(root, rel)
        live_routes += len(found)
        mapped = parsed.routes.get(rel)
        if mapped is None:
            out.append(f"§ B has no `#### {rel}` section; the row names it as one "
                       "of the fifteen.")
            continue
        claimed = parsed.route_counts.get(rel)
        if claimed is None:
            out.append(f"§ B's `{rel}` section has no `routes: N` line.")
        elif claimed != len(found):
            out.append(f"§ B says `{rel}` has {claimed} routes and it has {len(found)}.")
        for route in found:
            row = mapped.get(route.key)
            if row is None:
                out.append(
                    f"{rel}:{route.line}: `{route.key}` is in no § B table. Say what "
                    "gates it and whether that is intended."
                )
                continue
            want = _gate_from_source(route, exact, patterns)
            if row["gate"] != want:
                out.append(
                    f"{rel}: `{route.key}` is mapped as gated by `{row['gate']}` and "
                    f"the source says `{want}`."
                )
            if row["handler"] != route.func:
                out.append(
                    f"{rel}: `{route.key}` is mapped to handler `{row['handler']}` and "
                    f"the source says `{route.func}`."
                )
            verdict = row["intended"].strip().lower()
            if not (verdict.startswith("yes") or verdict.startswith("no")):
                out.append(
                    f"{rel}: `{route.key}`'s `intended` cell is `{row['intended']}` — it "
                    "has to begin `yes` or `no`. A reconciliation with a blank verdict "
                    "reconciles nothing."
                )
            elif verdict.startswith("no") and not _BROW.search(row["intended"]):
                out.append(
                    f"{rel}: `{route.key}` is marked NOT intended and names no `Bxxx`. "
                    "File it in ROADMAP.md § Bugs and cite the row here — an unfiled "
                    "hole in a map is worse than no map."
                )
        for key in sorted(set(mapped) - {r.key for r in found}):
            out.append(
                f"{rel}: the map has `{key}` and the file no longer serves it."
            )

    # ── C ────────────────────────────────────────────────────────────────────
    others = other_admin_gates(root)
    other_files = {o.split(":", 1)[0] for o in others}
    in_auth_routes = sum(1 for o in others if o.startswith("routes/auth_routes.py:"))
    want_others = (f"{len(others)} across {len(other_files)} files, "
                   f"{in_auth_routes} in routes/auth_routes.py")
    if parsed.other_total != want_others:
        out.append(
            f"§ A's `derived-others:` line says `{parsed.other_total}` and the tree "
            f"says `{want_others}`. This is the number the map's argument about four "
            "admin gates rests on, so it is derived rather than written down."
        )
    if len(others) > max_other:
        out.append(
            f"admin decisions taken outside `require_admin` rose from {max_other} "
            f"to {len(others)}. This ratchet only comes down: gate it with "
            "`require_admin`, or with whatever `P11-02` replaces it with, rather "
            "than writing a further way to ask the same question."
        )

    return out, {
        "sites": len(sites), "direct": direct, "depends": depends,
        "mapped": len(parsed.sites), "routes": live_routes,
        "others": len(others),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max", type=int, default=43,
                    help="ceiling for admin decisions taken outside require_admin "
                         "(may fall, never rise)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    if not MAP_PATH.exists():
        print(f"auth map  MISSING {MAP_PATH.relative_to(ROOT)}")
        return 1
    text = MAP_PATH.read_text(encoding="utf-8")
    found, n = problems(ROOT, text, max_other=args.max)

    print(
        f"require_admin sites {n['sites']} (direct {n['direct']} · Depends "
        f"{n['depends']})  ·  mapped {n['mapped']}  ·  routes in "
        f"{len(ROUTE_FILES)} files {n['routes']}  ·  admin gates outside "
        f"require_admin {n['others']} (max {args.max})  ·  PROBLEMS {len(found)}"
    )
    for p in found:
        print(f"  {p}")
    if args.list:
        print()
        for site in require_admin_sites(ROOT):
            print(f"  {site.file}:{site.line:<6} {site.kind:<8} "
                  f"{site.route or '—':<48} {site.func}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
