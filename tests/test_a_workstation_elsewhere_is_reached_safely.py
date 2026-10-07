# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-07` — a workstation on another machine, set up with one command and
reached without handing its token to whoever is on the way.

The adversary (`Law 17`): anyone on the network path between Pantheon and a
workstation it was pointed at. The token they would read drives every
person's account there, and with `sudo` on (the default) is root. So:

  * the client sends the token over plain `http://` only to an address that is
    not globally routable, and refuses anything else **before a byte goes
    out** — asserted with a transport that fails the test if it is touched;
  * `https://` is verified: by the trust store, or by the exact certificate
    `PANTHEON_WORKSTATION_CERT_SHA256` pins — and a certificate that is not the
    pinned one fails the handshake before the request is written, asserted by
    a TLS listener that records every byte it is sent;
  * a redirect is not followed;
  * the daemon refuses to bind a literal public address without TLS, and says
    what it is (`--backend`) by looking rather than by default;
  * `workstation/install.py` makes the token, the certificate and the service
    unit, keeps the first two across re-runs (so Pantheon's copy stays right),
    and prints the exact lines Pantheon's `.env` needs — and those lines, set
    on Pantheon's side, reach the daemon the unit starts, on another address,
    through `from_settings` and the status route, as an admin would.

Everything runs the shipped code over real sockets.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import socket
import ssl
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src import workstation_client as wc
from src.workstation_client import WorkstationClient, WorkstationError
from workstation import __main__ as cli
from workstation import install, machine, service
from workstation import protocol as P

ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (P.TLS_PIN_ENV, P.TOKEN_ENV, P.URL_ENV):
        monkeypatch.delenv(var, raising=False)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, ",".join(filter(None, [os.environ.get(var, ""),
                                                       "127.0.0.2", "127.0.0.3"])))


@pytest.fixture
def no_wire(monkeypatch):
    """Every way the client could send a request, each failing the test."""
    touched = []

    async def refuse(*a, **k):
        touched.append(a[:2])
        raise AssertionError("a request was sent")

    from src import paced_http
    monkeypatch.setattr(paced_http, "request", refuse)
    return touched


# ── plain http only where nobody else is on the way ──────────────────────────

@pytest.mark.parametrize("base", [
    "http://8.8.8.8:7040", "http://1.1.1.1", "http://[2606:4700:4700::1111]:7040",
    "http://[::ffff:8.8.8.8]:7040",
])
def test_the_token_never_goes_to_a_public_address_in_the_clear(base, no_wire):
    c = WorkstationClient(base, "pws_secret")
    for call in (c.health, lambda: c.ensure(wc.account_for("ann")),
                 lambda: c.exec(wc.account_for("ann"), "true", on_output=lambda *a: None)):
        with pytest.raises(WorkstationError) as e:
            run(call())
        assert e.value.code == "bad_request"
        assert "will not send the workstation's token" in e.value.message
        assert "https://" in e.value.message and P.TLS_PIN_ENV in e.value.message
    assert no_wire == []


@pytest.mark.parametrize("base", [
    "http://10.1.2.3:9", "http://192.168.1.50:9", "http://172.20.0.5:9",
    "http://100.101.102.103:9",        # a tailnet: neither private nor global
    "http://169.254.10.10:9", "http://[fd12:3456::1]:9", "http://127.0.0.2:9",
])
def test_private_addresses_are_reached_over_plain_http(base, monkeypatch):
    sent = []

    async def answer(method, url, **kw):
        sent.append(url)
        raise ConnectionRefusedError("nobody there")

    from src import paced_http
    monkeypatch.setattr(paced_http, "request", answer)
    with pytest.raises(WorkstationError) as e:
        run(WorkstationClient(base, "pws_x").health())
    assert e.value.code == "unavailable" and "did not answer" in e.value.message
    assert sent == [base + "/v1/health"]


def test_a_name_is_judged_by_every_address_it_resolves_to(monkeypatch, no_wire):
    table = {"lan.test": ["192.168.1.9"], "pub.test": ["93.184.216.34"],
             "mixed.test": ["192.168.1.9", "93.184.216.34"]}
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))
                    for ip in table[host]]
        return real(host, port, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    for host in ("pub.test", "mixed.test"):
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(f"http://{host}:7040", "pws_x").health())
        assert e.value.code == "bad_request" and host in e.value.message
    assert no_wire == []
    verify = run(WorkstationClient("http://lan.test:7040", "pws_x")._wire())
    assert verify is True
    # A name that does not resolve is not reachable, said the usual way.
    with pytest.raises(WorkstationError) as e:
        run(WorkstationClient("http://nowhere.invalid:7040", "pws_x").health())
    assert e.value.code == "unavailable" and "did not answer" in e.value.message


