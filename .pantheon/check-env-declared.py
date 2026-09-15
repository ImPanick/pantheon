#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-23` — environment variables the code reads and `.env.example` never mentions.

There are four sources of truth about this product's configuration and no two
of them agree: what the code reads, what `.env.example` declares, what
`docker-compose.yml` forwards, and what `docs/setup.md` explains. An operator
looks in `.env.example`. `H08` is what the gap costs: the switch that uncaps
every local agent run appeared **nowhere** outside the module that read it, so
the only way to turn the behaviour off was to already know the variable's name.

Two directions, and they are not symmetrical.

  UNDECLARED   read by app code, absent from `.env.example`. Ratcheted: may
               fall, may not rise. Detected from literal `os.getenv("X")` /
               `os.environ["X"]` call sites, which is precise about what it
               finds and **blind to indirect reads** — `os.getenv(SOME_CONST)`
               is invisible here. That is why the other direction does not use
               the same scan.

  UNREFERENCED declared in `.env.example` and appearing nowhere else in the
               repository at all. Hard rule, max 0: a documented knob nothing
               consumes is worse than an undocumented one, because an operator
               who sets it believes something changed. Matched by plain text
               across every tracked file, so an indirect read, a compose
               forward or a mention in a shell script all count — loose on
               purpose, because a false alarm here would send someone deleting
               a variable that works.

`B20` adds a third direction, and it is the same operator question the other
two ask — *can this variable do anything?* — from the one side neither could
see. A variable can be declared in `.env.example`, forwarded by compose,
explained in the docs, and read by a line that cannot execute:

  UNREACHABLE  read beneath a settings key whose SHIPPED DEFAULT IS TRUTHY.
               `settings.get_setting` merges `DEFAULT_SETTINGS` on every read,
               so `get_setting(K, None) or os.getenv(E)` never reaches the
               `or` — not after the first save, which is what `B20` originally
               claimed, but **at import, on a fresh install, with no settings
               file at all**. `H06` found `PANTHEON_TASK_CONCURRENCY_CAP` dead
               that way on every install this product has ever had. Hard rule,
               max 0, and 0 today: this is a ratchet against the reintroduction
               rather than a backlog. A scope that asks the question properly —
               `settings.setting_is_explicit`, or `settings.env_backed` — is
               not flagged, because those are the two answers.

  MIXED        one dict, some values through `env_backed` and one straight off
               `settings.get`. `H07` converted ten fields of the legacy mail
               config and left the eleventh; `IMAP_STARTTLS` was therefore
               honoured by `mcp_servers/email_server.py` and ignored by
               `routes/email_helpers.py` **on the same host, for the same
               mailbox**. Hard rule, max 0. Narrow on purpose: the finding is
               a sibling left behind, and a rule that fired on every settings
               read near an `env_backed` would be noise nobody reads.

  SPELLING     an environment value judged by an inline `== "true"` or
               `in ("1","true","yes")` instead of by `src/env_flags.env_flag`.
               `B91` counted **38 environment booleans and 10 incompatible
               rules** on 2026-09-15: `PANTHEON_STARTUP_WARMUPS=1` on and
               `IMAP_STARTTLS=1` off in one process, `AUTH_ENABLED=0` leaving
               auth enabled, `CLEANUP_ENABLED=" true"` off at the one site that
               never stripped. Hard rule, max 0 unexempted — a site that must
               keep its own rule says so with `# env-spelling: <reason>`, and
               nine do, each one a case where the shared vocabulary would loosen
               a control or flip a live deployment. The reason lives at the
               site, because a list of exempt names inside a checker is a list
               nobody reads next to the code it is about.

The three new rules are blind in the same way and it is worth stating: they see
one scope, one dict, or one comparison at a time. A resolver that reads the setting in one
function and the environment in another is invisible to them — so is
`services/search/providers._get_provider_key`, where the pairing lives in two
dict literals rather than in a name. What they catch is the shape that has
actually shipped twice.

