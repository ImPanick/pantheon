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
