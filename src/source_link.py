# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AGPL-3.0 §13 source offer, as one control on every page the app serves.

`P0-17`. §13 obliges whoever **offers a modified version over a network** to give
the users interacting with it an opportunity to receive the Corresponding
Source. Pantheon is a modified Odysseus, so the obligation attaches to the
operator the moment they put it in front of anybody but themselves.

**Why it ships dark.** `D-2026-09-08-06`: *"prime it, but dont flip that switch
yet."* The repository is private today and the default bind is loopback, so no
§13 offer is being made and none is owed. A link pointing at a repository a
stranger gets a 404 from would be **worse than no link** — it is an offer that
cannot be honoured, which is the failure `B25` had already produced once in
`CHANGELOG.md`. So the address is the switch and there is no second boolean
beside it (`D-2026-09-05-01`, `Law 14`): set `source_url` and the control
appears, leave it empty and the app claims nothing. Obligation and control
arrive together, in that order.

**One injection site, not two** (`Law 13`). `serve_html_with_nonce` is the front
door for both `/` and `/login`; the link goes in there rather than into the two
documents, so a third page served that way carries it the day it is added and
nobody has to remember. That also keeps it out of `static/index.html`, whose
element ids and classes are load-bearing (`FORBIDDEN` Part 1).

**No colour is named.** The control consumes `--accent` with a fallback to
`--fg-muted`, both of which already exist; `--accent` is set per theme and is
never defined in `:root`, and this does not define it. Sixteen themes and the
link inherits all of them.
"""

import html
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# The decision's words, verbatim (`D-2026-09-08-06`). The visible label says
# what the control offers; this says where the program came from. Both are the
# point: §13 is about the source, and the fork owes Odysseus the provenance.
SOURCE_LINK_TITLE = "Built on Odysseus — click to see where Pantheon originated from!"
SOURCE_LINK_LABEL = "Source"
SOURCE_LINK_ARIA = "Source code for this instance (AGPL-3.0-or-later)"

# `javascript:`, `data:` and friends are refused. The value is operator-set
# rather than user-set, so this is not the front line — but it is written into
# an `href` on the **login page**, which is the one document in this product
# that is served before anybody has authenticated, and a control that renders
# untrusted-shaped input into a pre-auth page gets the narrow rule.
_ALLOWED_SCHEMES = ("http", "https")


def source_url() -> str:
    """The configured repository address, or `""` when there is none.

    Empty is the shipped state. `.pantheon/check-destinations.py` enforces that
    a `*_url` default ships falsy, so the dark default is a build rule here and
    not merely an intention — and the falsiness is also what keeps
    `PANTHEON_SOURCE_URL` reachable beneath it (`H06`, `B20`).
    """
    from src.settings import env_backed, load_settings

    try:
        raw = env_backed(load_settings(), "source_url", "PANTHEON_SOURCE_URL")
    except Exception:
        logger.exception("Failed to read source_url; the §13 link stays dark")
        return ""
    return normalise_source_url(raw)


def normalise_source_url(raw) -> str:
    """`raw` if it is an absolute http(s) URL, else `""`.

    Returns rather than raises: this is called on the page-render path, and a
    malformed address is a reason to show no link, never a reason to fail to
    serve the application.
    """
    if not isinstance(raw, str):
        return ""
    value = raw.strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    # `.lower()` is belt-and-braces and mutation testing says so: `urlparse`
    # already case-folds the scheme, so no input can tell this line from its
    # absence. Kept anyway — it costs nothing and the alternative is a scheme
    # allowlist whose correctness depends on a normalisation performed
    # somewhere else. The `netloc` check is not redundant and is the one doing
    # the work against `javascript:alert(1)`; the allowlist is what stops
    # `javascript://host/%0Aalert(1)`, which has a netloc.
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.netloc:
        return ""
    return value


def source_link_html(url: str = None) -> str:
    """The footer control, or `""` when no address is configured.

    Inline styles and no new class, because `static/style.css` is not this
    row's to extend and a licence control may not wait on a stylesheet. The
    wrapper takes no pointer events so it can never swallow a click meant for
    the app; the anchor itself takes them back.
    """
    url = source_url() if url is None else normalise_source_url(url)
    if not url:
        return ""
    href = html.escape(url, quote=True)
    return (
        '<div class="pan-source-offer" data-source-offer="1" '
        'style="position:fixed;right:10px;bottom:6px;z-index:9000;'
        'pointer-events:none;font-size:10px;line-height:1;font-family:inherit">'
        f'<a href="{href}" target="_blank" rel="noopener noreferrer license"'
        f' title="{html.escape(SOURCE_LINK_TITLE, quote=True)}"'
        f' aria-label="{html.escape(SOURCE_LINK_ARIA, quote=True)}"'
        ' style="pointer-events:auto;color:var(--accent,var(--fg-muted));'
        'text-decoration:none;opacity:0.65;padding:3px 6px;border-radius:5px;'
        'border:1px solid var(--border);background:var(--panel)"'
        f'>{html.escape(SOURCE_LINK_LABEL)}</a></div>'
    )