# ── https, and the pin ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    root = tmp_path_factory.mktemp("cert")
    plan = install.Plan(dry_run=False, root=root)
    pin = install.make_certificate(plan, ["127.0.0.2", "workstation.test"])
    return (plan.path(install.TLS_DIR / "cert.pem"), plan.path(install.TLS_DIR / "key.pem"), pin)


@pytest.fixture(scope="module")
def other_cert(tmp_path_factory):
    root = tmp_path_factory.mktemp("other-cert")
    plan = install.Plan(dry_run=False, root=root)
    pin = install.make_certificate(plan, ["127.0.0.2"])
    return (plan.path(install.TLS_DIR / "cert.pem"), plan.path(install.TLS_DIR / "key.pem"), pin)


class Recorder:
    """A TLS listener that completes handshakes and records every byte a
    client sends after one — the request, and the token in it."""

    def __init__(self, cert_pem: Path, key_pem: Path):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(cert_pem), str(key_pem))
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.2", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.received = b""
        self.handshakes = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            try:
                with self.ctx.wrap_socket(raw, server_side=True) as tls:
                    self.handshakes += 1
                    tls.settimeout(2)
                    while True:
                        chunk = tls.recv(65536)
                        if not chunk:
                            break
                        self.received += chunk
                        if b"\r\n\r\n" in self.received:
                            tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                                        b"Content-Length: 2\r\nConnection: close\r\n\r\n{}")
                            break
            except (OSError, ssl.SSLError):
                continue

    def close(self):
        self.sock.close()


def test_the_pinned_certificate_is_trusted_and_no_other(cert, other_cert, monkeypatch):
    cert_pem, key_pem, pin = cert
    server = Recorder(cert_pem, key_pem)
    try:
        url = f"https://127.0.0.2:{server.port}"
        # Not pinned: a self-signed certificate is not trusted, and nothing is sent.
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(url, "pws_SECRET").health())
        assert "cannot verify" in e.value.message and P.TLS_PIN_ENV in e.value.message
        assert b"pws_SECRET" not in server.received and server.received == b""
        # Pinned to another certificate: the client stops inside the
        # handshake, before its last handshake message — so the server never
        # even completes one — and the request with the token is never written.
        monkeypatch.setenv(P.TLS_PIN_ENV, other_cert[2])
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(url, "pws_SECRET").health())
        assert "is not the one" in e.value.message and "sent nothing" in e.value.message
        assert server.received == b""
        # Pinned to this one, in any of the spellings an operator might paste.
        for spelling in (pin, pin.replace(":", "").lower(), f"sha256 Fingerprint={pin}"):
            monkeypatch.setenv(P.TLS_PIN_ENV, spelling)
            server.received = b""
            with pytest.raises(WorkstationError):
                run(WorkstationClient(url, "pws_SECRET").health())  # `{}` is not a workstation
            assert b"Authorization: Bearer pws_SECRET" in server.received
    finally:
        server.close()


def test_a_pin_that_is_not_a_fingerprint_is_said_not_ignored(monkeypatch, no_wire):
    monkeypatch.setenv(P.TLS_PIN_ENV, "not-a-fingerprint")
    with pytest.raises(WorkstationError) as e:
        run(WorkstationClient("https://127.0.0.2:7040", "pws_x").health())
    assert e.value.code == "bad_request" and P.TLS_PIN_ENV in e.value.message
    assert no_wire == []
    assert wc.normalise_pin("AB:" * 31 + "AB") == "ab" * 32
    assert wc.normalise_pin("ab" * 31) is None


class _Redirector(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/v1/health"):
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def test_a_redirect_is_not_followed():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(f"http://127.0.0.1:{httpd.server_address[1]}", "pws_x").health())
        assert "answered 302" in e.value.message
        assert [p for p, _ in _Redirector.hits] == ["/v1/health"]
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── the daemon's own side ────────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [
    ["--bind", "8.8.8.8"], ["--bind", "2606:4700:4700::1111"],
    ["--tls-cert", "a.pem"], ["--tls-key", "b.pem"], ["--backend", "cloud"],
])
def test_the_daemon_refuses_what_could_only_leak_or_mislead(argv):
    with pytest.raises(SystemExit) as e:
        cli.parse_args(argv)
    assert e.value.code == 2


def test_a_public_bind_with_tls_and_every_private_bind_are_allowed():
    assert cli.parse_args(["--bind", "8.8.8.8", "--tls-cert", "c", "--tls-key", "k"]).tls_cert == "c"
    for bind in ("0.0.0.0", "127.0.0.1", "10.0.0.5", "192.168.1.2", "::"):
        assert cli.parse_args(["--bind", bind]).bind == bind


