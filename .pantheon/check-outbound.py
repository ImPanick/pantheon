#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every call that leaves the process is paced, or it is named. `P15-06`.

    python3 .pantheon/check-outbound.py             # the inventory
    python3 .pantheon/check-outbound.py --max 96    # fail if it grows
    python3 .pantheon/check-outbound.py --quiet     # findings only

THE ROW'S `Verify:` IS THIS FILE.

*"a call that leaves the process without passing the limiter is the exception
and is named."* `P15`'s audit inventoried fifty modules making outbound calls
and found pacing was the exception rather than the rule — and the reason was
never carelessness. Routing a call by hand is three statements, and the third
(hand the response back so a 429 becomes a cooldown) is the one that gets
dropped, silently, because dropping it costs nothing until a provider starts
refusing and nobody is listening.

A BUDGET, NOT A BAN — AND THE BUDGET ONLY GOES DOWN.

`--max` is the same shape `check-wiring.py` and `check-specifiers.py` already
use. A hard zero today would be a lie: most of the remaining calls are the
agent's own tools talking to Pantheon's HTTP API on loopback, where pacing is
free (`LOCAL_POLICY`) but converting a hundred call sites in one commit is how
you ship a regression nobody can bisect. The budget makes the count visible and
monotonic, and the report below names every one — which is what the row asked
for.

THE ONE RULE WITH NO BUDGET.

A module that names a host carrying an explicit `HostPolicy` — GitHub,
HuggingFace, DuckDuckGo — and makes an unpaced call is a FAILURE regardless of
the budget. Those policies exist because those hosts have already, demonstrably,
throttled this product. There is no headroom to spend there.

WHAT COUNTS AS PACED.

The enclosing function acquires from the limiter, or it calls through
`src/paced_http.py`, which does the whole ritual.

Detection is per-function, so it OVER-reports: `webhook_manager._send_request`
is paced by `_deliver`, which calls it, and still appears in the inventory
below. Following the call graph would fix that and would also let a real gap
hide behind a helper that acquires on some paths and not others. Over-reporting
costs a line in a list; under-reporting costs a ban.

`B1014`: only `paced_http`'s request calls count. `direct_mounts` lives there
too and paces nothing, and before this a function that merely imported the
module — to route a client — was counted as paced.

EVERY CLIENT SAYS HOW IT IS ROUTED. `B1014`, with no budget.

httpx reads names and single addresses in `NO_PROXY`, not ranges (`B982`): a
client left to read the environment alone sends an address in an operator's
range to their proxy anyway. So every `httpx.Client(…)` / `httpx.AsyncClient(…)`
here says how it is routed — `mounts=` (`paced_http.direct_mounts`, the one
place that reads the ranges), `transport=` (httpx then reads no environment
proxy at all), or `trust_env=False` — and one that says none of them is a
FAILURE. It proves the construction says it, not that what it says is right:
that is what the tests are for.

A module-level `httpx.get(…)` builds a client nothing can say that to. Those
are counted against `--max-env`, which only goes down; the way off the list is
`src.paced_http`, which routes and paces.

    python3 .pantheon/check-outbound.py --max 109 --max-env 51
"""
import ast
import pathlib
import re
import signal
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_ROOTS = ("app.py", "src", "routes", "services", "core", "integrations",
          "companion", "mcp_servers")

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head",
                           "options", "request", "stream", "send"})
_LIMITER_CALLS = frozenset({"acquire", "acquire_async"})
_PACED_MODULE = "paced_http"
# The calls in `src/paced_http.py` that pace (`B1014`): the module also holds
# `direct_mounts` and the `NO_PROXY` guard, which pace nothing.
_PACED_CALLS = frozenset({"request", "get", "post", "request_sync", "get_sync", "post_sync"})

# `B1014`: an httpx client, and the module-level calls that build one inside.
_CLIENT_CLASSES = frozenset({"Client", "AsyncClient"})
_ENV_CALLS = frozenset({"get", "post", "put", "delete", "patch", "head", "options",
                        "request", "stream"})

# Hosts with an explicit policy in `src/rate_limiter.py`. An unpaced call in a
# module that names one of these is not a budget item.
_POLICED_HOSTS = (
    "api.github.com", "raw.githubusercontent.com", "github.com",
    "huggingface.co", "html.duckduckgo.com",
)

_HTTP_KWARGS = frozenset({"timeout", "json", "headers", "data", "params",
                          "follow_redirects", "content", "auth", "files", "stream"})


def _files():
    for entry in _ROOTS:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            for f in sorted(path.rglob("*.py")):
                if f.name.startswith("test_") or "test" in f.parts:
                    continue
                yield f


def _root_chain(node) -> str:
    """`a.b.c.get` -> "a.b.c". Follows one level into a call, so
    `httpx.Client(...).get` reads as `httpx.Client`."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, ast.Call):
        inner = node.func
        while isinstance(inner, ast.Attribute):
            names.append(inner.attr)
            inner = inner.value
        if isinstance(inner, ast.Name):
            names.append(inner.id)
    return ".".join(reversed(names))


