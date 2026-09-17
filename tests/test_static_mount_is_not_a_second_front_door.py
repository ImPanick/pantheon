# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B262` — the `/static` mount does not hand out a document a route owns.

Measured 2026-09-16 against the real app with `AUTH_ENABLED=true`: `GET /` was
`302 → /login`, `GET /docs` was `302 → /login`, and **`GET /static/index.html`
was 200 with all 292,260 bytes of the app shell**; `/static/login.html` was 200
as well. The `/static` prefix is in `AUTH_EXEMPT_EXACT`'s sibling
`AUTH_EXEMPT_PREFIXES` and has to be — the login page's stylesheet, its modules
and its fonts all load from there before anyone is logged in — and
`static/index.html` simply lived inside that exemption.

**Stated honestly, that was not a data bypass.** The shell is markup and
JavaScript and every call it makes is a separate request `AuthMiddleware` still
gates, so a caller who took it got the UI and nothing behind it. What they did
get is the entire frontend — every panel, every endpoint path the modules
fetch, every feature flag rendered into the document — from an unauthenticated
port, plus a **second URL for the app shell** that `static/sw.js` deliberately
excludes: `B120` narrowed the navigation handler precisely so a
`/static/*.html` navigation is never answered with the shell, and the shell was
at a `/static/*.html` URL.

**The fix and the way it could have gone wrong.** `/static/**` is one mount and
the login page needs nearly all of it *while logged out*, so a rule that gated
the mount would lock everyone out of the page they log in on. The rule is
therefore not about auth at all: three filenames under the mount are documents
a **route** serves, and the mount redirects those three to their route
(`ROUTE_OWNED_STATIC_PAGES` in `app.py`). Every other byte under `/static` is
served exactly as before, unauthenticated, including the two `*-variants.html`
prototypes `B120` and `B122` both require to keep reaching the network.

So this file asserts both halves, because the second is the way this fix
breaks: the shell is not reachable without a session, **and** everything the
login page loads still is.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from tests.helpers.served_pages import probe_served_surface  # noqa: E402

_SHELL = ROOT / "static" / "index.html"

# Documents under the mount that a route serves, and the route. Read from the
# app rather than written out again — `Law 13`: the table is the thing under
# test, so a test holding its own copy would agree with itself.
_PROBE = r'''
import json
import re
from urllib.parse import urljoin, urlparse

import app as app_module
from fastapi.testclient import TestClient

client = TestClient(app_module.app)
mounted = TestClient(app_module.app, root_path="/pantheon")

# Every path under `static/` this document names in a quoted string: `src`,
# `href`, a CSS `url()` and the computed `import()` the login page uses for
# `theme.js` all land in one. Quoted on purpose — the same paths appear in this
# page's comments unquoted, and a comment is not a request.
ASSET = re.compile(r"""["']([^"'\s>]*static/[^"'\s>]*\.(?:js|css|png|svg|woff2|json))["']""")


def direct(c, url):
    res = c.get(url, follow_redirects=False)
    return {"status": res.status_code, "location": res.headers.get("location"),
            "bytes": len(res.content)}


def followed(c, url):
    res = c.get(url, follow_redirects=True)
    return {"status": res.status_code, "bytes": len(res.content),
            "path": urlparse(str(res.url)).path,
            "hops": [urlparse(str(h.url)).path for h in res.history],
            "head": res.text[:400]}


# The three documents under the mount that a route serves. Named here rather
# than read out of `app.py` so that this probe boots — and every measurement
# below is taken — on a tree that has no such table, which is the tree these
# assertions have to be able to fail on (`Law 9`).
NAMES = ["index.html", "login.html", "backgrounds.html"]
owned = getattr(app_module, "ROUTE_OWNED_STATIC_PAGES", None)
urls = ["/", "/login", "/docs"] + ["/static/" + name for name in NAMES]
# The same three asked for in the spellings a filesystem or a URL normaliser
# would fold together.
variants = ["/static/INDEX.HTML", "/static/./index.html", "/static//index.html",
            "/static/index.html/", "/static/Login.HTML"]
# What the login page itself loads. Unauthenticated, because that is when it is
# read: a caller with no session is redirected to it and it has to work.
login = client.get("/login", follow_redirects=False)
assets = sorted({urljoin("http://testserver/login", ref)
                 for ref in ASSET.findall(login.text)})

out = {
    "auth_enabled": bool(app_module.AUTH_ENABLED),
    "owned": dict(owned) if owned else None,
    "direct": {u: direct(client, u) for u in urls + variants},
    "followed": {u: followed(client, u) for u in urls},
    "login_assets": {urlparse(u).path: direct(client, urlparse(u).path)
                     for u in assets},
    # Bytes and not characters: everything else here is `len(res.content)`,
    # and the login page carries enough non-ASCII to make the two differ by 34.
    "login_bytes": len(login.content),
    "root_path": {u: direct(mounted, "/pantheon" + u)
                  for u in ["/static/" + name for name in NAMES]},
}
print("RESULT=" + json.dumps(out, sort_keys=True))
'''


