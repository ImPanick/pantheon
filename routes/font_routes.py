# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom fonts: the list the theme's Font menu reads, an upload, and serving.

`P2-24`. Until this row the only way to add a font was to copy a file into
`static/fonts/custom/` on the server and reload, which is what the theme panel
told people to do. The upload lands somewhere else, on purpose — see
``UPLOADED_FONTS_DIR``.

**This is the one upload in the product whose allowlist stays, and it gets
stronger rather than lifted.** Every other upload is served back with
``Content-Disposition: attachment`` and ``nosniff``, which is why `P2-01` could
drop their blocklist: nothing a person uploads is rendered as a document. A font
is different in kind — it is fetched by the page and handed to the browser's
font parser. So the bytes must be a font, checked by what they are and not only
by what they are called, and the response must never be readable as anything
else.

**Who the adversary is (`Law 17`)**, since each control below answers one:

* **A signed-in person who is not an admin** (`P11` multi-user). Fonts are
  instance-wide — every browser on the instance loads them — so adding one is
  running the instance, not using it. ``require_admin`` (the operator tier in
  ``.pantheon/P11-AUTH-MAP.md``); single-user installs pass it as the owner.
* **A hostile file handed to an admin as "a font"** — an HTML or SVG page
  renamed ``.woff2``, a polyglot with a font's first four bytes, an SVG font.
  The name must end in one of four suffixes (``FONT_MIME_TYPES``) and the bytes
  must parse as that container (``font_extension_for``); anything else is
  refused before it is written. SVG fonts are refused by both rules: ``.svg`` is
  not a suffix here and ``<svg`` is not a font signature.
* **A crafted filename.** It reaches the filesystem and, through the family
  name, the ``@font-face`` rule ``static/js/theme.js`` writes into a
  ``<style>``. The stored name is rebuilt from ``[A-Za-z0-9_-]`` plus the
  suffix the *content* decided, so no quote, parenthesis, slash or dot from the
  original survives.
* **Not an adversary: the agent.** ``app_api`` sends JSON bodies only, and this
  route takes a multipart file; driven, a JSON body is refused with 422 and
  nothing is written.

Whatever still got through would be served ``font/<type>`` with ``nosniff`` and
``Content-Disposition: attachment`` — a font subresource ignores the
disposition, a navigation to the URL downloads it — so it is never rendered as a
page. Size is capped per request through the `P12-01` chain
(``font_upload_max_bytes``: role profile → instance setting → env → default).
"""
import os
import re
import struct
import tempfile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from src.constants import DATA_DIR, STATIC_DIR
from src.upload_limits import read_upload_limited, resolve_byte_limit

# Where fonts dropped onto the server by hand live, served by the `/static`
# mount. Anchored to `STATIC_DIR` (`P2-CORRECTED` § B): it used to be the
# relative `static/fonts/custom`, resolved against whatever directory the
# process happened to start in. Kept, so a file somebody already dropped there
# keeps working (`Law 1`); nothing here writes into it.
CUSTOM_FONTS_DIR = os.path.join(STATIC_DIR, "fonts", "custom")

# Where uploads go. **Not under `/static`**, which is what the row assumed and
# measured wrong twice: in Docker `static/` is baked into the image and is not a
# volume, so a file written there is lost on the next `up -d --build`; in the
# frozen desktop builds `STATIC_DIR` is inside PyInstaller's `_MEIPASS`, which
# `src/runtime_paths.get_default_data_dir` itself calls "the ephemeral,
# temporary extraction bundle directory". `DATA_DIR` is the one place that
# survives both. It also keeps `/static` a directory no route writes into, which
# is the premise `app._RevalidatingStatic` hashes inline scripts on.
UPLOADED_FONTS_DIR = os.path.join(DATA_DIR, "fonts")

# The four suffixes, and the one media type each is ever served as. A fixed map,
# not `mimetypes`: that table is the host's and can be anything.
FONT_MIME_TYPES = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}
FONT_EXTENSIONS = set(FONT_MIME_TYPES)
FAMILY_SUFFIX_WORDS = ("Display", "Rounded", "Serif", "Sans", "Mono", "Code", "Text")

# A stored upload's whole name. The route that serves them accepts nothing else,
# so a stray file in the directory is not reachable through it either.
_UPLOADED_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(?:woff2|woff|ttf|otf)$")
_STEM_MAX = 80
_MAX_TABLES = 512


def _split_family_token(token):
    """Split common compact font-family suffixes without breaking brand names."""
    for suffix in FAMILY_SUFFIX_WORDS:
        if token.endswith(suffix) and len(token) > len(suffix):
            return f"{token[:-len(suffix)]} {suffix}"
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', token)


def _derive_family(filename):
    """Derive a font-family name from a filename like 'JetBrainsMono-Regular.woff2' → 'JetBrains Mono'."""
    name = os.path.splitext(filename)[0]
    # Strip common weight/style suffixes
    name = re.sub(
        r'[-_ ]?(Thin|ExtraLight|UltraLight|Light|Regular|Medium|SemiBold|DemiBold|Bold|ExtraBold|UltraBold|Black|Heavy|Italic|Oblique|Variable|VF)$',
        '', name, flags=re.IGNORECASE
    )
    # Replace dashes/underscores with spaces
    name = re.sub(r'[-_]+', ' ', name).strip()
    name = " ".join(_split_family_token(part) for part in name.split())
    return name or filename


def _sfnt_is_sound(data: bytes) -> bool:
    """A TrueType/OpenType table directory that fits inside the file and has a `head`."""
    if len(data) < 12:
        return False
    num_tables = struct.unpack(">H", data[4:6])[0]
    if not 1 <= num_tables <= _MAX_TABLES or 12 + 16 * num_tables > len(data):
        return False
    tags = set()
    for i in range(num_tables):
        tag, _checksum, offset, length = struct.unpack(
            ">4sIII", data[12 + 16 * i:28 + 16 * i])
        if not all(0x20 <= b <= 0x7E for b in tag) or offset + length > len(data):
            return False
        tags.add(tag)
    return bool(tags & {b"head", b"bhed"})


def _woff_is_sound(data: bytes, header_size: int) -> bool:
    """A WOFF/WOFF2 header whose declared length is the file's length."""
    if len(data) < header_size:
        return False
    length, num_tables, reserved = struct.unpack(">IHH", data[8:16])
    return length == len(data) and 1 <= num_tables <= _MAX_TABLES and reserved == 0


