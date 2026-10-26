# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B684` — the auth audit log has a reader, and the metrics endpoint counts it.

`P11-08` writes `kind="auth"` rows and nothing read them: usage, receipts and
the metrics export filter other kinds. The row's `Verify:` — *an admin can see
the last N auth events, filtered by outcome and by either party, without opening
a database, and a failed-login counter appears on the metrics endpoint when one
is enabled* — is driven against the real app with two accounts
(`tests/helpers/gated_app.py`): real failed sign-ins through `POST
/api/auth/login`, a real admin action naming the member, then the reader.

The panel (`static/js/authAudit.js`) is driven under node against the route's
own answer shape: failures first, both parties shown, an account name drawn as
text.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parent.parent

_PROBE = r'''
admin, member, stranger = client(ADMIN), client(MEMBER), client(None)
# Two refused sign-ins for the member, one for nobody, then the member signs in.
for who in (MEMBER, MEMBER, "mallory"):
    r = client(None).post("/api/auth/login", json={"username": who, "password": "wrong"})
    assert r.status_code in (401, 403), r.text
ok = client(None).post("/api/auth/login", json={"username": MEMBER, "password": %(password)r})
assert ok.status_code == 200, ok.text
# An admin action that names the member as its subject.
r = admin.put(f"/api/auth/users/{MEMBER}/admin", json={"is_admin": False})
RESULT["admin_action"] = r.status_code

def get(c, **q):
    r = c.get("/api/diagnostics/auth-events", params=q)
    return r.status_code, (r.json() if r.status_code == 200 else None)

RESULT["member"] = get(member)[0]
RESULT["stranger"] = get(stranger)[0]
RESULT["all"] = get(admin)[1]
RESULT["failures"] = get(admin, outcome="failures")[1]
RESULT["ok"] = get(admin, outcome="ok")[1]
RESULT["party"] = get(admin, party=MEMBER.upper())[1]
RESULT["limit"] = get(admin, limit=2)[1]

RESULT["metrics_off"] = admin.get("/metrics").status_code
from src.settings import load_settings, save_settings
s = load_settings(); s["metrics_enabled"] = True; save_settings(s)
m = admin.get("/metrics")
RESULT["metrics"] = [m.status_code, m.text]
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    from tests.helpers.signed_in import PASSWORD
    return gated_app_probe(tmp_path_factory.mktemp("b684"), _PROBE % {"password": PASSWORD})


def test_the_premise_holds(probe):
    assert probe["premise"]["auth_enabled"] and not probe["premise"]["member_is_admin"]


def test_only_an_admin_reads_it(probe):
    assert probe["member"] == 403
    assert probe["stranger"] == 401


def test_failures_come_first_by_default(probe):
    events = probe["all"]["events"]
    outcomes = [e["outcome"] for e in events]
    assert "error" in outcomes and "ok" in outcomes
    first_ok = outcomes.index("ok")
    assert all(o != "ok" for o in outcomes[:first_ok])
    assert all(o == "ok" for o in outcomes[first_ok:])


def test_filtered_by_outcome(probe):
    assert probe["failures"]["events"] and all(e["outcome"] != "ok" for e in probe["failures"]["events"])
    assert probe["ok"]["events"] and all(e["outcome"] == "ok" for e in probe["ok"]["events"])
    refused_logins = [e for e in probe["failures"]["events"] if e["action"] == "login"]
    assert len(refused_logins) >= 3


def test_filtered_by_either_party(probe):
    """The member acted (their sign-ins, `owner`) and was acted on (the
    admin's change, `detail.subject`); both come back for one name, matched
    without regard to case."""
    from tests.helpers.signed_in import ADMIN, MEMBER
    events = probe["party"]["events"]
    assert events
    assert all(MEMBER in (e["actor"], e["subject"]) for e in events)
    assert any(e["actor"] == MEMBER for e in events)
    by_admin = [e for e in events if e["actor"] == ADMIN and e["subject"] == MEMBER]
    assert by_admin, events
    assert not any(e["actor"] == "mallory" for e in events)


def test_the_last_n(probe):
    assert len(probe["limit"]["events"]) == 2 and probe["limit"]["limit"] == 2


def test_no_credential_reaches_the_reader(probe):
    from tests.helpers.signed_in import PASSWORD
    assert PASSWORD not in json.dumps(probe["all"])
    assert "wrong" not in json.dumps(probe["all"])


def test_a_failed_login_counter_appears_when_metrics_are_enabled(probe):
    assert probe["metrics_off"] == 404
    status, text = probe["metrics"]
    assert status == 200
    assert "# TYPE pantheon_auth_events_1h gauge" in text
    line = next(l for l in text.splitlines()
                if l.startswith("pantheon_auth_events_1h{") and 'action="login"' in l
                and 'outcome="error"' in l)
    assert float(line.rsplit(" ", 1)[1]) >= 3


# ── the panel ───────────────────────────────────────────────────────────────

def _drive_panel(tmp_path, answer, then=""):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    from test_tool_effect_surfaces_js import _DOM

    (tmp_path / "dom.js").write_text(_DOM)
    shutil.copy(ROOT / "static" / "js" / "authAudit.js", tmp_path / "authAudit.js")
    case = """
import { installDom } from './dom.js';
const document = installDom();
const asked = [];
globalThis.fetch = async (url) => { asked.push(url); return { ok: true, status: 200, json: async () => (%(answer)s) }; };
const mk = (tag, id) => { const n = document.body.appendChild(document.createElement(tag)); n.setAttribute('id', id); return n; };
const outcome = mk('select', 'auth-audit-outcome'); outcome.value = 'all';
const party = mk('input', 'auth-audit-party');
const limit = mk('select', 'auth-audit-limit'); limit.value = '100';
const body = mk('div', 'auth-audit-body');
const panel = await import('./authAudit.js');
%(then)s
await panel.load();
const rows = body.querySelectorAll('tr').map((tr) => tr.querySelectorAll('td').map((td) => td.textContent)).filter((r) => r.length);
console.log(JSON.stringify({ asked, rows, html: body._html || '', head: (body.querySelectorAll('p')[0] || {}).textContent }));
""" % {"answer": json.dumps(answer), "then": then}
    (tmp_path / "case.mjs").write_text(case)
    out = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_panel_draws_both_parties_and_marks_the_failures(tmp_path):
    hostile = '<img src=x onerror="alert(1)">'
    answer = {"events": [
        {"ts": "2026-10-26T20:00:00", "action": "login", "actor": hostile, "subject": "",
         "outcome": "error", "detail": {"reason": "bad_password"}},
        {"ts": "2026-10-26T19:00:00", "action": "role_change", "actor": "ada", "subject": "bob",
         "outcome": "ok", "detail": {"role": "viewer"}}], "error": None}
    out = _drive_panel(tmp_path, answer, then="party.value = 'bob';")
    assert out["asked"] == ["/api/diagnostics/auth-events?outcome=all&limit=100&party=bob"]
    assert out["rows"][0][1:5] == ["login", hostile, "", "refused / failed"]
    assert out["rows"][1][1:5] == ["role_change", "ada", "bob", "ok"]
    assert out["head"] == "2 events · 1 refused or failed"
    assert "<img" not in out["html"]
