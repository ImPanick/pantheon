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
from src.context_budget import (
    CONTEXT_BUDGETS,
    attachment_kind as _attachment_kind,
    fit_to_context_budget,
    resolve_context_budget,
)

logger = logging.getLogger(__name__)

# `P12-04`. The six character budgets that decide how much of a turn an
# attachment may take are one registry now — `src.context_budget.CONTEXT_BUDGETS`
# — and each resolves **role profile → instance setting → built-in default** per
# request. These two names survive (`Law 1`): the constant is the built-in
# default for the shared ceiling and is read as a live module attribute at every
# call site, so a test that sets it still decides, exactly as `P12-03` left the
# byte caps. It is the registry's own number rather than a second copy of 24000.
MAX_INLINE_ATTACHMENT_CHARS = CONTEXT_BUDGETS["context_attachment_total_chars"]
MIN_INLINE_ATTACHMENT_SLICE = 500


def _budget(key: str, owner: str | None = None, ceiling=None) -> int:
    """One character budget, resolved now, under this module's own ceiling."""
    return resolve_context_budget(
        key, owner, ceiling_default=MAX_INLINE_ATTACHMENT_CHARS, ceiling=ceiling)

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
# **What it did not fix, measured rather than hoped.** The Big5→johab case is a
# *multi-byte* confusion: both readings are 100% letters with nothing inside a
# word, so this is blind to it. Three rules were built and measured against the
# same sweep and all three were rejected — see `B402`. A rule that refuses when
# a differently-scripted multi-byte rival is within ε chaos costs **98 correct
# answers to buy 16**, because the margin between the wrong top answer and the
# right runner-up (0.062–0.071 for Big5/johab) sits *inside* the margin range of
# the cases where the top answer is right (0.000–0.100). There is no threshold
# there, and saying so is the finding. `B402`/`B1514` below reach it another way.
#
# ── `B402` / `B1514`: a Korean reading that is not Korean ──────────────────────
#
# The CJK cases this module still got wrong were nearly all one shape: bytes of
# another CJK script answered with a **Korean** codec. Re-measured 2026-10-28
# over 3,017 cuts (24–160 bytes) of hand-written prose in nine CJK encodings —
# several registers each, Korean including chat slang (`ㅋㅋ`, `ㅠㅠ`) and
# Hanja-mixed text — **502 were read wrongly**: EUC-JP as cp949 197 times,
# Shift-JIS and cp932 as cp949 94 times each, Big5 and cp950 as johab 12 times
# each. Genuine Korean was right 968 of 968. Two things a Korean reading of
# those bytes does that Korean writing does not, neither of them a language
# model:
#
# 1. **Syllables outside KS X 1001.** Every Korean legacy codec is built around
#    KS X 1001's 2,350 syllables — the set chosen *because* it is the syllables
#    Korean is written in; the other 8,822 exist for completeness. Johab's
#    reading of Big5 lands in them (58–71% of its distinct syllables), and
#    cp949's reading of Shift-JIS lands in cp949's extension rows (100%).
#    Genuine Korean: 0% over the 968, and a deliberately rare line of
#    onomatopoeia (`햏햏햏 뷁뷁 똠똠 쌰쌰쌰`) 33%. **`B402`'s third rejected rule
#    asked exactly this and was measured wrongly**: it tested membership with
#    `ch.encode("euc_kr")`, which succeeds for *every* syllable — CPython's
#    EUC-KR writes a syllable outside the 2,350 as an 8-byte KS X 1001 Annex 3
#    make-up sequence. Membership is a 2-byte encoding (`_in_ks_x_1001`).
# 2. **Jamo standing alone after a word.** EUC-JP's hiragana row is KS X 1001's
#    compatibility-jamo row, so EUC-JP read as cp949 scatters jamo through the
#    text, glued to the syllables around them (Japanese has no spaces). Korean
#    writes a jamo alone for its consonant abbreviations and its crying and
#    laughing vowels (`_JAMO_WRITTEN_ALONE`), and names any other letter after
#    a space, a quote or a comma — measured on grammar sentences (`ㅚ와 ㅟ는`,
#    `'ㅢ'는`) that a looser count misread as Japanese.
#
# A Korean answer showing either is not taken: the detector's own runner-up is,
# under the same filters as `B280`'s, and failing that the bytes are refused as
# unidentified. Over the sweep: **452 corrected, 0 regressed, 0 refused**; the
# 50 left are Japanese read as GB18030 (16; GB2312 has the kana rows too) and
# GB read as cp949 (30), which neither signal touches.
#
# **CJK punctuation is not a symbol inside a word.** `、。，：` sit between
# characters with no space because CJK writing has none, so `_word_interior_
# symbols` counted every correctly decoded Japanese or Chinese sentence as
# mojibake — that is what let `B280`'s lever trade a right cp932 answer for a
# wrong cp949 one (the Shift-JIS cases above), and what kept a right Big5
# reading from beating a half-width-katakana one. Those two blocks are skipped
# there and in `_prose_plausibility`; no single-byte codec produces them.
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


