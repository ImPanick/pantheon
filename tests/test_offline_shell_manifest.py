# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B54` — the offline manifest must name the URLs the page actually requests.

`static/sw.js` says it above `PRECACHE`::

    Both are fetched at install time, in the background. Entries must match the
    exact URL the browser requests, query string included.

and the fetch handler is `cache.match(e.request)` with no `ignoreSearch`, so
that sentence is load-bearing: a precached `/static/app.js` is simply not the
response to a request for `/static/app.js?v=20260815toolapproval4`. `P3-11` found
eight entries in that state and fixed them. Measuring again during `P3-10` found
**nine more**, and they were not obscure ones — `style.css`, `app.js`, `chat.js`,
`chatStream.js`, `document.js` and `init.js` were listed under bare paths nobody
asks for, and `a11y.js`, `assistant.js` and `tourAutoplay.js` were not listed at
all. Offline, the app had no stylesheet and no chat.

Nothing checked it, because the check has to compare two files that never
mention each other: what `index.html` boots against what `sw.js` stores. That
comparison is this file.

The other direction — every precache entry naming a file that exists in the
tree — is in `test_calendar_reminders_ride_the_notes_loop.py`, where deleting a
module made it matter. Together they close the loop: nothing precached is
missing from disk, and nothing the shell loads is missing from the manifest.

`B57` added the third direction and it is the one that was missing. The two
tests above compare **tags** against **entries**, and a tag is not what loads:
an ES module graph loads whole or not at all. Walking the imports out of the 32
`<script type="module">` roots reached 172 modules and the lists named 105, so
21 of those 32 roots — `app.js` and `chat.js` among them — could not complete
from the cache. `static/sw.js` now derives the closure at install instead of it
being written down, and the tests below run **that install**, in node, against
the real tree: they assert the cache it produces contains every root and is
closed under import. A list can be checked by reading it; a walk cannot, so
these execute it (`Law 20`).
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SW = _REPO / "static" / "sw.js"
_HARNESS = _REPO / "tests" / "harness" / "sw_install_graph.js"

# `B260`. The one enumerator of what this app serves. `served_routes` below is
# a projection of it; it used to be a second walk of `app.routes` that could
# not see the `/static` mount.
sys.path.insert(0, str(_REPO / "tests"))
from tests.helpers.served_pages import probe_served_surface  # noqa: E402

# `B82`. The import walker this repo already has. `.pantheon/check-specifiers.py`
# resolves every specifier grammar in the tree against its importer and knows
# which ones are out of scope, and `B87` taught it to blank comments first.
# Writing a second one here to compare against `sw.js` would be a third opinion
# about what an import is (`Law 14`), and the one that rots is always the copy.
_CHECKER = _REPO / ".pantheon" / "check-specifiers.py"
_spec = importlib.util.spec_from_file_location("check_specifiers", _CHECKER)
check_specifiers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_specifiers)


def _sw_code() -> str:
    """`static/sw.js` with its comments blanked.

    Every assertion in this file that looks at the worker's *source* goes
    through here. `B58` put the string `ignoreSearch` in a comment explaining
    why there is no `ignoreSearch` and failed a grep for it; `B87` hit the same
    law in the checker a day later. A rule about code has to read code
    (`Law 20`), and the two "this URL appears nowhere in sw.js" assertions
    below are exactly the shape that trips on a sentence.
    """
    return check_specifiers.strip_comments(
        _SW.read_text(encoding="utf-8"), html=False
    )

_MODULE_SCRIPT = re.compile(r'<script[^>]*type="module"[^>]*src="([^"]+)"')
_STYLESHEET = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')
# `B57`. Any `<script src>`, module or not. The type attribute decides how a
# script is evaluated, not whether it is requested — and reading only the module
# ones hid `/static/js/cookbookSchedule.js` (index.html:3263), a classic script
# in neither list, which nothing imports so no import walk reaches it either.
_ANY_SCRIPT = re.compile(r'<script[^>]*\ssrc="([^"]+)"')


def _precached() -> set:
    """Every `/static/...` entry in sw.js's two precache arrays.

    Read out of the arrays and not out of the file. It used to grep the whole
    source, which was the same thing right up until `B57` put the string
    `'/static/lib/'` in the walk's own guard — a literal that is not a precache
    entry, and a whole-file grep cannot tell the two apart (`Law 20`).
    """
    text = _sw_code()
    entries = set()
    for block in ("PRECACHE", "PANEL_PRECACHE"):
        start = re.search(rf"\nconst {block} = \[", text)
        assert start, f"{block} not found in sw.js"
        i, depth = start.end(), 1
        while i < len(text) and depth:
            depth += {"[": 1, "]": -1}.get(text[i], 0)
            i += 1
        entries |= set(re.findall(r"'(/static/[^']+)'", text[start.end():i - 1]))
    return entries


def _shell_requests(page: Path) -> list:
    html = page.read_text(encoding="utf-8")
    found = _ANY_SCRIPT.findall(html) + _STYLESHEET.findall(html)
    return [u for u in found if u.startswith("/static/")]


def _shell_stylesheet() -> str:
    """The stylesheet URL `index.html` actually asks for, query string and all.

    Derived rather than remembered (`Law 6`). Two assertions below spelled the
    sheet's cache-buster as a literal, and the first change to bump it for an
    unrelated reason failed one of them while the other went on fetching a URL
    the page had stopped requesting — a pinned string that had quietly become
    evidence about nothing.
    """
    urls = [u for u in _shell_requests(_REPO / "static" / "index.html")
            if u.split("?", 1)[0] == "/static/style.css"]
    assert len(urls) == 1, urls
    return urls[0]


def test_every_module_and_stylesheet_the_app_shell_loads_is_precached():
    requests = _shell_requests(_REPO / "static" / "index.html")
    # A parser that silently matched nothing would make this test vacuous and
    # green forever; the shell is ~33 resources.
    assert len(requests) > 25, f"only found {len(requests)} shell resources — parser drift?"
    entries = _precached()
    missing = [u for u in requests if u not in entries]
    assert missing == [], (
        "requested by index.html but not in the sw.js precache list, so offline "
        f"they 404 and the boot graph stops: {missing}"
    )


def test_a_script_tag_is_a_shell_request_whether_or_not_it_is_a_module(tmp_path):
    """The scope, pinned on its own. A parser that quietly narrowed would leave
    every test in this file green on a tree it had stopped reading — which is
    exactly how `cookbookSchedule.js` sat outside the manifest for as long as it
    did, because `<script type="module">` was the whole of the question asked.
    `Law 20`'s other half: the regex has to be shown what it must match."""
    page = tmp_path / "page.html"
    page.write_text(
        '<link rel="stylesheet" href="/static/style.css?v=1">\n'
        '<script type="module" src="/static/js/a.js"></script>\n'
        '<script src="/static/js/classic.js"></script>\n'
        '<script defer src="/static/lib/vendor.js"></script>\n'
        '<script src="https://cdn.example/off.js"></script>\n'
        '<script>const inline = 1;</script>\n',
        encoding="utf-8",
    )
    assert sorted(_shell_requests(page)) == [
        "/static/js/a.js", "/static/js/classic.js",
        "/static/lib/vendor.js", "/static/style.css?v=1",
    ]


def test_the_comparison_is_exact_and_not_forgiving_of_query_strings():
    # The whole defect class is a URL that differs only by `?v=`. If this test
    # stripped query strings to be helpful it would pass on the broken tree it
    # was written for, so prove it does not.
    entries = _precached()
    versioned = [u for u in _shell_requests(_REPO / "static" / "index.html") if "?" in u]
    assert versioned, "no cache-busted shell URLs left — has the scheme changed?"
    for url in versioned:
        assert url in entries
        bare = url.split("?")[0]
        assert bare not in entries, (
            f"{bare} is precached as well as {url}; one of them is never requested, "
            "and a dead entry is how this defect hid the last two times"
        )


