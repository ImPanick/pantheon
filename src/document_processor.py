# SPDX-License-Identifier: AGPL-3.0-or-later
# src/document_processor.py
"""Document processing: PDF/OCR extraction, text file handling, image VL analysis, user content building."""

import os
import logging
import mimetypes
import base64
import tempfile
from typing import List, Dict, Any

from src.llm_core import llm_call
from src.markitdown_runtime import MARKITDOWN_EXTS
from src.pdf_runtime import PDF_EXTS

logger = logging.getLogger(__name__)

MAX_INLINE_ATTACHMENT_CHARS = 24000
MIN_INLINE_ATTACHMENT_SLICE = 500

# The extensions the text arm of ``build_user_content`` can actually read.
# One register per extractor: this one, ``MARKITDOWN_EXTS`` (Office/EPUB) and
# ``PDF_EXTS``. Nothing else may spell a fourth copy — see ``INGESTIBLE_EXTS``.
TEXT_EXTS = frozenset({
    ".txt", ".py", ".html", ".htm", ".md", ".json", ".csv", ".log", ".js", ".nix",
    ".bash", ".c", ".cpp", ".css", ".go", ".h", ".java", ".jsx", ".php", ".rb",
    ".rs", ".sh", ".sql", ".ts", ".tsx", ".xml", ".yaml", ".yml",
})

# Every extension chat ingest has an extractor for, and therefore exactly the
# set ``upload_handler.is_document_file`` accepts — it imports this name rather
# than keeping a list of its own.
#
# `B05` claimed the rule was ``document_extensions ⊆ _is_text_file`` and asked
# for a test. Measured, that rule is one we must never satisfy: the 34 accepted
# extensions minus the 28 text ones are ``.docx .epub .pdf .pptx .xls .xlsx``,
# and putting ``.pdf`` in the text arm would feed the model a binary stream.
# The rule that is actually true is this three-way union — 28 + 5 + 1 = 34, with
# zero slack — and stating it as a union makes it an identity that cannot drift,
# rather than a subset relation a checker has to police (`Law 13`).
#
# This is a superset of, not a substitute for, the ``mime.startswith("text/")``
# arm at the dispatch below: a libmagic sniff can still rescue an extension no
# register names. A set alone can never model that, which is the other reason
# `B05`'s "three-line test" would not have been a proof.
INGESTIBLE_EXTS = TEXT_EXTS | MARKITDOWN_EXTS | PDF_EXTS

# How much of a file the decode probe below reads before answering.
TEXT_SNIFF_BYTES = 8192


