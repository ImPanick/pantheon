# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nothing this app serves reaches for a host nobody chose — asked of the app.

`B212`. `P16-07` and `P16-08` spent two rows removing every third-party host
from the served frontend, and the guard they left behind —
`test_no_cdn_anywhere_in_served_frontend`, in `tests/test_vendored_pyodide.py`
— scanned `static/**`. That is where the files are; it is not where the
**pages** are. FastAPI built `/docs` and `/redoc` from a library at request
time, and those two documents named `cdn.jsdelivr.net`, `fonts.googleapis.com`
and `fastapi.tiangolo.com` for as long as the app has existed, in the one part
of the served surface a file scan cannot see. Measured 2026-09-16 against the
real app before the fix: `/docs` 200 naming two of those hosts, `/redoc` 200
naming three.

So the question is asked of the **running app** here: enumerate every GET route
that takes no path parameter, add every HTML document under the `/static`
mount — which is a `Mount` and therefore in nobody's route table — and read
what comes back. `tests/helpers/served_pages.py` is that enumerator, and it is
the one that already existed for `B120` rather than a second one (`Law 14`).

`B211` rides the same enumeration, because it is the same question one layer
in: a page is only served honestly if the policy it is served with authorises
the inline blocks it ships. `static/wave-variants.html` and
`static/whirlpool-variants.html` are *entirely* one inline block each and the
app CSP refused both, so they were 200s that rendered an empty frame.

**What is not claimed here.** These tests prove the served bytes name no
external host, that every subresource they do name answers from this origin,
and that every inline block they ship is authorised by that response's own
policy. They do not prove a browser paints the result — there is no browser in
this environment, and the same limit applies to `test_vendored_pyodide.py`,
which asserts the policy permits WebAssembly rather than compiling any.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from tests.helpers.served_pages import probe_served_surface, same_origin_refs  # noqa: E402

# `Law 14`: the two readings this suite already has of "what does a browser
# execute" and "what does the policy allow" live in the `B141` test, and the
# comment stripper the CDN scan has always used lives in the Pyodide one.
# Importing them is what keeps three files from disagreeing about what a script
# is.
from test_app_shell_csp_hashes import _hash_source, _inline_blocks, _script_src  # noqa: E402
from test_vendored_pyodide import strip_comments  # noqa: E402


# Positions a browser fetches from **without the user choosing**. `<a href>` is
# deliberately absent: a link the person clicks is the user explicitly linking
# an external service, which is the thing `Law 16` permits. A stylesheet, a
# script, an icon or a font is not.
_SRC_TAGS = re.compile(
    r"""<(?:script|img|iframe|source|video|audio|embed|track|input)\b[^>]*?"""
    r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I | re.S)
