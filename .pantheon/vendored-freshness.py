#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ask npm and OSV about every vendored library, and fail on what nobody owns.

The half of `B330` that needs the network, run by
`.github/workflows/vendored-freshness.yml` weekly and on demand — never by the
product, never by the offline gate (`Law 16`; `check-vendored-versions.py` is
the offline half and is where the record lives).

It sorts every answer into five sections. Two of them are, by construction,
*nobody has accounted for this*: a version behind upstream with no roadmap row
that owns it (`behind_ok`), and an advisory against what we ship that the
record does not explain (`osv_known`). **Either one non-empty fails the run**
(`B437`): an advisory check that never fails is a check nobody reads, which is
the argument `B322` settled for `pip-audit`. The escape hatches are the record's
own fields, next to the version they excuse, so a bump orphans them.

`B437` also moved this out of a heredoc in the workflow, where no test could
reach it without parsing YAML. `ask` takes the two upstream questions as
functions, so `tests/test_the_vendored_freshness_job_fails_on_what_nobody_owns.py`
drives every decision with no network.

    python3 .pantheon/vendored-freshness.py      the weekly job
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-vendored-versions.py"
UA = {"User-Agent": "pantheon-vendored-freshness"}

# (key, heading). The order is the report's.
SECTIONS = (
    ("behind", "Behind upstream, with no row that owns it"),
    ("vulnerable", "Advisories against what we ship"),
    ("filed", "Behind upstream, filed"),
    ("excused", "Advisory hits explained in the record"),
    ("unknown", "Could not be asked"),
)
# The two sections nobody has accounted for. `B437`: these fail the run.
UNACCOUNTED = ("behind", "vulnerable")

# What a question that could not be answered raises: `URLError` and a read
# timeout are `OSError`s, a reply without `dist-tags` is a `KeyError`, and a
# body that is not JSON is a `ValueError`. Each is a line under *Could not be
# asked*, never a crash that hides the other answers.
_UNANSWERED = (OSError, KeyError, ValueError)


def _get(url: str, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=dict(UA))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def npm_dist_tags(pkg: str) -> dict:
    """npm's `dist-tags` for a package."""
    return _get("https://registry.npmjs.org/"
                + urllib.request.quote(pkg, safe="@"))["dist-tags"]


def osv_vulns(pkg: str, version: str) -> list:
    """OSV's advisories against `pkg@version` in the npm ecosystem."""
    return _get("https://api.osv.dev/v1/query", json.dumps({
        "package": {"name": pkg, "ecosystem": "npm"},
        "version": version,
    }).encode()).get("vulns", [])