def _outbound_label(call):
    """A label when this call leaves the process, else None.

    An explicit `httpx`/`requests`/`aiohttp` in the chain is enough — except for
    an ALL-CAPS root, which is a lookup table: `_HTTPCORE_TO_HTTPX_EXC.get(exc)`
    contains the word and is a dict access. A `client`-ish name needs an
    HTTP-shaped keyword to count, or every `self._sessions.get(id)` in the
    product reads as a network call. Both mistakes were made on the first run.
    """
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
        return None
    chain = _root_chain(func.value)
    if not chain:
        return None
    tail = chain.rsplit(".", 1)[-1]
    if tail.isupper() or (tail.startswith("_") and tail.lstrip("_").isupper()):
        return None
    low = chain.lower()
    kwargs = {k.arg for k in call.keywords if k.arg}
    explicit = any(k in low for k in ("httpx", "requests", "aiohttp"))
    clientish = "client" in low
    if explicit or (clientish and (kwargs & _HTTP_KWARGS)):
        return f"{chain}.{func.attr}"
    return None


def _is_urlopen(call) -> bool:
    name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
    return name == "urlopen"


def _functions(tree):
    """(node, name) for every function, innermost first when nested."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return sorted(out, key=lambda n: -n.lineno)


def _enclosing(functions, lineno):
    for node in functions:
        if node.lineno <= lineno <= (node.end_lineno or node.lineno):
            return node
    return None


def _is_paced(node) -> bool:
    if node is None:
        return False
    imported = set()   # `from src.paced_http import get` — names that pace
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and sub.module and _PACED_MODULE in sub.module:
            imported |= {a.asname or a.name for a in sub.names if a.name in _PACED_CALLS}
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
        if name in _LIMITER_CALLS:
            return True
        parts = _root_chain(call.func).split(".")
        # `paced_http.get(…)`, `src.paced_http.get(…)` — a request call on the
        # module. `paced_http.direct_mounts(…)` routes and does not pace (`B1014`).
        if len(parts) >= 2 and parts[-2] == _PACED_MODULE and parts[-1] in _PACED_CALLS:
            return True
        if isinstance(call.func, ast.Name) and call.func.id in imported:
            return True
    return False


def _is_httpx(chain: str) -> bool:
    return chain.rsplit(".", 1)[-1].lstrip("_") == "httpx"


def _said(call) -> bool:
    """`B1014`: the construction says how it is routed."""
    for kw in call.keywords:
        if kw.arg == "mounts" and not (isinstance(kw.value, ast.Constant)
                                       and kw.value.value is None):
            return True
        if kw.arg == "transport":
            return True
        if kw.arg == "trust_env" and isinstance(kw.value, ast.Constant) \
                and kw.value.value is False:
            return True
    return False


def scan_clients():
    """`B1014`: (unsaid, env) — client constructions that say nothing about
    how they are routed, and module-level calls that build one inside."""
    unsaid, env = [], []
    for path in _files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        functions = _functions(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            owner = _root_chain(call.func.value)
            if not _is_httpx(owner):
                continue
            node = _enclosing(functions, call.lineno)
            where = node.name if node else "<module>"
            if call.func.attr in _CLIENT_CLASSES:
                if not _said(call):
                    unsaid.append((rel, where, call.lineno, f"{owner}.{call.func.attr}"))
            elif call.func.attr in _ENV_CALLS and not _said(call):
                env.append((rel, where, call.lineno, f"{owner}.{call.func.attr}"))
    return unsaid, env


def scan():
    """(unpaced, policed) — every finding, in file order."""
    unpaced, policed = [], []
    for path in _files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        functions = _functions(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            label = _outbound_label(call)
            if label is None and _is_urlopen(call):
                label = "urlopen"
            if label is None:
                continue
            node = _enclosing(functions, call.lineno)
            if _is_paced(node):
                continue
            where = node.name if node else "<module>"
            entry = (rel, where, call.lineno, label)
            unpaced.append(entry)
            # Per-FUNCTION, not per-module. The first version searched the whole
            # file, so one mention of `html.duckduckgo.com` in a 700-line
            # provider chain flagged the Google, Tavily and Serper calls beside
            # it — 57 findings, almost none of them about the host named.
            segment = ast.get_source_segment(source, node) if node else ""
            named = [h for h in _POLICED_HOSTS if h in (segment or "")]
            if named:
                policed.append(entry + (", ".join(named),))
    return unpaced, policed


def main() -> int:
    quiet = "--quiet" in sys.argv
    budget = env_budget = None
    for i, arg in enumerate(sys.argv):
        if arg == "--max" and i + 1 < len(sys.argv):
            budget = int(sys.argv[i + 1])
        if arg == "--max-env" and i + 1 < len(sys.argv):
            env_budget = int(sys.argv[i + 1])

    unpaced, policed = scan()
    unsaid, env = scan_clients()

    if not quiet:
        by_file = {}
        for rel, where, line, label in unpaced:
            by_file.setdefault(rel, []).append((line, where, label))
        print(f"unpaced outbound calls {len(unpaced)} in {len(by_file)} file(s)"
              + (f"  ·  budget {budget}" if budget is not None else ""))
        print()
        for rel in sorted(by_file):
            print(f"  {rel}  ({len(by_file[rel])})")
            for line, where, label in sorted(by_file[rel]):
                print(f"      {line:>6}  {where}()  {label}")

    if not quiet:
        print()
        print(f"httpx clients that say nothing of how they are routed {len(unsaid)}  ·  "
              f"module-level calls that build one {len(env)}"
              + (f"  ·  budget {env_budget}" if env_budget is not None else ""))
        for rel, where, line, label in unsaid:
            print(f"  UNSAID  {rel}:{line}  {where}()  {label}")
        by_file = {}
        for rel, where, line, label in env:
            by_file.setdefault(rel, []).append((line, where, label))
        for rel in sorted(by_file):
            print(f"  {rel}  ({len(by_file[rel])})")
            for line, where, label in sorted(by_file[rel]):
                print(f"      {line:>6}  {where}()  {label}")

    problems = []
    for rel, where, line, label in unsaid:
        problems.append(
            f"UNROUTED    {rel}:{line} in {where}() — {label}(…)\n"
            f"            A client that leaves routing to httpx sends an address in a\n"
            f"            NO_PROXY range to the proxy anyway (B982, B1014). Pass\n"
            f"            mounts=paced_http.direct_mounts(url), or transport= / trust_env=False."
        )
    if env_budget is not None and len(env) > env_budget:
        problems.append(
            f"ENV-BUDGET  {len(env)} module-level httpx calls, budget is {env_budget}\n"
            f"            They build a client that reads NO_PROXY as httpx does (no\n"
            f"            ranges). Use src.paced_http, or lower the budget in CI if you\n"
            f"            have converted others."
        )
    for rel, where, line, label, hosts in policed:
        problems.append(
            f"POLICED     {rel}:{line} in {where}() — {label}\n"
            f"            This function names {hosts}, which carries an explicit\n"
            f"            HostPolicy because it has already throttled this product.\n"
            f"            There is no budget for those. Use `src.paced_http`."
        )
    if budget is not None and len(unpaced) > budget:
        problems.append(
            f"BUDGET      {len(unpaced)} unpaced calls, budget is {budget}\n"
            f"            The count may go down and never up. Route the new call\n"
            f"            through `src.paced_http`, or lower the budget in CI if you\n"
            f"            have converted others."
        )

    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} problem(s).")
        return 1
    if not quiet:
        print("\nOK — no policed host is called unpaced"
              + (f", and the count is within {budget}." if budget is not None else "."))
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