`NOT_OURS` holds the names Pantheon reads but does not define: the operating
system's, the shell's, and third-party libraries' own conventions. Declaring
`PATH` or `HF_TOKEN` in our example file would be a claim we have no standing
to make. Each entry says whose it is.

Usage:  python3 .pantheon/check-env-declared.py [--max N] [--list]
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
SKIP_PREFIXES = ("tests/", ".pantheon/")
# Parsed, never imported. Importing `src.settings` to read `DEFAULT_SETTINGS`
# would make a checker's verdict depend on the whole application importing
# cleanly, and on `PANTHEON_DATA_DIR` in whatever shell ran it.
SETTINGS_SOURCE = ROOT / "src" / "settings.py"

# Names read from the environment that belong to somebody else. Declaring these
# in our own example file would be a claim about their meaning that we do not
# get to make, and an operator who changed one there would be surprised.
NOT_OURS = {
    # The operating system and the shell.
    "PATH": "the OS search path",
    "PYTHONPATH": "CPython's module search path",
    "TMPDIR": "the POSIX temp directory",
    "APPDATA": "Windows roaming application data",
    "LOCALAPPDATA": "Windows local application data",
    "ComSpec": "the Windows command interpreter",
    "TERM": "the terminal type, for colour detection",
    "USERNAME": "Windows' own name for the logged-in user",
    "USER": "the POSIX name for the logged-in user",
    "COLORTERM": "terminal colour capability",
    "LOG_LEVEL": "the standard-library logging convention, read by scripts/_lib/cli.py",
    # Third-party libraries reading their own settings.
    "SSL_CERT_FILE": "OpenSSL's own trust-store override",
    "REQUESTS_CA_BUNDLE": "requests' own trust-store override",
    "HF_TOKEN": "Hugging Face Hub's own credential",
    "HUGGING_FACE_HUB_TOKEN": "Hugging Face Hub's own credential",
    "HF_HUB_DISABLE_PROGRESS_BARS": "Hugging Face Hub's own switch",
    "HF_HUB_DOWNLOAD_MAX_WORKERS": "Hugging Face Hub's own switch",
    "npm_config_cache": "npm's own cache location",
}

_ENV_NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def _tracked(pattern: str | None = None) -> list[str]:
    args = ["git", "ls-files"] + ([pattern] if pattern else [])
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return out.split()


def declared() -> dict[str, int]:
    """Name → line number in `.env.example`, commented entries included."""
    found: dict[str, int] = {}
    for lineno, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        match = _ENV_NAME.match(line)
        if match:
            found.setdefault(match.group(1), lineno)
    return found


def literal_reads() -> dict[str, set]:
    """Name → files that read it with a string literal."""
    found: dict[str, set] = {}
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES):
            continue
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                func = node.func
                getenvish = (
                    (isinstance(func, ast.Attribute) and (
                        func.attr == "getenv"
                        or (func.attr in ("get", "pop")
                            and isinstance(func.value, ast.Attribute)
                            and func.value.attr == "environ")))
                    or (isinstance(func, ast.Name) and func.id == "getenv")
                )
                # `B91`. `env_flags.env_flag("X", default)` IS a literal read of
                # X, and adopting it at 22 sites took this scan from 143 names
                # to 121 — twelve of them undeclared, which would have lowered
                # the ratchet by hiding the variables rather than documenting
                # them. A helper that makes the checker blinder than the code it
                # replaced is a worse defect than the one it fixed.
                if isinstance(func, ast.Name) and func.id == "env_flag":
                    getenvish = True
                if getenvish and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    name = node.args[0].value
                # `env_backed(settings, key, ENV)` and its boolean twin name the
                # variable in the THIRD argument. These were invisible here
                # before `B91` — `H07` converted ten mail fields to `env_backed`
                # and this scan stopped seeing all ten, which is why the ratchet
                # had been falling for reasons that were not documentation.
                elif isinstance(func, ast.Name) \
                        and func.id in ("env_backed", "env_backed_flag") \
                        and len(node.args) >= 3 and isinstance(node.args[2], ast.Constant) \
                        and isinstance(node.args[2].value, str):
                    name = node.args[2].value
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                    and node.value.attr == "environ" and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                name = node.slice.value
            if name:
                found.setdefault(name, set()).add(rel)
    return found


