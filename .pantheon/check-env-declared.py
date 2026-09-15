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

Both new rules are blind in the same way and it is worth stating: they see one
scope, or one dict, at a time. A resolver that reads the setting in one
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
                if getenvish and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    name = node.args[0].value
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
    a comprehension is recorded as `None`, i.e. falsy, i.e. never flagged.
    Under-reporting is the right direction for a hard rule — a checker that
    guesses at a value it cannot see would fail a build over its own guess.
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
                out[name] = None
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
                if not defaults.get(key):
                    continue
                for env, env_line in envs.items():
                    stem = env[len("PANTHEON_"):] if env.startswith("PANTHEON_") else env
                    if stem.lower() == key:
                        found.append(
                            f"{rel}:{env_line} {env} is read beneath {key}, which ships "
                            f"{defaults[key]!r} — get_setting merges DEFAULT_SETTINGS on "
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

    print(f"env vars  read {len(reads)}  ·  declared {len(known)}  ·  "
          f"not ours {len(NOT_OURS)}  ·  UNDECLARED {len(missing)} (max {args.max})  ·  "
          f"UNREFERENCED {len(dead)} (max 0)  ·  UNREACHABLE {len(stranded)} (max 0)  ·  "
          f"MIXED {len(split)} (max 0)")

    failed = False
    if stranded:
        failed = True
        print("\n  Read beneath a settings key whose shipped default is truthy. "
              "`get_setting` merges DEFAULT_SETTINGS on every read, so this is dead "
              "code from first boot — ask `settings.setting_is_explicit` whether the "
              "operator chose the value, or ship a falsy default (`H06`, `B20`):")
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
