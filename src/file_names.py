# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a person's own file is called, from the moment it arrives (`P21-03`).

The owner, 2026-10-01: *"as for user uploaded documents - it must transfer the
document name. Not rename the document to some random base64 string - because
then the user can't even back-reference their own documents easily."*

Measured before this module existed, a file called ``Q3 Board Pack – final
(v2).odt`` dropped into a chat became a document titled
``a1d9182aca87476e8e1c9754dbf13105`` — the upload id, read back off the stored
path by ``_process_office_document``. Every other door had its own answer:
``secure_filename`` (``Q3_Board_Pack_final_v2``) for the chat chip, the model's
label, the PDF auto-document and the download; ``re.sub(r"[^\\w\\s\\-.]", "_")``
(``Q3 Board Pack _ final _v2_``) for an email attachment; ``splitext`` of the
raw multipart name (``../../evil``) for the two import routes; a random
ten-hex suffix on every personal upload. Five answers to one question.

This module is the one answer, in four parts that never get mixed up:

* :func:`display_name` — the name the person gave the file, made safe to
  *show*: the folder it came from is dropped, invisible characters (controls,
  bidi overrides like U+202E, zero-width marks) are removed, it is NFC
  normalised and capped. Everything visible is kept — spaces, dashes,
  parentheses, accents, other scripts.
* :func:`document_title` — the document's title: the display name without its
  extension (argued on the function).
* :func:`stored_name` — the name the file is stored under on disk: the display
  name, made safe to *store* on any filesystem this product runs on, still
  readable. Never random; :func:`create_unique` adds `` (2)`` only when two
  would collide.
* :func:`attachment_disposition` — the ``Content-Disposition`` a download
  carries: always ``attachment`` (`FORBIDDEN.md` Part 2), with the person's
  name in ``filename*=UTF-8''…``.

It is a new module rather than a change to ``upload_handler.secure_filename``
because that function is right for what else uses it: it names the per-owner
personal-upload directory (``routes/personal_routes._personal_upload_dir_for_owner``),
and making it keep Unicode would move every owner's directory on disk.

The upload id, where there is one, stays the key (URLs, references in saved
chats, the cleanup's reference scan). The readable name sits beside it; it is
never the key (``UploadHandler.save_upload`` says where on disk).
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

# A display name past this many characters is cut, keeping its extension.
# Measured: no filesystem this product ships on stores more than 255 bytes in
# one name, so a longer *display* name cannot be a name anything gave a file.
DISPLAY_NAME_MAX_CHARS = 255

# Bytes, not characters: ext4, APFS, NTFS (in UTF-16 units) and btrfs all cap
# one path component at 255, and the collision suffix `` (99)`` needs room.
STORED_NAME_MAX_BYTES = 200

# Characters Windows refuses in a file name. `/` and `\` never survive
# `display_name` (they are where the folder ends); the rest become `_`.
_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')

# Device names Windows reserves whatever the extension: `CON.txt` opens the
# console. Compared on the part before the first dot, case-folded.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{n}" for n in "0123456789¹²³"}
    | {f"LPT{n}" for n in "0123456789¹²³"}
)

# An extension is a short run after the last dot that has at least one letter
# in it. The letter is what keeps `Budget v1.5` and `Minutes 2026.10` whole:
# `splitext` would title them `Budget v1` and `Minutes 2026`.
_EXTENSION_RE = re.compile(r"\.(?=[A-Za-z0-9_+-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_+-]{0,15}$")

# Categories that draw nothing and can only mislead: Cc (controls, including
# NUL and DEL), Cf (format characters — the bidi overrides U+202A-202E and
# U+2066-2069 that make `invoice\u202eFDP.exe` render as `invoiceexe.PDF`,
# zero-width spaces and joiners, the BOM) and Cs (lone surrogates, which is
# what an undecodable byte becomes under `surrogateescape`). Removing ZWJ/ZWNJ
# loses the joined form of some emoji and some Persian words; the letters stay.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def split_extension(name: str) -> Tuple[str, str]:
    """``(stem, ext)`` where ``ext`` is a real extension or ``""``.

    A leading-dot name (``.env``) has no extension: the dot is the name.
    """
    if not isinstance(name, str) or not name:
        return "", ""
    match = _EXTENSION_RE.search(name)
    if not match or match.start() == 0:
        return name, ""
    return name[: match.start()], name[match.start():]