def test_the_service_worker_still_matches_requests_including_their_query():
    """The reason exactness matters. `cache.match(request)` compares full URLs
    unless `ignoreSearch` is passed; if someone adds that option, every entry in
    this file becomes optional and the tests above stop meaning anything.

    **Comments are stripped first, and that is not cosmetic** (`Law 20`). This
    read the raw file, so it failed on `B58`'s comment *explaining why there is
    no `ignoreSearch`* — a test that greps a file cannot tell a setting from a
    sentence about the setting. It now looks at the code.
    """
    code = _sw_code()
    assert "ignoreSearch" not in code, (
        "sw.js now ignores query strings when matching; the precache list no "
        "longer has to be exact, so revisit B54 and these tests together"
    )


def test_the_login_page_shell_is_covered_too():
    # login.html is the one screen index.html's modules never reach. It carries
    # its own inline styles today, so it loads no script or stylesheet of its
    # own — asserted rather than assumed, because the day it grows a <script
    # type="module"> tag is the day it needs to be in the manifest.
    #
    # `B122` corrects what this used to claim. "No external shell resources" was
    # too strong: the page names `static/manifest.json`, `static/icons/
    # icon-192.png` and two Fira Code faces, all *relative*, which this scan
    # drops because it only keeps `/static/` — and dropping them was safe only
    # by accident, since index.html happens to reference the same four. They
    # are covered by derivation now, from the page itself; see
    # `test_the_login_page_is_read_for_what_it_references`.
    assert _shell_requests(_REPO / "static" / "login.html") == []

    # `B57`: it does not request one through a `src` attribute, which is not the
    # same as requesting nothing. The page carries an inline <script
    # type="module"> that imports theme.js through a *computed* specifier —
    # `import(f('/static/js/theme.js'))` — which no import walker can follow, so
    # theme.js has to be a seed. It is; this pins that it stays one, because the
    # page degrades silently to its static gradient if the import fails.
    login = (_REPO / "static" / "login.html").read_text(encoding="utf-8")
    inline = re.findall(r'<script(?![^>]*\ssrc=)[^>]*type="module"[^>]*>(.*?)</script>',
                        login, re.S)
    assert inline, "login.html no longer has an inline module block"
    inline_roots = sorted({m for block in inline
                           for m in re.findall(r"""['"](/static/[^'"]+\.js)['"]""", block)})
    assert inline_roots == ["/static/js/theme.js"], inline_roots
    assert "/static/js/theme.js" in _precached()

    # `B122`. The gap this test's name promised and the manifest did not keep:
    # `theme.js` was a seed *because this page imports it*, and the page itself
    # was in neither list, so the dependency was guaranteed offline and the
    # document was not. `/login` is a seed now — the assertion, not the prose,
    # is what stops the two disagreeing again.
    listed = re.search(r"\nconst PRECACHE = \[(.*?)\n\];", _sw_code(), re.S)
    assert listed, "PRECACHE is no longer a list"
    assert "'/login'" in listed.group(1), (
        "login.html's dependency is precached and login.html is not; that is "
        "the disagreement B122 closed — see the row before reopening it"
    )


# ── `B57`: the manifest is not the shell, so run the install and look ─────────

# Scoped to the tests that need it. A module-level `pytestmark` would take the
# four list comparisons above down with it on a box without node, and those
# neither need it nor were failing.
_needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node binary not on PATH")


