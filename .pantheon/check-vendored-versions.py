#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The version we say we ship and the bytes we actually ship cannot disagree.

`B330`. Until 2026-09-16 a vendored library's version lived in one place: the
prose of `CREDITS.md`. Nothing compared it to anything. `check-licences.py`
checks *attribution* -- that every shipped third-party file is credited and its
licence text is present and linked -- and it is deliberately silent about which
release those bytes are, because attribution does not change when a library is
upgraded.

So the versions drifted, silently, and the only reason anyone knew how far was
that a person ran a research pass by hand. On 2026-09-16 that pass found
`mammoth.js` 18 releases behind, `html2pdf.js` on a bundle carrying jsPDF 2.3.1
with twelve open advisories, `highlight.js` three minors behind two unnumbered
ReDoS fixes, and `node-qrcode` with no recorded version at all -- the file could
not even be identified without rebuilding candidate versions and comparing
hashes.

A one-time bump fixes none of that. It drifts again within a month. **This is
the mechanism**, and it makes two claims that a person cannot forget to make:

  1. Every file under `static/lib/` is fingerprinted against a recorded
     sha256. Replace a byte and this fails. Bump a library without recording
     the new version and this fails. There is no way to change the bytes and
     leave the record saying the old thing.
  2. Every recorded version is the version `CREDITS.md` prints on the row that
     links that library's licence. The prose is checked against the record
     rather than maintained beside it.

**Law 14 -- this does not own a second list of the vendored files.**
`.pantheon/check-licences.py` has that list, as `INVENTORY`, and it is imported
here. A `Vendored` record below is keyed by an `Entry`'s *name*, the files it
covers come from that entry's own globs, and rule 1 fails if either side names
something the other does not. Neither list can grow, shrink or be renamed
without the other following.

**Law 16 -- this never touches the network.** Developers run
`.pantheon/release-gate.py --fast` constantly and offline; a checker that
resolved a registry would make the gate depend on somebody else's uptime. It
reads the repository and fails on internal inconsistency. Asking npm and OSV
whether something *newer* exists is a different question with a different
failure mode, and it lives in `.github/workflows/vendored-freshness.yml`, which
is allowed to need the network because CI has it.

  python3 .pantheon/check-vendored-versions.py              # gate
  python3 .pantheon/check-vendored-versions.py --report     # the table
  python3 .pantheon/check-vendored-versions.py --max-age-days 180
  python3 .pantheon/check-vendored-versions.py --json       # for the workflow

**`checked` is not a ratchet by default.** It is the date somebody last
confirmed against upstream that this version is the current one. Failing the
offline gate because a calendar day passed would redden CI on a repository
nobody changed, which teaches people to ignore it. `--max-age-days` exists for
whoever wants that ratchet; the freshness workflow is what actually goes red
when a newer release exists, because that is a fact about the world and not
about the clock.

**Two entries delegate instead of re-pinning.** `static/lib/pyodide/` and
`static/lib/swagger-ui/` were vendored by `scripts/fetch-pyodide.py` and
`scripts/fetch-swagger-ui.py`, which already write a `MANIFEST.json` holding
each file's sha256 and the package version. Copying those hashes here would be
the same defect this file exists to prevent, one level up. So those records
carry `manifest=` instead of `files=`, the hashes are read out of the manifest,
and the manifest's own `version` has to agree with the one recorded here.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import pathlib
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The root this checker fingerprints. `check-licences.py` scans four roots for
# *attribution*; this one is about released library versions, and `static/lib/`
# is where a released third-party library lands. `static/fonts/` and
# `static/icons/` hold assets whose entries are font families and vendor marks
# rather than versioned releases, and `library/` holds prose. Widening this is
# one string plus the records to match, and rule 1 will say exactly which
# records are missing.
FINGERPRINTED_ROOT = "static/lib/"


