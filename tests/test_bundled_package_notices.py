# SPDX-License-Identifier: AGPL-3.0-or-later
"""P0-21b — fifteen packages ship inside one file and four had paperwork.

`static/lib/html2pdf.bundle.min.js` is 906 KB of webpack output. Its
`LICENSE.txt` sidecar is what webpack could *extract* — the licence comments
that happened to survive minification — and that came to four: html2pdf.js
itself plus `es6-promise`, `html2canvas` and `jspdf`. The other eleven had no
notice anywhere in this repository for as long as the file has shipped, and MIT
requires the notice to travel with redistributed copies. `dompurify` was worse
than a missing file: Cure53 offers it under Apache-2.0 **or** MPL-2.0, and a
dual offer is a choice somebody has to make and record.

**The list is read out of the shipped bytes.** Webpack left 1,736
`node_modules/<package>/` paths in the blob, so what is inside it is a fact
about the file rather than a claim in a comment — which matters, because the
row this closes was written after an earlier count said five, from grepping
`/*!` markers only. If the bundle is ever replaced, these recompute.

`B45` is the other thing that fell out of re-deriving: the shipped bundle was not
upstream's bytes. One string differed, it came in at the fork baseline, and
nothing recorded it. `B334` closed it by replacing the file — see the bottom of
this module, which now records the refreshed bundle rather than the deviation.

`B334`, 2026-09-16: the bundle is html2pdf.js **0.14.0**, crossing jsPDF 2 -> 4.
Still fifteen packages and not the same fifteen, which is exactly why this list
is written down rather than counted: `fast-png`, `iobuffer`, `pako` and
`@babel/runtime` arrived and `@babel/runtime-corejs3`, `core-js-pure`,
`es6-promise` and `regenerator-runtime` left, and a test that only asserted
`len(found) == 15` would have passed through all eight changes without a word.
"""
import hashlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "static" / "lib" / "html2pdf.bundle.min.js"
CREDITS = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
BLOB = BUNDLE.read_bytes().decode("utf-8", "replace")
SIDECAR = (ROOT / "licenses" / "html2pdf.bundle.min.js.LICENSE.txt").read_text(
    encoding="utf-8", errors="replace")

_MODULE_PATH = re.compile(r'node_modules/((?:@[^/"\\]+/)?[^/"\\]+)/')


def bundled():
    return {m.group(1) for m in _MODULE_PATH.finditer(BLOB)}


# What the derivation found on 2026-09-07. Written down so the test can say
# *which* package appeared or vanished rather than only that a number moved —
# a count alone tells you nothing about what to go and license.
EXPECTED = {
    "@babel/runtime", "canvg", "core-js", "dompurify", "fast-png", "fflate",
    "html2canvas", "iobuffer", "jspdf", "pako", "performance-now", "raf",
    "rgbcolor", "stackblur-canvas", "svg-pathdata",
}

# What 0.10.2 shipped, kept so the diff above is readable and so that a
# roll-back to the old bundle fails loudly rather than quietly re-introducing
# three packages whose notices this file no longer claims are inside it.
EXPECTED_0_10_2 = {
    "@babel/runtime-corejs3", "canvg", "core-js", "core-js-pure", "dompurify",
    "es6-promise", "fflate", "html2canvas", "jspdf", "performance-now", "raf",
    "regenerator-runtime", "rgbcolor", "stackblur-canvas", "svg-pathdata",
}

# package -> the licence text that has to travel with it.
TEXTS = {
    "@babel/runtime": "babel-runtime-MIT-LICENSE.txt",
    "@babel/runtime-corejs3": "babel-runtime-corejs3-MIT-LICENSE.txt",
    "canvg": "canvg-MIT-LICENSE.txt",
    "core-js": "core-js-MIT-LICENSE.txt",
    "core-js-pure": "core-js-pure-MIT-LICENSE.txt",
    "dompurify": "DOMPurify-Apache-2.0-or-MPL-2.0.txt",
    "es6-promise": "es6-promise-MIT-LICENSE.txt",
    "fast-png": "fast-png-MIT-LICENSE.txt",
    "fflate": "fflate-MIT-LICENSE.txt",
    "html2canvas": "html2canvas-MIT-LICENSE.txt",
    "iobuffer": "iobuffer-MIT-LICENSE.txt",
    "jspdf": "jsPDF-MIT-LICENSE.txt",
    "pako": "pako-MIT-LICENSE.txt",
    "performance-now": "performance-now-MIT-LICENSE.txt",
    "raf": "raf-MIT-LICENSE.txt",
    "regenerator-runtime": "regenerator-runtime-MIT-LICENSE.txt",
    "rgbcolor": "rgbcolor-MIT-LICENSE.txt",
    "stackblur-canvas": "stackblur-canvas-MIT-LICENSE.txt",
    "svg-pathdata": "svg-pathdata-MIT-LICENSE.txt",
}


