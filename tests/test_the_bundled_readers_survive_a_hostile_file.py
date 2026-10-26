# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1178` / `B1289` — the new `.ods`, `.xls`, `.pptx` and `.epub` readers are
bounded against the file's author, the way `B102`'s and `B1156`'s are.

Each case is a file an attacker could attach, built here byte by byte, handed
to the real reader (`src/ooxml_native.py`) and through the real chain
(`markitdown_runtime.convert_to_markdown`, which is what every door calls).
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
