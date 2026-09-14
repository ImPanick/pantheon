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
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SW = _REPO / "static" / "sw.js"

_MODULE_SCRIPT = re.compile(r'<script[^>]*type="module"[^>]*src="([^"]+)"')
_STYLESHEET = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')


def _precached() -> set:
    """Every `/static/...` string literal in sw.js, both lists and the fonts."""
    return set(re.findall(r"'(/static/[^']+)'", _SW.read_text(encoding="utf-8")))


def _shell_requests(page: Path) -> list:
    html = page.read_text(encoding="utf-8")
    found = _MODULE_SCRIPT.findall(html) + _STYLESHEET.findall(html)
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
