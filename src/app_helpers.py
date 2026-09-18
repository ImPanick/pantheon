# SPDX-License-Identifier: AGPL-3.0-or-later
# src/app_helpers.py
import base64
import hashlib
import logging
import os
from email.utils import formatdate
from html.parser import HTMLParser
from typing import NamedTuple

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.requests import Request
from starlette.staticfiles import NotModifiedResponse, StaticFiles

logger = logging.getLogger(__name__)

def read_if_exists(path: str) -> str:
    """Read file if it exists, return empty string otherwise."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def file_to_data_url(path: str, mime: str) -> str:
    """Convert file to data URL."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def abs_join(base_dir: str, rel: str) -> str:
    """Join paths and return absolute path."""
    return os.path.abspath(os.path.join(base_dir, rel))


# ── `B141`: the CSP source for an inline block is a property of its bytes ─────

# The `type` values a browser actually executes. Anything else — the
# `application/json` and `text/template` data blocks a page can carry — is
# inert markup the parser hands to script, never to the JS engine, so hashing
# it would put a source in the policy that authorises text nobody executes.
# Empty / absent means "classic script" per HTML's own rule.
_EXECUTABLE_SCRIPT_TYPES = frozenset({
    "",
    "module",
    "text/javascript",
    "application/javascript",
    "text/ecmascript",
    "application/ecmascript",
    "application/x-javascript",
    "text/jscript",
})


