#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every third-party file we ship is attributed, and the summary still matches.

OpenMoji was the reason this exists. Its artwork was served through `/api/emoji/`
since before the fork -- CC BY-SA 4.0, credited in no file in the repository --
and it survived a fork, a licence audit and several weeks of work because nothing
ever compared what is *on disk* against what CREDITS.md *says*. A person found it
by accident while removing a CDN fetch for an unrelated reason.

That is not a mistake you fix once. The next vendored asset will arrive the same
way: as a byte-for-byte copy dropped into `static/` to remove a network call, in
a commit whose message is about the network call. So the inventory below is an
ALLOWLIST, and an unlisted file is a failure. Adding a vendored asset means
adding its licence here, which means having read it.

    python3 .pantheon/check-licences.py          # report
    python3 .pantheon/check-licences.py --quiet  # findings only

Eight rules, each one a way attribution has actually rotted somewhere:

  1. No undeclared file under a vendored root.        (OpenMoji, 2026-09-01)
  2. Every declared licence text exists in licenses/.
  3. Every declared licence text is linked from CREDITS.md -- a file nobody
     links is a file nobody reads.
  4. No orphan text in licenses/ that no entry claims.
  5. Every licenses/ link in CREDITS.md, NOTICE and README.md resolves.
  6. Every copyleft entry is named in the "Licence scope" section. That section
     summarises the obligations of the default install; a summary that omits one
     is worse than no summary, because it is read instead of the detail.
  7. Every package inside a shipped bundle is declared -- and both the list of
     bundles and their contents are read out of the tree, not out of a comment.
     (P0-21b, 2026-09-07: the html2pdf sidecar named four of fifteen and the
     other eleven had no notice anywhere. Deriving the bundle list rather than
     writing one down is what then found B46, three Microsoft `vscode-*`
     packages inside mermaid.min.js that nobody knew were there.)
  8. Every vendored script says HOW its contents are known, and the answer is
     checked. (B339, 2026-09-17: rule 7 had exactly one way of seeing inside a
     bundle -- `node_modules/` paths -- so a bundler that does not leave them
     made a bundle indistinguishable from a single-package file, and
     `dijkstrajs` shipped inside `qrcode.min.js` undeclared for as long as that
     file existed. There is no default: a vendored script whose entry does not
     say which answer applies fails, which is what stops the next esbuild,
     rollup or Vite artifact from arriving the same way.)

CONTENTS: how a vendored script's contents are known (rule 8). Four answers,
each one checkable against the bytes rather than taken on trust:

  "derived"  module paths survive in the shipped bytes -- webpack's
             `node_modules/<pkg>/`, pnpm's store layout. The claim FAILS if
             derivation finds fewer than `_BUNDLE_THRESHOLD` packages, which is
             the alarm B339 is about: a bundler that stopped leaving paths made
             a bundle look like a plain file and nothing noticed.
  "esbuild"  esbuild strips module paths but emits a `Bundled license
             information:` block naming each module it took a legal comment
             from. That block IS a record the build produced, so it is read the
             same way -- derived, not declared.
  "sidecar"  the bundler wrote the notices to a separate file and left
             `For license information please see <name>` in the bytes. The
             pointer is derived from the file; every notice block in the
             sidecar then has to be claimed by an Entry.
  "single"   upstream's own artifact for one package. Derivation must find
             nothing, AND every legal comment in the file must be claimed by
             some Entry -- a "this is just one library" claim is false the
             moment the file carries somebody else's notice.
  "build"    we built it, so the packages come from a build record under
             `.pantheon/vendored-builds/`. An absent, empty or unparseable
             record fails; a package in it with no Entry fails. This is the
             answer `qrcode.min.js` would have had to give.