def looks_like_text(path: str, probe_bytes: int = TEXT_SNIFF_BYTES) -> bool:
    """True when a bounded prefix of *path* reads as text.

    `B76`: 26 extensions a person can upload were measured delivering **zero
    bytes** to the model. **24 of them are text** — `.markdown .tsv .rst .toml
    .ini .conf .env .ipynb .patch .diff .cfg .properties .swift .kt .lua .pl
    .vue .scss .less .gradle .ps1 .r .svg .rtf` — and `_process_text_file`
    could read every one today; the only thing stopping them was that no
    register spelled their suffix. (The other two, `.doc` and `.odt`, are
    genuinely binary containers and still get the banner.) Appending the 24 is
    the defect itself: the register has been extended twice already and the
    25th format arrives next month. The right question is whether the bytes
    decode; the registers keep their real job, which is picking *which*
    extractor, not *whether* to read.

    **This is not a new gate — it is `B02`'s, given a home.** The same probe
    already shipped as a closure named `_looks_like_text` inside
    `routes/email_routes.attachment_as_doc`, where nothing else could call it.
    So the product already decided a `.toml` attachment is text — it decided it
    for the mailbox and not for the composer. Lifting the closure to module
    scope and calling it from both is `Law 13`; writing a second probe next to
    it would have been `Law 14`. The email route's behaviour is unchanged
    because this is literally the function it used to define inline.

    Cost, bounded, because this reads bytes the caller would otherwise skip:
    ``build_user_content`` calls this **only when no register claimed the
    file** — i.e. only on the path whose current cost is a banner and zero
    reads. A file that reaches the model today is answered by
    ``is_document_file`` and never reaches this call, so the added I/O for
    every upload that works today is zero. For the rest it is one
    ``read(8192)`` — 8 KiB, once, no decode of the tail, no libmagic.

    Deliberately stdlib-only: ``detect_content_type`` is a libmagic call and
    python-magic ships only in the Docker image, so routing this through it
    would accept different files on a Docker install than on a pip/venv one.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(probe_bytes)
    except Exception as exc:
        logger.warning("text sniff failed for %s: %s", path, exc)
        return False
    if not head:
        return True  # empty file — nothing binary about it
    if b"\x00" in head:
        # NUL byte: the classic binary tell, and the check doing the real work
        # here — png/jpeg/zip/gzip prefixes all carry one. (A zip of ASCII
        # scores only 0.02 on the ratio below, so the ratio alone would let it
        # through.) Cost: UTF-16/32 text reads as binary and keeps the banner
        # it already gets today.
        return False
    decoded = head.decode("utf-8", errors="replace")
    if not decoded:
        return False
    # Backstop for binary carrying no NUL in its first KiBs: such a prefix is
    # mostly U+FFFD. `B02` measured 0.43 for NUL-free random bytes, so 0.30
    # clears binary. It does NOT clear all text: legacy single-byte prose
    # scores far higher than one number suggests — `B02` measured German 0.148,
    # Spanish 0.125, French 0.193, Icelandic 0.229, Polish cp1250 0.396 and
    # cp1251 Russian 0.815, and `B76` re-measured the last two at 0.412 and
    # 0.793 on different samples. The number moves with the text and the
    # verdict does not: everything past latin-1, and UTF-16/32 with it, keeps
    # the banner. That is the pre-existing behaviour and therefore safe, but it
    # makes this a UTF-8-and-Western-latin probe rather than a general one, and
    # widening it means sniffing the encoding — not raising this number (`B101`).
    return decoded.count("\ufffd") / len(decoded) <= 0.30


def upload_display_name(info: Dict[str, Any], fallback_path: str | None = None) -> str:
    """The one name a stored upload is known by.

    `B77`: the name the model is told it received, the name the dedup key must
    distinguish on, and the name `Content-Disposition` serves are the same
    question, and were answered in three places. This is that answer, derived
    once — ``upload_handler.save_upload`` keys on it and ``build_user_content``
    renders it, so a row the dedup considers identical is by construction one
    the model would be told the same thing about.

    Falls back to ``basename``, not the full path: the previous
    ``... or path`` in ``build_user_content`` put the server's upload directory
    layout into the prompt whenever a row carried no name.
    """
    for key in ("name", "original_name"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return os.path.basename(fallback_path or "") or ""


def _is_text_file(path: str) -> bool:
    """Check if file has text extension.

    This is an *ingestion gate*, not a security check. ``build_user_content``
    calls it as the fallback arm of ``mime.startswith("text/") or
    _is_text_file(path)``; anything that fails both falls through to
    ``_process_office_document``, which returns a banner for a non-markitdown
    format — zero bytes of the file reach the model.

    ``upload_handler.is_document_file`` admits 34 extensions, and the mime it is
    compared against is a libmagic sniff of the first 1 KiB with
    ``mimetypes.guess_type`` as the fallback (``upload_handler.detect_content_type``).
    python-magic ships only in the Docker image, so on a pip/venv install the
    ``mimetypes`` table alone decides — and it maps ``.go .bash .tsx .jsx .php``
    to ``None`` and ``.yaml .yml .rs .sql .rb .xml`` to non-``text/*`` types.
    Those eleven were silently discarded.

    Keep ``TEXT_EXTS`` a superset of the ``language_map`` / ``code_extensions``
    fence sets in ``_process_text_file`` below: an extension that has a fence
    label but never reaches the fencer is a contradiction. ``.h`` is there for
    determinism only — ``mimetypes.guess_type`` already resolves it to
    ``text/x-chdr``.

    Suffix matching, not ``os.path.splitext``: a bare dotfile named ``.md`` has
    no splitext extension but is still markdown, and it was accepted before the
    set was lifted out of this function.
    """
    return any(path.lower().endswith(ext) for ext in TEXT_EXTS)


def _process_text_file(path: str, display_name: str | None = None) -> str:
    """Process text file with enhanced formatting and metadata.

    *display_name* is the name the user attached the file under. Without it
    this function read both the header and the fence language off the **stored**
    path, which is ``<uuid32>.md`` — so the model was told ``=== File:
    310f424428ee47c3b4f2794eb061de3b.md ===`` for every text attachment ever
    sent (measured through the real ``save_upload`` → ``build_user_content``
    path). That is the same defect `B77` names for the dedup case, except it
    fired on *every* upload, not only on a hash collision.
    """
    language_map = {
        ".py": "python", ".js": "javascript", ".html": "html", ".htm": "html", ".css": "css",
        ".json": "json", ".md": "markdown", ".txt": "text", ".csv": "csv",
        ".log": "log", ".sh": "bash", ".bash": "bash", ".nix": "nix",
        ".yml": "yaml", ".yaml": "yaml",
        ".xml": "xml", ".sql": "sql", ".cpp": "cpp", ".c": "c",
        ".java": "java", ".go": "go", ".rs": "rust", ".php": "php",
        ".rb": "ruby", ".ts": "typescript", ".jsx": "javascript", ".tsx": "typescript",
    }

    # Name and language both come from what the user called the file, falling
    # back to the stored path. They must come from the same string or the
    # `[Type: …]` label contradicts the filename printed one line above it.
    filename = os.path.basename(display_name or path)
    _, ext = os.path.splitext(filename.lower())
    if not ext:
        _, ext = os.path.splitext(path.lower())
    language = language_map.get(ext, "text")
    max_len = 30000 if ext != ".log" else 10000

    try:
        from src.personal_docs import read_text_file
        content = read_text_file(path)
    except Exception:
        try:
            with open(path, "rb") as f:
                raw_data = f.read()
            try:
                content = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                from charset_normalizer import detect
                encoding = (detect(raw_data) or {}).get("encoding") or "utf-8"
                content = raw_data.decode(encoding, errors="replace")
        except Exception as e:
            logger.error(f"Failed to read file {path}: {e}")
            return "\n\n[Failed to read attached file]"

    try:
        file_size = os.path.getsize(path)
        size_str = f"{file_size:,}"
    except OSError:
        size_str = "unknown"

    lines = content.split("\n")
    line_count = len(lines)
    content_length = len(content)
    truncated = False

    if content_length > max_len:
        truncation_point = max_len
        search_range = min(100, content_length - max_len)
        for i in range(search_range):
            if truncation_point + i >= content_length:
                break
            if content[truncation_point + i] == "\n":
                truncation_point += i
                truncated = True
                break
        else:
            for i in range(min(100, truncation_point)):
                if content[truncation_point - i] == "\n":
                    truncation_point -= i
                    truncated = True
                    break
        content = content[:truncation_point]
        truncated = True

    header = f"\n=== File: {filename} ===\n"
    header += f"[Type: {language}, Lines: {line_count}, Size: {size_str} bytes]"

    code_extensions = {
        ".py", ".js", ".html", ".htm", ".css", ".json", ".md", ".sh", ".bash", ".nix",
        ".yml", ".yaml", ".xml", ".sql", ".cpp", ".c", ".java", ".go", ".rs", ".php", ".rb",
        ".ts", ".jsx", ".tsx",
    }
    if ext in code_extensions:
        code_block = f"```{language}\n{content}"
        if truncated:
            code_block += "\n[Truncated]"
        code_block += "\n```"
        return header + "\n\n" + code_block
    else:
        result = header + "\n\n" + content
        if truncated:
            result += "\n[Truncated]"
        return result


def _process_pdf(path: str, owner: str | None = None) -> str:
    """Process PDF file with text extraction (pypdf). Uses VL model for image-heavy pages."""
    try:
        from pypdf import PdfReader
        pdf_text = ""
        reader = PdfReader(path)

        for page_num, page in enumerate(reader.pages):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pdf_text += f"\n\n[Page {page_num + 1} text]:\n{page_text}"

            # For pages with images but little text, try VL model
            try:
                images = list(page.images)
            except Exception:
                images = []
            if images and len(page_text) < 50:
                for img_index, img in enumerate(images[:3]):  # cap at 3 images per page
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            temp_img_path = tmp.name
                        try:
                            img.image.save(temp_img_path, "PNG")  # pypdf -> PIL image
                            ocr_text = analyze_image_with_vl(temp_img_path, owner=owner)
                            if ocr_text and "unavailable" not in ocr_text.lower():
                                pdf_text += f"\n\n[Page {page_num + 1} image {img_index + 1} text]: {ocr_text}"
                        finally:
                            try:
                                os.unlink(temp_img_path)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.warning(f"Failed to analyze image in PDF: {e}")
                        continue

        if pdf_text:
            if len(pdf_text) > 15000:
                pdf_text = pdf_text[:15000] + "\n[PDF content truncated]"
            return f"\n\n[PDF content]:{pdf_text}"
        else:
            return "\n\n[PDF processed but no readable content found]"

    except Exception as e:
        return f"\n\n[PDF processing failed: {str(e)}]"


def _truncate_inline(text: str, limit: int = 15000) -> tuple[str, str]:
    """Cap inline document text so a huge file can't blow the model's context."""
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit], "\n[…truncated for inline context.]"
    return text, ""


def _fit_inline_attachment_text(
    text: str,
    remaining: int,
    display_name: str,
) -> tuple[str, int]:
    """Fit extracted attachment text into the shared inline attachment budget.

    Individual processors already cap single files, but multi-file batches can
    still add N capped bodies to one user turn. Keep the first files readable,
    keep later files visible by name, and mark exactly where inline content was
    reduced so the model does not silently miss attachments.
    """
    text = text or ""
    if len(text) <= remaining:
        return text, remaining - len(text)

    name = os.path.basename(display_name or "attachment")
    if remaining < MIN_INLINE_ATTACHMENT_SLICE:
        return (
            f"\n\n[Attachment omitted from inline context: {name}. "
            f"The {MAX_INLINE_ATTACHMENT_CHARS:,}-character shared inline "
            "attachment budget was already used by earlier attachments. Ask "
            "to inspect this file specifically if more detail is needed.]",
            0,
        )
    marker = (
        f"\n\n[Attachment content truncated: {name}. "
        f"Only {remaining:,} characters of this attachment fit within "
        f"the {MAX_INLINE_ATTACHMENT_CHARS:,}-character shared inline "
        "attachment budget. Ask to inspect this file specifically if more "
        "detail is needed.]"
    )
    return text[:remaining] + marker, 0


def _process_office_document(
    path: str,
    display_name: str,
    session_id: str | None = None,
    auto_opened_docs: list[Dict[str, Any]] | None = None,
    owner: str | None = None,
) -> str:
    """Extract an Office/EPUB document to Markdown via the optional markitdown dep.

    Falls back to a friendly banner when markitdown is unavailable or finds no
    text, so a missing optional dependency never breaks the chat path. When a
    session_id is provided AND the extraction succeeded, the FULL text is also
    saved as a Document so the agent can page through it via
    `manage_documents action=read offset=…` after the inline copy is capped.
    """
    from src.markitdown_runtime import (
        is_markitdown_format,
        convert_to_markdown,
        load_markitdown,
    )

    if not is_markitdown_format(path):
        # Sibling of the "no extractor" banner in build_user_content, reached by
        # the other route into this state: `is_document_file` said yes on the
        # *mime* half (a libmagic sniff or the mimetypes table), so no register
        # named the extension and nothing here can read it. Same rule — name the
        # file and say the contents are missing, rather than a bare noun phrase
        # that reads like a successful attachment.
        return (
            f"\n\n[Attached file: {display_name} — contents not read. It was "
            f"classified as a document by its MIME type, but no extractor covers "
            f"this file type, so nothing from the file is in this message.]"
        )

    markdown = convert_to_markdown(path)
    if markdown and markdown.strip():
        title = os.path.splitext(os.path.basename(path))[0]
        body, marker = _truncate_inline(markdown)

        # Persist the full extracted text as a Document. The agent's existing
        # manage_documents tool can then read past the inline cap with offset.
        doc_id = None
        if session_id:
            try:
                from src.office_doc import create_office_document
                doc_id = create_office_document(
                    session_id=session_id,
                    upload_id=os.path.basename(path),
                    title=title,
                    body_text=markdown,
                )
                if doc_id and auto_opened_docs is not None:
                    from src.database import SessionLocal, Document
                    _db = SessionLocal()
                    try:
                        _d = _db.query(Document).filter(Document.id == doc_id).first()
                        if _d:
                            auto_opened_docs.append({
                                "doc_id": _d.id,
                                "title": _d.title,
                                "language": _d.language,
                                "content": _d.current_content,
                                "version": _d.version_count,
                            })
                    finally:
                        _db.close()
            except Exception as e:
                logger.warning("Office auto-doc creation failed for %s: %s", path, e)

        # Upgrade the truncation marker with a hint pointing at the full doc so
        # the agent knows it can read the rest.
        if doc_id and marker:
            marker = (
                f"\n[…truncated for inline context — full {len(markdown):,} chars "
                f"saved as document `{doc_id}`. Use `manage_documents` with "
                f"action=read, document_id={doc_id}, offset=<N> to page through.]"
            )

        return f"\n\n[Document content — {title}]:\n{body}{marker}"

    # No content: tell the user whether to install the optional dep or whether
    # the document simply had no extractable text.
    try:
        load_markitdown()
        return f"\n\n[Attached document: {display_name} — no extractable text found.]"
    except RuntimeError as exc:
        return f"\n\n[Attached document: {display_name} — {exc}]"


# Marker that _process_pdf prepends to extracted text.
_PDF_CONTENT_MARKER = "\n\n[PDF content]:"


def strip_pdf_content_marker(text: str) -> str:
    """Remove the leading ``[PDF content]:`` wrapper that ``_process_pdf`` adds.

    Uses ``str.removeprefix`` rather than ``str.lstrip(chars)``: ``lstrip``
    treats its argument as a *set of characters*, so ``lstrip("\\n[PDF content]:")``
    keeps chewing into the page text that follows the marker. For example
    ``"\\n\\n[PDF content]:\\n\\n[Page 1 text]:\\nto the board"`` would lose the
    leading "to" because 't' and 'o' are in the marker's character set.
    """
    return (text or "").removeprefix(_PDF_CONTENT_MARKER).strip()


def _load_vl_settings() -> dict:
    """Load admin settings from disk."""
    try:
        from src.settings import load_settings
        return load_settings()
    except Exception:
        return {}


def _resolve_vl_model(configured: str, owner: str | None = None) -> tuple:
    """Resolve the vision model to (url, model_id, headers).

    Uses admin-configured model if set, otherwise tries auto-detection
    of known vision-capable models across configured endpoints.
    """
    from src.ai_interaction import _resolve_model

    if configured:
        return _resolve_model(configured, owner=owner)

    # Auto-detect: try known vision-capable models in priority order
    candidates = [
        "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
        "claude-sonnet-4-5-20250929", "claude-opus-4-20250514",
        "gemini-2.0-flash", "gemini-2.5-pro",
        "llava", "pixtral", "qwen2-vl",
    ]
    for candidate in candidates:
        try:
            return _resolve_model(candidate, owner=owner)
        except (ValueError, Exception):
            continue

    raise ValueError("No vision model available")


def analyze_image_with_vl_result(image_path: str, owner: str | None = None) -> dict:
    """Analyze an image and return both text and the model that produced it."""
    logger.info(f"Analyzing image with VL model: {image_path}")
    try:
        settings = _load_vl_settings()
        if not settings.get("vision_enabled", True):
            return {"text": "[Vision is disabled — enable it in Settings → Vision]", "model": ""}
        vl_model = settings.get("vision_model", "")

        try:
            url, model_id, headers = _resolve_vl_model(vl_model, owner=owner)
        except ValueError:
            return {"text": "[No vision model configured — set one in Settings → Vision]", "model": vl_model or ""}

        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".webp": "webp"}
        img_format = mime_map.get(ext, "jpeg")

        vl_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in detail"},
                    {"type": "image_url", "image_url": {"url": f"data:image/{img_format};base64,{img_data}"}},
                ],
            }
        ]
        # Vision-specific fallback chain (Settings → Vision → Fallbacks). A
        # downed vision endpoint can fall through to the next configured model
        # — same shape as task/chat but its own list (`vision_model_fallbacks`).
        try:
            from src.endpoint_resolver import resolve_vision_fallback_candidates
            _vl_candidates = [(url, model_id, headers)] + resolve_vision_fallback_candidates(owner=owner)
        except Exception:
            _vl_candidates = [(url, model_id, headers)]

        last_err = None
        for i, (_url, _model, _headers) in enumerate([c for c in _vl_candidates if c and c[0] and c[1]]):
            try:
                description = llm_call(_url, _model, vl_messages, headers=_headers, timeout=120)
                logger.info("VL analysis complete with model %s", _model)
                return {"text": description, "model": _model}
            except Exception as e:
                last_err = e
                tag = "primary" if i == 0 else "candidate"
                logger.warning(f"[vision fallback] {tag} {_model} failed ({type(e).__name__}); trying next")
                continue
        raise last_err if last_err else RuntimeError("No vision model endpoint configured")

    except Exception as e:
        logger.error(f"VL model unavailable: {e}")
        return {"text": "[VL model unavailable - image not analyzed]", "model": ""}


def analyze_image_with_vl(image_path: str, owner: str | None = None) -> str:
    """Analyze an image using the admin-configured Vision-Language model."""
    return analyze_image_with_vl_result(image_path, owner=owner).get("text", "")


def build_user_content(
    text: str,
    attachment_ids: list[str] | None,
    upload_dir: str,
    upload_handler,
    session_id: str | None = None,
    auto_opened_docs: list[Dict[str, Any]] | None = None,
    owner: str | None = None,
    resolved_uploads: dict[str, Dict[str, Any]] | None = None,
) -> str | List[Dict[str, Any]]:
    """Build user content with attachments (text, images, audio, documents).

    If session_id is provided and an attached PDF contains AcroForm fields,
    a markdown Document is auto-created so the user can edit the form in the
    editor. When `auto_opened_docs` is supplied, an entry is appended for each
    such doc so the chat route can emit a `doc_update` SSE event and the
    frontend can switch to the new doc immediately.
    """
    content = [{"type": "text", "text": text}]
    inline_attachment_remaining = MAX_INLINE_ATTACHMENT_CHARS

    for fid in attachment_ids or []:
        upload_info = (resolved_uploads or {}).get(fid)
        if upload_info is None and hasattr(upload_handler, "resolve_upload"):
            upload_info = upload_handler.resolve_upload(fid, owner=owner)
        if upload_info is None:
            logger.warning(f"Attachment {fid} not found or not authorized")
            continue

        path = upload_info.get("path")
        if not path or not os.path.exists(path):
            logger.warning(f"Attachment {fid} path is missing")
            continue
        if hasattr(upload_handler, "_inside_upload_dir") and not upload_handler._inside_upload_dir(path):
            logger.warning(f"Attachment {fid} path is outside upload directory: {path}")
            continue
        if not hasattr(upload_handler, "_inside_upload_dir") and not upload_handler.inside_base_dir(path):
            logger.warning(f"Attachment {fid} path is outside base directory: {path}")
            continue

        _, ext = os.path.splitext(path.lower())
        mime = upload_info.get("mime") or mimetypes.guess_type(path)[0] or "application/octet-stream"
        display_name = upload_display_name(upload_info, path)

        is_image = upload_handler.is_image_file(display_name, mime)
        is_audio = False if is_image else upload_handler.is_audio_file(display_name, mime)
        # `B76`. Two questions, kept apart. The registers answer "which
        # extractor", and they are good at that. They were also answering "read
        # it at all", and at that they were wrong 26 times over: a `.toml` is
        # text whatever the register says, and appending the 26 only moves the
        # wrong answer to the 27th format.
        #
        # So ask the registers first, and only when none of them claims the
        # file, ask the bytes. Every `False if …` below short-circuits, so a
        # file that reaches the model today never pays for the probe: the added
        # read is confined to the path whose current behaviour is a banner and
        # zero bytes, and there it is one bounded `read(8192)`.
        is_doc = (
            False if (is_image or is_audio)
            else upload_handler.is_document_file(display_name, mime)
        )
        decoded_as_text = (
            False if (is_image or is_audio or is_doc) else looks_like_text(path)
        )

        if is_image:
            try:
                with open(path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                # Extensionless uploads (e.g. a pasted screenshot) have no ext,
                # so fall back to the resolved MIME subtype rather than emitting
                # an invalid "data:image/;base64," with an empty subtype.
                image_format = ext[1:] or (mime.split("/", 1)[1] if mime.startswith("image/") else "png")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{image_format};base64,{encoded_string}"},
                })
            except Exception as e:
                logger.error(f"Failed to encode image {fid}: {e}")
                if content and content[0]["type"] == "text":
                    content[0]["text"] += "\n\n[Image attached but could not be processed]"
                else:
                    content.insert(0, {"type": "text", "text": "[Image attached but could not be processed]"})

        elif is_audio:
            try:
                with open(path, "rb") as audio_file:
                    encoded_string = base64.b64encode(audio_file.read()).decode("utf-8")
                audio_format = ext[1:] or (mime.split("/", 1)[1] if mime.startswith("audio/") else "mpeg")
                content.append({
                    "type": "audio",
                    "audio": {"url": f"data:audio/{audio_format};base64,{encoded_string}"},
                })
            except Exception as e:
                logger.error(f"Failed to encode audio {fid}: {e}")
                if content and content[0]["type"] == "text":
                    content[0]["text"] += "\n\n[Audio attached but could not be processed]"
                else:
                    content.insert(0, {"type": "text", "text": "[Audio attached but could not be processed]"})

        elif is_doc or decoded_as_text:
            if mime == "application/pdf":
                extracted_text = None
                if session_id:
                    try:
                        from src.pdf_forms import has_form_fields, extract_fields
                        from src.pdf_form_doc import (
                            save_field_sidecar,
                            create_form_markdown_document,
                            create_plain_pdf_document,
                        )
                        title = os.path.splitext(os.path.basename(display_name))[0]
                        # Pull the PDF prose once — used as either intro_text
                        # (form path) or the doc body (plain path).
                        try:
                            pdf_body_text = strip_pdf_content_marker(_process_pdf(path, owner=owner))
                        except Exception:
                            pdf_body_text = None

                        is_form = False
                        try:
                            is_form = has_form_fields(path)
                        except Exception as e:
                            logger.warning(f"PDF form detection failed for {path}: {e}")

                        # Inline the PDF body in the chat content too. Without
                        # this, the assistant only saw the "PDF attached"
                        # banner and had no idea what was inside — even though
                        # the sidebar Document held the full extracted text.
                        # Cap the inline copy so a multi-hundred-page PDF
                        # doesn't blow the model's context; the sidebar still
                        # carries the full body for direct reference.
                        _MAX_INLINE_CHARS = 15000
                        body_for_chat = (pdf_body_text or "").strip()
                        truncated_marker = ""
                        if body_for_chat and len(body_for_chat) > _MAX_INLINE_CHARS:
                            body_for_chat = body_for_chat[:_MAX_INLINE_CHARS]
                            truncated_marker = (
                                "\n[…truncated for inline context — full text "
                                "available in the document viewer.]"
                            )

                        if is_form:
                            fields = extract_fields(path)
                            save_field_sidecar(path, fields)
                            doc_id = create_form_markdown_document(
                                session_id=session_id,
                                fields=fields,
                                upload_id=os.path.basename(path),
                                title=title,
                                intro_text=pdf_body_text,
                            )
                            if doc_id:
                                extracted_text = (
                                    f"\n\n[Form attached: {title} — {len(fields)} fields. "
                                    f"Opened in editor — edit the values there and use "
                                    f"the Export PDF button when done.]"
                                )
                                if body_for_chat:
                                    extracted_text += (
                                        f"\n\n[PDF content — {title}]:\n{body_for_chat}{truncated_marker}"
                                    )
                        else:
                            doc_id = create_plain_pdf_document(
                                session_id=session_id,
                                upload_id=os.path.basename(path),
                                title=title,
                                body_text=pdf_body_text,
                            )
                            if doc_id:
                                extracted_text = (
                                    f"\n\n[PDF attached: {title} — opened in document viewer.]"
                                )
                                if body_for_chat:
                                    extracted_text += (
                                        f"\n\n[PDF content — {title}]:\n{body_for_chat}{truncated_marker}"
                                    )

                        if doc_id and auto_opened_docs is not None:
                            from src.database import SessionLocal, Document
                            _db = SessionLocal()
                            try:
                                _d = _db.query(Document).filter(
                                    Document.id == doc_id
                                ).first()
                                if _d:
                                    auto_opened_docs.append({
                                        "doc_id": _d.id,
                                        "title": _d.title,
                                        "language": _d.language,
                                        "content": _d.current_content,
                                        "version": _d.version_count,
                                    })
                            finally:
                                _db.close()
                    except Exception as e:
                        logger.warning(f"PDF auto-doc creation failed for {path}: {e}")
                if extracted_text is None:
                    extracted_text = _process_pdf(path, owner=owner)
            elif mime.startswith("text/") or _is_text_file(path) or decoded_as_text:
                # `decoded_as_text` is the `B76` arm. It can only be true when
                # no register claimed the file, so it cannot divert anything
                # that has an extractor — it is reachable only from what used
                # to be the banner. `.svg` arrives here too, and reading its
                # source is the better answer than the image arm: it was in
                # neither `image_mime_types` nor any register, and a model that
                # sees the XML can edit it.
                extracted_text = _process_text_file(path, display_name)
            else:
                extracted_text = _process_office_document(
                    path,
                    display_name,
                    session_id=session_id,
                    auto_opened_docs=auto_opened_docs,
                    owner=owner,
                )

            extracted_text, inline_attachment_remaining = _fit_inline_attachment_text(
                extracted_text,
                inline_attachment_remaining,
                display_name,
            )
            if content and content[0]["type"] == "text":
                content[0]["text"] += extracted_text
            else:
                content.insert(0, {"type": "text", "text": extracted_text.lstrip()})
        else:
            # Reached when the upload is neither image, audio, a type any
            # extractor covers, nor bytes that decode as text. `B05` measured
            # `.markdown .tsv .rst .toml .ini .conf .env .ipynb .doc .odt .rtf`
            # landing here; `B76` moved the first eight out of it, because they
            # were text all along. What is left is the honest half — `.doc`
            # `.odt` `.rtf` and every genuine binary — where the answer is an
            # extractor or this banner, and this banner is true.
            # There is deliberately no upload type blocklist
            # (`upload_handler.save_upload`, D-2026-08-26-01), so the upload
            # succeeds and the chip renders; only the bytes are missing.
            #
            # Not rejected at upload, and not silently dropped either. Rejecting
            # would subtract a capability people use today: `.markdown` opens in
            # the document editor from the email library
            # (`static/js/emailLibrary.js`, `routes/email_routes.py`), and any
            # upload can be downloaded again afterwards. So the fix is the
            # banner, which is already persisted verbatim as the user's own
            # message (`routes/chat_helpers.add_user_message` stores
            # `user_content`; `routes/session_routes.py` returns `content` as-is)
            # and therefore already reaches the screen. What it did not do was
            # say anything: `[Attached non-text file]` names no file, so three
            # unreadable attachments produced three identical lines, and neither
            # the reader nor the model could tell that the contents were gone
            # rather than merely uninteresting.
            banner = (
                f"[Attached file: {display_name} — contents not read. No extractor "
                f"covers this file type, so nothing from the file is in this "
                f"message. The upload itself is intact and can be downloaded.]"
            )
            if content and content[0]["type"] == "text":
                content[0]["text"] += f"\n\n{banner}"
            else:
                content.insert(0, {"type": "text", "text": banner})

    has_media = any(item.get("type") in ["image_url", "audio"] for item in content if isinstance(item, dict))
    if not has_media and content:
        combined_text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                combined_text += item.get("text", "")
        return combined_text.strip()

    return content
