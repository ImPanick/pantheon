#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1674` (`D-2026-10-29-03` §3). The CJK face the fallback PDF draws Chinese,
Japanese and Korean with: `static/lib/pdf-fonts/NotoSansCJKsc-Regular.subset.ttf`.
`B1691`: and its symbols face, `NotoSansCJKsc-Symbols.subset.ttf`, cut from the
same source the same way (below, *The symbols face*).

The fallback PDF is drawn by jsPDF's `html()`, whose built-in fonts are
Windows-1252 only. jsPDF can embed a TrueType font — `glyf` outlines, not the
CFF of Noto Sans CJK's `.otf`s — and it draws each run of text in one font, with
no fallback from glyph to glyph. So the CJK face has to be one TrueType font
holding all three scripts, and small enough for the owner's budget ("roughly
5–10 MB more", with Inter's four faces).

**The source** is Noto Sans CJK SC's variable TrueType, `Sans2.004`
(`Sans/Variable/TTF/NotoSansCJKsc-VF.ttf` at that tag of
`github.com/notofonts/noto-cjk`; 36,144,788 bytes, sha256 in `SOURCE_SHA256`).
It is the Pan-CJK font — Simplified and Traditional Chinese, Japanese kana and
kanji, and Korean Hangul — with Simplified Chinese glyph forms by default.
Noto publishes no checksum for it; the bytes were the same from the tag and from
`main` on 2026-10-29.

**What this does to it**, and nothing else:

  1. keeps the characters four published national character sets encode —
     GB 2312, Big5, JIS X 0208 and KS X 1001, read out of Python's own codecs
     for them, so the set is the standards' and not a list kept here — plus the
     whole CJK Symbols and Punctuation, Hiragana, Katakana and Halfwidth and
     Fullwidth Forms blocks, and ASCII; 20,340 glyphs of 65,535;
  2. drops what jsPDF never reads (OpenType layout, vertical metrics, glyph
     names, the digital signature, `STAT`);
  3. fixes the weight axis at 400 — the file's default instance is Thin (100),
     which is what jsPDF, reading `glyf` and ignoring `gvar`, would draw;
  4. names the result Regular.

That is a Modified Version under the OFL. Noto Sans CJK's one Reserved Font Name
is "Source" (its copyright line, `licenses/NotoSansCJK-OFL.txt`), which this
name does not use.

**The symbols face** (`B1691`). The export fetches the CJK face for a character
in the Chinese, Japanese and Korean blocks (`_PDF_CJK` in
`static/js/document.js`) and Inter for one Inter draws; a box-drawing, block,
maths or dingbat character — every one of a pasted `tree` listing's `├── └──`
— is in neither, so a Latin document lost it, though the source draws it. The
6.4 MB face is not fetched for a `─`: this second cut keeps, from the same
source, only the characters of the blocks around it that the source draws and
that neither Windows-1252 (the built-in fonts) nor Inter (the vendored
`Inter-Regular.ttf`, read here) does — the symbol and punctuation blocks from
General Punctuation to Miscellaneous Symbols and Arrows, Supplemental
Punctuation, and the four small blocks outside `_PDF_CJK` the source also
draws (`SYMBOL_BLOCKS`): 532 characters in 521 glyphs, 73 KB — every
character of the source, up to U+FFFF and outside `_PDF_CJK`, that the export
had no face for (measured 2026-10-29), and 237 more than the CJK face carries
(`║ ╔ ╝`, `░ ▓`, `❶`, `⇄`). The same steps 2–4 make it, so it is the same
Regular instance as the CJK face, glyph for glyph.

    python3 scripts/build-pdf-cjk-font.py <NotoSansCJKsc-VF.ttf> <out-dir>

