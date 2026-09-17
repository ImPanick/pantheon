# SPDX-License-Identifier: AGPL-3.0-or-later
# src/document_processor.py
"""Document processing: PDF/OCR extraction, text file handling, image VL analysis, user content building."""

import os
import re
import logging
import mimetypes
import base64
import codecs
import tempfile
import unicodedata
from typing import List, Dict, Any

from src.llm_core import llm_call
# ``MARKITDOWN_EXTS`` is no longer read here — `B102` moved this union onto
# ``OFFICE_EXTS`` — and is kept as a re-export because it has been importable
# from this module since `B05` and taking a name away is not this row's
# business (`Law 1`).
from src.markitdown_runtime import (  # noqa: F401
    MARKITDOWN_EXTS,
    NO_EXTRACTABLE_TEXT,
    OFFICE_EXTS,
)
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
# for a test. Measured, that rule is one we must never satisfy: the accepted
# extensions minus the 28 text ones are ``.doc .docx .epub .odt .pdf .pptx .xls
# .xlsx``, and putting ``.pdf`` in the text arm would feed the model a binary
# stream. The rule that is actually true is this union — 28 + 7 + 1 = 36, with
# zero slack — and stating it as a union makes it an identity that cannot drift,
# rather than a subset relation a checker has to police (`Law 13`).
#
# ``OFFICE_EXTS``, not ``MARKITDOWN_EXTS``: `B102` added bundled `.odt` and
# `.doc` readers, which are extractors markitdown does not have, so the office
# side is now two registers and this union asks for their sum. Anything with an
# extractor belongs here; anything here without one produces a banner instead of
# a document, which is the defect this identity exists to prevent.
#
# This is a superset of, not a substitute for, the ``mime.startswith("text/")``
# arm at the dispatch below: a libmagic sniff can still rescue an extension no
# register names. A set alone can never model that, which is the other reason
# `B05`'s "three-line test" would not have been a proof.
INGESTIBLE_EXTS = TEXT_EXTS | OFFICE_EXTS | PDF_EXTS

# ── `B232`: what this product can make of a file, answered once ─────────────
#
# The browser asked this question twice, with two hand-written extension
# regexes — 38 entries on the composer's "Import to document library" banner
# (`static/js/chat.js`) and 36 on *open this attachment as a document* — and
# both were wrong in both directions. Measured against these registers:
# **10 ingestible extensions were not offered** (`.bash .doc .docx .epub .nix
# .odt .pdf .pptx .xls .xlsx`, five of which the server has a bundled extractor
# for) and **9 offered extensions no register names** (`.conf .env .ini .less
# .sass .scss .svelte .toml .vue`, which reach the model only because
# ``looks_like_text`` rescues them — `B76`).
#
# **The naive fix is a trap and it is worth naming.** ``INGESTIBLE_EXTS`` is the
# union of three extractors, so handing it to the composer verbatim offers
# `.pdf`, `.docx`, `.xlsx`, `.pptx` and `.epub` to a code path that pre-reads
# the raw ``File`` **as text** — "offer to import a `.zip`" in another costume.
# The question is not one question. It is two, and they have different answers:
#
# * ``text`` — the bytes read as text, so a client may read them itself. This is
#   ``looks_like_text``, which is open-ended by design: `.kt`, `.toml` and
#   `.env` are text and no register names them.
# * ``document`` — the bytes are a container this product has an **extractor**
#   for, so the client must post the file and let the server convert it.
#   `.docx` is not text and is not binary either.
# * ``binary`` — neither, and the honest answer is a banner.
#
# One function, three answers, and every door reads it: the upload response
# carries it per file (``routes/upload_routes.api_upload``), the download route
# carries it as ``X-Upload-Kind`` for an attachment the browser already has an
# id for, and the composer and the attachment opener both read it instead of
# testing a name (`Law 13`, and `D-2026-08-26-06` — the backend is the single
# decision point).
INGEST_KIND_TEXT = "text"
INGEST_KIND_DOCUMENT = "document"
INGEST_KIND_BINARY = "binary"

# The extractor half of ``INGESTIBLE_EXTS``, named so a caller can ask for it
# without re-deriving the subtraction. Stated as the union it is rather than as
# a list, for the same reason ``INGESTIBLE_EXTS`` is.
EXTRACTED_EXTS = OFFICE_EXTS | PDF_EXTS


def ingest_kind(path: str, display_name: str | None = None) -> str:
    """``"text"``, ``"document"`` or ``"binary"`` for one stored file.

    *display_name* is the name the user attached it under; the stored path is
    ``<uuid32><ext>`` and keeps the suffix, so either works and the caller's own
    name wins when it has one (the same rule ``_process_text_file`` follows).

    Extractor first, bytes second. A `.docx` is a zip and a `.doc` is an OLE2
    container — ``looks_like_text`` says no to both, correctly — but the product
    reads them, so asking the extension first is what stops "we can read this"
    from being answered by a probe that can only see the first 8 KiB of a
    compressed archive.

    Bytes second is what keeps the answer open-ended. `B76`'s finding was that
    a file is readable when its BYTES decode, so a `.kt`, a `.toml` or a file
    with no extension at all is ``text`` here without anything being appended to
    a register — which is the property the two regexes in the browser could not
    have.
    """
    name = display_name or path or ""
    _, ext = os.path.splitext(name.lower())
    if not ext:
        _, ext = os.path.splitext((path or "").lower())
    if ext in EXTRACTED_EXTS:
        return INGEST_KIND_DOCUMENT
    if path and looks_like_text(path):
        return INGEST_KIND_TEXT
    return INGEST_KIND_BINARY


