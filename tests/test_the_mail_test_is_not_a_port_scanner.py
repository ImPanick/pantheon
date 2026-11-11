# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2102` — the mail account form's Test is not a port scanner.

Any member could aim `POST /api/email/accounts/test`, or a saved account, at
`127.0.0.1`, the LAN or the cloud's metadata service and read whether a port
answered: `B2032` took the banner out of the answer, but *refused*, *timed out*
and *did not answer like an IMAP server* still told one port from another. The
owner's ruling: fix it.

Now a mail account reaches a public address on a mail port, and this machine,
a private network or another port only for a person who holds
`can_reach_private_mail` (every admin; a member an admin granted it to).
Link-local and the cloud metadata hosts are refused to everyone. The name is
resolved once, every address it resolved to is checked, and the connection is
made to the checked address, so a name that answers differently the second
time (DNS rebinding) is never connected to on its second answer; TLS still sees
the typed name. A refused host gets one sentence, whatever listens there.

No network: DNS and `socket.create_connection` are stand-ins, and every
connection a test let through is recorded rather than made.
"""
from __future__ import annotations

import asyncio
import json
import socket
from unittest import mock

import pytest

import routes.email_helpers as eh

PUBLIC = "93.184.216.34"
#: A public address this machine itself answers on.
THIS_HOST_PUBLIC = "44.1.2.3"

#: What the stand-in DNS answers for each name. A list is answered in turn,
#: the last answer repeating: `rebind.example` answers public first, then
#: loopback, as a rebinding attacker's resolver does.
DNS = {
    "mail.example.com": [[PUBLIC]],
    "sneaky.example": [["127.0.0.1"]],
    "mixed.example": [[PUBLIC, "10.0.0.7"]],
    "self.example": [[THIS_HOST_PUBLIC]],
    "home.lan": [["192.168.1.20"]],
    "rebind.example": [[PUBLIC], ["127.0.0.1"]],
}

ADMIN, MEMBER = "root-admin", "mallory"


class _Net:
    """The stand-in network: who looked up what, and where a connection went."""

    def __init__(self):
        self.lookups: list[str] = []
        self.dialled: list[tuple] = []
        self.answer = ConnectionRefusedError   # what a connection meets
        self._turn: dict[str, int] = {}

    def getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        host = str(host)
        self.lookups.append(host)
        try:
            ips = [str(socket.inet_ntop(socket.AF_INET6, socket.inet_pton(socket.AF_INET6, host.split("%")[0])))
                   if ":" in host else str(socket.inet_ntoa(socket.inet_aton(host)))]
        except OSError:
            answers = DNS.get(host.lower())
            if answers is None:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            turn = self._turn.get(host, 0)
            self._turn[host] = turn + 1
            ips = answers[min(turn, len(answers) - 1)]
        out = []
        for ip in ips:
            if ":" in ip:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port or 0, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)))
        return out

    def create_connection(self, address, timeout=None, source_address=None, *, all_errors=False):
        # What the libraries would have done unguarded: resolve the name again
        # and connect to whatever it says NOW.
        host, port = address[0], address[1]
        ip = self.getaddrinfo(host, port)[0][4][0]
        self.dialled.append((host, ip, port))
        if isinstance(self.answer, type):
            raise self.answer("stand-in network")
        return self.answer(host, ip, port)


class _Auth:
    is_configured = True

    def get_privileges(self, name):
        return {"can_reach_private_mail": True} if name == ADMIN else {}

    def is_admin(self, name):
        return name == ADMIN


@pytest.fixture()
def net(monkeypatch):
    stand_in = _Net()
    monkeypatch.setattr(socket, "getaddrinfo", stand_in.getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", stand_in.create_connection)
    # This machine answers on a LAN address and one public one.
    monkeypatch.setattr("netagent.observe._addresses", lambda: ["192.168.1.50", THIS_HOST_PUBLIC])
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager", lambda: _Auth())
    try:
        import src.mail_reach as mail_reach
    except ImportError:   # the tree before `B2102`
        pass
    else:
        monkeypatch.setattr(mail_reach, "_HOST_ADDRESSES", {"at": 0.0, "set": frozenset()})
    return stand_in


@pytest.fixture()
def endpoint(monkeypatch):
    import routes.email_routes as email_routes

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    router = email_routes.setup_email_routes()

    def find(method, path):
        for route in router.routes:
            if route.path == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise AssertionError(f"{method} {path} is not registered")

    return find


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _refused_sentence() -> str:
    from src.mail_reach import REFUSED_SENTENCE
    return REFUSED_SENTENCE


def _both_halves(host, imap_port=993, smtp_port=465):
    return {"imap_host": host, "imap_port": imap_port, "imap_user": "me@example.test",
            "imap_password": "pw", "smtp_host": host, "smtp_port": smtp_port,
            "smtp_security": "ssl"}


def _test(endpoint, body, owner):
    return asyncio.run(endpoint("POST", "/api/email/accounts/test")(req=_Req(body), owner=owner))


# ── a member is refused, and nothing is connected to ──────────────────────────

@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "172.16.4.4", "100.64.0.9",
    "169.254.169.254", "100.100.100.200", "::1", "[::1]", "fe80::1", "fd00:ec2::254",
    "fc00::5", "::ffff:127.0.0.1", "0.0.0.0", "metadata.google.internal",
])
def test_a_member_aiming_the_test_at_this_machine_or_a_private_network_is_refused(net, endpoint, host):
    result = _test(endpoint, _both_halves(host), MEMBER)
    assert result["ok"] is False
    assert result["imap"]["error"] == _refused_sentence()
    assert result["smtp"]["error"] == _refused_sentence()
    assert net.dialled == [], f"{host} was connected to: {net.dialled}"


def test_a_name_that_resolves_to_loopback_is_refused(net, endpoint):
    result = _test(endpoint, _both_halves("sneaky.example"), MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert result["smtp"]["error"] == _refused_sentence()
    assert net.dialled == []


def test_a_name_with_one_private_address_among_public_ones_is_refused(net, endpoint):
    result = _test(endpoint, _both_halves("mixed.example"), MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert net.dialled == []


def test_this_machines_own_public_address_is_refused_to_a_member(net, endpoint):
    result = _test(endpoint, _both_halves("self.example"), MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert net.dialled == []


def test_a_member_may_not_aim_a_public_host_at_a_port_mail_does_not_use(net, endpoint):
    result = _test(endpoint, _both_halves("mail.example.com", imap_port=22, smtp_port=3306), MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert result["smtp"]["error"] == _refused_sentence()
    assert net.dialled == []


def test_a_refused_host_reads_the_same_whatever_listens_there(net, endpoint):
    answers = []
    for what in (ConnectionRefusedError, TimeoutError, ConnectionResetError):
        net.answer = what
        answers.append(_test(endpoint, _both_halves("127.0.0.1", imap_port=143, smtp_port=25), MEMBER))
    assert answers[0] == answers[1] == answers[2]
    assert answers[0]["imap"]["error"] == _refused_sentence()


# ── rebinding: the address checked is the address connected to ───────────────

def test_a_name_that_rebinds_to_loopback_after_the_check_is_never_connected_to_on_loopback(net, endpoint):
    body = dict(_both_halves("rebind.example"), smtp_host="")
    result = _test(endpoint, body, MEMBER)
    assert result["ok"] is False
    # Let through on the public answer, and connected to that address as a
    # literal: never to the name, whose next answer is 127.0.0.1.
    assert [(h, ip) for h, ip, _ in net.dialled] == [(PUBLIC, PUBLIC)], net.dialled
    assert net.lookups.count("rebind.example") == 1


def test_dial_connects_to_the_address_it_checked_not_to_the_names_next_answer(net):
    from src import mail_reach
    with pytest.raises(ConnectionRefusedError):
        mail_reach.dial("rebind.example", 993, 5, mail_reach.MEMBER)
    assert [(h, ip) for h, ip, _ in net.dialled] == [(PUBLIC, PUBLIC)]
    # The name's next answer is loopback, and it is refused when asked again.
    with pytest.raises(mail_reach.MailHostRefused):
        mail_reach.dial("rebind.example", 993, 5, mail_reach.MEMBER)
    assert len(net.dialled) == 1


def test_the_tls_hostname_is_the_typed_name_while_the_socket_goes_to_the_checked_address(net, monkeypatch):
    seen = {}

    class _Ctx:
        def wrap_socket(self, sock, server_hostname=None, **kw):
            seen["server_hostname"] = server_hostname
            raise _Stop()

    class _Stop(Exception):
        pass

    net.answer = lambda host, ip, port: mock.MagicMock(name=f"socket to {ip}:{port}")
    monkeypatch.setattr(eh, "_get_email_config", lambda account_id=None, owner="": {
        "owner": ADMIN, "imap_host": "mail.example.com", "imap_port": 993, "imap_starttls": False,
        "imap_user": "u", "imap_password": "p"})
    monkeypatch.setattr(eh._mail_tls, "context_for", lambda *a, **k: _Ctx())
    with pytest.raises(_Stop):
        eh._imap_connect("acct", owner=ADMIN)
    assert seen["server_hostname"] == "mail.example.com"
    assert [(h, ip) for h, ip, _ in net.dialled] == [(PUBLIC, PUBLIC)]

    seen.clear()
    net.dialled.clear()
    cfg = {"owner": ADMIN, "smtp_host": "mail.example.com", "smtp_port": 465, "smtp_security": "ssl"}
    with pytest.raises(_Stop):
        eh._send_smtp_message(cfg, "a@example.com", ["b@example.com"], "hi")
    assert seen["server_hostname"] == "mail.example.com"
    assert [(h, ip) for h, ip, _ in net.dialled] == [(PUBLIC, PUBLIC)]


# ── still allowed ─────────────────────────────────────────────────────────────

def test_a_public_mail_host_on_a_mail_port_is_still_tried_for_a_member(net, endpoint):
    result = _test(endpoint, _both_halves("mail.example.com"), MEMBER)
    assert [(ip, p) for _h, ip, p in net.dialled] == [(PUBLIC, 993), (PUBLIC, 465)]
    # The ordinary `B2032` sentence for a server that refused, not the refusal's.
    for half in ("imap", "smtp"):
        assert "refused the connection" in result[half]["error"], result[half]


@pytest.mark.parametrize("host,port", [("192.168.1.20", 31143), ("home.lan", 143), ("127.0.0.1", 1143)])
def test_an_admin_may_reach_their_own_lan_or_this_machine_on_any_port(net, endpoint, host, port):
    result = _test(endpoint, _both_halves(host, imap_port=port, smtp_port=port), ADMIN)
    assert len(net.dialled) == 2, net.dialled
    for half in ("imap", "smtp"):
        assert "refused the connection" in result[half]["error"], result[half]


@pytest.mark.parametrize("host", ["169.254.169.254", "fe80::1", "100.100.100.200", "metadata.google.internal"])
def test_link_local_and_cloud_metadata_are_refused_even_to_an_admin(net, endpoint, host):
    result = _test(endpoint, _both_halves(host), ADMIN)
    assert result["imap"]["error"] == _refused_sentence()
    assert net.dialled == []


def _shared_db():
    """An in-memory database every thread sees: the Test reads the saved
    account off the event loop."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from core.database import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_a_member_testing_an_account_nobody_owns_gets_a_members_reach(net, endpoint):
    """An account nobody owns is the install's, and asks nothing of its own —
    but the Test asks the person pressing it too, so a member who can see a
    legacy row (its mailbox is theirs) cannot borrow the install's reach by
    editing its host in the form."""
    from tests.test_email_ownerless_account_owner_scope import _make_account
    Factory = _shared_db()
    _make_account(Factory, "acct-legacy", owner="", imap_user=MEMBER)
    with mock.patch("core.database.SessionLocal", Factory):
        result = _test(endpoint, {"account_id": "acct-legacy", "imap_host": "10.1.1.1",
                                  "imap_port": 993, "imap_password": "pw"}, MEMBER)
    assert result["imap"]["error"] == _refused_sentence()
    assert net.dialled == []


