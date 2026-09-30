# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real font files for `P2-24`, built here so no third-party font ships in the repo.

`P0-23` deleted a bundled font whose metadata read *"Copyright (c) 2025,
Unknown"*; a test fixture is not a reason to bring that question back. So the
TrueType file below is assembled table by table — `head`, `hhea`, `maxp`,
`OS/2`, `hmtx`, `cmap`, `loca`, `glyf`, `name`, `post` — and the WOFF 1.0 file
wraps it with zlib, the way the W3C format says.

**It is checked by a parser that is not ours.** A fixture written by the same
hand as the validator agrees with the validator's assumptions and passes for the
wrong reason (`B102`'s rule, `tests/helpers/office_fixtures.py`). The tests
load both files with FreeType through Pillow and render a glyph before trusting
them, so "a real font" means FreeType thinks so.

The WOFF2 case needs no builder: `static/fonts/Inter-Regular.woff2` ships with
the product and is as real as a font gets.
"""
import struct
import zlib

FAMILY = "Pantheon Test Sans"


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def _checksum(data: bytes) -> int:
    data = _pad4(data)
    return sum(struct.unpack(f">{len(data) // 4}I", data)) & 0xFFFFFFFF


def _square_glyph(x0, y0, x1, y1) -> bytes:
    """One closed contour, four on-curve points, absolute coordinates."""
    points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    header = struct.pack(">hhhhh", 1, x0, y0, x1, y1)
    end_pts = struct.pack(">H", len(points) - 1)
    instructions = struct.pack(">H", 0)
    flags = bytes([0x01] * len(points))  # on-curve, 16-bit deltas
    xs, ys, px, py = b"", b"", 0, 0
    for x, y in points:
        xs += struct.pack(">h", x - px)
        ys += struct.pack(">h", y - py)
        px, py = x, y
    return header + end_pts + instructions + flags + xs + ys


def _name_table(family: str) -> bytes:
    records = [(1, family), (2, "Regular"), (4, f"{family} Regular"),
               (6, family.replace(" ", "") + "-Regular")]
    strings, entries, offset = b"", b"", 0
    for name_id, text in records:
        raw = text.encode("utf-16-be")
        entries += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(raw), offset)
        strings += raw
        offset += len(raw)
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + entries + strings


def _delta(cp: int, gid: int) -> bytes:
    if cp == 0xFFFF:
        return struct.pack(">H", 1)
    return struct.pack(">H", (gid - cp) & 0xFFFF)


def _cmap(codepoints_to_glyph: dict) -> bytes:
    segments = sorted(codepoints_to_glyph.items()) + [(0xFFFF, 0)]
    count = len(segments)
    search = 1
    while search * 2 <= count:
        search *= 2
    ends = b"".join(struct.pack(">H", cp) for cp, _ in segments)
    starts = b"".join(struct.pack(">H", cp) for cp, _ in segments)
    deltas = b"".join(_delta(cp, gid) for cp, gid in segments)
    range_offsets = b"\0\0" * count
    body = (struct.pack(">HHHH", count * 2, search * 2, search.bit_length() - 1,
                        count * 2 - search * 2)
            + ends + b"\0\0" + starts + deltas + range_offsets)
    subtable = struct.pack(">HHH", 4, 6 + len(body), 0) + body
    return struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 1, 12) + subtable


def truetype_font(family: str = FAMILY) -> bytes:
    """A small, complete TrueType font: `.notdef` plus squares for A, B and space."""
    units = 1000
    glyphs = [b"", _square_glyph(100, 0, 500, 700), _square_glyph(100, 0, 600, 700), b""]
    advances = [600, 600, 700, 300]
    cmap = _cmap({0x20: 3, 0x41: 1, 0x42: 2})
    glyf, loca = b"", []
    for g in glyphs:
        loca.append(len(glyf))
        glyf += _pad4(g)
    loca.append(len(glyf))
    loca_bytes = b"".join(struct.pack(">I", o) for o in loca)  # long format
    head = struct.pack(">IIIIHHQQhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5,
                       0x000B, units, 0, 0, 0, 0, 600, 700, 0, 8, 2, 1, 0)
    hhea = struct.pack(">IhhhHhhhhhhhhhhhH", 0x00010000, 800, -200, 0, 700, 0, 0, 600,
                       1, 0, 0, 0, 0, 0, 0, 0, len(glyphs))
    maxp = struct.pack(">IHHHHHHHHHHHHHH", 0x00010000, len(glyphs), 4, 1, 0, 0, 2, 0,
                       0, 0, 0, 0, 0, 0, 0)
    # OS/2 version 3, 96 bytes, field by field.
    os2 = struct.pack(">HhHHHhhhhhhhhhhh10sIIII4sHHHhhhHHIIhhHHH",
                      3, 550, 400, 5, 0,                 # version .. fsType
                      650, 700, 0, 140, 650, 700, 0, 480,  # sub/superscript
                      50, 250, 0,                        # strikeout, family class
                      b"\0" * 10, 1, 0, 0, 0, b"PNTH",   # panose, ranges, vendor
                      0x40, 0x20, 0x42,                  # fsSelection, first, last
                      800, -200, 0, 800, 200,            # typo and win metrics
                      1, 0, 500, 700, 0, 0x20, 1)        # code pages .. maxContext
    hmtx = b"".join(struct.pack(">Hh", adv, 0) for adv in advances)
    post = struct.pack(">Iihh5I", 0x00030000, 0, -100, 50, 0, 0, 0, 0, 0)
    tables = {
        b"OS/2": os2, b"cmap": cmap, b"glyf": glyf, b"head": head, b"hhea": hhea,
        b"hmtx": hmtx, b"loca": loca_bytes, b"maxp": maxp, b"name": _name_table(family),
        b"post": post,
    }
    return _assemble(0x00010000, tables)


def _assemble(version: int, tables: dict) -> bytes:
    tags = sorted(tables)
    count = len(tags)
    search = 1
    while search * 2 <= count:
        search *= 2
    header = struct.pack(">IHHHH", version, count, search * 16, search.bit_length() - 1,
                         count * 16 - search * 16)
    offset = 12 + 16 * count
    directory, body = b"", b""
    for tag in tags:
        data = tables[tag]
        directory += struct.pack(">4sIII", tag, _checksum(data), offset + len(body), len(data))
        body += _pad4(data)
    font = bytearray(header + directory + body)
    # head.checkSumAdjustment, now that the whole file is known.
    head_offset = 12 + 16 * count + sum(len(_pad4(tables[t])) for t in tags[:tags.index(b"head")])
    adjust = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
    font[head_offset + 8:head_offset + 12] = struct.pack(">I", adjust)
    return bytes(font)


def woff_font(sfnt: bytes) -> bytes:
    """WOFF 1.0 around an sfnt: header, directory, zlib-compressed tables."""
    flavor, count = struct.unpack(">IH", sfnt[:6])
    records = []
    for i in range(count):
        tag, checksum, offset, length = struct.unpack(">4sIII", sfnt[12 + 16 * i:28 + 16 * i])
        records.append((tag, checksum, sfnt[offset:offset + length]))
    offset = 44 + 20 * count
    directory, body = b"", b""
    for tag, checksum, data in records:
        packed = zlib.compress(data)
        if len(packed) >= len(data):
            packed = data
        directory += struct.pack(">4sIIII", tag, offset + len(body), len(packed), len(data), checksum)
        body += _pad4(packed)
    total = offset + len(body)
    header = struct.pack(">4sIIHHIHHIIIII", b"wOFF", flavor, total, count, 0, len(sfnt),
                         1, 0, 0, 0, 0, 0, 0)
    return header + directory + body
