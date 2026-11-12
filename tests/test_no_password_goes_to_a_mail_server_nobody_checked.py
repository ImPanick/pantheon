# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2096` — no password goes to a mail server nobody checked.

`imaplib` and `smtplib` take `ssl._create_stdlib_context()` when they are given
no context, and that context checks nothing. No mail connection gave one, so
whoever answered on the network path was the mail server, and the next thing
the client sent it was the account's password. Measured before the fix: an
IMAP server showing a self-signed certificate for `impostor.example` read
`LOGIN alice@example.com "correct horse battery staple"`.

The owner chose *split by host* (2026-11-07), and `src/mail_tls.py` holds it:
a public host has to show a certificate an authority signed for its name; a
private host has its first certificate pinned and has to show the same one
after; a certificate a person trusts from the account form's Test is pinned
the same way whatever the host. Each check runs after the handshake and
before the sign-in.

The servers here are real: TLS IMAP and SMTP servers on loopback, each with a
certificate made for the test, each recording every line a client sends, so
"no password was sent" is read off the wire. The clients are Pantheon's own:
the app's `_imap_connect` (behind every mailbox route, the pool and the
pollers) and `_send_smtp_message` (every send), the agent's mail server's
`_imap_connect` and `_smtp_connect`, and the account form's Test and its
Trust button. 127.0.0.1 is a private host, so a test about a public one reads
it as public; the only other stand-in is a redirect that lets an implicit-TLS
IMAP account on 993 reach the test server's port.
"""
from __future__ import annotations

import ast
import base64
import datetime
import imaplib
import ipaddress
import json
import logging
import socket
import ssl
import threading
from pathlib import Path

import pytest

from src import constants, mail_tls


@pytest.fixture(autouse=True)
def _a_person_allowed_this_network(monkeypatch):
    """`B2102`: the mail servers here stand on loopback, which a mail account
    reaches only for a person holding `can_reach_private_mail`."""
    from tests.helpers.mail_reach import allow_this_network
    allow_this_network(monkeypatch)


USER = "alice@example.test"
PASSWORD = "correct horse battery staple"
_REAL_IMAP4_SSL = imaplib.IMAP4_SSL
_REPO = Path(__file__).resolve().parents[1]


# ── certificates ──────────────────────────────────────────────────────────────

class _Cert:
    def __init__(self, certfile: Path, keyfile: Path, der: bytes):
        self.certfile, self.keyfile = certfile, keyfile
        self.fingerprint = mail_tls.fingerprint(der)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _key_usage(*, signs_certificates: bool):
    from cryptography import x509
    return x509.KeyUsage(
        digital_signature=True, content_commitment=False, key_encipherment=False,
        data_encipherment=False, key_agreement=False, key_cert_sign=signs_certificates,
        crl_sign=signs_certificates, encipher_only=False, decipher_only=False)


class _Authority:
    """A certificate authority the test trusts, as the system trusts a real one."""

    def __init__(self, folder: Path):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        self.key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Mail Authority")])
        self.cert = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(minutes=5))
            .not_valid_after(_now() + datetime.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(_key_usage(signs_certificates=True), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(self.key.public_key()), critical=False)
            .sign(self.key, hashes.SHA256()))
        self.pem = folder / "authority.crt"
        self.pem.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))

    def context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=str(self.pem))


def _certificate(folder: Path, label: str, authority: _Authority | None = None) -> _Cert:
    """A certificate for 127.0.0.1 and `<label>.test`: signed by `authority`, or
    by itself, as an impostor's or a home server's would be."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{label}.test")])
    builder = (
        x509.CertificateBuilder().subject_name(subject)
        .issuer_name(authority.cert.subject if authority else subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=5))
        .not_valid_after(_now() + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName(f"{label}.test")]),
            critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(signs_certificates=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False))
    if authority:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(authority.key.public_key()),
            critical=False)
    cert = builder.sign(authority.key if authority else key, hashes.SHA256())
    certfile, keyfile = folder / f"{label}.crt", folder / f"{label}.key"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return _Cert(certfile, keyfile, cert.public_bytes(serialization.Encoding.DER))


