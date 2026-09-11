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

    print(f"env vars  read {len(reads)}  ·  declared {len(known)}  ·  "
          f"not ours {len(NOT_OURS)}  ·  UNDECLARED {len(missing)} (max {args.max})  ·  "
          f"UNREFERENCED {len(dead)} (max 0)")

    failed = False
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
