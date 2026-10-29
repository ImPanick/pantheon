#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1674` (`D-2026-10-29-03` §3). The CJK face the fallback PDF draws Chinese,
Japanese and Korean with: `static/lib/pdf-fonts/NotoSansCJKsc-Regular.subset.ttf`.

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

    python3 scripts/build-pdf-cjk-font.py <NotoSansCJKsc-VF.ttf> <out.ttf>

Needs fontTools (4.66.1 made the committed file; the output is the same bytes
on every run). It is a vendoring tool, run by hand when the font is bumped, and
nothing at runtime needs it. `.pantheon/check-vendored-versions.py` records the
command and the output's sha256; `.pantheon/vendored-builds/` records the build.
"""
from __future__ import annotations

import hashlib
import sys
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


def build(source: Path, out: Path) -> str:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(
            f"{source} is not Noto Sans CJK SC's variable TrueType at Sans2.004 (sha256 {digest}, "
            f"expected {SOURCE_SHA256}). Building from another release means checking its "
            f"coverage and licence again and moving SOURCE_SHA256 with it.")
    font = TTFont(source, recalcTimestamp=False)
    options = subset.Options()
    options.layout_features = []
    options.drop_tables += DROPPED
    options.glyph_names = False
    options.notdef_outline = True
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=characters())
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
    if len(argv) != 2:
        print("usage: python3 scripts/build-pdf-cjk-font.py <NotoSansCJKsc-VF.ttf> <out.ttf>",
              file=sys.stderr)
        return 2
    out = Path(argv[1])
    digest = build(Path(argv[0]), out)
    print(f"{out}: {out.stat().st_size:,} bytes, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