def test_the_package_list_is_still_readable_from_the_bundle():
    """Guards the derivation, not the paperwork. Every assertion below is
    vacuous against a bundle whose module paths were minified away, and a
    silently empty set is exactly how a licence check goes green over nothing."""
    found = bundled()
    assert len(found) == 15, sorted(found)
    assert found == EXPECTED, {
        "appeared": sorted(found - EXPECTED),
        "vanished": sorted(EXPECTED - found),
    }


@pytest.mark.parametrize("pkg", sorted(EXPECTED_0_10_2 - EXPECTED))
def test_a_package_that_left_the_bundle_keeps_its_licence_text(pkg):
    """`Law 1` applied to paperwork. `@babel/runtime-corejs3`, `core-js-pure`,
    `es6-promise` and `regenerator-runtime` are not in 0.14.0 — and they ship
    in every tag of this
    repository up to 0.10.2, which anyone can still check out. Deleting the
    notice for bytes somebody can still obtain rots attribution backwards, so
    the texts stay and the CREDITS.md rows say which version they were last in.
    """
    assert (ROOT / "licenses" / TEXTS[pkg]).is_file()
    lines = _credit_lines(TEXTS[pkg])
    assert lines, f"{pkg} lost its credits row as well as its place in the bundle"
    assert any("0.10.2" in ln for ln in lines), (
        f"{pkg}'s credits row does not say which version of the bundle it was "
        f"last inside: {lines}"
    )


@pytest.mark.parametrize("pkg", sorted(EXPECTED))
def test_every_bundled_package_has_a_licence_text(pkg):
    path = ROOT / "licenses" / TEXTS[pkg]
    assert path.is_file(), f"{pkg} ships inside the bundle with no licence text"
    text = path.read_text(encoding="utf-8")
    assert re.search(r"(?i)copyright", text), f"{TEXTS[pkg]} names no copyright holder"
    assert len(text) > 400, f"{TEXTS[pkg]} is too short to be a licence"


def _credit_lines(licence_file):
    """The CREDITS.md lines that link a given licence text."""
    return [ln for ln in CREDITS.splitlines() if f"licenses/{licence_file}" in ln]


@pytest.mark.parametrize("pkg", sorted(EXPECTED))
def test_every_bundled_package_is_credited_and_its_text_linked(pkg):
    """The package has to be named *on the row that links its licence*, not
    merely somewhere in the file. A name that only appears in a paragraph
    explaining the history satisfies a whole-file `in` check while the table —
    the part anyone actually reads to find a licence — has lost it."""
    lines = _credit_lines(TEXTS[pkg])
    assert lines, (
        f"{TEXTS[pkg]} is on disk and CREDITS.md links to no such file — a "
        "licence nobody can find from the credits file is not attribution"
    )
    names = {pkg, pkg.replace("jspdf", "jsPDF"), pkg.replace("dompurify", "DOMPurify")}
    if pkg == "@babel/runtime":
        # `@babel/runtime-corejs3` contains `@babel/runtime`, so a bare `in`
        # would be satisfied by the wrong row — the one for the package that
        # LEFT the bundle. The row for this one has to name it exactly.
        lines = [ln for ln in lines if "@babel/runtime-corejs3" not in ln]
        assert lines, "the @babel/runtime row is only the corejs3 row"
    assert any(n in ln for ln in lines for n in names), (
        f"{pkg} is not named on the credits row that links {TEXTS[pkg]}: {lines}"
    )


