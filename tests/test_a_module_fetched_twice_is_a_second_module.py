# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B58` (absorbing `B09`) — four assets were reachable under two URLs each.

`check-specifiers.py` has enforced "one query string per module path" since
`P3-11`, at `--max 0`, and reported `FORKED 0` the whole time — because it read
four of the six places a URL is written in this tree. It had no pattern for
`<link rel="modulepreload">` and none for `static/sw.js`'s precache list, and
both defects lived exactly there.

  * `chat.js` was preloaded at `?v=20260815toolapproval4` and executed at
    `?v=20260829trustladder1`. The HTTP cache and the module map are keyed on
    the full URL, query included, so 372 KB was fetched twice on every cold
    load, both on the critical path. `git log -L` says the preload line had not
    been edited since the fork baseline while the script tag was bumped twice.
  * `admin.js`, `emailInbox.js` and `sidebar-layout.js` were precached bare and
    imported with a version. `sw.js` matches with `cache.match(e.request)` and
    no `ignoreSearch`, so those three were downloaded at install and could
    never answer a request.

These tests hold the *scope*, which is the thing that was wrong. The checker
cannot assert its own blind spots, and `--max 0` in CI proves nothing about a
place the regexes never look.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-specifiers.py"

_spec = importlib.util.spec_from_file_location("check_specifiers", _CHECKER)
check_specifiers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_specifiers)


def _hits(regex, text):
    return [m.group(1) for m in regex.finditer(text)]


def test_a_modulepreload_is_a_specifier():
    """The blind spot that hid `chat.js`. Both attribute orders, because HTML
    does not care and a regex does."""
    forward = '<link rel="modulepreload" href="/static/js/chat.js?v=abc">'
    reverse = '<link href="/static/js/chat.js?v=abc" rel="modulepreload">'
    plain = '<link rel="preload" href="/static/js/chat.js?v=abc" as="script">'
    assert _hits(check_specifiers.LINK_RE, forward) == ["/static/js/chat.js?v=abc"]
    assert _hits(check_specifiers.LINK_REV_RE, reverse) == ["/static/js/chat.js?v=abc"]
    assert _hits(check_specifiers.LINK_RE, plain) == ["/static/js/chat.js?v=abc"]


def test_a_precache_entry_is_a_specifier():
    """The blind spot that hid the three dead service-worker entries."""
    listed = "const PRECACHE = [\n  '/static/js/admin.js?v=abc',\n  '/static/js/notes.js',\n];"
    assert _hits(check_specifiers.PRECACHE_RE, listed) == [
        "/static/js/admin.js?v=abc", "/static/js/notes.js",
    ]


def test_a_stylesheet_link_is_not_mistaken_for_a_module():
    """The widened pattern must not start counting things that are not modules."""
    css = '<link rel="stylesheet" href="/static/style.css?v=abc">'
    icon = '<link rel="icon" href="/static/icons/favicon.js">'
    assert _hits(check_specifiers.LINK_RE, css) == []
    assert _hits(check_specifiers.LINK_RE, icon) == []


def test_no_module_in_this_tree_is_reachable_under_two_urls():
    """The property itself, computed rather than asserted about the source."""
    forked = {p: dict(q) for p, q in check_specifiers.scan().items() if len(q) > 1}
    assert not forked, forked


def test_the_checker_still_fails_when_something_forks():
    """`--max 0` has to still bite, or the scope widening bought nothing."""
    result = subprocess.run([sys.executable, str(_CHECKER), "--max", "0"],
                            cwd=str(_REPO), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
    assert "FORKED 0" in result.stdout


@pytest.mark.parametrize("asset", [
    "static/js/chat.js", "static/js/admin.js",
    "static/js/emailInbox.js", "static/js/sidebar-layout.js",
])
def test_the_four_that_were_forked_are_each_reached_under_one_query(asset):
    seen = check_specifiers.scan()
    assert asset in seen, f"{asset} is reached by nothing — did it get renamed?"
    assert len(seen[asset]) == 1, seen[asset]


# The two tests below exist because a mutation run walked straight past the
# first draft of this file. Patterns that exist and a tree that is clean both
# stay true if `scan()` stops CALLING the patterns — so these assert the wiring
# by naming the source each specifier has to be attributed to. Having the rule
# and reading the file are two different things, which is the whole of `B58`.

def test_scan_actually_reads_the_preload_links():
    importers = check_specifiers.scan()["static/js/chat.js"]
    (query,) = importers
    # index.html reaches chat.js twice: the <script> tag and the modulepreload.
    assert importers[query].count("static/index.html") == 2, importers


def test_scan_actually_reads_the_service_worker_precache_list():
    importers = check_specifiers.scan()["static/js/admin.js"]
    (query,) = importers
    assert "static/sw.js" in importers[query], importers