def display_name(raw: Any, fallback: str = "") -> str:
    """The person's own name for a file, safe to show and to store in a row.

    *raw* is whatever the browser, the mail client or the agent sent — it may
    carry a folder (``dir/sub/report.pdf``, ``C:\\Users\\me\\report.pdf``,
    ``../../evil.txt``), control characters, a bidi override or nothing at all.
    Returns *fallback* when nothing nameable is left.
    """
    if not isinstance(raw, str):
        return fallback
    name = unicodedata.normalize("NFC", raw)
    # The file's own name, without the folder it came from — either separator,
    # because a Windows path arrives in an email header as well as from an old
    # browser, and python-multipart strips only the backslash form.
    name = re.split(r"[\\/]", name)[-1]
    kept = []
    for ch in name:
        if ch.isspace():
            kept.append(" ")  # tab, newline, U+2028 — a space, not a break
        elif unicodedata.category(ch) in _INVISIBLE_CATEGORIES:
            continue
        else:
            kept.append(ch)
    name = "".join(kept).strip()
    # `.` and `..` are not names, they are directions.
    if not name or set(name) == {"."}:
        return fallback
    if len(name) > DISPLAY_NAME_MAX_CHARS:
        stem, ext = split_extension(name)
        name = stem[: DISPLAY_NAME_MAX_CHARS - len(ext)].rstrip() + ext
    return name


def document_title(raw: Any, fallback: str = "Untitled") -> str:
    """The title a document made from this file gets: its name, no extension.

    **Why the extension goes.** Every door already dropped it before this row
    (`import-pdf`, `import-office`, the library, *Import from device*, the
    mailbox, the chat opener, the auto-document) — the defect was the stem,
    not the missing suffix, and changing the convention would make half the
    library inconsistent with the other half. And a document is not the file:
    a `.docx` imported is markdown from then on, and a title reading
    `board pack.docx` would claim a format the document is no longer in. The
    name with its extension is not lost — it is kept whole as the document's
    ``source_name`` (``Document.source_name``), which is what a search for
    ``board pack.pdf`` should match (`P21-04`).
    """
    name = display_name(raw)
    if not name:
        return fallback
    stem, _ext = split_extension(name)
    return stem.strip() or name


def _cap_utf8(name: str, limit: int) -> str:
    """Cut *name* to *limit* UTF-8 bytes on a character boundary, keeping the
    extension whole when the extension itself is short enough to keep."""
    if len(name.encode("utf-8")) <= limit:
        return name
    stem, ext = split_extension(name)
    ext_bytes = len(ext.encode("utf-8"))
    if ext_bytes * 2 > limit:
        stem, ext, ext_bytes = name, "", 0
    budget = limit - ext_bytes
    cut = stem.encode("utf-8")[:budget].decode("utf-8", "ignore")
    return cut.rstrip(" .") + ext


def stored_name(raw: Any, fallback: str = "upload") -> str:
    """The name a file is stored under on disk — readable, never random.

    From :func:`display_name`, then made storable everywhere:

    * ``< > : " | ? *`` become ``_`` (Windows refuses them);
    * no leading ``.``, space or ``-``: never a dotfile (``.env``, ``.bashrc``
      — so never a name ``_resolve_tool_path``'s sensitive-directory list has
      to catch), never a name a shell command the agent runs reads as a flag;
    * no trailing ``.`` or space (Windows drops them and two names collide);
    * a reserved device name gets ``_`` after it (``CON.txt`` → ``CON_.txt``);
    * capped at :data:`STORED_NAME_MAX_BYTES`, extension kept.

    A name that matches a sensitive *file* name (``id_rsa``) is stored as given:
    ``_resolve_tool_path`` then refuses it to the agent's file tools exactly as
    it refuses every ``id_rsa``, which is the control holding, not a hole.
    Renaming it to get past that list would be the hole.
    """
    name = display_name(raw)
    name = "".join("_" if ch in _WINDOWS_FORBIDDEN else ch for ch in name)
    name = name.lstrip(" .-").rstrip(" .")
    head = name.split(".", 1)[0].rstrip(" ")
    if head.upper() in _WINDOWS_RESERVED:
        name = head + "_" + name[len(head):]
    name = _cap_utf8(name, STORED_NAME_MAX_BYTES).lstrip(" .-").rstrip(" .")
    return name or fallback