_LINK_HREF = re.compile(r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", re.I | re.S)
_OBJECT_DATA = re.compile(r"""<object\b[^>]*?\bdata\s*=\s*["']([^"']+)["']""", re.I | re.S)
_CSS_URL = re.compile(r"""\burl\(\s*['"]?\s*((?:https?:)?//[^'")\s]+)""", re.I)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]((?:https?:)?//[^'"]+)""", re.I)

# An absolute or scheme-relative URL. `data:`, `blob:` and `/...` are this
# origin or no origin at all and never leave the machine.
_LEAVES = re.compile(r"^\s*(?:[a-z][a-z0-9+.\-]*:)?//", re.I)

# The three hosts two closed rows and this one removed by name. The general
# rule above subsumes these; they are listed anyway so a regression says which
# row came back rather than only that something did.
_NAMED_REGRESSIONS = ("cdn.jsdelivr.net", "fonts.googleapis.com",
                      "fastapi.tiangolo.com", "unpkg.com", "fonts.gstatic.com")


def _fetching_urls(html: str) -> list:
    """Every URL this document makes the browser fetch on its own."""
    text = strip_comments(html, html=True)
    out = []
    for pattern in (_SRC_TAGS, _LINK_HREF, _OBJECT_DATA, _CSS_URL, _CSS_IMPORT):
        out.extend(pattern.findall(text))
    return out


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> dict:
    return probe_served_surface(tmp_path_factory.mktemp("served_surface"))


def test_the_scan_is_asking_the_app_and_not_an_empty_list(served):
    """The failure mode every derived check in this repo has had to pin.

    A scan that enumerates nothing passes every assertion below. This states
    what the enumeration must contain: the app shell, the login page, the two
    prototype documents that are only reachable through the `/static` mount,
    and FastAPI's own docs routes — the four kinds of served page this file
    exists to cover.
    """
    pages = served["pages"]
    assert len(pages) >= 19, sorted(pages)
    for required in ("/", "/login", "/docs", "/redoc", "/openapi.json",
                     "/static/wave-variants.html", "/static/whirlpool-variants.html"):
        assert required in pages, (required, sorted(pages))
    html = [u for u, row in pages.items() if row["is_html"]]
    assert len(html) >= 5, html
    # And the second pass found subresources to resolve, or the test below is
    # about nothing.
    assert len(served["refs"]) >= 5, sorted(served["refs"])


def test_no_cdn_anywhere_in_served_frontend(served):
    """The whole served surface, asked of the server rather than of the disk.

    Two halves, and the row is that there used to be one. The file half is what
    this test has always been — kept, not replaced (`Law 1`) — and it is now
    the weaker of the two: it reads `static/**`, which is every byte the app
    ships and no byte it generates. The app half asks the running server for
    every page it will actually serve and reads what came back.

    Fails on `HEAD`: `/docs` named `cdn.jsdelivr.net` and
    `fastapi.tiangolo.com`, `/redoc` named `cdn.jsdelivr.net`,
    `fonts.googleapis.com` and `fastapi.tiangolo.com`.
    """
    offenders = {}

    for path in list((ROOT / "static").rglob("*.js")) + list((ROOT / "static").rglob("*.html")):
        if "static/lib" in path.as_posix():
            continue  # vendored bundles carry their own upstream URLs internally
        code = strip_comments(path.read_text(encoding="utf-8", errors="replace"),
                              html=path.suffix == ".html")
        named = [h for h in _NAMED_REGRESSIONS if h in code]
        if named:
            offenders[str(path.relative_to(ROOT))] = named

    for url, row in sorted(served["pages"].items()):
        if not row["body"]:
            continue
        leaving = sorted({u for u in _fetching_urls(row["body"]) if _LEAVES.match(u)})
        named = sorted({h for h in _NAMED_REGRESSIONS if h in strip_comments(row["body"], html=True)})
        if leaving or named:
            offenders[url] = {"fetches": leaving, "named hosts": named}

    assert not offenders, f"served surface reaches for hosts nobody chose: {offenders}"


def test_every_subresource_a_served_page_names_answers_from_this_origin(served):
    """A vendoring is only a vendoring if the local URL resolves.

    Repointing `/docs` at `/static/lib/swagger-ui/...` and not shipping the
    bytes passes the scan above and leaves exactly the page it started with —
    blank, and now blank with no explanation. This is the assertion that tells
    the two apart, and it is the same trap `test_code_runner_references_no_cdn`
    guards on the Pyodide side, where repointing `script.src` and leaving
    `indexURL` alone left three of five files remote.
    """
    missing = {url: row["status"] for url, row in served["refs"].items()
               if row["status"] != 200}
    assert not missing, f"a served page names a URL this app does not answer: {missing}"


def test_every_inline_block_on_a_served_page_is_authorised(served):
    """`B211`'s `Verify:`, for every HTML document this app serves.

    `B141` gave `/` and `/login` a `'sha256-…'` source per inline block, and it
    did it at `serve_html_with_nonce` — the route handlers' front door. The
    `/static` mount has no route handler, so the documents it serves went out
    under a `script-src` that named hashes and therefore refused every block it
    did not name. `static/wave-variants.html` and
    `static/whirlpool-variants.html` are one inline block each and that block
    *is* the page: whirlpool builds all four variant cards from
    `document.getElementById('grid')`, wave animates `#hero-preview`.

    Fails on `HEAD` for both, with the block's own hash absent from the policy
    the page was served with.
    """
    unauthorised = {}
    for url, row in sorted(served["pages"].items()):
        if not row["is_html"] or row["status"] != 200:
            continue
        csp = row["csp"]
        assert csp, f"{url} served HTML with no Content-Security-Policy"
        script_src = _script_src(csp)
        for block in _inline_blocks(row["body"]):
            source = _hash_source(block.replace("\r\n", "\n").replace("\r", "\n"))
            if source not in script_src:
                unauthorised.setdefault(url, []).append(source)
    assert not unauthorised, (
        "inline blocks a browser would refuse on a page this app serves: "
        f"{unauthorised}")


def test_a_304_carries_the_same_authorisation_as_the_200_it_replaces(served):
    """The half of `B211` that only shows up on the second request.

    A conditional request for an unchanged page is answered with headers and
    no body, and RFC 9111 §4.3.4 says the client updates its **stored**
    response's headers from that `304`. So a `304` whose
    `Content-Security-Policy` names no hash does not merely fail to help — it
    overwrites a good policy with one that authorises nothing, and the next
    time the user opens the page from cache it paints and does nothing. That
    is the failure `B121` refused to ship for `/`, and the `/static` mount
    reaches it by a different road: `StaticFiles.file_response` throws the
    `FileResponse` away and returns a `NotModifiedResponse`, so a hook that
    reads the response's file path sees a 304 it cannot identify a page from.
    """
    checked = 0
    for url, row in sorted(served["pages"].items()):
        if not row["is_html"] or row["status"] != 200 or not row.get("conditional"):
            continue
        blocks = _inline_blocks(row["body"])
        if not blocks:
            continue
        conditional = row["conditional"]
        assert conditional["status"] == 304, (url, conditional)
        assert conditional["bytes"] == 0, (url, conditional)
        for block in blocks:
            source = _hash_source(block.replace("\r\n", "\n").replace("\r", "\n"))
            assert source in _script_src(conditional["csp"]), (url, source, conditional["csp"])
        checked += 1
    assert checked >= 3, f"only {checked} pages exercised the conditional path"


def test_the_policy_that_authorises_them_did_not_get_looser(served):
    """The other way to make the test above pass, and the one that must fail.

    `'unsafe-inline'` in `script-src` authorises every block on the page at
    once — and a browser *ignores* it whenever a hash or nonce source is
    present, so a policy carrying both reads safe and behaves safe right up
    until the hashes are removed. `B141` landed without it deliberately;
    nothing here may put it back, and nothing may reach for a host either.
    """
    for url, row in sorted(served["pages"].items()):
        if not row["csp"]:
            continue
        script_src = _script_src(row["csp"])
        assert "'unsafe-inline'" not in script_src, (url, script_src)
        assert "'unsafe-eval'" not in script_src, (url, script_src)
        assert "//" not in script_src, (url, script_src)
        assert "'nonce-" not in script_src, (url, script_src)
        for host in _NAMED_REGRESSIONS:
            assert host not in row["csp"], (url, host)


def test_the_api_schema_the_agent_discovers_with_is_still_served(served):
    """Why `openapi_url` is not among the things switched off.

    `B212` offers `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` as
    one of its two outcomes. The third of those has a caller in this tree:
    `src/tools/system.py`'s `do_app_api` with `action: "endpoints"` fetches
    `{base}/openapi.json` over the loopback with the internal-tool header, and
    it is how the agent discovers every endpoint it is allowed to call. Turning
    it off is not a tightening, it is removing a shipped tool (`Law 1`), so the
    schema stays and this is the line that says a later cleanup may not take it.
    """
    row = served["pages"]["/openapi.json"]
    assert row["status"] == 200, row
    assert "json" in row["content_type"], row
    assert '"paths"' in row["body"][:400], row["body"][:200]

    source = (ROOT / "src" / "tools" / "system.py").read_text(encoding="utf-8")
    assert "/openapi.json" in source, (
        "nothing in the tree consumes the schema any more — re-decide the row "
        "rather than leaving a 344 KB API map served for no reader")


def test_the_api_browser_is_served_from_this_origin(served):
    """`B212`'s decision, pinned so it cannot be quietly reversed either way.

    Either `/docs` is a real API browser built from bytes this repo ships, or
    the row was answered "no docs" and this test should have gone with it. It
    is the first: the page loads exactly two subresources, both under
    `/static/lib/swagger-ui/`, and both are in the licence inventory.
    """
    docs = served["pages"]["/docs"]
    assert docs["status"] == 200, docs
    refs = sorted(set(same_origin_refs(docs["body"])))
    assert "/static/lib/swagger-ui/swagger-ui-bundle.js" in refs, refs
    assert "/static/lib/swagger-ui/swagger-ui.css" in refs, refs
    for ref in refs:
        assert served["refs"].get(ref, served["pages"].get(ref, {})).get("status") == 200, ref

    # ReDoc is not vendored and the route says so rather than serving a blank
    # page that names three hosts (`B140`'s shape). If someone vendors it, this
    # is the line that has to change with the route.
    redoc = served["pages"]["/redoc"]
    assert redoc["status"] == 404, redoc
    assert "/docs" in redoc["body"], redoc["body"]


def test_the_vendored_api_browser_is_the_bytes_that_were_pinned():
    """A vendored bundle nobody re-hashes is a bundle nobody would notice
    changing — the same check `test_vendored_bytes_match_the_pinned_hashes`
    makes for Pyodide, run for these two files."""
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch-swagger-ui.py"),
                        "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_licence_paperwork_shipped_with_the_swagger_bytes():
    """`check-licences.py` rule 1 fails on an undeclared file under
    `static/lib/`, which is how OpenMoji was found. Adding 1.7 MB of Apache-2.0
    JavaScript means adding its licence, which means having read it."""
    import subprocess
    assert (ROOT / "licenses" / "SwaggerUI-Apache-2.0.txt").is_file()
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    assert "static/lib/swagger-ui" in credits
    assert "SwaggerUI-Apache-2.0.txt" in credits
    r = subprocess.run([sys.executable, str(ROOT / ".pantheon" / "check-licences.py"),
                        "--quiet"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