@pytest.fixture(scope="module")
def gated(tmp_path_factory) -> dict:
    """The real app with `AUTH_ENABLED=true`, asked what it hands a caller with
    no session.

    Out of process because `AUTH_ENABLED` is read once at import and importing
    `app` pulls the whole application up — the same shape as every other probe
    in this suite.
    """
    tmp_path = tmp_path_factory.mktemp("gated_surface")
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true",
        # Not incidental. `_is_trusted_loopback` is false for the test client's
        # host, but a tree that turned this on by default would answer every
        # request below without ever consulting the session.
        "LOCALHOST_BYPASS": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(ROOT), env=env,
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))


def test_the_gate_is_actually_on_in_this_probe(gated):
    """The premise every assertion below rests on.

    A probe that booted with auth off would find `/` serving the shell, agree
    with itself that `/static/index.html` serves the same thing, and prove
    nothing. This states what the app under test is: auth enabled, and `/`
    answering a caller with no session with a redirect rather than a page.
    """
    assert gated["auth_enabled"] is True
    root = gated["direct"]["/"]
    assert root["status"] == 302, root
    assert root["location"] == "/login", root
    assert root["bytes"] == 0, root
    # And the login page is served, or the redirect above is a dead end.
    assert gated["direct"]["/login"]["status"] == 200
    assert gated["login_bytes"] > 1000, gated["login_bytes"]


def test_the_app_shell_is_not_handed_to_a_caller_with_no_session(gated):
    """`B262`'s `Verify:`, driven against the real app.

    Fails on the tree as it stood: `/static/index.html` answered 200 with
    292,260 bytes and `/static/login.html` answered 200 with 31,257, to a
    client carrying no cookie at all.
    """
    shell_bytes = _SHELL.stat().st_size
    assert shell_bytes > 200_000, shell_bytes  # the file this is about

    for url, owner in (("/static/index.html", "/"), ("/static/login.html", "/login")):
        row = gated["direct"][url]
        assert row["status"] == 302, (url, row)
        assert row["location"] == owner, (url, row)
        assert row["bytes"] == 0, (url, row)

    # The whole chain, followed the way a browser follows it: a caller who
    # asks for the shell by its file name ends on the login page, and the
    # shell's bytes never appear anywhere along the way.
    chain = gated["followed"]["/static/index.html"]
    assert chain["path"] == "/login", chain
    assert chain["hops"] == ["/static/index.html", "/"], chain
    assert chain["bytes"] == gated["login_bytes"], chain
    assert chain["bytes"] < shell_bytes / 2, chain

    # `/login` is a real document and reaching it by either road is the same
    # page — the redirect is not a way to serve something else.
    assert gated["followed"]["/static/login.html"]["path"] == "/login"
    assert gated["followed"]["/static/login.html"]["bytes"] == gated["login_bytes"]


def test_everything_the_login_page_loads_still_answers_without_a_session(gated):
    """The companion assertion, and the way this fix breaks if it is done at
    the mount instead of at the three documents.

    `/static` is auth-exempt because the page a logged-out user is sent to
    loads its stylesheet, its modules, its icon, its manifest and its two
    webfonts from there. Gating the mount — or gating `*.html` under it and
    then reaching for the same lever again — locks every user out of the only
    screen they can act on. The list is read out of the served login document
    rather than written here, so an asset the page grows tomorrow is covered
    by this on the commit that adds it (`Law 13`).
    """
    assets = gated["login_assets"]
    # Not vacuous: the page names a manifest, an icon, two fonts and the theme
    # module, and if the reading found none of them this test is about nothing.
    assert len(assets) >= 5, assets
    assert any(u.endswith("/static/js/theme.js") for u in assets), assets
    assert any(u.endswith(".woff2") for u in assets), assets

    refused = {url: row for url, row in assets.items() if row["status"] != 200}
    assert not refused, f"the login page cannot load its own assets logged out: {refused}"