def _load_licences():
    """`check-licences.py` has a hyphen in its name, so it is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "_pantheon_check_licences", ROOT / ".pantheon" / "check-licences.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Vendored:
    """What release a vendored library is, and the bytes that prove it.

    `entry` is the `name` of the `check-licences.py` INVENTORY entry this
    covers — the join that keeps one list of files rather than two.

    `files` maps a repository path to its sha256. `manifest` is the alternative:
    a `MANIFEST.json` already written by a fetch script, whose `files` map and
    `version` are read instead. Exactly one of the two is given.

    `credits` is the literal string `CREDITS.md` has to carry on the row that
    links this library's licence text — usually `v<version>`, but Pyodide's row
    has never used the `v` and reading the tree is better than reformatting it.

    `source` is where the bytes came from, written down because "it is on a CDN
    somewhere" is how `node-qrcode` became unidentifiable. `build` is set where
    upstream publishes no browser artifact and we produced one: it is the exact
    command, so the bytes are reproducible rather than merely present.

    `behind_ok` and `osv_known` are what keep the freshness workflow from being
    a light that is always on. `behind_ok` names the roadmap row that owns the
    decision not to bump this library yet; a library that is behind upstream and
    names no row fails that workflow. `osv_known` maps an advisory id to why a
    hit against *this* version is not a live vulnerability here — written beside
    the version it excuses, so that bumping the version leaves behind an excuse
    that no longer matches anything and somebody has to look again. Neither
    field can silence the offline check: bytes are bytes.
    """

    def __init__(self, entry, package, version, checked, source, credits,
                 files=None, manifest=None, registry="npm", build=None, note=None,
                 behind_ok=None, osv_known=None):
        self.entry = entry
        self.package = package
        self.version = version
        self.checked = checked
        self.source = source
        self.credits = credits
        self.files = dict(files or {})
        self.manifest = manifest
        self.registry = registry
        self.build = build
        self.note = note
        self.behind_ok = behind_ok
        self.osv_known = dict(osv_known or {})


# ---------------------------------------------------------------------------
# The record. Every sha256 below was computed from the bytes in this commit;
# `--report` recomputes them, so a hand-edited hash is a hash that fails.
# ---------------------------------------------------------------------------

VENDORED = [
    Vendored(
        "highlight.js", "@highlightjs/cdn-assets", "11.12.0", "2026-09-16",
        "https://registry.npmjs.org/@highlightjs/cdn-assets/-/cdn-assets-11.12.0.tgz",
        "v11.12.0",
        files={"static/lib/highlight.min.js":
               "8ab71eb09c51f501e5e25157d9cff100e46cc29bcbfc744d0b746d451fca7f53"},
        note="No CVE at any version and no scanner will ever flag it. 11.12.0 "
             "carries unnumbered ReDoS fixes in the C/C++ and XML grammars, "
             "recorded only in the project's own CHANGES.md, and we highlight "
             "code the user did not write (B332).",
    ),
    Vendored(
        "SheetJS / xlsx", "xlsx", "0.20.3", "2026-09-16",
        "https://cdn.sheetjs.com/xlsx-0.20.3/",
        "v0.20.3",
        registry="sheetjs",
        osv_known={
            "GHSA-4r6h-8v6p-xvw6":
                "CVE-2023-30533, fixed upstream in 0.19.3. The npm advisory "
                "range is {introduced: 0} with no `fixed` event — 0.19.3 was "
                "never published to npm for a range to close against — so it "
                "matches 0.20.3 exactly as it matches 0.1.0. B333.",
            "GHSA-5pgg-2g8v-p4x9":
                "CVE-2024-22363, fixed upstream in 0.20.2. Same unbounded npm "
                "range, same reason. B333.",
        },
        files={"static/lib/xlsx.full.min.js":
               "cc015130aa8521e7f088f88898eba949ccdcbfb38df0bd129b44b7273c3a6f41"},
        note="NOT on npm and deliberately so. npm's `xlsx` dist-tags.latest is "
             "0.18.5 from 2022 — OLDER than this — so npm-based scanners report "
             "us vulnerable to CVE-2023-30533 and CVE-2024-22363 and are wrong, "
             "and `npm install xlsx` would downgrade us into both. See B333 and "
             "the SheetJS section of CREDITS.md before 'fixing' this.",
    ),
    Vendored(
        "docx", "docx", "8.5.0", "2026-09-16",
        "https://registry.npmjs.org/docx/-/docx-8.5.0.tgz",
        "v8.5.0",
        files={"static/lib/docx.umd.min.js":
               "02d568d203c0180af37609bcf5ff6c0919d220f933a88ca896eba0556a08faad"},
        note="Zero advisories at 8.5.0 (OSV, 2026-09-16). 9.x is current and the "
             "bump is not free — see B335.",
        behind_ok="B335 — 9.7.1 is current. A major across `exportAsDocx`, which is a "
             "user-visible path this wave did not touch.",
    ),
    Vendored(
        "mammoth.js", "mammoth", "1.12.3", "2026-09-16",
        "https://registry.npmjs.org/mammoth/-/mammoth-1.12.3.tgz",
        "v1.12.3",
        files={"static/lib/mammoth.browser.min.js":
               "f9465c0e4b91c6ab5fe03db285aa3c5bd33a1d20da781b8dffc5676bc9689a95"},
        note="Bumped from 1.8.0 on 2026-09-16 (B331). Fixes a crash on a "
             "document carrying mc:AlternateContent with no mc:Fallback, which "
             "1.8.0 rejected with a TypeError and no import.",
    ),
    Vendored(
        "html2pdf.js", "html2pdf.js", "0.14.0", "2026-09-16",
        "https://registry.npmjs.org/html2pdf.js/-/html2pdf.js-0.14.0.tgz",
        "v0.14.0",
        files={"static/lib/html2pdf.bundle.min.js":
               "9563c45f032179c73454293a649929e60fc24c05a326e8ab2811cfa8f25c3607"},
        note="Bumped from 0.10.2 on 2026-09-16 (B334), crossing jsPDF 2 -> 4. "
             "The published bundle carries jsPDF 4.0.0 and DOMPurify 3.3.1, "
             "neither of which is the current release of its own project; B336 "
             "holds that measurement and what it would cost to close.",
    ),
    Vendored(
        "node-qrcode", "qrcode", "1.5.4", "2026-09-16",
        "https://registry.npmjs.org/qrcode/-/qrcode-1.5.4.tgz",
        "v1.5.4",
        files={"static/lib/qrcode.min.js":
               "d59af15f40bc321f78871fe9d892d1dbbf05e35e20ad22aa51203c68185b58b6"},
        build="esbuild node_modules/qrcode/lib/browser.js --bundle --minify "
              "--format=iife --global-name=QRCode   (esbuild 0.25.0)",
        note="node-qrcode has shipped no browser build to npm since 1.5.1, so "
             "this file is built rather than fetched and the command above is "
             "the whole provenance. The bytes that were here before 2026-09-16 "
             "carried no version string and matched no published artifact; they "
             "were identified by reproduction as 1.5.1/1.5.3 (identical lib/, "
             "identical output) — see B337. Nothing in the served frontend loads "
             "this file; B338 is that finding.",
    ),
    Vendored(
        "KaTeX", "katex", "0.16.22", "2026-09-16",
        "https://registry.npmjs.org/katex/-/katex-0.16.22.tgz",
        "v0.16.22",
        files={
            "static/lib/katex/katex.min.js":
                "e8d885505949f3a5f4abdd5dd0d53696bd1371ad26ffbf4f310dcd77c8cdae89",
            "static/lib/katex/katex.min.css":
                "19095127357ed6d29fe0a63a6b000c913a89f7f1963b765dd3715e97c9852e75",
        },
        note="Zero advisories at 0.16.22 (OSV, 2026-09-16); 0.16.x is the "
             "current line.",
        behind_ok="B335 — 0.18.7 is current. A major across the math renderer.",
    ),
    Vendored(
        "KaTeX fonts", "katex", "0.16.22", "2026-09-16",
        "https://registry.npmjs.org/katex/-/katex-0.16.22.tgz",
        "v0.16.22",
        files={
            "static/lib/katex/fonts/KaTeX_AMS-Regular.woff2":
                "0cdd387c9590a1a9f9794560022dbb59654a7d86f187aa0c81495ad42d3a7308",
            "static/lib/katex/fonts/KaTeX_Caligraphic-Bold.woff2":
                "de7701e42cf1f4cf0b766c03fb27977207eee2f4fd5d76fa82188406da43ea4c",
            "static/lib/katex/fonts/KaTeX_Caligraphic-Regular.woff2":
                "5d53e70ad607c2352162dec9e0923fb54ecdafaccbf604cd8dcf7d00facb989b",
            "static/lib/katex/fonts/KaTeX_Fraktur-Bold.woff2":
                "74444efd593c005e3f4573b44524704c0af0a937fe911cca9e94068d0d140d3f",
            "static/lib/katex/fonts/KaTeX_Fraktur-Regular.woff2":
                "51814d270d06ff0255dba0799994fa4d8c84d11f09951d47595f4abb1f3602dc",
            "static/lib/katex/fonts/KaTeX_Main-Bold.woff2":
                "0f60d1b897938ec918c8ce073092411baf9438f6739465693ff18b0f9d20b021",
            "static/lib/katex/fonts/KaTeX_Main-BoldItalic.woff2":
                "99cd42a3c072d918f2f44984a807cf7aa16e13545fd0875fc07c6c65f99e715b",
            "static/lib/katex/fonts/KaTeX_Main-Italic.woff2":
                "97479ca6cce906abc961ecac96faa5f9ca2e61b8e7670d475826bcdee9a7c267",
            "static/lib/katex/fonts/KaTeX_Main-Regular.woff2":
                "c2342cd8b869e01752a9321dc17213fc40d4d04c79688c1d43f2cf316abd7866",
            "static/lib/katex/fonts/KaTeX_Math-BoldItalic.woff2":
                "dc47344dbb6cb5b655c8460d561f4df5f501b90c804ad3c6cec65fe322351ab1",
            "static/lib/katex/fonts/KaTeX_Math-Italic.woff2":
                "7af58c5ec8f132a2ddde9027c6d7814decce4d3b822a11192a42a20e2e973264",
            "static/lib/katex/fonts/KaTeX_SansSerif-Bold.woff2":
                "e99ae51144bf1232efcc1bfe5add36262c6866b0faab24fa75740e1b98577a62",
            "static/lib/katex/fonts/KaTeX_SansSerif-Italic.woff2":
                "00b26ac825e2095056396e0553b8ac26d3f8ad158c3826e28b4c45b385c4714a",
            "static/lib/katex/fonts/KaTeX_SansSerif-Regular.woff2":
                "68e8c73ef42afd3ccec58bf0fba302cce448938e7fc020a5e31f8a952eee1342",
            "static/lib/katex/fonts/KaTeX_Script-Regular.woff2":
                "036d4e95149b69ff9bcc0cd55771efeb25ffa3947293e69acd78d5ac328c684b",
            "static/lib/katex/fonts/KaTeX_Size1-Regular.woff2":
                "6b47c40166b6dbe21a5dfca7718413f2147fd2399be1ba605d8ad39cedf25dfe",
            "static/lib/katex/fonts/KaTeX_Size2-Regular.woff2":
                "d04c54219f9eaec6d4d4fd42dfb28785975a4794d6b2fc71e566b9cd6db842dd",
            "static/lib/katex/fonts/KaTeX_Size3-Regular.woff2":
                "73d591271b1604960cb10bb90fee021670af7297017e0e98480b332d11f51995",
            "static/lib/katex/fonts/KaTeX_Size4-Regular.woff2":
                "a4af7d414440a1c1790825cfb700cf9cf43b0f2c4b04f0ebc523011ad9853ec0",
            "static/lib/katex/fonts/KaTeX_Typewriter-Regular.woff2":
                "71d517d67827787cfabdf186914cc3358eda539e37931941f2b2fd4a21f68c0b",
        },
        note="Shipped with KaTeX and versioned with it — the fonts are in the "
             "same npm tarball. The row CREDITS.md links the OFL text from is "
             "in the font table rather than the library table, and it carries "
             "the version now; before 2026-09-16 it carried none, so a font "
             "swap and a KaTeX bump looked the same from the credits file.",
        behind_ok="B335 — versioned with KaTeX; it moves when KaTeX moves.",
    ),
    Vendored(
        "Mermaid", "mermaid", "11.16.1", "2026-09-16",
        "https://registry.npmjs.org/mermaid/-/mermaid-11.16.1.tgz",
        "v11.16.1",
        files={"static/lib/mermaid.min.js":
               "18327bef70d96fb505fe7287d9f6a7362ebf07ff6576ddfaffb1a06f3e1a2954"},
        note="Zero advisories at 11.16.1 (OSV, 2026-09-16). The three "
             "Microsoft vscode-* packages inside it are declared by B46's "
             "INVENTORY entry; their versions come out of the pnpm module "
             "paths in the shipped bytes.",
        behind_ok="B335 — 12.0.0 is current. A major, and mermaid.min.js is 3.5 MB of "
             "parser; the vscode-* bundled set has to be re-derived with it.",
    ),
    Vendored(
        "Pyodide", "pyodide", "0.27.5", "2026-09-16",
        "https://registry.npmjs.org/pyodide/-/pyodide-0.27.5.tgz",
        "0.27.5",
        manifest="static/lib/pyodide/MANIFEST.json",
        note="Hashes are not repeated here — scripts/fetch-pyodide.py owns "
             "them and writes MANIFEST.json.",
        behind_ok="B335 — npm `pyodide` dist-tags.latest is 314.x, which is not the "
             "runtime version line 0.27.5 belongs to; the comparison needs a "
             "human before it means anything.",
    ),
    Vendored(
        "Swagger UI", "swagger-ui-dist", "5.32.15", "2026-09-16",
        "https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.32.15.tgz",
        "v5.32.15",
        manifest="static/lib/swagger-ui/MANIFEST.json",
        note="Hashes are not repeated here — scripts/fetch-swagger-ui.py owns "
             "them and writes MANIFEST.json.",
        behind_ok="B335 — 5.33.0 is current. scripts/fetch-swagger-ui.py --version is "
             "how this one moves, and it re-pins hashes.",
    ),
]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_lib_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", FINGERPRINTED_ROOT],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def credit_lines(credits: str, licence_text: str) -> list[str]:
    """The CREDITS.md lines that link a given licence text."""
    return [ln for ln in credits.splitlines() if f"licenses/{licence_text}" in ln]


def _manifest_files(rec: Vendored, problems: list) -> dict:
    """The {repo path: sha256} a delegating record stands for.

    Returns {} and records a problem when the manifest cannot answer, so the
    caller never silently checks nothing — an empty expectation is how a hash
    check goes green over a file it never read.
    """
    path = ROOT / rec.manifest
    if not path.is_file():
        problems.append(
            f"NO MANIFEST  {rec.entry}: {rec.manifest} is named as the record "
            f"and is not on disk"
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"BAD MANIFEST {rec.manifest}: {exc}")
        return {}
    if data.get("version") != rec.version:
        problems.append(
            f"VERSION SPLIT {rec.entry}\n"
            f"             {rec.manifest} says {data.get('version')!r}, this "
            f"record says {rec.version!r}.\n"
            f"             One of the two was edited without the other."
        )
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        problems.append(
            f"EMPTY MANIFEST {rec.manifest} records no files, so delegating to "
            f"it checks nothing"
        )
        return {}
    base = str(pathlib.PurePosixPath(rec.manifest).parent)
    return {f"{base}/{name}": digest for name, digest in files.items()}


def check(max_age_days=None, today=None):
    """Every problem found, as a list of printable strings."""
    lic = _load_licences()
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    problems: list[str] = []
    today = today or datetime.date.today()

    by_name = {e.name: e for e in lic.INVENTORY}
    records = {r.entry: r for r in VENDORED}

    if len(records) != len(VENDORED):
        seen, dupes = set(), set()
        for r in VENDORED:
            (dupes if r.entry in seen else seen).add(r.entry)
        problems.append(f"DUPLICATE   two VENDORED records for {sorted(dupes)}")

    files = tracked_lib_files()

    # 1 — coverage, both ways. The join with check-licences.py's INVENTORY is
    # what keeps this from being a second list of the same files: an entry that
    # ships bytes under static/lib/ must have a version record, and a version
    # record must name an entry that exists.
    needs_record = set()
    for path in files:
        owners = [e.name for e in lic.INVENTORY if e.matches(path)]
        if not owners:
            # check-licences.py rule 1 owns this failure and says it better.
            continue
        needs_record.update(owners)
    for name in sorted(needs_record):
        if name not in records:
            problems.append(
                f"NO VERSION  {name}\n"
                f"            Ships bytes under {FINGERPRINTED_ROOT} and no "
                f"VENDORED record says which release they are.\n"
                f"            Add one with its version, its source and each "
                f"file's sha256."
            )
    for name in sorted(records):
        if name not in by_name:
            problems.append(
                f"NO ENTRY    {name}\n"
                f"            A VENDORED record names an INVENTORY entry that "
                f"does not exist in check-licences.py.\n"
                f"            The two lists are joined on this name; one of "
                f"them was renamed alone."
            )
        elif name not in needs_record:
            problems.append(
                f"NO BYTES    {name}\n"
                f"            A VENDORED record for an entry that matches no "
                f"tracked file under {FINGERPRINTED_ROOT}.\n"
                f"            Either the files went away or the entry's "
                f"patterns changed."
            )

    # 2, 3 — the recorded bytes are the shipped bytes.
    for name in sorted(records):
        rec = records[name]
        entry = by_name.get(name)
        if entry is None:
            continue
        owned = sorted(p for p in files if entry.matches(p))
        expected = _manifest_files(rec, problems) if rec.manifest else dict(rec.files)
        if rec.manifest and rec.files:
            problems.append(
                f"TWO RECORDS {name} gives both `manifest` and `files`; the "
                f"point of delegating is that there is one record"
            )
        for path in owned:
            want = expected.pop(path, None)
            if want is None:
                # A manifest legitimately does not record itself.
                if rec.manifest and path == rec.manifest:
                    continue
                problems.append(
                    f"UNPINNED    {path}\n"
                    f"            Shipped under {name} and no sha256 is "
                    f"recorded for it. Its bytes can change\n"
                    f"            without anything failing, which is the whole "
                    f"defect this file exists for."
                )
                continue
            got = sha256(ROOT / path)
            if got != want:
                problems.append(
                    f"HASH        {path}\n"
                    f"            recorded {want}\n"
                    f"            shipped  {got}\n"
                    f"            The file was replaced. If that is a version "
                    f"bump, record the new version,\n"
                    f"            the new hash and today's date in "
                    f"`checked`, and say so in CREDITS.md."
                )
        for path in sorted(expected):
            problems.append(
                f"GHOST       {path}\n"
                f"            {name} records a hash for a file git does not "
                f"track under {FINGERPRINTED_ROOT}."
            )

    # 4 — the prose is driven off the record.
    for name in sorted(records):
        rec = records[name]
        entry = by_name.get(name)
        if entry is None or not entry.text:
            continue
        lines = credit_lines(credits, entry.text)
        if not lines:
            # check-licences.py rule 3 owns "linked from nowhere".
            continue
        if not any(rec.credits in ln for ln in lines):
            problems.append(
                f"UNVERSIONED {name}\n"
                f"            CREDITS.md links licenses/{entry.text} and the "
                f"row does not carry {rec.credits!r}.\n"
                f"            A version in prose that nothing checks is the "
                f"version that drifts."
            )

    # 5 — the bookkeeping is a date.
    for name in sorted(records):
        rec = records[name]
        try:
            when = datetime.date.fromisoformat(rec.checked)
        except ValueError:
            problems.append(
                f"BAD DATE    {name}: checked={rec.checked!r} is not an ISO date"
            )
            continue
        if when > today:
            problems.append(
                f"FUTURE      {name}: checked={rec.checked} is in the future"
            )
        elif max_age_days is not None and (today - when).days > max_age_days:
            problems.append(
                f"STALE       {name}: last checked against upstream "
                f"{rec.checked}, {(today - when).days} days ago "
                f"(--max-age-days {max_age_days})"
            )

    return problems


def report() -> None:
    lic = _load_licences()
    by_name = {e.name: e for e in lic.INVENTORY}
    files = tracked_lib_files()
    print(f"{'library':<24} {'version':<12} {'checked':<12} {'files':>5} "
          f"{'bytes':>11}  source")
    print("-" * 110)
    total = 0
    for rec in VENDORED:
        entry = by_name.get(rec.entry)
        owned = sorted(p for p in files if entry and entry.matches(p))
        size = sum((ROOT / p).stat().st_size for p in owned)
        total += size
        print(f"{rec.entry:<24} {rec.version:<12} {rec.checked:<12} "
              f"{len(owned):>5} {size:>11,}  {rec.source}")
        for p in owned:
            print(f"    {sha256(ROOT / p)}  {p}")
        if rec.build:
            print(f"    built: {rec.build}")
    print("-" * 110)
    print(f"{len(VENDORED)} libraries · {len(files)} files · {total:,} bytes")


def as_json() -> None:
    print(json.dumps([
        {"entry": r.entry, "package": r.package, "registry": r.registry,
         "version": r.version, "checked": r.checked, "source": r.source,
         "built": bool(r.build), "behind_ok": r.behind_ok,
         "osv_known": r.osv_known}
        for r in VENDORED
    ], indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true",
                    help="print the table, hashes recomputed from the tree")
    ap.add_argument("--json", action="store_true",
                    help="the record as JSON, for the freshness workflow")
    ap.add_argument("--max-age-days", type=int, default=None,
                    help="also fail when a `checked` date is older than this")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.json:
        as_json()
        return 0
    if args.report:
        report()
        return 0

    problems = check(max_age_days=args.max_age_days)
    if not args.quiet:
        files = tracked_lib_files()
        print(f"vendored libraries {len(VENDORED)}  ·  fingerprinted files "
              f"{len(files)}  ·  root {FINGERPRINTED_ROOT}")
    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} vendored-version problem(s).")
        return 1
    if not args.quiet:
        print("OK — every vendored file matches its recorded version and hash.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
