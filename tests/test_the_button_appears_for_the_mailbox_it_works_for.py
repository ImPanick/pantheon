# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-01` — one button, offered to the mailboxes it actually works for.

Google email OAuth was never missing from this fork. It was **built, tested and
live** — authorize, callback, refresh, four database columns, ten test files.
What was missing is that almost nobody could reach it, and that it half-worked
once they did. Writing a *build OAuth account linking* epic here would have
rebuilt a working thing, which is the `P17-02` mistake one phase later.

Three defects, and the third is the one that matters:

  1. **The button was hidden from Gmail.** `static/js/settings.js` listed eight
     providers and exactly one carried an `oauth:` marker — `google_workspace`.
     That marker was the only thing that revealed the button. Picking **Gmail**
     filled in `imap.gmail.com` and showed nothing; picking **Google Workspace**
     filled in the identical host and showed the button. Same mailbox, two
     answers, because *is this Google* was written twice — once as a hostname
     comparison on the server, which is the copy that runs when the link is
     used, and once as a dropdown marker in the browser (`Law 13`; `B65` is the
     standing proof of what a rule in two languages costs).

  2. **Custom hosts never qualified.** A person who typed `imap.gmail.com` by
     hand reached a working flow that was never offered to them.

  3. **The button was offered on installs where it cannot work, and it failed
     at the worst possible moment.** `.env.example` ships both Google
     credentials commented out. Authorize only ever checked
     `GOOGLE_OAUTH_CLIENT_ID`; the *callback* needs the secret as well and
     posted an empty one to Google's token endpoint. So on a default install
     the path was: press Connect, **the account is saved**, go to Google,
     **grant full mailbox access** — the `https://mail.google.com/` scope, read
     and write — come back, and get `invalid_client`. The consent is the step a
     person cannot take back, and it was being spent on a flow that could not
     complete.

The fix is not a fourth answer. The host list is **served** by the endpoint that
already owns the rule, and the browser asks rather than restates.

**AND THE PASSWORD FIELDS STAY.** Making Gmail qualify while keeping the old
hide-the-password behaviour would have removed the app-specific-password path
from the mailboxes most likely to use it. `Law 1`: we add, never subtract. OAuth
is an offer here, not a mode — the password only goes away once an account is
genuinely linked, where leaving it would invite somebody to fill it in.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"


@pytest.fixture()
def email_routes():
    import routes.email_routes as er

    return er


# --------------------------------------------------------------------------
# The rule itself, on the server, where it already lived
# --------------------------------------------------------------------------


def test_the_provider_list_names_the_hosts_the_guards_compare_against(email_routes):
    """The served list and the enforcing guard must be the same constant.

    If these ever diverge the browser offers a button for a host the server
    will refuse, which is the original defect wearing different clothes.
    """
    providers = email_routes._oauth_providers()
    google = next(p for p in providers if p["id"] == "google")
    assert google["imap_hosts"] == [email_routes._GOOGLE_OAUTH_IMAP_HOST]
    assert google["smtp_hosts"] == [email_routes._GOOGLE_OAUTH_SMTP_HOST]


def test_configured_requires_both_halves(email_routes, monkeypatch):
    """The id alone gets you to Google. The secret is what gets you back."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    assert email_routes._google_oauth_configured() is False

    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csec")
    assert email_routes._google_oauth_configured() is False

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    assert email_routes._google_oauth_configured() is True


def test_whitespace_is_not_a_credential(email_routes, monkeypatch):
    """A `.env` line left as `GOOGLE_OAUTH_CLIENT_ID= ` is unset, not set."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "   ")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csec")
    assert email_routes._google_oauth_configured() is False


def test_a_default_install_reports_the_button_as_unusable(email_routes, monkeypatch):
    """`.env.example` ships both commented out, so this is the common case."""
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    google = next(p for p in email_routes._oauth_providers() if p["id"] == "google")
    assert google["configured"] is False
    assert google["setup_hint"], "an unusable button must say what would make it work"
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in google["setup_hint"]


def test_the_hint_names_both_variables(email_routes, monkeypatch):
    """Naming only the id is how somebody sets one and hits the same wall."""
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    hint = next(p for p in email_routes._oauth_providers() if p["id"] == "google")["setup_hint"]
    assert "GOOGLE_OAUTH_CLIENT_ID" in hint and "GOOGLE_OAUTH_CLIENT_SECRET" in hint


# --------------------------------------------------------------------------
# The browser, which must ask the rule rather than hold a copy of it
# --------------------------------------------------------------------------


def _oauth_decision_source() -> str:
    """The two functions that decide whether to offer the button.

    Sliced out deliberately: `PROVIDERS` further up the file legitimately
    contains `imap.gmail.com` as *preset autofill data*, and asserting the
    string is absent from the whole file would fail for the wrong reason. What
    must not contain it is the code that makes the decision.
    """
    text = SETTINGS_JS.read_text(encoding="utf-8")
    start = text.index("const _oauthFor =")
    end = text.index("const eafProviderNotes", start)
    return text[start:end]


