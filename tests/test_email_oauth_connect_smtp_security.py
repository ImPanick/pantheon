# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for SMTP security saved before Google OAuth.

**RE-ANCHORED BY `B69`, AND THE REASON IS THE REGRESSION ITSELF.** This test was
written against `el('eaf-oauth-btn')` — the Connect handler of the second
email-account form, which `B69` established had been unmounted since before the
fork (upstream `ea2778d9` removed the markup and left the JavaScript). So the
guard was real, the property it describes is real, and it was watching a handler
no browser ever ran.

The property holds in the live form and is now asserted where it is enforced:
`showEmailForm`'s single `_collectBody()`. That is strictly stronger than the
original. The old version pinned one handler, and the form it pinned had **two**
body builders that had already drifted apart on `smtp_port` — 587 in Connect and
465 in Save. Asserting the shared builder covers Connect, Save and test-connection
at once, and there is no second builder left to drift.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _collect_body_source() -> str:
    source = (_REPO / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    start = source.index("async function showEmailForm")
    start = source.index("const _collectBody = () => {", start)
    return source[start : source.index("return body;", start)]


def test_email_oauth_connect_persists_selected_smtp_security():
    body = _collect_body_source()
    assert "smtp_security: el('uf-smtp-security').value" in body
    assert "display_name: el('uf-display-name').value.trim()" in body


def test_every_submit_path_uses_the_one_builder():
    """What makes the assertion above cover Connect as well as Save.

    Connect, Save and any other path share one builder, so a field added to the
    body reaches all of them and cannot be present on one route and missing on
    another — which is how `smtp_port` came to mean two different things in the
    form this test used to watch.
    """
    source = (_REPO / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    form = source[source.index("async function showEmailForm"):]
    assert len(re.findall(r"const _collectBody = ", form)) == 1
    assert len(re.findall(r"_collectBody\(\)", form)) >= 3
