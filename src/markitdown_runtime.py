# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers for the optional markitdown document-extraction dependency.

markitdown (MIT, Microsoft) converts Office/EPUB documents to Markdown, which is
more token-efficient and model-legible than a raw text dump. It is **optional**:
install with `pip install -r requirements-optional.txt`. When absent, callers
degrade gracefully (chat shows a hint; the RAG indexer skips the file) — the MIT
core never hard-depends on it. Mirrors the optional-dependency pattern in
`src/pdf_runtime.py`.
"""

import logging
import os

logger = logging.getLogger(__name__)

MARKITDOWN_MISSING = (
    "Office/EPUB document extraction requires markitdown. Install optional "
    "dependencies with `pip install -r requirements-optional.txt`."
)

# Formats routed through markitdown. PDFs stay on pypdf (src/document_processor
# and src/personal_docs); plain text/code/csv/json/markdown/html stay on the
# cheaper built-in text path.
MARKITDOWN_EXTS = frozenset({".docx", ".pptx", ".xlsx", ".xls", ".epub"})

# Formats the bundled pure-Python extractors below read, and markitdown does
# not. `B102`: driven against markitdown 0.1.6 both `.odt` and `.doc` raise
# ``UnsupportedFormatException`` — *"no converter attempted a conversion"* — so
# listing them in ``MARKITDOWN_EXTS`` would have turned a truthful "no extractor
# covers this file type" banner into a misleading "no extractable text found"
# one. They are a different extractor, so they are a different register: the
# rule is one register per extractor, and ``OFFICE_EXTS`` is the union the
# ingest layer asks, never a fourth hand-written copy.
NATIVE_OFFICE_EXTS = frozenset({".odt", ".doc"})

# Every non-PDF document format chat ingest can extract, whichever code does it.
OFFICE_EXTS = MARKITDOWN_EXTS | NATIVE_OFFICE_EXTS


def is_markitdown_format(path: str) -> bool:
    """True if the file extension is one markitdown itself converts."""
    if not isinstance(path, str):
        return False
    return os.path.splitext(path)[1].lower() in MARKITDOWN_EXTS


def is_office_format(path: str) -> bool:
    """True if any extractor in this module can read *path*.

    This is the question ``document_processor._process_office_document`` needs
    answered — "can anything here read it" — and it used to be spelled
    ``is_markitdown_format``, which answers a narrower one. `B102`: the two
    were the same set until the bundled `.odt`/`.doc` readers arrived, and
    conflating them is how `.doc` ended up with no extractor while `.docx` had
    two.
    """
    if not isinstance(path, str):
        return False
    return os.path.splitext(path)[1].lower() in OFFICE_EXTS


def load_markitdown():
    """Return the MarkItDown class, or raise a user-facing setup hint."""
    try:
        from markitdown import MarkItDown  # optional dependency
    except ImportError as exc:
        raise RuntimeError(MARKITDOWN_MISSING) from exc
    return MarkItDown


def _extract_docx_native(path: str) -> str | None:
    """Pure-Python .docx text extractor — no external deps.

    A .docx file is just a zip of XML. The body prose lives in <w:t> runs
    inside <w:p> paragraphs. Iterating with ElementTree (rather than
    re.findall) keeps paragraph breaks intact and lets the XML parser handle
    namespaces + entity unescaping. Loses tables, footnotes, images and
    list bullets — keeps ~95% of "summarize this doc" content, which is the
    case people hit when markitdown isn't installed.
    """
    import zipfile

    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            xml_bytes = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    root = _parse_office_xml(xml_bytes)
    if root is None:
        return None
    paragraphs: list[str] = []
    for para in root.iter(f"{ns}p"):
        runs = [t.text or "" for t in para.iter(f"{ns}t")]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs) if paragraphs else None


# ── ODF (.odt) ────────────────────────────────────────────────────────────
_ODF_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _parse_office_xml(xml_bytes: bytes):
    """Parse a document part from an untrusted zip, or return ``None``.

    ``ElementTree`` never resolves external entities, so there is no XXE here,
    but it does expand *internal* ones — a 200-byte ``<!ENTITY>`` chain is the
    classic way to turn an attachment into an out-of-memory. A document part
    has no legitimate reason to declare entities, so one that does is refused
    before the parser sees it. Shared by both readers below so the guard cannot
    exist on one and not the other (`Law 13`).
    """
    import xml.etree.ElementTree as ET

    if b"<!ENTITY" in xml_bytes or b"<!entity" in xml_bytes:
        logger.warning("document part declares XML entities; refusing to parse")
        return None
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None


def _extract_odf_native(path: str) -> str | None:
    """Pure-Python .odt text extractor — no external deps.

    An ODF text document is a zip whose ``content.xml`` holds the body as
    ``<text:p>`` paragraphs and ``<text:h>`` headings — the same shape the
    bundled ``.docx`` reader already walks, one namespace over. `B102`: `.odt`
    had no extractor at all, and markitdown refuses it, so the alternative to
    these forty lines is the banner.

    A paragraph is taken whole (``itertext``) and not descended into, so text
    inside a footnote or annotation body is emitted once rather than twice.
    ``<text:tab>`` and ``<text:line-break>`` are empty elements carrying no
    text, so they are turned back into the characters they stand for; table
    cells arrive as their own paragraphs, which loses the row structure and
    keeps every word of it — the same trade the ``.docx`` reader makes.
    """
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            xml_bytes = z.read("content.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    root = _parse_office_xml(xml_bytes)
    if root is None:
        return None

    def render(el) -> str:
        out = []
        if el.text:
            out.append(el.text)
        for child in el:
            tag = child.tag
            if tag == _ODF_TEXT_NS + "tab":
                out.append("\t")
            elif tag == _ODF_TEXT_NS + "line-break":
                out.append("\n")
            elif tag == _ODF_TEXT_NS + "s":
                out.append(" " * max(1, int(child.get(_ODF_TEXT_NS + "c", 1) or 1)))
            else:
                out.append(render(child))
            if child.tail:
                out.append(child.tail)
        return "".join(out)

    blocks: list[str] = []

    def walk(el) -> None:
        for child in el:
            if child.tag in (_ODF_TEXT_NS + "p", _ODF_TEXT_NS + "h"):
                line = render(child).strip()
                if line:
                    blocks.append(line)
            else:
                walk(child)

    walk(root)
    return "\n\n".join(blocks) if blocks else None


# ── Legacy Word (.doc) ────────────────────────────────────────────────────
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
# Word's in-text control codes. \x13 opens a field, \x14 separates its
# instruction from its result and \x15 closes it: "\x13 HYPERLINK "http://…"
# \x14 the link \x15" must reach the model as "the link", not as the URL and
# the switches. \x07 ends a table cell, twice in a row ends the row.
_DOC_DROP = dict.fromkeys([0x01, 0x02, 0x05, 0x08, 0x1F], "")
_DOC_DROP.update({0x0B: "\n", 0x0C: "\n", 0x0E: "\n", 0x1E: "-", 0x0D: "\n"})


def _cfb_streams(data: bytes, wanted: set) -> dict:
    """Read named streams out of an OLE2/CFB container.

    A `.doc` is not a zip: it is a little FAT filesystem in a file, and the
    prose lives in a stream inside it. This is the minimum of that format —
    the FAT, the mini-FAT for streams under the 4 KiB cutoff, and the
    directory — and nothing else; it is a reader, it allocates only what the
    header describes, and every chain walk is bounded.
    """
    import struct

    if not data.startswith(_CFB_MAGIC) or len(data) < 512:
        return {}
    u16 = lambda o: struct.unpack_from("<H", data, o)[0]  # noqa: E731
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]  # noqa: E731
    try:
        ssz = 1 << u16(0x1E)
        mssz = 1 << u16(0x20)
        n_fat = u32(0x2C)
        dir_start = u32(0x30)
        mini_cutoff = u32(0x38)
        mini_fat_start = u32(0x3C)
        n_mini_fat = u32(0x40)
        difat_start = u32(0x44)
        n_difat = u32(0x48)
    except struct.error:
        return {}
    if ssz < 128 or ssz > 1 << 20 or mssz < 8 or mssz > ssz:
        return {}
    max_sectors = max(0, (len(data) - ssz) // ssz)

    def sector(i: int) -> bytes:
        off = (i + 1) * ssz
        return data[off:off + ssz]

    difat = [u32(0x4C + 4 * i) for i in range(109)]
    nxt, seen = difat_start, 0
    while nxt not in (_ENDOFCHAIN, _FREESECT) and nxt < max_sectors and seen <= n_difat:
        sec = sector(nxt)
        if len(sec) < ssz:
            break
        difat.extend(struct.unpack_from("<%dI" % (ssz // 4 - 1), sec, 0))
        nxt = struct.unpack_from("<I", sec, ssz - 4)[0]
        seen += 1

    fat: list = []
    for sect in difat[:n_fat]:
        if sect >= max_sectors:
            continue
        sec = sector(sect)
        if len(sec) < ssz:
            continue
        fat.extend(struct.unpack_from("<%dI" % (ssz // 4), sec, 0))

    def chain(start: int, size: int | None = None) -> bytes:
        out = bytearray()
        cur, guard = start, 0
        limit = len(fat) + 1
        while cur not in (_ENDOFCHAIN, _FREESECT) and cur < len(fat) and guard < limit:
            out += sector(cur)
            cur = fat[cur]
            guard += 1
            if size is not None and len(out) >= size:
                break
        return bytes(out[:size]) if size is not None else bytes(out)

    entries = []
    dirdata = chain(dir_start)
    for off in range(0, max(0, len(dirdata) - 127), 128):
        e = dirdata[off:off + 128]
        nlen = struct.unpack_from("<H", e, 0x40)[0]
        name = e[:max(nlen - 2, 0)].decode("utf-16-le", "replace")
        entries.append((
            name,
            e[0x42],
            struct.unpack_from("<I", e, 0x74)[0],
            struct.unpack_from("<Q", e, 0x78)[0],
        ))

    root = next((e for e in entries if e[1] == 5), None)
    mini_stream = chain(root[2], root[3]) if root else b""
    mini_fat: list = []
    if n_mini_fat and mini_fat_start < max_sectors:
        mf = chain(mini_fat_start)
        mini_fat = list(struct.unpack_from("<%dI" % (len(mf) // 4), mf, 0))

    def mini_chain(start: int, size: int) -> bytes:
        out = bytearray()
        cur, guard = start, 0
        limit = len(mini_fat) + 1
        while cur not in (_ENDOFCHAIN, _FREESECT) and cur < len(mini_fat) and guard < limit:
            out += mini_stream[cur * mssz:(cur + 1) * mssz]
            cur = mini_fat[cur]
            guard += 1
            if len(out) >= size:
                break
        return bytes(out[:size])

    found = {}
    for name, typ, start, size in entries:
        if typ != 2 or name not in wanted:
            continue
        found[name] = mini_chain(start, size) if size < mini_cutoff else chain(start, size)
    return found


def _clean_doc_text(raw: str) -> str:
    """Turn Word's in-text control codes into the text a reader would see."""
    out: list = []
    in_instruction = False
    pending_cells = 0
    for ch in raw:
        code = ord(ch)
        if code == 0x13:
            in_instruction = True
            continue
        if code == 0x14:
            in_instruction = False
            continue
        if code == 0x15:
            in_instruction = False
            continue
        if in_instruction:
            continue
        if code == 0x07:
            # One ends a cell, two in a row end the row.
            pending_cells += 1
            continue
        if pending_cells:
            out.append("\n" if pending_cells > 1 else "\t")
            pending_cells = 0
        if code in _DOC_DROP:
            out.append(_DOC_DROP[code])
            continue
        if code < 0x20 and ch not in "\t\n":
            continue
        out.append(ch)
    if pending_cells:
        out.append("\n")
    text = "".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def _extract_doc_native(path: str) -> str | None:
    """Pure-Python Word 97-2003 (.doc) text extractor — no external deps.

    `B102`: `.docx` had two extractors and `.doc` — the format people mean when
    they say "a Word document" — had none, because markitdown refuses it and
    the decode gate correctly refuses an OLE2 container.

    Word 97 keeps the document text in the ``WordDocument`` stream but does not
    keep it in one run: the piece table (``CLX``) in the table stream says which
    byte range holds which character range and whether that piece is
    CP1252-compressed or UTF-16. Extracting without it works until the first
    edit-and-save, which is why "run strings(1) over it" is not an extractor.
    Everything here is a bounded read of structures the file itself describes.

    Loses formatting, footnotes, headers and images; keeps the prose, the table
    cell text and the visible half of fields — the same trade
    ``_extract_docx_native`` makes.
    """
    import struct

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    streams = _cfb_streams(data, {"WordDocument", "1Table", "0Table"})
    wd = streams.get("WordDocument")
    if not wd or len(wd) < 0x200:
        return None
    u16 = lambda o: struct.unpack_from("<H", wd, o)[0]  # noqa: E731
    u32 = lambda o: struct.unpack_from("<I", wd, o)[0]  # noqa: E731
    try:
        if u16(0x00) != 0xA5EC:  # wIdent: not a Word binary document
            return None
        flags = u16(0x0A)
        if (flags >> 8) & 1:  # fEncrypted
            logger.info("%s is an encrypted .doc; no text extracted", path)
            return None
        table = streams.get("1Table" if (flags >> 9) & 1 else "0Table")
        if not table:
            return None
        # Walk the FIB by its own length fields rather than hard-coded offsets,
        # so a Word 2000/2002 FIB (which grows fibRgFcLcb) still resolves.
        csw = u16(0x20)
        off = 0x22 + csw * 2
        cslw = u16(off)
        fib_rg_lw = off + 2
        ccp_text = u32(fib_rg_lw + 0x0C)
        blob = fib_rg_lw + cslw * 4 + 2
        fc_clx = u32(blob + 33 * 8)
        lcb_clx = u32(blob + 33 * 8 + 4)
    except struct.error:
        return None
    if lcb_clx <= 0 or fc_clx + lcb_clx > len(table):
        return None

    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    try:
        while i < len(clx) and clx[i] == 0x01:  # Prc: character properties, skip
            i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
        if i >= len(clx) or clx[i] != 0x02:  # Pcdt marker
            return None
        lcb = struct.unpack_from("<I", clx, i + 1)[0]
        pcdt = clx[i + 5:i + 5 + lcb]
        n_pieces = (len(pcdt) - 4) // 12
        if n_pieces <= 0:
            return None
        cps = struct.unpack_from("<%dI" % (n_pieces + 1), pcdt, 0)
    except struct.error:
        return None

    base = 4 * (n_pieces + 1)
    chunks: list = []
    for k in range(n_pieces):
        try:
            fc = struct.unpack_from("<I", pcdt, base + k * 8 + 2)[0]
        except struct.error:
            break
        n_chars = cps[k + 1] - cps[k]
        if n_chars <= 0:
            continue
        if fc & 0x40000000:  # fCompressed: one CP1252 byte per character
            start = (fc & 0x3FFFFFFF) >> 1
            chunks.append(wd[start:start + n_chars].decode("cp1252", "replace"))
        else:
            start = fc & 0x3FFFFFFF
            chunks.append(wd[start:start + n_chars * 2].decode("utf-16-le", "replace"))
    text = "".join(chunks)
    if ccp_text:
        # Everything past ccpText is footnotes, headers and annotations, which
        # arrive without their anchors and read as noise.
        text = text[:ccp_text]
    cleaned = _clean_doc_text(text)
    return cleaned or None


