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

Seven rules, each one a way attribution has actually rotted somewhere:

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

Scope (Law 5, so the pass means something): files tracked by git under
static/lib/, static/fonts/, static/icons/ and library/. Python and JavaScript
package dependencies are NOT in scope -- they are declared in requirements*.txt
and package.json, resolved by a package manager, and their licences travel with
the wheels. This checks what THIS repository copies into itself.
"""
import fnmatch
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


class Entry:
    """One third-party thing we ship, and the paperwork it needs.

    `text` is the filename in licenses/, or None where the licence obligation is
    met without a distributed text (trademark use, for one). `copyleft` marks
    an entry that rule 6 requires the scope section to name.
    """

    def __init__(self, name, patterns, licence, text, credits, copyleft=False,
                 bundled=()):
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

    def matches(self, path):
        return any(fnmatch.fnmatch(path, p) for p in self.patterns)


INVENTORY = [
    Entry("highlight.js", ["static/lib/highlight.min.js"], "BSD-3-Clause",
          "highlight.js-BSD-3-Clause.txt", "highlight.js"),
    Entry("SheetJS / xlsx", ["static/lib/xlsx.full.min.js"], "Apache-2.0",
          "SheetJS-Apache-2.0.txt", "SheetJS"),
    Entry("docx", ["static/lib/docx.umd.min.js"], "MIT",
          "docx-MIT-LICENSE.txt", "dolanmiu/docx"),
    Entry("mammoth.js", ["static/lib/mammoth.browser.min.js"], "BSD-2-Clause",
          "mammoth.js-BSD-2-Clause.txt", "mammoth.js"),
    Entry("html2pdf.js", ["static/lib/html2pdf.bundle.min.js"], "MIT",
          "html2pdf.js-MIT-LICENSE.txt", "html2pdf.js"),
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
    Entry("@babel/runtime-corejs3", [], "MIT",
          "babel-runtime-corejs3-MIT-LICENSE.txt", "@babel/runtime-corejs3",
          bundled=("@babel/runtime-corejs3",)),
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
          bundled=("dompurify",)),
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
    Entry("node-qrcode", ["static/lib/qrcode.min.js"], "MIT",
          "node-qrcode-MIT-LICENSE.txt", "node-qrcode"),
    Entry("KaTeX", ["static/lib/katex/katex.min.js", "static/lib/katex/katex.min.css"],
          "MIT", "KaTeX-MIT-LICENSE.txt", "KaTeX"),
    Entry("KaTeX fonts", ["static/lib/katex/fonts/*.woff2"], "OFL-1.1",
          "KaTeX-fonts-OFL.txt", "KaTeX-fonts-OFL.txt"),
    Entry("Mermaid", ["static/lib/mermaid.min.js"], "MIT",
          "Mermaid-MIT-LICENSE.txt", "Mermaid"),
    # B46, found by rule 7 the first time it derived the bundle list instead of
    # reading one: mermaid.min.js is a bundle too, and it ships three Microsoft
    # packages nobody had noticed. All three carry the same MIT text byte for
    # byte, so one file covers them and the entry names all three.
    Entry("vscode-languageserver (jsonrpc, protocol, types)", [], "MIT",
          "vscode-languageserver-MIT-LICENSE.txt", "vscode-languageserver",
          bundled=("vscode-jsonrpc", "vscode-languageserver-protocol",
                   "vscode-languageserver-types")),
    Entry("Pyodide", ["static/lib/pyodide/*"], "MPL-2.0",
          "Pyodide-MPL-2.0.txt", "static/lib/pyodide", copyleft=True),
    # B212, 2026-09-16. FastAPI's `/docs` loaded these two from
    # cdn.jsdelivr.net; they are vendored by `scripts/fetch-swagger-ui.py`,
    # which pins each file's SHA-256 and checks the npm tarball's own
    # `dist.integrity` before opening it. The glob covers MANIFEST.json the
    # same way the Pyodide entry does — rule 1 fails on any undeclared file
    # under a vendored root and MANIFEST.json is a file.
    Entry("Swagger UI", ["static/lib/swagger-ui/*"], "Apache-2.0",
          "SwaggerUI-Apache-2.0.txt", "static/lib/swagger-ui"),
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
    for bundle, found in sorted(bundles.items()):
        for pkg in sorted(found - declared):
            problems.append(
                f"UNBUNDLED   {pkg}  (inside {bundle})\n"
                f"            Shipped inside that bundle, declared by no Entry. "
                f"Add one with\n"
                f"            bundled=({pkg!r},) and its licence text."
            )

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
