# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-04` — a name only the person's network knows, mapped for them alone;
a self-signed certificate trusted only when they pinned it. `D-2026-10-24-03`.

Driven, not read (`Law 20`): the real proxy (`workstation/name_proxy.py`) and
the real daemon starting it, a real curl through it, a real HTTPS server with a
self-signed certificate made by openssl for a name no DNS knows, and — where
Firefox is installed — the person's real Firefox reaching both through the
PAC file and `certutil`'s trust. The vault's side is driven through its own
functions and the daemon over HTTP.

**Measured before this file, on `9109d7c`:** setting up an agent account on
`grafana.lan` answered *curl: (6) Could not resolve host: grafana.lan*, and
there was no way for one person to say where that name is.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from workstation import name_proxy as NP
from workstation import names as NM

CURL = shutil.which("curl")
OPENSSL = shutil.which("openssl")
FIREFOX = shutil.which("firefox")


class _Page(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = f"<title>{self.headers.get('Host')}</title><p>served {self.path}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def plain():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture(scope="module")
def secure(tmp_path_factory):
    """An HTTPS server whose certificate signed itself, for `secure.lan`."""
    if not OPENSSL:
        pytest.skip("openssl is not installed here")
    d = tmp_path_factory.mktemp("tls")
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", "/CN=secure.lan", "-addext", "subjectAltName=DNS:secure.lan",
                    "-keyout", str(d / "key.pem"), "-out", str(d / "cert.pem")],
                   check=True, capture_output=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "cert.pem", d / "key.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], (d / "cert.pem").read_text()
    srv.shutdown()


def _curl(url, proxy, cafile=None):
    argv = [CURL, "-sS", "--max-time", "10", "-o", "-", "-w", "\n%{http_code}", "-x", proxy, url]
    if cafile:
        argv[1:1] = ["--cacert", str(cafile)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=20)


# ── the proxy ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not CURL, reason="curl is not installed here")
def test_the_proxy_sends_a_mapped_name_to_its_address_and_the_rest_as_they_resolve(tmp_path, plain):
    m = tmp_path / "map.json"
    m.write_text(json.dumps({"map": {"grafana.lan": "127.0.0.1"}}))
    srv = NP.serve(m, tmp_path / "port")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    proxy = f"http://127.0.0.1:{(tmp_path / 'port').read_text()}"
    try:
        r = _curl(f"http://grafana.lan:{plain}/dashboards", proxy)
        assert r.stdout.endswith("\n200") and "<title>grafana.lan:" in r.stdout, r
        assert "served /dashboards" in r.stdout, "origin form, Host kept"
        r = _curl(f"http://localhost:{plain}/", proxy)
        assert r.stdout.endswith("\n200"), "an unmapped name resolves as the network says"
        m.write_text(json.dumps({"map": {}}))
        r = _curl(f"http://grafana.lan:{plain}/", proxy)
        assert not r.stdout.endswith("\n200"), "the map is read again when it changes"
    finally:
        srv.shutdown()


# ── the daemon's side: files, the proxy as the account, the trusted file ────

@pytest.mark.skipif(not (CURL and OPENSSL), reason="curl or openssl is not installed here")
def test_a_pinned_certificate_is_trusted_for_its_name_and_nothing_else(tmp_path, plain, secure):
    import os
    port, pem = secure
    n = NM.AccountNames(tmp_path / "home", [], dict(os.environ))
    try:
        out = n.apply({"map": {"secure.lan": "127.0.0.1", "grafana.lan": "127.0.0.1"}, "pins": []})
        assert out["proxy"] and out["ca_file"] is None and out["changed"]
        pac = (tmp_path / "home" / NM.NAMES_DIR / NM.PAC_FILE).read_text()
        assert '"grafana.lan", "secure.lan"' in pac and "PROXY 127.0.0.1:" in pac
        assert "network.proxy.autoconfig_url" in n.browser_prefs()
        unpinned = _curl(f"https://secure.lan:{port}/", out["proxy"])
        assert "certificate" in unpinned.stderr.lower(), "a self-signed certificate is not trusted unasked"

        again = n.apply({"map": {"secure.lan": "127.0.0.1", "grafana.lan": "127.0.0.1"},
                         "pins": [{"origin": f"https://secure.lan:{port}", "pem": pem}]})
        assert again["changed"] and again["proxy"] == out["proxy"], "the proxy keeps running; the map is reread"
        trusted = Path(again["ca_file"]).read_text()
        assert pem.strip() in trusted and trusted.count("BEGIN CERTIFICATE") > 1, "the system's CAs and the pin"
        pinned = _curl(f"https://secure.lan:{port}/x", again["proxy"], again["ca_file"])
        assert pinned.stdout.endswith("\n200") and "served /x" in pinned.stdout, pinned
        assert n.apply({"map": {"secure.lan": "127.0.0.1", "grafana.lan": "127.0.0.1"},
                        "pins": [{"origin": f"https://secure.lan:{port}", "pem": pem}]})["changed"] is False

        n.apply({"map": {}, "pins": []})
        assert n.port is None and n.proc is None, "no name mapped: no proxy"
    finally:
        n.stop()