# ── every other door a member's host reaches ──────────────────────────────────

def test_a_saved_accounts_inbox_check_and_send_refuse_loopback(net, monkeypatch):
    monkeypatch.setattr(eh, "_get_email_config", lambda account_id=None, owner="": {
        "owner": MEMBER, "imap_host": "127.0.0.1", "imap_port": 993, "imap_starttls": False,
        "imap_user": "u", "imap_password": "p"})
    with pytest.raises(OSError) as raised:
        eh._imap_connect("acct", owner=MEMBER)
    assert str(raised.value) == _refused_sentence()

    cfg = {"owner": MEMBER, "smtp_host": "sneaky.example", "smtp_port": 587, "smtp_security": "starttls"}
    with pytest.raises(OSError) as raised:
        eh._send_smtp_message(cfg, "a@example.com", ["b@example.com"], "hi")
    assert str(raised.value) == _refused_sentence()
    assert eh._friendly_email_auth_error("SMTP", "sneaky.example", raised.value, port=587) == _refused_sentence()
    assert net.dialled == []


def test_a_member_reaching_an_ownerless_account_gets_a_members_reach(net, monkeypatch):
    """An account nobody owns is the install's, but whoever asks for it is asked."""
    from tests.test_email_ownerless_account_owner_scope import _make_account, _make_db
    Factory = _make_db()
    _make_account(Factory, "acct-legacy", owner="", imap_user=MEMBER)
    from core.database import EmailAccount
    db = Factory()
    row = db.get(EmailAccount, "acct-legacy")
    row.imap_host, row.imap_port, row.imap_starttls = "127.0.0.1", 993, False
    db.commit()
    db.close()
    with mock.patch("core.database.SessionLocal", Factory):
        with pytest.raises(OSError) as raised:
            eh._imap_connect("acct-legacy", owner=MEMBER)
    assert str(raised.value) == _refused_sentence()
    assert net.dialled == []


