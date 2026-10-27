# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1227` — a static text file is prepared once per version, not once per request.

The app ships its frontend as files with no build step (`D-2026-09-14-04`
records the decision), served by `_RevalidatingStatic` in `app.py` under
`Cache-Control: no-cache`, so every load revalidates and every miss is a full
answer. Before this, a full answer was the file streamed through Starlette's
`GZipMiddleware`, which compresses the bytes **per request**: `style.css`
(1.6 MB) took 58 ms of compression on every miss — 78 ms to the last byte
against 20 ms uncompressed, measured with `curl` — and a cold load compressed
~9 MB of modules the same way, again for the service worker's install walk,
which fetches the whole graph a second time.

Now the mount's answer for a text file is built **once per version of the
file** — keyed by its path and the ETag `FileResponse` already derives from
its mtime and size — kept, and reused. Nothing is written beside the files
(`STATIC_DIR` stays the shipped bundle; `app.py`'s `_RevalidatingStatic`
docstring holds that no route writes into it), so a file edited on disk is a
new ETag and a new entry, and a restart starts empty.

**A miss is answered as before, and prepared behind the answer**, by one
background thread, one file at a time, once the mount has gone quiet
(`QUIET`). Preparing in the request, or at once beside it, was measured first
and was worse where it counts: the first load after a restart asks for ~165
files at once, and that load got slower. Behind the answer and after the
burst, that load is the load it was, and every one after it — another
visitor, a reload — is served from what is kept.