def _numbered(name: str, n: int) -> str:
    stem, ext = split_extension(name)
    return f"{stem} ({n}){ext}"


def create_unique(directory: str, name: str, *, max_tries: int = 10_000) -> str:
    """Create an empty file called *name* in *directory* and return its path.

    The name is used as given while nothing is there; when something is, the
    next free `` (2)``, `` (3)``… is taken. Created with ``O_EXCL`` so two
    writers can never be handed the same path, and checked to be a direct child
    of *directory* so a name can never place a file anywhere else.
    """
    base = os.path.realpath(directory)
    for n in range(1, max_tries + 1):
        candidate = name if n == 1 else _numbered(name, n)
        path = os.path.join(base, candidate)
        if os.path.dirname(os.path.realpath(path)) != base:
            raise ValueError("stored name escapes its directory")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return path
    raise FileExistsError(f"no free name for {name!r} in {directory!r}")


def ascii_filename(raw: Any, fallback: str = "download") -> str:
    """The display name folded to printable ASCII, safe inside a quoted header
    parameter: accents decomposed and dropped, ``"`` and ``\\`` made ``_``,
    nothing invisible (:func:`display_name` already removed it). The old
    clients' half of RFC 6266, and the only name a header that cannot carry
    ``filename*`` gets (`B1000`: the mailbox's inline-image route)."""
    def fold(text: str) -> str:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", re.sub(r'["\\]', "_", text)).strip()

    name = display_name(raw, fallback) or fallback
    stem, ext = split_extension(name)
    ascii_stem = fold(stem)
    # A name in another script folds to its extension alone — `схема.png` to
    # `.png`, which a client saving it makes a hidden file (measured on the
    # mailbox's inline images, `B1000`). The fallback stands in for the stem.
    if not ascii_stem.strip(" ."):
        ascii_stem = fallback
    return ascii_stem + fold(ext)


