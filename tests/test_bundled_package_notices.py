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

`B45` is the other thing that fell out of re-deriving: the shipped bundle is not
upstream's bytes. One string differs, it came in at the fork baseline, and
nothing recorded it.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "static" / "lib" / "html2pdf.bundle.min.js"
CREDITS = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
BLOB = BUNDLE.read_bytes().decode("utf-8", "replace")

_MODULE_PATH = re.compile(r'node_modules/((?:@[^/"\\]+/)?[^/"\\]+)/')


def bundled():
    return {m.group(1) for m in _MODULE_PATH.finditer(BLOB)}


# What the derivation found on 2026-09-07. Written down so the test can say
# *which* package appeared or vanished rather than only that a number moved —
# a count alone tells you nothing about what to go and license.
EXPECTED = {
    "@babel/runtime-corejs3", "canvg", "core-js", "core-js-pure", "dompurify",
    "es6-promise", "fflate", "html2canvas", "jspdf", "performance-now", "raf",
    "regenerator-runtime", "rgbcolor", "stackblur-canvas", "svg-pathdata",
}

# package -> the licence text that has to travel with it.
TEXTS = {
    "@babel/runtime-corejs3": "babel-runtime-corejs3-MIT-LICENSE.txt",
    "canvg": "canvg-MIT-LICENSE.txt",
    "core-js": "core-js-MIT-LICENSE.txt",
    "core-js-pure": "core-js-pure-MIT-LICENSE.txt",
    "dompurify": "DOMPurify-Apache-2.0-or-MPL-2.0.txt",
    "es6-promise": "es6-promise-MIT-LICENSE.txt",
    "fflate": "fflate-MIT-LICENSE.txt",
    "html2canvas": "html2canvas-MIT-LICENSE.txt",
    "jspdf": "jsPDF-MIT-LICENSE.txt",
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


# --- B45 -------------------------------------------------------------------

# The one place the shipped bundle differs from upstream html2pdf.js 0.10.2.
# Substituting it back makes the two files byte-identical after CRLF
# normalisation, which is how "exactly one difference" is known.
LOCAL_DEVIATION = '"sv-SV":"Swedish (SE)"'
UPSTREAM_HAD = '"sv-SV":"Swedish (Sweden)"'


def test_the_known_deviation_from_upstream_is_still_there_and_still_recorded():
    """B45. The vendored bundle is not upstream's bytes, and it arrived that
    way at the fork baseline — so this is not a change to undo, it is one to
    know about. Pinned here because a refresh from npm reverts it silently, and
    an undocumented edit to a vendored file is how provenance rots.
    """
    assert BLOB.count(LOCAL_DEVIATION) == 1, (
        "the bundle was replaced. That may be entirely right — but upstream "
        f"0.10.2 has {UPSTREAM_HAD} here, so decide deliberately, re-derive the "
        "package list, and update CREDITS.md rather than letting the swap pass"
    )
    assert UPSTREAM_HAD not in BLOB
    assert LOCAL_DEVIATION.strip('"') in CREDITS or "Swedish (SE)" in CREDITS, (
        "the deviation is in the file and not in the credits file"
    )
    assert "B45" in CREDITS


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