**What a request gets is what `GZipMiddleware` gave it.** The same
`Accept-Encoding` test (a substring, as the middleware's), the same 1024-byte
floor, the same level, the same ETag and `Last-Modified` (so a revalidation is
the same `304`), `Vary: Accept-Encoding` as the middleware adds; the response
carries `Content-Encoding`, so the middleware passes it through untouched.
A range request, a file over `LARGEST`, a type that is not text, and a file
that changed between its `stat` and its read are all served exactly as before.
A stylesheet's first answer is the file and the next ones the prepared sheet,
under one ETag: they are the same sheet to a browser, which
`tests/test_a_static_file_is_compressed_once_per_version.py` checks in
Chromium rule by rule.

**The comments.** A stylesheet's comments are emptied — `/* why */` becomes
`/**/` with its line breaks kept — only where that cannot change what the
browser does, and nowhere else. Three measured facts set the rule:

  * a comment is not whitespace: `.a/**/.b` is `.a.b`, one compound selector,
    and `.a    .b` is a descendant selector (Chromium, probed). So a comment is
    *emptied*, never blanked to spaces and never removed — the token boundary
    it made is still there, and so are the line numbers;
  * Chromium keeps a custom property's interior text, comments included:
    `--y:/* c */1px/**/2px` reads back as `1px/**/2px`; and a declaration
    holding `var()` the same way — `color: var(--x,/* c */red)` serialises
    with its comment, where `margin: 1px/* e */2px` reads `1px 2px`
    (probed). So only a comment at a **statement
    boundary** is emptied — after `{`, `}` or `;` outside any bracket, and not
    inside a custom property's value — where it belongs to no value, prelude
    or selector;
  * a comment that says `/*!`, a licence, a copyright or an SPDX identifier is
    kept whole: the notices go out with the code.

`style.css` carries 2,250 comments — the row ids and the why that the repo's
`Law`s ask for — and emptied they take its gzip from 365 KB to 193 KB, and
what the browser decodes and parses from 1,663 KB to 1,275 KB. JavaScript keeps
its comments: there is no rule like the one above for it without a parser —
`/` is division or a regular expression by grammar, not by spelling,
`Function.prototype.toString` returns source text, and the service worker's
own walk (`withoutComments`) reads the modules it fetches.
"""

from __future__ import annotations

import gzip
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.types import Scope

logger = logging.getLogger(__name__)

#: What `app.py` gives `GZipMiddleware`: a body under the floor goes out as it
#: is, and a kept answer is compressed as hard as a fresh one was.
MINIMUM_SIZE = 1024
COMPRESSLEVEL = 6

#: A file larger than this is left to stream from disk as before.
LARGEST = 8 * 1024 * 1024
#: What the kept answers may hold in all; the oldest go first past it. The
#: shipped text files take ~3 MB compressed.
BUDGET = 64 * 1024 * 1024

#: The media types prepared here: text, which compresses. Everything else
#: (fonts, pictures) goes the way it went.
TEXT_TYPES = frozenset({
    "text/css", "text/javascript", "text/html", "text/plain", "text/xml",
    "application/javascript", "application/json", "application/manifest+json",
    "application/xml", "image/svg+xml",
})


# ── A stylesheet's comments ─────────────────────────────────────────────────

_NOTICE = re.compile(r"licen[cs]e|copyright|spdx-license-identifier|©", re.I)
_LINE_BREAK = re.compile(r"\r\n|\r|\n|\f")


#: The tokens that matter to where a comment is, in the shape of CSS Syntax 3;
#: everything between two of them is ordinary text. A comment (to the end of
#: the sheet if it is never closed); a string, which a newline ends as a bad
#: string; an unquoted `url(…)`, one token to its `)`, so a `/*` in it is part
#: of the address; an escape; a custom property's name and colon; a bracket,
#: a brace or a semicolon.
_TOKEN = re.compile(
    r"/\*.*?(?:\*/|\Z)"
    r"|\"(?:[^\"\\\n\r\f]|\\[\s\S])*\"?"
    r"|'(?:[^'\\\n\r\f]|\\[\s\S])*'?"
    r"|(?<![\w\-\u0080-\U0010ffff\\])url\([ \t\n\r\f]*(?![\"' \t\n\r\f])(?:[^)\\]|\\[\s\S])*\)?"
    r"|\\[\s\S]?"
    r"|--(?:[\w\-\u0080-\U0010ffff]|\\[\s\S])*[ \t\n\r\f]*:"
    r"|[()\[\]{};]",
    re.S | re.I)
_SPACE = " \t\n\r\f"


def css_with_comments_emptied(css: str) -> str:
    """`css` with every comment at a statement boundary emptied to `/**/`
    (its line breaks kept inside), and every other character as it was.

    When it is unsure it keeps the comment: the transform only ever does
    less. One pass, ~150 ms for `style.css`, once per version of it."""
    out: list[str] = []
    copied = 0                     # css[:copied] is in `out`
    last: Optional[str] = None     # the last significant character, outside comments
    brackets = 0                   # ( and [ open
    depth = 0                      # { open
    custom_depth: Optional[int] = None   # inside a custom property's value, at this depth
    pos = 0
    for m in _TOKEN.finditer(css):
        if m.start() > pos:
            gap = css[pos:m.start()].rstrip(_SPACE)
            if gap:
                last = gap[-1]
        pos = m.end()
        tok = m.group()
        c = tok[0]
        at_boundary = last in (None, "{", "}", ";") and brackets == 0 and custom_depth is None
        if c == "/":
            if (at_boundary and len(tok) >= 4 and tok.endswith("*/")
                    and not tok.startswith("/*!") and not _NOTICE.search(tok)):
                out.append(css[copied:m.start()])
                out.append("/*" + "".join(_LINE_BREAK.findall(tok)) + "*/")
                copied = m.end()
            continue
        if c in "\"'":
            last = c
        elif c == "\\":
            last = "\\"
        elif c in "uU":
            last = ")"
        elif c == "-":
            if at_boundary:
                custom_depth = depth
            last = ":"
        else:
            if c in "([":
                brackets += 1
            elif c in ")]":
                brackets = max(0, brackets - 1)
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if custom_depth is not None and depth < custom_depth:
                    custom_depth = None
            elif c == ";" and brackets == 0 and custom_depth == depth:
                custom_depth = None
            last = c
    out.append(css[copied:])
    return "".join(out)


# ── The kept answers ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Prepared:
    etag: str
    body: Optional[bytes]       # the identity bytes, when they differ from the file's
    gzipped: Optional[bytes]    # None under MINIMUM_SIZE


_lock = threading.Lock()
_settled = threading.Condition(_lock)
_kept: "dict[str, _Prepared]" = {}
_held = 0
_pending: "set[tuple[str, str]]" = set()
_queue: "queue.SimpleQueue[tuple[str, os.stat_result, str, bool]]" = queue.SimpleQueue()
_worker: Optional[threading.Thread] = None
#: How many times a file was read and prepared — what a test counts.
prepared_count = 0
#: The worker prepares once the mount has been asked nothing for this long. A
#: page's load asks for ~165 files in waves and the service worker's walk
#: asks again after it; preparing during them was measured to cost the first
#: load after a restart 0.2–0.5 s of first paint on two cores (the stylesheet
#: pass holds the interpreter). After them it costs that load nothing.
QUIET = 0.5
_last_asked = 0.0


def _size(p: _Prepared) -> int:
    return len(p.body or b"") + len(p.gzipped or b"")


def _prepare(path: str, stat_result: os.stat_result, etag: str, rewrite: bool) -> Optional[_Prepared]:
    global prepared_count
    with open(path, "rb") as f:
        data = f.read()
        now = os.fstat(f.fileno())
    if (now.st_mtime_ns, now.st_size) != (stat_result.st_mtime_ns, stat_result.st_size) \
            or len(data) != stat_result.st_size:
        return None   # the file changed under the stat its ETag was made from
    body = data
    if rewrite:
        try:
            body = css_with_comments_emptied(data.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            body = data
    gzipped = gzip.compress(body, compresslevel=COMPRESSLEVEL, mtime=0) if len(body) >= MINIMUM_SIZE else None
    with _lock:
        prepared_count += 1
    return _Prepared(etag, body if body != data else None, gzipped)


def _remember(path: str, prepared: _Prepared) -> None:
    global _held
    with _lock:
        old = _kept.pop(path, None)
        if old is not None:
            _held -= _size(old)
        _kept[path] = prepared
        _held += _size(prepared)
        while _held > BUDGET and len(_kept) > 1:
            oldest = next(iter(_kept))
            _held -= _size(_kept.pop(oldest))


def _work() -> None:
    while True:
        path, stat_result, etag, rewrite = _queue.get()
        # Not while a load is under way: wait for the mount to go quiet.
        while (idle := time.monotonic() - _last_asked) < QUIET:
            time.sleep(QUIET - idle)
        try:
            prepared = _prepare(path, stat_result, etag, rewrite)
            if prepared is not None:
                _remember(path, prepared)
        except Exception as exc:   # the file stays served as before; say why
            logger.warning("Could not prepare %s for serving: %s", path, exc)
        finally:
            with _lock:
                _pending.discard((path, etag))
                _settled.notify_all()


def _prepare_behind(path: str, stat_result: os.stat_result, etag: str, rewrite: bool) -> None:
    global _worker
    with _lock:
        if (path, etag) in _pending:
            return
        _pending.add((path, etag))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="static-prepare", daemon=True)
            _worker.start()
    _queue.put((path, stat_result, etag, rewrite))


def settle(timeout: float = 30.0) -> bool:
    """Wait until nothing is waiting to be prepared (a test's, and a
    measurement's, way to know the next answer is a kept one)."""
    with _lock:
        return _settled.wait_for(lambda: not _pending, timeout)


def forget() -> None:
    """Drop every kept answer (a test's clean slate)."""
    global _held, prepared_count
    settle()
    with _lock:
        _kept.clear()
        _held = 0
        prepared_count = 0


async def prepared_response(response: Response, scope: Scope) -> Response:
    """The mount's answer for one file: `response` itself, or the kept bytes
    of this version of the file under `response`'s own headers."""
    global _last_asked
    _last_asked = time.monotonic()
    if not isinstance(response, FileResponse) or response.status_code != 200:
        return response
    stat_result = response.stat_result
    method = scope.get("method")
    if stat_result is None or method not in ("GET", "HEAD") or stat_result.st_size > LARGEST:
        return response
    media = (response.media_type or "").partition(";")[0].strip().lower()
    if media not in TEXT_TYPES:
        return response
    request = Headers(scope=scope)
    accepts_gzip = "gzip" in request.get("accept-encoding", "")
    rewrite = media == "text/css"
    if request.get("range") or (not rewrite and (not accepts_gzip or stat_result.st_size < MINIMUM_SIZE)):
        return response
    path = os.fspath(response.path)
    etag = response.headers["etag"]
    with _lock:
        prepared = _kept.get(path)
    if prepared is None or prepared.etag != etag:
        _prepare_behind(path, stat_result, etag, rewrite)
        return response
    if accepts_gzip and prepared.gzipped is not None:
        body, encoding = prepared.gzipped, "gzip"
    elif prepared.body is not None:
        body, encoding = prepared.body, None
    else:
        return response   # identity, and the file's own bytes: stream them as before
    headers = [(k, v) for k, v in response.raw_headers
               if k not in (b"content-length", b"accept-ranges")]
    headers.append((b"content-length", str(len(body)).encode("latin-1")))
    if encoding:
        headers.append((b"content-encoding", encoding.encode("latin-1")))
    headers.append((b"vary", b"Accept-Encoding"))
    answer = Response(content=b"" if method == "HEAD" else body, status_code=200)
    answer.raw_headers = headers
    return answer
