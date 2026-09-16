#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B322` — the half of the dependency gate that needs a network, and therefore is not in the gate.

`.pantheon/release-gate.py` runs offline, constantly, on developer machines.
`.pantheon/check-pins.py` lives there and answers questions about what this
repository records: is every dependency pinned, does every accepted risk explain
itself, is anything configured to bump the pins. None of that needs a network,
and `Law 16`'s spirit is that a developer with no connection still gets the full
offline gate.

Asking whether a pinned version has an advisory published against it **today**
is a different question and it cannot be answered from a file. So it runs here,
from `.github/workflows/dependency-review.yml`, and never from the shipped
application: nothing in Pantheon calls a registry at runtime and nothing here
changes that.

**What it does.** Runs `pip-audit` over every requirements file plus the
Real-ESRGAN wheel pins (which live in a shell variable in
`docker/build-realesrgan-wheels.sh` and are read from there rather than copied,
so the two cannot disagree), then partitions the findings against
`.pantheon/dependency-advisories.toml`:

  * a finding with no register entry **fails the job**;
  * a finding with a register entry is printed **with its full reasoning**, so
    the justification appears in the log next to the failures rather than in a
    file a reader would have to know to open;
  * a register entry whose package was audited and whose advisory is no longer
    reported **fails the job** too. A suppression that has outlived its finding
    is the start of the rot this whole mechanism exists to prevent: the next
    person reads an ignore list that no longer describes anything.

    python3 .pantheon/audit-dependencies.py
    python3 .pantheon/audit-dependencies.py --report path.json   # audit an existing report
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEEL_SCRIPT = "docker/build-realesrgan-wheels.sh"