# Extensions whose language name is not simply the extension. Everything else
# derives: `.toml` is toml, `.swift` is swift, `.lua` is lua. `B100` measured a
# 27-entry `language_map` and a 24-entry `code_extensions` living side by side
# inside ``_process_text_file`` — two lists answering one question, which had to
# agree with each other and with ``TEXT_EXTS``, and whose agreement was asserted
# only by a sentence in a docstring. They did not agree: a `.toml` reached the
# model as ``[Type: text]`` with no fence while a byte-identical `.yaml` got
# ``[Type: yaml]`` inside a ```yaml fence, and `.h` — in ``TEXT_EXTS``, in
# neither list — was labelled `text` as well.
#
# Deriving from the suffix rather than listing it is what stops the list
# arriving again: `B76` opened chat ingest to every file whose *bytes* decode,
# so the set of extensions that reaches this function is open-ended by design
# and a closed list can only be wrong about the next one. What stays listed is
# the residue a suffix cannot answer — `.py` is not "py".
#
# ``mimetypes`` was measured as the alternative single source and is not one: on
# this interpreter it has no answer at all for `.toml .ini .conf .go .kt .swift
# .lua .vue .scss .less .gradle .ps1 .env .ipynb .cfg .properties .nix .jsx
# .tsx`, and it is wrong for `.rs` (``application/rls-services+xml``) and `.ts`
# (``text/vnd.trolltech.linguist``).
LANGUAGE_ALIASES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".htm": "html", ".md": "markdown", ".markdown": "markdown", ".mdx": "markdown",
    ".rb": "ruby", ".rs": "rust", ".kt": "kotlin", ".kts": "kotlin",
    ".pl": "perl", ".ps1": "powershell", ".sh": "bash", ".zsh": "bash",
    ".yml": "yaml", ".h": "c", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".cc": "cpp", ".cxx": "cpp", ".cs": "csharp", ".patch": "diff",
    ".ipynb": "json", ".txt": "text", ".text": "text",
}

# Languages whose content is prose, and which are therefore printed as-is rather
# than inside a code fence. This is the *only* input to the fence decision —
# there is no second list of "code extensions" left to fall out of step with the
# labels.
PROSE_LANGUAGES = frozenset({"text", "log"})

# A suffix is used as its own language name only when it reads like one. An
# unrecognised-but-plausible token (```toml, ```rst, ```gradle) degrades to a
# plain code block in every renderer, which is what the unfenced dump already
# was, plus a boundary; a suffix that is not a word at all falls back to `text`.
_LANGUAGE_TOKEN = re.compile(r"^[a-z][a-z0-9+#]{0,11}$")


def attachment_language(name: str) -> str:
    """The one word this product uses for what *name* is.

    `B100`: the ``[Type: ...]`` label and the code fence are the same question
    asked twice, so they are answered once, here. ``_process_text_file`` reads
    this and derives the fence from the answer (``PROSE_LANGUAGES``); nothing
    else may spell a second map (`Law 14`).

    Suffix-derived, alias-corrected. A file with no extension, or one whose
    suffix is not a word, is ``text`` — the same answer the old map's
    ``.get(ext, "text")`` gave it.
    """
    lowered = (name or "").lower()
    _, ext = os.path.splitext(lowered)
    if not ext and lowered.startswith("."):
        # A bare dotfile: ``.md`` has no splitext extension but is still
        # markdown, and ``_is_text_file`` has always accepted it by suffix. The
        # two answers agree now.
        ext = os.path.basename(lowered)
    if not ext:
        return "text"
    alias = LANGUAGE_ALIASES.get(ext)
    if alias:
        return alias
    token = ext[1:]
    return token if _LANGUAGE_TOKEN.match(token) else "text"


# How much of a file the decode probe below reads before answering.
TEXT_SNIFF_BYTES = 8192

# Byte-order marks, longest first: the UTF-32 marks begin with the UTF-16 ones,
# so testing UTF-16 first would read a UTF-32 file as UTF-16 and get noise. A
# BOM is a file stating its own encoding — `B101`'s "free first half".
# The codec names are the BOM-consuming ones on purpose: ``utf-16`` reads the
# mark, takes the endianness from it and drops it, where ``utf-16-le`` would
# leave a U+FEFF sitting in front of the first word of the document.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

# Share of U+FFFD a UTF-8 decode may carry and still count as text. `B02`
# measured 0.43 for NUL-free random bytes, so 0.30 clears binary.
_MAX_REPLACEMENT_RATIO = 0.30

# Share of control characters a *detected* legacy encoding may carry. Every
# single-byte codec maps almost every byte to something, so "it decoded" is not
# evidence on its own; C0/C1 controls are what real prose does not contain.
_MAX_CONTROL_RATIO = 0.02


def _replacement_ratio(decoded: str) -> float:
    return decoded.count("\ufffd") / len(decoded) if decoded else 1.0


