#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No address ships pre-filled. Armed before there is a hole to guard.

`P16-13`. `Law 16` clause 4, as the owner amended it: *"telemetry is fine, but
'phone home' to an external destination is not allowed. if the user wants to
establish their own telemetry endpoint, they can bypass this law and do so."*
The rule is about the destination, not the activity — the question is always
*who owns the address at the other end?*

`P16-12` will build the first legitimate place in this codebase for an outbound
metrics URL, and therefore the first place a well-meant default could land: a
"community stats" endpoint, a "public demo collector", or — most likely of all —
an SDK whose constructor already has a hosted URL baked in and whose docs call
it the quickstart. This check exists **before** that row so the answer is
already no.

    python3 .pantheon/check-destinations.py           # report
    python3 .pantheon/check-destinations.py --quiet    # findings only

TWO LAYERS, AND THE SECOND IS THE WEAK ONE.

The primary rule is an **allowlist over shape**: any absolute URL that ships as
a default must point somewhere local, or be an obvious placeholder, or be listed
below with a reason. That catches a vendor nobody has heard of yet, which is the
only kind that matters — every telemetry vendor was new once.

The secondary rule is a **denylist of known collector hosts**. It is a guess
about names, it will age, and it is kept only because it is nearly free and
catches the SDK case in one line. If the two ever disagree, the allowlist is
right.

Scope (Law 5): `DEFAULT_SETTINGS`, `.env.example`, every `docker-compose*.yml`
`environment:` default, and the built-in default beneath a stored setting — the
fourth argument of `env_backed(settings, key, ENV, default)` in shipped code,
which is where a default sits that `DEFAULT_SETTINGS` keeps empty. Not runtime
values, not documentation, not a URL a person types into Settings — that address
is theirs and the law explicitly permits it.