def _run(command: dict) -> dict:
    proc = subprocess.run(
        ["node", str(_HARNESS)], input=json.dumps(command),
        capture_output=True, text=True, cwd=str(_REPO), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def installed() -> dict:
    """The cache `static/sw.js`'s own install handler builds, against this tree."""
    return _run({"op": "install"})


@_needs_node
def test_install_caches_every_module_the_shell_imports(installed):
    """The ratchet. Two properties, and together they are the transitive
    closure: every `<script type="module">` root is cached, and the cache is
    closed under import. Induction does the walking, so this test needs no
    second walker to disagree with the one in `sw.js` (`Law 13`).
    """
    roots = [u for u in _MODULE_SCRIPT.findall(
        (_REPO / "static" / "index.html").read_text(encoding="utf-8"))
        if u.startswith("/static/")]
    assert len(roots) > 25, f"only found {len(roots)} module roots — parser drift?"

    cached = set(installed["cached"])
    assert [r for r in roots if r not in cached] == []

    # `imports` is the worker's own reading of each cached module.
    assert len(installed["imports"]) > 150, "the walk read suspiciously few modules"
    wanted = {target for targets in installed["imports"].values() for target in targets}
    unreachable = sorted(wanted - cached)
    assert unreachable == [], (
        "cached modules import these and they are in no cache entry, so the "
        f"graph cannot complete offline: {unreachable}"
    )


@_needs_node
def test_nothing_that_used_to_be_precached_stopped_being_precached(installed):
    """`Law 1` as a test. Deriving the closure had to be strictly additive: the
    walk may only add to what the two lists already named, never replace it.
    Both lists are still the seeds, so every entry in them is still cached."""
    listed = _precached()
    assert len(listed) > 100, f"only parsed {len(listed)} entries — parser drift?"
    dropped = sorted(listed - set(installed["cached"]))
    assert dropped == [], f"in a list but not in the cache install builds: {dropped}"


@_needs_node
def test_a_seed_nothing_imports_still_gets_its_own_graph_walked():
    """`PANEL_PRECACHE`'s whole job: `js/panels.js` imports those modules on
    first use, so a panel the user never opened while online must still open
    offline. On this tree the walk reaches them anyway — `panels.js` is in the
    shell graph and `import('./galleryEditor.js')` is a specifier like any other,
    so seeding from `PRECACHE` alone builds a byte-identical cache. That makes
    the second list derived rather than load-bearing, and it stays as the
    declaration of intent and the floor for the day `panels.js` moves. What must
    not quietly stop working is the walk reaching a seed nothing imports."""
    out = _run({"op": "walk", "seeds": ["/static/js/root.js", "/static/js/lazy.js"],
                "files": {
                    "/static/js/root.js": "import './fromroot.js';",
                    "/static/js/fromroot.js": "",
                    "/static/js/lazy.js": "import './fromlazy.js';",
                    "/static/js/fromlazy.js": "",
                }})
    assert out["cached"] == [
        "/static/js/fromlazy.js", "/static/js/fromroot.js",
        "/static/js/lazy.js", "/static/js/root.js",
    ]


@_needs_node
def test_the_modules_no_list_names_are_there_by_derivation(installed):
    """The four the row named. They are cached, and their URLs appear nowhere in
    `sw.js` — which is the point: adding them to a list would have fixed these
    four and left the next one to be found by hand."""
    derived = {
        "/static/js/toolWindowZOrder.js",
        "/static/js/escMenuStack.js",
        "/static/js/windowDrag.js",
        "/static/js/modalManager.js?v=20260723compareicon2",
    }
    cached = set(installed["cached"])
    assert derived <= cached, sorted(derived - cached)
    source = _sw_code()
    assert [u for u in derived if u.split("?")[0] in source] == []


@_needs_node
def test_a_specifier_resolves_to_the_url_the_browser_will_request():
    """The defect class `P3-11`, `B54` and `B58` each found a fresh batch of: a
    query string that does not match is a cache entry that can never be served.
    A relative import carries its OWN query and never the importer's."""
    source = "\n".join([
        "import a from './sibling.js';",
        "import b from './versioned.js?v=20260101x';",
        "export { c } from '../up.js';",
        "const d = await import('/static/js/absolute.js');",
        # Off-origin, and the path deliberately LOOKS local: dropping the
        # origin check would turn this into a request to our own /static/js/,
        # for a module that only exists on somebody else's host. A mutation run
        # walked past the first version of this line, which used a path no
        # `isWalkable` would have accepted anyway.
        "import 'https://cdn.example/static/js/notours.js';",
        "import '/static/lib/mermaid.min.js';",
    ])
    got = _run({"op": "imports", "url": "/static/js/deep/importer.js?v=IGNOREME",
                "source": source})["imports"]
    assert got == [
        "/static/js/deep/sibling.js",
        "/static/js/deep/versioned.js?v=20260101x",
        "/static/js/up.js",
        "/static/js/absolute.js",
    ]


@_needs_node
def test_the_walk_stops_at_the_vendored_libraries():
    """Mermaid is 3.5 MB and is deliberately not precached — it would re-download
    on every `CACHE_NAME` bump for the sessions that never render a diagram. A
    walk that followed imports into `static/lib/` would bring it back in through
    the side door, so `static/lib/` is outside the walk and this proves it on a
    tree built to tempt it."""
    out = _run({"op": "walk", "seeds": ["/static/js/root.js"], "files": {
        "/static/js/root.js": "import '/static/lib/mermaid.min.js';\nimport './leaf.js';",
        "/static/lib/mermaid.min.js": "// 3.5 MB",
        "/static/js/leaf.js": "",
    }})
    assert out["cached"] == ["/static/js/leaf.js", "/static/js/root.js"]
    assert "/static/lib/mermaid.min.js" not in out["fetched"]


@_needs_node
def test_one_module_that_404s_does_not_take_the_rest_of_the_install_with_it():
    """`cache.addAll` is atomic and that is why it is not used. A module that has
    been deleted must cost its own subtree and nothing else — the walk reports
    no imports for it and carries on with its siblings."""
    files = {
        "/static/js/root.js": "import './gone.js';\nimport './alive.js';",
        "/static/js/alive.js": "import './deep.js';",
        "/static/js/deep.js": "",
        "/static/js/gone.js": "import './orphan.js';",
        "/static/js/orphan.js": "",
    }
    out = _run({"op": "walk", "seeds": ["/static/js/root.js"], "files": files,
                "fail": ["/static/js/gone.js"]})
    assert out["cached"] == [
        "/static/js/alive.js", "/static/js/deep.js", "/static/js/root.js",
    ]


@_needs_node
def test_the_walk_terminates_on_an_import_cycle():
    """`seen` is the termination argument, not the round ceiling. Two modules
    that import each other are ordinary in this tree."""
    out = _run({"op": "walk", "seeds": ["/static/js/a.js"], "files": {
        "/static/js/a.js": "import './b.js';",
        "/static/js/b.js": "import './a.js';",
    }})
    assert out["cached"] == ["/static/js/a.js", "/static/js/b.js"]
    assert out["fetched"] == ["/static/js/a.js", "/static/js/b.js"]


@_needs_node
def test_the_install_stores_the_body_it_just_read(installed):
    """`cache.put` consumes the response body, so the walk has to clone before it
    reads. The harness's Response refuses a second read — a worker that stored
    first and cloned after would cache nothing here, and nothing in a browser."""
    assert len(installed["cached"]) == len(installed["fetched"])
    assert "/" in installed["cached"]
    assert installed["cacheName"].startswith("pantheon-v")


# ── `B85`: the install's REQUEST, not just its result ─────────────────────────


@_needs_node
def test_install_revalidates_instead_of_refetching_the_whole_shell(installed):
    """`{ cache: 'reload' }` bypasses the HTTP cache and forces a full 200 for
    every entry. Install is paid on a cold install *and on every `CACHE_NAME`
    bump* — 416 bumps, 13 in the week `B57` was measured — so the shell came
    down at full size roughly twice a day against a server holding a
    byte-identical copy.

    `{ cache: 'no-cache' }` is the mode that keeps what `reload` was for
    (never serve a stored response the server has not just confirmed) and
    drops what it cost (the body). Asserted over every URL install fetches,
    not a sample: a mode is a per-request argument and the cheap way to get
    this wrong is to change it for the list and miss the walk.
    """
    modes = installed["modes"]
    assert len(modes) == len(installed["cached"]), "a URL was fetched twice"
    assert set(modes.values()) == {"no-cache"}, {
        m for m in set(modes.values()) if m != "no-cache"
    }

    # Named individually because each is a different bug with the same symptom.
    # '(none)' is the harness's spelling for "the option was dropped", which
    # behaves as 'default' and would be the easiest of the three to not notice.
    bad = sorted(u for u, m in modes.items() if m in ("reload", "default", "(none)"))
    assert bad == [], bad


@_needs_node
def test_the_install_covers_urls_the_revalidating_header_does_not(installed):
    """Why the mode is `no-cache` and not `default`, held as a ratchet.

    `app.py`'s `_RevalidatingStatic` stamps `Cache-Control: no-cache` on `.js`,
    `.css` and `.html` — and nothing else. Under `{ cache: 'default' }` a
    response with validators but no freshness directive gets *heuristic*
    freshness (RFC 9111 §4.2.2) and can be served from disk for days without
    asking the server, which is the stale install `reload` existed to prevent.
    The row that filed `B85` concluded those URLs must therefore keep `reload`;
    the answer is that `default` was the wrong alternative, not that they are
    special.

    This asserts the condition that makes `default` unsafe still holds. If it
    ever fails, that is good news and not a bug — see the message.
    """
    covered = (".js", ".css", ".html")
    uncovered = sorted(u for u in installed["cached"]
                       if not u.split("?")[0].endswith(covered))
    assert uncovered, (
        "every precached URL is now served by a handler that forces "
        "revalidation, so `{cache: 'default'}` would be safe and cheaper than "
        "`no-cache` on a warm HTTP cache — revisit B85 and this test together"
    )
    # The classes the header does not reach: fonts, icons, the PWA manifest,
    # and the app route itself.
    assert "/" in uncovered
    assert any(u.endswith(".woff2") for u in uncovered)


def test_a_conditional_request_is_actually_cheap_on_this_server(tmp_path):
    """The saving `B85` claims, measured rather than asserted about.

    `no-cache` only pays if the server answers `If-None-Match` with a 304. That
    is a property of `app.py` and `StaticFiles`, not of `sw.js`, so it is
    measured by driving the real ASGI app — one request per class the install
    fetches (`Law 20`: the worker's fetch mode is worth nothing if the server
    has stopped sending validators).

    Run out-of-process because importing `app` pulls the whole application up;
    same shape as `test_auth_root_path.py`.
    """
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    # The stylesheet URL is resolved HERE and interpolated, because the probe
    # below runs in a subprocess with `python3 -c` and has none of this
    # module's helpers. Interpolated as a repr so a URL containing a quote
    # could not break out of the literal.
    probe = textwrap.dedent(
        """
        import json
        import app as app_module
        from fastapi.testclient import TestClient

        client = TestClient(app_module.app)
        out = {}
        for label, url in [
            ("js", "/static/app.js?v=20260815toolapproval4"),
            ("css", __CSS_URL__),
            ("woff2", "/static/fonts/FiraCode-Regular.woff2"),
            ("png", "/static/icons/icon-192.png"),
            ("json", "/static/manifest.json"),
            ("root", "/"),
        ]:
            first = client.get(url)
            etag = first.headers.get("etag")
            second = (client.get(url, headers={"If-None-Match": etag})
                      if etag else first)
            out[label] = {
                "status": first.status_code,
                "cache_control": first.headers.get("cache-control"),
                "etag": bool(etag),
                "full_bytes": len(first.content),
                "revalidated_status": second.status_code,
                "revalidated_bytes": len(second.content),
            }
        print("RESULT=" + json.dumps(out, sort_keys=True))
        """
    ).replace("__CSS_URL__", repr(_shell_stylesheet()))
    result = subprocess.run([sys.executable, "-c", probe], cwd=str(_REPO), env=env,
                            capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout
    got = json.loads(line.removeprefix("RESULT="))

    # Every class install fetches answers a conditional request with an empty
    # 304 — including the fonts, icons and manifest, which carry no
    # `Cache-Control` at all. That is the whole of `B85`'s saving.
    #
    # `root` is in this list as of `B121` and was the reason the list used to
    # stop before it: `serve_html_with_nonce` rebuilt the page per request to
    # substitute the CSP nonce, so `/` carried no ETag and no Last-Modified and
    # was the one entry of 213 that answered an unchanged `CACHE_NAME` bump
    # with 290,468 bytes. `B141` took the nonce out of the body — the inline
    # blocks are authorised by `'sha256-…'` computed from the file — and the
    # response became describable. This assertion failing again means the shell
    # went back to varying per request, whatever the reason.
    for label in ("js", "css", "woff2", "png", "json", "root"):
        row = got[label]
        assert row["status"] == 200, row
        assert row["etag"], f"{label} lost its validator; `no-cache` now costs a full body"
        assert row["revalidated_status"] == 304, row
        assert row["revalidated_bytes"] == 0, row
        assert row["full_bytes"] > 0

    # `_RevalidatingStatic` reaches the source files and nothing else — the
    # measurement that rules out `{cache: 'default'}`.
    assert got["js"]["cache_control"] == "no-cache"
    assert got["css"]["cache_control"] == "no-cache"
    assert got["woff2"]["cache_control"] is None
    assert got["png"]["cache_control"] is None
    assert got["json"]["cache_control"] is None

    # `/` is not served by `_RevalidatingStatic` — it is the app route, not the
    # static mount — so it has to set the same directive itself, and `B121` is
    # the row that made it possible to. Without any `Cache-Control` at all this
    # response had *heuristic* freshness (RFC 9111 §4.2.2): a browser was
    # entitled to paint a stale shell for days without asking.
    assert got["root"]["cache_control"] == "no-cache"
    assert got["root"]["full_bytes"] > 100_000


# ── `B86`: a font named inside a stylesheet is a shell request too ────────────

_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def _stylesheet_sources() -> dict:
    """Every stylesheet the app shell carries, by the URL it is cached under.

    Deliberately includes `index.html`'s inline `<style>` blocks. That is the
    half `B86` did not name and the half a hand-list would have missed: three
    `Inter` faces — the UI font — are declared there, so they are in no
    stylesheet the page links and no `<link rel=stylesheet>` scan can see them.
    """
    index = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    return {
        "/static/style.css": (_REPO / "static" / "style.css").read_text(encoding="utf-8"),
        "/": "\n".join(_STYLE_BLOCK.findall(index)),
    }


@_needs_node
def test_every_font_a_shell_stylesheet_names_is_installed(installed):
    """`B86`'s `Verify:`, and the reason the row exists: nothing could see this.

    The manifest tests above compare `<script src>` and `<link rel=stylesheet>`
    against the lists, and a font referenced from *inside* a stylesheet is
    neither — so five `@font-face` woff2 in `style.css` and three more in
    `index.html`'s inline `<style>` sat outside every list while KaTeX's 20
    were in one.

    This reads the stylesheets with a deliberately BROADER rule than the worker
    uses — every `url()`, no format filter — so narrowing the worker's own
    filter fails here instead of quietly shrinking the guarantee.
    """
    cached = set(installed["cached"])
    referenced = sorted({
        target
        for source in _stylesheet_sources().values()
        for _, target in _CSS_URL.findall(source)
        if target.startswith("/static/")
    })
    assert len(referenced) >= 8, f"only found {len(referenced)} — parser drift?"
    assert [u for u in referenced if u not in cached] == [], [
        u for u in referenced if u not in cached
    ]


@_needs_node
def test_install_caches_everything_the_documents_it_stores_reference(installed):
    """The `B86` ratchet, and the same induction `B57` used for imports: the
    cache is closed under *reference* as well as under import. `assets` is the
    worker's own reading of each cached stylesheet, page and manifest, so this
    test needs no second extractor to disagree with the one in `sw.js`."""
    cached = set(installed["cached"])
    assets = installed["assets"]

    # A `docKind` that quietly stopped recognising a document type would empty
    # the map and make the closure below vacuous, which is how `B57`'s
    # `cookbookSchedule.js` hid: pin the documents that must be read.
    assert set(assets) == {
        "/",
        # `B122`. The second document, and the reason `docKind` now decides on
        # "no extension" rather than on the single path `/`: a route is not a
        # file and `/login` has no `.html` to recognise it by.
        "/login",
        _shell_stylesheet(),
        "/static/lib/katex/katex.min.css",
        "/static/manifest.json",
    }, sorted(assets)

    wanted = {target for targets in assets.values() for target in targets}
    assert len(wanted) >= 28, f"the walk read suspiciously few references: {len(wanted)}"
    unreachable = sorted(wanted - cached)
    assert unreachable == [], (
        "cached documents reference these and they are in no cache entry, so "
        f"offline they fall back to a system font or a missing icon: {unreachable}"
    )


@_needs_node
def test_the_katex_font_list_is_exactly_what_its_stylesheet_says(installed):
    """The check on the new walk. `KATEX_FONTS` is a 20-entry hand-list that has
    been correct for 416 cache generations; deriving `url()` out of
    `katex.min.css` has to reproduce it exactly or the derivation is wrong.

    It also pins the format rule in both directions. `katex.min.css` names 60
    url()s — 20 `.woff2` and 40 `.woff`/`.ttf` legacy fallbacks this repo never
    vendored. A browser takes the first `format()` it supports and every
    browser with a service worker supports woff2, so following all 60 would be
    40 requests per install that 404; following none of the fonts would be
    `B86` reopened for KaTeX.
    """
    source = _sw_code()
    names = re.search(r"const KATEX_FONTS = \[(.*?)\]\.map", source, re.S)
    assert names, "KATEX_FONTS is no longer a list of names"
    listed = {f"/static/lib/katex/fonts/KaTeX_{n}.woff2"
              for n in re.findall(r"'([^']+)'", names.group(1))}
    assert len(listed) == 20, sorted(listed)

    derived = set(installed["assets"]["/static/lib/katex/katex.min.css"])
    assert derived == listed, {
        "only in the list": sorted(listed - derived),
        "only derived": sorted(derived - listed),
    }


@_needs_node
def test_the_manifest_and_its_icons_are_there_by_derivation(installed):
    """What a hand-list would have got wrong, stated as a test. `B86` named
    seven URLs to add: five fonts, `manifest.json` and `icon-192.png`. The
    walk finds twelve. Two of the five it would have missed are named only by
    `manifest.json` itself — nothing else in the tree reads that file — and
    three are the `Inter` faces in `index.html`'s inline `<style>`.

    So: they are cached, and their URLs appear nowhere in `sw.js`."""
    cached = set(installed["cached"])
    derived = {
        "/static/manifest.json",
        "/static/icons/icon-192.png",
        "/static/icons/icon-512.png",
        "/static/icons/icon-maskable-512.png",
        "/static/fonts/Inter-Regular.woff2",
        "/static/fonts/Inter-Medium.woff2",
        "/static/fonts/Inter-SemiBold.woff2",
        "/static/fonts/FiraCode-Light.woff2",
        "/static/fonts/FiraCode-Regular.woff2",
        "/static/fonts/FiraCode-SemiBold.woff2",
        "/static/fonts/OpenDyslexic-Regular.woff2",
        "/static/fonts/OpenDyslexic-Bold.woff2",
    }
    assert derived <= cached, sorted(derived - cached)
    source = _sw_code()
    listed_anyway = [u for u in sorted(derived) if f"'{u}'" in source]
    assert listed_anyway == [], (
        f"{listed_anyway} was added to a precache list; the walk already has it "
        "and a second copy is a second thing to keep in step"
    )


@_needs_node
def test_the_asset_walk_reads_the_grammar_and_not_more():
    """The scope of `assetsOf`, pinned on its own — the lesson
    `test_a_script_tag_is_a_shell_request_whether_or_not_it_is_a_module`
    records. The closure test above is over the worker's *own* notion of a
    reference, so a filter that silently narrowed would shrink both sides of it
    and stay green. This shows the extractor what it must match and what it
    must not."""
    css = "\n".join([
        "@font-face { src: url('/static/fonts/A.woff2') format('woff2'); }",
        '@font-face { src: url("./rel.woff2"); }',
        "@font-face { src: url(/static/fonts/unquoted.woff2); }",
        "@font-face { src: url('/static/fonts/Q.woff2?v=7'); }",
        # The legacy formats KaTeX lists and this repo never vendored.
        "@font-face { src: url('/static/fonts/A.woff') format('woff'); }",
        "@font-face { src: url('/static/fonts/A.ttf') format('truetype'); }",
        # An off-origin reference whose path deliberately looks local.
        "@font-face { src: url('https://cdn.example/static/fonts/away.woff2'); }",
        ".x { background: url('/static/icons/bg.png'); }",
        ".y { background: url('data:image/gif;base64,R0lGOD'); }",
        # Outside /static/ — the same boundary `isWalkable` draws for modules.
        # A stylesheet can point at user content (`/uploads/...`) and an
        # install-time guarantee is about the shipped shell, not about whatever
        # a user has uploaded.
        ".z { background: url('/uploads/whatever.png'); }",
        # A stylesheet naming a script is not a thing, but `/static/lib/` holds
        # mermaid's 3.5 MB and this is one of the two doors into it.
        ".w { background: url('/static/lib/mermaid.min.js'); }",
    ])
    got = _run({"op": "assets", "url": "/static/css/deep/theme.css?v=IGNOREME",
                "source": css})["assets"]
    assert got == [
        "/static/fonts/A.woff2",
        "/static/css/deep/rel.woff2",     # relative, resolved against the sheet
        "/static/fonts/unquoted.woff2",
        "/static/fonts/Q.woff2?v=7",      # its OWN query, never the referrer's
        "/static/icons/bg.png",
    ], got

    html = "\n".join([
        '<link rel="manifest" href="/static/manifest.json">',
        '<link rel="apple-touch-icon" href="/static/icons/icon-192.png">',
        '<link rel="preload" as="font" crossorigin href="/static/fonts/P.woff2">',
        '<link rel="stylesheet" href="/static/style.css?v=9">',
        # A data: URI favicon — same-origin only by accident of syntax.
        '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg/%3E">',
        # The module graph is the import walk's job. Note WHY this one is
        # absent from the output: not because `modulepreload` is off the rel
        # list — putting it on changes nothing — but because `isNotAScript`
        # refuses every `.js` a <link> can name. A mutation run established
        # that; the rel list is an allow-list of reference kinds, not the
        # script guard.
        '<link rel="modulepreload" href="/static/js/chat.js?v=9">',
        '<link rel="alternate" href="/static/feed.xml">',
        '<link rel="preload" as="script" href="/static/lib/mermaid.min.js">',
        '<link rel="manifest" href="/outside-static.json">',
        "<style>@font-face { src: url('/static/fonts/Inline.woff2'); }</style>",
    ])
    got = _run({"op": "assets", "url": "/", "source": html})["assets"]
    assert got == [
        "/static/manifest.json",
        "/static/icons/icon-192.png",
        "/static/fonts/P.woff2",
        "/static/style.css?v=9",
        "/static/fonts/Inline.woff2",
    ], got

    manifest = json.dumps({"icons": [
        {"src": "icons/a.png"},                       # relative to the manifest
        {"src": "/static/icons/b.png"},
        {"src": "https://cdn.example/static/icons/away.png"},
        {"src": 17},
    ]})
    got = _run({"op": "assets", "url": "/static/manifest.json",
                "source": manifest})["assets"]
    assert got == ["/static/icons/a.png", "/static/icons/b.png"], got


@_needs_node
def test_the_asset_walk_cannot_reach_a_script():
    """The mermaid guard, re-proved for the grammar `B86` added. `isWalkable`
    keeps `/static/lib/` out of the *import* walk; a stylesheet or a `<link>`
    is a second door into the same 3.5 MB — `rel="preload" as="script"` names a
    script outright — so the exclusion is stated once in `isNotAScript` and
    tested on a tree built to tempt it.

    `static/lib/` itself is NOT excluded here, and must not be: KaTeX's 20
    fonts live there and have been precached since long before this row.
    """
    out = _run({"op": "walk", "seeds": ["/"], "files": {
        "/": "\n".join([
            '<link rel="preload" as="script" href="/static/lib/mermaid.min.js">',
            '<link rel="stylesheet" href="/static/lib/katex/katex.min.css">',
        ]),
        "/static/lib/katex/katex.min.css":
            "@font-face{src:url(fonts/KaTeX_Main-Regular.woff2)}"
            "@font-face{src:url(../../js/sneaky.js)}",
        "/static/lib/mermaid.min.js": "// 3.5 MB",
        "/static/lib/katex/fonts/KaTeX_Main-Regular.woff2": "font",
        "/static/js/sneaky.js": "// not a font",
    }})
    assert out["cached"] == [
        "/",
        "/static/lib/katex/fonts/KaTeX_Main-Regular.woff2",
        "/static/lib/katex/katex.min.css",
    ]
    assert "/static/lib/mermaid.min.js" not in out["fetched"]
    assert "/static/js/sneaky.js" not in out["fetched"]


@_needs_node
def test_a_manifest_that_is_not_json_does_not_take_the_install_with_it():
    """Same rule as the 404 above: one broken document costs its own references
    and nothing else. A PWA manifest is the one thing here that is *parsed*
    rather than scanned, so it is the one that can throw."""
    out = _run({"op": "walk", "seeds": ["/"], "files": {
        "/": "\n".join([
            '<link rel="manifest" href="/static/manifest.json">',
            "<style>@font-face{src:url('/static/fonts/A.woff2')}</style>",
        ]),
        "/static/manifest.json": "<!doctype html>an error page, not a manifest",
        "/static/fonts/A.woff2": "font",
    }})
    assert out["cached"] == [
        "/", "/static/fonts/A.woff2", "/static/manifest.json",
    ]


# ── `B120`/`B122`: what a navigation is answered with, and for which routes ───


def _shell_routes_in_sw() -> set:
    """The `SHELL_ROUTES` literal, read out of the array in the worker's code.

    This set is the *only* thing in `sw.js` that names a server route, and it
    exists because a service worker cannot ask `app.py` anything at the moment
    it has to decide whether to claim a navigation — the decision is
    synchronous and a cache read is not. So the list is written down and then
    checked against the server, by the test below. A list nobody checks is the
    defect `B120` is; a list checked on every run is a build step this repo has
    no build for.
    """
    code = _sw_code()
    block = re.search(r"const SHELL_ROUTES = new Set\(\[(.*?)\]\)", code, re.S)
    assert block, "SHELL_ROUTES is no longer a literal set in sw.js"
    return set(re.findall(r"'([^']+)'", block.group(1)))


@pytest.fixture(scope="module")
def served_routes(tmp_path_factory) -> dict:
    """Every navigable page the real app serves, asked for its body by the real
    app, compared byte for byte.

    Driven rather than parsed (`Law 20`). An AST pass over `app.py` would have
    to recognise `return await serve_index(request)` as delegation, and would
    miss the next handler that reaches the same document another way; asking
    the app what it serves recognises all of them and nothing else.

    **`B260`: this is a projection of `probe_served_surface` and no longer a
    second enumerator.** It used to run its own out-of-process probe with its
    own route walk, and the two had already drifted in the way `Law 13`
    predicts: this one skipped the `/static` mount, which is a `Mount` and so
    appears in `app.routes` as one entry with no per-file path, so the app
    shell and the login page each had a second URL that this fixture could not
    see and `B211` found by other means. The enumeration now happens once, in
    `tests/helpers/served_pages.py`, and one subprocess boots the app for both
    callers. What is projected away here is what the offline row does not ask
    about: `/api/` routes, which the service worker never touches.

    **The normalisation is gone, and that is the point.** `B120` compared these
    bodies through `re.sub(r'nonce="[0-9a-f]*"', 'nonce=""', text)`, because the
    one part of a response that was not the file was the per-request CSP nonce
    substituted into 7 places in it. `B141` moved that authorisation to
    `'sha256-…'` sources in the header, computed from the file, so there is
    nothing left to normalise — and a regex that now matches nothing is a
    regex that would go on matching nothing if the shell started varying again.
    `body_repeats` re-asks for each body and records whether the second answer
    is the same bytes as the first, so this fixture states the premise it used
    to assume; `test_the_app_shell_does_not_vary_per_request` is the assertion
    on it.
    """
    surface = probe_served_surface(tmp_path_factory.mktemp("served_routes"))
    pages = surface["pages"]
    shell = pages["/"]["body"]
    assert shell, "the probe returned no body for `/` — every check below is vacuous"
    return {
        url: {
            "status": row["status"],
            "bytes": row["bytes"],
            "is_shell": row["status"] == 200 and row["body"] == shell,
            "body_repeats": row["body_repeats"],
            "etag": row["etag"],
            "head": row["body"][:200],
        }
        for url, row in pages.items()
        if not url.startswith("/api/")
    }


def test_the_shell_route_set_is_what_the_server_actually_serves(served_routes):
    """`B120`'s `Law 13` half, and the whole reason this row is not "add eight
    strings to sw.js".

    Nine routes answer with the identical app shell — `/` plus the eight
    `app.py` sends to `serve_index` — and the worker claimed a navigation for
    exactly one of them. Adding the other eight by hand fixes today and leaves
    the tenth route to be found by a user with no network, so the list is
    checked against the server on every run instead. This fails on the commit
    that adds a route, not on the install that misses it.
    """
    is_shell = sorted(p for p, row in served_routes.items() if row["is_shell"])
    # If the derivation ever matched nothing, every assertion here would be
    # vacuous and green — the failure mode `B57` and `B86` each had to pin.
    assert len(is_shell) >= 9, (is_shell, served_routes)
    assert _shell_routes_in_sw() == set(is_shell), {
        "served but not claimed by sw.js": sorted(set(is_shell) - _shell_routes_in_sw()),
        "claimed by sw.js but not served": sorted(_shell_routes_in_sw() - set(is_shell)),
    }


def test_a_route_that_serves_its_own_document_is_not_in_the_shell_set(served_routes):
    """The trap the narrowing existed for, from the server's side.

    `sw.js:509` narrowed to `/` because matching every navigation served the
    app index in place of the page the user asked for, and that reason has to
    survive the widening. `/login` is the live proof on this tree: a real route,
    a real document, and **not** the shell — so a predicate like "a navigation
    outside `/static/`" would hand a user asking to log in the app they are not
    logged into. It is cached (`B122`) and it is cached as itself.
    """
    assert "/login" in served_routes
    assert "/login" not in _shell_routes_in_sw()
    # Every route the server does not answer with the shell stays out, whatever
    # its status — `/backgrounds` is a 404 naming a page this build does not
    # ship (`B140`, `B210`), `/redoc` is a 404 naming `/docs` (`B261`), and the
    # docs routes are FastAPI's own pages.
    for path, row in served_routes.items():
        if not row["is_shell"]:
            assert path not in _shell_routes_in_sw(), (path, row)


def test_the_static_mount_is_in_this_view_of_the_served_surface(served_routes):
    """`B260`. The drift this fixture used to have, stated as an assertion.

    `served_routes` walked `app.routes` and nothing else. The `/static` mount
    is one `Route`-less `Mount` entry there, so every document under it was
    invisible: the app shell had a second URL (`/static/index.html`), the login
    page had a second URL, and the two prototype pages `sw.js` names in the
    comment above its navigation handler could not be checked against the
    server at all. It is now a projection of `probe_served_surface`, which
    enumerates the mount's documents from the directory the mount is pointed
    at, so the two tests that ask what this app serves are asking one probe.

    Fails on `HEAD`: the fixture returned 20 URLs, none of them under
    `/static`.
    """
    mounted = sorted(p for p in served_routes if p.startswith("/static/"))
    assert "/static/wave-variants.html" in mounted, mounted
    assert "/static/whirlpool-variants.html" in mounted, mounted
    # And the two the mount no longer hands over (`B262`) are seen here as the
    # redirects they became, rather than not being seen at all.
    for shell_url, owner in (("/static/index.html", "/"),
                             ("/static/login.html", "/login")):
        assert shell_url in mounted, mounted
        assert served_routes[shell_url]["status"] == 302, served_routes[shell_url]
        assert not served_routes[shell_url]["is_shell"], served_routes[shell_url]
        assert owner in served_routes, owner


def test_the_app_shell_does_not_vary_per_request(served_routes):
    """`B141`'s `Verify:`, and the premise every comparison above rests on.

    The nine shell routes are the same document, and `sw.js`'s revalidate
    branch writes a response fetched from any of them back into the one `/`
    entry all nine are served from. That was true up to a 32-hex token in seven
    places: `serve_html_with_nonce` substituted a fresh `secrets.token_hex(16)`
    per request, and the fixture above had to normalise it out to compare
    anything. Two consecutive requests for `/` now return the same bytes, so
    the fixture compares raw text and this is what says so.

    Measured on the tree before the change: `/` differed between two requests
    (`1016b6d2…` then `3b18b742…`), and so did all eight routes behind it.
    """
    varying = sorted(p for p, row in served_routes.items()
                     if row["status"] == 200 and not row["body_repeats"])
    assert varying == [], varying
    assert served_routes["/"]["body_repeats"]
    # And the consequence the whole of `B121` is: a body that does not vary can
    # be described, so it carries a validator. `/` is not under the `/static`
    # mount, so nothing else was going to give it one.
    assert served_routes["/"]["etag"], served_routes["/"]


def test_the_backgrounds_sandbox_route_stops_claiming_the_server_is_broken(served_routes):
    """`B140`'s `Verify:`. `GET /backgrounds` either returns a page or returns
    nothing at all, and this drives the real app to say which.

    `static/backgrounds.html` is in no commit of this repository and nothing
    links to `/backgrounds` — so the route read a template that does not exist,
    through a helper whose contract is that a missing template is a broken
    deployment, and answered `500` with a `logger.exception` per request on a
    route that has no auth by design. Measured before the change: `500`, 34
    bytes, `{"detail":"Internal server error"}`.

    **The route is not removed** (`Law 1`): a deployment that ships the sandbox
    page is still served it. What is asserted here is the answer when it is
    absent — a 404 that names the file, and never a 5xx.
    """
    assert "/backgrounds" in served_routes, "the route was removed, not fixed"
    row = served_routes["/backgrounds"]
    assert row["status"] == 404, row
    assert not row["is_shell"], "a missing sandbox page must not be answered with the app"
    # It says what is missing — a 404 with no name is the same dead end as the
    # 500, one status code politer.
    assert "static/backgrounds.html" in row["head"], row
    # And says it repo-relatively. `app.py` calls this route "no auth
    # required", which describes the handler and not the path — `AuthMiddleware`
    # gates `/backgrounds` like any other page when `AUTH_ENABLED=true`, and
    # with auth off anyone who can reach the app reaches this. Either way the
    # reply must not hand out the deployment's absolute paths.
    assert str(_REPO) not in row["head"], row


@_needs_node
def test_every_shell_route_is_answered_from_the_cached_shell_offline(served_routes):
    """`B120`'s `Verify:`, driven end to end: the real install fills the cache,
    the network is taken away, and a real `FetchEvent` for each route goes
    through the shipped `fetch` handler.

    Measured on the tree before this row: `/` was answered and the other eight
    were `NOT HANDLED` — no `respondWith`, straight to a network that is not
    there — while a complete, correct copy of what they render sat in the
    cache. The installed PWA is where it bit, because `index.html` builds a
    per-route manifest with `start_url: path`: "Add to Home Screen" from
    `/tasks` installed an app whose launch URL was one of the eight.
    """
    routes = sorted(p for p, row in served_routes.items() if row["is_shell"])
    out = _run({"op": "navigate", "urls": routes})
    shell_digest = out["hashes"]["/"]
    for path in routes:
        answer = out["answered"][path]
        assert answer.get("handled"), (
            f"a navigation to {path} is claimed by no branch of the fetch "
            "handler, so with no network it fails while the document it "
            "renders is in the cache"
        )
        assert answer.get("sha") == shell_digest, (path, answer)


@_needs_node
def test_a_navigation_the_worker_has_no_document_for_is_left_alone():
    """The other half, and the one `Law 1` is about: widening the branch must
    not take a page away from anyone.

    A deep-linked `/static/*.html` prototype page and a path that does not
    exist are both answered by the network in a browser that has one, and by
    nothing here — never by the app shell, which is what the narrowing at
    `sw.js:509` was put there to stop. `/backgrounds` is in this list because
    it is a route `app.py` serves its own document at: it is not the shell and
    must never be answered with it.
    """
    urls = ["/backgrounds", "/static/whirlpool-variants.html", "/nope"]
    out = _run({"op": "navigate", "urls": urls})
    shell_digest = out["hashes"]["/"]
    for url in urls:
        answer = out["answered"][url]
        assert answer.get("sha") != shell_digest, (
            f"{url} was answered with the app shell — the regression the "
            "pathname check at sw.js:509 exists to prevent"
        )


@_needs_node
def test_the_login_page_is_answered_from_cache_offline(served_routes):
    """`B122`'s `Verify:`, the direction the row was closed in.

    The reachable failure is not the server-issued redirect the row imagined —
    a server that can redirect can serve the page. It is
    `static/js/settings.js`'s Log out button: it awaits `/api/auth/logout`
    inside a `try {} catch (_) {}`, wipes localStorage and sessionStorage, and
    then sets `location.href = '/login'` whatever happened. Offline the fetch
    rejects, the catch swallows it, the wipe happens anyway and the navigation
    happens anyway — measured before this row, that navigation was
    `NOT HANDLED`.

    It is answered with **login.html**, not with the shell. Those are different
    documents and serving one for the other is the `B120` trap.
    """
    out = _run({"op": "navigate", "urls": ["/login"]})
    answer = out["answered"]["/login"]
    assert answer.get("handled"), "a navigation to /login is claimed by no branch"
    assert answer.get("sha") == out["hashes"]["/login"]
    assert answer.get("sha") != out["hashes"]["/"]


@_needs_node
def test_the_login_page_is_read_for_what_it_references(installed):
    """`B86`'s grammar, applied to the document `B122` added.

    `login.html` names four things and names them all *relatively* —
    `static/manifest.json`, `static/icons/icon-192.png` and two Fira Code
    faces. Resolved against `/login` they are `/static/...`, and resolving them
    against anything else would put four URLs in the cache that nothing ever
    asks for. They are already there via `index.html`, so this asserts the
    *reading*, not just the result: the walk has to recognise an extensionless
    route as a document at all, which is what `docKind` now does.
    """
    referenced = installed["assets"]["/login"]
    assert referenced == [
        "/static/manifest.json",
        "/static/icons/icon-192.png",
        "/static/fonts/FiraCode-Regular.woff2",
        "/static/fonts/FiraCode-SemiBold.woff2",
    ], referenced
    assert set(referenced) <= set(installed["cached"])


@_needs_node
def test_a_precache_entry_that_redirects_is_not_stored_under_the_url_asked_for():
    """`B122`'s cost guard. `/login` is the first entry that can redirect:
    `app.py:972` sends it to `/` with a 302 when `AUTH_ENABLED` is false, and
    `fetch` follows that by default. Storing the result under `/login` would
    put a second 283 KB copy of the app shell in every auth-disabled
    deployment's cache and answer a navigation to `/login` with it.
    """
    out = _run({"op": "walk", "seeds": ["/", "/login"], "files": {
        "/": "the app shell",
        "/login": "the app shell",
    }, "redirects": ["/login"]})
    assert out["cached"] == ["/"], out["cached"]
    # It was still asked for — the guard is about what is stored, not about
    # skipping the request.
    assert "/login" in out["fetched"]


# ── `B82`: the shell's import closure, walked from outside the worker ─────────


def _shell_module_closure() -> dict:
    """Every `/static/js/**` module reachable from `static/index.html`'s script
    tags, keyed by URL and valued by the importer that spells it that way.

    The walk is `.pantheon/check-specifiers.py`'s — its comment stripper, its
    specifier grammar and its resolver (`Law 14`). What is new here is only the
    transitive step, because that checker asks a different question: it wants
    every specifier in the tree, and this wants the ones the shell can reach.

    Cache identity is the resolved URL, query included, so a module is recorded
    at the URL its *importer* spells and not at its bare path — the defect
    class `P3-11`, `B54` and `B58` each found a fresh batch of.
    """
    index = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    roots = [u for u in _ANY_SCRIPT.findall(
        check_specifiers.strip_comments(index, html=True))
        if u.startswith("/static/") and not u.startswith("/static/lib/")]
    assert len(roots) > 25, f"only found {len(roots)} script roots — parser drift?"

    found = {u: "static/index.html" for u in roots}
    frontier = list(found)
    for _round in range(32):
        if not frontier:
            break
        nxt = []
        for url in frontier:
            rel = url.split("?")[0].lstrip("/")
            source = _REPO / rel
            if not source.is_file():
                continue
            text = check_specifiers.strip_comments(
                source.read_text(encoding="utf-8", errors="replace"), html=False)
            for match in check_specifiers.IMPORT_RE.finditer(text):
                spec = match.group(1)
                path = check_specifiers.resolve(rel, spec)
                if path is None or not path.startswith("static/"):
                    continue
                _, _, query = spec.partition("?")
                target = "/" + path + (f"?{query}" if query else "")
                if target not in found:
                    found[target] = rel
                    nxt.append(target)
        frontier = nxt
    else:  # pragma: no cover - the graph settles in four rounds
        raise AssertionError("the import closure did not settle in 32 rounds")
    return {u: importer for u, importer in found.items()
            if u.startswith("/static/js/")}


@_needs_node
def test_every_module_the_shell_can_reach_is_installed(installed):
    """`B82`'s `Verify:`, and the one thing
    `test_install_caches_every_module_the_shell_imports` cannot say.

    That test is induction over the worker's *own* reading: every root is
    cached, and every import the worker found in a cached module is cached. It
    is the right ratchet and it is closed under the worker's notion of an
    import — so a `MODULE_SPECIFIER` that quietly stopped recognising
    `import('…')` would shrink both sides of it and stay green while 61 modules
    fell out of the install. That is how this row was found: by walking the
    graph from outside, which is what this does.

    Measured 2026-09-14, when the row was filed: 182 modules reachable from the
    shell's script tags and 61 named nowhere in `sw.js`. Measured again
    2026-09-15 on this tree: 173 reachable and all 173 installed — `B57`'s walk
    closed the gap, and this is the test that says so out loud and fails on the
    62nd.
    """
    closure = _shell_module_closure()
    assert len(closure) > 150, f"the closure is suspiciously small: {len(closure)}"
    cached = set(installed["cached"])
    missing = sorted((url, closure[url]) for url in closure if url not in cached)
    assert missing == [], (
        "reachable from index.html's script tags and not fetched at install, so "
        "the guarantee written above PRECACHE does not hold for them on a cold "
        f"install or the first offline use after a CACHE_NAME bump: {missing}"
    )


@_needs_node
def test_every_module_the_shell_can_reach_is_served_offline():
    """The consequence, stated the honest way `B82` asks for.

    The JS branch of the fetch handler is network-first **with runtime
    caching**, so a module fetched once while online serves offline and
    "offline is broken" would be too strong. What fails without the install
    walk is narrower and real: a cold install that never reached the page, and
    the first offline use after a `CACHE_NAME` bump, because `activate` deletes
    every cache but the current one. Both are the install cache alone, which is
    what this drives — install, then no network, then ask for every module in
    the closure through the shipped handler.
    """
    closure = sorted(_shell_module_closure())
    out = _run({"op": "navigate", "urls": closure, "mode": "cors"})
    unanswered = sorted(u for u in closure
                        if not out["answered"][u].get("handled")
                        or out["answered"][u].get("sha") != out["hashes"].get(u))
    assert unanswered == [], unanswered


# ── `B231`: the walk reads code, and what it stores is what the shell asks for ─


@_needs_node
def test_a_sentence_about_an_import_is_not_an_import():
    """`B231`, and `B87` one layer down.

    `importsOf` read raw source. `static/js/runStatus.js:33` is a JSDoc line
    explaining that the Tasks view is reached as `import('./tasks.js?v=…')` —
    with a literal ellipsis — and the walk followed it: install fetched
    `/static/js/tasks.js?v=%E2%80%A6`, the static handler answered 200 because
    it ignores the query, and the worker stored a second 178 KB copy of
    `tasks.js` under a URL no importer spells and `caches.match` (no
    `ignoreSearch`) can never serve. Every cold install and every `CACHE_NAME`
    bump, of which there have been 418.

    `.pantheon/check-specifiers.py` was taught to blank comments for *that same
    docstring*; the worker never was. The last three cases are the reason the
    stripper tracks quotes: `'https://x'` contains `//`, and a stripper that
    blanked from there would silently stop looking.
    """
    source = "\n".join([
        "import './real.js';",
        "// import './line-comment.js';",
        "/* import './block-comment.js'; */",
        "/**",
        " * `tasks.js` is only ever reached by `import('./doc-comment.js?v=…')`.",
        " */",
        "const u = 'https://cdn.example/x'; import './after-a-url.js';",
        "const t = `//not a comment`; import './after-a-template.js';",
        "import './last.js';",
    ])
    got = _run({"op": "imports", "url": "/static/js/x.js", "source": source})["imports"]
    assert got == [
        "/static/js/real.js",
        "/static/js/after-a-url.js",
        "/static/js/after-a-template.js",
        "/static/js/last.js",
    ], got


@_needs_node
def test_the_comment_rule_knows_which_grammar_it_is_reading():
    """Three grammars, because getting one wrong is worse than not stripping.

    `//` is a comment in JS and **not** in CSS, and the stylesheets this worker
    installs are minified onto one line — `katex.min.css` is a single line
    naming 60 `url()`s. Treating a protocol-relative `url(//…)` as a comment
    there would blank the rest of the file and take all 20 KaTeX fonts out of
    the install, which is a worse outcome than the phantom entry this row
    started from. HTML gets `<!-- -->` and JSON gets nothing, having no
    comments to strip.
    """
    css = ("@font-face { src: url('//cdn.example/away.woff2'); } "
           "/* @font-face { src: url('/static/fonts/Commented.woff2'); } */ "
           "@font-face { src: url('/static/fonts/Kept.woff2'); }")
    assert _run({"op": "assets", "url": "/static/style.css",
                 "source": css})["assets"] == ["/static/fonts/Kept.woff2"]

    html = ("<!-- <link rel=\"stylesheet\" href=\"/static/gone.css\"> -->\n"
            '<link rel="stylesheet" href="/static/kept.css">')
    assert _run({"op": "assets", "url": "/", "source": html})["assets"] == [
        "/static/kept.css"]

    manifest = json.dumps({"icons": [{"src": "/static/icons/kept.png"}]})
    assert _run({"op": "assets", "url": "/static/manifest.json",
                 "source": manifest})["assets"] == ["/static/icons/kept.png"]


@_needs_node
def test_nothing_is_installed_that_the_shell_cannot_reach(installed):
    """The converse of `test_every_module_the_shell_can_reach_is_installed`,
    and the direction nothing checked.

    That test asks whether the closure is a subset of the cache. Both walks can
    agree on every module the shell really imports and the worker can still
    store things nobody will ask for — a phantom URL costs a full download per
    install and a cache entry that can never be served, and it is invisible to
    a one-directional containment. On the tree this row was filed against there
    was exactly one: `/static/js/tasks.js?v=%E2%80%A6`, from a comment.

    A seed is allowed to be here without being reachable from `index.html` —
    that is what a seed is for (`/login`'s graph, and `PANEL_PRECACHE`).
    """
    closure = set(_shell_module_closure())
    seeds = {u for u in _precached() if u.startswith("/static/js/")}
    unreachable = sorted(u for u in installed["cached"]
                         if u.startswith("/static/js/")
                         and u not in closure and u not in seeds)
    assert unreachable == [], (
        "install fetches and stores these, and no importer in the shell graph "
        "and no seed spells them — so each is a download per install for a "
        f"cache entry the fetch handler can never match: {unreachable}")


@_needs_node
def test_the_two_leaf_tables_this_row_named_are_installed_by_derivation(installed):
    """`B231` as filed said `static/js/icons.js` and
    `static/js/attachmentLanguage.js` are "in no precache list" and that a cold
    offline load therefore 404s on both. Re-measured here: the first half is
    true and the second does not follow. Both are reached from
    `index.html`'s script tags — `icons.js` through `markdown.js`,
    `attachmentLanguage.js` through `document.js` — so `B57`'s install walk
    fetches them, and adding them to a list is the second copy the comment
    above `PRECACHE` forbids.

    Same shape as `test_the_modules_no_list_names_are_there_by_derivation`, and
    kept separate from it because these two are what the row is about.
    """
    named = {"/static/js/icons.js", "/static/js/attachmentLanguage.js"}
    closure = _shell_module_closure()
    assert named <= set(closure), sorted(named - set(closure))
    cached = set(installed["cached"])
    assert named <= cached, sorted(named - cached)
    source = _sw_code()
    assert [u for u in named if u in source] == [], (
        "these are derived; a list entry would be a second thing to keep in step")


@_needs_node
def test_a_module_a_shelled_module_imports_and_the_walk_misses_is_caught():
    """`B231`'s `Verify:`, second half, driven rather than asserted about.

    The claim under test is that the manifest test fails when a module a
    shelled module imports is not itself installed. Here the walk is given a
    tree where it can see the root's import and not the leaf's, which is what a
    narrowed `MODULE_SPECIFIER` or a shrunken `isWalkable` does in the large.
    """
    out = _run({"op": "walk", "seeds": ["/static/js/root.js"],
                "files": {
                    "/static/js/root.js": "import './mid.js';",
                    # The specifier is spelled in a way the grammar does not
                    # match — a template literal — so the leaf is reachable in
                    # a browser and invisible to the walk.
                    "/static/js/mid.js": "import(`./leaf.js`);",
                    "/static/js/leaf.js": "",
                }})
    assert out["cached"] == ["/static/js/mid.js", "/static/js/root.js"], out["cached"]
    assert "/static/js/leaf.js" not in out["cached"]