@pytest.mark.parametrize("body,words", [
    ({"map": {"bad name!": "10.0.0.5"}}, "is not a host name"),
    ({"map": {"nas.lan": "nas"}}, "is not an address"),
    ({"pins": [{"origin": "x", "pem": "not a certificate"}]}, "one PEM certificate"),
])
def test_a_bad_set_is_refused_in_a_sentence(body, words):
    with pytest.raises(NM.NamesRefused) as e:
        NM.clean(body)
    assert words in e.value.message


# ── the vault: names are a login's own, within the network mode ─────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    from tests.test_the_vault_is_each_persons_own import db as _db_fixture  # noqa: F401
    import core.database as cdb
    import src.secret_storage as ss
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    engine = create_engine(f"sqlite:///{tmp_path / 'names.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.VaultKey.__table__, cdb.VaultItem.__table__,
                                                 cdb.GitIdentity.__table__, cdb.GitCredential.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    from src import vault as V
    V._unlocked_until.clear()
    from src import vault_names
    vault_names._sent.clear()
    return factory


def test_a_name_is_mapped_on_its_own_login_and_only_within_the_network_mode(db, monkeypatch):
    from src import vault as V
    from src import vault_names
    import src.workstation_access as wa
    s = db()
    item = V.create(s, "alice", {"label": "Grafana", "addresses": "grafana.lan:3000", "username": "a",
                                 "secret": "pw-secret-1"})
    monkeypatch.setattr(wa, "network_setting", lambda: "internet")
    with pytest.raises(V.VaultRefused) as mode:
        V.update(s, "alice", item["id"], {"mapped": {"grafana.lan": "10.0.0.5"}})
    assert "set to “internet”, which reaches the internet only" in mode.value.sentence and "never widens" in mode.value.sentence
    got = V.update(s, "alice", item["id"], {"mapped": {"grafana.lan": "93.184.216.34"}})
    assert got["mapped"] == {"grafana.lan": "93.184.216.34"}, "a public address is within any mode that reaches out"
    monkeypatch.setattr(wa, "network_setting", lambda: "full")
    V.update(s, "alice", item["id"], {"mapped": {"grafana.lan": "10.0.0.5"}})
    for bad, words in ((({"other.lan": "10.0.0.6"}), "is not one of this login's addresses"),
                       ({"grafana.lan": "0.0.0.0"}, "is not an address a service is reached at")):
        with pytest.raises(V.VaultRefused) as e:
            V.update(s, "alice", item["id"], {"mapped": bad})
        assert words in e.value.sentence
    assert vault_names.wanted(s, "alice") == {"map": {"grafana.lan": "10.0.0.5"}, "pins": []}
    assert vault_names.wanted(s, "bob") == {"map": {}, "pins": []}, "one person's names are theirs"
    assert V.for_use(s, "alice", "Grafana")["mapped"] == {"grafana.lan": "10.0.0.5"}
    V.update(s, "alice", item["id"], {"addresses": "grafana.example.org"})
    assert V.listing(s, "alice")["items"][0]["mapped"] == {}, "a name no longer an address is unmapped"


def test_a_command_is_given_the_proxy_the_trusted_file_and_the_address_itself():
    from src import vault_names
    from src.agent_tools import login_shell_tools as L
    env = vault_names.env_for({"proxy": "http://127.0.0.1:4100", "ca_file": "/h/.pantheon/names/trusted.pem"})
    assert env["HTTPS_PROXY"] == env["http_proxy"] == "http://127.0.0.1:4100"
    assert env["CURL_CA_BUNDLE"] == env["GIT_SSL_CAINFO"] == "/h/.pantheon/names/trusted.pem"
    assert vault_names.env_for({}) == {}
    got, names = L.environment([{"label": "DB", "username": "agent", "secret": "pw", "otp": "",
                                 "origins": ["http://db.lan:5432"], "mapped": {"db.lan": "10.0.0.7"}}])
    assert got["LOGIN_HOST_IP"] == "10.0.0.7" and got["LOGIN_PORT"] == "5432" and got["LOGIN_HOST"] == "db.lan"


# ── through the daemon, with the person's real Firefox ──────────────────────

@pytest.fixture
def daemon_up(tmp_path, monkeypatch, db):
    from tests.helpers.workstation_daemon import running_workstation
    from tests.test_the_agent_works_the_workstation_screen import configure
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws)
        yield ws


