# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B73` — one mechanism tells a person where an app password comes from.

Two did. `PROVIDER_NOTES` in `settings.js` is **preset**-keyed (`gmail`,
`icloud`, `yahoo`, `outlook`) and carries a title, a body, a link and a copy
button. `_renderOauthAlternative` reads the **provider record** (`google`,
`microsoft`) and its `app_password_url`. They overlapped on exactly one entry —
Gmail — and on that entry both were on screen at the same time, a few pixels
apart, each printing the same URL, spelled once in `src/providers.py` and again
as a literal in the browser.

**The record is the real one.** It is server-side, single-sourced, already on
the wire (`routes/email_routes.py:235`), and it is the only mechanism that
covers `google_workspace`, which has no `PROVIDER_NOTES` entry at all. A URL in
the browser is the same rule in a second language — the argument `P18-08`
already used when it took the environment-variable names out of the `outlook`
note body.

**The note does not go away**, because deleting it deletes the answer for
iCloud and Yahoo, which have no record and are not going to get one (`Law 1`).
What went away is its copy of the URL: `_presetAppPasswordUrl` resolves the
preset's IMAP host through `_oauthFor`, the host→record map the rest of the
panel already uses, so nothing new had to be listed to join them (`Law 14`).
And `_renderOauthAlternative` stops printing a URL the note above it is already
showing, so the person reads it once.

Driven under node against the real `PROVIDERS`, the real `PROVIDER_NOTES`, the
real `_oauthFor` and the real renderers (`Law 20`). The provider payload the
harnesses are fed is the one the backend actually serves, taken from
`routes/email_routes._oauth_providers()` rather than hand-written.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

H_NOTE = ROOT / "tests" / "harness" / "provider_note_app_password.js"
H_ALT = ROOT / "tests" / "harness" / "render_oauth_alternative.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _served():
    """The provider records as `/api/email/oauth/providers` serves them."""
    import routes.email_routes as er

    return er._oauth_providers()


def _record(provider_id):
    for row in _served():
        if row["id"] == provider_id:
            return row
    raise AssertionError(f"{provider_id} is not served")