# ── servers ───────────────────────────────────────────────────────────────────

class _Lines:
    """A client connection read line by line, which can turn into TLS."""

    def __init__(self, sock):
        self.sock, self._buf = sock, b""

    def readline(self) -> bytes:
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return b""
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line + b"\n"

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def start_tls(self, ctx: ssl.SSLContext) -> None:
        self.sock = ctx.wrap_socket(self.sock, server_side=True)


class _MailServer:
    """An IMAP or SMTP server on loopback that records every line it reads.

    `tls` is `ssl` (TLS from the first byte) or `starttls`. `use(cert)` changes
    the certificate the next connection is shown, as replacing the server's
    certificate would, or an impostor taking its place.
    """

    def __init__(self, kind: str, tls: str, cert: _Cert):
        self.kind, self.tls, self.lines = kind, tls, []
        self.use(cert)
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def use(self, cert: _Cert) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert.certfile), str(cert.keyfile))
        self._ctx = ctx

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._listener.close()

    def signins(self) -> list[str]:
        """The sign-in lines it read: IMAP `LOGIN`/`AUTHENTICATE`, SMTP `AUTH`."""
        out = []
        for line in list(self.lines):
            words = line.split(" ")
            verb = words[1] if self.kind == "imap" and len(words) > 1 else words[0]
            if verb.upper() in ({"LOGIN", "AUTHENTICATE"} if self.kind == "imap" else {"AUTH"}):
                out.append(line)
        return out

    def heard_the_password(self) -> bool:
        plain = base64.b64encode(f"\0{USER}\0{PASSWORD}".encode()).decode()
        return any(PASSWORD in line or plain in line for line in list(self.lines))

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                sock, _ = self._listener.accept()
            except OSError:   # the listener's 0.2 s tick, or it was closed
                continue
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock) -> None:
        sock.settimeout(5)
        conn = _Lines(sock)
        try:
            if self.tls == "ssl":
                conn.start_tls(self._ctx)
            (self._imap if self.kind == "imap" else self._smtp)(conn)
        except OSError:
            return   # a client that refused the certificate hangs up mid-handshake
        finally:
            conn.sock.close()

    def _imap(self, conn: _Lines) -> None:
        secure = self.tls == "ssl"
        conn.send(b"* OK test IMAP ready\r\n")
        while True:
            raw = conn.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            self.lines.append(line)
            tag, _, rest = line.partition(" ")
            verb = rest.split(" ", 1)[0].upper()
            if verb == "CAPABILITY":
                caps = "IMAP4rev1 AUTH=PLAIN" + ("" if secure else " STARTTLS")
                conn.send(f"* CAPABILITY {caps}\r\n{tag} OK done\r\n".encode())
            elif verb == "STARTTLS":
                conn.send(f"{tag} OK begin TLS\r\n".encode())
                conn.start_tls(self._ctx)
                secure = True
            elif verb == "LOGOUT":
                conn.send(f"* BYE\r\n{tag} OK done\r\n".encode())
                return
            else:
                conn.send(f"{tag} OK {verb} done\r\n".encode())

    def _smtp(self, conn: _Lines) -> None:
        secure = self.tls == "ssl"
        conn.send(b"220 test ESMTP ready\r\n")
        while True:
            raw = conn.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            self.lines.append(line)
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                ext = ["250-test", "250-AUTH PLAIN"] + ([] if secure else ["250-STARTTLS"]) + ["250 8BITMIME"]
                conn.send(("\r\n".join(ext) + "\r\n").encode())
            elif verb == "STARTTLS":
                conn.send(b"220 go ahead\r\n")
                conn.start_tls(self._ctx)
                secure = True
            elif verb == "AUTH":
                conn.send(b"235 2.7.0 accepted\r\n")
            elif verb == "DATA":
                conn.send(b"354 go on\r\n")
                while conn.readline() not in (b"", b".\r\n", b".\n"):
                    pass   # the message itself; only the commands are recorded
                conn.send(b"250 queued\r\n")
            elif verb == "QUIT":
                conn.send(b"221 bye\r\n")
                return
            else:
                conn.send(b"250 ok\r\n")


