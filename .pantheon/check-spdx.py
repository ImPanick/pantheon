#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every file of program text says what licence it is under.

`P0-18`, decided `AGPL-3.0-or-later` in `DECISIONS.md` D-2026-08-26-06 —
matching upstream, because narrowing below the parent creates a compatibility
puzzle for anyone combining the two in exchange for control over a future
revision there is no reason to fear.

Before this, the qualifier lived in **one line of the README** and nowhere else.
Not in `LICENSE`, not in `NOTICE`, and in zero source files. A reader with a
single file in front of them — which is how code is actually read, in a search
result, a diff, a paste — had nothing to go on.

**The identifier only. No per-file copyright line.** REUSE wants both, and the
second one cannot be written truthfully here: most of this tree is upstream
Odysseus's code that Pantheon modified, there was no upstream copyright notice
in the repo to preserve (`P0-15`), and stamping `SPDX-FileCopyrightText: 2026
Panick` on a file nobody here wrote is the same class of statement as the font
that claimed to be GohuFont (`P0-23`). The licence identifier is true of every
file in scope. `NOTICE` stays the authority on copyright and on the §5(a)
modification statement naming both upstreams.

**Scope is program text we ship, and it is derived, not listed.** Tracked files
with a source suffix, minus the vendored roots `check-licences.py` already owns
— `static/lib/`, `static/fonts/`, `static/icons/`, `library/` — and minus
`licenses/`, which is other people's licence text. Markdown, JSON and YAML are
out: they carry no program text, and an HTML comment at the top of every one of
325 documents buys nothing a `LICENSE` file does not.

**Two rules, and the second is the one that matters.** Every in-scope file
carries the identifier; and no file under a vendored root carries *this*
identifier, because stamping AGPL on somebody else's MIT build is a licence
claim about work that is not ours to relicense. That is the direction this
repository has actually gone wrong in before: `P0-16`'s first attempt put a
`# Licence: licenses/DeepResearch-Apache-2.0.txt` line on eight AGPL files and
it read as declaring them Apache-2.0.

    python3 .pantheon/check-spdx.py          # report
    python3 .pantheon/check-spdx.py --fix    # insert the missing headers
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

LICENCE = "AGPL-3.0-or-later"
TAG = "SPDX-License-Identifier"
LINE = f"{TAG}: {LICENCE}"

# How far down a file the header counts as a header. A scanner reads the top of
# a file, not all of it, and so does a person. This bound is also what stops a
# file that merely *discusses* the tag from being treated as declaring it —
# which this checker did to itself on its first run: its own `TAG` constant and
# docstring were enough to make it skip its own source.
HEAD_LINES = 10

# suffix -> how a comment is spelled in it.
COMMENT = {
    ".py": "# {}",
    ".sh": "# {}",
    ".zsh": "# {}",
    ".ps1": "# {}",
    ".js": "// {}",
    ".mjs": "// {}",
    ".ts": "// {}",
    ".swift": "// {}",
    ".css": "/* {} */",
    ".html": "<!-- {} -->",
}

# Vendored roots. `check-licences.py` owns these and their licences live in
# `licenses/`; the two checkers must agree on the boundary or one of them is
# making a claim about the other's files.
VENDORED = ("static/lib/", "static/fonts/", "static/icons/", "library/")
SKIP = VENDORED + ("licenses/",)

# A first line the header must go *after*, not before: the kernel reads `#!`
# only at byte zero, PEP 263 reads an encoding declaration only in the first two
# lines, and a comment above `<!DOCTYPE html>` puts old browsers into quirks
# mode. Getting any of these wrong turns a licence header into an outage.
SHEBANG = re.compile(r"^#!")
CODING = re.compile(r"^#.*coding[:=]")
DOCTYPE = re.compile(r"^\s*<!doctype", re.I)


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return out.splitlines()


def in_scope(rel):
    return pathlib.Path(rel).suffix in COMMENT and not rel.startswith(SKIP)


def _insert_at(lines, suffix):
    """The index the header goes at, after anything that must stay first."""
    i = 0
    if lines and SHEBANG.match(lines[0]):
        i = 1
        if suffix == ".py" and len(lines) > 1 and CODING.match(lines[1]):
            i = 2
    elif suffix == ".py" and lines and CODING.match(lines[0]):
        i = 1
    elif suffix == ".html" and lines and DOCTYPE.match(lines[0]):
        i = 1
    return i


def add_header(text, suffix):
    lines = text.split("\n")
    i = _insert_at(lines, suffix)
    lines.insert(i, COMMENT[suffix].format(LINE))
    return "\n".join(lines)


def main(argv):
    fix = "--fix" in argv
    missing, changed = [], 0
    for rel in _tracked():
        if not in_scope(rel):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if LINE in "\n".join(text.split("\n")[:HEAD_LINES]):
            continue
        if fix:
            path.write_text(add_header(text, path.suffix), encoding="utf-8")
            changed += 1
        else:
            missing.append(rel)

    # The other direction. A vendored file that carries *our* identifier is a
    # licence claim about work this project has no standing to relicense.
    mislabelled = []
    for rel in _tracked():
        if not rel.startswith(VENDORED):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if LICENCE in text:
            mislabelled.append(rel)

    if mislabelled:
        print(f"Vendored files carrying `{LICENCE}` — this project cannot "
              "relicense them:\n")
        for rel in mislabelled:
            print(f"  {rel}")
        return 1
    if missing:
        print(f"{len(missing)} file(s) of program text carry no `{TAG}`:\n")
        for rel in missing[:40]:
            print(f"  {rel}")
        if len(missing) > 40:
            print(f"  ... and {len(missing) - 40} more")
        print("\n  python3 .pantheon/check-spdx.py --fix")
        return 1

    total = sum(1 for rel in _tracked() if in_scope(rel))
    if fix:
        print(f"spdx: added {changed} header(s); {total} files in scope")
    else:
        print(f"spdx OK — {total} files of program text declare "
              f"{LICENCE}, and no vendored file does")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
