# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1461` — Settings → Reminders → *Send from* is kept, and used.

The 2026-10-25 settings audit: the picker posted `reminder_email_account_id`
from the day it was drawn, and `POST /api/auth/settings` stores only keys
`DEFAULT_SETTINGS` names — this was not one, so the choice was dropped with a
200 and every reminder went from the default account. The reader
(`routes/note/note_routes.py`) was right all along; it never got a value.
"""

from __future__ import annotations

from pathlib import Path

import src.settings as S
from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, app, as_user, auth, datadir)

ROOT = Path(__file__).resolve().parent.parent


def test_the_key_is_a_setting():
    assert S.DEFAULT_SETTINGS.get("reminder_email_account_id") == ""


def test_saving_the_picker_keeps_the_choice(app):
    client = as_user(app, ADMIN)
    r = client.post("/api/auth/settings", json={"reminder_email_account_id": "acct-2"})
    assert r.status_code == 200, r.text
    assert S.load_settings().get("reminder_email_account_id") == "acct-2"
    # "the default account" is an empty choice, and that is kept too
    r = client.post("/api/auth/settings", json={"reminder_email_account_id": ""})
    assert r.status_code == 200, r.text
    assert S.load_settings().get("reminder_email_account_id") == ""


def test_the_reader_and_the_test_send_use_it():
    routes = (ROOT / "routes" / "note" / "note_routes.py").read_text(encoding="utf-8")
    ui = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert 'settings.get("reminder_email_account_id")' in routes
    assert '_override["reminder_email_account_id"]' in routes, "a test send uses the account on screen"
    assert "email_account_id: el('set-reminder-email-account')" in ui
    assert "reminder_email_account_id: emailAcctSel.value || null" not in ui, \
        "an empty choice is sent as '', the setting's own empty value"
