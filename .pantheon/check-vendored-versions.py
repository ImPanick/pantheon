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


class Inside:
    """A package the bundle carries, at the version the shipped bytes say.

    `B336`. `check-licences.py` rule 7 answers *which* packages are inside a
    bundle; nothing answered *which release* each one is, so the fact that
    html2pdf.js 0.14.0 ships jsPDF 4.0.0 and DOMPurify 3.3.1 — neither of them
    its own project's current release — lived in a roadmap row and in nothing a
    machine read.

    `witness` is a literal string that has to be present in `where` (the
    bundle, or its extracted sidecar). That is the whole point: the version is
    not asserted, it is *read out of the artifact*, so replacing the bundle
    with one carrying a different jsPDF fails here until somebody re-measures.

    `osv_known` works exactly as it does on `Vendored`, and matters more: these
    are the advisories the freshness workflow counts every week against the
    versions actually inside the file, and each excuse is written beside the
    version it excuses, so a bump orphans them and somebody has to look again.
    """

    def __init__(self, package, version, witness, where=None, osv_known=None,
                 behind_ok=None, note=None):
        self.package = package
        self.version = version
        self.witness = witness
        self.where = where
        self.osv_known = dict(osv_known or {})
        self.behind_ok = behind_ok
        self.note = note


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
                 behind_ok=None, osv_known=None, contains=(), dist_tag="latest"):
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
        # `B336`. What this bundle carries, at the version its bytes say.
        self.contains = tuple(contains)
        # `B335`. Which npm dist-tag is the right comparison. Pyodide is why
        # this is a field: `dist-tags.latest` is 314.x, a CPython-aligned line
        # that 0.27.x does not belong to, so asking for `latest` reports a
        # library on a maintained line as permanently behind — a light that is
        # always on. The 0.27 line's own tag is `stable-0.27`.
        self.dist_tag = dist_tag


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
        note="Zero advisories at 8.5.0 AND at 9.7.1 (OSV, 2026-09-17), so "
             "this is currency, not exposure. 9.7.1 was fetched, run against "
             "the real `exportAsDocx` and measured on 2026-09-17 (B335): the "
             "API surface is unchanged and the body XML it emits for "
             "Pantheon's paragraph and run shapes is byte-identical. It is "
             "not the bytes that stopped the bump — see B424.",
        behind_ok="B424 — 9.7.1's Vite UMD build leaves `//#region "
             "node_modules/<pkg>/` markers for 44 bundled packages that "
             "8.5.0's rollup build did not, so the bump ships 44 newly visible "
             "third-party packages needing notices. Measured 2026-09-17.",
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
             "neither of which is the current release of its own project. "
             "B336's decision, 2026-09-17: STAY on the published artifact. "
             "`contains=` below is what that decision cost us and what now "
             "holds it honest — the inner versions are read out of the shipped "
             "bytes on every gate run, and the freshness workflow asks OSV "
             "about them by name every week.",
        contains=(
            Inside(
                "jspdf", "4.0.0", 'M.version="4.0.0"',
                behind_ok="B336 — jsPDF 4.2.1 returns zero advisories and this "
                          "bundle is what html2pdf.js 0.14.0 published. Ours "
                          "moves when html2pdf publishes a release built "
                          "against it, or when B421 splits the bundle.",
                note="Nine open advisories at 4.0.0 (OSV, 2026-09-17), one "
                     "CRITICAL and six HIGH; 4.2.1 returns zero. None is "
                     "reachable on Pantheon's path — see the per-id reasons "
                     "below, each of which names an API `static/js/document.js` "
                     "does not call. This is audit noise and supply-chain "
                     "hygiene, not a live vulnerability, and it is written down "
                     "rather than argued away.",
                osv_known={
                    "GHSA-wfv2-pwc8-crg5":
                        "CRITICAL, HTML injection in the new-window output "
                        "paths. Reached only by `output()` with a "
                        "window/dataurlnewwindow option. exportAsPdf calls "
                        "`.save()`; the bundle's Worker never calls `output` "
                        "with a window target.",
                    "GHSA-9vjf-qc39-jprp":
                        "PDF object injection via unsanitised input in "
                        "`addJS`. Pantheon never calls `addJS`, and html2pdf's "
                        "Worker does not either.",
                    "GHSA-cjw8-79x6-5cj4":
                        "Shared-state race in the addJS plugin. Same API, same "
                        "answer, and the race is between Node processes.",
                    "GHSA-7x6v-j9x4-qf24":
                        "Object injection via FreeText annotation colour. "
                        "Needs `createAnnotation`; nothing here annotates.",
                    "GHSA-p5xg-68wr-hm3m":
                        "Injection in the AcroForm module. Needs the AcroForm "
                        "classes; Pantheon generates no form fields.",
                    "GHSA-pqxr-3g65-p328":
                        "Injection in AcroFormChoiceField. Same module, same "
                        "answer.",
                    "GHSA-vm32-vv63-w422":
                        "Stored XMP metadata injection. Needs "
                        "`addMetadata`/XMP; exportAsPdf sets none.",
                    "GHSA-95fx-jjr5-f39c":
                        "DoS via unvalidated BMP dimensions. The image path is "
                        "html2canvas's own PNG canvas, not a user-supplied "
                        "BMP.",
                    "GHSA-67pg-wm7f-q7fj":
                        "DoS via a malicious font/file load. The Node-only "
                        "`loadFile` LFI half is structurally unreachable in a "
                        "browser; no font is loaded from user input here.",
                },
            ),
            Inside(
                "dompurify", "3.3.1", "@license DOMPurify 3.3.1",
                where="licenses/html2pdf.bundle.min.js.LICENSE.txt",
                behind_ok="B336 — DOMPurify 3.4.15 returns zero advisories. "
                          "Same answer as jsPDF: it moves when html2pdf "
                          "publishes, or when B421 splits the bundle.",
                note="Eighteen open advisories at 3.3.1 (OSV, 2026-09-17); "
                     "3.4.15 returns zero. **DOMPurify is not invoked at all on "
                     "Pantheon's path.** html2pdf calls `DOMPurify.sanitize` in "
                     "exactly one place — `createElement`, the string branch of "
                     "`Worker.from()` — and `exportAsPdf` passes a DOM element, "
                     "which `tests/test_vendored_libraries_still_work.py` pins "
                     "by measurement rather than by reading the call site. The "
                     "bundle's other consumer is canvg, which that path does "
                     "not reach either.",
                osv_known={gid: (
                    "Not reachable: DOMPurify is never invoked on Pantheon's "
                    "PDF path. html2pdf sanitises only in `createElement`, the "
                    "string branch of `from()`, and exportAsPdf passes an "
                    "element (pinned by test, B334). B336.")
                    for gid in (
                        "GHSA-39q2-94rc-95cp", "GHSA-55q2-fjhq-7xh7",
                        "GHSA-76mc-f452-cxcm", "GHSA-c2j3-45gr-mqc4",
                        "GHSA-cj63-jhhr-wcxv", "GHSA-cjmm-f4jc-qw8r",
                        "GHSA-cmwh-pvxp-8882", "GHSA-crv5-9vww-q3g8",
                        "GHSA-gvmj-g25r-r7wr", "GHSA-h7mw-gpvr-xq4m",
                        "GHSA-h8r8-wccr-v5f2", "GHSA-hpcv-96wg-7vj8",
                        "GHSA-r47g-fvhr-h676", "GHSA-rp9w-3fw7-7cwq",
                        "GHSA-v2wj-7wpq-c8vv", "GHSA-v9jr-rg53-9pgp",
                        "GHSA-vxr8-fq34-vvx9", "GHSA-x4vx-rjvf-j5p4",
                    )},
            ),
            Inside(
                "html2canvas", "1.4.1", "html2canvas 1.4.1",
                where="licenses/html2pdf.bundle.min.js.LICENSE.txt",
                note="1.4.1 is html2canvas's current release and returns zero "
                     "advisories, so this one is here to be checked rather "
                     "than excused.",
            ),
        ),
    ),
    # B338, 2026-09-17. The `node-qrcode` record is GONE, because the bytes
    # are: `static/lib/qrcode.min.js` was loaded by nothing and is no longer
    # shipped. This file fingerprints what we serve, so a record for a file
    # that is not there would be a hash over nothing — rule 1 says NO BYTES and
    # rule 3 says GHOST, and both are right. The *attribution* stays, with
    # empty patterns, in check-licences.py's INVENTORY; that is a different
    # question with a different answer (`Law 1`), and CREDITS.md says which
    # release was the last to carry the file.
    Vendored(
        "KaTeX", "katex", "0.18.7", "2026-09-17",
        "https://registry.npmjs.org/katex/-/katex-0.18.7.tgz",
        "v0.18.7",
        files={
            "static/lib/katex/katex.min.js":
                "10a91b479cd927446ceb60409fb0d72b5d0d05eaf446c9e52fafd64058c84540",
            "static/lib/katex/katex.min.css":
                "50d9c78e03da144a021001b7de679133355179bcb06fd11e9e309223056a03dd",
        },
        note="Bumped from 0.16.22 on 2026-09-17 (B335), across two 0.x minors "
             "that are both semver-breaking. Zero advisories either side. "
             "0.17.0's break is the internal `__defineFunction` extension API "
             "and 0.18.0's is the CSS class prefix (`base` -> `katex-base`, "
             "`strut` -> `katex-strut`); Pantheon calls `renderToString` and "
             "its own stylesheet names only `.katex` and `.katex-display`, "
             "both unchanged. All twenty font faces are byte-identical between "
             "0.16.22 and 0.18.7, so the fonts moved version and not bytes. "
             "0.18.2 also carries an unnumbered prototype-pollution fix in "
             "settings, recorded because no scanner will ever flag it (B332's "
             "shape).",
    ),
    Vendored(
        "KaTeX fonts", "katex", "0.18.7", "2026-09-17",
        "https://registry.npmjs.org/katex/-/katex-0.18.7.tgz",
        "v0.18.7",
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
             "swap and a KaTeX bump looked the same from the credits file. "
             "Every one of the twenty is byte-identical at 0.16.22 and 0.18.7 "
             "— checked face by face on 2026-09-17 — so the 0.18.7 bump moved "
             "this record's version and not one byte under it, and the hashes "
             "below are unchanged on purpose.",
    ),
    Vendored(
        "Mermaid", "mermaid", "11.17.2", "2026-09-17",
        "https://registry.npmjs.org/mermaid/-/mermaid-11.17.2.tgz",
        "v11.17.2",
        files={"static/lib/mermaid.min.js":
               "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8"},
        note="Bumped from 11.16.1 on 2026-09-17 (B335) — same major, three "
             "releases, zero advisories either side. Carries 11.17.0's fix for "
             "a `RangeError: Invalid array length` crash on certain edges and "
             "11.17.2's restoration of the `edgePaths` class the flowchart, "
             "block and journey stylesheets hang off. The three Microsoft "
             "vscode-* packages inside it are declared by B46's INVENTORY "
             "entry, unchanged at the same versions; `lodash-es` and "
             "`cytoscape` were found in here on 2026-09-17 by B339's new "
             "reading of esbuild's own notice block, and had no notice "
             "anywhere before that.",
        behind_ok="B423 — 12.0.0 is current and changes how existing diagrams "
             "look: ELK replaces dagre as the default layout for seven diagram "
             "types (measured — `getConfig().layout` comes back `elk` after "
             "Pantheon's own `initialize()` call), the browser floor rises to "
             "Safari 17.4 / ES2024, and mermaid.min.js grows 3.57 MB -> 5.58 "
             "MB. Needs a browser to verify, which this wave could not do.",
    ),
    Vendored(
        "Pyodide", "pyodide", "0.27.5", "2026-09-16",
        "https://registry.npmjs.org/pyodide/-/pyodide-0.27.5.tgz",
        "0.27.5",
        manifest="static/lib/pyodide/MANIFEST.json",
        dist_tag="stable-0.27",
        note="Hashes are not repeated here — scripts/fetch-pyodide.py owns "
             "them and writes MANIFEST.json. **npm `dist-tags.latest` is "
             "314.0.7 and that is not this line.** Pyodide moved to a "
             "CPython-aligned version scheme; the 0.27 line is still "
             "maintained and its own tag is `stable-0.27` (0.27.8, "
             "2026-09-16). That is the comparison this record asks for, which "
             "is the human judgement B335 wanted: comparing 0.27.5 against "
             "314.0.7 reports a supported runtime as permanently behind, and a "
             "light that is always on is a light nobody reads.",
        behind_ok="B425 — 0.27.8's own change is `python` CLI compatibility with "
             "Node 26, a path Pantheon never runs (codeRunner.js loads the "
             "browser runtime). Reaching it crosses 0.27.7's documented "
             "breaking change — `enableRunUntilComplete` defaults on, which "
             "turns a no-op into a crash where stack switching is off — and "
             "that needs a browser matrix this wave could not run, for 13 MB "
             "of new binaries.",
    ),
    Vendored(
        "Swagger UI", "swagger-ui-dist", "5.33.0", "2026-09-17",
        "https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.33.0.tgz",
        "v5.33.0",
        manifest="static/lib/swagger-ui/MANIFEST.json",
        note="Bumped from 5.32.15 on 2026-09-17 (B335) through "
             "scripts/fetch-swagger-ui.py, which verified the registry's own "
             "dist.integrity before opening the tarball and re-pinned both "
             "hashes. Zero advisories either side. The extracted sidecar "
             "licenses/swagger-ui-bundle.js.LICENSE.txt is BYTE-IDENTICAL at "
             "5.32.15 and 5.33.0, which is how the bump was shown to add no "
             "undeclared package — and reading that sidecar at all is B339, "
             "which found React and ten others shipping in here with no notice "
             "anywhere. Hashes are not repeated here; the fetch script owns "
             "them and writes MANIFEST.json.",
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

    # 6 — `B336`. A bundle's inner versions are read out of the shipped bytes.
    # `CREDITS.md` and the freshness workflow both say html2pdf.js 0.14.0
    # carries jsPDF 4.0.0 and DOMPurify 3.3.1; until this rule existed, nothing
    # checked that against the file, so a replacement bundle carrying a
    # different jsPDF would have gone in under a record that still said 4.0.0
    # and under twenty-seven advisory excuses that no longer applied to it.
    for name in sorted(records):
        rec = records[name]
        if not rec.contains:
            continue
        entry = by_name.get(name)
        owned = sorted(p for p in files if entry and entry.matches(p))
        for inner in rec.contains:
            where = inner.where or (owned[0] if len(owned) == 1 else None)
            if where is None:
                problems.append(
                    f"NO WITNESS  {name}/{inner.package}: this record covers "
                    f"{len(owned)} files, so `where=` has to say which one "
                    f"carries the version string"
                )
                continue
            path = ROOT / where
            if not path.is_file():
                problems.append(
                    f"NO WITNESS  {name}/{inner.package}: {where} is named as "
                    f"the witness file and is not on disk"
                )
                continue
            blob = path.read_bytes().decode("utf-8", "replace")
            if inner.witness not in blob:
                problems.append(
                    f"INNER       {name}: {inner.package} is recorded as "
                    f"{inner.version}\n"
                    f"            and {where} does not contain "
                    f"{inner.witness!r}.\n"
                    f"            The bundle was replaced with one carrying a "
                    f"different release. Re-measure the\n"
                    f"            inner versions and re-check every "
                    f"`osv_known` reason against the new ones — an\n"
                    f"            excuse written for one version is not an "
                    f"excuse for another (B336)."
                )

    # 7 — `B339`. A self-built artifact's provenance lives in two files: the
    # command is here, the inputs are in `.pantheon/vendored-builds/`. Neither
    # is any use alone, so neither is allowed to exist without the other.
    builds = lic.build_records()
    for name in sorted(records):
        rec = records[name]
        if not rec.build:
            continue
        entry = by_name.get(name)
        owned = sorted(p for p in files if entry and entry.matches(p))
        for path in owned:
            record = builds.get(path)
            if record is None:
                problems.append(
                    f"NO INPUTS   {path}\n"
                    f"            {name} records a build command and no record "
                    f"under .pantheon/vendored-builds/\n"
                    f"            names this file. `check-licences.py` rule 8 "
                    f"cannot state its contents, which is\n"
                    f"            how `dijkstrajs` hid inside `qrcode.min.js` "
                    f"(B337, B339)."
                )
            elif record.get("command") != rec.build:
                problems.append(
                    f"BUILD SPLIT {path}\n"
                    f"            this record's command and "
                    f".pantheon/vendored-builds/{record.get('_record')} "
                    f"disagree.\n"
                    f"            One of the two was edited alone."
                )
    for path, record in sorted(builds.items()):
        owner = None
        for name, rec in records.items():
            entry = by_name.get(name)
            if entry and entry.matches(path):
                owner = rec
                break
        if owner is None or not owner.build:
            problems.append(
                f"ORPHAN BUILD .pantheon/vendored-builds/"
                f"{record.get('_record')} records {path}, and no VENDORED "
                f"record says we build it"
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
        for inner in rec.contains:
            where = inner.where or (owned[0] if len(owned) == 1 else "?")
            print(f"    contains {inner.package}@{inner.version}"
                  f"  ({inner.witness!r} in {where})")
    print("-" * 110)
    print(f"{len(VENDORED)} libraries · {len(files)} files · {total:,} bytes")


def as_json() -> None:
    print(json.dumps([
        {"entry": r.entry, "package": r.package, "registry": r.registry,
         "version": r.version, "checked": r.checked, "source": r.source,
         "built": bool(r.build), "behind_ok": r.behind_ok,
         "dist_tag": r.dist_tag,
         "osv_known": r.osv_known,
         # `B336`. The packages inside the bundle, at the versions its bytes
         # carry. The freshness workflow asks OSV about these by name, which is
         # the difference between "a roadmap row says twenty-seven advisories"
         # and a machine counting them every week.
         "contains": [
             {"package": i.package, "version": i.version,
              "behind_ok": i.behind_ok, "osv_known": i.osv_known}
             for i in r.contains
         ]}
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