@lru_cache(maxsize=1)
def _corpus() -> tuple:
    """Every tracked file except `.env.example`, read once."""
    texts = []
    for rel in _tracked():
        if rel == ".env.example":
            continue
        try:
            texts.append((ROOT / rel).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return tuple(texts)


def unreferenced(names) -> list[str]:
    """Declared names that appear nowhere else in the repository."""
    corpus = _corpus()
    return sorted(n for n in names if not any(n in text for text in corpus))


# ── `B20`: can the variable do anything once it is read? ────────────────────


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def shipped_defaults() -> dict:
    """`DEFAULT_SETTINGS` as written in `src/settings.py`.

    Only what a literal can express: a key whose default is built by a call or
    a comprehension is recorded as `UNREADABLE`, which is falsy, i.e. never
    flagged. Under-reporting is the right direction for a hard rule — a checker
    that guesses at a value it cannot see would fail a build over its own guess.

    `B90` is why that is a sentinel and not `None` any more. A literal `None` in
    `DEFAULT_SETTINGS` became meaningful — it is the tri-state a stored `False`
    needs to mean *no* — so "ships None" and "we could not read it" stopped
    being the same fact. `UNREADABLE` is falsy so every existing caller reading
    this by truthiness is unchanged, and `is None` now means what it says.
    """
    try:
        tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "DEFAULT_SETTINGS"
                and isinstance(node.value, ast.Dict)):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            name = _str(key)
            if name is None:
                continue
            try:
                out[name] = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                out[name] = UNREADABLE
    return out


