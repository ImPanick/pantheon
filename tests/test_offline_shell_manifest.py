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

import json
import shutil
import subprocess
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SW = _REPO / "static" / "sw.js"
_HARNESS = _REPO / "tests" / "harness" / "sw_install_graph.js"

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
    text = _SW.read_text(encoding="utf-8")
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
    src = _SW.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    assert "ignoreSearch" not in code, (
        "sw.js now ignores query strings when matching; the precache list no "
        "longer has to be exact, so revisit B54 and these tests together"
    )


def test_the_login_page_shell_is_covered_too():
    # login.html is the one screen index.html's modules never reach. It carries
    # its own inline styles today, so it requests no external shell resources —
    # asserted rather than assumed, because the day it grows a <script
    # type="module"> tag is the day it needs to be in the manifest.
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
    source = _SW.read_text(encoding="utf-8")
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