def test_the_agents_mail_tools_refuse_a_members_loopback_account(net, monkeypatch):
    import mcp_servers.email_server as srv
    monkeypatch.setattr(srv, "_current_owner", lambda: MEMBER)
    cfg = {"owner": MEMBER, "imap_host": "127.0.0.1", "imap_port": 993, "imap_ssl": True,
           "imap_starttls": False, "smtp_host": "10.0.0.2", "smtp_port": 465, "smtp_security": "ssl",
           "smtp_user": "u", "smtp_password": "p", "imap_user": "u", "imap_password": "p",
           "account_name": "m"}
    monkeypatch.setattr(srv, "_load_config", lambda account=None: dict(cfg))
    with pytest.raises(OSError) as raised:
        srv._imap_connect(None)
    assert str(raised.value) == _refused_sentence()
    with pytest.raises(OSError) as raised:
        srv._smtp_connect(None, cfg=dict(cfg))
    assert str(raised.value) == _refused_sentence()
    assert net.dialled == []


def test_reading_a_certificate_to_offer_is_refused_on_loopback_too(net):
    from src import mail_tls
    from src.mail_reach import MEMBER as member_reach
    with pytest.raises(OSError) as raised:
        mail_tls.peek("imap", "127.0.0.1", 993, tls="ssl", reach=member_reach)
    assert str(raised.value) == _refused_sentence()
    assert net.dialled == []


def test_a_member_cannot_save_an_account_on_this_machine_or_on_another_port(net, endpoint):
    create = endpoint("POST", "/api/email/accounts")
    for data in ({"name": "x", "imap_host": "127.0.0.1", "imap_port": 993},
                 {"name": "x", "imap_host": "mail.example.com", "imap_port": 993,
                  "smtp_host": "10.0.0.3", "smtp_port": 587},
                 {"name": "x", "imap_host": "mail.example.com", "imap_port": 2222}):
        answer = create(data, owner=MEMBER)
        assert getattr(answer, "status_code", None) == 400, (data, answer)
        assert json.loads(answer.body)["error"] == _refused_sentence()
    assert net.dialled == []