writes both faces into `<out-dir>` (`static/lib/pdf-fonts`). Needs fontTools
(4.66.1 made the committed files; the output is the same bytes on every run).
It is a vendoring tool, run by hand when the font is bumped — or Inter, which
the symbols face is cut against — and nothing at runtime needs it.
`.pantheon/check-vendored-versions.py` records the command and each output's
sha256; `.pantheon/vendored-builds/` records the build. A face's coverage is
read for the export by `node scripts/build-pdf-font-coverage.mjs`, which a
rebuilt symbols face needs run again.
"""
from __future__ import annotations

import hashlib
import sys
import unicodedata
from pathlib import Path

SOURCE_SHA256 = "990c807e79c25662a5a9ecf7f971baeb2bf2eab9a559e5ecf15cdfdb8561d21f"

#: The national character sets, by the codec Python reads each with.
CHARACTER_SETS = {"GB 2312": "gb2312", "Big5": "big5", "JIS X 0208": "euc_jp", "KS X 1001": "euc_kr"}

#: Whole blocks kept as well: (first, last) code points.
BLOCKS = {
    "ASCII": (0x20, 0x7E),
    "CJK Symbols and Punctuation": (0x3000, 0x303F),
    "Hiragana": (0x3040, 0x309F),
    "Katakana": (0x30A0, 0x30FF),
    "Halfwidth and Fullwidth Forms": (0xFF00, 0xFFEF),
}

#: What jsPDF does not read, so the file need not carry it.
DROPPED = ["GSUB", "GPOS", "GDEF", "BASE", "vhea", "vmtx", "VORG", "DSIG", "STAT"]

#: `B1691`. The symbols face's blocks, by Unicode's own ranges for them. None
#: is in `_PDF_CJK` (`static/js/document.js`), which fetches the CJK face; the
#: last four are the blocks outside it the source still draws characters of
#: (ideographic description, the ﬁ ligatures, vertical and small forms).
SYMBOL_BLOCKS = {
    "General Punctuation to Miscellaneous Symbols and Arrows": (0x2000, 0x2BFF),
    "Supplemental Punctuation": (0x2E00, 0x2E7F),
    "Ideographic Description Characters": (0x2FF0, 0x2FFF),
    "Alphabetic Presentation Forms": (0xFB00, 0xFB4F),
    "Vertical Forms": (0xFE10, 0xFE1F),
    "Small Form Variants": (0xFE50, 0xFE6F),
}

#: The face the export draws Latin, Greek and Cyrillic with, beside this file.
INTER = Path(__file__).resolve().parent.parent / "static" / "lib" / "pdf-fonts" / "Inter-Regular.ttf"

CJK_FACE = "NotoSansCJKsc-Regular.subset.ttf"
SYMBOLS_FACE = "NotoSansCJKsc-Symbols.subset.ttf"


def encoded_by(codec: str) -> set[int]:
    """Every character `codec` decodes from a two-byte sequence: the double-byte
    half of the character set it implements (the single-byte half is ASCII)."""
    out = set()
    for hi in range(0x81, 0xFF):
        for lo in range(0x40, 0xFF):
            try:
                text = bytes((hi, lo)).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(text) == 1 and 0x7F < ord(text) <= 0xFFFF:
                out.add(ord(text))
    return out


def characters() -> set[int]:
    out = set()
    for codec in CHARACTER_SETS.values():
        out |= encoded_by(codec)
    for first, last in BLOCKS.values():
        out |= set(range(first, last + 1))
    return out


def windows_1252() -> set[int]:
    """The characters Windows-1252 encodes, the PDF's built-in fonts' encoding."""
    out = set()
    for byte in range(0x20, 0x100):
        try:
            out.add(ord(bytes((byte,)).decode("cp1252")))
        except UnicodeDecodeError:
            continue
    return out


def symbol_characters(source: Path) -> set[int]:
    """`B1691`. The symbols face's characters: those of `SYMBOL_BLOCKS` the
    source draws and neither the built-in fonts nor Inter does — less the
    invisible ones (spaces, format and control characters), which the export
    never fetches a face for."""
    from fontTools.ttLib import TTFont

    drawn = TTFont(source, lazy=True).getBestCmap()
    elsewhere = windows_1252() | set(TTFont(INTER, lazy=True).getBestCmap())
    out = set()
    for first, last in SYMBOL_BLOCKS.values():
        for cp in range(first, last + 1):
            if cp in drawn and cp not in elsewhere and unicodedata.category(chr(cp))[0] not in "CZ":
                out.add(cp)
    return out


def check_source(source: Path) -> None:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(
            f"{source} is not Noto Sans CJK SC's variable TrueType at Sans2.004 (sha256 {digest}, "
            f"expected {SOURCE_SHA256}). Building from another release means checking its "
            f"coverage and licence again and moving SOURCE_SHA256 with it.")


def build(source: Path, out: Path, unicodes: set[int]) -> str:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(source, recalcTimestamp=False)
    options = subset.Options()
    options.layout_features = []
    options.drop_tables += DROPPED
    options.glyph_names = False
    options.notdef_outline = True
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    instancer.instantiateVariableFont(font, {"wght": 400}, inplace=True)
    name = font["name"]
    name.removeNames(nameID=17)
    for nid, value in ((2, "Regular"), (3, "2.004;ADBO;NotoSansCJKsc-Regular;ADOBE"),
                       (4, "Noto Sans CJK SC"), (6, "NotoSansCJKsc-Regular")):
        name.setName(value, nid, 3, 1, 0x409)
        if name.getName(nid, 1, 0, 0):
            name.setName(value, nid, 1, 0, 0)
    font["OS/2"].usWeightClass = 400
    font.save(out, reorderTables=True)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not Path(argv[1]).is_dir():
        print("usage: python3 scripts/build-pdf-cjk-font.py <NotoSansCJKsc-VF.ttf> <out-dir>\n"
              f"  writes {CJK_FACE} and {SYMBOLS_FACE} into <out-dir>, which must exist",
              file=sys.stderr)
        return 2
    source, where = Path(argv[0]), Path(argv[1])
    check_source(source)
    from fontTools.ttLib import TTFont

    for name, unicodes in ((CJK_FACE, characters()), (SYMBOLS_FACE, symbol_characters(source))):
        out = where / name
        digest = build(source, out, unicodes)
        made = TTFont(out, lazy=True)
        print(f"{out}: {out.stat().st_size:,} bytes, {len(made.getBestCmap()):,} characters in "
              f"{len(made.getGlyphOrder()):,} glyphs, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