def _control_ratio(decoded: str) -> float:
    if not decoded:
        return 1.0
    bad = sum(
        1 for ch in decoded
        if (ord(ch) < 0x20 and ch not in "\t\n\r\f\v") or 0x7F <= ord(ch) <= 0x9F
    )
    return bad / len(decoded)


def _detect_encoding(head: bytes) -> str | None:
    """``charset_normalizer``'s answer for *head*, or ``None``.

    The one call site for the dependency, so the probe and the reader ask it
    the same way. Import-guarded: ``charset-normalizer`` is a hard requirement
    (``requirements.txt``), but a sniff that cannot run must answer "no idea"
    rather than raise.
    """
    try:
        from charset_normalizer import detect
        return (detect(head) or {}).get("encoding") or None
    except Exception as exc:  # pragma: no cover - dependency missing or broken
        logger.warning("encoding sniff unavailable: %s", exc)
        return None


def _is_wide_encoding(name: str) -> bool:
    """True for the UTF-16/32 family, whatever spelling the detector used."""
    return name.lower().replace("-", "_").startswith(("utf_16", "utf_32"))


# The multi-byte (CJK) codec families, by the prefixes ``charset_normalizer``
# spells them with. What they have in common — and what makes them different
# from every single-byte legacy codec — is that they **regroup** the bytes: two
# input bytes become one character, and for Big5, Shift-JIS and the GB family a
# *trail* byte may legally be an ASCII byte, so an ASCII letter sitting after a
# high byte is swallowed into a CJK ideograph. A wrong single-byte guess gives
# the right words with the wrong accents; a wrong multi-byte guess gives a
# different number of characters in a different script.
_MULTIBYTE_PREFIXES = (
    "big5", "gb", "euc", "shift", "cp932", "cp936", "cp949", "cp950",
    "johab", "iso2022", "hz", "utf_7",
)


def _is_multibyte_encoding(name: str) -> bool:
    """True for a codec that groups several bytes into one character."""
    return name.lower().replace("-", "_").startswith(_MULTIBYTE_PREFIXES)


# How many bytes a multi-byte guess has to be about before it is evidence.
#
# `B201` measured `charset_normalizer` answering **Big5** for the 11 bytes of
# ``"сервер порт"`` in cp1251 — a decode with no replacement characters and no
# control characters, so it beat UTF-8 on both of `B101`'s comparisons and the
# file arrived as ``'鼫謼歑 瀁貗'``. The same text at 21 bytes is identified
# correctly, and the row's own sentence is that the boundary is sample size and
# not codec.
#
# 24 is measured, not chosen. Over eleven real prose samples in cp1251, cp1250,
# cp1253, cp1254, cp1255, latin-1, Big5, GB2312, Shift-JIS and EUC-KR, truncated
# at every length from 4 to 48 bytes and compared against the true decode:
# **a multi-byte answer about fewer than 24 bytes was right 22 times and wrong
# 59** — worse than a coin flip — while at 24 bytes and above it was right 44
# times and wrong 20. Below the floor the guess is discarded and the file falls
# to the UTF-8 floor below, which for a legacy-encoded file means the honest
# refusal `B162`'s skip-with-a-reason contract already has a slot for.
#
# **What this costs, stated rather than implied**: a genuine CJK file shorter
# than 24 bytes — roughly a dozen ideographs, with no BOM and no registered
# extension — stops being rescued and gets the banner. That is 22 of the 81
# short-sample rescues in the sweep. It is deliberate: the other 59 were
# mojibake, and there is nothing in a sample that small that tells the two
# apart. A single-byte guess is untouched at any size, because it cannot do
# this kind of damage — it maps one byte to one character, so the worst it
# produces is the right words with the wrong accents.
_MIN_MULTIBYTE_SAMPLE = 24