ONE NAMED EXCEPTION, AND IT IS NOT A DESTINATION (`D-2026-10-02-04` §2).
`source_url` — the AGPL-3.0 §13 source offer — defaults to this repository, so an
unmodified install offers its own source. See `SHIPPED_DEFAULTS` below: it names
the setting, its environment variable and the exact address, and says why.
"""
import ipaddress
import pathlib
import re
import signal
import sys
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>{},]+", re.I)

# Keys shaped like a destination. Broader than a word-list on purpose: the five
# words the pytest guard uses ("telemetry", "analytics", "otlp", "collector",
# "metrics_endpoint") would not catch `metrics_push_url` or `grafana_target`.
DESTINATION_KEY = re.compile(
    r"(_url|_uri|_endpoint|_host|_server|_collector|_webhook|_base|_target)$", re.I
)

# Hosts that are the operator's own machine or network by construction.
LOCAL_NAMES = {
    "localhost", "host.docker.internal", "gateway.docker.internal",
    "pantheon", "searxng", "chromadb", "chroma", "ntfy", "ollama",   # compose services
}
LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".localdomain", ".home.arpa")

# Placeholders. A reader is meant to replace these; they are not destinations.
PLACEHOLDER = re.compile(
    r"(your[-_.]?(domain|org|host|server|instance|fork)|example\.(com|org|net)"
    r"|\bchangeme\b|\byour\b|\bx\.y\.z\b|<[^>]+>)", re.I
)
# `${...}` is NOT in that pattern, deliberately: compose writes defaults as
# `KEY=${VAR:-default}`, and excusing anything containing `${` would excuse
# `${TELEMETRY_URL:-https://collector.some-vendor.com}` — the exact line this
# file exists to reject.
#
# It is not the only thing standing between that line and a pass, and the
# distinction cost a surviving mutation to find. `classify()` receives an
# extracted URL, never a whole line, and `URL` excludes `{` and `}` — so the
# address inside an expansion is pulled out and judged on its own regardless.
# An earlier version of this file added a `COMPOSE_DEFAULT` regex to "close the
# hole"; the hole was already closed, the regex changed no result, and it was
# removed. What actually makes compose scannable is the `lstrip("- ")` below,
# which is the line the test for this exercises.
ASSIGNMENT = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")

# External addresses that ship anyway, each with the reason it is not a
# destination. An entry here is a decision, not an exemption — it says "bytes
# never go here on their own".
ALLOWED = {
    # (nothing yet — and the emptiness is the point)
}

# A default that ships FILLED, named by the setting it belongs to, the variable
# beneath it and the exact address — never by host, because "github.com is
# fine" would excuse a collector on GitHub Pages in any key. Each entry is an
# owner's ruling, cited.
#
# `source_url` (`D-2026-10-02-04` §2, superseding `D-2026-09-08-06`'s empty
# default): the AGPL-3.0 §13 offer of this program's Corresponding Source. It is
# an `href` the user's own browser follows if they click it — the app never
# requests it, so it is not a destination in `Law 16`'s sense: no bytes go there
# on their own. The repository is public, so an unmodified install offering it
# offers what it runs; a modified copy owes its users ITS source and points the
# setting or `PANTHEON_SOURCE_URL` there (`docs/setup.md`).
SOURCE_OFFER = "https://github.com/ImPanick/pantheon"
SHIPPED_DEFAULTS = {
    (name, SOURCE_OFFER): "the AGPL §13 source offer — an href a person clicks, "
                          "never fetched by the app (D-2026-10-02-04 §2)"
    for name in ("source_url", "PANTHEON_SOURCE_URL")
}

_COLLECTOR_HOSTS = (
    "sentry.io", "posthog.com", "mixpanel.com", "amplitude.com", "segment.io",
    "google-analytics.com", "analytics.google.com", "googletagmanager.com",
    "bugsnag.com", "datadoghq.com", "newrelic.com", "rollbar.com",
    "logrocket.com", "fullstory.com", "hotjar.com", "plausible.io",
    "umami.is", "matomo.cloud", "statsig.com", "launchdarkly.com",
    "honeycomb.io", "lightstep.com", "instana.io", "dynatrace.com",
)
_CODE_ROOTS = ("src", "routes", "services", "core", "companion", "integrations",
               "mcp_servers", "scripts")


def host_is_local(host: str) -> bool:
    if not host:
        return True                      # a relative or malformed URL is not a destination
    host = host.strip("[]").lower()
    if host in LOCAL_NAMES or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    # `is_global` rather than `is_private`: a tailnet lives in 100.64.0.0/10
    # (RFC 6598), which `is_private` reports as False. That mistake was made
    # once already, in the Law 16 egress guard.
    return not ip.is_global


def classify(url: str, name: str = ""):
    """(ok, why). `ok` False means this address should not ship.

    `name` is the setting or variable the address is the default of, when the
    caller knows it — the only way `SHIPPED_DEFAULTS` can answer."""
    if name and (name, url) in SHIPPED_DEFAULTS:
        return True, f"named — {SHIPPED_DEFAULTS[(name, url)]}"
    if PLACEHOLDER.search(url):
        return True, "placeholder"
    host = ""
    try:
        host = (urlparse(url).hostname or "")
    except ValueError:
        return True, "unparseable"
    if host_is_local(host):
        return True, "local"
    if host in ALLOWED:
        return True, f"allowed — {ALLOWED[host]}"
    return False, host


def scan_default_settings(problems, seen):
    try:
        from src.settings import DEFAULT_SETTINGS
    except Exception as e:
        problems.append(f"IMPORT      could not read DEFAULT_SETTINGS: {e}")
        return

    def walk(key, value):
        if isinstance(value, str):
            for url in URL.findall(value):
                seen.append((f"DEFAULT_SETTINGS[{key}]", url, key))
                ok, why = classify(url, key)
                if not ok:
                    problems.append(
                        f"DESTINATION DEFAULT_SETTINGS[{key!r}] ships {url}\n"
                        f"            Host {why} is not local, not a placeholder, and not in\n"
                        f"            ALLOWED. A shipped address is a decision made on the\n"
                        f"            operator's behalf (Law 16 clause 4)."
                    )
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(f"{key}.{k}", v)
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(f"{key}[{i}]", v)

    for key, value in sorted(DEFAULT_SETTINGS.items()):
        walk(key, value)
        if DESTINATION_KEY.search(key) and value not in ("", None, False, [], {}, 0) \
                and not (isinstance(value, str) and (key, value) in SHIPPED_DEFAULTS):
            problems.append(
                f"PREFILLED   DEFAULT_SETTINGS[{key!r}] = {value!r}\n"
                f"            A destination-shaped key must ship empty. Empty is not a\n"
                f"            disabled feature here — it is the shipped state the law\n"
                f"            requires, and it is also what keeps any env-var fallback\n"
                f"            reachable (H06, B20)."
            )


def scan_files(problems, seen):
    targets = [ROOT / ".env.example"] + sorted(ROOT.glob("docker-compose*.yml"))
    for path in targets:
        if not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Only the VALUE side of an assignment. Prose in .env.example links
            # to Google's OAuth docs and quotes a Gmail scope that is spelled as
            # a URL; neither is a destination and neither is a default. A
            # commented-out assignment (`# KEY=https://…`) still counts, because
            # that is exactly where a shipped default would hide.
            m = ASSIGNMENT.match(line.lstrip("- "))
            if not m:
                continue
            for url in URL.findall(m.group(2)):
                where = f"{path.name}:{n}"
                seen.append((where, url, m.group(1)))
                ok, why = classify(url, m.group(1))
                if not ok:
                    problems.append(
                        f"DESTINATION {where} ships {url}\n"
                        f"            Host {why} is not local, not a placeholder, and\n"
                        f"            not in ALLOWED."
                    )


def _code_files():
    files = [ROOT / "app.py"]
    for root in _CODE_ROOTS:
        d = ROOT / root
        if d.is_dir():
            files += [p for p in d.rglob("*.py")
                      if not p.name.startswith("test_") and "test" not in p.parts]
    return [f for f in files if f.is_file()]


def scan_code_defaults(problems, seen):
    """The default beneath a stored setting, in code.

    `D-2026-10-02-04` §2 put the first filled `*_url` default here rather than in
    `DEFAULT_SETTINGS` — keeping the stored layer empty is what keeps
    `PANTHEON_SOURCE_URL` reachable over it (`H06`, `B20`) — and a default this
    check cannot see is the hole a well-meant collector address would use next.
    So every `env_backed(settings, key, ENV, default)` call in shipped code has its
    default read: a string literal, or a module-level string constant of the same
    file, judged by the same rule under the setting's own name.
    """
    import ast
    for f in _code_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        consts = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = node.value.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname != "env_backed":
                continue
            default = node.args[3] if len(node.args) > 3 else next(
                (k.value for k in node.keywords if k.arg == "default"), None)
            if isinstance(default, ast.Constant) and isinstance(default.value, str):
                value = default.value
            elif isinstance(default, ast.Name) and default.id in consts:
                value = consts[default.id]
            else:
                continue
            key = node.args[1].value if len(node.args) > 1 and isinstance(
                node.args[1], ast.Constant) else ""
            env = node.args[2].value if len(node.args) > 2 and isinstance(
                node.args[2], ast.Constant) else ""
            where = f"{f.relative_to(ROOT)}:{node.lineno}"
            for url in URL.findall(value):
                seen.append((where, url, key))
                ok, why = classify(url, key)
                if ok and env and why.startswith("named"):
                    # The same address must be the exception under BOTH names,
                    # or the code default and `.env.example` can drift apart.
                    ok, why = classify(url, env)
                if not ok:
                    problems.append(
                        f"DESTINATION {where} env_backed({key!r}, {env!r}) defaults to {url}\n"
                        f"            Host {why} is not local, not a placeholder, and not a\n"
                        f"            named shipped default. A default beneath a setting ships\n"
                        f"            exactly as DEFAULT_SETTINGS does (Law 16 clause 4)."
                    )


def scan_code_for_collectors(problems):
    """The weak layer. Kept because it is nearly free and catches an SDK import
    in one line, not because a name list can be complete."""
    files = _code_files()
    files += list((ROOT / "static").rglob("*.js"))
    for f in files:
        if "static/lib" in f.as_posix() or "library/" in f.as_posix():
            continue
        try:
            low = f.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        for host in _COLLECTOR_HOSTS:
            if host in low:
                problems.append(
                    f"COLLECTOR   {f.relative_to(ROOT)} names {host}\n"
                    f"            A telemetry collector host in shipped code. Clause 4's\n"
                    f"            absolute half: a build that reports to us is never\n"
                    f"            acceptable, at any sample rate, with or without a dialog."
                )


def main() -> int:
    quiet = "--quiet" in sys.argv
    problems, seen = [], []
    scan_default_settings(problems, seen)
    scan_files(problems, seen)
    scan_code_defaults(problems, seen)
    scan_code_for_collectors(problems)

    if not quiet:
        local = sum(1 for _, u, n in seen if classify(u, n)[1] == "local")
        place = sum(1 for _, u, n in seen if classify(u, n)[1] == "placeholder")
        named = sum(1 for _, u, n in seen if classify(u, n)[1].startswith("named"))
        print(f"shipped URLs {len(seen)}  ·  local {local}  ·  placeholder {place}  ·  "
              f"allowed {len(ALLOWED)}  ·  named defaults {named} "
              f"(of {len(SHIPPED_DEFAULTS)} names)  ·  PROBLEMS {len(problems)}")

    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} shipped destination(s).")
        print("The rule has no opt-in ceremony that satisfies it: consent makes a")
        print("destination lawful to USE, never lawful to SHIP (D-2026-08-31-01).")
        return 1
    if not quiet:
        print("OK — no address ships pre-filled.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
