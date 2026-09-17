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

**What it adds over CI**: nothing that CI does not also do. `py_compile` and
`node --check` run over the one list of which files are ours, and `ci.yml`'s
syntax jobs call these same two functions rather than keeping their own (`B10`,
`B436`); the retrieval eval is a report rather than a gate (`P13-13`) and is
printed here because a number nobody looks at is a number that drifts.

**What it does NOT do, and now says so.** `B432`: five waves shipped on
2026-09-17, each reporting "gate green on 22 checkers", and every one of those
was a `--fast` run — so "gate passed" meant "the suite did not run" five times
in a row while CI was red and nobody noticed. Three separate things were
invisible at once:

  - `--fast` skips the suite, and the only trace of it was the word "everything"
    missing from a line that otherwise reads "gate passed";
  - this gate mirrors `ci.yml` and nothing else, while a push also runs the
    secret scan, the workflow-security audit, the dependency review and the
    container scan — four blocking gates it has never claimed to run and never
    admitted not running;
  - it runs on whatever interpreter and node happen to be on the developer's
    PATH, against a workflow that pins both. Measured here on 2026-09-17: node
    22 locally against a workflow pinning 20.

None of those are failures. All three are things a reader of a green run was
entitled to know, so every run now ends with what it did not cover.

**Divergence is read, not remembered** (`B431`). The interpreter, the node
version, the suite's own argv and the advisory step's argv all come out of the
workflow the same way the checker list does. The suite used to run
`-p no:randomly` here and `-q` in CI, so a local pass was evidence about a
**fixed test order CI does not use**; `.pantheon/check-ci-contract.py` is what
now fails when the two drift apart again.

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


def _ci_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.exists() else ""


def ci_python_version() -> str | None:
    """The interpreter `ci.yml` pins, read from the workflow.

    `B431`. Not to enforce — a contributor on 3.12 must still be able to run
    this — but because "the gate passed" is a claim about a run, and a run on a
    different interpreter is a different run. It goes in the not-covered block.
    """
    found = re.findall(r"^\s*python-version:\s*[\"']?([\w.]+)[\"']?\s*$",
                       _ci_text(), re.M)
    return found[0] if found else None


def ci_node_version() -> str | None:
    found = re.findall(r"^\s*node-version:\s*[\"']?([\w.]+)[\"']?\s*$",
                       _ci_text(), re.M)
    return found[0] if found else None


def ci_suite_args() -> list[str]:
    """The arguments CI gives the whole-suite pytest run.

    Read rather than written down. This is where the two had actually drifted:
    the gate passed `-p no:randomly` and CI does not, so every local suite run
    was evidence about a fixed order and CI's was not. An invocation that names
    a path under `tests/` is a *targeted* run (`law16-egress`) and is not the
    suite.
    """
    for m in re.finditer(r"run:\s*python3?\s+-m\s+pytest([^\n#]*)", _ci_text()):
        args = m.group(1).split()
        if not any(a.startswith("tests/") for a in args):
            return args
    return ["-q"]


def ci_advisory_argv() -> list[str]:
    """`P13-13`'s report, with the flags CI gives it. It ran `--verbose` in the
    workflow and bare here, which is two commands wearing one name."""
    m = re.search(r"run:\s*python3?\s+(\.pantheon/retrieval_eval\.py[^\n#]*)",
                  _ci_text())
    return m.group(1).split() if m else [".pantheon/retrieval_eval.py"]


def _node_version() -> str | None:
    if not shutil.which("node"):
        return None
    out = subprocess.run(["node", "--version"], capture_output=True, text=True)
    return out.stdout.strip().lstrip("v") or None


def environment_divergence() -> list[str]:
    """Every way this machine is not the machine CI uses.

    Reported, never enforced. The moment a gate refuses to run because somebody
    has the wrong node is the moment people stop running it — and a gate nobody
    runs was `P10-10`'s whole complaint.
    """
    out: list[str] = []
    want_python = ci_python_version()
    have_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    # Compared on major.minor: `3.11.15` and `3.11.9` are the same claim, and a
    # workflow that pinned `3.11.15` would be pinning a patch nobody chose.
    if want_python and want_python.split(".")[:2] != have_python.split(".")[:2]:
        out.append(f"python {have_python} here, CI pins {want_python}")
    want_node = ci_node_version()
    have_node = _node_version()
    if want_node and have_node and have_node.split(".")[0] != want_node.split(".")[0]:
        out.append(f"node {have_node} here, CI pins {want_node}")
    return out


def workflows_not_run_here() -> list[str]:
    """The other workflows a push sets off, which this gate does not run.

    `B432`. Four of them block a merge (`docs/security-ci.md`), and this script
    has never run one or said that it does not. The filenames are read from the
    directory rather than listed, so a workflow added tomorrow is named here the
    day it lands. What is inside them is
    `.pantheon/check-ci-contract.py`'s subject, not this file's.
    """
    out = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        if path.name == WORKFLOW.name:
            continue
        head = path.read_text(encoding="utf-8").split("jobs:", 1)[0]
        if re.search(r"^\s{0,4}(pull_request|push):\s*$", head, re.M):
            out.append(path.name)
    return out