# ── `B280`: the guess is wrong above the floor too, and the floor cannot reach it ──
#
# `B201` bought what a sample floor can buy. What it left is content-dependent,
# so no threshold on sample size touches it. Measured on the tree as it stood:
# the 58-byte cp1250 Polish pangram ``Zażółć gęślą jaźń pchnąć w tę łódź jeża
# lub ośm skrzyń fig`` is answered ``Windows-1252`` and arrives as
# ``Za¿ó³æ gêœl¹ jaŸñ pchn¹æ w tê ³ódŸ je¿a lub oœm skrzyñ fig`` — every
# Polish-specific letter replaced — while 34 bytes of Big5 are answered
# ``johab`` and arrive as Hangul. Both decode with no replacement characters and
# no control characters, so `B101`'s two comparisons have nothing to say.
#
# **Two levers, both measured, and only one of them works.**
#
# 1. **A file that declares its own encoding is not a guess** (``_DECLARED_*``
#    below). This is the ``_BOMS`` rule one step out: an XML declaration, an
#    HTML ``meta charset`` and a Python/Emacs coding cookie are the file saying
#    what it is, in the first bytes, in a grammar that predates every detector.
#    Taken only when the named codec exists AND decodes the prefix at least as
#    cleanly as UTF-8 did, so a stale or hostile declaration cannot make the
#    reader worse than it already was.
#
# 2. **A wrong single-byte guess is visible in the shape of its own output.**
#    Every single-byte codec maps every byte to *something*, which is why "it
#    decoded" is not evidence — but what it maps them to is evidence. The cp1252
#    reading of cp1250 Polish is ``Za¿ó³æ gêœl¹``: an inverted question mark and
#    a superscript three, **inside words**. That last part is the whole rule and
#    the first attempt at this row got it wrong by leaving it out.
#
#    ``_word_interior_symbols`` counts non-ASCII characters that are not letters
#    and sit between two alphanumerics. Real prose never does that in any
#    script. A *legitimately* symbol-heavy file does — a DOS box-drawing
#    diagram, a price list of ``£ ¥ ¤ ½``, a table of ``°C ± µ`` — but it does it
#    between **spaces**, which is why counting symbols alone was not a rule:
#    measured, a scoring of "how many of the non-ASCII characters are letters"
#    re-read ``Preis: 45,00 £ · 50,00 ¥`` as Thai, because a codec that maps
#    those bytes to letters scores perfectly by destroying them. Requiring the
#    symbol to be *inside a word* leaves every one of those files alone.
#
#    The choice is made over ``charset_normalizer.from_bytes``'s **ranked**
#    candidates rather than ``detect``'s single answer, because the right codec
#    was sitting second on the list and being thrown away.
#
# Measured over 891 rows — 29 real prose samples in 17 encodings across Latin,
# Cyrillic, Greek, Hebrew, Arabic, Han, Kana and Hangul, truncated at every
# length from the floor to the full sample — this is **22 corrections and 0
# regressions** (709 right → 731, 179 wrong → 157, refusals unchanged at 3), and
# the three symbol-heavy control files above keep the answer they had.
#
# **What it does not fix, measured rather than hoped.** The Big5→johab case is a
# *multi-byte* confusion: both readings are 100% letters with nothing inside a
# word, so this is blind to it. Three rules were built and measured against the
# same sweep and all three were rejected — see `B402`. A rule that refuses when
# a differently-scripted multi-byte rival is within ε chaos costs **98 correct
# answers to buy 16**, because the margin between the wrong top answer and the
# right runner-up (0.062–0.071 for Big5/johab) sits *inside* the margin range of
# the cases where the top answer is right (0.000–0.100). There is no threshold
# there, and saying so is the finding.
# Unicode general categories that a letter of some script has. Combining marks
# are letters for this purpose — a Vietnamese or Devanagari decode is letters
# plus marks and must not be scored down for it.
_LETTER_CATEGORIES = frozenset({"Ll", "Lu", "Lt", "Lm", "Lo", "Mn", "Mc", "Me"})

# A file stating its own encoding, in the three grammars that actually appear in
# the corpus this product ingests. Bounded to the first ``_DECLARATION_BYTES``
# because every one of them is required to be in the first line or two, and
# because a scan of 8 KiB for these would be reading the body for a header.
_DECLARATION_BYTES = 1024
_DECLARED_ENCODING_RES = (
    # <?xml version="1.0" encoding="windows-1250"?>
    re.compile(br"""<\?xml[^>]*?\bencoding\s*=\s*['"]([A-Za-z0-9_.:+-]+)['"]""",
               re.IGNORECASE),
    # <meta charset="big5">  /  <meta http-equiv=... content="text/html; charset=big5">
    re.compile(br"""<meta[^>]*?\bcharset\s*=\s*['"]?([A-Za-z0-9_.:+-]+)""",
               re.IGNORECASE),
    # # -*- coding: cp1251 -*-   /   # vim: set fileencoding=cp1251 :
    re.compile(br"""\b(?:coding[:=]\s*|fileencoding\s*=\s*)([A-Za-z0-9_.:+-]+)""",
               re.IGNORECASE),
)


def _is_letterish(ch: str) -> bool:
    return unicodedata.category(ch) in _LETTER_CATEGORIES


def _word_interior_symbols(decoded: str) -> int:
    """How many non-ASCII non-letters sit **inside** a word.

    The measurement behind `B280`'s second lever, and the one thing in this
    module that reads a decode rather than the bytes. A character counts when it
    is non-ASCII, is not a letter or a combining mark, and has an alphanumeric
    on *both* sides — ``Za¿ó³æ`` scores 2 and ``45,00 £ · 50,00 ¥`` scores 0.

    That distinction is the rule, not decoration. A price list, a DOS
    box-drawing diagram and a table of ``°C ± µ`` are full of symbols and are
    perfectly good text; what they never do is put one between two letters.
    Counting symbols without it was measured and re-read a German price list as
    Thai, because a codec that maps ``£¥¤½`` to letters looks *more* letter-like
    precisely by destroying them.

    ASCII is skipped because every candidate agrees about it, which would drown
    the signal in the 90% of a config file that is ``key = value``.
    """
    count = 0
    for i, ch in enumerate(decoded):
        if ord(ch) <= 0x7F or _is_letterish(ch):
            continue
        before = decoded[i - 1] if i else ""
        after = decoded[i + 1] if i + 1 < len(decoded) else ""
        if before and after and before.isalnum() and after.isalnum():
            count += 1
    return count


