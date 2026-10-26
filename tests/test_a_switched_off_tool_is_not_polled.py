# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1542`: a tool switched off is not asked by the page's own background polls.

`emailInbox.js`'s `_refreshUnreadCount` asked `/api/email/unread-state` at load,
every 60 s and on the tab coming back, the library prewarm asked
`/api/email/accounts`, the held-mail panel `/api/email/pending`; `notes.js`
loaded `/api/notes` at load and every five minutes for the due badge; and
`assistant.js` asked `/api/assistant/settings` at load and on every chat
switch. With the person's switch (`B1191`) or everyone's (`B1488`) off, every
one of them was a 403. Each now asks `ui_visibility.toolPollMayAsk(key)` first.

Driven under node with fake timers: each module's own functions, cut out of its
file, run beside the real `static/js/ui_visibility.js`, whose state is set the
way `app.js` sets it; a `fetch` records every URL asked.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_a_hidden_tab_stops_polling import _PRELUDE, _cut
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
UI_VIS = (ROOT / "static" / "js" / "ui_visibility.js").as_uri()

# The table's state, as `app.js` hands it: the switches for everyone
# (`/api/auth/features`) and the person's column (`/api/auth/status`).
_STATES = {
    "on": "V.applyToolVisibility({ features: {} }, null); V.applyToolVisibility({ privileges: {}, isAdmin: false, auth: true }, null);",
    "person": "V.applyToolVisibility({ features: {} }, null); V.applyToolVisibility({ privileges: { can_use_email: false, can_use_notes: false, can_use_assistant: false }, isAdmin: false, auth: true }, null);",
    "everyone": "V.applyToolVisibility({ features: { email: false, notes: false, assistant: false } }, null); V.applyToolVisibility({ privileges: {}, isAdmin: true, auth: true }, null);",
    # Appearance hides the doors in this browser and refuses nothing.
    "browser": "V.applyToolVisibility({ features: {} }, null); V.applyToolVisibility({ privileges: {}, isAdmin: false, auth: true, ui: { 'email-section': false, 'tool-notes': false, 'tool-assistant': false } }, null);",
}

_MAIL = _cut("static/js/emailInbox.js", "export function init(", "function _bindEvents(",
             "async function _refreshUnreadCount(")
_DRAFTS = _cut("static/js/agentDrafts.js", "export async function refresh(", "export function start(")
_NOTES = _cut("static/js/notes.js", "async function _fetchNotes(", "export async function refreshDueBadge(",
              "async function _initReminders(")
_ASSISTANT = _cut("static/js/assistant.js", "async function _fetchJSON(", "async function _getSettings(",
                  "async function _ensureHeaderAffordances(")

_STUBS = r"""
let V = null, toolPollMayAsk = null;
globalThis.localStorage = { getItem: () => null, setItem() {} };
// emailInbox.js
let _unreadCheckedAt = 0, _docModule = null, _showEmailTags = true;
const API_BASE = '';
const emailApiUrl = (path) => path;
const noteMailboxSync = () => {}, paintUnreadDot = () => {}, prewarmUnreadEmails = async () => {};
const _maybeOpenFromHash = () => {}, openEmailLibrary = () => {}, markInboxAsSeen = () => {}, _composeNew = () => {};
const initEmailLibrary = () => {}, _watchDocOpenToReDockEmail = () => {};
// The prewarm's first ask (`emailLibrary._ensureEmailAccountsForPrewarm`).
const prewarmEmailLibrary = () => fetch('/api/email/accounts');
// agentDrafts.js
const POLL_MS = 60000;
let _timer = null, _refreshedAt = 0, _visibilityHooked = false, _lastCount = 0;
const _bind = () => true;
// notes.js
let _notes = [], _showingArchived = false, _loading = false;
// `B1228`: the list is read through `appConfig.getNotes`, shared at boot.
let _activeNotesRead = false;
const getNotes = ({ archived = false } = {}) =>
  fetch('/api/notes' + (archived ? '?archived=true' : '')).then((r) => r.json());
const markUnreached = (p) => p, quietIfUnreached = () => true;
const _updateRailBadge = () => {}, _startReminderLoop = () => {};
// assistant.js
const API = '/api/assistant';
let _cachedSettings = null;
"""


def _run(tmp_path: Path, state: str, *, before: str = "") -> dict:
    """`state` is applied after `before` has run — so a poll started before the
    switches arrived is measured on the switches it then meets."""
    body = (_STUBS + _MAIL + "\n" + _DRAFTS + "\n" + _NOTES + "\n" + _ASSISTANT + r"""
(async () => {
  V = await import(__UI_VIS__);
  toolPollMayAsk = V.toolPollMayAsk;
  __BEFORE__
  __STATE__
  init(null);
  start();
  _initReminders();
  refreshDueBadge();
  _ensureHeaderAffordances('s1');
  await advance(200000);
  setVisible(false); setVisible(true);
  _ensureHeaderAffordances('s2');
  await advance(1000); await flush();
  const out = { email: count('/api/email'), notes: count('/api/notes'),
                assistant: count('/api/assistant'), urls: [...new Set(asked)].sort() };
  // The switch is asked at each look: turned back on, the polls resume.
  V.applyToolVisibility({ features: {}, privileges: {} }, null);
  _notes = [];
  refreshDueBadge(); _ensureHeaderAffordances('s3');
  await advance(70000); await flush();
  out.resumed = { email: count('/api/email/unread-state') > 0, notes: count('/api/notes') > 0,
                  assistant: count('/api/assistant') > 0 };
  console.log(JSON.stringify(out));
})();
""").replace("__UI_VIS__", json.dumps(UI_VIS)).replace("__STATE__", _STATES[state]) \
        .replace("__BEFORE__", before)
    script = tmp_path / f"{state}.cjs"
    script.write_text(_PRELUDE + body, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_harness_sees_every_poll_with_the_tools_on(tmp_path):
    out = _run(tmp_path, "on")
    assert out["email"] >= 4, out["urls"]   # unread-state, accounts, pending, urgency
    assert "/api/email/unread-state" in "".join(out["urls"])
    assert "/api/email/pending" in out["urls"] and "/api/email/accounts" in out["urls"]
    assert out["notes"] >= 1 and out["assistant"] >= 1, out["urls"]


@pytest.mark.parametrize("state", ["person", "everyone"])
def test_with_the_tool_off_no_request_leaves_the_page(tmp_path, state):
    out = _run(tmp_path, state)
    assert out["email"] == 0, f"Email off ({state}) still asked: {out['urls']}"
    assert out["notes"] == 0, f"Notes off ({state}) still asked: {out['urls']}"
    assert out["assistant"] == 0, f"Assistant off ({state}) still asked: {out['urls']}"
    assert out["resumed"] == {"email": True, "notes": True, "assistant": True}


def test_a_poll_started_before_the_switches_arrive_waits_for_them(tmp_path):
    """The load path: `notes.js` starts its reminder load three seconds in and
    `app.js` may not have heard from `/api/auth/features` yet. The ask waits
    for the switches rather than going out on *unknown*."""
    out = _run(tmp_path, "everyone", before="_initReminders(); _ensureHeaderAffordances('s0');")
    assert out["notes"] == 0 and out["assistant"] == 0, out["urls"]


def test_appearance_hides_the_doors_and_the_polls_still_ask(tmp_path):
    """The browser's own switch refuses nothing on the server, so the mail and
    the reminders a person hid the doors of keep working."""
    out = _run(tmp_path, "browser")
    assert out["email"] >= 4 and out["notes"] >= 1 and out["assistant"] >= 1, out["urls"]
