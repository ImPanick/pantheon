# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-07` — one button means the fields are gone, not that one of them is hidden.

The owner set the measure: *"as easy as fucking possible"*, and the honest test
of that is a count. Linking a mailbox took **fifteen fields**. `P18-01` made the
button appear; this makes the button the whole interaction.

**THE SERVER ALREADY KNEW EVERY ANSWER.** The OAuth callback fills `imap_host`,
`imap_port`, `imap_starttls`, `smtp_host`, `smtp_port`, `imap_user`, `smtp_user`,
`from_address`, `name` and `display_name` — four of them pinned as module
constants, the rest read off the Google identity. The form was asking for values
the server pins and values it is about to be told.

**ENABLING THAT WALKED INTO A BUG THE ROW DID NOT NAME, AND IT WAS ALREADY
REACHABLE.** The callback set `smtp_port = 587` and never touched
`smtp_security`, which defaults to `"ssl"` — and
`_google_oauth_smtp_transport_allowed` permits only `(465, ssl)` or
`(587, starttls)`. So an account linked without an SMTP host typed came out as
**SSL on port 587**, a pair this app's own validator rejects. `smtplib.SMTP_SSL`
against 587 does not negotiate; it hangs to the socket timeout and reports as a
connection failure, which reads like a firewall rather than a config error.
Reachable before this row by anyone who left the SMTP host blank — and reachable
*by default* once linking requires typing nothing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
EMAIL_ROUTES = ROOT / "routes" / "email_routes.py"


INDEX_HTML = ROOT / "static" / "index.html"

# The `uf-` form. There are two complete email-account forms in settings.js and
# only this one is mounted — see `test_the_oauth_form_is_the_one_that_is_mounted`,
# which is the assertion that would have saved a day's work.
_FIELD = "uf-"


def _account_form_template() -> str:
    text = SETTINGS_JS.read_text(encoding="utf-8")
    start = text.index("async function showEmailForm")
    start = text.index("formEl.innerHTML = `", start)
    return text[start : text.index("`;", start)]


# --------------------------------------------------------------------------
# The pair the callback used to produce
# --------------------------------------------------------------------------


def test_the_callback_sets_a_transport_its_own_validator_accepts():
    """The bug, stated as the rule it broke.

    Asserted through `_google_oauth_smtp_transport_allowed` rather than against
    the literal 587, so the test tracks the rule instead of restating it.
    """
    import routes.email_routes as er

    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    block = source[source.index('if not row.smtp_host:'):]
    block = block[: block.index("if email_addr:")]
    port = int(re.search(r"row\.smtp_port = (\d+)", block).group(1))
    security = re.search(r'row\.smtp_security = "(\w+)"', block).group(1)
    assert er._google_oauth_smtp_transport_allowed(port, security), (
        f"the callback writes ({port}, {security}), which this app refuses"
    )


def test_the_callback_sets_an_imap_transport_its_own_validator_accepts():
    import routes.email_routes as er

    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    block = source[source.index('if not row.imap_host:'):]
    block = block[: block.index("if not row.smtp_host:")]
    port = int(re.search(r"row\.imap_port = (\d+)", block).group(1))
    starttls = re.search(r"row\.imap_starttls = (\w+)", block).group(1) == "True"
    assert er._google_oauth_imap_transport_allowed(port, starttls)


def test_the_callback_uses_the_pinned_hosts_rather_than_literals():
    """Two spellings of one hostname is how the P18-01 defect started."""
    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    block = source[source.index('if not row.imap_host:'):]
    block = block[: block.index("if email_addr:")]
    assert "_GOOGLE_OAUTH_IMAP_HOST" in block
    assert "_GOOGLE_OAUTH_SMTP_HOST" in block
    assert '"imap.gmail.com"' not in block and '"smtp.gmail.com"' not in block


# --------------------------------------------------------------------------
# Typing nothing
# --------------------------------------------------------------------------


def test_a_row_created_to_be_linked_needs_no_name():
    """The address comes back from the provider; there is nothing to insist on."""
    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    assert "_LINKABLE_PROVIDERS" in source
    assert 'if not name and pending_link not in _LINKABLE_PROVIDERS:' in source


def test_a_nameless_account_is_named_after_its_own_id():
    """Not a placeholder invented here — the callback already tests for it.

    `row.name == row.id` is a branch written for exactly this case and
    unreachable until now, because nothing could create such a row.
    """
    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    assert "name=name or _new_id," in source
    assert "row.name == row.id" in source, (
        "the callback branch that renames the placeholder is gone"
    )


