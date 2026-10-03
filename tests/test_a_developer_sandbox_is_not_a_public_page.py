# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B370` — the `/static` mount hands no page to a caller with no session.

Measured 2026-10-02 against the real app with `AUTH_ENABLED=true` and
`LOCALHOST_BYPASS=false`: `/static/wave-variants.html` (8,238 bytes),
`/static/whirlpool-variants.html` (9,731) and
`/static/modal-control-variants.html` (7,159) answered **200 to a client with
no cookie**, while `/`, `/docs` and `/backgrounds` answered `302 → /login`.
The row named two; there were three. `/static` is auth-exempt because the
login page loads its assets from it before anyone signs in (`B262`), and the
sandboxes simply lived inside that exemption with no route of their own.

**The adversary** (`Law 17`) is anyone who can reach the port of a deployment
whose source is now public: the pages hold no user data and name no API path,
and what they publish is a fingerprint. Small — stated at its real size — and
an auth boundary with a hole in it and no exemption written down is not.

**The decision, and what it keeps.** Not served to a stranger, not deleted
(`Law 1`), not admin-only (nothing in them is the operator's): they are pages
a route serves now, under `/sandbox/…`, behind the same session check as `/`.
`B262`'s table does the rest — the mount answers `/static/<name>.html` with a
302 to the route, so the URL the pages' own text gives still opens them for
anyone signed in, a single-user owner included; with auth off, nothing changed.
`B120` and `B122` need a deep-linked `/static/*.html` navigation to reach the
network and not the cached shell; it does, and the network answers with the
redirect. `.pantheon/check-auth-map.py` rule F keeps a fourth from arriving.

These drive the real app out of process (`Law 20`). The documents are
enumerated from the directory the mount serves, so the assertions are about
every page under it and not three names.
"""
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from tests.helpers.gated_app import gated_app_probe  # noqa: E402
from tests.helpers.served_pages import probe_served_surface  # noqa: E402
# `Law 14`: the suite's one reading of "what does a browser execute" and "what
# does the policy allow" (`B141`), as the CDN scan imports it.
from test_app_shell_csp_hashes import _hash_source, _inline_blocks, _script_src  # noqa: E402

_SANDBOXES = {
    "wave-variants.html": "/sandbox/wave-variants",
    "whirlpool-variants.html": "/sandbox/whirlpool-variants",
    "modal-control-variants.html": "/sandbox/modal-control-variants",
}

_PROBE = r'''
import hashlib, mimetypes, pathlib, re
from urllib.parse import urlparse
from src.constants import STATIC_DIR

# The AGPL §13 offer rides on every route-served page and, since
# `D-2026-10-02-04` §2, it is drawn by default — so "the page's bytes" are the
# served bytes with that one injected control taken out, and whether it was
# there is recorded beside them.
_OFFER = re.compile(rb'<div class="pan-source-offer"[^>]*>.*?</a></div>', re.S)

# Every page under the mount, from the directory it serves — not a list.
# `mimetypes` is the table `StaticFiles` answers with.
docs = sorted(p.relative_to(STATIC_DIR).as_posix()
              for p in pathlib.Path(STATIC_DIR).rglob("*")
              if p.is_file() and mimetypes.guess_type(p.name)[0]
              in ("text/html", "application/xhtml+xml"))
RESULT["documents"] = docs
RESULT["file_sha"] = {d: hashlib.sha256((pathlib.Path(STATIC_DIR) / d).read_bytes()).hexdigest()
                      for d in docs}
RESULT["exempt_exact"] = sorted(app_module.AUTH_EXEMPT_EXACT)

def direct(c, url):
    res = c.get(url, follow_redirects=False)
    return {"status": res.status_code, "location": res.headers.get("location"),
            "bytes": len(res.content)}

def followed(c, url):
    res = c.get(url, follow_redirects=True)
    html = "text/html" in res.headers.get("content-type", "")
    return {"status": res.status_code, "path": urlparse(str(res.url)).path,
            "hops": [urlparse(str(h.url)).path for h in res.history],
            "sha": hashlib.sha256(_OFFER.sub(b"", res.content, count=1)).hexdigest(),
            "offer": bool(_OFFER.search(res.content)),
            "csp": res.headers.get("content-security-policy", ""),
            "body": res.text if html else ""}

for label, who in CALLERS:
    c = client(who)
    RESULT[label] = {d: {"direct": direct(c, "/static/" + d),
                         "followed": followed(c, "/static/" + d)} for d in docs}

anon = client(None)
RESULT["anonymous_routes"] = {r: direct(anon, r) for r in %(routes)r}
RESULT["anonymous_spellings"] = {u: direct(anon, u) for u in (
    "/static/WAVE-VARIANTS.HTML", "/static/./wave-variants.html",
    "/static//wave-variants.html", "/static/wave-variants.html/",
    "/static/Modal-Control-Variants.html")}
# The login page's own assets, which the exemption exists for, still answer.
RESULT["login_css"] = direct(anon, "/static/style.css")
''' % {"routes": sorted(_SANDBOXES.values())}


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b370"), _PROBE)


def test_the_probe_is_gated_and_sees_every_page_under_the_mount(probe):
    """The premise. A probe with auth off, or one that enumerated nothing,
    would pass everything below."""
    assert probe["premise"]["auth_enabled"] is True, probe["premise"]
    assert probe["premise"]["localhost_bypass"] is False, probe["premise"]
    for name in ["index.html", "login.html", *_SANDBOXES]:
        assert name in probe["documents"], probe["documents"]


def test_no_page_under_the_mount_is_served_by_the_mount_to_a_stranger(probe):
    """`B370`'s `Verify:` and the class with it. Every page under `static/`
    answers a caller with no cookie with a redirect and no bytes — never the
    page. Fails on the tree before the fix: the three sandboxes answered 200."""
    for doc in probe["documents"]:
        row = probe["anonymous"][doc]["direct"]
        assert row["status"] == 302, (doc, row)
        assert row["bytes"] == 0, (doc, row)


def test_a_stranger_gets_a_page_only_from_a_route_the_exemption_list_names(probe):
    """Followed to the end the way a browser follows it. The bytes of a page
    under `static/` reach a caller with no session only when the route that
    serves them is written in `AUTH_EXEMPT_EXACT` — which is `/login`, and
    that is the point of it. For every other page the chain ends at the login
    page."""
    exempt = set(probe["exempt_exact"])
    for doc in probe["documents"]:
        end = probe["anonymous"][doc]["followed"]
        if end["sha"] == probe["file_sha"][doc]:
            assert end["path"] in exempt, (doc, end["path"])
        else:
            assert end["path"] == "/login", (doc, end["path"], end["hops"])
    for doc, route in _SANDBOXES.items():
        end = probe["anonymous"][doc]["followed"]
        assert end["hops"] == [f"/static/{doc}", route], (doc, end["hops"])
        assert end["path"] == "/login", (doc, end)


def test_the_sandbox_routes_need_a_session(probe):
    """Asked directly, not through the mount."""
    for route, row in probe["anonymous_routes"].items():
        assert row["status"] == 302, (route, row)
        assert row["location"] == "/login", (route, row)


def test_no_spelling_of_a_sandbox_walks_around_the_rule(probe):
    """`B262`'s fold — normpath and casefold — covers the new entries the same
    way: whatever spelling reaches the file goes to the route."""
    for url, row in probe["anonymous_spellings"].items():
        assert row["status"] == 302, (url, row)
        assert row["location"].startswith("/sandbox/"), (url, row)


@pytest.mark.parametrize("who", ["member", "admin"])
def test_anyone_signed_in_still_opens_every_page_at_the_url_it_gives(probe, who):
    """`Law 1`. Nothing is taken away: the URL the sandboxes' own text names —
    `/static/<name>.html` — still opens the page, byte for byte, for a member
    and for the admin a single-user owner is. Signed in is the bar; nothing in
    them is the operator's, so it is not admin-only."""
    for doc in probe["documents"]:
        end = probe[who][doc]["followed"]
        assert end["status"] == 200, (who, doc, end["path"])
        assert end["sha"] == probe["file_sha"][doc], (who, doc, end["path"])
        # And the §13 source offer rides on it, as on every route-served page.
        assert end["offer"], (who, doc, end["path"])
    for doc, route in _SANDBOXES.items():
        assert probe[who][doc]["followed"]["path"] == route, (who, doc)


def test_a_sandbox_still_runs_when_its_route_serves_it(probe):
    """`B211`'s property, carried across the move. `wave-variants.html` and
    `whirlpool-variants.html` are each driven by one inline block, and a
    policy that does not name its hash renders an empty frame — which is what
    they did for their whole lives before `B211`. (`modal-control-variants.html`
    is markup and CSS only, and has no block to authorise.) Read with the
    suite's own inline-script reader (`B141`), not the server's."""
    for doc in _SANDBOXES:
        end = probe["member"][doc]["followed"]
        blocks = _inline_blocks(end["body"])
        if doc in ("wave-variants.html", "whirlpool-variants.html"):
            assert blocks, (doc, "no inline block found — this page is its block")
        script_src = _script_src(end["csp"])
        for block in blocks:
            source = _hash_source(block.replace("\r\n", "\n").replace("\r", "\n"))
            assert source in script_src, (doc, source)


def test_what_the_exemption_is_for_still_answers_a_stranger(probe):
    """The way this fix breaks if it is done at the mount: the login page's
    stylesheet must still load with no session (`B262` asserts every asset
    the login page names; this is the one-line canary beside the change)."""
    assert probe["login_css"]["status"] == 200, probe["login_css"]


@pytest.fixture(scope="module")
def surface(tmp_path_factory):
    """The served surface with auth off — the one enumerator (`B260`)."""
    return probe_served_surface(tmp_path_factory.mktemp("served_surface"))


def test_with_auth_off_the_sandboxes_are_pages_the_surface_scans(surface):
    """With auth off nothing changed for the person opening them, and the
    suite's CDN and CSP scans (`B211`, `B212`) still read them: they iterate
    every page the app answers 200 with, and the sandboxes are now that at
    their routes, while their `/static` URL is the redirect."""
    pages = surface["pages"]
    for doc, route in _SANDBOXES.items():
        assert pages[route]["status"] == 200, (route, pages.get(route))
        assert pages[route]["is_html"], route
        assert pages["/static/" + doc]["status"] == 302, doc
        assert pages["/static/" + doc]["location"] == route, doc
        on_disk = (ROOT / "static" / doc).read_bytes()
        # The page as the file has it, the §13 offer aside (drawn by default
        # since `D-2026-10-02-04` §2 — and asserted to be there).
        body, offers = re.subn(r'<div class="pan-source-offer"[^>]*>.*?</a></div>', "",
                               pages[route]["body"], count=1, flags=re.S)
        assert offers == 1, route
        assert hashlib.sha256(body.encode("utf-8")).digest() == \
            hashlib.sha256(on_disk).digest(), route
