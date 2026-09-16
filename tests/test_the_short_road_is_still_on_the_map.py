# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-09` — a comment that named the defect, and the next line that caused it.

The owner, on the enrollment work: *"I mean these are all intended to be self
hosted within their own systems/network etc.. so is it **really** necessary?"*

Checking that produced a live defect, and the way it hid is the part worth
keeping. `P18-07` wrote this:

    // The password fields stay while OAuth is merely *offered*. Hiding them
    // the moment Gmail qualified would delete the app-password path from the
    // mailboxes most likely to use it (`Law 1`). They go once it is linked.
    formEl.querySelectorAll('.uf-password-section').forEach(r => {
      r.style.display = linked ? 'none' : '';
    });
    const manual = el('uf-manual');
    if (manual) manual.style.display = (provider && !linked) ? 'none' : '';

**`.uf-password-section` is inside `#uf-manual`.** So the first statement sets a
child visible and the second sets its parent to `none`, and the child is hidden
anyway. The comment names the exact outcome it is protecting against, three
lines above the statement that produces it — which is why nobody caught it: the
file *says* the path is protected, and reading is how this repo checks browser
behaviour.

**What it cost is the owner's whole point.** Choosing Gmail deleted the
thirty-second road — paste an app password — and left one option: register an
application with Google Cloud Console. For a self-hosted install on its own
network that is ceremony the situation does not need, and `P18-08` had just
made it four numbered steps, which is a better wrong answer, not a right one.

**The fix is a choice, not a default.** OAuth stays the headline because it is
better when it applies; the alternative is one line and one button beneath it,
offered **only where a password can actually work** — Google issues app
passwords, Microsoft has disabled basic authentication in every Exchange Online
tenant, and offering the choice there would be offering a bricked-up door. That
is a fact about a provider, so it lives on the record.
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

HARNESS = ROOT / "tests" / "harness" / "render_oauth_alternative.js"
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"


