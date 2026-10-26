# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1539`: Settings shows both retention windows, with their ranges.

`events_retention_days` (`P14-01`) and `auth_events_retention_days` (`B685`)
were settable only through `POST /api/auth/settings`, `manage_settings` or the
settings file, and neither had a range — a negative window was stored as typed
and read by the pruner as the default, so a page showing it would show a
number nothing used. Now both are in `int_setting_ranges` (from
`src.events.RETENTION_DAYS_RANGE`), `GET /api/auth/settings/ranges` hands the
bounds to the panel, and Settings › System has a field for each.

Driven: the real settings routes behind a real auth manager (the fixtures of
`test_the_workstation_is_admin_controlled.py`), the pruner's own readers, and
`settings.js`'s `initRetentionWindows` cut out and run under node against the
real `static/index.html` ids and a `fetch` that answers as the route does.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function
from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401 — fixtures
    ADMIN, PLAIN, app, as_user, auth, datadir, stored)

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
INDEX = ROOT / "static" / "index.html"
KEYS = ("events_retention_days", "auth_events_retention_days")


# ── the server ──────────────────────────────────────────────────────────────

def test_the_ranges_are_handed_to_an_admin_and_to_nobody_else(app):
    r = as_user(app, ADMIN).get("/api/auth/settings/ranges")
    assert r.status_code == 200, r.text
    body = r.json()
    from src.events import RETENTION_DAYS_RANGE
    for key in KEYS:
        assert body["ranges"][key] == list(RETENTION_DAYS_RANGE)
    assert body["unset_by_null"] == ["auth_events_retention_days"]
    assert as_user(app, PLAIN).get("/api/auth/settings/ranges").status_code == 403


@pytest.mark.parametrize("key,asked,kept", [
    ("events_retention_days", 30, 30),
    ("events_retention_days", 0, 0),
    ("events_retention_days", -5, 0),
    ("events_retention_days", 99999, 3650),
    ("auth_events_retention_days", 365, 365),
    ("auth_events_retention_days", 0, 0),
    ("auth_events_retention_days", None, None),
    ("auth_events_retention_days", "", None),
])
def test_a_save_is_held_to_the_range_and_a_blank_audit_window_is_unset(app, key, asked, kept):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={key: asked})
    assert r.status_code == 200, r.text
    assert stored(key) == kept


def test_the_usage_window_cannot_be_unset_and_the_pruner_reads_what_was_kept(app):
    r = as_user(app, ADMIN).post("/api/auth/settings", json={"events_retention_days": None})
    assert r.status_code == 400 and "must be an integer" in r.text
    from src.events import _auth_retention_days, _retention_days
    as_user(app, ADMIN).post("/api/auth/settings",
                             json={"events_retention_days": 45, "auth_events_retention_days": None})
    assert _retention_days() == 45
    assert _auth_retention_days(45) == 45, "unset follows the usage window"
    as_user(app, ADMIN).post("/api/auth/settings", json={"auth_events_retention_days": 400})
    assert _auth_retention_days(45) == 400


# ── the page ────────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HARNESS = r"""
const nodes = {};
for (const id of __IDS__) nodes[id] = { id, value: '', min: '', max: '', textContent: '', style: {},
  listeners: {}, addEventListener(t, fn) { this.listeners[t] = fn; } };
const el = (id) => nodes[id] || null;
const store = { events_retention_days: 90, auth_events_retention_days: null };
const RANGES = { ranges: { events_retention_days: [0, 3650], auth_events_retention_days: [0, 3650] },
                 unset_by_null: ['auth_events_retention_days'] };
const posted = [];
globalThis.fetch = async (url) => ({ ok: true, json: async () =>
  (url === '/api/auth/settings/ranges' ? RANGES : { ...store }) });
// The route's own rule for these two keys, as `int_setting_ranges` holds it.
async function _postSettings(body) {
  posted.push(body);
  for (const [k, v] of Object.entries(body)) {
    store[k] = v === null ? null : Math.max(0, Math.min(v, 3650));
  }
  return { ok: true };
}
const _notSaved = () => 'Not saved.';
__FN__
const look = () => Object.fromEntries(['set-eventsRetention', 'set-authEventsRetention'].map((id) =>
  [id, { value: nodes[id].value, min: nodes[id].min, max: nodes[id].max, msg: nodes[id + 'Msg'].textContent }]));
(async () => {
  await initRetentionWindows();
  const out = { first: look() };
  nodes['set-eventsRetention'].value = '5000';
  await nodes['set-eventsRetention'].listeners.change();
  nodes['set-authEventsRetention'].value = '365';
  await nodes['set-authEventsRetention'].listeners.change();
  out.saved = look();
  nodes['set-authEventsRetention'].value = '';
  await nodes['set-authEventsRetention'].listeners.change();
  nodes['set-eventsRetention'].value = '';
  await nodes['set-eventsRetention'].listeners.change();
  out.cleared = look();
  out.posted = posted;
  console.log(JSON.stringify(out));
})();
"""


def _ids():
    html = INDEX.read_text(encoding="utf-8")
    ids = ["set-eventsRetention", "set-eventsRetentionMsg",
           "set-authEventsRetention", "set-authEventsRetentionMsg"]
    for i in ids:
        assert re.search(rf'id="{i}"', html), f"static/index.html has no #{i}"
    return ids


@pytestmark_node
def test_settings_shows_both_windows_with_their_ranges_and_what_it_kept(tmp_path):
    src = SETTINGS_JS.read_text(encoding="utf-8")
    fn = "async function initRetentionWindows() " + js_function(src, "async function initRetentionWindows(")
    script = tmp_path / "case.mjs"
    script.write_text(_HARNESS.replace("__IDS__", json.dumps(_ids())).replace("__FN__", fn),
                      encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])

    first = out["first"]
    assert first["set-eventsRetention"]["value"] == "90"
    assert first["set-eventsRetention"]["msg"] == "Kept 90 days. Allowed: 0 to 3,650 days."
    assert first["set-authEventsRetention"]["value"] == ""
    assert first["set-authEventsRetention"]["msg"].startswith("Follows usage and activity.")
    for field in first.values():
        assert (field["min"], field["max"]) == ("0", "3650"), field

    saved = out["saved"]
    assert saved["set-eventsRetention"]["value"] == "3650"
    assert "5000 is outside the range, so it was kept at 3650" in saved["set-eventsRetention"]["msg"]
    assert saved["set-authEventsRetention"]["msg"].startswith("Kept 365 days.")

    cleared = out["cleared"]
    assert cleared["set-authEventsRetention"]["msg"].startswith("Follows usage and activity.")
    assert cleared["set-eventsRetention"]["value"] == "3650", "a blank usage window is not saved"
    assert "A whole number of days" in cleared["set-eventsRetention"]["msg"]
    assert out["posted"] == [{"events_retention_days": 5000}, {"auth_events_retention_days": 365},
                             {"auth_events_retention_days": None}]