@pytest.fixture
def certs(tmp_path):
    folder = tmp_path / "certs"
    folder.mkdir()
    return folder


@pytest.fixture
def serve():
    started = []

    def start(kind, tls, cert):
        server = _MailServer(kind, tls, cert)
        started.append(server)
        return server

    yield start
    for server in started:
        server.close()


@pytest.fixture
def as_public(monkeypatch):
    """127.0.0.1 read as a public host, the way `mail.example.com` is."""
    monkeypatch.setattr(mail_tls, "is_private_host", lambda host: False)


def _pins() -> dict:
    path = Path(constants.MAIL_TLS_PINS_FILE)
    return json.loads(path.read_text()) if path.exists() else {}


# ── the doors: every client that signs in to a mail server ────────────────────

def _imap_cfg(port: int, owner: str, *, implicit: bool) -> dict:
    return {"account_id": "acct-1", "account_name": "Home", "owner": owner,
            "imap_host": "127.0.0.1", "imap_port": port, "imap_user": USER,
            "imap_password": PASSWORD, "imap_starttls": not implicit, "imap_ssl": implicit,
            "oauth_provider": ""}


def _smtp_cfg(port: int, owner: str, *, security: str) -> dict:
    return {"account_id": "acct-1", "account_name": "Home", "owner": owner,
            "smtp_host": "127.0.0.1", "smtp_port": port, "smtp_security": security,
            "smtp_user": USER, "smtp_password": PASSWORD, "from_address": USER,
            "oauth_provider": ""}


class _Door:
    def __init__(self, who: str, kind: str, tls: str, monkeypatch):
        self.who, self.kind, self.tls, self._mp = who, kind, tls, monkeypatch

    def __repr__(self):
        return f"{self.who}-{self.kind}-{self.tls}"

    def typed_port(self, server) -> int:
        """The port the account names: an implicit-TLS IMAP account names 993."""
        return 993 if (self.who, self.kind, self.tls) == ("app", "imap", "ssl") else server.port

    def sign_in(self, server, owner: str = "alice") -> None:
        if self.who == "app" and self.kind == "imap":
            import routes.email_helpers as eh
            cfg = _imap_cfg(self.typed_port(server), owner, implicit=self.tls == "ssl")
            self._mp.setattr(eh, "_get_email_config", lambda *a, **k: cfg)
            self._mp.setattr(imaplib, "IMAP4_SSL",
                             lambda host, port, **kw: _REAL_IMAP4_SSL(host, server.port, **kw))
            eh._imap_connect("acct-1", owner=owner).logout()
        elif self.who == "app":
            import routes.email_helpers as eh
            eh._send_smtp_message(_smtp_cfg(server.port, owner, security=self.tls), USER,
                                  ["bob@example.test"], "Subject: hi\r\n\r\nhello\r\n")
        elif self.kind == "imap":
            import mcp_servers.email_server as agent
            cfg = _imap_cfg(server.port, owner, implicit=self.tls == "ssl")
            self._mp.setattr(agent, "_load_config", lambda account=None: cfg)
            agent._imap_connect().logout()
        else:
            import mcp_servers.email_server as agent
            agent._smtp_connect(cfg=_smtp_cfg(server.port, owner, security=self.tls)).quit()


_DOORS = [(who, kind, tls) for who in ("app", "agent") for kind in ("imap", "smtp")
          for tls in ("starttls", "ssl")]


@pytest.fixture(params=_DOORS, ids=["-".join(d) for d in _DOORS])
def door(request, monkeypatch):
    return _Door(*request.param, monkeypatch)


