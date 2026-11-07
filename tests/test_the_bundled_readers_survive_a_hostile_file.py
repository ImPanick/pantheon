# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1178` / `B1289` — the new `.ods`, `.xls`, `.pptx` and `.epub` readers are
bounded against the file's author, the way `B102`'s and `B1156`'s are.

Each case is a file an attacker could attach, built here byte by byte, handed
to the real reader (`src/ooxml_native.py`) and through the real chain
(`markitdown_runtime.convert_to_markdown`, which is what every door calls).

`B1956` holds the rest of the chain to the same bound. When the structured
`.docx` reader refused a part for its size, the chain went on to the `<w:t>`
walk, which read the part whole; the `.odt` reader had no bound at all; and
markitdown and `python-docx`, which read every part whole, were handed any file
first. A part that inflates past `PART_LIMIT`, whatever size its header states,
is now read by no rung past it. Reported upstream in Odysseus PR #6976
(c8481eab).
"""
import io
import time
import zipfile

from src import markitdown_runtime as mr
from src import ooxml_native as on
from tests.helpers.office_fixtures import office_fixture, office_sample

_ODS_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
    '<office:body><office:spreadsheet><table:table table:name="S">')
_ODS_TAIL = "</table:table></office:spreadsheet></office:body></office:document-content>"


def _zip(tmp_path, name, parts):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for part, data in parts.items():
            z.writestr(part, data)
    path = tmp_path / name
    path.write_bytes(b.getvalue())
    return str(path)


def test_a_billion_repeated_cells_are_not_a_billion_cells(tmp_path):
    rows = ('<table:table-row table:number-rows-repeated="1000000000">'
            '<table:table-cell table:number-columns-repeated="1000000000" '
            'office:value-type="string"><text:p>x</text:p></table:table-cell>'
            '</table:table-row>')
    path = _zip(tmp_path, "bomb.ods", {"content.xml": _ODS_HEAD + rows + _ODS_TAIL})
    started = time.monotonic()
    sheets = on.ods_sheets(path)
    assert time.monotonic() - started < 30
    (_name, csv), = sheets
    assert 0 < csv.count("x") <= on._ODS_MAX_CELLS


def test_a_declared_entity_is_refused_in_every_new_reader(tmp_path):
    entity = '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]>'
    ods = _zip(tmp_path, "e.ods", {"content.xml": entity + _ODS_HEAD + _ODS_TAIL})
    assert on.ods_sheets(ods) is None
    epub = _zip(tmp_path, "e.epub", {
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                                  '<rootfiles><rootfile full-path="c.opf"/></rootfiles></container>',
        "c.opf": '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                 '<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/></manifest>'
                 '<spine><itemref idref="a"/></spine></package>',
        "a.xhtml": entity + "<html><body><p>&a;&a;</p></body></html>"})
    assert on.epub_text(epub) is None


def test_a_slide_that_points_nowhere_is_skipped_not_raised(tmp_path):
    deck = io.BytesIO(office_sample("deck.pptx"))
    src = zipfile.ZipFile(deck)
    parts = {n: src.read(n) for n in src.namelist() if n != "ppt/slides/slide2.xml"}
    path = _zip(tmp_path, "holed.pptx", parts)
    text = on.pptx_text(path)
    assert "DECKSENTINEL5e8" in text and "Outlook" not in text


def test_a_truncated_or_foreign_workbook_reads_as_nothing(tmp_path):
    xls = office_fixture(".xls")
    for n, body in enumerate((xls[:600], xls[:2048], b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(600),
                              b"not a workbook at all")):
        path = tmp_path / f"t{n}.xls"
        path.write_bytes(body)
        # Through the chain every door calls: never an exception, at most None.
        assert mr.convert_to_markdown(str(path)) is None or isinstance(
            mr.convert_to_markdown(str(path)), str)


# ── `B1956`: a part that inflates past the bound is read by no rung past it ──
_W_DOC = ('<?xml version="1.0"?><w:document xmlns:w="'
          + on.W[1:-1] + '"><w:body><w:p><w:r><w:t>INFLATED</w:t></w:r></w:p>')
_W_END = "</w:body></w:document>"
_ODT_DOC = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:text><text:p>INFLATED</text:p>')
_ODT_END = "</office:text></office:body></office:document-content>"


def _inflating(tmp_path, name, part, head, tail, *, declare=None, mib=48):
    """A zip a few kilobytes long whose `part` inflates to `mib` MiB of blanks
    between `head` and `tail`. `declare` rewrites the size its central
    directory entry states, the way a hostile file understates it."""
    import struct

    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        with z.open(part, "w") as fh:
            fh.write(head.encode())
            blanks = b" " * (1 << 20)
            for _ in range(mib):
                fh.write(blanks)
            fh.write(tail.encode())
    raw = bytearray(b.getvalue())
    if declare is not None:
        entry = raw.rfind(b"PK\x01\x02")       # the one part's central directory entry
        struct.pack_into("<I", raw, entry + 24, declare)
    path = tmp_path / name
    path.write_bytes(bytes(raw))
    return str(path)


def _held(fn, *args):
    """What `fn(*args)` returned, and the most memory it held doing it."""
    import tracemalloc

    tracemalloc.start()
    try:
        out = fn(*args)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return out, peak


def _no_markitdown(monkeypatch):
    def missing():
        raise RuntimeError(mr.MARKITDOWN_MISSING)
    monkeypatch.setattr(mr, "load_markitdown", missing)


def test_a_docx_that_inflates_past_the_bound_is_not_read_past_it(tmp_path, monkeypatch):
    """`B1956`. The structured reader stopped at `PART_LIMIT` and the chain
    went on to the `<w:t>` walk, which read the whole part: a file of a few
    kilobytes held 48 MiB and answered with its text. One that understates
    its size held it too, and then failed its checksum."""
    _no_markitdown(monkeypatch)
    monkeypatch.setattr(on, "PART_LIMIT", 1 << 20)
    for name, declare in (("bomb.docx", None), ("lying.docx", 1000)):
        path = _inflating(tmp_path, name, "word/document.xml", _W_DOC, _W_END, declare=declare)

        text, peak = _held(mr.convert_to_markdown, path)

        assert text is None, name
        assert peak < 8 << 20, f"{name}: {peak / (1 << 20):.1f} MiB held to read one part"
        assert mr.office_extraction_gap(path) == mr.NO_EXTRACTABLE_TEXT


def test_an_odt_that_inflates_past_the_bound_is_not_read_past_it(tmp_path, monkeypatch):
    """`B1956`. The `.odt` reader read `content.xml` whole, with no bound."""
    monkeypatch.setattr(on, "PART_LIMIT", 1 << 20)
    for name, declare in (("bomb.odt", None), ("lying.odt", 1000)):
        path = _inflating(tmp_path, name, "content.xml", _ODT_DOC, _ODT_END, declare=declare)

        text, peak = _held(mr.convert_to_markdown, path)

        assert text is None, name
        assert peak < 8 << 20, f"{name}: {peak / (1 << 20):.1f} MiB held to read one part"


def test_markitdown_is_never_handed_a_file_that_inflates_past_the_bound(tmp_path, monkeypatch):
    """`B1956`. markitdown reads every part whole, and first. A part stating
    48 MiB, and one stating 1,000 bytes that inflates to 48 MiB, go to the
    bounded readers instead; an ordinary file still goes to markitdown."""
    handed = []

    class _MarkItDown:
        def convert(self, path):
            handed.append(path)
            return type("R", (), {"text_content": "MARKITDOWN SAID SO"})()

    monkeypatch.setattr(mr, "load_markitdown", lambda: _MarkItDown)
    monkeypatch.setattr(on, "PART_LIMIT", 1 << 20)
    for name, declare in (("stated.docx", None), ("lying.docx", 1000)):
        path = _inflating(tmp_path, name, "word/document.xml", _W_DOC, _W_END, declare=declare)

        text, peak = _held(mr.convert_to_markdown, path)

        assert text is None and handed == [], name
        assert peak < 8 << 20, f"{name}: {peak / (1 << 20):.1f} MiB held"

    small = _zip(tmp_path, "small.docx", {"[Content_Types].xml": "<Types/>",
                                          "word/document.xml": _W_DOC + _W_END})
    assert mr.convert_to_markdown(small) == "MARKITDOWN SAID SO"
    assert handed == [small]


def test_python_docx_is_never_handed_a_file_that_inflates_past_the_bound(tmp_path, monkeypatch):
    """`B1956`. `python-docx`, the `.docx` chain's middle rung, reads every
    part whole too; such a file goes on to the bounded `<w:t>` walk."""
    import sys
    import types

    opened = []

    def document(path):
        opened.append(path)
        return types.SimpleNamespace(paragraphs=[], tables=[])

    monkeypatch.setitem(sys.modules, "docx", types.SimpleNamespace(Document=document))
    monkeypatch.setattr(on, "PART_LIMIT", 1 << 20)
    for name, declare in (("stated.docx", None), ("lying.docx", 1000)):
        path = _inflating(tmp_path, name, "word/document.xml", _W_DOC, _W_END, declare=declare)
        assert mr._extract_docx_python_docx(path) is None
    assert opened == []

    small = _zip(tmp_path, "small.docx", {"[Content_Types].xml": "<Types/>",
                                          "word/document.xml": _W_DOC + _W_END})
    mr._extract_docx_python_docx(small)
    assert opened == [small]
