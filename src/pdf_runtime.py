# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small helpers for optional PDF runtime dependencies."""

# The extensions chat ingest routes down the PDF arm of
# ``document_processor.build_user_content``. Named here, next to the other PDF
# runtime facts, because ``upload_handler.is_document_file`` derives the set of
# extensions it accepts from this register plus ``markitdown_runtime.MARKITDOWN_EXTS``
# plus ``document_processor.TEXT_EXTS`` — one register per extractor, no
# hand-maintained fourth copy. This module stays import-leaf (no ``src.*``
# imports) so the upload layer can read it without pulling the LLM stack.
PDF_EXTS = frozenset({".pdf"})

PDF_VIEWER_PYMUPDF_MISSING = (
    "PDF viewer requires PyMuPDF. Install optional PDF dependencies with "
    "`pip install -r requirements-optional.txt` (PyMuPDF is AGPL-3.0)."
)


def load_pymupdf_for_pdf_viewer():
    """Return the PyMuPDF module, or raise a user-facing setup hint."""
    try:
        import fitz  # PyMuPDF, optional
    except ImportError as exc:
        raise RuntimeError(PDF_VIEWER_PYMUPDF_MISSING) from exc
    return fitz


def pdf_page_view_available() -> bool:
    """`P23-08` (DOCS-M-6). Whether this server can draw a PDF's pages.

    Read through `load_pymupdf_for_pdf_viewer` — the one test `render-pages`
    makes — and not cached: a missing module costs one path scan, and a test or
    an admin who installs it is believed at once. The document answer carries it
    as `can_render_pages`, so the editor shows the text without first asking
    `render-pages` for a 503 the server could have predicted (measured on
    `9560d50`: one 503 in the console per PDF opened).
    """
    try:
        load_pymupdf_for_pdf_viewer()
    except RuntimeError:
        return False
    return True


# `B1154` (f-import: `import-pdf` accepted any file). What a PDF looks like
# from its first bytes. The header is `%PDF-`; readers (pypdf, PyMuPDF, Acrobat)
# accept it anywhere in the first 1024 bytes, because some producers write a
# few bytes of junk first, so the probe looks there and no further.
PDF_MAGIC = b"%PDF-"
PDF_MAGIC_WINDOW = 1024

# What the first bytes say a file is, for the sentence a refusal gives. Only
# formats someone plausibly mistakes for a PDF — a scan saved as an image, an
# Office file — and nothing that would need a dependency to recognise.
_NOT_PDF_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "a PNG image"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"GIF87a", "a GIF image"),
    (b"GIF89a", "a GIF image"),
    (b"II*\x00", "a TIFF image"),
    (b"MM\x00*", "a TIFF image"),
    (b"PK\x03\x04", "a zip archive"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "a legacy Office file (.doc, .xls or .ppt)"),
)


def looks_like_pdf(head: bytes) -> bool:
    """True when *head* — a file's first bytes — carries a PDF header."""
    return PDF_MAGIC in (head or b"")[:PDF_MAGIC_WINDOW]


def not_a_pdf_reason(name: str, head: bytes) -> str:
    """The sentence a door gives for a file that is not a PDF.

    The verdict is the bytes' (``looks_like_pdf``) — a PDF with no extension
    is a PDF. This only words it: what the name says when it says something
    other than `.pdf`, otherwise what the first bytes say, when they say it.
    """
    import os

    shown = name or "This file"
    ext = os.path.splitext((name or "").lower())[1]
    if ext and ext not in PDF_EXTS:
        return f"{shown} is not a PDF: it is a {ext} file."
    what = next((label for sig, label in _NOT_PDF_SIGNATURES
                 if (head or b"").startswith(sig)), None)
    if what:
        return f"{shown} is not a PDF: it is {what}."
    return f"{shown} is not a PDF: its contents do not begin with a PDF header."