def _prose_plausibility(decoded: str) -> float:
    """Share of *decoded*'s non-ASCII characters that are letters.

    The tie-break behind ``_word_interior_symbols``, never the test on its own:
    an alternative has to both clear the interior-symbol count **and** be more
    letter-like overall before it is preferred, so a reading that merely swaps
    one alphabet for another cannot win on this alone.

    A decode with no non-ASCII characters at all scores 1.0: there is nothing to
    be implausible about, and it is the same answer every candidate gives.
    """
    high = [ch for ch in decoded if ord(ch) > 0x7F]
    if not high:
        return 1.0
    return sum(1 for ch in high if _is_letterish(ch)) / len(high)


def _canonical_codec(name: str) -> str | None:
    """The one spelling of *name*, or ``None`` when Python has no such codec.

    ``Windows-1252`` and ``cp1252`` are the same codec under two names —
    ``charset_normalizer.detect`` returns chardet's spelling and
    ``from_bytes`` returns Python's — so any comparison between the two has to
    go through here or it compares strings instead of codecs.
    """
    try:
        return codecs.lookup(name).name
    except (LookupError, TypeError, ValueError):
        return None


def _declared_encoding(head: bytes) -> str | None:
    """The encoding the file says it is, if it says so and the codec exists.

    `B280`, and this is the ``_BOMS`` rule rather than a new kind of guess: a
    BOM is a file declaring its encoding in bytes, and an XML declaration, an
    HTML ``meta charset`` and a coding cookie are the same declaration in text.
    The detector never reads them — it is a statistical classifier over the byte
    histogram — so this is information that exists in the file and is currently
    thrown away.

    Deliberately *not* trusted blindly: the caller checks that the declared
    codec decodes at least as cleanly as UTF-8 did before taking it, so a
    declaration left behind by a converter, or one written to make the reader
    misread the body, degrades to the answer we would have given anyway.
    """
    window = head[:_DECLARATION_BYTES]
    for pattern in _DECLARED_ENCODING_RES:
        match = pattern.search(window)
        if not match:
            continue
        name = match.group(1).decode("ascii", errors="replace")
        canonical = _canonical_codec(name)
        if canonical:
            return canonical
    return None


def _rank_encodings(head: bytes) -> list[str]:
    """Every encoding ``charset_normalizer`` thinks *head* could be, best first.

    ``_detect_encoding`` is ``from_bytes(...).best()`` with a rename — the
    ranking behind it is computed either way and then discarded, so this costs
    one extra call and no extra work per call. Import-guarded for the same
    reason ``_detect_encoding`` is: a ranking that cannot run answers "no
    alternatives" rather than raising.
    """
    try:
        from charset_normalizer import from_bytes
        return [match.encoding for match in from_bytes(head)]
    except Exception as exc:  # pragma: no cover - dependency missing or broken
        logger.warning("encoding ranking unavailable: %s", exc)
        return []


def _more_plausible_alternative(head: bytes, detected: str) -> str | None:
    """A candidate the detector ranked lower whose decode reads like prose.

    Only ever a **reordering of the detector's own list** — nothing is invented
    here, and a codec `charset_normalizer` did not put forward cannot be chosen.
    Three conditions, each of which is a way this could otherwise do harm:

    * *detected* must itself appear in the ranking. When it does not — which is
      what a test that stubs ``_detect_encoding`` produces, and what a future
      rename would produce — there is nothing to compare against and the answer
      is left alone.
    * the alternative must survive the same structural filters the caller
      applies to the detector's own answer: never a UTF-16/32 codec, and never
      a multi-byte codec about fewer than ``_MIN_MULTIBYTE_SAMPLE`` bytes
      (`B201`). Reordering must not be a door around either guard.
    * the detected reading must **put a symbol inside a word**, and the
      alternative must put none there while being more letter-like overall. A
      file that is legitimately symbol-heavy — DOS box-drawing, a price list of
      ``£¥¤½``, a table of ``°C ± µ`` — spells its symbols between spaces, so it
      scores zero here and this function never looks at it. That is the guard
      that keeps the rule away from files whose encoding nobody can name, and it
      is measured: without it, ``Preis: 45,00 £ · 50,00 ¥`` is re-read as Thai.
    """
    ranking = _rank_encodings(head)
    if len(ranking) < 2:
        return None
    canonical_detected = _canonical_codec(detected)
    canonical = [(_canonical_codec(name), name) for name in ranking]
    if canonical_detected is None or canonical_detected not in [c for c, _ in canonical]:
        return None
    try:
        baseline_text = head.decode(canonical_detected, errors="replace")
    except (LookupError, UnicodeError):
        return None
    if _word_interior_symbols(baseline_text) == 0:
        # Nothing about this reading says mojibake. Whatever else is true of it,
        # this rule has no evidence and does not get an opinion.
        return None
    baseline = _prose_plausibility(baseline_text)
    for name, _original in canonical:
        if name is None or name == canonical_detected:
            continue
        if _is_wide_encoding(name):
            continue
        if _is_multibyte_encoding(name) and len(head) < _MIN_MULTIBYTE_SAMPLE:
            continue
        try:
            decoded = head.decode(name, errors="replace")
        except (LookupError, UnicodeError):
            continue
        if _word_interior_symbols(decoded) == 0 \
                and _prose_plausibility(decoded) > baseline:
            logger.debug("preferring %s over %s: no symbol inside a word",
                         name, detected)
            return name
    return None


