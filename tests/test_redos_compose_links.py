# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1918`. A compose body of `[` held the server while it rendered the mail.

`POST /api/email/send` renders the compose box's markdown into the message's
HTML part with `routes/email_routes._md_to_email_html` whenever the request
carries no `body_html` (a send through an API token carries none), and the
renderer found links with `re.sub(r"\\[([^\\]]+)\\]\\((https?://[^)\\s]+)\\)", ...)`.
From every `[` with no `]` after it that pattern reads to the end of the line,
so its time grows with the square of the line: measured on `a5341d78`, 40,000
`[` took 4.8 s and 80,000 about four times that. The body has no length cap,
and a regex holds the GIL, so every other request waited with it.

Now links are found by `_md_links_to_html`, upstream Odysseus 3d91ad82's
forward-only scan: a `[` that shares its `]` with an earlier `[` cannot start a
link the earlier one did not, and neither can one whose `]` lies inside a link
address that never closed, so both are skipped. It writes exactly what the
pattern wrote, and the control `FORBIDDEN.md` Part 2 names for this renderer
is unchanged: `html.escape` runs first, and only an http(s) address becomes a
link.

Two halves: the scan links exactly what the old pattern linked, and each of
upstream's two flood shapes is rendered within the budget, timed in a fresh
interpreter so the old code is killed rather than waited for.
"""

import itertools
import random
import re

import pytest

from tests.helpers.timed_process import seconds_in_a_fresh_process

_BUDGET_S = 2.0

#: The pattern `_md_to_email_html` used before `B1918`, as the reference.
_LINK_REF = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

_CASES = [
    # Upstream's cases.
    "see [docs](https://example.com/a) and [b](http://x.y)",
    "[a[b](http://x)",
    "[]()[x](http://y)",
    "[a](http://x [b c](http://y)",
    "[a](http://)[b](https://z)",
    "[a](ftp://x) [b](https://ok)",
    "[unterminated(http://x)",
    "[t](http://u) tail ] [",
    # Only http(s) becomes a link, and a quote stays inside the address.
    "[x](javascript:alert(1))",
    '[x](http://a"b)',
    "[x](HTTP://upper.example)",
    "[<b>](https://e.example/?a=1&b=2)",
]
_CASES += ["".join(p) for n in range(6) for p in itertools.product(["[", "]", "(", ")", "http://", "a", " "], repeat=n)]
_rng = random.Random(1918)
_PIECES = ["[", "]", "(", ")", "http://", "https://", "ftp://", "a", " ", "\t", '"', "<", "&", "x"]
_CASES += ["".join(_rng.choices(_PIECES, k=_rng.randint(0, 24))) for _ in range(20_000)]


def test_links_are_found_exactly_where_the_old_pattern_found_them():
    import html

    from routes.email_routes import _md_links_to_html

    for text in _CASES:
        # Raw, and as `_md_to_email_html` hands it over: escaped first.
        for given in (text, html.escape(text)):
            assert _md_links_to_html(given) == _LINK_REF.sub(r'<a href="\2">\1</a>', given), repr(given)


@pytest.mark.parametrize("flood", [
    '"[" + "[\\\\" * 60_000',   # CodeQL's reported shape: `[` that never meet a `]`
    '"[a](http://x" * 16_000',  # a link address that never closes, again and again
])
def test_a_compose_body_of_brackets_is_rendered_within_the_budget_and_still_escaped(flood):
    seconds = seconds_in_a_fresh_process(
        "import src.agent_tools\n"
        "from routes.email_routes import _md_to_email_html\n"
        f"flood = {flood}\n"
        # One line, so every `[` is on the line the renderer scans; the links
        # after it are `FORBIDDEN.md` Part 2's control, held through the flood.
        "body = flood + ' [x](javascript:alert(1)) [y](http://a\"b) <script>alert(1)</script>'",
        "out = _md_to_email_html(body)\n"
        "assert '<script>' not in out and '&lt;script&gt;' in out, out[-300:]\n"
        "assert 'javascript' in out and 'href=\"javascript' not in out, out[-300:]\n"
        "assert '<a href=\"http://a&quot;b\">y</a>' in out, out[-300:]",
    )
    assert seconds < _BUDGET_S, f"{seconds:.1f} s"
