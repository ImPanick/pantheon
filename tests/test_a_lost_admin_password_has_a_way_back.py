# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1272`, `D-2026-10-26-01` §3 — a lost admin password is recovered by a
script run where the data lives, which rewrites one account's hash and signs
it out everywhere — never an environment variable applied on every boot.

**Measured before this file:** there was no reset; the 0.2.0 notes' way back
was to move `auth.json` aside and set `PANTHEON_ADMIN_PASSWORD`, which works
only while `admin` is the only account.

Driven: the real `AuthManager` on a real `auth.json`, and the script's own
`main`.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.auth import AuthManager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reset_password as R  # noqa: E402


@pytest.fixture()
def accounts(tmp_path):
    path = tmp_path / "auth.json"
    mgr = AuthManager(str(path))
    assert mgr.setup("ada", "old-password-1")
    assert mgr.create_user("bob", "bobs-password-1")
    ada = [mgr.create_session("ada", "old-password-1") for _ in range(2)]
    bob = mgr.create_session("bob", "bobs-password-1")
    return path, ada, bob


def test_the_script_sets_the_password_and_signs_that_person_out(accounts, capsys):
    path, ada_tokens, bob_token = accounts
    code = R.main(["ada", "--password-stdin"], stdin=io.StringIO("new-password-22\n"), auth_path=str(path))
    assert code == 0
    out = capsys.readouterr().out
    assert "2 session(s) were signed out" in out and "Start Pantheon again" in out
    fresh = AuthManager(str(path))
    assert fresh.verify_password("ada", "new-password-22") and not fresh.verify_password("ada", "old-password-1")
    assert not any(fresh.validate_token(t) for t in ada_tokens)
    assert fresh.validate_token(bob_token), "nobody else is signed out"
    assert fresh.is_admin("ada") and fresh.verify_password("bob", "bobs-password-1")


def test_it_asks_twice_and_changes_nothing_when_they_differ(accounts):
    path, _, _ = accounts
    answers = iter(["new-password-22", "new-password-23"])
    with pytest.raises(SystemExit) as e:
        R.main(["ada"], prompt=lambda _: next(answers), auth_path=str(path))
    assert "differ" in str(e.value)
    assert AuthManager(str(path)).verify_password("ada", "old-password-1")


def test_a_short_password_or_an_unknown_name_changes_nothing(accounts, capsys):
    path, _, _ = accounts
    assert R.main(["ada", "--password-stdin"], stdin=io.StringIO("short\n"), auth_path=str(path)) == 1
    assert "at least" in capsys.readouterr().err
    assert R.main(["cy", "--password-stdin"], stdin=io.StringIO("whatever-long\n"), auth_path=str(path)) == 1
    assert "The accounts are: ada, bob." in capsys.readouterr().err
    assert AuthManager(str(path)).verify_password("ada", "old-password-1")


def test_a_lost_authenticator_can_go_with_it(accounts):
    path, _, _ = accounts
    data = json.loads(path.read_text())
    data["users"]["ada"].update({"totp_enabled": True, "totp_secret": "JBSWY3DPEHPK3PXP"})
    path.write_text(json.dumps(data))
    R.main(["ada", "--password-stdin", "--disable-2fa"], stdin=io.StringIO("new-password-22\n"),
           auth_path=str(path))
    rec = json.loads(path.read_text())["users"]["ada"]
    assert rec["totp_enabled"] is False and "totp_secret" not in rec


def test_an_unreadable_account_file_is_left_alone(tmp_path, capsys):
    path = tmp_path / "auth.json"
    path.write_text("{ not json")
    assert R.main(["ada", "--password-stdin"], stdin=io.StringIO("new-password-22\n"), auth_path=str(path)) == 2
    assert path.read_text() == "{ not json"


def test_the_password_never_rides_on_the_command_line():
    """`ps` shows a process's arguments to everyone on the machine."""
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_password.py"), "--help"],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert done.returncode == 0
    assert "--password " not in done.stdout and "--password-stdin" in done.stdout


def test_no_route_resets_a_password_without_the_old_one():
    for path in (ROOT / "routes").rglob("*.py"):
        assert "reset_password(" not in path.read_text(encoding="utf-8"), path