def _note(key, providers=None, then=None):
    """Render one preset's note, or a sequence of them when `then` is given —
    the second render runs against whatever state the first left behind."""
    payload = json.dumps(providers if providers is not None else _served())
    keys = key if then is None else f"{key},{then}"
    proc = subprocess.run(["node", str(H_NOTE), keys, payload],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    out["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out["html"])).strip()
    return out


def _alt(provider, *, preset=None, linked=False, revealed=False):
    argv = [str(H_ALT), json.dumps(provider),
            "linked" if linked else "-", "revealed" if revealed else "-"]
    if preset:
        argv.append(preset)
    proc = subprocess.run(["node", *argv], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    out["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out["html"])).strip()
    return out


# ── The URL has one source ──────────────────────────────────────────────────

def test_the_gmail_note_takes_its_url_from_the_provider_record():
    """The defect, from the note's side: this URL used to be a literal in
    `PROVIDER_NOTES.gmail`. It is the record's value now, and the note is
    still a complete answer."""
    out = _note("gmail")
    assert out["presetUrl"] == _record("google")["app_password_url"]
    assert out["noteUrl"] == _record("google")["app_password_url"]
    assert out["hasLinkRow"] is True
    assert "Gmail needs an App Password" in out["text"]


def test_the_url_is_reached_through_the_host_the_preset_already_carries():
    """No preset→provider map was added. The join is the IMAP host, which the
    preset already holds and `_oauthFor` already resolves."""
    out = _note("gmail")
    assert out["presetHost"] == "imap.gmail.com"
    assert out["presetHost"] in _record("google")["imap_hosts"]


def test_changing_the_record_changes_what_the_note_shows():
    """`Law 13` proved by moving the one source and watching the note move.
    A re-inlined literal in `PROVIDER_NOTES` passes every other test here."""
    moved = [dict(row) for row in _served()]
    for row in moved:
        if row["id"] == "google":
            row["app_password_url"] = "https://example.invalid/moved"
    out = _note("gmail", providers=moved)
    assert out["noteUrl"] == "https://example.invalid/moved"
    assert "myaccount.google.com" not in out["html"]


# ── And it is said once ─────────────────────────────────────────────────────

def test_the_note_prints_one_distinct_url():
    """The anchor and the copy button are two elements pointing at one place,
    which is one answer. Two *different* URLs in one panel would not be."""
    out = _note("gmail")
    assert len(out["distinctUrls"]) == 1


def test_the_alternative_does_not_repeat_a_url_the_note_is_showing():
    """The `Law 15` half: on a Gmail preset both blocks render. The offer
    still reads as an offer; the URL is printed by the note and not again
    here."""
    google = _record("google")
    out = _alt(google, preset="gmail")
    assert out["display"] != "none"
    assert "Use an app password instead" in out["text"]
    assert google["app_password_url"] not in out["html"]
    assert google["app_password_url"] in out["noteHtml"]


def test_the_alternative_still_says_where_when_no_note_is_showing():
    """A host typed by hand, or a preset with no note — `google_workspace` is
    the live case — leaves this block as the only place the person is told,
    and it still tells them (`Law 1`)."""
    google = _record("google")
    out = _alt(google)
    assert google["app_password_url"] in out["html"]
    assert out["noteHtml"] == ""


def test_google_workspace_has_no_note_and_is_answered_by_the_record():
    """The row's second Verify clause runs both ways. This preset has no
    `PROVIDER_NOTES` entry, so the note renders nothing and the alternative
    block is the answer."""
    out = _note("google_workspace")
    assert out["hasNoteEntry"] is False
    assert out["display"] == "none"
    assert out["html"] == ""
    out_alt = _alt(_record("google"), preset="google_workspace")
    assert _record("google")["app_password_url"] in out_alt["html"]


# ── A preset with no record still gets an answer ────────────────────────────

@pytest.mark.parametrize("key,needle", [
    ("icloud", "App-Specific Password"),
    ("yahoo", "App Password"),
])
def test_a_preset_with_no_record_keeps_its_own_answer(key, needle):
    """`Verify:` *a preset with no OAuth record still gets an answer.* iCloud
    and Yahoo have no provider record to read, so their literal stays — and it
    has to, or this change would have deleted their answer."""
    out = _note(key)
    assert out["presetUrl"] == "", "these presets resolve to no record"
    assert out["hasLinkRow"] is True
    assert needle in out["text"]
    assert len(out["distinctUrls"]) == 1


def test_the_outlook_link_is_not_an_app_password_link_and_survives():
    """Microsoft's record carries an EMPTY `app_password_url` on purpose —
    basic auth is bricked up in Exchange Online. So the empty string is an
    answer, and the `outlook` note's own link, which points at app
    registration rather than at app passwords, must not be replaced by it."""
    assert _record("microsoft")["app_password_url"] == ""
    out = _note("outlook")
    assert out["presetUrl"] == ""
    assert "How to register the app" in out["text"]
    assert "learn.microsoft.com" in out["html"]


def test_microsoft_is_still_offered_no_app_password_alternative():
    """Unchanged by this row and asserted here so it stays that way: a
    provider that cannot take a password is not offered the choice."""
    out = _alt(_record("microsoft"), preset="outlook")
    assert out["display"] == "none"


# ── The failure mode the derivation introduces ──────────────────────────────

def test_a_note_rendered_before_the_records_arrive_shows_no_dead_link():
    """`/api/email/oauth/providers` is fetched async and the panel is usable
    before it resolves. With no record there is no URL, and the note renders
    its title and body without a link row rather than a button that goes
    nowhere."""
    out = _note("gmail", providers=[])
    assert out["display"] == ""
    assert "Gmail needs an App Password" in out["text"]
    assert out["hasLinkRow"] is False
    assert out["urls"] == []


def test_the_panel_re_renders_the_note_when_the_records_land():
    """Which is why the fetch callback re-renders it. Read off the source
    because it is a wiring statement rather than a rendered value — the
    behaviour it guarantees is the test above, in the other direction."""
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    then = js[js.index("fetch('/api/email/oauth/providers'"):]
    then = then[: then.index(".catch(")]
    assert "_renderProviderNote(_noteKey)" in then


def test_no_preset_selected_renders_nothing():
    out = _note("")
    assert out["display"] == "none"
    assert out["html"] == ""


def test_hiding_the_note_empties_it():
    """The invariant `_noteAppPasswordUrl` relies on. It asks one question —
    *is a copy button rendered* — and that is only equivalent to *is the note
    visible* because hiding the note clears its markup. Switching from Gmail
    to Custom must therefore leave nothing behind for the block below to read,
    or the offer would stay silent on a panel showing no URL at all."""
    out = _note("gmail", then="")
    assert out["display"] == "none"
    assert out["html"] == ""
    assert out["noteUrl"] == ""
    assert out["urls"] == []
