# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-08` — the operator's half of enrollment, in the panel rather than a doc.

The owner: *"Ensure the enrollment of these systems is straight forward and not
confusing as fuck to any end user."*

**THE END USER'S HALF WAS ALREADY ONE BUTTON.** `P18-01` made it appear,
`P18-07` made it the whole interaction, `P18-05` made a second provider data.
What stayed hard is the step before any of that: somebody has to register an
application, and the only instructions lived in `.env.example` and a docs file —
neither of which is open when the button is greyed out and the panel says only
*set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET*. That sentence names
the destination and none of the journey, which is `Law 15` stated as a defect.

**EVERY VALUE IN THE WALKTHROUGH IS SERVED, NOT WRITTEN INTO THE BROWSER.** A
scope list or a variable name spelled twice is a rule in two languages, and
`B65` is this fork's standing proof of what that costs. It also means a provider
added later gets a correct walkthrough without anybody writing one — which is
the test at the bottom of this file, with a provider that does not exist.

**AND THE RENDERER IS RUN, NOT READ.** The rest of this repo checks browser
behaviour with a substring search, and for this it would not do: what is being
claimed is *an operator can follow this*, and every property worth asserting —
a step skipped when its value is absent, the box hidden once configured, the
half-done case named — is a property of the output. `tests/harness/` evaluates
the real function against a stub DOM.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HARNESS = ROOT / "tests" / "harness" / "render_oauth_setup.js"
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"