@pytest.mark.skipif(not (FIREFOX and OPENSSL), reason="Firefox or openssl is not installed here")
def test_the_persons_browser_reaches_a_mapped_name_and_a_pinned_certificate(daemon_up, plain, secure, monkeypatch):
    from src import vault as V
    from src import vault_names
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
    from tests.test_the_agent_works_the_workstation_screen import PERMITTED
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "network_setting", lambda: "full")
    port, pem = secure
    s = __import__("core.database", fromlist=["SessionLocal"]).SessionLocal()
    item = V.create(s, PERMITTED, {"label": "Shop", "addresses": [f"plain.lan:{plain}", f"https://secure.lan:{port}"],
                                   "username": "agent", "secret": "pw-shop-9"})

    def browse(args):
        return asyncio.run(execute_tool_block(ToolBlock("agent_browser", json.dumps(args)), owner=PERMITTED,
                                              security_context=NO_TOOL_SECURITY_CONTEXT))[1]

    try:
        # Before: neither name resolves.
        tested = asyncio.run(vault_names.test(s, PERMITTED, item["id"]))
        assert [r["dns"] for r in tested["results"]] == [[], []]
        # Map both to this machine (a private address: the mode is Full).
        V.update(s, PERMITTED, item["id"], {"mapped": {"plain.lan": "127.0.0.1", "secure.lan": "127.0.0.1"}})
        tested = asyncio.run(vault_names.test(s, PERMITTED, item["id"]))
        plain_r, secure_r = tested["results"]
        assert plain_r["mapped_to"] == "127.0.0.1" and plain_r["http"] == 200
        cert = secure_r["cert"]
        assert cert["self_signed"] and not cert["trusted"] and not cert["pinned"]
        opened = browse({"action": "open", "url": f"http://plain.lan:{plain}/"})
        assert opened["exit_code"] == 0 and f"plain.lan:{plain}" in opened["output"], opened
        # Pin the certificate the person was shown; a different one is refused.
        with pytest.raises(V.VaultRefused) as wrong:
            asyncio.run(vault_names.pin(s, PERMITTED, item["id"], f"https://secure.lan:{port}", "AB:CD"))
        assert "different certificate" in wrong.value.sentence
        asyncio.run(vault_names.pin(s, PERMITTED, item["id"], f"https://secure.lan:{port}", cert["sha256"]))
        again = asyncio.run(vault_names.test(s, PERMITTED, item["id"]))["results"][1]["cert"]
        assert again["pinned"] and again["trusted"], "the workstation trusts it now, for that name"
        page = browse({"action": "open", "url": f"https://secure.lan:{port}/pinned"})
        assert page["exit_code"] == 0, page
        read = browse({"action": "read"})
        assert "served /pinned" in read["output"], "Firefox trusted exactly the pinned certificate"
    finally:
        s.close()
        daemon_up.server.station.browsers.stop_all()
