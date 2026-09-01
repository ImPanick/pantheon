#!/usr/bin/env python3
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

Six rules, each one a way attribution has actually rotted somewhere:

  1. No undeclared file under a vendored root.        (OpenMoji, 2026-09-01)
  2. Every declared licence text exists in licenses/.
  3. Every declared licence text is linked from CREDITS.md -- a file nobody
     links is a file nobody reads.
  4. No orphan text in licenses/ that no entry claims.
  5. Every licenses/ link in CREDITS.md, NOTICE and README.md resolves.
  6. Every copyleft entry is named in the "Licence scope" section. That section
     summarises the obligations of the default install; a summary that omits one
     is worse than no summary, because it is read instead of the detail.

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


class Entry:
    """One third-party thing we ship, and the paperwork it needs.

    `text` is the filename in licenses/, or None where the licence obligation is
    met without a distributed text (trademark use, for one). `copyleft` marks
    an entry that rule 6 requires the scope section to name.
    """

    def __init__(self, name, patterns, licence, text, credits, copyleft=False):
        self.name = name
        self.patterns = patterns
        self.licence = licence
        self.text = text
        self.credits = credits
        self.copyleft = copyleft

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
    Entry("jsPDF", [], "MIT", "jsPDF-MIT-LICENSE.txt", "jsPDF"),
    Entry("html2canvas", [], "MIT", "html2canvas-MIT-LICENSE.txt", "html2canvas"),
    Entry("node-qrcode", ["static/lib/qrcode.min.js"], "MIT",
          "node-qrcode-MIT-LICENSE.txt", "node-qrcode"),
    Entry("KaTeX", ["static/lib/katex/katex.min.js", "static/lib/katex/katex.min.css"],
          "MIT", "KaTeX-MIT-LICENSE.txt", "KaTeX"),
    Entry("KaTeX fonts", ["static/lib/katex/fonts/*.woff2"], "OFL-1.1",
          "KaTeX-fonts-OFL.txt", "KaTeX-fonts-OFL.txt"),
    Entry("Mermaid", ["static/lib/mermaid.min.js"], "MIT",
          "Mermaid-MIT-LICENSE.txt", "Mermaid"),
    Entry("Pyodide", ["static/lib/pyodide/*"], "MPL-2.0",
          "Pyodide-MPL-2.0.txt", "static/lib/pyodide", copyleft=True),
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