# Why a prefix has no encoding. Constants rather than sentences at the return
# statements, because `B162` made "skipped, and here is why" a contract the
# index reports to the operator and these are the two things it can say about
# bytes (`src/personal_docs.py` maps them onto its ``SKIP_*`` vocabulary).
NOT_TEXT = "the bytes do not decode as text"
ENCODING_UNIDENTIFIED = "the encoding could not be identified from so few bytes"


def sniff_text_encoding(head: bytes) -> str | None:
    """The encoding *head* decodes as, or ``None`` when it does not read as text.

    One decision, two callers: ``looks_like_text`` asks whether there is an
    answer, ``decode_text_file`` uses the answer. Before `B101` those were
    different questions answered by different code — the probe refused a file on
    the strength of a NUL byte while the reader three frames away had a
    ``charset_normalizer`` fallback that resolves exactly those files. They
    cannot disagree now (`Law 13`).

    Order matters and each step earns its place:

    * **BOM** — a file declaring its own encoding. This is the half of `B101`
      that costs nothing: a UTF-16LE ``.txt`` opens ``FF FE`` and everything
      after it is unambiguous.
    * **NUL, no BOM** — binary. png/jpeg/zip/gzip prefixes all carry one, and a
      zip of pure ASCII scores 0.02 on the ratio below, so the ratio alone would
      pass it. UTF-16 *without* a BOM is what this rule costs, and it keeps the
      banner it has always had: nothing separates it from a container without
      guessing.
    * **Clean UTF-8** — no replacement characters at all. This is almost every
      file the product sees, and it is answered without running a detector.
    * **charset_normalizer** — reached by anything with even one bad byte, and
      taken only when it decodes *strictly cleaner* than UTF-8 did. This is the
      rescue `B101` names, and the comparison is what makes it safe to run
      before the ratio rather than after it: legacy prose scores anywhere in the
      range (cp1251 Russian 0.811 here, cp1250 Polish 0.170, latin-1 German
      0.098 — `B02` measured 0.815/0.396/0.148 on its own samples), so a rule
      that only rescued the *worst*-scoring files would leave the ones in the
      middle decoded as UTF-8 and handed to the model as mojibake. Which is what
      happened: a 0.17 file passed the ratio and lost every accented character.
    * **UTF-8 under ``_MAX_REPLACEMENT_RATIO``** — the `B02`/`B76` verdict, kept
      as the floor, so every file that reached the model before still does even
      when the detector has no opinion.

    Measured against the png, jpeg, gzip, PE, dense-binary and NUL-free
    high-byte fixtures in ``tests/test_attachment_extension_registers.py``, the
    detector answers ``None`` for every one; the control-char guard is the belt
    for whatever a future version guesses wrong.

    Import-guarded: ``charset-normalizer`` is a hard requirement
    (``requirements.txt``), but a probe that cannot run must answer "not text"
    rather than raise, exactly as the ``open()`` failure in ``looks_like_text``
    does.
    """
    return describe_text_encoding(head)[0]