def _is_cjk_punctuation(ch: str) -> bool:
    """`B402`/`B1514`. The CJK Symbols and Punctuation block and the full-width
    forms of ASCII punctuation — what CJK prose separates words with, written
    with no space. The half-width katakana forms (U+FF61 on) are not in it:
    that is what Big5 read as cp932 is made of."""
    o = ord(ch)
    return 0x3000 <= o <= 0x303F or 0xFF01 <= o <= 0xFF60


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
        if ord(ch) <= 0x7F or _is_letterish(ch) or _is_cjk_punctuation(ch):
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
    CJK punctuation is neither letter nor symbol here (`_is_cjk_punctuation`):
    a Korean misreading swallows those bytes into syllables, and counting them
    against the right reading scored the mojibake higher.
    """
    high = [ch for ch in decoded if ord(ch) > 0x7F and not _is_cjk_punctuation(ch)]
    if not high:
        return 1.0
    return sum(1 for ch in high if _is_letterish(ch)) / len(high)


#: `B402`/`B1514`. The Korean codecs, as `_canonical_codec` spells them.
_KOREAN_CODECS = frozenset({"cp949", "euc_kr", "johab"})

#: The compatibility jamo Korean writes standing alone: the consonants of its
#: initial-consonant abbreviations (`ㅋㅋ`, `ㅇㅇ`, `ㄱㄱ`, `ㅂㅂ`, `ㄳ`) and the
#: vowels of its faces (`ㅠㅠ`, `ㅜㅜ`, `ㅡㅡ`, `ㅗ`). And (`B1611`'s sweep) `ㆍ`,
#: the old vowel Korean prints as a middle dot between words and as an
#: ellipsis (`서울ㆍ경기ㆍ인천`, `그래서ㆍㆍㆍ`): glued after a syllable it made
#: Korean read as Big5 (28 of 102 such cuts measured; all 102 right now), and
#: no kana lands on it.
_JAMO_WRITTEN_ALONE = frozenset("ㄱㄲㄳㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎㅗㅜㅠㅡㆍ")


def _in_ks_x_1001(ch: str) -> bool:
    """One of KS X 1001's 2,350 syllables. A **2-byte** EUC-KR encoding: CPython
    encodes any other syllable too, as an 8-byte Annex 3 make-up sequence,
    which is why asking only whether it encodes measured nothing (`B402`)."""
    try:
        return len(ch.encode("euc_kr")) == 2
    except UnicodeEncodeError:
        return False


def _is_hangul_syllable(ch: str) -> bool:
    return "\uac00" <= ch <= "\ud7a3"


def _is_ideograph(ch: str) -> bool:
    return unicodedata.name(ch, "").startswith("CJK UNIFIED")


def _is_kana(ch: str) -> bool:
    """Hiragana or katakana, the prolonged-sound mark included."""
    return "\u3041" <= ch <= "\u3096" or "\u30a1" <= ch <= "\u30fc"


#: `B1611`. Compatibility jamo a Korean keyboard does not leave standing next to
#: another: the compound finals (but `ㄳ` and `ㅄ`, abbreviations Korean writes
#: alone) and the old letters from U+3165 on (but `ㆍ`, which Korean prints as a
#: middle dot and an ellipsis, `서울ㆍ경기`, `ㆍㆍㆍ`). GB2312's hiragana row is
#: KS X 1001's jamo row, and from `う` `お` `か` `が` `き` `く` and `ま` on the
#: kana land on exactly these.
_JAMO_NEVER_IN_A_RUN = frozenset("ㄵㄶㄺㄻㄼㄽㄾㄿㅀ") | frozenset(
    chr(c) for c in range(0x3165, 0x318F) if c != 0x318D)

#: `B1611`. The particles Korean puts straight after a letter it names (`ㄼ과`,
#: `ㅚ와`, `ㄳㄵㄶ…은`).
_PARTICLES_AFTER_A_LETTER = frozenset("은는이가과와도를을의로에만")


def _is_compatibility_jamo(ch: str) -> bool:
    return "ㄱ" <= ch <= "ㆎ"


def _jamo_run_korean_does_not_type(decoded: str) -> int:
    """`B1611`. Jamo of `_JAMO_NEVER_IN_A_RUN` standing directly after another
    jamo, in runs no particle follows. Kana read as cp949 is a run of jamo with
    nothing glued to a syllable — `ありがとうございます` is `ㄲㅺㄼㅘㄶㅄㅆㄴㅮㅉ`,
    so `B1514`'s count, which asks what a jamo is glued *after*, sees none of
    it. A run Korean writes is a laugh, a cry or an abbreviation
    (`_JAMO_WRITTEN_ALONE`, `ㅗㅜㅑ`), or a list of the letters it then names
    with a particle (`ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ은`)."""
    count = 0
    i = 0
    while i < len(decoded):
        if not _is_compatibility_jamo(decoded[i]):
            i += 1
            continue
        j = i
        while j < len(decoded) and _is_compatibility_jamo(decoded[j]):
            j += 1
        if not (j < len(decoded) and decoded[j] in _PARTICLES_AFTER_A_LETTER):
            count += sum(1 for ch in decoded[i + 1:j] if ch in _JAMO_NEVER_IN_A_RUN)
        i = j
    return count


def _hanja_inside_words(decoded: str) -> int:
    """`B1597`. Runs of ideographs with a Hangul syllable directly on **both**
    sides. Korean writes Hanja as words — a run after a space or at the start,
    a particle after it (`大韓民國은`, `國民에게`); a Chinese text read as a
    Korean codec scatters single Hanja between syllables, because GB2312's
    rows from 0xCA on are KS X 1001's Hanja rows and the rows before them its
    syllable rows (`되쩌呵겨`)."""
    count = 0
    i = 0
    while i < len(decoded):
        if not _is_ideograph(decoded[i]):
            i += 1
            continue
        j = i
        while j < len(decoded) and _is_ideograph(decoded[j]):
            j += 1
        if i and j < len(decoded) and _is_hangul_syllable(decoded[i - 1]) \
                and _is_hangul_syllable(decoded[j]):
            count += 1
        i = j
    return count


def _not_korean(decoded: str) -> int:
    """How much of a Hangul reading Korean writing does not do (`B402`,
    `B1514`, the block above): compatibility jamo outside
    `_JAMO_WRITTEN_ALONE` glued after a syllable or an ideograph, two or more;
    the syllables outside KS X 1001, when they are at least half of the
    distinct syllables and at least two; and (`B1597`) Chinese's own marks —
    full-width punctuation, not one space, and Hanja inside a word
    (`_hanja_inside_words`), all three. ``0`` for anything that is not Hangul.

    `B1597`'s three are asked together because each alone is something Korean
    does: a headline glues `北` to its particle, a chat runs on without a
    space, an old document carries a full-width comma. Chinese read as cp949
    does all three at once — every one of the sweep's 30 cuts carried the
    full-width comma, none a space, 27 a Hanja inside a word — and the
    968 Korean cuts none of them. The one Korean found that does all three was
    written to (`새누리黨은，國會에서法案을처리했다`, no space anywhere): it is
    refused with `ENCODING_UNIDENTIFIED` rather than read, which is this
    rule's cost, and a CJK frequency table is what would remove it.

    `B1611`: and two or more jamo in a run Korean does not type
    (`_jamo_run_korean_does_not_type`), in a reading with no space anywhere —
    kana read as cp949, which is what GB2312 or EUC-JP text that leads with
    kana becomes. Measured over the `B402` sweep plus 1,037 further cuts (GB
    text quoting Japanese, Korean news with Hanja, spaced Chinese, and Korean
    that writes jamo next to jamo — vowel and compound-final lists, old
    letters, `ㅗㅜㅑ`, `ㆍㆍㆍ`, filter-dodging spelling, `ㅄㅄ`): 58 corrected
    by this count (the sweep's last four EUC-JP-as-cp949 among them; the sweep
    is wrong 7 → 3) and 28 by `ㆍ` in `_JAMO_WRITTEN_ALONE`, none regressed, no
    new refusal; six kana-led GB cuts are still wrong, now as EUC-JIS-2004 —
    mostly kana, which `B1596` reads as Japanese. A space is the guard: every
    Korean line found that lists letters without one stops at its particle.
    """
    glued = sum(
        1 for i, ch in enumerate(decoded)
        if "\u3131" <= ch <= "\u318e" and ch not in _JAMO_WRITTEN_ALONE
        and i and (_is_hangul_syllable(decoded[i - 1]) or _is_ideograph(decoded[i - 1]))
    )
    syllables = {ch for ch in decoded if _is_hangul_syllable(ch)}
    rare = sum(1 for ch in syllables if not _in_ks_x_1001(ch))
    evidence = glued if glued >= 2 else 0
    if rare >= 2 and rare * 2 >= len(syllables):
        evidence += rare
    unspaced = not any(ch.isspace() for ch in decoded)
    if syllables and any(0xFF01 <= ord(ch) <= 0xFF5E for ch in decoded) and unspaced:
        evidence += _hanja_inside_words(decoded)
    if unspaced:
        run = _jamo_run_korean_does_not_type(decoded)   # `B1611`
        if run >= 2:
            evidence += run
    return evidence


#: `B1596`. The Chinese and Japanese codecs, as `_canonical_codec` spells them.
_CHINESE_CODECS = frozenset({"gb2312", "gbk", "gb18030", "hz", "big5", "big5hkscs", "cp950"})
_JAPANESE_CODECS = frozenset({"euc_jp", "euc_jis_2004", "euc_jisx0213", "shift_jis",
                              "shift_jis_2004", "shift_jisx0213", "cp932"})


#: `B1617`. The Big5 codecs, as `_canonical_codec` spells them.
_BIG5_CODECS = frozenset({"big5", "big5hkscs", "cp950"})

#: `B1617`. A run of compatibility jamo.
_JAMO_RUN = re.compile("[\u3131-\u318e]+")


def _reads_as_korean_chat(decoded: str) -> bool:
    """`B1617`. A Korean reading that is Korean chat and nothing else: three or
    more jamo, every one a modern letter (U+3131–U+3163) standing in a run of
    two or more — the abbreviations, laughs and filter-dodging spellings Korean
    types (`ㄱㅅㄱㅅ`, `ㅋㅋㅋ`, `ㄱㅐㅅㄲㅣ`) — spaces between words, every
    other letter a KS X 1001 syllable, and nothing `_not_korean` objects to.

    EUC-KR's jamo row is Big5's row of one- to four-stroke characters
    (`丑今元六`), and its syllable rows land in Big5's level 1, so the detector
    ranked ``ㄱㅅㄱㅅ ㅈㅅㅈㅅ ㅇㅋㅇㅋ 내일 봐`` Big5 first and its Big5 reading
    (``丑今丑今 元今元今 仄六仄六 頂橾 瑭``) carries nothing any count here can
    object to. Asked of the rival instead, it is narrow on purpose: Chinese
    read as cp949 lands on Hanja, on symbols, on syllables outside KS X 1001
    and on old jamo — every Big5 character whose trail byte is under 0xA1, or
    whose lead byte is outside KS X 1001's jamo row (0xA4) and syllable rows
    (0xB0–0xC8), breaks it — and a jamo standing
    alone between syllables, which is what scattered 4-stroke characters
    become, breaks it too. Measured: the 16 sweep cuts this row filed right, no
    change to the 4,054-cut sweep's other answers or to 634 cuts of
    traditional Chinese spaced every two characters; on 5,226 cuts of nonsense
    built only from Big5 characters that read as Korean letters, 10 flip.
    """
    jamo = [ch for ch in decoded if _is_compatibility_jamo(ch)]
    if len(jamo) < 3 or not any(ch.isspace() for ch in decoded):
        return False
    if any(not ("\u3131" <= ch <= "\u3163") for ch in jamo):
        return False
    if any(len(run) < 2 for run in _JAMO_RUN.findall(decoded)):
        return False
    for ch in decoded:
        if ord(ch) <= 0x7F or _is_compatibility_jamo(ch):
            continue
        if not (_is_hangul_syllable(ch) and _in_ks_x_1001(ch)):
            return False
    return _not_korean(decoded) == 0


def _not_chinese(decoded: str) -> int:
    """`B1596`. A Chinese reading that is Japanese: kana at least half of its
    kana and ideographs together, four or more. GB2312 put hiragana and
    katakana in the rows JIS X 0208 put them in, so EUC-JP read as GB18030
    keeps every kana and turns only the kanji into other hanzi
    (`ログインに己窃しました`) — neither `B402`'s signal nor `B1514`'s can see
    it, since nothing in it is Hangul. Chinese writes kana only quoting
    Japanese, between the hanzi that say what it means; text that is mostly
    kana is Japanese text. The kana count, or ``0``."""
    kana = sum(1 for ch in decoded if _is_kana(ch))
    ideographs = sum(1 for ch in decoded if _is_ideograph(ch))
    return kana if kana >= 4 and kana * 2 >= kana + ideographs else 0


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


def _narrow_runner_up(head: bytes) -> str | None:
    """`B1616`. The detector's best candidate for *head* that is not UTF-16/32.

    Asked only when the detector's own answer was a wide codec about bytes with
    no NUL in them, and UTF-8 cannot carry them either (the call site says
    why) — the guess `B101` throws away, because every byte pair
    decodes under UTF-16 to *some* code point. Throwing the guess away is right;
    throwing the ranking away with it was not: EUC-KR chat
    (``ㅗㅜㅑ 대박 이거 뭐야 ㅋㅋㅋㅋ``, 30 bytes) is ranked
    ``['utf_16_le', 'cp949', …]`` and was answered `NOT_TEXT` with the right
    codec sitting second. Only a reordering of the detector's own list, like
    `_more_plausible_alternative`, and the answer goes through every guard the
    detector's first answer would have (the short-sample floor, the Korean
    check, strictly cleaner than UTF-8).
    """
    for name in _rank_encodings(head):
        if not _is_wide_encoding(name):
            return name
    return None


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
    if canonical_detected in _BIG5_CODECS:
        # `B1617`. Nothing about a Big5 reading of Korean jamo chat is wrong on
        # its face, so the evidence is asked of the detector's Korean candidate.
        for name, original in canonical:
            if name not in _KOREAN_CODECS:
                continue
            try:
                rival = head.decode(name)
            except (LookupError, UnicodeError):
                continue
            if _reads_as_korean_chat(rival):
                logger.debug("preferring %s over %s: it reads as Korean chat", name, detected)
                return original
    symbols = _word_interior_symbols(baseline_text)
    not_korean = _not_korean(baseline_text)
    not_chinese = _not_chinese(baseline_text) if canonical_detected in _CHINESE_CODECS else 0
    if symbols == 0 and not_korean == 0 and not_chinese == 0:
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
        if _not_korean(decoded):
            continue   # `B1514`: never trade one misreading for another
        if not_chinese and name not in _JAPANESE_CODECS:
            continue   # `B1596`: the evidence is that the text is Japanese
        if not_korean or not_chinese:
            # `B402`/`B1514`. A Korean answer that is not Korean — or (`B1596`)
            # a Chinese one that is Japanese — against a rival reading that is
            # clean, not one replacement character, and no worse in either of
            # `B280`'s measures. Both readings can be all letters, so "more
            # letter-like" is not asked of it.
            if (_replacement_ratio(decoded) == 0.0
                    and _word_interior_symbols(decoded) <= symbols
                    and _prose_plausibility(decoded) >= baseline):
                logger.debug("preferring %s over %s: the Korean reading is not Korean",
                             name, detected)
                return name
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

    One decision for its callers: ``looks_like_text`` asks whether there is an
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
        #
        # `B1616`: the guess goes, and — when UTF-8 cannot carry these bytes
        # either, so the answer would otherwise be a refusal — the detector's
        # runner-up is asked in its place. Over the 4,054-cut CJK sweep this
        # turned all 20 of its refusals (Korean chat, Korean prose and Big5,
        # each ranked UTF-16 first) into right answers and changed nothing
        # else. Only then: UTF-8 with one stray byte has been ranked UTF-16
        # first too, and its runner-up is a single-byte codec that decodes it
        # "cleaner" by turning every accented letter into two — the UTF-8 floor
        # below, one U+FFFD, is the better answer there, and stays it
        # (`test_a_detector_guess_is_taken_only_when_it_decodes_better`).
        detected = _narrow_runner_up(head) if utf8_ratio > _MAX_REPLACEMENT_RATIO else None
    if (
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
            and _canonical_codec(detected) in _KOREAN_CODECS
            and _not_korean(decoded)
        ):
            # `B402`: a Korean reading that is not Korean, and no reading the
            # detector proposed to put in its place. Not handed on as text: the
            # file is text in an encoding this cannot name, and says so.
            logger.debug("refusing %s: the Korean reading is not Korean", detected)
            unsupported_guess = detected
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


# `B77`'s one derivation of what a stored upload is called. `P21-03` moved it to
# `src/file_names.py` beside the rest of the naming (the person's own name, the
# title, the stored name, the download header) and taught it to read the
# person's name back out of rows written before `display_name` existed. It is
# re-exported here because this is where `upload_handler`, the tests and
# `build_user_content` below have always imported it from.
from src.file_names import document_title, upload_display_name  # noqa: E402,F401


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


def _process_text_file(path: str, display_name: str | None = None,
                       owner: str | None = None, ceiling=None) -> str:
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
    # `P12-04`. Two budgets on one line, and the second is the `.log`-only
    # branch nobody had written down. They are separate keys because they are
    # separate decisions: an operator raising the text budget was silently
    # raising the log one too.
    max_len = _budget(
        "context_text_file_chars" if ext != ".log" else "context_log_file_chars",
        owner, ceiling)

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


def _process_pdf(path: str, owner: str | None = None, ceiling=None) -> str:
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
            pdf_text, marker = fit_to_context_budget(
                pdf_text, "context_pdf_extract_chars", owner,
                ceiling_default=MAX_INLINE_ATTACHMENT_CHARS, ceiling=ceiling,
                marker="\n[PDF content truncated]")
            return f"\n\n[PDF content]:{pdf_text}{marker}"
        else:
            return "\n\n[PDF processed but no readable content found]"

    except Exception as e:
        return f"\n\n[PDF processing failed: {str(e)}]"


def _truncate_inline(text: str, owner: str | None = None,
                     ceiling=None) -> tuple[str, str]:
    """Cap inline document text so a huge file can't blow the model's context.

    `P12-04`: the 15,000 that used to be a default argument here is
    `context_office_inline_chars`, one of three separate 15,000s the row called
    "the PDF's 15,000". This one bounds Office/EPUB markdown.
    """
    return fit_to_context_budget(
        (text or "").strip(), "context_office_inline_chars", owner,
        ceiling_default=MAX_INLINE_ATTACHMENT_CHARS, ceiling=ceiling,
        marker="\n[…truncated for inline context.]")


def _fit_inline_attachment_text(
    text: str,
    remaining: int,
    display_name: str,
    total: int | None = None,
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

    # `P12-04`. The sentence names the budget that actually applied to this
    # turn, not the shipped constant. An operator who lowered the ceiling for a
    # role, and a user reading why their attachment was dropped, are looking at
    # the same number or the message is a second source of truth (`Law 7`).
    total = MAX_INLINE_ATTACHMENT_CHARS if total is None else int(total)
    name = os.path.basename(display_name or "attachment")
    if remaining < MIN_INLINE_ATTACHMENT_SLICE:
        return (
            f"\n\n[Attachment omitted from inline context: {name}. "
            f"The {total:,}-character shared inline "
            "attachment budget was already used by earlier attachments. Ask "
            "to inspect this file specifically if more detail is needed.]",
            0,
        )
    marker = (
        f"\n\n[Attachment content truncated: {name}. "
        f"Only {remaining:,} characters of this attachment fit within "
        f"the {total:,}-character shared inline "
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
    ceiling=None,
    upload_id: str | None = None,
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
        extracted_language,
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
        # `P21-03` — the owner's report, reproduced here: this was
        # `splitext(basename(path))[0]`, and the stored path is the upload id,
        # so a `.docx` dropped into a chat became a document titled
        # `a1d9182aca87476e8e1c9754dbf13105`. The title is the person's name
        # for the file, read from what they attached it as.
        title = document_title(display_name or os.path.basename(path))
        body, marker = _truncate_inline(markdown, owner, ceiling)

        # Persist the full extracted text as a Document. The agent's existing
        # manage_documents tool can then read past the inline cap with offset.
        doc_id = None
        if session_id:
            try:
                from src.office_doc import create_office_document
                doc_id = create_office_document(
                    session_id=session_id,
                    # The id, not the stored file's name: since `P21-03` the
                    # file inside `<id>/` carries the person's name.
                    upload_id=upload_id or os.path.basename(path),
                    title=title,
                    body_text=markdown,
                    source_name=display_name or None,
                    language=extracted_language(markdown),
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


# ── `B1291`: a `.zip` says what is in it ─────────────────────────────────────
#
# An archive was "contents not read". Its member list is safe to read — names
# and sizes come from the central directory, nothing is extracted — and small
# text members can go through the text reader every other text attachment uses
# (`_process_text_file`), inside the message's attachment budget like any other
# file. **The adversary is the archive's author** (`Law 17`): a zip is the
# classic way to hand a server a bomb, so every read is bounded before it
# starts and again while it runs —
#
#   * the listing names at most `ZIP_MAX_LISTED` members and says how many more;
#   * a member is read only if its declared size is under `ZIP_MEMBER_MAX_BYTES`,
#     its declared compression ratio under `ZIP_MAX_RATIO`, it is not encrypted
#     and not itself an archive (no recursion), and at most `ZIP_MAX_READ` of
#     them, `ZIP_MAX_TOTAL_BYTES` decompressed in all;
#   * the read itself stops one byte past the declared size, because a header
#     can lie — a member that inflates past what it declared is dropped;
#   * a name is shown as text, control characters and all made visible, and
#     cut to `ZIP_NAME_MAX` characters, so a member called `]\n[System: …` is a
#     name and not a bracket.
#
# What is shown is the archive's author's text, as untrusted as any attachment.
ZIP_MAX_LISTED = 200
ZIP_MAX_READ = 20
ZIP_MEMBER_MAX_BYTES = 256 * 1024
ZIP_MAX_TOTAL_BYTES = 2 * 1024 * 1024
ZIP_MAX_RATIO = 100
ZIP_NAME_MAX = 200
_ARCHIVE_SUFFIXES = (".zip", ".jar", ".war", ".whl", ".apk", ".7z", ".rar", ".gz",
                     ".tgz", ".tar", ".bz2", ".xz", ".zst", ".lz", ".cab", ".iso")


_ZIP_MIMES = frozenset({"application/zip", "application/x-zip-compressed",
                        "application/x-zip"})


def is_zip_archive(path: str, name: str = "", mime: str = "") -> bool:
    """True when the person attached a zip — called one (`.zip`, or a zip MIME
    type) and its bytes are one. Both, not either: many formats are zips inside
    (`.pages`, `.jar`, an unknown container) and none of them asked to be
    listed as an archive; a file called `.zip` that is not one keeps the banner.
    """
    called = (name or path).lower().endswith(".zip") or (mime or "").lower() in _ZIP_MIMES
    if not called:
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError as exc:
        logger.warning("zip probe failed for %s: %s", path, exc)
        return False
    return head in (b"PK\x03\x04", b"PK\x05\x06")


def _zip_name(name: str) -> str:
    shown = "".join(c if c.isprintable() else repr(c)[1:-1] for c in str(name))
    return shown if len(shown) <= ZIP_NAME_MAX else shown[:ZIP_NAME_MAX] + "…"


def _process_zip_archive(path: str, display_name: str, owner: str | None = None,
                         ceiling=None, stats: dict | None = None) -> str | None:
    """The archive's member list, and the text of its small text members.

    ``None`` when the bytes are not a zip this can open — the caller keeps its
    "contents not read" banner. ``stats`` is filled with ``listed``,
    ``members`` and ``shown`` for the note under the attachment.
    """
    import tempfile
    import zipfile

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        total = sum(max(0, i.file_size) for i in infos)
        lines, shown, budget = [], [], ZIP_MAX_TOTAL_BYTES
        with tempfile.TemporaryDirectory(prefix="pantheon-zip-") as tmp:
            for n, info in enumerate(infos):
                name = _zip_name(info.filename)
                why = ""
                lower = info.filename.lower()
                if info.flag_bits & 0x1:
                    why = "encrypted"
                elif lower.endswith(_ARCHIVE_SUFFIXES):
                    why = "an archive inside the archive — not opened"
                elif info.file_size > ZIP_MEMBER_MAX_BYTES:
                    why = "too large to show"
                elif info.file_size > ZIP_MAX_RATIO * max(info.compress_size, 1):
                    why = (f"compressed {info.file_size // max(info.compress_size, 1):,} to 1 "
                           f"— refused as a likely zip bomb")
                elif len(shown) >= ZIP_MAX_READ or info.file_size > budget:
                    why = ""   # simply not shown; the listing says how many were
                else:
                    try:
                        with zf.open(info) as fh:
                            data = fh.read(info.file_size + 1)
                    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError,
                            EOFError, ValueError):
                        data = None
                        why = "could not be read"
                    if data is not None and len(data) > info.file_size:
                        why = "larger than its header declared — refused"
                    elif data is not None:
                        budget -= len(data)
                        member = os.path.join(tmp, f"m{n}")
                        with open(member, "wb") as out:
                            out.write(data)
                        if _is_text_file(lower) or looks_like_text(member):
                            read = _process_text_file(member, display_name=info.filename,
                                                      owner=owner, ceiling=ceiling)
                            # The reader names a file by its basename; inside an
                            # archive the path is what tells two README files apart.
                            base = os.path.basename(info.filename)
                            shown.append(read.replace(f"=== File: {base} ===",
                                                      f"=== File: {name} ===", 1))
                if n < ZIP_MAX_LISTED:
                    lines.append(f"- {name} ({info.file_size:,} bytes)" + (f" — {why}" if why else ""))
    more = len(infos) - min(len(infos), ZIP_MAX_LISTED)
    if more:
        lines.append(f"- … and {more:,} more not listed")
    if stats is not None:
        stats.update({"members": len(infos), "listed": min(len(infos), ZIP_MAX_LISTED),
                      "shown": len(shown)})
    head = (f"\n\n[Archive attached: {display_name} — {len(infos):,} "
            f"file{'' if len(infos) == 1 else 's'}, {total:,} bytes uncompressed. Listed "
            f"from its directory, not extracted"
            + (f"; the text of {len(shown)} small text file{'' if len(shown) == 1 else 's'} "
               f"follows" if shown else "") + ".]")
    return head + ("\n" + "\n".join(lines) if lines else "") + "".join(shown)


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


#: The four raster types every vision API in use takes, by their signatures.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_IMAGE_EXT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp"}


def image_media_type(raw: bytes, ext: str = "", declared: str = "") -> str:
    """The registered media type of a picture: what its first bytes say, then
    its extension, then the type it was uploaded with — `image/jpg` (no such
    type) read as `image/jpeg`. fx5-vision: the label a provider is handed with
    a person's picture, so Anthropic's path can take it."""
    head = bytes(raw[:12]) if raw else b""
    for signature, media_type in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return media_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    by_ext = _IMAGE_EXT_TYPES.get((ext or "").lower())
    if by_ext:
        return by_ext
    declared = (declared or "").split(";", 1)[0].strip().lower()
    if declared == "image/jpg":
        return "image/jpeg"
    return declared if declared.startswith("image/") and declared != "image/" else "image/png"


_VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".mpeg", ".mpg", ".3gp"})


def _text_reach(extracted: str, display_name: str, sent: int, total: int) -> dict | None:
    """fx5-vision (`B1284`). What the person is told about a file whose text
    the model was given — nothing when it was given whole. Read from the same
    brackets the model was handed, so the two cannot disagree (`Law 7`)."""
    text = extracted or ""
    if "[Attachment omitted from inline context:" in text:
        return {"state": "omitted", "note": (
            f"Not sent: earlier attachments filled this message's room for files "
            f"({total:,} characters).")}
    if ("[Attachment content truncated:" in text or "[Truncated]" in text
            or "[PDF content truncated]" in text or "truncated for inline context" in text):
        return {"state": "cut", "note": (
            f"Too long to send whole: the model was given the start of it "
            f"({sent:,} characters).")}
    if "[Archive attached:" in text:
        # `B1291`: an archive is listed, not read whole — said, not hidden.
        head = text[text.index("[Archive attached:"):].split("]", 1)[0]
        shown = "; the text of" in head
        return {"state": "listed", "note": (
            "Listed: the model was given the names and sizes of the files inside"
            + (", and the text of the small text files" if shown else "")
            + ". Nothing was extracted.")}
    if "— contents not read." in text:
        return {"state": "not_read", "note": (
            "Not read: there is no reader for this kind of file, so the model was "
            "not given what is in it.")}
    if "[Attached document:" in text:
        gap = text.split("—", 1)[-1].strip().rstrip("]").strip()
        if "markitdown" in gap:
            ext = os.path.splitext(display_name or "")[1].lower() or "these"
            return {"state": "not_read", "note": (
                f"Not read: {ext} files need markitdown, an optional install on this "
                "server.")}
        return {"state": "not_read", "note": "Not read: no text was found in it."}
    return None


def recording_format(path: str) -> str | None:
    """`B1290`. `"wav"` or `"mp3"` when the bytes are one — the two formats
    OpenAI's `input_audio` part names, and so the two a model that hears can be
    sent — else None. Read from the file's first bytes, not its name: a voice
    note is as often `.webm`, `.ogg` or `.m4a`, which no `input_audio` takes.
    An MP3 starts with an ID3 tag or a Layer III frame sync (`0xFFE…`, layer
    bits `01`) — an AAC ADTS frame has the sync too, with layer bits `00`."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return None
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06) == 0x02:
        return "mp3"
    return None