def test_every_other_caller_still_needs_a_name():
    """The guard is relaxed for one case, not removed."""
    import asyncio
    import routes.email_routes as er

    source = EMAIL_ROUTES.read_text(encoding="utf-8")
    guard = source[source.index("async def create_email_account"):]
    guard = guard[: guard.index("imap_port, port_err")]
    assert 'return {"ok": False, "error": "name required"}' in guard


def test_an_arbitrary_pending_value_does_not_bypass_the_name_guard():
    """`_LINKABLE_PROVIDERS` is an allowlist, so `oauth_pending: "yes"` is not a key."""
    import routes.email_routes as er

    assert "yes" not in er._LINKABLE_PROVIDERS
    assert "google" in er._LINKABLE_PROVIDERS


def test_the_connect_button_no_longer_demands_a_name_first():
    js = SETTINGS_JS.read_text(encoding="utf-8")
    assert js.count("body.oauth_pending = 'google'") >= 1


# --------------------------------------------------------------------------
# The count, which is the measure the row set
# --------------------------------------------------------------------------


def test_every_field_the_callback_fills_is_inside_the_hideable_block():
    """The block is only honest if it contains everything OAuth makes redundant.

    A field left outside it is a field the person is still asked for, and the
    hiding then looks like tidying rather than like one button.
    """
    tpl = _account_form_template()
    block = tpl[tpl.index('<div id="uf-manual">') :]
    for field in (
        "uf-email-name",
        "uf-email-from",
        "uf-display-name",
        "uf-imap-host",
        "uf-imap-port",
        "uf-imap-user",
        "uf-imap-pass",
        "uf-imap-starttls",
        "uf-smtp-host",
        "uf-smtp-port",
        "uf-smtp-security",
        "uf-smtp-user",
        "uf-smtp-pass",
    ):
        assert field in block, f"{field} is still asked for on the OAuth path"


def test_the_button_sits_above_the_block_it_replaces():
    """Below it, the person scrolls past fifteen fields to reach the shortcut."""
    tpl = _account_form_template()
    assert tpl.index("uf-oauth-section") < tpl.index('<div id="uf-manual">')


def test_the_block_is_hidden_only_while_a_qualifying_account_is_unlinked():
    """Three states, and the middle one is the row.

    Not a Google host: everything shows, because nothing else can fill it in.
    Google host, not linked: the button is the interaction.
    Linked: the fields come back, populated and worth reading.
    """
    js = SETTINGS_JS.read_text(encoding="utf-8")
    match = re.search(
        r"manual\.style\.display = \(provider && !linked\) \? 'none' : ''", js
    )
    assert match is not None, "the visibility rule is not the three-state one"


def test_the_form_still_works_for_everything_that_is_not_google():
    """`Law 1`. A Migadu or Dovecot account is typed in, exactly as before."""
    tpl = _account_form_template()
    assert "uf-email-provider" in tpl
    assert "uf-imap-host" in tpl and "uf-smtp-host" in tpl


# --------------------------------------------------------------------------
# The assertion that would have saved a day, written after it did not exist
# --------------------------------------------------------------------------


def test_the_oauth_form_is_the_one_that_is_mounted():
    """There are two complete email-account forms and only one is reachable.

    `P18-01` and the first pass of this row were written against the `eaf-`
    form, which mounts into `set-email-accounts-form` — an id that appears
    **zero times** in `static/index.html` and is created by nothing. Its
    initialiser opens `if (!listEl || !addBtn || !formEl) return;`, so it
    silently does nothing on every page load, and two other modules already
    treat it as legacy by querying `'#unified-intg-form,
    #set-email-accounts-form'` with the live one first.

    `check-wiring.py` **did** catch the ids — all four sit in its unresolved
    list. They are inside the 124 the ratchet grandfathers, which is the
    ratchet working as designed and is also why a whole dead form could sit
    there unnoticed. This test is the narrow version: whichever form carries
    the account-linking flow has to mount somewhere that exists.

    `B69` removes the dead one.
    """
    js = SETTINGS_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    start = js.index("async function showEmailForm")
    # Walk back to the container this form renders into.
    head = js[:start]
    container = re.findall(r"const formEl = el\('([\w-]+)'\)", head)[-1]
    assert f'id="{container}"' in html, (
        f"the OAuth form renders into #{container}, which is not in index.html"
    )