Scope (Law 5, so the pass means something): files tracked by git under
static/lib/, static/fonts/, static/icons/ and library/. Python and JavaScript
package dependencies are NOT in scope -- they are declared in requirements*.txt
and package.json, resolved by a package manager, and their licences travel with
the wheels. This checks what THIS repository copies into itself.
"""
import fnmatch
import json
import pathlib
import re
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Roots scanned for undeclared files. A vendored asset that lands anywhere else
# is out of scope here and stays that way until someone adds its root.
ROOTS = ("static/lib/", "static/fonts/", "static/icons/", "library/")

# `node_modules/<package>/`, with the scoped form. Anchored on the separator so
# a bare mention of a package name in a string is not mistaken for a module
# path — the point is what the bundler recorded, not what the code talks about.
_MODULE_PATH = re.compile(r'node_modules/((?:@[^/"\\]+/)?[^/"\\]+)/')

# pnpm's store layout is `node_modules/.pnpm/<pkg>@<ver>/node_modules/<pkg>/`,
# so the naive match reports a package called `.pnpm`. Mermaid is built with
# pnpm and that is how a real bundle first looked like it shipped a package
# nobody could find on npm.
_NOT_A_PACKAGE = {".pnpm", ".bin", ".cache", ".store"}

# Suffixes worth reading. A `.woff2` will never carry a module path and reading
# 28 fonts as text on every CI run buys nothing.
_BUNDLE_SUFFIXES = {".js", ".mjs", ".cjs", ".css"}

# How many distinct packages make a file a bundle rather than a file that
# happens to mention `node_modules` once in a comment.
_BUNDLE_THRESHOLD = 3


# `B339`. Rule 8's vocabulary. Kept as constants rather than bare strings so a
# typo in an entry is an AttributeError at import rather than a file that
# quietly matches no branch and is never checked.
CONTENTS_DERIVED = "derived"
CONTENTS_ESBUILD = "esbuild"
CONTENTS_SIDECAR = "sidecar"
CONTENTS_SINGLE = "single"
CONTENTS_BUILD = "build"
CONTENTS_ANSWERS = frozenset({
    CONTENTS_DERIVED, CONTENTS_ESBUILD, CONTENTS_SIDECAR, CONTENTS_SINGLE,
    CONTENTS_BUILD,
})

# Scripts only. A `.woff2` carries no packages and a stylesheet does not bundle
# npm modules in the sense attribution cares about; `katex.min.css` and
# `swagger-ui.css` are covered by the entry that covers the library.
_SCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}

# Where a self-built vendored artifact records what went into it. `B337` put
# the *command* in `check-vendored-versions.py`; this is the other half, the
# inputs, and it lives in a file both checkers can read without importing each
# other (`check-vendored-versions.py` imports this module, so the dependency
# cannot go the other way).
BUILD_RECORDS = ROOT / ".pantheon" / "vendored-builds"

# A legal comment, as every minifier defines one: `/*! ... */`, or a block
# carrying `@license` or `@preserve`. Terser's `comments: "some"` keeps exactly
# these, which is why they survive minification when everything else does not.
_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# esbuild's own record of what it bundled. It strips `node_modules/` paths but
# appends
#
#     /*! Bundled license information:
#
#       lodash-es/lodash.js:
#         (** @license Lodash ... *)
#     */
#
# naming every module it lifted a legal comment from. `B339` is that this is a
# record produced by the build and rule 7 could not read it.
_ESBUILD_HEADER = "Bundled license information:"
_ESBUILD_MODULE = re.compile(
    r"^\s+((?:@[\w.-]+/)?[\w.-]+)/\S*:\s*$", re.M)

# webpack points at its extracted sidecar from inside the bundle, so which
# sidecar belongs to which file is derived rather than listed.
_SIDECAR_POINTER = re.compile(
    r"For license information please see ([\w.+-]+\.(?:txt|LICENSE\.txt))")


def legal_comments(text):
    """Every legal comment in a blob, as a minifier defines one."""
    out = []
    for block in _COMMENT.finditer(text):
        body = block.group(0)
        if len(body.strip()) <= 12:
            continue
        head = body[:400]
        if body.startswith("/*!") or "@license" in head or "@preserve" in head:
            out.append(body)
    return out


def esbuild_packages(text):
    """The packages esbuild says it bundled, read out of its own notice block."""
    found = set()
    for body in legal_comments(text):
        if _ESBUILD_HEADER not in body:
            continue
        # The block reaches here as it sits in the file. A bundle that embedded
        # it inside a string literal spells the newlines `\n`; normalising both
        # spellings costs nothing and a missed block is a missed package.
        for name in _ESBUILD_MODULE.findall(body.replace("\\n", "\n")):
            if name not in _NOT_A_PACKAGE:
                found.add(name)
    return found


def sidecar_name(text):
    """The extracted notice file this bundle points at, or None."""
    names = set(_SIDECAR_POINTER.findall(text))
    return sorted(names)[0] if len(names) == 1 else None


def notice_blocks(text):
    """The distinct notices in an extracted sidecar.

    webpack writes one block per module it kept a comment from, and most of
    them in a big bundle are its own `!*** ./node_modules/x/y.js ***!` banners
    rather than notices. Those are dropped: they carry no copyright line, and a
    rule that demanded an Entry per banner would be noise rather than a check.
    """
    out = []
    for body in legal_comments(text):
        flat = " ".join(body.split())
        stripped = flat.strip("/*! ")
        # webpack's module banner: a row of stars around a path, no notice.
        if "!*\\" in flat or "!***" in flat:
            continue
        # A bare `/*! ../internals/a-callable */` re-export marker.
        if len(stripped) < 40 and "(c)" not in flat.lower() \
                and "copyright" not in flat.lower():
            continue
        out.append(flat)
    return out


def bundled_packages(path):
    """The npm packages a bundle was built from, read out of the shipped bytes."""
    blob = path.read_bytes().decode("utf-8", "replace")
    return {m.group(1) for m in _MODULE_PATH.finditer(blob)} - _NOT_A_PACKAGE


def discover_bundles(files):
    """Which shipped files are bundles — derived, not listed.

    A hardcoded list can be emptied and nothing notices; mutation testing said
    so out loud, by deleting the list and watching every check stay green. So
    the tree decides: a vendored script carrying module paths for three or more
    packages *is* a bundle, and its contents have to be declared. That is also
    how `mermaid.min.js` turned out to ship three Microsoft `vscode-*` packages
    with no notice anywhere (`B46`) — nobody had listed it as a bundle, because
    nobody knew it was one.
    """
    out = {}
    for rel in files:
        path = ROOT / rel
        if path.suffix.lower() not in _BUNDLE_SUFFIXES:
            continue
        try:
            found = bundled_packages(path)
        except OSError:
            continue
        if len(found) >= _BUNDLE_THRESHOLD:
            out[rel] = found
    return out


def build_records():
    """What our own builds say they put into each self-built vendored file.

    `B339`. A file we built has no upstream package to point at, so its
    contents cannot come from a registry and must come from the build. The
    records live in `.pantheon/vendored-builds/*.json`:

        {"file": "static/lib/x.min.js", "entry": "...", "bundler": "esbuild",
         "command": "...", "packages": ["a", "b"]}

    Returned as {repo path: record}. A record that names no file is dropped
    here and reported by rule 8, which is the half that knows which files are
    supposed to have one.
    """
    out = {}
    if not BUILD_RECORDS.is_dir():
        return out
    for path in sorted(BUILD_RECORDS.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rel = data.get("file")
        if isinstance(rel, str) and rel:
            data["_record"] = path.name
            out[rel] = data
    return out


def _claimed_by(notice, entries):
    """The entries whose markers appear in a legal notice."""
    low = notice.lower()
    return [e for e in entries
            if any(marker.lower() in low for marker in e.notices if marker)]


def check_contents(files):
    """Rule 8. Every vendored script says how its contents are known.

    The answers are checked, not believed:

      derived   derivation has to find packages. It finding none is the alarm
                — that is a bundler that stopped leaving module paths, which is
                the whole of `B339`.
      esbuild   esbuild's own notice block has to be there and name modules.
      sidecar   the pointer has to be in the bytes, the file has to exist, and
                every notice in it has to be claimed by an Entry.
      single    derivation has to find nothing AND every legal comment in the
                file has to be claimed. A file carrying somebody else's
                copyright notice is not one library.
      build     the record has to exist, name this file and list packages.

    Returns a list of printable problems.
    """
    problems = []
    records = build_records()
    scripts = [f for f in files
               if pathlib.Path(f).suffix.lower() in _SCRIPT_SUFFIXES]
    for rel in sorted(scripts):
        owners = [e for e in INVENTORY if e.matches(rel)]
        if not owners:
            continue                      # rule 1 owns "declared by nobody"
        entry = owners[0]
        answer = entry.contents
        if answer is None:
            problems.append(
                f"NO CONTENTS {rel}\n"
                f"            Shipped under {entry.name!r}, which does not say "
                f"how its contents are known.\n"
                f"            Set contents= to one of "
                f"{', '.join(sorted(CONTENTS_ANSWERS))} — there is no default, "
                f"because\n"
                f"            a bundle nobody classified is how `dijkstrajs` "
                f"shipped with no notice (B339)."
            )
            continue
        if answer not in CONTENTS_ANSWERS:
            problems.append(
                f"BAD CONTENTS {entry.name}: contents={answer!r} is not one of "
                f"{sorted(CONTENTS_ANSWERS)}"
            )
            continue
        try:
            blob = (ROOT / rel).read_bytes().decode("utf-8", "replace")
        except OSError as exc:
            problems.append(f"UNREADABLE  {rel}: {exc}")
            continue
        derived = bundled_packages(ROOT / rel)

        if answer == CONTENTS_DERIVED:
            if len(derived) < _BUNDLE_THRESHOLD:
                problems.append(
                    f"NOT DERIVED {rel}\n"
                    f"            {entry.name!r} says its contents come from "
                    f"module paths in the bytes, and only\n"
                    f"            {len(derived)} package(s) are there. Either "
                    f"the build changed bundler — in which case\n"
                    f"            nothing can see inside this file any more — "
                    f"or this is not a bundle. B339."
                )
        elif answer == CONTENTS_ESBUILD:
            if not esbuild_packages(blob):
                problems.append(
                    f"NO ESBUILD  {rel}\n"
                    f"            {entry.name!r} says esbuild's "
                    f"`{_ESBUILD_HEADER}` block names what is inside,\n"
                    f"            and the file has no such block. Its contents "
                    f"are now unreadable. B339."
                )
        elif answer == CONTENTS_SIDECAR:
            name = sidecar_name(blob)
            if not name:
                problems.append(
                    f"NO SIDECAR  {rel}\n"
                    f"            {entry.name!r} says an extracted notice file "
                    f"records its contents, and the\n"
                    f"            bundle does not point at one. B339."
                )
                continue
            path = ROOT / "licenses" / name
            if not path.is_file():
                problems.append(
                    f"LOST SIDECAR {rel} points at licenses/{name}, which is "
                    f"not on disk"
                )
                continue
            blocks = notice_blocks(path.read_text(encoding="utf-8",
                                                  errors="replace"))
            if not blocks:
                problems.append(
                    f"EMPTY SIDECAR licenses/{name} records no notices, so "
                    f"standing on it checks nothing"
                )
            for notice in blocks:
                if not _claimed_by(notice, INVENTORY):
                    problems.append(
                        f"UNATTRIBUTED {rel}\n"
                        f"            licenses/{name} carries a notice no "
                        f"Entry claims:\n"
                        f"              {notice[:150]}\n"
                        f"            Add an Entry with its licence text and a "
                        f"`notices=` marker that matches."
                    )
        elif answer == CONTENTS_SINGLE:
            if derived:
                problems.append(
                    f"NOT SINGLE  {rel}\n"
                    f"            {entry.name!r} is declared to be one "
                    f"package's own artifact and carries module\n"
                    f"            paths for {sorted(derived)}. It is a bundle; "
                    f"say so and declare them."
                )
            for notice in notice_blocks(blob):
                if not _claimed_by(notice, INVENTORY):
                    problems.append(
                        f"UNATTRIBUTED {rel}\n"
                        f"            Declared as a single package and carries "
                        f"a notice no Entry claims:\n"
                        f"              {notice[:150]}\n"
                        f"            Somebody else's code is in this file. "
                        f"B339."
                    )
        elif answer == CONTENTS_BUILD:
            record = records.get(rel)
            if record is None:
                problems.append(
                    f"NO BUILD    {rel}\n"
                    f"            {entry.name!r} says we built it, and no "
                    f"record under\n"
                    f"            .pantheon/vendored-builds/ names this file. "
                    f"A self-built artifact that\n"
                    f"            cannot state its own contents does not ship. "
                    f"B339."
                )
                continue
            if entry.build and record.get("_record") != entry.build:
                problems.append(
                    f"BUILD SPLIT {rel}: the entry names {entry.build!r} and "
                    f"{record['_record']} claims the file"
                )
            if not record.get("packages"):
                problems.append(
                    f"EMPTY BUILD .pantheon/vendored-builds/"
                    f"{record.get('_record')} lists no packages for {rel},\n"
                    f"            so the record states nothing. B46 is what an "
                    f"emptiable list does."
                )
            if not record.get("command"):
                problems.append(
                    f"NO COMMAND  .pantheon/vendored-builds/"
                    f"{record.get('_record')} records no build command, so the "
                    f"bytes are not reproducible"
                )

    # The other direction: a record for a file nothing ships.
    tracked_set = set(files)
    for rel, record in sorted(records.items()):
        if rel not in tracked_set:
            problems.append(
                f"GHOST BUILD .pantheon/vendored-builds/"
                f"{record.get('_record')} records {rel}, which git does not "
                f"track"
            )
    return problems


class Entry:
    """One third-party thing we ship, and the paperwork it needs.

    `text` is the filename in licenses/, or None where the licence obligation is
    met without a distributed text (trademark use, for one). `copyleft` marks
    an entry that rule 6 requires the scope section to name.
    """

    def __init__(self, name, patterns, licence, text, credits, copyleft=False,
                 bundled=(), contents=None, notices=(), build=None):
        self.name = name
        self.patterns = patterns
        self.licence = licence
        self.text = text
        self.credits = credits
        self.copyleft = copyleft
        # npm package names this entry covers *inside* a bundle. Display names
        # and package names differ (`jsPDF` / `jspdf`, `DOMPurify` /
        # `dompurify`), so rule 7 needs the package name written down rather
        # than lowercased and hoped for.
        self.bundled = tuple(bundled)
        # `B339`. How rule 8 is to learn what is inside the scripts this entry
        # ships: one of CONTENTS_ANSWERS, or None for an entry that ships no
        # script (a bundled-package entry, a font, a mark). There is no default
        # answer -- a script whose entry says nothing fails rule 8.
        self.contents = contents
        # Strings that identify this project inside somebody else's legal
        # comment. The package name is usually enough (`repeat-string`,
        # `ieee754`), but a notice does not have to contain it: `deep-extend`
        # signs itself "Viacheslav Lotsmanov" and `immutable` "Lee Byron". The
        # marker is checked in both directions -- a notice nothing claims
        # fails, and rule 8 reads these out of the file rather than trusting
        # them -- so a marker that matches nothing is dead weight, not a hole.
        self.notices = tuple(notices) or tuple(bundled)
        # For CONTENTS_BUILD: the record under `.pantheon/vendored-builds/`
        # that this entry's build wrote.
        self.build = build

    def matches(self, path):
        return any(fnmatch.fnmatch(path, p) for p in self.patterns)


INVENTORY = [
    Entry("highlight.js", ["static/lib/highlight.min.js"], "BSD-3-Clause",
          "highlight.js-BSD-3-Clause.txt", "highlight.js",
          contents=CONTENTS_SINGLE, notices=("Highlight.js",)),
    Entry("SheetJS / xlsx", ["static/lib/xlsx.full.min.js"], "Apache-2.0",
          "SheetJS-Apache-2.0.txt", "SheetJS",
          contents=CONTENTS_SINGLE, notices=("SheetJS",)),
    # `B339`, 2026-09-17. `single` here is upstream's rollup UMD build, which
    # leaves no module paths — and rule 8's second half is what makes the claim
    # mean something: the file carries three legal comments that are not docx's
    # (`ieee754`, `buffer`, `string.fromcodepoint`), and each now has an Entry
    # because an unclaimed notice fails. Upstream's 9.x Vite build leaves
    # `//#region node_modules/<pkg>/` markers for **44** packages — the same
    # library, the same dependencies, a build that says so — which is the
    # measured cost recorded on `B424`.
    Entry("docx", ["static/lib/docx.umd.min.js"], "MIT",
          "docx-MIT-LICENSE.txt", "dolanmiu/docx",
          contents=CONTENTS_SINGLE, notices=("dolanmiu/docx",)),
    Entry("mammoth.js", ["static/lib/mammoth.browser.min.js"], "BSD-2-Clause",
          "mammoth.js-BSD-2-Clause.txt", "mammoth.js",
          contents=CONTENTS_SINGLE, notices=("mammoth",)),
    Entry("html2pdf.js", ["static/lib/html2pdf.bundle.min.js"], "MIT",
          "html2pdf.js-MIT-LICENSE.txt", "html2pdf.js",
          contents=CONTENTS_DERIVED, notices=("html2pdf.js",)),
    Entry("html2pdf bundle sidecar", [], "MIT (bundled deps)",
          "html2pdf.bundle.min.js.LICENSE.txt", "html2pdf.bundle.min.js.LICENSE.txt"),
    Entry("jsPDF", [], "MIT", "jsPDF-MIT-LICENSE.txt", "jsPDF", bundled=("jspdf",)),
    Entry("html2canvas", [], "MIT", "html2canvas-MIT-LICENSE.txt", "html2canvas",
          bundled=("html2canvas",)),
    Entry("es6-promise", [], "MIT", "es6-promise-MIT-LICENSE.txt", "es6-promise",
          bundled=("es6-promise",)),
    # P0-21b. `html2pdf.bundle.min.js` ships fifteen top-level packages and its
    # webpack-extracted sidecar carries a notice for four of them. These are the
    # other eleven plus DOMPurify, enumerated from upstream 0.10.2's own source
    # map (497 sources) rather than by reading the minified blob. Each has no
    # file of its own in static/lib/, so `patterns` is empty: the obligation is
    # attached to the bundle, and this is the paperwork it travels with.
    #
    # B334, 2026-09-16: the bundle moved to 0.14.0 and its contents changed.
    # Still fifteen packages, but not the same fifteen — `fast-png`, `iobuffer`,
    # `pako` and `@babel/runtime` arrived, and `@babel/runtime-corejs3`,
    # `core-js-pure`, `es6-promise` and `regenerator-runtime` left. The four
    # that left keep their entries and their licence texts: they ship in every
    # tag of this repository
    # up to 0.10.2, and deleting the paperwork for bytes somebody can still
    # check out is how attribution rots backwards.
    Entry("@babel/runtime", [], "MIT",
          "babel-runtime-MIT-LICENSE.txt", "@babel/runtime",
          bundled=("@babel/runtime",)),
    Entry("@babel/runtime-corejs3", [], "MIT",
          "babel-runtime-corejs3-MIT-LICENSE.txt", "@babel/runtime-corejs3",
          bundled=("@babel/runtime-corejs3",)),
    Entry("fast-png", [], "MIT", "fast-png-MIT-LICENSE.txt", "fast-png",
          bundled=("fast-png",)),
    Entry("iobuffer", [], "MIT", "iobuffer-MIT-LICENSE.txt", "iobuffer",
          bundled=("iobuffer",)),
    Entry("pako", [], "MIT", "pako-MIT-LICENSE.txt", "pako", bundled=("pako",)),
    Entry("canvg", [], "MIT", "canvg-MIT-LICENSE.txt", "canvg", bundled=("canvg",)),
    Entry("core-js", [], "MIT", "core-js-MIT-LICENSE.txt", "core-js",
          bundled=("core-js",)),
    Entry("core-js-pure", [], "MIT", "core-js-pure-MIT-LICENSE.txt", "core-js-pure",
          bundled=("core-js-pure",)),
    # Dual-licensed by Cure53, and the choice is ours to make as the recipient.
    # Apache-2.0 (D-2026-09-07-01): MPL-2.0 §3.2 would oblige us to make
    # DOMPurify's own Source Code Form available to anyone who receives the
    # minified bundle, which is a real obligation bought for nothing, and
    # Apache-2.0 carries a patent grant MPL's is narrower than. The upstream
    # LICENSE ships verbatim with BOTH texts, because misrepresenting what was
    # offered would be worse than stating which half we took.
    Entry("DOMPurify", [], "Apache-2.0 (dual, or MPL-2.0)",
          "DOMPurify-Apache-2.0-or-MPL-2.0.txt", "DOMPurify",
          bundled=("dompurify",), notices=("DOMPurify",)),
    Entry("fflate", [], "MIT", "fflate-MIT-LICENSE.txt", "fflate", bundled=("fflate",)),
    Entry("performance-now", [], "MIT",
          "performance-now-MIT-LICENSE.txt", "performance-now",
          bundled=("performance-now",)),
    Entry("raf", [], "MIT", "raf-MIT-LICENSE.txt", "raf", bundled=("raf",)),
    Entry("regenerator-runtime", [], "MIT",
          "regenerator-runtime-MIT-LICENSE.txt", "regenerator-runtime",
          bundled=("regenerator-runtime",)),
    Entry("rgbcolor", [], "MIT", "rgbcolor-MIT-LICENSE.txt", "rgbcolor",
          bundled=("rgbcolor",)),
    Entry("stackblur-canvas", [], "MIT",
          "stackblur-canvas-MIT-LICENSE.txt", "stackblur-canvas",
          bundled=("stackblur-canvas",)),
    Entry("svg-pathdata", [], "MIT", "svg-pathdata-MIT-LICENSE.txt", "svg-pathdata",
          bundled=("svg-pathdata",)),
    # B338, 2026-09-17: `static/lib/qrcode.min.js` is GONE. Nothing in the
    # served frontend ever loaded it — no `<script>` in `static/index.html`, no
    # module import, not precached by `static/sw.js` — and the QR code a user
    # sees during 2FA setup is rasterised server-side by the Python
    # `qrcode[pil]` package. It was 24 KB of unreferenced third-party
    # JavaScript in the served surface with a CREDITS.md row describing a use
    # that had never existed.
    #
    # The PAPERWORK STAYS, with empty patterns, for the reason `B334` records
    # three entries above: these bytes ship in every tag of this repository up
    # to 2026-09-17, and deleting the notice for bytes somebody can still check
    # out is how attribution rots backwards. `CREDITS.md` says which release
    # was the last to carry them.
    Entry("node-qrcode", [], "MIT",
          "node-qrcode-MIT-LICENSE.txt", "node-qrcode"),
    # B337. `qrcode.min.js` was esbuild output, not a published artifact —
    # node-qrcode has shipped no browser build to npm since 1.5.1 — and the
    # bundle pulled `dijkstrajs` in with it. Rule 7 could not see it: esbuild
    # rewrites module paths away, so the blob carried no `node_modules/` string
    # for the derivation to find, and the package had no notice anywhere here
    # until the file was rebuilt and its inputs read off the build. `B339` is
    # the rule that would have caught it; rule 8 has no default answer, so that
    # file could not ship today without a build record naming both packages.
    Entry("dijkstrajs", [], "MIT", "dijkstrajs-MIT-LICENSE.txt", "dijkstrajs",
          bundled=("dijkstrajs",)),
    # ── B339, 2026-09-17 ──────────────────────────────────────────────────
    # Found by rule 8 the first time anything read a bundle's own notices
    # instead of only its module paths. Every entry below ships inside a
    # vendored bundle and had NO notice anywhere in this repository before
    # today. `patterns` is empty for the same reason the html2pdf set's is: the
    # obligation is attached to the bundle, and this is the paperwork it
    # travels with.
    #
    # Three are inside `docx.umd.min.js`, whose rollup build leaves no module
    # paths but does keep their legal comments:
    Entry("ieee754", [], "BSD-3-Clause", "ieee754-BSD-3-Clause.txt", "ieee754",
          bundled=("ieee754",), notices=("ieee754",)),
    Entry("buffer", [], "MIT", "buffer-MIT-LICENSE.txt", "buffer",
          bundled=("buffer",),
          notices=("buffer module from node.js",)),
    Entry("string.fromcodepoint", [], "MIT",
          "string.fromcodepoint-MIT-LICENSE.txt", "string.fromcodepoint",
          bundled=("string.fromcodepoint",),
          notices=("fromcodepoint",)),
    # Two are inside `mermaid.min.js`, named by esbuild's own
    # `Bundled license information:` block — the record `B339` is about:
    Entry("Lodash", [], "MIT", "lodash-MIT-LICENSE.txt", "Lodash",
          bundled=("lodash-es", "lodash"), notices=("Lodash",)),
    Entry("Cytoscape", [], "MIT", "cytoscape-MIT-LICENSE.txt", "Cytoscape",
          bundled=("cytoscape",), notices=("Cytoscape",)),
    # The rest are inside `swagger-ui-bundle.js`, named by the webpack sidecar
    # the bundle points at. React shipping unattributed in a repository about
    # to go public is the one that matters most here.
    Entry("React (react, react-dom, scheduler, use-sync-external-store)", [],
          "MIT", "react-MIT-LICENSE.txt", "React",
          bundled=("react", "react-dom", "scheduler",
                   "use-sync-external-store"),
          notices=("@license React",)),
    Entry("classnames", [], "MIT", "classnames-MIT-LICENSE.txt", "classnames",
          bundled=("classnames",), notices=("classnames",)),
    Entry("deep-extend", [], "MIT", "deep-extend-MIT-LICENSE.txt",
          "deep-extend", bundled=("deep-extend",),
          notices=("Lotsmanov",)),
    Entry("fast-json-patch", [], "MIT", "fast-json-patch-MIT-LICENSE.txt",
          "fast-json-patch", bundled=("fast-json-patch",),
          notices=("JSON-Patch",)),
    Entry("repeat-string", [], "MIT", "repeat-string-MIT-LICENSE.txt",
          "repeat-string", bundled=("repeat-string",),
          notices=("repeat-string",)),
    Entry("safe-buffer", [], "MIT", "safe-buffer-MIT-LICENSE.txt",
          "safe-buffer", bundled=("safe-buffer",), notices=("safe-buffer",)),
    Entry("Immutable.js", [], "MIT", "immutable-MIT-LICENSE.txt", "Immutable.js",
          bundled=("immutable",), notices=("Lee Byron",)),
    Entry("KaTeX", ["static/lib/katex/katex.min.js", "static/lib/katex/katex.min.css"],
          "MIT", "KaTeX-MIT-LICENSE.txt", "KaTeX",
          contents=CONTENTS_SINGLE, notices=("KaTeX",)),
    Entry("KaTeX fonts", ["static/lib/katex/fonts/*.woff2"], "OFL-1.1",
          "KaTeX-fonts-OFL.txt", "KaTeX-fonts-OFL.txt"),
    # `CONTENTS_ESBUILD`, not `derived`: mermaid is built with esbuild over a
    # pnpm store, so the three `vscode-*` packages `B46` found survive as store
    # paths while everything else does not. esbuild's own
    # `Bundled license information:` block names the rest, and reading it is
    # `B339`'s fix — it is how `cytoscape` and `lodash-es` turned out to be in
    # here with no notice anywhere, on 2026-09-17, the same way `dijkstrajs`
    # was inside `qrcode.min.js`.
    Entry("Mermaid", ["static/lib/mermaid.min.js"], "MIT",
          "Mermaid-MIT-LICENSE.txt", "Mermaid",
          contents=CONTENTS_ESBUILD, notices=("Mermaid",)),
    # B46, found by rule 7 the first time it derived the bundle list instead of
    # reading one: mermaid.min.js is a bundle too, and it ships three Microsoft
    # packages nobody had noticed. All three carry the same MIT text byte for
    # byte, so one file covers them and the entry names all three.
    Entry("vscode-languageserver (jsonrpc, protocol, types)", [], "MIT",
          "vscode-languageserver-MIT-LICENSE.txt", "vscode-languageserver",
          bundled=("vscode-jsonrpc", "vscode-languageserver-protocol",
                   "vscode-languageserver-types")),
    Entry("Pyodide", ["static/lib/pyodide/*"], "MPL-2.0",
          "Pyodide-MPL-2.0.txt", "static/lib/pyodide", copyleft=True,
          contents=CONTENTS_SINGLE, notices=("Pyodide",)),
    # B212, 2026-09-16. FastAPI's `/docs` loaded these two from
    # cdn.jsdelivr.net; they are vendored by `scripts/fetch-swagger-ui.py`,
    # which pins each file's SHA-256 and checks the npm tarball's own
    # `dist.integrity` before opening it. The glob covers MANIFEST.json the
    # same way the Pyodide entry does — rule 1 fails on any undeclared file
    # under a vendored root and MANIFEST.json is a file.
    # `CONTENTS_SIDECAR`. The published dist carries no module paths at all,
    # so rule 7 derived **zero** packages from 1.5 MB of bundle and the file
    # looked like a plain script. The bundle points at its own extracted notice
    # file from inside its bytes, and rule 8 follows that pointer and requires
    # every notice in it to be claimed. That is how React, `classnames`,
    # `immutable`, `buffer` and seven more turned out to be shipping here with
    # no notice anywhere in this repository (`B339`, 2026-09-17) — the same
    # defect as `P0-21b`, in the one bundle whose sidecar nothing had read.
    Entry("Swagger UI", ["static/lib/swagger-ui/*"], "Apache-2.0",
          "SwaggerUI-Apache-2.0.txt", "static/lib/swagger-ui",
          contents=CONTENTS_SIDECAR, notices=("Swagger UI", "swagger-ui")),
    Entry("Swagger UI NOTICE", [], "Apache-2.0 (§4(d) notice)",
          "SwaggerUI-NOTICE.txt", "SwaggerUI-NOTICE.txt"),
    # Webpack's extracted notice for the MIT-licensed packages inside
    # `swagger-ui-bundle.js`, the same shape as the html2pdf sidecar. Rule 7
    # finds no `node_modules/` paths in this bundle — the published dist
    # carries no source-map comments — so the sidecar is the only record of
    # what is in there, which is exactly why it ships.
    Entry("Swagger UI bundle sidecar", [], "MIT (bundled deps)",
          "swagger-ui-bundle.js.LICENSE.txt", "swagger-ui-bundle.js.LICENSE.txt"),
    Entry("Fira Code", ["static/fonts/FiraCode-*.woff2"], "OFL-1.1",
          "FiraCode-OFL.txt", "Fira Code"),
    Entry("Inter", ["static/fonts/Inter-*.woff2"], "OFL-1.1",
          "Inter-OFL.txt", "Inter"),
    Entry("OpenDyslexic", ["static/fonts/OpenDyslexic-*.woff2"], "OFL-1.1",
          "OpenDyslexic-OFL.txt", "OpenDyslexic"),
    Entry("OpenMoji", ["library/emoji/*"], "CC-BY-SA-4.0",
          "OpenMoji-CC-BY-SA-4.0.txt", "OpenMoji", copyleft=True),
    Entry("ECC skill library", ["library/ecc/*", "library/ecc/skills/*"], "MIT",
          "ECC-MIT.txt", "ECC"),
    Entry("opencode", [], "MIT", "opencode-MIT-LICENSE.txt", "opencode"),
    Entry("llmfit", [], "MIT", "llmfit-MIT-LICENSE.txt", "llmfit"),
    Entry("Tongyi DeepResearch", [], "Apache-2.0",
          "DeepResearch-Apache-2.0.txt", "DeepResearch"),
    # Vendor marks. Used nominatively, to label the backend a row talks about --
    # the reason no licence text is distributed, and the reason the entry still
    # exists: an unattributed logo is how OpenMoji started.
    Entry("Ollama mark", ["static/icons/ollama-mark*.png"], "Trademark — nominative use",
          None, "static/icons/ollama-mark"),
    Entry("SGLang mark", ["static/icons/sglang-*.png"], "Trademark — nominative use",
          None, "static/icons/sglang-mark"),
    # Pantheon's own. Listed so rule 1 can stay an allowlist without exceptions.
    Entry("Pantheon app icons", ["static/icons/icon-*.png"], "AGPL-3.0-or-later (this project)",
          None, None),
    Entry("Pantheon library README", ["library/README.md"],
          "AGPL-3.0-or-later (this project)", None, None),
]

SCOPE_HEADING = "## Licence scope — what applies to what"
LINK_RE = re.compile(r"licenses/([A-Za-z0-9._+-]+\.txt)")


def tracked():
    out = subprocess.run(
        ["git", "ls-files", "-z", *ROOTS],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def scope_section(credits):
    start = credits.find(SCOPE_HEADING)
    if start < 0:
        return None
    end = credits.find("\n## ", start + 1)
    return credits[start:end if end > 0 else len(credits)]


def main() -> int:
    quiet = "--quiet" in sys.argv
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    problems = []

    # 1 — no undeclared file under a vendored root.
    files = tracked()
    for path in files:
        if not any(e.matches(path) for e in INVENTORY):
            problems.append(
                f"UNDECLARED  {path}\n"
                f"            Shipped, attributed nowhere. Add an Entry to "
                f"INVENTORY with its licence,\n"
                f"            or move it out of {', '.join(ROOTS)}."
            )

    # 2, 3 — the text exists, and CREDITS.md links it.
    claimed = set()
    for e in INVENTORY:
        if e.text:
            claimed.add(e.text)
            if not (ROOT / "licenses" / e.text).is_file():
                problems.append(f"MISSING     licenses/{e.text}  ({e.name}, {e.licence})")
            elif f"licenses/{e.text}" not in credits:
                problems.append(
                    f"UNLINKED    licenses/{e.text}  ({e.name})\n"
                    f"            Present on disk, linked from no line of CREDITS.md."
                )
        if e.credits and e.credits not in credits:
            problems.append(f"UNCREDITED  {e.name}  — CREDITS.md never says {e.credits!r}")

    # 4 — no orphan text.
    for f in sorted((ROOT / "licenses").glob("*.txt")):
        if f.name not in claimed:
            problems.append(
                f"ORPHAN      licenses/{f.name}\n"
                f"            No INVENTORY entry claims it. Either it is dead "
                f"paperwork, or the\n            thing it covers is shipping "
                f"undeclared."
            )

    # 5 — every link resolves.
    for doc in ("CREDITS.md", "NOTICE", "README.md"):
        p = ROOT / doc
        if not p.is_file():
            continue
        for name in set(LINK_RE.findall(p.read_text(encoding="utf-8"))):
            if not (ROOT / "licenses" / name).is_file():
                problems.append(f"BROKEN LINK {doc} → licenses/{name}")

    # 6 — the scope summary names every copyleft obligation.
    scope = scope_section(credits)
    if scope is None:
        problems.append(f"NO SCOPE    CREDITS.md has no {SCOPE_HEADING!r} section")
    else:
        for e in INVENTORY:
            if e.copyleft and e.name not in scope:
                problems.append(
                    f"UNSUMMARISED {e.name} ({e.licence}) is copyleft and ships by "
                    f"default,\n            but the Licence scope section never "
                    f"names it. That section is what\n            a reader reaches "
                    f"for instead of the detail; leaving it out is worse\n"
                    f"            than having no summary at all."
                )

    # 7 — a bundle's own contents, re-derived from the bundle. P0-21b: the
    # html2pdf sidecar names four of the fifteen packages inside it, and the
    # other eleven had no notice anywhere for as long as the file has shipped,
    # because nothing could see past the minification. It can: webpack left
    # 1,736 `node_modules/<package>/` paths in the blob, so the list is
    # readable from the shipped bytes rather than carried in a comment. If the
    # bundle is ever replaced, this recomputes and the new contents have to be
    # declared before CI is green again.
    # No "and there must be at least one bundle" guard here. This checker is
    # also run against a stripped fixture repo (`tests/test_licence_alignment`)
    # where every `.min.js` is an empty stand-in, so a claim about *this* tree
    # would fail there and mean nothing. The claim lives where it is true:
    # `tests/test_bundled_package_notices.py` asserts, against the real tree,
    # that discovery returns exactly the two bundles it should.
    bundles = discover_bundles(files)
    declared = {pkg for e in INVENTORY for pkg in e.bundled}

    # `B339`. esbuild strips the module paths `discover_bundles` reads, and
    # emits its own `Bundled license information:` block instead. That block is
    # a record the build produced, so the packages in it go through the same
    # check — which is the difference between deriving contents and having one
    # bundler's habit be the only thing anybody can see.
    for rel in files:
        if pathlib.Path(rel).suffix.lower() not in _SCRIPT_SUFFIXES:
            continue
        try:
            blob = (ROOT / rel).read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        found = esbuild_packages(blob)
        if found:
            bundles.setdefault(rel, set()).update(found)

    # `B339`. And the packages we put into a file ourselves, from the record
    # our own build wrote. `check-vendored-versions.py` holds the command;
    # this holds the inputs.
    for rel, record in sorted(build_records().items()):
        bundles.setdefault(rel, set()).update(record.get("packages") or ())

    for bundle, found in sorted(bundles.items()):
        for pkg in sorted(found - declared):
            problems.append(
                f"UNBUNDLED   {pkg}  (inside {bundle})\n"
                f"            Shipped inside that bundle, declared by no Entry. "
                f"Add one with\n"
                f"            bundled=({pkg!r},) and its licence text."
            )

    # 8 — every vendored script says how its contents are known. `B339`: rule 7
    # had one way of looking inside a bundle and no opinion at all about a file
    # it could not look inside, so a bundler that leaves no module paths turned
    # a bundle into a plain file and `dijkstrajs` shipped undeclared for as
    # long as `qrcode.min.js` existed. There is no default answer here: a
    # vendored script whose entry does not say which of CONTENTS_ANSWERS
    # applies fails, and each answer is then checked against the bytes.
    problems.extend(check_contents(files))

    if not quiet:
        copyleft = [e.name for e in INVENTORY if e.copyleft]
        print(
            f"vendored files {len(files)}  ·  entries {len(INVENTORY)}  ·  "
            f"licence texts {len(claimed)}  ·  copyleft {len(copyleft)}"
        )
        if copyleft:
            print(f"    copyleft, shipped by default: {', '.join(copyleft)}")

    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} licence problem(s).")
        return 1
    if not quiet:
        print("OK — every shipped third-party file is attributed.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