#: `B1290`. The words a recording given to a model as sound leaves in the
#: message, beside its `input_audio` part — read back by `unheard_turn`
#: (`B1566`), so it is written once.
HEARD_RECORDING = "\n\n[Recording attached: {name} — given to the model as sound]"
HEARD_NOTE = {"state": "heard", "note": "The model was given the recording itself."}


def recording_in_words(display_name: str, said: str = "", *, ext: str = "",
                       hears: bool = False) -> tuple[str, dict]:
    """A recording that does not reach the model as sound, in words: its
    transcript, or the sentence that it was not heard — and what the card
    under it says (`{"state", "note"}`). fx5-vision (`B1284`) wrote both
    inside `build_user_content`; `B1566` needs them again for a fallback model
    that does not hear, so they are here once. `hears` says the model hears
    and this recording's format is what kept it out (`B1290`). The transcript
    is not fitted to the inline budget here; the caller fits it."""
    if said:
        return (f"\n\n[Recording attached: {display_name} — transcript]:\n{said}",
                {"state": "transcribed", "note": "The model was given a transcript of it."})
    # `B1290`: a model that hears was not given this one because of its
    # format — said, so nobody looks for a missing setting.
    why = (f"the model takes recordings as WAV or MP3 and this one is {ext or 'neither'}"
           if hears else "the model can't be given a recording")
    # `B1571`. *No speech-to-text set up* sent a person who had set local
    # Whisper up looking for a setting they had already made, when the
    # download gate (`B1565`) had refused its model: the server's own sentence
    # says which switch, and is the note when there is one.
    refusal = _speech_to_text_refusal()
    note = (f"Not heard: {why}. {refusal}" if refusal
            else f"Not heard: {why}, and this server has no speech-to-text set up.")
    return (f"\n\n[Recording attached: {display_name} — not heard. This server "
            f"turns no speech into text, so nothing from the recording is in "
            f"this message.]",
            {"state": "not_heard", "note": note})