@pytest.mark.parametrize("system,word,expected", [
    ("single", "none", "remote"), ("single", "docker", "remote"),
    ("ubuntu", "docker", "container"), ("ubuntu", "podman", "container"),
    ("ubuntu", "none", "remote"), ("ubuntu", "kvm", "remote"), ("ubuntu", "unknown", "remote"),
])
def test_what_a_daemon_says_it_is_comes_from_looking(system, word, expected, monkeypatch):
    monkeypatch.setattr(machine, "virtualization", lambda **k: word)
    monkeypatch.delenv(cli.BACKEND_ENV, raising=False)
    assert cli.parse_args(["--system", system]).backend == expected
    assert cli.parse_args(["--system", system, "--backend", "vm"]).backend == "vm"


@pytest.mark.parametrize("word,accel", [("kvm", "kvm"), ("qemu", "tcg"), ("none", None),
                                        ("docker", None), ("vmware", None)])
def test_the_machine_says_whether_it_is_emulated(word, accel):
    assert machine.facts(word) == {"virtualization": word, "accel": accel}


def test_virtualization_is_systemds_word_or_a_runtime_marker_or_unknown(tmp_path):
    assert machine.virtualization(detect=lambda: "kvm", root=tmp_path) == "kvm"
    assert machine.virtualization(detect=lambda: None, root=tmp_path) == "unknown"
    (tmp_path / ".dockerenv").write_text("")
    assert machine.virtualization(detect=lambda: None, root=tmp_path) == "docker"


def test_a_token_file_is_read_and_never_written(tmp_path):
    path = tmp_path / "token"
    path.write_text("pws_from-the-file\n")
    os.chmod(path, 0o400)
    before = path.stat()
    args = cli.parse_args(["--token-file", str(path), "--homes", str(tmp_path / "h"),
                           "--port", "0", "--pairing-dir", str(tmp_path / "pairing")])
    server, _system = cli.build(args)
    try:
        assert server.station.token == "pws_from-the-file"
        assert path.stat().st_mtime == before.st_mtime and stat.S_IMODE(path.stat().st_mode) == 0o400
        assert not (tmp_path / "pairing").exists(), "a pairing token was minted beside the file"
    finally:
        server.server_close()
    os.chmod(path, 0o600)  # The test owner can now replace its read-only fixture.
    path.write_text("")
    with pytest.raises(cli.WorkstationError) as e:
        cli.build(cli.parse_args(["--token-file", str(path), "--port", "0",
                                  "--homes", str(tmp_path / "h")]))
    assert "empty" in e.value.message


# ── the installer, and the whole remote path ─────────────────────────────────