def not_covered(fast: bool, node_skipped: bool) -> list[str]:
    """Everything a green exit from this script is not evidence about."""
    lines = []
    if fast:
        lines.append(
            "NOT RUN   the suite — `--fast` skips it. This run says nothing "
            "about whether the tests pass.")
    if node_skipped:
        lines.append(
            "NOT RUN   node --check — node is not on PATH, so no JavaScript "
            "was parsed.")
    others = workflows_not_run_here()
    if others:
        lines.append(
            f"NOT RUN   {len(others)} workflows a push also sets off, four of "
            f"them merge-blocking: {', '.join(others)}")
    for line in environment_divergence():
        lines.append(f"DIVERGES  {line} — this run is not evidence about CI's.")
    lines.append(
        "NOT COVERED  the manual pass over every surface (`P10-10`). This "
        "script cannot do it and does not pretend the gate covers it.")
    return lines


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


# `B10`. Vendored roots, spelled the way `.pantheon/check-licences.py` spells
# them: not ours to parse, and some are minified past the point node accepts
# without a module hint.
_VENDORED = ("static/lib/", "library/")


def _js_files() -> list[str]:
    """Every `.js` and `.mjs` in the tree that is ours.

    This used to be `static/js/*.js` + `static/*.js`, which left the two
    `.github/scripts/` helpers, six test harnesses and seven `.mjs` files
    checked by nothing while `docs/security-ci.md` advertised "JS syntax" as a
    merge-blocking status check. Widening it is free — all thirteen already
    parse — and it makes the gate's number mean what its name says (`B10`).
    """
    out = subprocess.run(["git", "ls-files", "*.js", "*.mjs"],
                         cwd=str(ROOT), capture_output=True, text=True)
    return [f for f in out.stdout.split()
            if f and not any(f.startswith(root) for root in _VENDORED)]


def _node_check(files: list[str]) -> tuple[bool, str]:
    """`node --check` cannot read ES modules from a path, so each file is piped
    in with `--input-type=module`. The same trick the JS tests use.

    **The piping is the whole check, not a convenience** (`B10`). Given a PATH,
    node resolves module type from the nearest `package.json` — and the root
    one has no `"type"`, so `static/app.js` parses as CommonJS. Node's
    module-syntax detection then retries the failed CJS parse as ESM and does
    not re-check, so ANY file containing `import`/`export` passes
    unconditionally: `node --check static/app.js` returns 0 on a file whose
    body is `this is not javascript at all !!! ( [ {`. Measured on node 20 and
    22. CI ran exactly that loop, over a path, and was therefore checking
    nothing at all on the 4,641-line module it named first."""
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
        print("\nthen: py_compile, node --check, "
              f"{' '.join(ci_advisory_argv())} (advisory)"
              + ("" if args.fast else f", pytest {' '.join(ci_suite_args())}"))
        print()
        for line in not_covered(args.fast, not shutil.which("node")):
            print(f"  {line}")
        return 0

    if not from_ci:
        print(f"! {WORKFLOW.relative_to(ROOT)} has no checker steps — nothing to mirror.")
        return 1

    # `B432`. The header says it before the run and the footer says it after,
    # because the thing that went wrong five times in one day was a person
    # reading the last line of a long output and taking "gate passed" for
    # "everything passed".
    print(f"release gate · {len(from_ci)} checkers from CI"
          + (f" · {len(extra)} not in CI" if extra else "")
          + ("  ·  SUITE NOT RUN (--fast)" if args.fast
             else f"  ·  suite: pytest {' '.join(ci_suite_args())}"))
    print()

    steps: list[tuple[str, list[str]]] = [
        (name, [sys.executable, *argv]) for name, argv in from_ci
    ]
    for name, argv in extra:
        steps.append((f"{name} (not in CI)", [sys.executable, *argv]))
    steps.append(("py_compile", [sys.executable, "-m", "py_compile", *_python_files()]))
    steps.append(("retrieval eval", [sys.executable, *ci_advisory_argv()]))
    if not args.fast:
        steps.append(("pytest", [sys.executable, "-m", "pytest", *ci_suite_args()]))

    failed: list[str] = []
    for label, argv in steps:
        ok, secs, tail = _run(label, argv)
        mark = "ok  " if ok else ("warn" if label in ADVISORY else "FAIL")
        print(f"  {mark}  {label:<24} {secs:6.1f}s  {tail[:96]}")
        if not ok and label not in ADVISORY:
            failed.append(label)

    # `B432`. A step that did not run is `skip`, never `ok`. Node missing is a
    # legitimate reason not to parse any JavaScript and it is not a reason to
    # print the same word as a run that parsed 187 modules.
    node_skipped = not shutil.which("node")
    ok, detail = _node_check(_js_files())
    mark = "skip" if node_skipped else ("ok  " if ok else "FAIL")
    print(f"  {mark}  {'node --check':<24} {'':>6}   {detail[:96]}")
    if not ok:
        failed.append("node --check")

    print()
    if failed:
        print(f"GATE FAILED — {len(failed)}: {', '.join(failed)}")
    elif args.fast:
        print(f"GATE PASSED — {len(steps)} steps.  THE SUITE DID NOT RUN.")
    else:
        print(f"GATE PASSED — {len(steps)} steps, suite included. Safe to push, "
              "as far as this gate goes.")
    print()
    for line in not_covered(args.fast, node_skipped):
        print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
