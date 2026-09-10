#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""P10-10 — the full regression, as one command instead of a memory.

Every checker, every syntax pass and the suite have been run by hand before each
commit in this project. That works right up until the run somebody is tired
during, and then it fails silently: a gate you have to remember is a gate that
is sometimes not there.

**What this is not.** It is not CI — `.github/workflows/ci.yml` runs the same
fourteen checkers and the same suite on every push, and duplicating that logic
here would be two places to change a ratchet (`Law 13`). The checker list below
is **read out of the workflow file** for exactly that reason: CI is the source
of truth for which checks exist and at what ceiling, and this script is the way
to run CI's gate before pushing rather than after.

**What it adds over CI**: `py_compile` across the tree and `node --check` across
every module, which the workflow does per-job on changed files; and the
retrieval eval, which is a report rather than a gate (`P13-13`) and is printed
here because a number nobody looks at is a number that drifts.

    .pantheon/release-gate.py             everything
    .pantheon/release-gate.py --fast      everything except the suite
    .pantheon/release-gate.py --list      what would run, and from where

Exit code is the gate: zero means every required step passed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Steps that report but never fail the gate. `P3-20`'s lesson: a ratchet on a
# number nobody has calibrated is worse than no ratchet, and the first honest
# thing to know is what today's number is.
ADVISORY = {"retrieval eval"}


def _checkers_from_ci() -> list[tuple[str, list[str]]]:
    """The checker invocations CI actually runs, read from the workflow.

    Parsed rather than copied. A ceiling that lives in two files is a ceiling
    that will disagree with itself, and the disagreement will be discovered by
    a push that fails after a local run said it was fine.
    """
    if not WORKFLOW.exists():
        return []
    text = WORKFLOW.read_text(encoding="utf-8")
    found: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = re.search(r"run:\s*python3?\s+(\.pantheon/check-[\w-]+\.py[^\n#]*)", line)
        if not m:
            continue
        argv = m.group(1).split()
        found.append((Path(argv[0]).stem.replace("check-", ""), argv))
    return found


def _extra_checkers(known: set[str]) -> list[tuple[str, list[str]]]:
    """Checkers that exist on disk but are not in CI.

    Reported rather than silently included: a checker CI does not run is either
    a gap in CI or a file nobody deleted, and both are worth seeing.
    """
    out = []
    for path in sorted(ROOT.glob(".pantheon/check-*.py")):
        name = path.stem.replace("check-", "")
        if name not in known:
            out.append((name, [f".pantheon/{path.name}"]))
    return out


def _run(label: str, argv: list[str], timeout: int = 1800) -> tuple[bool, float, str]:
    start = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, time.time() - start, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return False, time.time() - start, str(e)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, time.time() - start, (tail[-1] if tail else "")


def _python_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                         capture_output=True, text=True)
    return [f for f in out.stdout.split() if f]


def _js_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "static/js/*.js", "static/*.js"],
                         cwd=str(ROOT), capture_output=True, text=True)
    # Vendored bundles are not ours to parse and some are minified past the
    # point node will accept without a module hint.
    return [f for f in out.stdout.split() if f and "/lib/" not in f]


def _node_check(files: list[str]) -> tuple[bool, str]:
    """`node --check` cannot read ES modules from a path, so each file is piped
    in with `--input-type=module`. The same trick the JS tests use."""
    if not shutil.which("node"):
        return True, "node not on PATH — skipped"
    bad = []
    for rel in files:
        src = (ROOT / rel).read_text(encoding="utf-8")
        proc = subprocess.run(["node", "--input-type=module", "--check"],
                              input=src, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            bad.append(rel)
    return not bad, (f"{len(files)} modules parse" if not bad
                     else f"{len(bad)} failed: {', '.join(bad[:3])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fast", action="store_true", help="skip the full suite")
    ap.add_argument("--list", action="store_true", help="print the plan and stop")
    args = ap.parse_args()

    from_ci = _checkers_from_ci()
    extra = _extra_checkers({n for n, _ in from_ci})

    if args.list:
        print(f"{len(from_ci)} checkers read from {WORKFLOW.relative_to(ROOT)}:")
        for name, argv in from_ci:
            print(f"  {name:<18} {' '.join(argv[1:]) or '(no ceiling)'}")
        if extra:
            print(f"\n{len(extra)} checker(s) on disk that CI does NOT run:")
            for name, _ in extra:
                print(f"  {name}")
        print("\nthen: py_compile, node --check, retrieval eval (advisory)"
              + ("" if args.fast else ", pytest -q"))
        return 0

    if not from_ci:
        print(f"! {WORKFLOW.relative_to(ROOT)} has no checker steps — nothing to mirror.")
        return 1

    print(f"release gate · {len(from_ci)} checkers from CI"
          + (f" · {len(extra)} not in CI" if extra else "")
          + (" · suite skipped" if args.fast else ""))
    print()

    steps: list[tuple[str, list[str]]] = [
        (name, [sys.executable, *argv]) for name, argv in from_ci
    ]
    for name, argv in extra:
        steps.append((f"{name} (not in CI)", [sys.executable, *argv]))
    steps.append(("py_compile", [sys.executable, "-m", "py_compile", *_python_files()]))
    steps.append(("retrieval eval", [sys.executable, ".pantheon/retrieval_eval.py"]))
    if not args.fast:
        steps.append(("pytest", [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly"]))

    failed: list[str] = []
    for label, argv in steps:
        ok, secs, tail = _run(label, argv)
        mark = "ok  " if ok else ("warn" if label in ADVISORY else "FAIL")
        print(f"  {mark}  {label:<24} {secs:6.1f}s  {tail[:96]}")
        if not ok and label not in ADVISORY:
            failed.append(label)

    ok, detail = _node_check(_js_files())
    print(f"  {'ok  ' if ok else 'FAIL'}  {'node --check':<24} {'':>6}   {detail[:96]}")
    if not ok:
        failed.append("node --check")

    print()
    if failed:
        print(f"GATE FAILED — {len(failed)}: {', '.join(failed)}")
        return 1
    print("gate passed." + ("" if args.fast else " Safe to push."))
    # `P10-10`'s other half is a person: a manual pass over every surface. This
    # script cannot do it and does not pretend the gate covers it.
    print("Not covered here: the manual pass over every surface (`P10-10`).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