def _install(tmp_path, *extra):
    out = subprocess.run(
        [sys.executable, str(ROOT / "workstation" / "install.py"), "--root", str(tmp_path),
         "--no-packages", "--no-start", "--address", "127.0.0.2", "--name", "127.0.0.2", *extra],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


def _env_lines(stdout: str) -> dict:
    found = {}
    for line in stdout.splitlines():
        m = re.match(r"^\s+([A-Z][A-Z0-9_]*)=(\S+)$", line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def test_the_installer_writes_a_token_a_certificate_and_a_unit_and_keeps_them(tmp_path):
    out = _install(tmp_path)
    lines = _env_lines(out)
    token_file = tmp_path / "etc/pantheon-workstation/token"
    cert_file = tmp_path / "etc/pantheon-workstation/tls/cert.pem"
    key_file = tmp_path / "etc/pantheon-workstation/tls/key.pem"
    token = token_file.read_text().strip()
    assert token.startswith(P.TOKEN_PREFIX)
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    der = ssl.PEM_cert_to_DER_cert(cert_file.read_text())
    assert lines == {
        "COMPOSE_FILE": "docker-compose.yml:docker/workstation-remote.yml",
        P.URL_ENV: "https://127.0.0.2:7040",
        P.TOKEN_ENV: token,
        P.TLS_PIN_ENV: install.fingerprint(cert_file.read_text()),
    }
    assert wc.normalise_pin(lines[P.TLS_PIN_ENV]) == hashlib.sha256(der).hexdigest()
    # The daemon and its skeleton went where the unit looks for them, the
    # skeleton a superset of this machine's own, and Firefox's policy is there.
    assert (tmp_path / "opt/pantheon-workstation/workstation/agentd.py").is_file()
    assert (tmp_path / "opt/pantheon-workstation/skel/.jwmrc").read_bytes() == \
        (ROOT / "workstation/skel/.jwmrc").read_bytes()
    assert json.loads((tmp_path / "etc/firefox/policies/policies.json").read_text()) == \
        json.loads((ROOT / "workstation/firefox/policies.json").read_text())
    unit = (tmp_path / "etc/systemd/system/pantheon-workstation.service").read_text()
    exec_line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    argv = shlex.split(exec_line.split("=", 1)[1])
    assert argv[1:3] == ["-m", "workstation"]
    assert cli.parse_args(argv[3:]).backend == "remote"
    assert argv[argv.index("--token-file") + 1] == "/etc/pantheon-workstation/token"
    assert argv[argv.index("--tls-cert") + 1] == "/etc/pantheon-workstation/tls/cert.pem"
    assert argv[argv.index("--skeleton") + 1] == "/opt/pantheon-workstation/skel"
    assert token not in unit, "the token is in the unit"
    # A second run keeps both, so Pantheon's copy of each stays right.
    again = _env_lines(_install(tmp_path))
    assert again == lines


def test_without_tls_the_lines_say_http_and_pin_nothing(tmp_path):
    lines = _env_lines(_install(tmp_path, "--no-tls"))
    assert lines[P.URL_ENV] == "http://127.0.0.2:7040" and P.TLS_PIN_ENV not in lines
    unit = (tmp_path / "etc/systemd/system/pantheon-workstation.service").read_text()
    assert "--tls-cert" not in unit
    assert not (tmp_path / "etc/pantheon-workstation/tls").exists()


def test_a_dry_run_says_everything_and_does_nothing(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "workstation" / "install.py"), "--root",
                          str(tmp_path), "--dry-run"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for step in ("provision.sh packages", "systemctl enable", "a new token", "the service",
                 "TLS certificate", "DRY RUN"):
        assert step in out.stdout, step
    assert list(tmp_path.iterdir()) == []


def test_uninstall_takes_the_service_and_keeps_the_homes(tmp_path):
    _install(tmp_path)
    (tmp_path / "home/pw-ann-12345678").mkdir(parents=True)
    ran = []
    plan = install.Plan(dry_run=False, root=tmp_path,
                        run=lambda argv, env=None: ran.append(argv) or
                        subprocess.CompletedProcess(argv, 0))
    install.uninstall(install.parser().parse_args(["--uninstall"]), plan)
    assert ["systemctl", "disable", "--now", service.UNIT_NAME] in ran
    assert not (tmp_path / "etc/systemd/system/pantheon-workstation.service").exists()
    assert not (tmp_path / "opt/pantheon-workstation").exists()
    assert not (tmp_path / "etc/pantheon-workstation").exists()
    assert (tmp_path / "home/pw-ann-12345678").is_dir()


def test_the_certificate_names_this_machine_and_not_loopback(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "ws1")
    monkeypatch.setattr(socket, "getfqdn", lambda: "ws1.lan")
    monkeypatch.setattr(install, "primary_address", lambda: "192.168.1.50")
    names = install.machine_names(["127.0.0.1", "localhost", "ws.example.org"])
    assert names == ["ws1", "ws1.lan", "192.168.1.50", "ws.example.org"]
    assert install.san(names) == "DNS:ws1,DNS:ws1.lan,IP:192.168.1.50,DNS:ws.example.org"


def _start_from_unit(tmp_path: Path):
    """What systemd would run, from the unit the installer wrote, with its
    paths under the test's root and the address the lines name."""
    unit = (tmp_path / "etc/systemd/system/pantheon-workstation.service").read_text()
    argv = shlex.split(next(ln for ln in unit.splitlines()
                            if ln.startswith("ExecStart=")).split("=", 1)[1])
    for i, a in enumerate(argv):
        if a.startswith("/etc/") or a.startswith("/opt/"):
            argv[i] = str(tmp_path / a.lstrip("/"))
    argv[0] = sys.executable
    argv[argv.index("--bind") + 1] = "127.0.0.2"
    argv[argv.index("--port") + 1] = "0"
    argv[argv.index("--system") + 1] = "single"  # no Unix accounts on the test machine
    argv += ["--homes", str(tmp_path / "home")]
    env = {k: v for k, v in os.environ.items() if k not in (P.TOKEN_ENV,)}
    proc = subprocess.Popen(argv, cwd=tmp_path / "opt/pantheon-workstation", env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = proc.stdout.readline()
    m = re.search(r"listening on 127\.0\.0\.2:(\d+).*TLS", line)
    assert m, line + proc.stdout.read() if proc.poll() is not None else line
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return proc, int(m.group(1))


@pytest.fixture
def pantheon_settings(tmp_path, monkeypatch):
    import src.constants
    import src.settings
    settings_file = tmp_path / "pantheon" / "settings.json"
    settings_file.parent.mkdir()
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", str(settings_file))
    # The install's admin, signed in (`D-2026-10-07-02` §2 — this was the
    # single-user owner, nobody, under `AUTH_ENABLED=false`).
    from tests.helpers.signed_in import signed_in
    signed_in(monkeypatch, tmp_path / "auth", members=())
    monkeypatch.setenv(P.PAIRING_DIR_ENV, str(tmp_path / "no-pairing"))
    src.settings._invalidate_caches()
    yield settings_file
    src.settings._invalidate_caches()


def test_the_printed_lines_reach_the_daemon_the_unit_starts_on_another_address(
        tmp_path, monkeypatch, pantheon_settings):
    """The remote path, end to end minus systemd: install, start what the
    unit says, put the printed lines in Pantheon's environment, switch it on —
    and the status route an admin opens says `up`, `remote`, and its home is
    looked at without being made."""
    machine_root = tmp_path / "machine"
    machine_root.mkdir()
    lines = _env_lines(_install(machine_root))
    proc, port = _start_from_unit(machine_root)
    try:
        url = lines[P.URL_ENV].replace(":7040", f":{port}")
        monkeypatch.setenv(P.URL_ENV, url)
        monkeypatch.setenv(P.TOKEN_ENV, lines[P.TOKEN_ENV])
        monkeypatch.setenv(P.TLS_PIN_ENV, lines[P.TLS_PIN_ENV])
        pantheon_settings.write_text(json.dumps({"workstation_enabled": True}))
        import src.settings
        src.settings._invalidate_caches()
        assert wc.resolve_base() == (url, wc.SOURCE_ENVIRONMENT)
        assert wc.resolve_token() == (lines[P.TOKEN_ENV], wc.SOURCE_ENVIRONMENT)
        client = wc.from_settings()
        health = run(client.health())
        assert (health["backend"], health["sudo"]) == ("remote", False)
        from src import workstation_access as wa
        from tests.helpers.signed_in import ADMIN
        status = run(wa.status_for(ADMIN, is_admin=True))
        assert status["state"] == wa.STATE_UP and status["daemon"]["backend"] == "remote"
        assert status["you"]["home_state"] == wa.HOME_NONE
        assert not (machine_root / "home").exists() or not any((machine_root / "home").iterdir())
        account = wa.account_of(ADMIN)
        r = run(client.exec(account, "echo hello from $HOSTNAME-less $PWD"))
        assert r["exit_code"] == 0 and str(machine_root / "home" / account) in r["stdout"]
        assert run(wa.status_for(ADMIN, is_admin=True))["you"]["home_state"] == wa.HOME_KEPT
        # The same address with the pin of some other certificate: refused.
        monkeypatch.setenv(P.TLS_PIN_ENV, "00" * 32)
        with pytest.raises(WorkstationError) as e:
            run(wc.from_settings().health())
        assert "is not the one" in e.value.message
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ── waiting for a machine to boot, only where machines boot ──────────────────

class _SlowEnsure(BaseHTTPRequestHandler):
    """A workstation whose `ensure` takes longer than the client's bound, as a
    VM host's does while it boots the person's machine."""
    backend = "vm"

    def _send(self, body):
        data = json.dumps(body).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up first, which is what some cases assert

    def do_GET(self):  # noqa: N802
        self._send({"ok": True, "agent": P.AGENT_NAME, "protocol": P.PROTOCOL_VERSION,
                    "backend": type(self).backend, "version": "1"})

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        import time
        time.sleep(1.5)
        self._send({"account": "x", "home": "/home/x", "created": True})

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("backend,waits", [("vm", True), ("container", False), ("remote", False)])
def test_only_a_backend_that_boots_machines_is_waited_for(backend, waits):
    handler = type("Slow", (_SlowEnsure,), {"backend": backend})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        c = WorkstationClient(f"http://127.0.0.1:{httpd.server_address[1]}", "pws_x", timeout=0.5)
        account = wc.account_for("ann")
        # Before `health` the client knows nothing, and waits nothing extra.
        with pytest.raises(WorkstationError):
            run(c.ensure(account))
        assert run(c.health())["backend"] == backend
        if waits:
            assert run(c.ensure(account))["created"] is True
        else:
            with pytest.raises(WorkstationError) as e:
                run(c.ensure(account))
            assert "did not answer" in e.value.message
    finally:
        httpd.shutdown()
        httpd.server_close()