def _register() -> list[dict]:
    """The accepted-risk register, read by the checker that validates it.

    Imported rather than re-parsed. `Law 14`: one reader for one file. The
    checker is what refuses a malformed entry, so anything this script receives
    has already been through that rule in the offline gate.
    """
    path = ROOT / ".pantheon" / "check-pins.py"
    spec = importlib.util.spec_from_file_location("pantheon_check_pins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    entries, problems = module.load_advisories()
    if problems:
        for problem in problems:
            print(f"  {problem}")
        raise SystemExit(2)
    return entries


def realesrgan_pins() -> list[str]:
    """`name==version` for each Real-ESRGAN wheel the image builds.

    Read out of the build script's `SPECS` line. These three packages are
    installed into every image and appear in no requirements file, so without
    this they are audited by nothing — which is how `basicsr`'s advisory came to
    be visible only to someone who thought to run `pip-audit` inside a running
    container by hand.
    """
    path = ROOT / WHEEL_SCRIPT
    if not path.exists():
        return []
    m = re.search(r'^SPECS="([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    if not m:
        return []
    return [s for s in m.group(1).split() if "==" in s]


def audit(paths: list[pathlib.Path]) -> dict:
    """Run pip-audit over the given requirements files and return its report."""
    argv = [sys.executable, "-m", "pip_audit", "--format", "json",
            "--progress-spinner", "off"]
    for path in paths:
        argv += ["-r", str(path)]
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True)
    if not proc.stdout.strip():
        print(proc.stderr.strip()[-4000:])
        raise SystemExit(f"pip-audit produced no report (exit {proc.returncode})")
    return json.loads(proc.stdout)


def _ids(vuln: dict) -> set[str]:
    return ({vuln.get("id", "")} | set(vuln.get("aliases") or [])) - {""}


def partition(report: dict, register: list[dict]) -> tuple[list, list, list]:
    """Split a pip-audit report into `(failures, suppressed, stale)`.

    Pure, so it is tested against canned reports rather than against whatever
    the advisory database happens to say on the day the suite runs. A gate whose
    tests need a network is a gate whose tests are sometimes about the network.

    pip-audit can report the same advisory twice for one package (it does for
    `basicsr`, once per matching database range), so findings are deduplicated
    on `(package, version, id)` before anything is counted.
    """
    by_id: dict[str, dict] = {}
    for entry in register:
        by_id[entry["id"]] = entry
        for alias in entry.get("aliases") or []:
            by_id[alias] = entry

    failures: list[tuple[str, str, dict]] = []
    suppressed: list[tuple[str, str, dict, dict]] = []
    matched: set[str] = set()
    audited: set[str] = set()
    seen: set[tuple[str, str, str]] = set()

    for dep in report.get("dependencies", []):
        name = dep.get("name", "")
        version = dep.get("version", "")
        audited.add(name.lower().replace("_", "-"))
        for vuln in dep.get("vulns", []) or []:
            key = (name, version, vuln.get("id", ""))
            if key in seen:
                continue
            seen.add(key)
            entry = next((by_id[i] for i in _ids(vuln) if i in by_id), None)
            if entry is None:
                failures.append((name, version, vuln))
                continue
            if (entry["package"].lower().replace("_", "-") != name.lower().replace("_", "-")
                    or entry["version"] != version):
                # The register accepts one advisory for one package at one
                # version. The same id against a different package, or the same
                # package at a version nobody reasoned about, is a new finding.
                failures.append((name, version, vuln))
                continue
            matched.add(entry["id"])
            suppressed.append((name, version, vuln, entry))

    stale = [e for e in register
             if e["id"] not in matched
             and e["package"].lower().replace("_", "-") in audited]
    return failures, suppressed, stale


def _print_suppressed(rows: list) -> None:
    for name, version, vuln, entry in rows:
        print(f"\n  ACCEPTED RISK  {vuln.get('id')}  {name} {version}")
        print(f"    decided in     {entry['decision']} (.pantheon/DECISIONS.md)")
        print(f"    recorded in    .pantheon/dependency-advisories.toml")
        print(f"    reviewed by    {entry['review_by']} — {_oneline(entry['reviewed_by'])}")
        for field, label in (("what_it_is", "the bug"),
                             ("why_it_does_not_apply", "why it is unreachable here"),
                             ("fix_available", "what upstream offers"),
                             ("what_would_change_this", "what would change this")):
            print(f"    {label}:")
            for line in entry[field].strip().splitlines():
                print(f"      {line}")


def _oneline(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", help="audit an existing pip-audit JSON report "
                                     "instead of running pip-audit")
    args = ap.parse_args()

    register = _register()

    if args.report:
        report = json.loads(pathlib.Path(args.report).read_text(encoding="utf-8"))
    else:
        paths = sorted(ROOT.glob("requirements*.txt"))
        pins = realesrgan_pins()
        with tempfile.TemporaryDirectory() as tmp:
            if pins:
                extra = pathlib.Path(tmp) / "requirements-realesrgan.txt"
                extra.write_text(
                    "# Generated by .pantheon/audit-dependencies.py from "
                    f"{WHEEL_SCRIPT}. Not a file to edit.\n" + "\n".join(pins) + "\n",
                    encoding="utf-8",
                )
                paths.append(extra)
            print("auditing: " + ", ".join(
                p.name if p.is_relative_to(ROOT) else p.name for p in paths))
            report = audit(paths)

    failures, suppressed, stale = partition(report, register)

    if suppressed:
        print(f"\n{len(suppressed)} finding(s) accepted, with the reasoning that accepted them:")
        _print_suppressed(suppressed)

    if stale:
        print()
        for entry in stale:
            print(f"  STALE  {entry['id']} ({entry['package']} {entry['version']}) is "
                  f"no longer reported, but is still in "
                  f".pantheon/dependency-advisories.toml. Delete the entry — an ignore "
                  f"list that describes nothing is how people stop reading one.")

    if failures:
        print(f"\n{len(failures)} finding(s) with no recorded decision:")
        for name, version, vuln in failures:
            fixes = ", ".join(vuln.get("fix_versions") or []) or "none published"
            print(f"\n  {vuln.get('id')}  {name} {version}")
            print(f"    fixed in: {fixes}")
            print(f"    {_oneline(vuln.get('description') or '')[:400]}")
        print(
            "\nEither bump the pin to a fixed version, or record an accepted risk in "
            "\n.pantheon/dependency-advisories.toml with a DECISIONS.md entry behind it. "
            "\nAn entry with no reasoning is refused by .pantheon/check-pins.py."
        )

    print()
    if failures or stale:
        print(f"DEPENDENCY AUDIT FAILED — {len(failures)} unexplained, {len(stale)} stale")
        return 1
    print(f"dependency audit passed — {len(suppressed)} accepted risk(s), "
          f"0 unexplained findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