@pytest.mark.parametrize("pkg", sorted(EXPECTED - {"dompurify"}))
def test_the_mit_texts_carry_the_permission_sentence(pkg):
    """A file with a copyright line and no grant is not a licence. This is what
    catches a README or a stub copied in by mistake."""
    text = (ROOT / "licenses" / TEXTS[pkg]).read_text(encoding="utf-8")
    assert "Permission is hereby granted, free of charge" in text, TEXTS[pkg]


def test_dompurify_ships_both_offered_texts_and_records_which_was_taken():
    """Cure53 offered two licences. Shipping a trimmed copy of the one we took
    would misrepresent the offer; shipping both without saying which applies
    would leave the choice unmade. Both halves are the deliverable."""
    text = (ROOT / "licenses" / TEXTS["dompurify"]).read_text(encoding="utf-8")
    assert "Apache License" in text and "Version 2.0" in text
    assert "Mozilla Public License Version 2.0" in text, (
        "the MPL half was trimmed out — that edits somebody else's licence file"
    )
    assert "D-2026-09-07-01" in CREDITS, "CREDITS does not point at the decision"
    decisions = (ROOT / ".pantheon" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "D-2026-09-07-01" in decisions
    assert "Apache-2.0" in decisions.split("D-2026-09-07-01", 1)[1][:2000]


# --- B45, closed by B334 ---------------------------------------------------

# Until 2026-09-16 the vendored bundle differed from upstream html2pdf.js
# 0.10.2 in exactly one string, inherited at the fork baseline `fff72ec`.
# Substituting it back made the two files byte-identical after CRLF
# normalisation, which is how "exactly one difference" was known.
FORK_DEVIATION = '"sv-SV":"Swedish (SE)"'
UPSTREAM_HAS = '"sv-SV":"Swedish (Sweden)"'

# The published 0.14.0 artifact, from the npm tarball the registry's own
# `dist.integrity` vouched for. Recorded here as well as in
# `.pantheon/check-vendored-versions.py` for a reason: that checker asks "are
# these the bytes we recorded", and this asks "are those bytes upstream's" —
# the second question is what `B45` was, and it is not the same question.
UPSTREAM_0_14_0_SHA256 = (
    "9563c45f032179c73454293a649929e60fc24c05a326e8ab2811cfa8f25c3607"
)


def test_the_bundle_is_upstreams_bytes_again_and_the_deviation_is_recorded():
    """`B45`, closed by `B334`. The deviation was pinned by a test precisely so
    that replacing this file would be a decision rather than an accident — and
    that is what happened. The 0.14.0 refresh reverts it.

    Recording the change rather than deleting the old assertion is the point:
    a reader who finds `Swedish (SE)` in a CREDITS.md paragraph and
    `Swedish (Sweden)` in the file needs this test to tell them which is now
    true and why both are mentioned.
    """
    assert FORK_DEVIATION not in BLOB, (
        "the fork's `Swedish (SE)` edit is back. That means the 0.10.2 bundle "
        "was restored; re-derive the package list and the CREDITS.md rows "
        "before letting it pass"
    )
    assert BLOB.count(UPSTREAM_HAS) == 1
    assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == UPSTREAM_0_14_0_SHA256, (
        "the bundle is neither upstream 0.14.0 nor the 0.10.2 fork copy"
    )
    assert "B45" in CREDITS
    assert "B334" in CREDITS
    assert "Swedish (SE)" in CREDITS and "Swedish (Sweden)" in CREDITS, (
        "CREDITS.md no longer records what the fork's edit was and what "
        "replaced it"
    )


def test_the_bundle_carries_the_versions_credits_claims():
    """The versions in CREDITS.md's table for the packages inside this bundle
    are read out of the shipped bytes, not carried from a document. Four of
    them are still legible after minification, so four of them are checked.
    """
    for marker, credited in (
        ('M.version="4.0.0"', "jsPDF](https://github.com/parallax/jsPDF) v4.0.0"),
        ("html2canvas 1.4.1", "html2canvas) v1.4.1"),
        ("DOMPurify 3.3.1", None),
        ("html2pdf.js v0.14.0", "html2pdf.js) v0.14.0"),
    ):
        haystack = BLOB + SIDECAR
        assert marker in haystack, f"{marker!r} is not in the bundle or its sidecar"
        if credited:
            assert credited in CREDITS, credited


# --- B46 -------------------------------------------------------------------

MERMAID = ROOT / "static" / "lib" / "mermaid.min.js"
# pnpm writes the version into the module path, so these are read out of the
# shipped bytes rather than looked up.
VSCODE = {
    "vscode-jsonrpc": "8.2.0",
    "vscode-languageserver-protocol": "3.17.5",
    "vscode-languageserver-types": "3.17.5",
}
_PNPM = re.compile(r'node_modules/\.pnpm/([^/"@]+)@([\d][^/"_]*)(?:_[^/"]*)?/node_modules/')


def test_mermaid_is_a_bundle_and_its_contents_are_credited():
    """B46. `mermaid.min.js` was in the inventory as one MIT library. It is a
    bundle, and it ships three Microsoft packages that had no notice anywhere.
    Nothing found it while the list of bundles was a list — deriving that list
    from the tree is what did."""
    blob = MERMAID.read_bytes().decode("utf-8", "replace")
    found = {m.group(1): m.group(2) for m in _PNPM.finditer(blob)}
    assert found, "no pnpm module paths in mermaid.min.js — the derivation broke"
    lines = _credit_lines("vscode-languageserver-MIT-LICENSE.txt")
    assert lines, "no credits row links the vscode licence text"
    for pkg, version in VSCODE.items():
        assert found.get(pkg) == version, (pkg, found.get(pkg), version)
        assert any(pkg in ln for ln in lines), (
            f"{pkg} ships inside mermaid.min.js and is not named on the row "
            f"that links its licence: {lines}"
        )
        assert any(version in ln for ln in lines), (
            f"{pkg}'s version is in the shipped module path and not in credits"
        )
    body = (ROOT / "licenses" / "vscode-languageserver-MIT-LICENSE.txt").read_text(
        encoding="utf-8")
    assert "Microsoft Corporation" in body
    assert "Permission is hereby granted, free of charge" in body
    assert "B46" in CREDITS


def test_the_bundle_list_is_derived_and_not_written_down():
    """The gap mutation testing found: rule 7 read a hardcoded tuple of bundles,
    and emptying that tuple disabled the whole rule with every check still
    green. The tree decides now, so there is nothing to empty."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_licences", ROOT / ".pantheon" / "check-licences.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not hasattr(mod, "BUNDLES"), (
        "a hardcoded bundle list came back — it is the thing that can be "
        "emptied without anything noticing"
    )
    found = mod.discover_bundles(mod.tracked())
    assert set(found) == {
        "static/lib/html2pdf.bundle.min.js",
        "static/lib/mermaid.min.js",
    }, sorted(found)


# ── B339: how this repository knows what is inside a bundle ────────────────
#
# Rule 7 had exactly one way of looking inside a file — `node_modules/` paths —
# and no opinion at all about a file it could not look inside. So a bundler that
# does not leave module paths made a bundle indistinguishable from an ordinary
# one-library file, and `dijkstrajs` shipped inside `qrcode.min.js` undeclared
# from before the fork until `B337` rebuilt the file to find out.
#
# Rule 8 is the fix: every vendored script says HOW its contents are known, and
# the answer is checked against the bytes. The tests below are what keep it able
# to fail. They run against the real tree, because the claims are about this
# tree — the mutation half lives in `tests/test_licence_alignment.py`, whose
# fixture now keeps the real script bytes for exactly this reason.

def _licences():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_check_licences_r8", ROOT / ".pantheon" / "check-licences.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_vendored_script_says_how_its_contents_are_known():
    """No default. A vendored script whose entry answers nothing fails, which
    is what stops the next esbuild, rollup or Vite artifact arriving the way
    `qrcode.min.js` did."""
    mod = _licences()
    scripts = [f for f in mod.tracked()
               if pathlib.Path(f).suffix.lower() in mod._SCRIPT_SUFFIXES]
    assert scripts, "no vendored scripts found — the derivation broke"
    for rel in scripts:
        owners = [e for e in mod.INVENTORY if e.matches(rel)]
        assert owners, f"{rel} is declared by no entry (rule 1 owns this)"
        assert owners[0].contents in mod.CONTENTS_ANSWERS, (
            f"{rel} ships under {owners[0].name!r}, which does not say how its "
            f"contents are known"
        )


def test_the_esbuild_notice_block_is_read_and_names_real_packages():
    """`B339`'s direct answer to "esbuild strips module paths".

    It strips them and then appends its own `Bundled license information:`
    block naming every module it lifted a legal comment from. That block is a
    record the build produced, and rule 7 could not read it — which is how
    `cytoscape` and `lodash-es` sat inside `mermaid.min.js` with no notice
    anywhere in this repository until 2026-09-17.
    """
    mod = _licences()
    blob = MERMAID.read_bytes().decode("utf-8", "replace")
    found = mod.esbuild_packages(blob)
    assert found >= {"lodash-es", "cytoscape", "dompurify"}, sorted(found)
    declared = {pkg for e in mod.INVENTORY for pkg in e.bundled}
    assert found <= declared, sorted(found - declared)


def test_the_swagger_sidecar_is_read_and_every_notice_is_claimed():
    """`P0-21b` again, in the one bundle nobody had looked at.

    `swagger-ui-bundle.js` carries no module paths at all — rule 7 derived zero
    packages from 1.5 MB — so it was not a bundle as far as anything here was
    concerned. It points at its own extracted sidecar from inside its bytes,
    and following that pointer found React, `immutable`, `classnames`,
    `deep-extend`, `fast-json-patch`, `repeat-string`, `safe-buffer`, `buffer`
    and `ieee754` shipping with no notice anywhere.
    """
    mod = _licences()
    bundle = ROOT / "static" / "lib" / "swagger-ui" / "swagger-ui-bundle.js"
    blob = bundle.read_bytes().decode("utf-8", "replace")
    assert not mod.bundled_packages(bundle), (
        "swagger-ui-bundle.js now carries module paths — rule 7 can read it, "
        "and this entry should say `derived`"
    )
    name = mod.sidecar_name(blob)
    assert name == "swagger-ui-bundle.js.LICENSE.txt", name
    blocks = mod.notice_blocks(
        (ROOT / "licenses" / name).read_text(encoding="utf-8", errors="replace"))
    assert len(blocks) >= 12, len(blocks)
    for notice in blocks:
        assert mod._claimed_by(notice, mod.INVENTORY), notice[:160]


@pytest.mark.parametrize("pkg,text", [
    ("React", "react-MIT-LICENSE.txt"),
    ("Immutable.js", "immutable-MIT-LICENSE.txt"),
    ("classnames", "classnames-MIT-LICENSE.txt"),
    ("deep-extend", "deep-extend-MIT-LICENSE.txt"),
    ("fast-json-patch", "fast-json-patch-MIT-LICENSE.txt"),
    ("repeat-string", "repeat-string-MIT-LICENSE.txt"),
    ("safe-buffer", "safe-buffer-MIT-LICENSE.txt"),
    ("buffer", "buffer-MIT-LICENSE.txt"),
    ("ieee754", "ieee754-BSD-3-Clause.txt"),
    ("Lodash", "lodash-MIT-LICENSE.txt"),
    ("Cytoscape", "cytoscape-MIT-LICENSE.txt"),
    ("string.fromcodepoint", "string.fromcodepoint-MIT-LICENSE.txt"),
])
def test_the_packages_rule_8_found_have_a_text_and_a_credits_row(pkg, text):
    """**Fails on the tree as it stood** (`Law 9`): none of these twelve had a
    licence text or a `CREDITS.md` row before 2026-09-17, and React — four
    packages of it — ships inside `/docs` in a repository about to go public."""
    body = ROOT / "licenses" / text
    assert body.is_file(), f"licenses/{text} is missing"
    assert f"licenses/{text}" in CREDITS, (
        f"no CREDITS.md row links licenses/{text}")
    lines = _credit_lines(text)
    assert lines, text
    assert any(pkg.split()[0] in ln for ln in lines), (pkg, lines)


def test_a_single_package_claim_is_checked_against_the_files_own_notices():
    """The half that makes `single` mean something.

    `docx.umd.min.js` is upstream's rollup UMD build and leaves no module
    paths, so a `single` claim would otherwise be unfalsifiable. It carries
    three legal comments that are not docx's — `ieee754`, `buffer` and
    `string.fromcodepoint` — and rule 8 requires each to be claimed by an
    entry. That is what turns "this is just one library" from an assertion into
    something the file can contradict.
    """
    mod = _licences()
    docx = ROOT / "static" / "lib" / "docx.umd.min.js"
    blocks = mod.notice_blocks(docx.read_bytes().decode("utf-8", "replace"))
    assert len(blocks) >= 3, blocks
    for notice in blocks:
        claimers = mod._claimed_by(notice, mod.INVENTORY)
        assert claimers, notice[:160]


# Rule 8's five answers, each broken in a throwaway copy of the tree. A rule
# that cannot fail is the same as no rule — the lesson
# `tests/test_licence_alignment.py` was written for, applied to the rule next
# door. The fixture keeps the real script bytes, because every claim rule 8
# makes is about bytes.

@pytest.fixture
def repo(tmp_path):
    import shutil
    import subprocess

    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in ("CREDITS.md", "NOTICE", "README.md"):
        if (ROOT / rel).is_file():
            shutil.copy2(ROOT / rel, dst / rel)
    for rel in ("licenses", ".pantheon", "static/lib", "static/fonts",
                "static/icons"):
        src = ROOT / rel
        if not src.is_dir():
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst / rel,
                        ignore=shutil.ignore_patterns("*.woff2", "*.wasm",
                                                      "*.zip"))
        for f in src.rglob("*"):
            if f.is_file() and f.suffix in (".woff2", ".wasm", ".zip"):
                out = dst / f.relative_to(ROOT)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"")
    (dst / "library").mkdir(exist_ok=True)
    (dst / "library" / "README.md").write_text("stand-in\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    return dst


def check(repo):
    import subprocess
    import sys
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return subprocess.run(
        [sys.executable, str(repo / ".pantheon" / "check-licences.py"),
         "--quiet"], cwd=repo, capture_output=True, text=True)


def test_the_rule_8_fixture_starts_clean(repo):
    """Every mutation below is measured against this passing."""
    r = check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_rule_8_fails_when_a_bundles_contents_stop_being_readable(repo):
    """The alarm, driven. This is `B339` in one test: a bundle whose module
    paths went away is a bundle nothing can see inside, and before rule 8 that
    was silence rather than a failure.

    The mutation replaces the html2pdf bundle — declared `derived` — with bytes
    carrying no module paths, which is exactly what happened when `qrcode.min.js`
    was built with esbuild.
    """
    target = repo / "static" / "lib" / "html2pdf.bundle.min.js"
    target.write_text(
        "/*! For license information please see nothing.txt */\n"
        "window.html2pdf=function(){};\n", encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "NOT DERIVED" in r.stdout, r.stdout
    assert "html2pdf.bundle.min.js" in r.stdout, r.stdout


def test_rule_8_fails_when_a_vendored_script_answers_nothing(repo):
    """No default. A new vendored script arrives the way every one of them has
    arrived — a copy dropped into `static/lib/` to remove a network call — and
    rule 1 makes somebody write its licence down. Rule 8 makes them write down
    how anybody is to know what is *inside* it."""
    (repo / "static" / "lib" / "newthing.min.js").write_text(
        "// a library somebody vendored\n", encoding="utf-8")
    path = repo / ".pantheon" / "check-licences.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(
        "INVENTORY = [",
        'INVENTORY = [\n    Entry("newthing", ["static/lib/newthing.min.js"], '
        '"MIT",\n          None, None),', 1), encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "NO CONTENTS" in r.stdout, r.stdout
    assert "newthing.min.js" in r.stdout, r.stdout


def test_rule_8_fails_when_an_esbuild_bundle_loses_its_notice_block(repo):
    """`mermaid.min.js` answers `esbuild`, and that answer is only worth
    anything while the block is there. A mermaid built with the block stripped
    is a 3.5 MB bundle nothing can enumerate — `qrcode.min.js` exactly."""
    target = repo / "static" / "lib" / "mermaid.min.js"
    blob = target.read_text(encoding="utf-8", errors="replace")
    target.write_text(blob.replace("Bundled license information:",
                                   "Bundled licence info:"), encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "NO ESBUILD" in r.stdout, r.stdout
    assert "mermaid.min.js" in r.stdout, r.stdout


def test_rule_8_fails_on_a_sidecar_notice_no_entry_claims(repo):
    """`P0-21b`'s shape, now caught by machine. A bundle bump that pulls in a
    new dependency ships a new notice in the sidecar, and before this nothing
    read the sidecar at all — which is how React got here."""
    sidecar = repo / "licenses" / "swagger-ui-bundle.js.LICENSE.txt"
    sidecar.write_text(
        sidecar.read_text(encoding="utf-8", errors="replace")
        + "\n/*!\n * left-pad <https://example.invalid/left-pad>\n"
          " * Copyright (c) 2016 Nobody At All\n * Licensed under the MIT "
          "License.\n */\n", encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "UNATTRIBUTED" in r.stdout, r.stdout
    assert "left-pad" in r.stdout, r.stdout


def test_rule_8_fails_on_a_build_record_naming_an_undeclared_package(repo):
    """The `build` answer, and the reason it exists. `B337` found `dijkstrajs`
    inside `qrcode.min.js` by rebuilding the file; had that file carried a build
    record, rule 7 would have folded its packages in and demanded a notice for
    every one. This is that path, driven."""
    import json
    (repo / ".pantheon" / "vendored-builds").mkdir(parents=True, exist_ok=True)
    (repo / ".pantheon" / "vendored-builds" / "qrcode.json").write_text(
        json.dumps({
            "file": "static/lib/highlight.min.js",
            "entry": "highlight.js",
            "bundler": "esbuild",
            "command": "esbuild whatever --bundle",
            "packages": ["highlight.js", "dijkstrajs", "not-declared-anywhere"],
        }), encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "UNBUNDLED" in r.stdout, r.stdout
    assert "not-declared-anywhere" in r.stdout, r.stdout


def test_rule_8_fails_when_a_single_package_file_turns_out_to_be_a_bundle(repo):
    """The `single` answer's other half.

    `docx.umd.min.js` is upstream's rollup UMD build and leaves no module paths,
    which is what makes `single` the right answer for it today. Upstream's 9.x
    Vite build leaves `//#region node_modules/<pkg>/` markers for forty-four
    packages (`B424`), so a refresh that took that build would turn this file
    into a declared-as-single bundle overnight. That is the case this fails on,
    and it is not hypothetical — it is the reason the docx bump was filed rather
    than taken.
    """
    target = repo / "static" / "lib" / "docx.umd.min.js"
    blob = target.read_text(encoding="utf-8", errors="replace")
    target.write_text(
        blob + "\n//#region node_modules/jszip/dist/jszip.min.js\n"
               "//#region node_modules/xml-js/lib/index.js\n"
               "//#region node_modules/sax/lib/sax.js\n", encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "NOT SINGLE" in r.stdout, r.stdout
    assert "docx.umd.min.js" in r.stdout, r.stdout


def test_rule_8_fails_when_a_single_package_file_carries_a_foreign_notice(repo):
    """The half that makes `single` falsifiable at all.

    Derivation finding nothing is not evidence a file is one library — esbuild
    output finds nothing either, which is the whole of `B339`. What a bundled
    package cannot hide is its **legal comment**: every minifier keeps `/*!` and
    `@license` blocks, which is how `ieee754`, `buffer` and
    `string.fromcodepoint` turned out to be inside `docx.umd.min.js`. So a file
    declared `single` that carries a notice no entry claims fails.
    """
    target = repo / "static" / "lib" / "highlight.min.js"
    blob = target.read_text(encoding="utf-8", errors="replace")
    target.write_text(
        "/*!\n * left-pad <https://example.invalid/left-pad>\n"
        " * Copyright (c) 2016 Nobody At All\n * Licensed under the MIT "
        "License.\n */\n" + blob, encoding="utf-8")
    r = check(repo)
    assert r.returncode == 1, r.stdout
    assert "UNATTRIBUTED" in r.stdout, r.stdout
    assert "highlight.min.js" in r.stdout, r.stdout