def _attempt(door, server, owner="alice"):
    """The refusal, or `None` when the client signed in."""
    try:
        door.sign_in(server, owner)
    except mail_tls.MailCertificateError as exc:
        return exc
    return None


# ── the rule ──────────────────────────────────────────────────────────────────

def test_an_impostor_on_a_public_host_is_refused_before_the_password(door, serve, certs, as_public):
    server = serve(door.kind, door.tls, _certificate(certs, "impostor"))

    refused = _attempt(door, server)

    assert server.signins() == [], f"the impostor read {server.signins()}"
    assert not server.heard_the_password()
    assert refused is not None and refused.reason == "untrusted"
    assert f"127.0.0.1:{door.typed_port(server)}" in str(refused)
    assert _pins() == {}, "a public host is never pinned on sight"


def test_a_public_host_whose_certificate_an_authority_signed_still_signs_in(
        door, serve, certs, as_public, monkeypatch):
    authority = _Authority(certs)
    monkeypatch.setattr(mail_tls, "_authority_context", authority.context)
    server = serve(door.kind, door.tls, _certificate(certs, "mail", authority))

    assert _attempt(door, server) is None
    assert len(server.signins()) == 1 and server.heard_the_password()
    assert _pins() == {}


def test_a_private_server_is_pinned_on_first_sight_and_refused_when_its_certificate_changes(
        door, serve, certs):
    first, other = _certificate(certs, "dovecot"), _certificate(certs, "stranger")
    server = serve(door.kind, door.tls, first)
    key = f"127.0.0.1:{door.typed_port(server)}"

    assert _attempt(door, server) is None, "a private server's first certificate is trusted"
    assert _pins()["alice"][key]["sha256"] == first.fingerprint
    assert _pins()["alice"][key]["how"] == "first seen"

    server.use(other)
    refused = _attempt(door, server)

    assert len(server.signins()) == 1, f"the changed server read {server.signins()[1:]}"
    assert refused is not None and refused.reason == "changed"
    assert (refused.fingerprint, refused.pinned) == (other.fingerprint, first.fingerprint)
    assert other.fingerprint in str(refused) and first.fingerprint in str(refused)

    server.use(first)
    assert _attempt(door, server) is None, "the pinned certificate still signs in"
    assert _pins()["alice"][key]["sha256"] == first.fingerprint


def test_a_pin_is_the_accounts_owners_in_the_app_and_the_agent_alike(serve, certs, monkeypatch):
    first, other = _certificate(certs, "dovecot"), _certificate(certs, "stranger")
    server = serve("imap", "starttls", first)
    app, agent = _Door("app", "imap", "starttls", monkeypatch), _Door("agent", "imap", "starttls", monkeypatch)

    assert _attempt(app, server, owner="alice") is None
    server.use(other)
    refused = _attempt(agent, server, owner="alice")
    assert refused is not None and refused.reason == "changed", "the agent did not read the app's pin"

    # Another member's account on the same server has pins of its own.
    assert _attempt(agent, server, owner="bob") is None
    assert _pins()["bob"][f"127.0.0.1:{server.port}"]["sha256"] == other.fingerprint
    assert _pins()["alice"][f"127.0.0.1:{server.port}"]["sha256"] == first.fingerprint