def _without_comments(source: str) -> str:
    """Strip `//` lines. A comment naming a host is not a rule about hosts.

    Written without this and it failed immediately — on the comment above the
    password rule, which explains the Gmail case in prose. That is the same
    distinction `check-tool-surface.py` makes when it reads dispatch with `ast`
    rather than a regex: naming a thing and doing something about it are
    different, and a check that cannot tell them apart reports the explanation
    as the defect.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )


def test_the_decision_holds_no_hostname_of_its_own():
    """`Law 13`: the rule is asked, never restated.

    A second copy of *which hosts are Google* in JavaScript is exactly the
    defect this row exists to close, and it would be invisible until the two
    copies disagreed — which is how the first one was found.
    """
    source = _without_comments(_oauth_decision_source())
    for literal in ("gmail", "googlemail", "google.com"):
        assert literal not in source.lower(), (
            f"the OAuth decision mentions {literal!r} — it must use the host list "
            f"the server sends, not one of its own"
        )


def test_the_decision_is_driven_by_the_host_field_not_the_dropdown():
    source = _oauth_decision_source()
    assert "el('eaf-imap-host').value" in source
    assert "PROVIDERS[" not in source, "the dropdown must not decide this any more"


def test_typing_a_host_by_hand_re_runs_the_rule():
    """The defect was that only the preset path ever asked."""
    text = SETTINGS_JS.read_text(encoding="utf-8")
    assert "el('eaf-imap-host').addEventListener('input', _syncOauthUI)" in text


def test_the_host_list_is_fetched_from_the_endpoint_that_owns_it():
    text = SETTINGS_JS.read_text(encoding="utf-8")
    assert "/api/email/oauth/providers" in text


def test_the_password_fields_are_hidden_only_for_a_linked_account():
    """`Law 1`. Qualifying Gmail must not take the app-password path away.

    The old rule hid the password whenever OAuth was *available*. Applied to
    Gmail that removes the way most `@gmail.com` mailboxes are connected today.
    The new rule keys on `linked` — an account that has actually completed the
    flow — so the offer costs nothing.
    """
    source = _oauth_decision_source()
    hide = re.search(
        r"eaf-password-section'\)\.forEach\(r => \{\s*r\.style\.display = (\w+) \?", source
    )
    assert hide is not None, "could not find the password-visibility rule"
    assert hide.group(1) == "linked", (
        f"password visibility keys on {hide.group(1)!r}; it must key on whether the "
        f"account is linked, not on whether OAuth is merely offered"
    )


def test_an_unconfigured_deployment_disables_the_button_before_it_is_pressed():
    """Saving the account and *then* failing is what this replaces."""
    source = _oauth_decision_source()
    assert "btn.disabled = !provider.configured" in source


def test_the_connect_handler_refuses_rather_than_redirecting_into_a_400():
    """Belt and braces: disabled buttons can be re-enabled from a console."""
    text = SETTINGS_JS.read_text(encoding="utf-8")
    handler = text[text.index("eaf-oauth-btn').addEventListener"):]
    handler = handler[: handler.index("el('eaf-smtp-security').value = _smtpSecurity")]
    assert "!provider.configured" in handler
    assert "provider.authorize" in handler, "the redirect must use the served path"


def test_connect_and_save_agree_on_the_smtp_port_default():
    """They disagreed — 587 in one handler and 465 in the other, fifteen lines apart.

    An account created through Connect without a typed port got a different
    port from one created through Save, and nothing said so.
    """
    text = SETTINGS_JS.read_text(encoding="utf-8")
    defaults = re.findall(r"smtp_port: parseInt\(el\('eaf-smtp-port'\)\.value\) \|\| (\d+)", text)
    assert len(defaults) == 2, f"expected two smtp_port defaults, found {len(defaults)}"
    assert defaults[0] == defaults[1], f"Connect and Save disagree: {defaults}"


# --------------------------------------------------------------------------
# The two presets that were the visible symptom
# --------------------------------------------------------------------------


def test_gmail_and_workspace_share_a_host_which_is_why_the_split_was_wrong():
    """The whole defect in one assertion.

    Two dropdown entries, one mail host, and a rule that keyed on the entry.
    Whatever else changes, if these two ever stop sharing a host the argument
    for a host-based rule needs revisiting — so the test states the premise
    rather than assuming it.
    """
    text = SETTINGS_JS.read_text(encoding="utf-8")
    block = text[text.index("const PROVIDERS = {"):]
    block = block[: block.index("\n    };")]
    hosts = {}
    for key in ("gmail", "google_workspace"):
        line = next(l for l in block.splitlines() if l.strip().startswith(key + ":"))
        hosts[key] = re.search(r"imap: \{ host: '([^']*)'", line).group(1)
    assert hosts["gmail"] == hosts["google_workspace"] == "imap.gmail.com"


def test_the_authorize_route_refuses_a_half_configured_deployment(monkeypatch):
    """The sharp end: refusing here is refusing before the consent is spent."""
    import asyncio

    import routes.email_routes as er
    from fastapi import HTTPException

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    source = Path(er.__file__).read_text(encoding="utf-8")
    guard = source[source.index("async def google_oauth_authorize"):]
    guard = guard[: guard.index("redirect_uri = (")]
    assert "_google_oauth_configured()" in guard, (
        "authorize must use the two-part rule; checking the id alone lets the "
        "flow fail after the mailbox consent has been granted"
    )
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in guard
