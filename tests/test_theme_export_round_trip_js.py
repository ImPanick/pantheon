# SPDX-License-Identifier: AGPL-3.0-or-later
"""The theme editor's export/import must round-trip everything it stores.

This file exists because of a real export, handed over by the owner, of a theme
called `customtheme` — kept verbatim at `tests/fixtures/pantheon_customtheme.json`
and used here as a fixture rather than a hand-written sample, so the format under
test is the format the product actually emits.

The defect it caught: `save()` and `saveCustomTheme()` persist **seven** options,
and the exporter wrote **four**. `bgEffectIntensity`, `bgEffectSize` and
`frosted` were dropped. Nothing failed loudly — the file it produced imported
cleanly and simply came back as a different theme, with the frosted-glass look
off and a tuned background pattern back at its defaults.

The invariant these tests hold is that the four lists agree: what
`saveCustomTheme` stores, what `save` stores, what export writes, and what
import reads.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
THEME_JS = ROOT / "static" / "js" / "theme.js"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pantheon_customtheme.json"

# The options a theme can carry. Order is the declaration order in
# `saveCustomTheme`, which is the list the other three are checked against.
STORED_OPTIONS = [
    "font",
    "density",
    "bgPattern",
    "bgEffectColor",
    "bgEffectIntensity",
    "bgEffectSize",
    "frosted",
]


@pytest.fixture(scope="module")
def src():
    return THEME_JS.read_text(encoding="utf-8")


def _block(src, start_marker, end_marker):
    i = src.index(start_marker)
    return src[i:src.index(end_marker, i)]


def _options_named_in(block, prefix):
    """Which STORED_OPTIONS a block reads or writes off `prefix`."""
    return [k for k in STORED_OPTIONS if re.search(rf"\b{re.escape(prefix)}\.{k}\b", block)]


# ── the fixture is the format the product emits ────────────────────────────

def test_the_owners_export_is_the_shape_the_importer_accepts():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["name"], "an export names its theme"
    for key in ("bg", "fg", "panel", "border", "red"):
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", data["colors"][key]), key
    # The importer requires exactly these five and rejects anything else as a
    # missing field, so an export that dropped one would be unimportable.
    assert set(data["colors"]) == {"bg", "fg", "panel", "border", "red"}


def test_an_export_without_the_newer_options_still_imports(src):
    """The owner's file predates the fix and carries four of the seven.

    Import reads the three additions with `!== undefined` rather than
    truthiness, so their absence leaves the defaults alone instead of forcing
    them off. A file written before 2026-08-30 must keep working.
    """
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "frosted" not in data
    block = _block(src, "if (importGoEl && importAreaEl)", "if (importCancelEl")
    for key in ("bgEffectIntensity", "bgEffectSize", "frosted"):
        assert f"parsed.{key} !== undefined" in block, (
            f"{key} must be read with an undefined check, or an older export "
            f"turns it off rather than leaving it alone"
        )


# ── the four lists agree ───────────────────────────────────────────────────

def test_save_custom_theme_stores_every_option(src):
    block = _block(src, "export function saveCustomTheme", "export function deleteCustomTheme")
    assert _options_named_in(block, "opts") == STORED_OPTIONS


def test_save_stores_every_option(src):
    block = _block(src, "export function save(", "function _syncToServer")
    assert _options_named_in(block, "opts") == STORED_OPTIONS


def test_export_writes_every_option_the_theme_stores(src):
    """The defect. Export wrote four of seven; glass was one of the three."""
    block = _block(src, "if (exportBtnEl)", "if (importBtnEl")
    assert _options_named_in(block, "cur") == STORED_OPTIONS


def test_import_reads_every_option_export_writes(src):
    block = _block(src, "if (importGoEl && importAreaEl)", "if (importCancelEl")
    assert _options_named_in(block, "parsed") == STORED_OPTIONS


# ── the glass toggle in particular, because it is a headline feature ───────

def test_frosted_glass_survives_a_round_trip(src):
    export_block = _block(src, "if (exportBtnEl)", "if (importBtnEl")
    import_block = _block(src, "if (importGoEl && importAreaEl)", "if (importCancelEl")
    assert "obj.frosted" in export_block, "export must write the glass state"
    assert "opts.frosted" in import_block, "import must read the glass state"
    assert "applyFrostedGlass" in import_block, (
        "import must apply the glass state — storing it without applying it "
        "means the look only appears after a reload"
    )


def test_every_function_the_importer_calls_exists(src):
    """`node --check` parses this file; it does not resolve names.

    The first draft of the export fix called `applyFrosted`, which does not
    exist — the function is `applyFrostedGlass`. It parsed, and would have
    thrown on the first import. This is that check.
    """
    block = _block(src, "if (importGoEl && importAreaEl)", "if (importCancelEl")
    called = set(re.findall(r"(?<![\w.])([a-z_$][\w$]*)\s*\(", block))
    defined = set(re.findall(r"(?:export\s+)?function\s+([\w$]+)", src))
    defined |= set(re.findall(r"(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?\(", src))
    language = {"if", "for", "while", "switch", "catch", "return", "typeof"}
    unresolved = sorted(c for c in called - defined - language if not c[0].isupper())
    assert unresolved == [], f"the importer calls names this module does not define: {unresolved}"