def _speech_to_text_refusal() -> str:
    """`B1571`. The speech-to-text service's sentence for why it transcribed
    nothing (`STTService.unheard_reason`), or `""` when it has none to give."""
    try:
        from services.stt import get_stt_service
        ask = getattr(get_stt_service(), "unheard_reason", None)
        said = ask() if callable(ask) else None
    except Exception:
        logger.debug("No speech-to-text reason to give", exc_info=True)
        return ""
    return str(said).strip() if said else ""


def unheard_turn(messages: list, recordings: list, transcripts: dict | None = None,
                 *, owner: str | None = None) -> tuple[list, dict]:
    """`B1566`. This turn as a model that does not hear is to be sent it.

    `B1290` sends a recording as sound only to the model whose endpoint said it
    hears, and a fallback that did not say so is sent `without_sounds` — the
    turn's words alone. Those words still said *given to the model as sound*,
    with no transcript beside them (none is asked for a recording the selected
    model hears), and the card still said *The model was given the recording
    itself* when that model answered. Here each such recording's bracket in
    the newest user message becomes the words it reaches this model as — its
    transcript (`transcripts`, by attachment id), fitted to the turn's inline
    budget, or the not-heard sentence — and every sound part goes.

    `recordings` are the turn's attachment records the card said were heard
    (`{"id", "name"}`). Returns the messages (copies; the session's own are not
    changed) and `{attachment id: {"state", "note"}}`, what the card says when
    this model is the one that answers."""
    from src.attachment_refs import without_sounds

    out = without_sounds(messages)
    if not recordings:
        return out, {}
    last = next((i for i in range(len(out) - 1, -1, -1)
                 if isinstance(out[i], dict) and out[i].get("role") == "user"), None)
    reach: dict = {}
    if last is None:
        return out, reach
    message = dict(out[last])
    content = message.get("content")
    total = _budget("context_attachment_total_chars", owner)
    remaining = total
    for rec in recordings:
        name = rec.get("name") or rec.get("id") or "recording"
        bracket = HEARD_RECORDING.format(name=name)
        said = ((transcripts or {}).get(rec.get("id")) or "").strip()
        words, note = recording_in_words(name, said)
        if said:
            words, remaining = _fit_inline_attachment_text(words, remaining, name, total)
        if isinstance(content, str):
            if bracket not in content:
                continue
            content = content.replace(bracket, words, 1)
        elif isinstance(content, list):
            hit = False
            parts = []
            for part in content:
                if (not hit and isinstance(part, dict) and part.get("type") == "text"
                        and bracket in str(part.get("text") or "")):
                    part = {**part, "text": str(part["text"]).replace(bracket, words, 1)}
                    hit = True
                parts.append(part)
            if not hit:
                continue
            content = parts
        else:
            continue
        reach[rec.get("id")] = note
    message["content"] = content
    out = list(out)
    out[last] = message
    return out, reach