def render(provider, linked=False, revealed=False):
    proc = subprocess.run(
        ["node", str(HARNESS), json.dumps(provider),
         "linked" if linked else "-", "revealed" if revealed else "-"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    out["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out["html"])).strip()
    return out


GOOGLE = {"id": "google", "label": "Google", "password_auth": True,
          "app_password_url": "https://myaccount.google.com/apppasswords"}
MICROSOFT = {"id": "microsoft", "label": "Microsoft", "password_auth": False,
             "app_password_url": ""}


# --------------------------------------------------------------------------
# The defect itself, asserted structurally
# --------------------------------------------------------------------------


def test_the_password_fields_are_inside_the_block_that_gets_hidden():
    """The containment is the whole bug, so it is pinned rather than assumed.

    If somebody later moves `.uf-password-section` out of `#uf-manual`, the
    sticky reveal below stops being necessary — and this test failing is how
    they find out, instead of leaving two mechanisms for one job.
    """
    source = SETTINGS_JS.read_text(encoding="utf-8")
    start = source.index('<div id="uf-manual">')
    depth, end = 0, None
    for m in re.finditer(r"<div\b|</div>", source[start:start + 40000]):
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                end = m.end()
                break
        else:
            depth += 1
    assert end, "could not find the end of #uf-manual"
    block = source[start:start + end]
    assert "uf-password-section" in block
    assert "uf-imap-pass" in block and "uf-smtp-pass" in block


def test_hiding_the_manual_block_now_consults_the_reveal():
    """The statement that caused it, with the term that fixes it.

    Read rather than run because it is one expression in a function that needs
    the whole form to exist; the behaviour it guards is covered below.
    """
    source = SETTINGS_JS.read_text(encoding="utf-8")
    line = next(l for l in source.splitlines()
                if "manual.style.display" in l or "_manualRevealed) ? 'none'" in l)
    assert "_manualRevealed" in line, (
        "the manual block is hidden without asking whether the person chose it"
    )


# --------------------------------------------------------------------------
# The way back, and who is offered it
# --------------------------------------------------------------------------


def test_a_provider_that_takes_a_password_offers_the_short_road():
    out = render(GOOGLE)
    assert out["display"] == ""
    assert "app password" in out["text"].lower()
    assert "myaccount.google.com/apppasswords" in out["html"], (
        "the person is told a password is possible and not where to get one"
    )
    assert "uf-oauth-alt-btn" in out["html"]


def test_the_offer_says_it_needs_nothing_set_up_first():
    """That is the entire reason somebody self-hosting would take it."""
    out = render(GOOGLE)
    assert "nothing on this install has to be set up first" in out["text"]


def test_a_provider_where_a_password_cannot_work_is_not_offered_one():
    """Microsoft disabled basic auth in every tenant, and nobody can re-enable
    it. A button here would be a door that is bricked up."""
    out = render(MICROSOFT)
    assert out["display"] == "none"
    assert out["html"] == ""


def test_an_already_linked_account_is_not_offered_a_downgrade():
    assert render(GOOGLE, linked=True)["display"] == "none"


def test_no_provider_means_no_offer():
    assert render(None)["display"] == "none"


def test_the_offer_withdraws_once_it_has_been_taken():
    """`_syncOauthUI` re-runs on every keystroke in the host field. An offer
    that stayed up after the fields appeared would be a button that does
    nothing, next to the thing it already did."""
    assert render(GOOGLE, revealed=True)["display"] == "none"


# --------------------------------------------------------------------------
# The fact lives on the record
# --------------------------------------------------------------------------


def test_whether_a_password_works_is_a_property_of_the_provider():
    from src import providers

    assert providers.get("google").password_auth is True
    assert providers.get("google").app_password_url
    assert providers.get("microsoft").password_auth is False
    assert providers.get("microsoft").app_password_url == ""


def test_the_default_is_that_a_password_works():
    """Most mail servers in the world take a password, and a self-hosted
    Dovecot needs none of this machinery at all."""
    from src import providers

    assert providers.Provider(id="x", label="X").password_auth is True


def test_the_panel_is_told_both_facts(monkeypatch):
    import routes.email_routes as er

    served = {p["id"]: p for p in er._oauth_providers()}
    assert served["google"]["password_auth"] is True
    assert served["google"]["app_password_url"].startswith("https://")
    assert served["microsoft"]["password_auth"] is False


def test_the_new_block_takes_the_app_password_url_from_the_record():
    """`Law 13`, same rule as the scopes and the variable names — narrowed, and
    the narrowing is declared rather than quietly applied.

    Written first as *this URL appears nowhere in `settings.js`*, which failed
    on `PROVIDER_NOTES.gmail.url` — a **pre-existing, preset-keyed** table that
    also covers iCloud and Yahoo, neither of which has a provider record to
    read from. So the two were not one rule spelled twice; they were two
    mechanisms that overlapped on exactly one entry. Widening this assertion to
    pass by ignoring that would have been the test bending to the code, so the
    overlap was filed as `B73` and this asserted what it could honestly assert:
    **the block added here reads the record.**

    It is not decoration either — the *Google Workspace* preset has no
    `PROVIDER_NOTES` entry at all, so for that mailbox this block is the only
    place a person is told where an app password comes from.

    **`B73` closed it, and the count moved 1 → 0.** The note table no longer
    carries Gmail's URL: `_presetAppPasswordUrl` resolves the preset's IMAP
    host through `_oauthFor` — the same host→record map the rest of the panel
    uses — so the record is the only spelling in the tree. The literals that
    remain in that table belong to presets with no record (`icloud`, `yahoo`)
    and to a link that is not an app-password link (`outlook`). The behaviour
    is `tests/test_one_answer_about_where_an_app_password_comes_from.py`;
    this stays as the ratchet.
    """
    js = SETTINGS_JS.read_text(encoding="utf-8")
    block = js[js.index("function _renderOauthAlternative"):]
    block = block[: block.index("function _syncOauthUI")]
    assert "provider.app_password_url" in block
    assert "myaccount.google.com" not in block
    # Zero copies in the browser: the record is the only place it is written.
    assert js.count("myaccount.google.com") == 0
