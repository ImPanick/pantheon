# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AGPL-3.0 §13 source offer, as one control on every page the app serves.

`P0-17`. §13 obliges whoever **offers a modified version over a network** to give
the users interacting with it an opportunity to receive the Corresponding
Source. Pantheon is a modified Odysseus, so the obligation attaches to the
operator the moment they put it in front of anybody but themselves.

**Where it points: this repository, unless the operator says otherwise**
(`D-2026-10-02-04` §2). It shipped dark from 2026-09-18 to 2026-10-02 —
`D-2026-09-08-06`, *"prime it, but dont flip that switch yet"* — because the
repository was private and a link a stranger gets a 404 from is an offer that
cannot be honoured (`B25`). The repository is public (`D-2026-10-02-03`), so an
unmodified install now offers the source it runs: `DEFAULT_SOURCE_URL`. The
order is stored setting → `PANTHEON_SOURCE_URL` → that default, through
`env_backed`, so `DEFAULT_SETTINGS["source_url"]` still ships empty and the
environment stays reachable beneath it (`H06`, `B20`). **A modified copy must
point it at its own source** — §13 obliges whoever offers the *modified* version
— and `docs/setup.md` says so where the variable is explained. The address is
still the only control (`D-2026-09-05-01`, `Law 14`); one that is not an
absolute http(s) URL draws no link rather than a wrong one.
`.pantheon/check-destinations.py` names this default as its one shipped
exception, with the reason.

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

# `D-2026-10-02-04` §2. The public repository this program is published from —
# what an unmodified install offers. `.pantheon/check-destinations.py` names this
# exact address (`SHIPPED_DEFAULTS`); moving it anywhere else fails that check.
DEFAULT_SOURCE_URL = "https://github.com/ImPanick/pantheon"

# `javascript:`, `data:` and friends are refused. The value is operator-set
# rather than user-set, so this is not the front line — but it is written into
# an `href` on the **login page**, which is the one document in this product
# that is served before anybody has authenticated, and a control that renders
# untrusted-shaped input into a pre-auth page gets the narrow rule.
_ALLOWED_SCHEMES = ("http", "https")


def source_url() -> str:
    """The repository this instance offers, or `""` when the configured value
    is not an absolute http(s) URL.

    Stored `source_url` → `PANTHEON_SOURCE_URL` → `DEFAULT_SOURCE_URL`. The stored
    layer ships empty (`DEFAULT_SETTINGS`), which is what keeps the variable
    reachable beneath it (`H06`, `B20`); the default sits under both. An
    unreadable settings file is not a reason to withdraw the offer: the
    environment and the default still answer.
    """
    import os

    from src.settings import env_backed, load_settings

    try:
        raw = env_backed(load_settings(), "source_url", "PANTHEON_SOURCE_URL",
                         DEFAULT_SOURCE_URL)
    except Exception:
        logger.exception("Failed to read source_url; offering the environment's or the default")
        raw = os.environ.get("PANTHEON_SOURCE_URL") or DEFAULT_SOURCE_URL
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
    """The footer control, or `""` when the address is not an http(s) URL.

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