def unread_reason(path: str, ext: str = "") -> str:
    """Why nothing was read from a file no extractor covers and whose bytes do
    not read as text — one phrase, two doors.

    `B401`. The chat's attachment note says it ("Not read: …"), and so does
    the Library when it refuses to import such a file instead of storing its
    bytes as a document of replacement characters. `B201`'s distinction holds
    at both: a short legacy-encoded text file is not "a format nothing reads".
    """
    if text_refusal_reason(path) == ENCODING_UNIDENTIFIED:
        return "its text is in an encoding that could not be identified"
    return f"there is no reader for {ext or 'this kind of'} files"


def build_user_content(
    text: str,
    attachment_ids: list[str] | None,
    upload_dir: str,
    upload_handler,
    session_id: str | None = None,
    auto_opened_docs: list[Dict[str, Any]] | None = None,
    owner: str | None = None,
    resolved_uploads: dict[str, Dict[str, Any]] | None = None,
    budget_report: dict | None = None,
    reach: dict | None = None,
    transcripts: dict | None = None,
    hears: bool = False,
    window_tokens: int = 0,
) -> str | List[Dict[str, Any]]:
    """Build user content with attachments (text, images, audio, documents).

    If session_id is provided and an attached PDF contains AcroForm fields,
    a markdown Document is auto-created so the user can edit the form in the
    editor. When `auto_opened_docs` is supplied, an entry is appended for each
    such doc so the chat route can emit a `doc_update` SSE event and the
    frontend can switch to the new doc immediately.

    fx5-vision (`B1284`). `reach`, when given, is filled with
    `{attachment id: {"state", "note"}}` for every attachment the model did not
    get whole: the one sentence the person is shown under that attachment,
    beside the bracket the model is given. `transcripts` maps an audio
    attachment's id to its speech-to-text transcript (`ChatHandler` asks the
    STT service before this runs, off the event loop).

    `B1290`. `hears` is True only when the model's endpoint said it takes a
    recording as sound (`chat_helpers.audio_answer`); a WAV or MP3 recording
    then goes as an `input_audio` part and the card says the model was given
    the recording itself. Anything else — the default — keeps the transcript
    or the sentence that it was not heard.

    `P2-08`. `window_tokens` is the turn's model's *proven* context window
    (`model_context.budget_context_for_model(url, model, fallback=0)`; `0` when
    unknown). The shared attachment total scales to it
    (`context_budget.resolve_attachment_total`); `0` keeps the ceiling as
    `P12-04` resolves it.
    """
    content = [{"type": "text", "text": text}]
    if reach is not None:
        reach.clear()
    # `P12-04` / `P12-03`. Resolved once for the whole turn and threaded into
    # every processor below, not resolved per file: a settings save or a role
    # change landing between the first attachment and the last would otherwise
    # apply two different budgets to one message. This is the same rule
    # `routes/personal_routes.py` already states for its byte cap.
    from src.context_budget import resolve_attachment_total
    _total = resolve_attachment_total(
        owner, window_tokens=window_tokens, ceiling_default=MAX_INLINE_ATTACHMENT_CHARS)
    inline_attachment_total = _total.value
    inline_attachment_remaining = inline_attachment_total
    # `P12-09`. The spend was computed and thrown away on every turn — the
    # shape `P4` closed thirteen rows of. `budget_report` is an out-parameter so
    # a caller that wants the breakdown gets the one the product actually
    # applied, rather than a second computation of it beside this loop
    # (`Law 14`). Callers that pass nothing are unaffected (`Law 1`).
    _spend: list[dict] = []
    if budget_report is not None:
        budget_report.clear()
        budget_report.update({
            "total_chars": inline_attachment_total,
            # `P2-08`: who decided the total — `window` when the model's proven
            # window did — so the composer draws the number the turn used.
            "total_source": _total.source,
            "total_clamped": bool(_total.clamped),
            "window_tokens": int(window_tokens or 0),
            "used_chars": 0,
            "remaining_chars": inline_attachment_total,
            "attachments": _spend,
        })

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
        # fx5-vision: a `.webm` is as often a video as a voice note, and the
        # extension alone sent a video down the recording arm.
        is_audio = False if (is_image or mime.startswith("video/")) else upload_handler.is_audio_file(display_name, mime)
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
        # `B1291`. Asked last, and only of a file nothing above claimed: a
        # `.docx` is a zip too, and its reader is the better answer.
        archive_text = (
            None if (is_image or is_audio or is_doc or decoded_as_text
                     or not is_zip_archive(path, display_name, mime))
            else _process_zip_archive(path, display_name, owner, inline_attachment_total)
        )

        if is_image:
            try:
                with open(path, "rb") as image_file:
                    raw_image = image_file.read()
                encoded_string = base64.b64encode(raw_image).decode("utf-8")
                # fx5-vision: the label is what the bytes are. It was
                # `image/<extension>`, so every `.jpg` — every phone photo —
                # went out as `data:image/jpg`, a type no registry names, which
                # Anthropic's `media_type` refuses (`image/jpeg`, `image/png`,
                # `image/gif`, `image/webp` only).
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_media_type(raw_image, ext, mime)};base64,{encoded_string}"},
                })
            except Exception as e:
                logger.error(f"Failed to encode image {fid}: {e}")
                if reach is not None:
                    reach[fid] = {"state": "not_read",
                                  "note": "Not sent: the picture could not be read."}
                if content and content[0]["type"] == "text":
                    content[0]["text"] += "\n\n[Image attached but could not be processed]"
                else:
                    content.insert(0, {"type": "text", "text": "[Image attached but could not be processed]"})

        elif is_audio:
            # fx5-vision (`B1284`). This sent `{"type": "audio", "audio":
            # {"url": "data:audio/…"}}` — a part no chat API names (OpenAI's is
            # `input_audio`; llama-server, LM Studio and vLLM refuse an unknown
            # type, Ollama's native path drops it, Anthropic's refuses it) — and
            # said nothing in words, so the model was not even told a recording
            # was attached and the saved message showed none. Measured on
            # `0345288` through the real route: a `.wav` and an `.mp3` reached
            # the recording model as that part and no text. A recording reaches
            # a model as words: its transcript, when the server's speech-to-text
            # gave one; otherwise the model and the person are told it was not.
            # `B1290`. A model whose endpoint says it hears is given the
            # recording itself, when it is a format `input_audio` takes.
            sound = recording_format(path) if hears else None
            said = ((transcripts or {}).get(fid) or "").strip()
            if sound:
                with open(path, "rb") as audio_file:
                    encoded_audio = base64.b64encode(audio_file.read()).decode("ascii")
                content.append({"type": "input_audio",
                                "input_audio": {"data": encoded_audio, "format": sound}})
                content[0]["text"] += HEARD_RECORDING.format(name=display_name)
                if reach is not None:
                    reach[fid] = dict(HEARD_NOTE)
            else:
                # The words and the card's sentence are `recording_in_words`'s,
                # which a fallback that does not hear is given too (`B1566`).
                words, said_note = recording_in_words(display_name, said, ext=ext, hears=hears)
                if said:
                    # `P12-04`: a transcript is text, and spends the same budget.
                    words, inline_attachment_remaining = _fit_inline_attachment_text(
                        words, inline_attachment_remaining, display_name, inline_attachment_total)
                content[0]["text"] += words
                if reach is not None:
                    reach[fid] = said_note

        elif is_doc or decoded_as_text or archive_text is not None:
            if archive_text is not None:
                extracted_text = archive_text
            elif mime == "application/pdf":
                extracted_text = None
                if session_id:
                    try:
                        from src.pdf_forms import has_form_fields, extract_fields
                        from src.pdf_form_doc import (
                            save_field_sidecar,
                            create_form_markdown_document,
                            create_plain_pdf_document,
                        )
                        # `P21-03`: the person's name, no extension
                        # (`document_title` says why), not its ASCII fold.
                        title = document_title(display_name)
                        _upload_key = upload_info.get("id") or os.path.basename(path)
                        # Pull the PDF prose once — used as either intro_text
                        # (form path) or the doc body (plain path).
                        try:
                            pdf_body_text = strip_pdf_content_marker(_process_pdf(
                                path, owner=owner,
                                ceiling=inline_attachment_total))
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
                        # `P12-04`. `context_pdf_inline_chars` — the third of
                        # the three separate 15,000s, and a different decision
                        # from how much the extractor keeps.
                        body_for_chat, truncated_marker = fit_to_context_budget(
                            (pdf_body_text or "").strip(),
                            "context_pdf_inline_chars", owner,
                            ceiling_default=MAX_INLINE_ATTACHMENT_CHARS,
                            ceiling=inline_attachment_total,
                            marker=(
                                "\n[…truncated for inline context — full text "
                                "available in the document viewer.]"
                            ),
                        )

                        if is_form:
                            fields = extract_fields(path)
                            save_field_sidecar(path, fields)
                            doc_id = create_form_markdown_document(
                                session_id=session_id,
                                fields=fields,
                                upload_id=_upload_key,
                                title=title,
                                intro_text=pdf_body_text,
                                source_name=display_name or None,
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
                                upload_id=_upload_key,
                                title=title,
                                body_text=pdf_body_text,
                                source_name=display_name or None,
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
                    extracted_text = _process_pdf(
                        path, owner=owner, ceiling=inline_attachment_total)
            elif mime.startswith("text/") or _is_text_file(path) or decoded_as_text:
                # `decoded_as_text` is the `B76` arm. It can only be true when
                # no register claimed the file, so it cannot divert anything
                # that has an extractor — it is reachable only from what used
                # to be the banner. `.svg` arrives here too, and reading its
                # source is the better answer than the image arm: it was in
                # neither `image_mime_types` nor any register, and a model that
                # sees the XML can edit it.
                extracted_text = _process_text_file(
                    path, display_name, owner, inline_attachment_total)
            else:
                extracted_text = _process_office_document(
                    path,
                    display_name,
                    session_id=session_id,
                    auto_opened_docs=auto_opened_docs,
                    owner=owner,
                    ceiling=inline_attachment_total,
                    upload_id=upload_info.get("id") or None,
                )

            _before = inline_attachment_remaining
            extracted_text, inline_attachment_remaining = _fit_inline_attachment_text(
                extracted_text,
                inline_attachment_remaining,
                display_name,
                inline_attachment_total,
            )
            if budget_report is not None:
                # Three states, not a boolean (`Law 10`): a file that fit, a
                # file cut to what was left, and a file the turn had no room
                # for at all are three different things to draw.
                if "[Attachment omitted from inline context:" in extracted_text:
                    _state = "omitted"
                elif "[Attachment content truncated:" in extracted_text:
                    _state = "truncated"
                else:
                    _state = "full"
                _spend.append({
                    "id": fid,
                    "name": os.path.basename(display_name or "attachment"),
                    "chars": _before - inline_attachment_remaining,
                    "state": _state,
                    # `B892`. What the file is — code, a document, a
                    # spreadsheet — so the composer can say so instead of
                    # calling every attachment text.
                    "kind": _attachment_kind(display_name, mime),
                })
                budget_report["remaining_chars"] = inline_attachment_remaining
                budget_report["used_chars"] = (
                    inline_attachment_total - inline_attachment_remaining)
            if reach is not None:
                _said = _text_reach(extracted_text, display_name,
                                    _before - inline_attachment_remaining, inline_attachment_total)
                if _said:
                    reach[fid] = _said
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
            if reach is not None:
                # `B401`: the two reasons are `unread_reason`'s, which the
                # Library's import refusal says too.
                if text_refusal_reason(path) == ENCODING_UNIDENTIFIED:
                    _note = f"Not read: {unread_reason(path, ext)}."
                elif mime.startswith("video/") or ext in _VIDEO_EXTS:
                    _note = "Not read: the model can't be given a video."
                else:
                    _note = (f"Not read: {unread_reason(path, ext)}, "
                             "so the model was not given what is in it.")
                reach[fid] = {"state": "not_read", "note": _note}

    # `B1290`: a recording given as sound keeps the list shape, as a picture does.
    has_media = any(item.get("type") in ("image_url", "input_audio")
                    for item in content if isinstance(item, dict))
    if not has_media and content:
        combined_text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                combined_text += item.get("text", "")
        return combined_text.strip()

    return content
