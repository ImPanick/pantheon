# SPDX-License-Identifier: AGPL-3.0-or-later
"""`can_reach_private_mail` opens the LAN, not the machine Pantheon runs on.

`B2102` let a mail account reach this machine, the private ranges and any port
only for a person holding `can_reach_private_mail`: every admin, and a member
an admin granted it to (Settings → Users). One grant opened both. An admin
granting it so a member's account can reach the house mail server on the LAN
also let that member aim the Test, or a saved account, at `127.0.0.1` and any
port, and at every address this host answers on: Pantheon's own database,
model servers, the Android worker. Measured on `dev@ad4aac6`: a granted
member's Test dialled `127.0.0.1:5432`.

This machine is the admin's, who already holds the shell (`src/mail_reach.py`,
*Who the adversary is*). The grant still opens the LAN, on any port.

No network: the stand-ins of `test_the_mail_test_is_not_a_port_scanner`.
"""
from __future__ import annotations

import pytest

from test_the_mail_test_is_not_a_port_scanner import (  # noqa: F401 — fixtures
    ADMIN, MEMBER, _both_halves, _refused_sentence, _test, endpoint, net,
)

GRANTED = "lan-mail-member"


class _Auth:
    is_configured = True

    def get_privileges(self, name):
        from core.auth import ADMIN_PRIVILEGES
        if name == ADMIN:  # as the real manager answers an admin
            return dict(ADMIN_PRIVILEGES)
        return {"can_reach_private_mail": True} if name == GRANTED else {}

    def is_admin(self, name):
        return name == ADMIN


@pytest.fixture()
def people(net, monkeypatch):
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager", lambda: _Auth())
    return net


@pytest.mark.parametrize("host,port", [
    ("127.0.0.1", 5432), ("localhost", 11434), ("::1", 8080), ("sneaky.example", 993),
    ("192.168.1.50", 22),   # an address this machine answers on (the stand-in's)
])
def test_a_granted_member_cannot_reach_this_machine(people, endpoint, host, port):
    result = _test(endpoint, _both_halves(host, imap_port=port, smtp_port=port), GRANTED)
    assert result["imap"]["error"] == _refused_sentence(), result
    assert result["smtp"]["error"] == _refused_sentence(), result
    assert people.dialled == [], f"{host}:{port} was connected to: {people.dialled}"


def test_a_granted_members_saved_account_cannot_be_aimed_at_this_machine(people, endpoint):
    """The account save asks the same question before it stores the host."""
    from src import mail_reach
    reach = mail_reach.reach_for(GRANTED)
    assert mail_reach.refusal("127.0.0.1", 5432, reach) == _refused_sentence()
    assert mail_reach.refusal("localhost", 993, reach) == _refused_sentence()


# ── what the grant is for, and the admin ──────────────────────────────────────

@pytest.mark.parametrize("host,port", [("192.168.1.20", 31143), ("home.lan", 143), ("10.0.0.5", 1143)])
def test_a_granted_member_still_reaches_the_lan_on_any_port(people, endpoint, host, port):
    result = _test(endpoint, _both_halves(host, imap_port=port, smtp_port=port), GRANTED)
    assert len(people.dialled) == 2, people.dialled
    for half in ("imap", "smtp"):
        assert "refused the connection" in result[half]["error"], result[half]


def test_the_admin_still_reaches_this_machine(people, endpoint):
    result = _test(endpoint, _both_halves("127.0.0.1", imap_port=1143, smtp_port=1025), ADMIN)
    assert len(people.dialled) == 2, people.dialled


def test_a_member_without_the_grant_still_reaches_neither(people, endpoint):
    result = _test(endpoint, _both_halves("192.168.1.20"), MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert people.dialled == []