class _InlineScriptCollector(HTMLParser):
    """Every inline `<script>` a browser would execute, in document order.

    `HTMLParser` is used rather than a regex because the thing being read is
    what the *browser* will execute, and the two disagree in ways that matter
    here. `static/index.html:313` carries the string `<script` inside an HTML
    comment; a regex counts eight inline blocks in that file and the browser
    executes seven. A hash list that is one entry long in the wrong direction
    is a page that does not run, so the reading is done by a parser that knows
    comment state and raw-text elements — which is also what makes the ban on
    `<script src=...>` here correct: an external script matches `'self'` and
    has no inline source to hash.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._buf: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        seen = {k.lower(): (v or "") for k, v in attrs}
        if "src" in seen:
            # External: authorised by `'self'`, nothing inline to hash.
            self._buf = None
            return
        kind = seen.get("type", "").strip().lower()
        self._buf = [] if kind in _EXECUTABLE_SCRIPT_TYPES else None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag != "script":
            return
        if self._buf is not None:
            self.blocks.append("".join(self._buf))
        self._buf = None


def _csp_hash_source(script_text: str) -> str:
    """The `'sha256-…'` source that authorises exactly `script_text`."""
    digest = hashlib.sha256(script_text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def inline_script_hashes(html: str) -> tuple[str, ...]:
    """The CSP `script-src` sources that authorise this document's own inline
    scripts, and nothing else.

    Line endings are normalised first because the browser normalises them
    first: HTML's input-stream preprocessing turns CRLF and a lone CR into LF
    before the parser ever sees them, so on a CRLF checkout the bytes on disk
    and the bytes the browser hashes are different documents. Duplicates are
    collapsed — two identical blocks are one source — and order is the
    document's, so the policy reads in the order the page does.
    """
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    parser = _InlineScriptCollector()
    parser.feed(text)
    parser.close()
    out: list[str] = []
    for block in parser.blocks:
        source = _csp_hash_source(block)
        if source not in out:
            out.append(source)
    return tuple(out)


class _Page(NamedTuple):
    """One version of one served template, and everything derived from it."""

    key: tuple          # what says this is still that version
    html: str           # the source, for the `{{CSP_NONCE}}` path
    hashes: tuple       # the `'sha256-…'` sources authorising its inline blocks
    body: bytes         # the served bytes, when nothing is substituted
    etag: str           # a strong validator over exactly those bytes
    last_modified: str  # HTTP-date from the file's mtime


# path → `_Page`. `serve_html_with_nonce` is on the hot path for every
# navigation and the shell is 285 KB, so the parse, the encode and the digest
# happen once per version of the file rather than once per request; a
# revalidation costs one `stat` and a string compare. The key is the file's
# identity and mtime, so an edit in a dev checkout is picked up on the next
# request without a restart — the property `_RevalidatingStatic` exists to give
# the browser, kept on the server side of the same file.
_PAGE_CACHE: dict[str, _Page] = {}

_NONCE_PLACEHOLDER = "{{CSP_NONCE}}"


_BODY_CLOSE = "</body>"


def _source_offer_key() -> str:
    """What the injected offer depends on, for the page cache key."""
    from src.source_link import source_url

    try:
        return source_url()
    except Exception:
        return ""


def _with_source_offer(html: str, url: str) -> str:
    """Put the AGPL §13 source offer in front of whoever is using this page.

    `P0-17`. It goes here — the one front door both `/` and `/login` come
    through — rather than into the two documents, so the obligation is
    discharged in one place and a page added to `ROUTE_OWNED_STATIC_PAGES`
    tomorrow carries it without anybody remembering (`Law 13`). A licence term
    satisfied at N sites is a licence term satisfied at N-1 sites shortly
    afterwards.

    Empty when no repository address is configured, which is the shipped state
    (`D-2026-09-08-06`): the app makes no claim it cannot honour.

    Appended before the final `</body>` so it is inside the document rather
    than after it, and last so it paints over nothing. A page with no `</body>`
    is returned untouched — malformed markup is not worth a 500 on the app
    shell, and the control is absent in the same way it is absent when unset.
    """
    if not url:
        return html
    from src.source_link import source_link_html

    try:
        offer = source_link_html(url)
    except Exception:
        logger.exception("Failed to render the §13 source offer")
        return html
    if not offer:
        return html
    at = html.rfind(_BODY_CLOSE)
    if at < 0:
        logger.warning("No </body> in the served page; the §13 source link is not injected")
        return html
    return html[:at] + offer + html[at:]


def _read_page(file_path: str) -> _Page:
    """The page, its inline-script hashes and its validators, cached per
    version of the file."""
    # Part of the key and not only of the body: the offer is configuration
    # rather than file content, so an operator setting `source_url` changes the
    # served bytes with no edit to the file the rest of this key describes.
    # Left out, the cache would serve the pre-configuration page — and its
    # ETag — until a restart.
    offer_url = _source_offer_key()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            stat = os.fstat(f.fileno())
            key = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size, offer_url)
            cached = _PAGE_CACHE.get(file_path)
            if cached is not None and cached.key == key:
                return cached
            html = f.read()
    except OSError:
        logger.exception("Failed to read page %s", file_path)
        raise HTTPException(500, "Internal server error")
    html = _with_source_offer(html, offer_url)
    body = html.encode("utf-8")
    page = _Page(
        key=key,
        html=html,
        hashes=inline_script_hashes(html),
        body=body,
        # Derived from the bytes, not from `mtime`+`size` the way
        # `FileResponse` derives one: the row asks for a validator that
        # describes the template rather than the request, and a content hash
        # also survives a redeploy that rewrites mtimes and two replicas whose
        # checkouts differ by a timestamp.
        etag='"' + hashlib.sha256(body).hexdigest()[:32] + '"',
        last_modified=formatdate(stat.st_mtime, usegmt=True),
    )
    _PAGE_CACHE[file_path] = page
    return page


def serve_html_with_nonce(request: Request, file_path: str) -> Response:
    """Serve an app-bundled HTML page under a CSP that authorises its own
    inline scripts, and give the response a validator when it can have one.

    Callers pass fixed, server-owned template paths (index/login), never a
    client-supplied path. So any read failure here — a missing file (broken
    deployment) or a permission/IO error — is a server fault, not a client
    "not found": map all of them to a logged 500 so a missing core template
    surfaces in 5xx alerting instead of hiding behind a 404. If a caller
    serves a template that is *optional* — or a client-influenced path where
    404 is correct — branch that at the call site rather than defaulting this
    shared helper to 404. `GET /backgrounds` (`app.py`) is the live example:
    the sandbox page is not shipped in this build and the route answers 404
    naming it, instead of logging a stack trace per request (`B140`).

    **`B141` — why the nonce is not in the body any more.** Until 2026-09-16
    this substituted a per-request `secrets.token_hex(16)` into the 7
    `{{CSP_NONCE}}` placeholders in `index.html` and 3 in `login.html`. Those
    tokens were the only part of a 285 KB response that varied, and they cost
    the app shell its validator: a body built per request carries no ETag and
    no Last-Modified, so `/` was the one precached URL of 213 that could not
    answer a conditional request with a `304` (`B85`, `B121`). An ETag over a
    varying body is not merely useless, it is wrong — RFC 9111 §4.3.4 updates
    the stored response's headers from the `304`, which would leave a client
    holding the stored HTML with nonce A under a policy naming nonce B and
    every inline script blocked.

    The blocks are authorised by `'sha256-…'` instead, computed from the file.
    That is not a widening: a nonce authorises *whatever bytes* sit inside a
    tag carrying it, a hash authorises those bytes and no others, so an
    injection into an authorised block — or a leaked nonce — stops being
    enough. `'unsafe-inline'` is not involved in either direction, and the
    hashes are derived from the page being served rather than written down
    anywhere, so a block edited in `index.html` is re-authorised by the edit
    (`Law 13`).

    The nonce machinery is **kept, not removed** (`Law 1`): a template that
    still carries `{{CSP_NONCE}}` is still substituted, still gets a
    `'nonce-…'` source in its CSP — and, because its body then varies per
    request, correctly gets no validator.
    """
    page = _read_page(file_path)

    # The policy for THIS response, read off the document this response is.
    # `SecurityHeadersMiddleware` (core/middleware.py) picks these up after
    # `call_next` and splices them into `script-src`. Passing them through
    # `request.state` is what keeps the middleware from holding a second list
    # of which routes serve which template (`Law 14`).
    state = request.state
    state.csp_script_hashes = page.hashes

    if _NONCE_PLACEHOLDER in page.html:
        nonce = getattr(state, "csp_nonce", "")
        state.csp_nonce_used = True
        # Per-request body: no validator can describe it. This is the branch
        # `B121` measured and refused to put an ETag on.
        return HTMLResponse(page.html.replace(_NONCE_PLACEHOLDER, nonce))

    headers = {
        "ETag": page.etag,
        "Last-Modified": page.last_modified,
        # The same directive `_RevalidatingStatic` (app.py) stamps on every
        # `.html` it serves, and for the same reason: store it, but never use
        # it without asking. Without any `Cache-Control` this response had
        # *heuristic* freshness (RFC 9111 §4.2.2) — a browser was entitled to
        # paint a stale shell for days without a request.
        "Cache-Control": "no-cache",
    }
    if _is_not_modified(headers, request):
        return NotModifiedResponse(Headers(headers))
    return HTMLResponse(page.body, headers=headers)


def inline_script_hashes_for_file(file_path: str) -> tuple[str, ...]:
    """The `'sha256-…'` sources for a page on disk, cached per version of it.

    `B211`. `serve_html_with_nonce` is the route-handler front door and reads
    its page through `_read_page`; the `/static` mount serves HTML documents
    too and has no route handler to go through. This is the same `_read_page`
    — the same parse, the same digest, the same `(dev, ino, mtime_ns, size)`
    cache key — so a document served both ways is hashed once and cannot be
    hashed two different ways (`Law 14`).
    """
    return _read_page(file_path).hashes


def authorise_inline_scripts(request: Request, html: str) -> tuple[str, ...]:
    """Stamp the `'sha256-…'` sources for `html`'s inline blocks on this
    request, and return them.

    `B212`. `serve_html_with_nonce` above does this for a page read off disk;
    the docs UI is a document a **library** builds at request time, so there is
    no file to read and its bytes depend on the app's own title, the schema URL
    and the parameters passed in. Same derivation either way — the hashes are a
    property of the document being served and are written down nowhere
    (`Law 13`) — so this is the same `inline_script_hashes` call, exposed for a
    caller that already holds the HTML (`Law 14`).

    Returns the sources so a caller can assert on them; the side effect on
    `request.state` is what `SecurityHeadersMiddleware` reads after
    `call_next`.
    """
    hashes = inline_script_hashes(html)
    request.state.csp_script_hashes = hashes
    return hashes


def serve_generated_html(request: Request, html: str) -> Response:
    """Serve HTML this process just generated, under a CSP that authorises its
    own inline blocks, with a validator over exactly the bytes sent.

    The docs pages are deterministic for a given build — same routes, same
    title, same asset URLs — so they can carry an ETag for the same reason `/`
    can since `B141`: nothing in the body varies per request. The `304` path is
    safe for the same reason too, and it is not a coincidence. Both sides of
    the response are functions of the same bytes: same ETag ⟹ same document ⟹
    same hash set ⟹ same policy, so a client that updates its stored headers
    from a `304` (RFC 9111 §4.3.4) writes back the policy the stored body was
    already running under.
    """
    authorise_inline_scripts(request, html)
    body = html.encode("utf-8")
    headers = {
        "ETag": '"' + hashlib.sha256(body).hexdigest()[:32] + '"',
        "Cache-Control": "no-cache",
    }
    if _is_not_modified(headers, request):
        return NotModifiedResponse(Headers(headers))
    return HTMLResponse(body, headers=headers)


def _is_not_modified(response_headers: dict, request: Request) -> bool:
    """Whether the client's copy is still good.

    `StaticFiles.is_not_modified` is the comparison the `/static` mount
    already makes for all 212 of the other precached URLs — `If-None-Match`
    first with the weak-prefix strip, `If-Modified-Since` only when there is no
    ETag to go on. Reusing it rather than re-deriving it is the point
    (`Law 14`): two implementations of "is this conditional request
    satisfied?" is exactly the shape that lets `/` drift back out of step with
    the mount it is the front page of.
    """
    try:
        request_headers = request.headers
    except Exception:
        return False
    # Called unbound with `self=None`: the method reads only its two header
    # arguments, and instantiating a `StaticFiles` here would mean naming a
    # directory this helper has no business knowing about.
    return StaticFiles.is_not_modified(
        None, Headers(response_headers), request_headers  # type: ignore[arg-type]
    )


def inside_base_dir(base_dir: str, path: str) -> bool:
    """Check if path is inside base directory."""
    if not isinstance(base_dir, str) or not isinstance(path, str):
        return False
    base = os.path.realpath(base_dir)
    p = os.path.realpath(path)
    try:
        return os.path.commonpath([base, p]) == base
    except Exception:
        return False