def _run_native(extractor, path: str) -> str | None:
    """Call a bundled extractor and never let it take the message down.

    These readers walk attacker-supplied containers: a deeply nested document
    part reaches Python's recursion limit, a truncated one reaches a slice that
    is not there. Every path through them already returns ``None`` for "cannot
    read this", and an unexpected exception means the same thing, so it is
    logged and answered the same way — the caller then emits a banner naming the
    file instead of raising out of ``build_user_content``.
    """
    try:
        return extractor(path)
    except Exception as e:  # noqa: BLE001 - the banner is the answer for all of them
        logger.warning("native extractor failed on %s: %s", path, e)
        return None


_NATIVE_EXTRACTORS = {
    ".docx": _extract_docx_native,
    ".odt": _extract_odf_native,
    ".doc": _extract_doc_native,
}


def convert_to_markdown(path: str) -> str | None:
    """Convert a document to Markdown text via markitdown.

    Returns the extracted Markdown, or ``None`` if markitdown is unavailable or
    the conversion fails — callers degrade gracefully rather than erroring.

    Three shapes, one entry point: `.docx` prefers markitdown and falls back to
    the bundled ``<w:t>`` reader, `.odt`/`.doc` go straight to their bundled
    readers (markitdown refuses both — `B102`), and `.pptx`/`.xlsx`/`.xls`/
    `.epub` still need markitdown installed.
    """
    ext = os.path.splitext(path)[1].lower() if isinstance(path, str) else ""
    native = _NATIVE_EXTRACTORS.get(ext)
    if ext not in MARKITDOWN_EXTS:
        # `.odt` and `.doc`: markitdown raises UnsupportedFormatException on both
        # (measured, markitdown 0.1.6), so asking it first would only cost a
        # traceback. The bundled reader is the extractor for these.
        if native is None:
            logger.warning("no extractor for %s", path)
            return None
        text = _run_native(native, path)
        if not text:
            logger.warning("native extractor found no text in %s", path)
        return text or None
    try:
        markitdown_cls = load_markitdown()
    except RuntimeError:
        if native is not None:
            text = _run_native(native, path)
            if text:
                logger.info(
                    "markitdown not installed — used the native %s extractor for %s",
                    ext, path,
                )
                return text
        logger.warning("markitdown not installed; cannot extract %s", path)
        return None
    try:
        result = markitdown_cls().convert(path)
        text = getattr(result, "text_content", None)
        if text is None:
            text = getattr(result, "markdown", None)
        return text
    except Exception as e:
        logger.warning("markitdown failed to convert %s: %s", path, e)
        if native is not None:
            # Installed but unhappy — a corrupt part, a format version it does
            # not know. The bundled reader is a second opinion, not a fallback
            # only for the uninstalled case.
            return _run_native(native, path) or None
        return None