def describe_text_encoding(head: bytes) -> tuple[str | None, str]:
    """``(encoding, reason)`` — the same decision, with the refusal named.

    ``sniff_text_encoding`` is this function's first element and has always been
    the whole answer; `B201` needed the second, because "we could not identify
    the encoding of these bytes" and "these bytes are not text" are different
    things to say to the person who attached the file, and the index has
    reported skips with a reason since `B162`. One decision, two shapes — the
    boolean probe, the reader and the indexer all come through here (`Law 13`).

    *reason* is ``""`` whenever there is an encoding, and one of ``NOT_TEXT`` /
    ``ENCODING_UNIDENTIFIED`` otherwise.
    """
    if not head:
        return "utf-8", ""  # empty file — nothing binary about it
    for bom, encoding in _BOMS:
        if head.startswith(bom):
            return encoding, ""
    if b"\x00" in head:
        return None, NOT_TEXT
    utf8_ratio = _replacement_ratio(head.decode("utf-8", errors="replace"))
    if utf8_ratio == 0.0:
        return "utf-8", ""
    # `B280`, first lever. A file that names its own encoding is not a guess,
    # and it is checked before the detector for the same reason a BOM is: the
    # detector is a classifier over the byte histogram and cannot read a
    # sentence. It still has to clear the same bar the detector's answer does —
    # strictly cleaner than the UTF-8 reading — so a stale declaration cannot
    # make this worse than it already was.
    declared = _declared_encoding(head)
    if declared and _is_wide_encoding(declared):
        # `B101`'s rule, and it applies to a declaration for the same reason it
        # applies to a guess: bytes with no NUL in them decode under a UTF-16/32
        # codec to *some* codepoint for every pair, so the check below scores it
        # a perfect zero and it wins on merit while being nonsense. A real
        # UTF-16 file reaches this function with a BOM or with NULs and is
        # answered above, so a declaration is never the only evidence for one.
        declared = None
    if declared:
        try:
            decoded = head.decode(declared, errors="replace")
        except (LookupError, UnicodeError):
            decoded = None
        if (
            decoded is not None
            and _replacement_ratio(decoded) < utf8_ratio
            and _control_ratio(decoded) <= _MAX_CONTROL_RATIO
        ):
            return declared, ""
    detected = _detect_encoding(head)
    unsupported_guess = ""
    if detected and _is_wide_encoding(detected):
        # A UTF-16/32 guess about bytes that contain no NUL: every byte pair maps
        # to *some* codepoint, so such a decode scores a perfect zero on the
        # ratio and wins on merit while being nonsense. Measured: b"h\xc3\xa9llo
        # w\xc3\xb6rld\xff" is detected as utf_16_be and decodes to CJK. Real
        # UTF-16 reaches this function with a BOM or with NULs, and both are
        # answered above, so there is nothing here for a wide codec to win.
        detected = None
    elif (
        detected
        and _is_multibyte_encoding(detected)
        and len(head) < _MIN_MULTIBYTE_SAMPLE
    ):
        # `B201`, and the same argument one codec family over. A multi-byte
        # guess regroups the bytes, so getting it wrong does not mis-accent the
        # text, it replaces it: eleven cp1251 bytes read as Big5 are five CJK
        # ideographs. The sample is what decides whether that regrouping is
        # evidence or a coincidence, and under `_MIN_MULTIBYTE_SAMPLE` bytes it
        # is measurably a coincidence (22 right, 59 wrong). Discarding it here
        # rather than at the comparison below is deliberate: the comparison asks
        # whether the decode is *clean*, and the whole problem is that this one
        # is — no replacement characters, no control characters, and wrong.
        logger.debug(
            "ignoring %s guessed from %d bytes: too short to be evidence",
            detected, len(head),
        )
        unsupported_guess = detected
        detected = None
    if detected:
        # `B280`, second lever. ``detect`` is ``from_bytes(...).best()``: the
        # runners-up were computed and thrown away. A single-byte codec maps
        # every byte to *something*, so the winner can be a reading that puts
        # ``¿`` and ``³`` inside words while the file's real codec is sitting
        # second on the list. Reordering the detector's own candidates by how
        # much their output looks like prose is the only thing here that reads
        # the decode rather than the bytes — and it is a reordering, so nothing
        # the detector did not propose can be chosen.
        detected = _more_plausible_alternative(head, detected) or detected
        try:
            decoded = head.decode(detected, errors="replace")
        except (LookupError, UnicodeError):
            decoded = None
        if (
            decoded is not None
            and _replacement_ratio(decoded) < utf8_ratio
            and _control_ratio(decoded) <= _MAX_CONTROL_RATIO
        ):
            return detected, ""
    if utf8_ratio <= _MAX_REPLACEMENT_RATIO:
        return "utf-8", ""
    # Nothing left to say yes with. When the only candidate was a multi-byte
    # guess the sample could not support, say that rather than "not text" — the
    # file almost certainly *is* text, in an encoding nobody here can name, and
    # a caller that reports "unsupported extension" for it would be lying about
    # a format it supports.
    return None, (ENCODING_UNIDENTIFIED if unsupported_guess else NOT_TEXT)


def decode_text_file(path: str) -> str:
    """Read *path* as text, in the encoding the probe identified.

    `B101`: ``_process_text_file`` read through ``personal_docs.read_text_file``,
    which is ``open(..., encoding="utf-8", errors="ignore")`` and **cannot
    raise** — it returns ``""`` on any failure. So the ``charset_normalizer``
    fallback written directly underneath its call site was unreachable, and a
    cp1251 file did not arrive mangled: it arrived *stripped*, every non-ASCII
    byte dropped by ``errors="ignore"``. A UTF-16LE file fared worse — its NUL
    padding is valid UTF-8, so the model was handed ``S\x00E\x00N\x00...``.

    The prefix picks the codec (``sniff_text_encoding``), the whole file is
    decoded with it, and ``errors="replace"`` is the floor: a file whose tail is
    not what its first 8 KiB promised loses a character, not the document.
    """
    with open(path, "rb") as fh:
        head = fh.read(TEXT_SNIFF_BYTES)
        rest = fh.read()
    # The probe and the reader run the same sniff, but they are not asking the
    # same thing and so they do not stop in the same place. ``sniff_text_encoding``
    # decides *whether* to read and must stay strict — its NUL rule is what keeps
    # png/zip/docx out. By the time this function runs the decision is already
    # made (a register named the extension, or the probe said yes), so a NUL-laden
    # prefix here is far more likely to be BOM-less UTF-16 than a container, and
    # asking the detector one more time is the difference between a `.txt` the
    # model can read and one full of NULs. Measured: ``charset_normalizer``
    # resolves BOM-less utf-16-le/utf-16-be/utf-32-le prose correctly.
    #
    # `B201`: that second call used to run for **every** prefix the sniff
    # refused, which made it an unconditional override of the sniff's own
    # guards — the control-char guard, the "must decode strictly cleaner than
    # UTF-8" comparison and the new short-sample rule all got the same answer
    # handed back to them by the very next expression. The NUL test narrows it
    # to the case the comment above describes and is the only case it was ever
    # for: BOM-less UTF-16/32 is exactly the thing that reaches here with NULs
    # and no other answer. A registered `.txt` whose encoding nobody can name
    # falls to the UTF-8 floor and arrives with visible U+FFFD, which is what
    # the floor has always meant and is the honest half of `Law 1` — the
    # alternative was a confident decode into the wrong script.
    encoding = sniff_text_encoding(head)
    if encoding is None and b"\x00" in head:
        encoding = _detect_encoding(head)
    encoding = encoding or "utf-8"
    try:
        return (head + rest).decode(encoding, errors="replace")
    except LookupError:
        return (head + rest).decode("utf-8", errors="replace")



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

    Deliberately no python-magic: ``detect_content_type`` is a libmagic call and
    python-magic ships only in the Docker image, so routing this through it
    would accept different files on a Docker install than on a pip/venv one.
    ``charset-normalizer`` is a hard requirement and has no such split.

    `B101` moved the verdict into ``sniff_text_encoding`` so the probe and the
    reader are one piece of code. What changed here: a BOM'd UTF-16/32 file and
    a legacy single-byte file are text now. What did not: every file that
    reached the model before still does, and every binary fixture still gets the
    banner.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(probe_bytes)
    except Exception as exc:
        logger.warning("text sniff failed for %s: %s", path, exc)
        return False
    return sniff_text_encoding(head) is not None