def test_the_rule_is_not_walked_around_by_how_the_path_is_spelled(gated):
    """One rule guarding one boundary, and every spelling that reaches the
    same file goes through it.

    `StaticFiles.get_path` is `os.path.normpath`, so `/static/./index.html`,
    `/static//index.html` and `/static/index.html/` are all `index.html` by the
    time the mount sees them. The case fold is the one that is not free: a
    case-insensitive filesystem — macOS, Windows — serves `INDEX.HTML` out of
    `index.html`, and a rule that is the only case-sensitive thing on that path
    is a rule with a bypass on two of the three platforms this project ships
    installers for.
    """
    for url in ("/static/INDEX.HTML", "/static/./index.html",
                "/static//index.html", "/static/index.html/"):
        row = gated["direct"][url]
        assert row["status"] == 302, (url, row)
        assert row["location"] == "/", (url, row)
    assert gated["direct"]["/static/Login.HTML"]["location"] == "/login"


def test_the_redirect_lands_in_the_deployment_and_not_in_the_mount(gated):
    """A deployment behind `uvicorn --root-path /pantheon`.

    Starlette's `Mount` rewrites `root_path` for the scope it hands its child,
    so inside the `/static` mount `root_path` is `/pantheon/static` and only
    `app_root_path` is `/pantheon`. The first version of this fix read
    `root_path` and sent a client asking for `/static/index.html` to
    `/static/` — a redirect into the mount it was trying to leave, which on a
    plain deployment is a 404 loop and behind a prefix is worse. Measured, not
    reasoned: this is the measurement.
    """
    assert gated["root_path"]["/static/index.html"]["location"] == "/pantheon/"
    assert gated["root_path"]["/static/login.html"]["location"] == "/pantheon/login"
    assert gated["root_path"]["/static/backgrounds.html"]["location"] == "/pantheon/backgrounds"


@pytest.fixture(scope="module")
def surface(tmp_path_factory) -> dict:
    """The served surface with auth off — the one enumerator (`B260`)."""
    return probe_served_surface(tmp_path_factory.mktemp("served_surface"))


def test_no_document_this_app_serves_has_two_urls(surface):
    """The class, rather than the two files (`Law 13`).

    `B262` is "the shell has a second URL", and the fix is only a fix if the
    next page added under `static/` and served by a route cannot acquire one
    the same way. Asked of the whole served surface with auth off, where every
    route answers and every HTML document under the mount is enumerated: no
    two URLs may answer with the same bytes unless they are the nine shell
    routes, which are the same document on purpose and which `sw.js` knows
    about by name.

    Fails on the tree as it stood: `/static/index.html` was byte-identical to
    `/` and `/static/login.html` to `/login`.
    """
    pages = surface["pages"]
    shell = pages["/"]["body"]

    by_body: dict = {}
    for url, row in sorted(pages.items()):
        if row["status"] != 200 or not row["is_html"] or not row["body"]:
            continue
        by_body.setdefault(row["body"], []).append(url)

    duplicates = {urls[0]: urls for body, urls in by_body.items()
                  if len(urls) > 1 and body != shell}
    assert not duplicates, f"one document, two URLs: {duplicates}"

    # The shell's own set is the exception and it is not a loose one: every URL
    # that answers with the shell is a route `sw.js` claims, and none of them
    # is under the mount.
    shell_urls = sorted(by_body.get(shell, []))
    assert len(shell_urls) >= 9, shell_urls
    assert not [u for u in shell_urls if u.startswith("/static/")], shell_urls


def test_the_table_the_mount_reads_is_the_table_the_routes_read(gated):
    """`Law 13`, from the other side.

    Three route handlers used to each spell out their own template path, and
    the mount knew about none of them. They now read
    `ROUTE_OWNED_STATIC_PAGES`, so a page cannot be given a route without the
    mount learning that it has one — which is the direction the drift has to
    fail in. This asserts the table covers what it claims to: every entry names
    a route this app actually answers, and every entry's file redirects there.
    """
    owned = gated["owned"]
    assert owned is not None, (
        "app.py has no ROUTE_OWNED_STATIC_PAGES — the mount and the three "
        "route handlers are each spelling out their own paths again")
    assert owned == {"index.html": "/", "login.html": "/login",
                     "backgrounds.html": "/backgrounds"}, owned
    for name, route in owned.items():
        assert gated["direct"]["/static/" + name]["location"] == route, name
    # `backgrounds.html` is the entry for a file this build does not ship
    # (`B140`, `B210`). The mount still sends it to the route, and the route
    # answers 404 naming the file — not the mount answering 404 naming nothing.
    assert gated["direct"]["/static/backgrounds.html"]["status"] == 302