def _env_name_of(node, consts: dict):
    """The variable an `os.getenv(...)`-shaped call reads, or None.

    Resolves a module-level string constant, unlike `literal_reads` above. That
    asymmetry is deliberate and is the reason this is a second walk rather than
    a widening of the first: `literal_reads` feeds the UNDECLARED ratchet, whose
    ceiling an operator reads off `ci.yml`, and a scan that suddenly sees more
    names would move that number without a line of product code changing.
    `PANTHEON_TASK_CONCURRENCY_CAP` is read as `os.getenv(TASK_CONCURRENCY_CAP_ENV)`
    and is exactly the variable `H06` found dead, so a rule that could not see
    it would not have caught the defect it exists for.
    """
    func = node.func
    getenvish = (
        (isinstance(func, ast.Attribute) and (
            func.attr == "getenv"
            or (func.attr in ("get", "pop")
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ")))
        or (isinstance(func, ast.Name) and func.id == "getenv"))
    if not (getenvish and node.args):
        return None
    arg = node.args[0]
    return _str(arg) or (consts.get(arg.id) if isinstance(arg, ast.Name) else None)


def _called(node) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _settings_receiver(node) -> bool:
    """Whether `<x>.get("k")` is reading settings rather than any other dict."""
    try:
        receiver = ast.unparse(node.func.value)
    except Exception:
        return False
    return "etting" in receiver


def _module_consts(tree) -> dict:
    return {n.targets[0].id: _str(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and _str(n.value)}


class _Unreadable:
    """A default this checker could not evaluate — a call, a comprehension.

    **Deliberately neither truthy nor falsy in meaning, and not `None`.** It was
    written falsy first, so that `not shipped` would skip it the way a bare
    `None` used to, and a mutation removing the explicit guard survived: the
    guard was decoration resting on the sentinel's own `__bool__`. That is the
    same shape `B20` found and restructured rather than left. Unknown is not
    false; the caller must say so, and now it has to, because without the guard
    an unreadable default falls through to the truthy-default rule and reports
    a finding nobody can act on."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<unreadable>"


UNREADABLE = _Unreadable()
_NO_SUCH_KEY = object()


def unreachable(defaults: dict) -> list[str]:
    """Env reads that sit beneath a settings key shipping a truthy default.

    The pairing is by name — `PANTHEON_TASK_CONCURRENCY_CAP` to
    `task_concurrency_cap` — which is how every pair in this tree is spelled
    and is the only correspondence a reader can check without running anything.
    """
    found = []
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES):
            continue
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        consts = _module_consts(tree)
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [tree]
        for scope in scopes:
            keys, envs, asked = {}, {}, False
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                name = _env_name_of(node, consts)
                if name:
                    envs.setdefault(name, node.lineno)
                called = _called(node)
                if called in ("setting_is_explicit", "is_setting_overridden", "env_backed"):
                    asked = True
                if called in ("get_setting", "get_user_setting") and node.args:
                    arg = node.args[0]
                    key = _str(arg) or (consts.get(arg.id) if isinstance(arg, ast.Name) else None)
                    if key:
                        keys.setdefault(key, node.lineno)
            if asked:
                continue
            for key, line in keys.items():
                shipped = defaults.get(key, _NO_SUCH_KEY)
                if shipped is _NO_SUCH_KEY or isinstance(shipped, UNREADABLE.__class__):
                    # Not a key we ship, or a default we could not evaluate.
                    # Guessing at a value this checker cannot see is how a hard
                    # rule starts failing builds over its own arithmetic.
                    continue
                if shipped is not None and not shipped:
                    # A falsy literal default. The env leg beneath it is
                    # genuinely reachable — that is `H06`'s whole distinction —
                    # and a key that is not tri-state has nothing to flatten.
                    continue
                for env, env_line in envs.items():
                    stem = env[len("PANTHEON_"):] if env.startswith("PANTHEON_") else env
                    if stem.lower() != key:
                        continue
                    if shipped is None:
                        # `B90`. A key shipping `None` is tri-state on purpose:
                        # absent, yes, and **no**. `get_setting` merges the
                        # default on every read, so `bool(get_setting(K, False))`
                        # collapses the stored `no` back into the absence it was
                        # added to be distinguishable from — which is the exact
                        # line that let `PANTHEON_ALLOW_MODEL_DOWNLOAD=1` beat a
                        # `Law 16` gate an operator had turned off. Measured
                        # 2026-09-15: stored `False`, effective `True`.
                        found.append(
                            f"{rel}:{env_line} {env} is read beside {key} (:{line}), "
                            f"which ships None because its stored False has to mean "
                            f"*no* — get_setting flattens that back to absence; use "
                            f"settings.env_backed_flag")
                    else:
                        found.append(
                            f"{rel}:{env_line} {env} is read beneath {key}, which ships "
                            f"{shipped!r} — get_setting merges DEFAULT_SETTINGS on "
                            f"every read (:{line}), so this line cannot run")
    return sorted(set(found))


def mixed_layers() -> list[str]:
    """One dict, some values env-backed and one read straight off settings."""
    found = []
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES):
            continue
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        # `routes/email_helpers.py` spells it `_v = lambda k, e, d="": env_backed(...)`
        # and eleven values later that lambda is the only thing distinguishing the
        # ten fields that reach the environment from the one that does not.
        alias = {n.targets[0].id for n in ast.walk(tree)
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Lambda)
                 and any(isinstance(c, ast.Call) and _called(c) == "env_backed"
                         for c in ast.walk(n.value.body))}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            backed, raw = set(), []
            for value in node.values:
                for call in ast.walk(value):
                    if not isinstance(call, ast.Call):
                        continue
                    called = _called(call)
                    if called == "env_backed" and len(call.args) >= 3 and _str(call.args[1]):
                        backed.add(_str(call.args[1]))
                    elif called in alias and call.args and _str(call.args[0]):
                        backed.add(_str(call.args[0]))
                    elif called == "get" and call.args and _str(call.args[0]) \
                            and _settings_receiver(call):
                        raw.append((_str(call.args[0]), call.lineno))
            if not backed:
                continue
            for key, line in raw:
                if key in backed:
                    continue
                found.append(
                    f"{rel}:{line} {key} is read straight off settings while "
                    f"{len(backed)} siblings in the same dict go through env_backed — "
                    f"its environment layer is unreachable here and reachable elsewhere")
    return sorted(set(found))


def _env_derived(node, consts: dict) -> list[str]:
    """Environment names an expression subtree reads, resolving module consts."""
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _env_name_of(child, consts)
            if name:
                names.append(name)
        elif isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) \
                and child.value.attr == "environ":
            name = _str(child.slice) or (consts.get(child.slice.id)
                                         if isinstance(child.slice, ast.Name) else None)
            if name:
                names.append(name)
    return names


# `B91`. Every token any site in the tree accepted as yes or no on 2026-09-15.
# A comparison drawn wholly from this set is a truthiness rule; one that is not
# — `TERM == "dumb"`, `PANTHEON_SCRIPT_HOST in ("", "localhost", …)`, a duration,
# a hostname — is a different question and is none of this rule's business.
_TRUTH_TOKENS = {"1", "0", "true", "false", "yes", "no", "on", "off", "y", "n",
                 "t", "f", "enable", "disable", "enabled", "disabled",
                 # `""` is a member of three real off-lists in this tree —
                 # `not in ("0","false","no","off","")`. Leaving it out made the
                 # rule silently skip the whole comparison; a test caught it.
                 ""}
_SPELLING_EXEMPT = re.compile(r"env-spelling:\s*(.+)")


def spellings() -> list[str]:
    """Environment truthiness spelled inline instead of read from `env_flags`.

    `B91`. Measured 2026-09-15 by this same walk: **38 environment booleans, 10
    incompatible rules**. `PANTHEON_STARTUP_WARMUPS=1` was on and
    `IMAP_STARTTLS=1` was off in one process; `AUTH_ENABLED=0` left auth
    enabled; `CLEANUP_ENABLED=" true"` was off because one site of the 38 never
    called `.strip()`. Nothing errored and `.env.example` documented none of it.

    A site may keep its own rule by saying so — `# env-spelling: <reason>` on the
    line or in the three above it. Nine do, and every one of them is a case
    where adopting the shared vocabulary would loosen a control or flip a live
    deployment. The exemption carries the reason **at the site** rather than in a
    list here, for the same reason `NOT_OURS` makes each entry say whose it is:
    a list of names in a checker is a list nobody reads next to the code it is
    about. Hard rule, max 0 unexempted.

    Blind the same way `unreachable` and `mixed_layers` are, and worth saying:
    it sees a comparison, so a site that assigns `os.environ.get(X)` to a name
    in one function and judges it in another is invisible here. What it catches
    is the shape that produced all ten rules — the comparison written inline
    beside the read.
    """
    found = []
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES) or rel == "src/env_flags.py":
            continue
        try:
            source = (ROOT / rel).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue
        lines = source.splitlines()
        consts = _module_consts(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
                continue
            op, right = node.ops[0], node.comparators[0]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                values = [_str(right)] if _str(right) is not None else []
            elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(
                    right, (ast.Tuple, ast.Set, ast.List)):
                values = [_str(e) for e in right.elts]
            else:
                continue
            if not values or any(v is None for v in values):
                continue
            if not all(v.strip().lower() in _TRUTH_TOKENS for v in values):
                continue
            names = _env_derived(node.left, consts)
            if not names:
                continue
            # Walk up through the contiguous comment block rather than a fixed
            # window: the reasons these sites are held run to five and six lines
            # and a window sized to today's longest one is a trap for tomorrow's.
            index = node.lineno - 1
            while index >= 0 and (lines[index].lstrip().startswith("#")
                                  or index == node.lineno - 1):
                if _SPELLING_EXEMPT.search(lines[index]):
                    break
                index -= 1
            else:
                index = -1
            if index >= 0:
                continue
            found.append(
                f"{rel}:{node.lineno} {'/'.join(sorted(set(names)))} is judged by an "
                f"inline {sorted(values)} — call env_flags.env_flag, or say why not "
                f"with `# env-spelling: <reason>`")
    return sorted(set(found))


def exempt_spellings() -> list[str]:
    """The `# env-spelling:` holds, so `--list` can print the whole set."""
    out = []
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES):
            continue
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            match = _SPELLING_EXEMPT.search(line)
            if match:
                out.append(f"{rel}:{lineno} {match.group(1).strip()}")
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=74,
                    help="ceiling for undeclared variables (may fall, never rise)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    known = declared()
    reads = literal_reads()
    missing = sorted(set(reads) - set(known) - set(NOT_OURS))
    dead = unreferenced(known)
    stranded = unreachable(shipped_defaults())
    split = mixed_layers()
    spelled = spellings()
    held = exempt_spellings()

    print(f"env vars  read {len(reads)}  ·  declared {len(known)}  ·  "
          f"not ours {len(NOT_OURS)}  ·  UNDECLARED {len(missing)} (max {args.max})  ·  "
          f"UNREFERENCED {len(dead)} (max 0)  ·  UNREACHABLE {len(stranded)} (max 0)  ·  "
          f"MIXED {len(split)} (max 0)  ·  SPELLING {len(spelled)} (max 0, "
          f"{len(held)} held)")

    failed = False
    if spelled:
        failed = True
        print("\n  Environment truthiness spelled inline. Ten incompatible rules is "
              "how `PANTHEON_X=1` came to mean yes in one module and no in the next, "
              "with nothing to error and nothing to log (`B91`):")
        for line in spelled:
            print(f"    {line}")
    if stranded:
        failed = True
        print("\n  Read beside a settings key `get_setting` cannot answer for. The "
              "merge runs on every read, so a truthy shipped default makes the line "
              "below it dead (`H06`, `B20`) and a `None` one — the tri-state a "
              "stored `False` needs to mean *no* — is flattened back to absence "
              "(`B90`). Ask `setting_is_explicit`, `env_backed` or `env_backed_flag`:")
        for line in stranded:
            print(f"    {line}")
    if split:
        failed = True
        print("\n  One dict, two rules. A field left on `settings.get` beside fields "
              "that go through `env_backed` has an environment layer everywhere except "
              "here, and nothing in settings.json looks wrong (`H07`, `B20`):")
        for line in split:
            print(f"    {line}")
    if dead:
        failed = True
        print("\n  Declared in .env.example and used by nothing — an operator who sets "
              "one of these believes something changed:")
        for name in dead:
            print(f"    {name} (line {known[name]})")
    stale = sorted(set(NOT_OURS) - set(reads))
    if stale:
        failed = True
        print("\n  NOT_OURS names variables nothing reads any more. An exemption that "
              "outlives its call site hides the next one that needs looking at:")
        for name in stale:
            print(f"    {name} — {NOT_OURS[name]}")
    if len(missing) > args.max:
        failed = True
        print(f"\n  The undeclared count rose from {args.max} to {len(missing)}. "
              "This ratchet only comes down: document the new variable in "
              ".env.example, or add it to NOT_OURS with whose it is.")
        for name in missing[args.max:]:
            print(f"    {name}  ({sorted(reads[name])[0]})")
    if args.list:
        print()
        for name in missing:
            print(f"  {name:44} {sorted(reads[name])[0]}")
        print("\n  Sites keeping their own truthiness rule, and why (`B91`):")
        for line in held:
            print(f"    {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