def ask(records: Iterable[dict],
        dist_tags: Callable[[str], dict] = npm_dist_tags,
        advisories: Callable[[str, str], list] = osv_vulns) -> dict[str, list[str]]:
    """Every answer, sorted into `SECTIONS`."""
    found: dict[str, list[str]] = {key: [] for key, _ in SECTIONS}
    behind, vulnerable, unknown = found["behind"], found["vulnerable"], found["unknown"]
    filed, excused = found["filed"], found["excused"]

    def advisories_for(where: str, pkg: str, ver: str, known: dict) -> None:
        try:
            vulns = advisories(pkg, ver)
        except _UNANSWERED as exc:
            unknown.append(f"{pkg}@{ver}: OSV said {exc}")
            return
        for v in vulns:
            sev = (v.get("database_specific") or {}).get("severity", "")
            line = f"{where}: {v['id']} {sev}"
            why = known.get(v["id"])
            if why:
                excused.append(f"{line}\n      {why}")
            else:
                vulnerable.append(line)

    def behind_line(line: str, owner: str) -> None:
        # Being behind is allowed only when a roadmap row owns the decision. A
        # light that is always on is a light nobody reads, and "we know, here
        # is the row" is the difference between a backlog and a shrug.
        (filed if owner else behind).append(line + (f"  [{owner}]" if owner else ""))

    for rec in records:
        pkg, ver, reg = rec["package"], rec["version"], rec["registry"]

        # 1 — is there something newer?
        # `dist_tag` is which tag to compare against, and it is a field because
        # of Pyodide (`B335`): npm's `latest` is 314.x, a CPython-aligned line
        # that 0.27.x does not belong to, so asking for `latest` reports a
        # maintained runtime as permanently behind. The record names
        # `stable-0.27` and this asks for that.
        if reg == "npm":
            tag = rec.get("dist_tag") or "latest"
            try:
                tags = dist_tags(pkg)
            except _UNANSWERED as exc:
                unknown.append(f"{pkg}: registry said {exc}")
                tags = {}
            latest = tags.get(tag)
            if tags and latest is None:
                unknown.append(
                    f"{rec['entry']}: the record asks for dist-tag {tag!r} and npm "
                    f"publishes {sorted(tags)} — the line may have been retired")
            if latest and latest != ver:
                behind_line(f"{rec['entry']}: shipping {ver}, npm latest is {latest}",
                            rec["behind_ok"])
        else:
            # No machine-readable index. Named rather than skipped, so a library
            # whose upstream cannot be polled is still somebody's job rather
            # than quietly exempt. SheetJS is why: npm's `xlsx` stopped at
            # 0.18.5, OLDER than what Pantheon ships (CREDITS.md).
            unknown.append(f"{rec['entry']}: registry={reg!r} has no index this job "
                           f"can read — check {rec['source']} by hand")

        # 2 — does anyone know of an advisory against what we ship? OSV is asked
        # for the npm coordinate whatever the registry is: the advisories are
        # about the code, not about where it was downloaded from.
        advisories_for(f"{rec['entry']} {pkg}@{ver}", pkg, ver, rec["osv_known"])

        # 3 — `B336`. The packages INSIDE a bundle, at the versions its bytes
        # carry: html2pdf.js 0.14.0 has no advisory of its own and ships jsPDF
        # 4.0.0 with nine and DOMPurify 3.3.1 with eighteen.
        # `check-vendored-versions.py` rule 6 checks each version against the
        # shipped bytes offline, so what is asked here is what is in the file.
        for inner in rec.get("contains", []):
            ipkg, iver = inner["package"], inner["version"]
            where = f"{rec['entry']} ⊃ {ipkg}@{iver}"
            try:
                ilatest = dist_tags(ipkg)["latest"]
            except _UNANSWERED as exc:
                unknown.append(f"{ipkg}: registry said {exc}")
                ilatest = None
            if ilatest and ilatest != iver:
                behind_line(f"{where}: the bundle carries {iver}, npm latest is {ilatest}",
                            inner["behind_ok"])
            advisories_for(where, ipkg, iver, inner["osv_known"])
    return found


def decide(found: dict[str, list[str]]) -> int:
    """`B437`. The exit code: 1 when either unaccounted section has a line."""
    return 1 if any(found[key] for key in UNACCOUNTED) else 0


def render(found: dict[str, list[str]]) -> str:
    out = []
    for key, title in SECTIONS:
        lines = found[key]
        out.append(f"\n## {title}")
        out.append("\n".join(f"  {line}" for line in lines) if lines else "  none")
    if decide(found):
        out.append(
            "\nFAIL. Bump the library, record the new version, hash and today's date "
            "in .pantheon/check-vendored-versions.py, and update the CREDITS.md row.\n"
            "If being behind is a decision, name the row that owns it in the record's "
            "`behind_ok`; if a hit is a false positive — `xlsx` always is, see "
            "CREDITS.md — explain it in the record's `osv_known`, not in a comment here.")
    else:
        out.append("\nOK — nothing is behind upstream or under an advisory without a "
                   "record that says why.")
    return "\n".join(out)


def recorded() -> list[dict]:
    """The record, as the offline checker exports it."""
    return json.loads(subprocess.run(
        [sys.executable, str(CHECKER), "--json"],
        capture_output=True, text=True, check=True, cwd=str(ROOT)).stdout)


def main(records: list[dict] | None = None,
         dist_tags: Callable[[str], dict] = npm_dist_tags,
         advisories: Callable[[str, str], list] = osv_vulns) -> int:
    found = ask(recorded() if records is None else records, dist_tags, advisories)
    print(render(found))
    return decide(found)


if __name__ == "__main__":
    raise SystemExit(main())