def text_refusal_reason(path: str, probe_bytes: int = TEXT_SNIFF_BYTES) -> str:
    """Why ``looks_like_text`` said no, in one phrase, or ``""`` if it said yes.

    `B201`. The banner for a file nothing read has said *"No extractor covers
    this file type"* since `B76`, and for a binary container that is true. For a
    short legacy-encoded file it is a lie about a format the product supports
    perfectly well: the extension is unregistered, the bytes are text, and the
    only thing missing is a name for the encoding. Callers that show a person
    why nothing arrived ask this instead of assuming the first answer.

    Kept apart from ``looks_like_text`` on purpose. The probe is what
    ``build_user_content`` calls to *decide*, and two tests pin that it is
    literally that function being called; this is what a caller asks **after**
    the decision has already gone against the file, so it is paid only on the
    path whose current cost is a banner and zero bytes of content.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(probe_bytes)
    except Exception as exc:
        logger.warning("text sniff failed for %s: %s", path, exc)
        return NOT_TEXT
    return describe_text_encoding(head)[1]


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

    This used to end with an invariant in prose — "keep ``TEXT_EXTS`` a
    superset of the ``language_map`` / ``code_extensions`` fence sets in
    ``_process_text_file``" — which `B100` measured as already false and has
    now made unnecessary: there are no fence sets left to be a superset of.
    The label and the fence are derived by ``attachment_language`` for
    whatever file arrives, including the ones no register names. ``.h`` is in
    ``TEXT_EXTS`` for determinism only — ``mimetypes.guess_type`` already
    resolves it to ``text/x-chdr``.

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
    # Name and language both come from what the user called the file, falling
    # back to the stored path. They must come from the same string or the
    # `[Type: …]` label contradicts the filename printed one line above it.
    filename = os.path.basename(display_name or path)
    _, ext = os.path.splitext(filename.lower())
    if ext:
        language = attachment_language(filename)
    else:
        _, ext = os.path.splitext(path.lower())
        language = attachment_language(path)
    max_len = 30000 if ext != ".log" else 10000

    # `B101`: one decoder, and it is reachable. The previous first call was
    # ``personal_docs.read_text_file`` — utf-8 with ``errors="ignore"``, which
    # cannot raise — so the ``charset_normalizer`` fallback written under it
    # never ran, and a cp1251 file arrived with every non-ASCII byte dropped.
    try:
        content = decode_text_file(path)
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

    # `B100`: the fence follows the label rather than a second list. Anything
    # with a language name is fenced with that name; ``PROSE_LANGUAGES`` is the
    # only exception, and it holds the same two answers (`text`, `log`) that
    # were printed unfenced before.
    if language not in PROSE_LANGUAGES:
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
        is_office_format,
        convert_to_markdown,
    )

    if not is_office_format(path):
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
    # the document simply had no extractable text. `B240` moved that three-way
    # answer into ``markitdown_runtime.office_extraction_gap`` — it is a fact
    # about the extractors, and the mailbox needs the same fact to say why it
    # refused an attachment. The wording around it stays here because a chat
    # banner and a JSON error are not the same sentence; the *reason* is one.
    from src.markitdown_runtime import office_extraction_gap

    gap = office_extraction_gap(path)
    if gap == NO_EXTRACTABLE_TEXT:
        # `.odt`/`.doc`: the bundled reader is always present, so "install the
        # optional dependency" would be a lie and the only honest answer is that
        # the document holds no text this reader can see.
        return f"\n\n[Attached document: {display_name} — no extractable text found.]"
    return f"\n\n[Attached document: {display_name} — {gap}]"


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
            #
            # `B201`: two reasons reach this line and they are not the same
            # sentence. "No extractor covers this file type" is true of a
            # WordPerfect document and false of a nine-character cp1251 `.conf`,
            # where the extractor exists, the bytes are text, and what is
            # missing is a name for the encoding. Ask which one it was rather
            # than printing the first.
            if text_refusal_reason(path) == ENCODING_UNIDENTIFIED:
                banner = (
                    f"[Attached file: {display_name} — contents not read. The "
                    f"file is text in a legacy encoding, and there are too few "
                    f"bytes in it to identify which one, so nothing from the "
                    f"file is in this message. The upload itself is intact and "
                    f"can be downloaded.]"
                )
            else:
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