def render(provider, linked=False):
    """Run the real renderer. A missing anchor exits 2 and fails loudly."""
    proc = subprocess.run(
        ["node", str(HARNESS), json.dumps(provider), "linked" if linked else "-"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    out["text"] = re.sub(r"<[^>]+>", " ", out["html"])
    out["text"] = re.sub(r"\s+", " ", out["text"]).strip()
    return out


GOOGLE = {
    "id": "google", "label": "Google", "configured": False,
    "setup_url": "https://console.cloud.google.com/apis/credentials",
    "redirect_uri": "http://localhost:7000/api/email/oauth/google/callback",
    "scopes": ["https://mail.google.com/", "email"],
    "env_vars": ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"],
    "missing_env": ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"],
}


def _copy_values(html):
    return re.findall(r'data-url="([^"]*)"', html)


# --------------------------------------------------------------------------
# The walkthrough exists, and it is followable
# --------------------------------------------------------------------------


def test_an_unconfigured_provider_gets_every_step():
    out = render(GOOGLE)
    assert out["display"] == ""
    assert out["html"].count("<li>") == 4, "a step went missing"
    assert "console.cloud.google.com" in out["html"]
    assert "redirect_uri_mismatch" in out["text"], (
        "the step does not say what happens if the URI is off by a character"
    )
    assert ".env" in out["text"]
    assert "restart" in out["text"].lower()


def test_every_value_an_operator_must_paste_has_a_copy_button():
    """Three strings have to cross into another window exactly."""
    out = render(GOOGLE)
    copied = _copy_values(out["html"])
    assert GOOGLE["redirect_uri"] in copied
    assert "https://mail.google.com/ email" in copied
    assert "GOOGLE_OAUTH_CLIENT_ID=\nGOOGLE_OAUTH_CLIENT_SECRET=" in copied
    assert len(copied) == 3


def test_the_env_block_is_copied_with_real_newlines_and_shown_with_them():
    """A `\\n` inside `<code>` renders as a space unless told otherwise.

    The copy value was right and the displayed value was one run-on line —
    exactly the kind of thing this row exists to stop. Found by running the
    renderer rather than reading it.
    """
    out = render(GOOGLE)
    block = next(v for v in _copy_values(out["html"]) if "CLIENT_ID" in v)
    assert "\n" in block
    assert "white-space:pre-wrap" in out["html"]


def test_the_scopes_are_space_separated_and_say_so():
    out = render(GOOGLE)
    assert "https://mail.google.com/ email" in _copy_values(out["html"])
    assert "space-separated" in out["text"].lower()


# --------------------------------------------------------------------------
# Knowing when to shut up
# --------------------------------------------------------------------------


def test_a_configured_provider_gets_no_walkthrough():
    """Finished work shown again is the panel talking over itself."""
    out = render({**GOOGLE, "configured": True, "missing_env": []})
    assert out["display"] == "none"
    assert out["html"] == ""


def test_a_linked_account_gets_no_walkthrough():
    out = render(GOOGLE, linked=True)
    assert out["display"] == "none"


def test_no_provider_selected_gets_no_walkthrough():
    out = render(None)
    assert out["display"] == "none"


def test_a_half_configured_deployment_is_told_which_half():
    """Repeating the whole setup at somebody who has done most of it is how a
    person concludes they did it wrong and starts over."""
    out = render({**GOOGLE, "missing_env": ["GOOGLE_OAUTH_CLIENT_SECRET"]})
    assert "Almost there" in out["text"]
    assert "GOOGLE_OAUTH_CLIENT_SECRET is still missing" in out["text"]
    assert "GOOGLE_OAUTH_CLIENT_ID" not in _copy_values(out["html"])[-1], (
        "the variable they already set is still being asked for"
    )


# --------------------------------------------------------------------------
# Nothing about a provider is written into the browser
# --------------------------------------------------------------------------


def test_no_scope_string_is_hard_coded_in_the_panel():
    """`Law 13`, and the property rather than the spelling.

    A scope list in two places is one that can disagree, and the disagreement
    surfaces as a consent screen missing a permission — days later, as a send
    that fails with a permission error naming nothing.
    """
    js = SETTINGS_JS.read_text(encoding="utf-8")
    for scope in ("mail.google.com", "IMAP.AccessAsUser.All", "SMTP.Send",
                  "offline_access"):
        assert scope not in js, f"{scope} is spelled in the browser as well"


def test_no_oauth_variable_name_is_hard_coded_in_the_panel():
    js = SETTINGS_JS.read_text(encoding="utf-8")
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "MICROSOFT_OAUTH_CLIENT_SECRET",
                 "MICROSOFT_OAUTH_TENANT"):
        assert name not in js, f"{name} is spelled in the browser as well"


def test_a_provider_nobody_wrote_a_walkthrough_for_gets_one():
    """The claim, tested with a provider that does not exist.

    If any step were per-provider knowledge in JavaScript, `acme` would render
    a walkthrough with a hole in it.
    """
    out = render({
        "id": "acme", "label": "Acme Mail", "configured": False,
        "setup_url": "https://acme.test/console",
        "redirect_uri": "https://pantheon.test/api/email/oauth/acme/callback",
        "scopes": ["mail.read", "mail.send"],
        "env_vars": ["ACME_OAUTH_CLIENT_ID", "ACME_OAUTH_CLIENT_SECRET"],
        "missing_env": ["ACME_OAUTH_CLIENT_ID", "ACME_OAUTH_CLIENT_SECRET"],
    })
    assert out["html"].count("<li>") == 4
    copied = _copy_values(out["html"])
    assert "https://pantheon.test/api/email/oauth/acme/callback" in copied
    assert "mail.read mail.send" in copied
    assert "ACME_OAUTH_CLIENT_ID=\nACME_OAUTH_CLIENT_SECRET=" in copied
    assert "acme.test/console" in out["html"]


def test_a_provider_with_no_console_url_skips_that_step_rather_than_linking_nowhere():
    out = render({**GOOGLE, "setup_url": ""})
    assert out["html"].count("<li>") == 3
    assert "<a href=\"\"" not in out["html"]


def test_a_provider_with_no_scopes_skips_that_step():
    out = render({**GOOGLE, "scopes": []})
    assert out["html"].count("<li>") == 3
    assert "Scopes" not in out["text"]


# --------------------------------------------------------------------------
# What the server has to serve for any of that to work
# --------------------------------------------------------------------------


@pytest.fixture()
def clean_env(monkeypatch):
    for prefix in ("GOOGLE", "MICROSOFT"):
        monkeypatch.delenv(f"{prefix}_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv(f"{prefix}_OAUTH_CLIENT_SECRET", raising=False)
    return monkeypatch


def test_the_payload_carries_what_the_walkthrough_needs(clean_env):
    import routes.email_routes as er

    for entry in er._oauth_providers():
        assert entry["scopes"], entry["id"]
        assert entry["env_vars"], entry["id"]
        assert entry["setup_url"], entry["id"]
        assert entry["redirect_uri"], entry["id"]


def test_missing_env_names_only_what_is_actually_missing(clean_env):
    import routes.email_routes as er

    google = next(p for p in er._oauth_providers() if p["id"] == "google")
    assert google["missing_env"] == ["GOOGLE_OAUTH_CLIENT_ID",
                                     "GOOGLE_OAUTH_CLIENT_SECRET"]

    clean_env.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    google = next(p for p in er._oauth_providers() if p["id"] == "google")
    assert google["missing_env"] == ["GOOGLE_OAUTH_CLIENT_SECRET"]

    clean_env.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "shh")
    google = next(p for p in er._oauth_providers() if p["id"] == "google")
    assert google["missing_env"] == []
    assert google["configured"] is True


def test_the_scopes_served_are_the_scopes_requested(clean_env):
    """The authorize request and the walkthrough must not be able to differ.

    An operator granting a permission set that does not match what the flow
    asks for gets consent, then a send that fails on a missing scope — with an
    error that names the scope and not the step that omitted it.
    """
    import urllib.parse

    import routes.email_routes as er
    from src import providers

    for entry in er._oauth_providers():
        record = providers.get(entry["id"])
        assert entry["scopes"] == list(record.scopes)
        assert " ".join(entry["scopes"]) == providers.scope_string(record)