def attachment_disposition(raw: Any, fallback: str = "download") -> str:
    """``Content-Disposition: attachment`` naming the file as the person named it.

    Always ``attachment`` — there is deliberately no parameter for ``inline``
    (`FORBIDDEN.md` Part 2: it is the reason the upload extension blocklist is
    unnecessary). RFC 6266 form: an ASCII ``filename=`` for old clients and the
    exact name in ``filename*=UTF-8''…`` for everything since.
    """
    name = display_name(raw, fallback) or fallback
    return (
        f'attachment; filename="{ascii_filename(name, fallback)}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )


# `B1000`. One line of an outgoing message's header stays under RFC 5322's
# recommended 78 characters, so an encoded name is cut into pieces this long:
# ` filename*0*=utf-8''` is 20 characters, and 20 + 56 + `;` is 77.
_MIME_SEGMENT = 56

# A name sent as a plain quoted parameter: printable ASCII with nothing that
# needs escaping, short enough that `Content-Disposition: attachment;
# filename="…"` fits on one line. Anything else goes out RFC 2231-encoded.
_MIME_PLAIN_RE = re.compile(r'[ !#-\[\]-~]{1,%d}' % (78 - len('Content-Disposition: attachment; filename=""')))


def _mime_segments(encoded: str) -> list:
    """*encoded* cut into :data:`_MIME_SEGMENT`-sized pieces, never inside a
    ``%XX`` escape (a split escape is two broken bytes to every reader)."""
    out, i = [], 0
    while i < len(encoded):
        j = min(i + _MIME_SEGMENT, len(encoded))
        cut = encoded.rfind("%", max(i, j - 2), j)
        if j < len(encoded) and cut > i:
            j = cut
        out.append(encoded[i:j])
        i = j
    return out


def mime_attachment_disposition(raw: Any, fallback: str = "attachment") -> str:
    """The ``Content-Disposition`` of a file attached to an outgoing message,
    naming it as the person named it (`B1000`).

    The mail-header twin of :func:`attachment_disposition`, and the same name:
    :func:`display_name`, so a recipient receives ``Q3 Board Pack – final
    (v2).pdf`` — not the ``Q3 Board Pack _ final _v2_.pdf`` the mailbox's own
    regex used to send. Always ``attachment``.

    A short printable-ASCII name with nothing to escape is a plain quoted
    ``filename="…"``. Everything else — any non-ASCII letter, a quote, a
    backslash, a long name — is RFC 2231, folded onto a line of its own:
    ``filename*=utf-8''<percent-encoded>``, or past one line, continuations
    (``filename*0*=…;`` ``filename*1*=…``) one to a line, every line under 78
    characters and never split inside a ``%XX``. Measured before this: Python's own
    ``add_header(filename=…)`` writes a 250-letter Cyrillic name as one
    1,554-character header line, past RFC 5322's hard limit of 998.

    No ASCII ``filename=`` beside an encoded one: Python's parser (and so this
    product reading its own Sent folder) answers the first ``filename`` it
    finds, which would be the fold.

    **Header injection.** A sender's name can carry CR/LF (an RFC 2047 or 2231
    encoded word decodes to anything). :func:`display_name` makes every
    whitespace character a space, and a name that is not plain ASCII is
    percent-encoded whole, so nothing in the result can end the header. The
    only line breaks in it are the folds this function writes, each followed by
    a space, which is what a folded header is.
    """
    name = display_name(raw, fallback) or fallback
    if _MIME_PLAIN_RE.fullmatch(name):
        return f'attachment; filename="{name}"'
    segments = _mime_segments(quote(name, safe=""))
    if len(segments) == 1:
        return f"attachment;\n filename*=utf-8''{segments[0]}"
    params = [f"filename*0*=utf-8''{segments[0]}"]
    params += [f"filename*{n}*={seg}" for n, seg in enumerate(segments[1:], start=1)]
    return "attachment;\n " + ";\n ".join(params)


def upload_display_name(info: Dict[str, Any], fallback_path: Optional[str] = None) -> str:
    """The one name a stored upload is known by.

    `B77`: the name the model is told it received, the name the dedup key must
    distinguish on, and the name `Content-Disposition` serves are the same
    question, and were answered in three places. This is that answer, derived
    once — ``upload_handler.save_upload`` keys on it and ``build_user_content``
    renders it, so a row the dedup considers identical is by construction one
    the model would be told the same thing about.

    `P21-03`. In order: the row's ``display_name`` (every upload since this
    row); then, for a row written before it, the person's own name recovered
    from ``original_name`` — but only when its ASCII-folded form is the
    ``name`` the row was given, i.e. when it provably names the same file, so a
    row whose ``name`` was set to something else keeps it; then ``name``; then
    ``original_name`` made safe; then the stored file's basename.

    Falls back to ``basename``, not the full path: the previous
    ``... or path`` in ``build_user_content`` put the server's upload directory
    layout into the prompt whenever a row carried no name.

    Moved here from ``src/document_processor.py`` (which re-exports it) so the
    light modules that name attachments (``src/attachment_refs.py``) can ask
    the same question without importing the extractors (`Law 7`).
    """
    value = info.get("display_name")
    if isinstance(value, str) and value.strip():
        return value
    name = info.get("name")
    original = info.get("original_name")
    if isinstance(original, str) and original.strip():
        recovered = display_name(original)
        if recovered:
            if not (isinstance(name, str) and name.strip()):
                return recovered
            from src.upload_handler import secure_filename
            if secure_filename(recovered) == name:
                return recovered
    if isinstance(name, str) and name.strip():
        return name
    return os.path.basename(fallback_path or "") or ""