def test_an_unreadable_pin_file_refuses_a_private_server_and_is_left_as_it_was(serve, certs, monkeypatch):
    path = Path(constants.MAIL_TLS_PINS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    server = serve("imap", "starttls", _certificate(certs, "dovecot"))

    refused = _attempt(_Door("app", "imap", "starttls", monkeypatch), server)

    assert server.signins() == []
    assert refused is not None and refused.reason == "unreadable"
    assert path.read_text() == "{not json", "the record of trust was written over"


def test_an_unreadable_pin_file_leaves_a_public_host_the_authorities_check(
        serve, certs, as_public, monkeypatch):
    path = Path(constants.MAIL_TLS_PINS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    authority = _Authority(certs)
    monkeypatch.setattr(mail_tls, "_authority_context", authority.context)
    signed = serve("smtp", "starttls", _certificate(certs, "mail", authority))
    impostor = serve("smtp", "starttls", _certificate(certs, "impostor"))
    door = _Door("app", "smtp", "starttls", monkeypatch)

    assert _attempt(door, signed) is None
    refused = _attempt(door, impostor)
    assert impostor.signins() == [] and refused is not None and refused.reason == "untrusted"
    assert path.read_text() == "{not json"


@pytest.mark.parametrize("host, private", [
    ("127.0.0.1", True), ("10.1.2.3", True), ("192.168.1.20", True), ("172.20.0.4", True),
    ("100.101.102.103", True), ("169.254.0.9", True), ("[::1]", True), ("fd12:3456::1", True),
    ("fe80::1%eth0", True), ("::ffff:192.168.1.20", True), ("localhost", True),
    ("dovecot", True), ("mail.lan", True), ("nas.local", True), ("mail.home.arpa", True),
    ("box.internal", True), ("Mail.LAN.", True),
    ("imap.gmail.com", False), ("mail.example.com", False), ("8.8.8.8", False),
    ("1.1.1.1", False), ("2001:4860:4860::8888", False), ("localhost.example.com", False),
    ("", False),
])
def test_a_private_host_is_read_from_what_was_typed(host, private):
    assert mail_tls.is_private_host(host) is private


# ── the account form's Test and its Trust button ──────────────────────────────

class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
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


def _form(imap, smtp) -> dict:
    return {"imap_host": "127.0.0.1", "imap_port": imap.port, "imap_user": USER,
            "imap_password": PASSWORD, "imap_starttls": True,
            "smtp_host": "127.0.0.1", "smtp_port": smtp.port, "smtp_security": "starttls",
            "smtp_user": USER, "smtp_password": PASSWORD}


@pytest.mark.asyncio
async def test_a_certificate_trusted_from_the_account_test_is_the_one_that_signs_in(
        endpoint, serve, certs, as_public):
    own = _certificate(certs, "home")
    imap, smtp = serve("imap", "starttls", own), serve("smtp", "starttls", own)
    test = endpoint("POST", "/api/email/accounts/test")
    trust = endpoint("POST", "/api/email/accounts/trust-certificate")

    refused = await test(req=_Req(_form(imap, smtp)), owner="alice")

    assert refused["ok"] is False
    for half, server in (("imap", imap), ("smtp", smtp)):
        offer = refused[half]["certificate"]
        assert offer["reason"] == "untrusted" and offer["trustable"] is True
        assert offer["fingerprint"] == own.fingerprint, "the form offers what the server shows"
        assert (offer["host"], offer["port"]) == ("127.0.0.1", server.port)
        assert refused[half]["error"].startswith(
            f"The mail server at 127.0.0.1:{server.port} showed a certificate no trusted authority")
        assert server.signins() == [], f"the {half} server read {server.signins()}"

    for half in ("imap", "smtp"):
        offer = refused[half]["certificate"]
        answer = await trust(req=_Req({"host": offer["host"], "port": offer["port"],
                                       "fingerprint": offer["fingerprint"]}), owner="alice")
        assert answer == {"ok": True}

    passed = await test(req=_Req(_form(imap, smtp)), owner="alice")
    assert passed == {"ok": True, "imap": {"ok": True}, "smtp": {"ok": True}}
    assert len(imap.signins()) == 1 and len(smtp.signins()) == 1
    assert _pins()["alice"][f"127.0.0.1:{imap.port}"]["how"] == "trusted"

    # Alice's trust is hers: another member's Test of the same server is refused.
    other = await test(req=_Req(_form(imap, smtp)), owner="bob")
    assert other["imap"]["ok"] is False and other["imap"]["certificate"]["reason"] == "untrusted"
    assert len(imap.signins()) == 1


@pytest.mark.asyncio
async def test_the_trust_button_refuses_what_the_form_should_not_send(endpoint, monkeypatch):
    trust = endpoint("POST", "/api/email/accounts/trust-certificate")
    good = "sha256:" + "ab" * 32

    async def answer(body):
        response = await trust(req=_Req(body), owner="alice")
        return response.status_code, json.loads(response.body)

    assert (await answer({"host": "IMAP.Gmail.com.", "port": 993, "fingerprint": good}))[0] == 400
    assert (await answer({"host": "smtp-mail.outlook.com", "port": 587, "fingerprint": good}))[0] == 400
    assert (await answer({"host": "mail.home.test", "port": 70000, "fingerprint": good}))[0] == 400
    assert (await answer({"host": "mail.home.test", "port": 993, "fingerprint": "sha1:00"}))[0] == 400
    assert (await answer({"host": "", "port": 993, "fingerprint": good}))[0] == 400
    assert (await answer(["not", "an", "object"]))[0] == 400
    assert _pins() == {}

    # A provider's host is never offered either, and nothing is dialled to ask.
    monkeypatch.setattr(mail_tls, "peek", lambda *a, **k: pytest.fail("peeked at a provider"))
    refusal = mail_tls.MailCertificateError("imap.gmail.com", 993, reason="untrusted")
    assert mail_tls.offer(refusal, "imap", "imap.gmail.com", 993, tls="ssl")["trustable"] is False


@pytest.mark.asyncio
async def test_a_saved_accounts_test_and_trust_use_the_pins_its_own_connections_read(
        endpoint, serve, certs, monkeypatch):
    """A legacy account with no owner, seen by the member whose mailbox it is:
    its connections read the pins of owner `""`, so its Test and its Trust
    button do too, and another member cannot trust a certificate for it."""
    from fastapi import HTTPException

    import routes.email_helpers as eh
    from src.secret_storage import encrypt
    from tests.test_email_test_connection_oauth import _make_orm_account, _make_orm_db

    first, other = _certificate(certs, "dovecot"), _certificate(certs, "stranger")
    server = serve("imap", "starttls", first)
    db, factory = _make_orm_db()
    _make_orm_account(db, account_id="acct-legacy", owner="", imap_host="127.0.0.1",
                      imap_port=server.port, imap_starttls=True, imap_user=USER,
                      imap_password=encrypt(PASSWORD), from_address=USER, smtp_host="")
    db.close()
    monkeypatch.setattr("core.database.SessionLocal", factory)
    test = endpoint("POST", "/api/email/accounts/test")
    trust = endpoint("POST", "/api/email/accounts/trust-certificate")

    tested = await test(req=_Req({"account_id": "acct-legacy"}), owner=USER)
    assert tested["imap"] == {"ok": True}
    assert _pins()[""][f"127.0.0.1:{server.port}"]["sha256"] == first.fingerprint

    server.use(other)
    with pytest.raises(mail_tls.MailCertificateError) as changed:
        eh._imap_connect("acct-legacy", owner=USER)
    assert changed.value.reason == "changed"

    with pytest.raises(HTTPException) as hidden:
        await trust(req=_Req({"account_id": "acct-legacy", "host": "127.0.0.1",
                              "port": server.port, "fingerprint": other.fingerprint}), owner="bob")
    assert hidden.value.status_code == 404

    answer = await trust(req=_Req({"account_id": "acct-legacy", "host": "127.0.0.1",
                                   "port": server.port, "fingerprint": other.fingerprint}), owner=USER)
    assert answer == {"ok": True}
    eh._imap_connect("acct-legacy", owner=USER).logout()
    assert len(server.signins()) == 2


GOOD = "sha256:" + "ab" * 32
NOT_UPDATED = ("The certificate was not trusted: the list of trusted mail certificates "
               "could not be updated. The server log says why.")


async def _trust_answer(trust, body):
    response = await trust(req=_Req(body), owner="alice")
    return response.status_code, json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_the_trust_button_is_told_why_in_a_sentence_of_its_own(endpoint):
    """CodeQL on the port's pull request: the Trust route answered with an
    exception's text. A refusal is now `trust_refusal`'s sentence, which the
    route shows and nothing else. JSON's `Infinity` as the port was an
    `OverflowError` out of the route, a 500 the form could not read; it is a
    port out of range."""
    trust = endpoint("POST", "/api/email/accounts/trust-certificate")

    port_range = (400, "The port must be a number from 1 to 65535.")
    assert await _trust_answer(trust, {"host": "mail.home.test", "port": 70000,
                                       "fingerprint": GOOD}) == port_range
    assert await _trust_answer(trust, {"host": "mail.home.test", "port": float("inf"),
                                       "fingerprint": GOOD}) == port_range
    assert await _trust_answer(trust, {"host": "mail.home.test", "port": 993,
                                       "fingerprint": "sha1:00"}) == (
        400, "That is not a certificate fingerprint.")
    assert await _trust_answer(trust, {"host": " ", "port": 993, "fingerprint": GOOD}) == (
        400, "Name the mail server's host.")
    status, said = await _trust_answer(trust, {"host": "IMAP.Gmail.com.", "port": 993,
                                               "fingerprint": GOOD})
    assert status == 400 and said.startswith("imap.gmail.com belongs to a mail provider"), said
    assert _pins() == {}


@pytest.mark.asyncio
async def test_a_pin_file_that_cannot_be_read_or_written_is_said_without_its_path(
        endpoint, serve, certs, monkeypatch, caplog):
    """The pin file's own error can name a path on this host. It goes to the
    log; the Trust button and a refused connection say so in a sentence."""
    trust = endpoint("POST", "/api/email/accounts/trust-certificate")
    path = Path(constants.MAIL_TLS_PINS_FILE)
    path.mkdir(parents=True)        # reading it is `IsADirectoryError`, naming the path

    with caplog.at_level(logging.ERROR):
        assert await _trust_answer(trust, {"host": "mail.home.test", "port": 993,
                                           "fingerprint": GOOD}) == (503, NOT_UPDATED)
    assert str(path) in caplog.text, "the log no longer says why"

    server = serve("imap", "starttls", _certificate(certs, "dovecot"))
    refused = _attempt(_Door("app", "imap", "starttls", monkeypatch), server)
    assert server.signins() == []
    assert refused is not None and refused.reason == "unreadable"
    assert str(path) not in str(refused), str(refused)
    assert str(refused).endswith("could not be read. The server log says why.")

    # Read, and refused on the write.
    path.rmdir()

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr("core.atomic_io.atomic_write_json", refuse)
    assert await _trust_answer(trust, {"host": "mail.home.test", "port": 993,
                                       "fingerprint": GOOD}) == (503, NOT_UPDATED)


# ── the shape of the defect ───────────────────────────────────────────────────

def _python_files():
    for top in ("app.py", "core", "routes", "src", "services", "mcp_servers", "scripts"):
        path = _REPO / top
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
    yield _REPO / "scripts" / "pantheon-mail"


def test_every_tls_dial_in_the_tree_names_its_context():
    """The defect was a call that passed nothing: `IMAP4_SSL(...)`, `SMTP_SSL(...)`
    and `.starttls()` with no context take one that checks nothing. Every such
    call names one, so a new mail connection cannot fall back to it unseen."""
    wants = {"IMAP4_SSL": {"ssl_context"}, "SMTP_SSL": {"context"},
             "starttls": {"ssl_context", "context"}}
    bare = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in wants and not wants[name] & {kw.arg for kw in node.keywords}:
                bare.append(f"{path.relative_to(_REPO)}:{node.lineno} {name}()")
    assert bare == [], "TLS opened with no context, which checks no certificate:\n" + "\n".join(bare)