def font_extension_for(data: bytes, requested_ext: str) -> str | None:
    """The suffix these bytes are a font of, or ``None`` when they are not a font.

    Signature first, then the container's own structure, because four bytes
    are easy to forge: a WOFF/WOFF2 header states the file's total length and a
    TrueType/OpenType table directory states where every table is, and a page
    with a font's first four bytes glued on satisfies neither.

    The answer is the suffix the *content* is, so a WOFF2 somebody named
    ``.ttf`` is stored and served as WOFF2 and the media type always matches the
    bytes. TrueType outlines are legitimately either ``.ttf`` or ``.otf``, so for
    those the requested suffix is kept.
    """
    head = data[:4]
    if head == b"wOF2":
        return ".woff2" if _woff_is_sound(data, 48) else None
    if head == b"wOFF":
        return ".woff" if _woff_is_sound(data, 44) else None
    if head in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        if not _sfnt_is_sound(data):
            return None
        if head == b"OTTO":
            return ".otf"
        if head == b"true":
            return ".ttf"
        return requested_ext if requested_ext in (".ttf", ".otf") else ".ttf"
    return None


def _stored_name(filename: str, ext: str) -> str:
    """The person's stem in ``[A-Za-z0-9_-]``, capped, plus the content's suffix."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:_STEM_MAX].strip("-_")
    return f"{stem or 'font'}{ext}"


def _inside(directory: str, path: str) -> bool:
    root = os.path.realpath(directory)
    return os.path.commonpath([root, os.path.realpath(path)]) == root


def _font_entries():
    """Every font the theme can offer: the hand-dropped ones, then uploads."""
    entries = {}
    try:
        os.makedirs(CUSTOM_FONTS_DIR, exist_ok=True)
    except OSError:
        pass  # a read-only bundle; the directory may still be listable
    for directory, url_prefix in ((CUSTOM_FONTS_DIR, "/static/fonts/custom/"),
                                  (UPLOADED_FONTS_DIR, "/api/fonts/custom/")):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for f in names:
            ext = os.path.splitext(f)[1].lower()
            if ext not in FONT_EXTENSIONS:
                continue
            if url_prefix == "/api/fonts/custom/" and not _UPLOADED_NAME_RE.match(f):
                continue
            # An upload with the same name as a hand-dropped file replaces it
            # in the menu; it is the one the person just chose.
            #
            # `B937`. `source` says which of the two it is, so the theme panel
            # can offer Remove on an upload and say where a hand-dropped font
            # lives — an enum rather than a flag, because "server" is not "not
            # uploaded" in any sense a reader should have to work out (`Law 10`).
            entries[f] = {"file": f, "url": f"{url_prefix}{f}", "format": ext.lstrip("."),
                          "source": "upload" if url_prefix == "/api/fonts/custom/" else "server"}
    return entries


def setup_font_routes():
    router = APIRouter(prefix="/api/fonts", tags=["fonts"])

    @router.get("/custom")
    async def list_custom_fonts():
        """Return available custom fonts grouped by derived family name.

        ``accepted`` is the upload's allowlist, so the file picker offers what
        the server takes from one list rather than a second copy of it.
        """
        families = {}
        for f, entry in sorted(_font_entries().items()):
            families.setdefault(_derive_family(f), []).append(entry)
        return {"fonts": families, "accepted": sorted(FONT_EXTENSIONS)}

    @router.post("/custom")
    async def upload_custom_font(request: Request, file: UploadFile = File(...)):
        """Add a font for everyone on this instance. `P2-24`; see the module docstring."""
        from core.middleware import require_admin
        from src.auth_helpers import get_current_user

        require_admin(request)
        data = await read_upload_limited(
            file, resolve_byte_limit("font_upload_max_bytes", get_current_user(request)),
            "Font upload")
        filename = os.path.basename(file.filename or "")
        requested_ext = os.path.splitext(filename.lower())[1]
        if requested_ext not in FONT_EXTENSIONS:
            raise HTTPException(
                400, "Only WOFF2, WOFF, TTF and OTF font files can be added.")
        ext = font_extension_for(data, requested_ext)
        if ext is None:
            raise HTTPException(400, f"{filename} isn't a font file.")

        name = _stored_name(filename, ext)
        os.makedirs(UPLOADED_FONTS_DIR, exist_ok=True)
        target = os.path.join(UPLOADED_FONTS_DIR, name)
        if not _inside(UPLOADED_FONTS_DIR, target):
            raise HTTPException(400, "That file name can't be used.")
        replaced = os.path.exists(target)
        # Written beside the target and moved into place, so a reader never
        # sees half a font. The temporary name is not a font suffix and this
        # directory is not served, so it is reachable by nothing.
        fd, tmp_path = tempfile.mkstemp(dir=UPLOADED_FONTS_DIR, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return {
            "ok": True,
            "file": name,
            "family": _derive_family(name),
            "url": f"/api/fonts/custom/{name}",
            "format": ext.lstrip("."),
            "replaced": replaced,
        }

    @router.delete("/custom/{filename}")
    async def delete_custom_font(filename: str, request: Request):
        """Remove an uploaded font, for everyone on this instance. `B937`.

        A font added by mistake could only be taken out on the server. The same
        adversary and the same controls as the upload (`Law 17`): an admin only,
        because the font is every browser's; the stored-name pattern, so only a
        file the upload route could have written is named; and the containment
        check, so the name cannot leave `DATA_DIR/fonts`. A hand-dropped font in
        `static/fonts/custom/` is the operator's file and is not removable from
        here — the panel says where it lives instead.

        Not an adversary here: the agent. Unlike the upload (a multipart body
        `app_api` cannot send), this route takes none, so the agent's loopback
        can reach it, as it reaches every delete the UI has that is not one of
        the owner's trust controls (`B896`). A font it removed is one an admin
        adds back; nothing it gains reach through.
        """
        from core.middleware import require_admin

        require_admin(request)
        if not _UPLOADED_NAME_RE.match(filename or ""):
            raise HTTPException(404, "Font not found")
        path = os.path.join(UPLOADED_FONTS_DIR, filename)
        if not _inside(UPLOADED_FONTS_DIR, path) or not os.path.isfile(path):
            raise HTTPException(404, "Font not found")
        os.remove(path)
        return {"ok": True, "file": filename, "family": _derive_family(filename)}

    @router.get("/custom/{filename}")
    async def get_custom_font(filename: str):
        """Serve one uploaded font as the type its suffix — and its bytes — are."""
        if not _UPLOADED_NAME_RE.match(filename or ""):
            raise HTTPException(404, "Font not found")
        path = os.path.join(UPLOADED_FONTS_DIR, filename)
        if not _inside(UPLOADED_FONTS_DIR, path) or not os.path.isfile(path):
            raise HTTPException(404, "Font not found")
        ext = os.path.splitext(filename)[1].lower()
        return FileResponse(
            path,
            media_type=FONT_MIME_TYPES[ext],
            headers={
                # The global middleware sets this too; a route that serves
                # bytes back says it itself rather than relying on the order.
                "X-Content-Type-Options": "nosniff",
                # Ignored for a font subresource; a navigation downloads.
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
            },
        )

    return router
