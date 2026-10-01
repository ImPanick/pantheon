# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B982`. httpx reads names and single addresses in `NO_PROXY`, not ranges:
with `HTTPS_PROXY` set and `NO_PROXY=…,10.0.0.0/8,192.168.0.0/16`, an
`https://` call to `10.1.2.3` went to the proxy. Now a destination goes direct
when a proxy is configured for its scheme and `NO_PROXY` puts its address in a
range — `src.paced_http.direct_mounts`, used by `paced_http`'s own clients and
by the workstation client.

Driven for real: a proxy that writes down every connection it is handed and
forwards none, the real workstation daemon on another loopback address (over
plain http, and over TLS with the installer's certificate pinned), and
Pantheon's real client and `paced_http` — so "went direct" means the daemon
answered and the proxy heard nothing, and the control case (no range) means the
proxy heard the request. Nothing reads a source file (`Law 20`).
"""
from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path

import httpx
import pytest

from src import paced_http
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from workstation import install
from workstation import protocol as P
from workstation.agentd import SingleUserSystem, make_server, server_context

TOKEN = "pws_b982-the-token-for-the-workstation"
# No IPv6 range here: httpx 0.28.1 turns one into a URL pattern it cannot
# parse, and every client it then builds raises `InvalidURL` (filed, `B982`'s
# handoff). `direct_mounts` reads one; `test_an_ipv6_range_is_read_too`.
RANGES = "localhost,10.0.0.0/8,127.0.0.0/8,192.168.0.0/16"


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """A proxy that forwards nothing: it notes the first line of every
    connection it is handed and answers `502`."""

    def __init__(self):
        self.lines = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                data = b""
                try:
                    while b"\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    self.lines.append(data.split(b"\r\n", 1)[0].decode("latin-1"))
                    conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n"
                                 b"Connection: close\r\n\r\n")
                except OSError:
                    pass  # the client hung up first: what it sent is already noted

    def close(self):
        # `B1016`: wake the `accept()` before closing. A bare `close()` from
        # another thread leaves that thread blocked in `accept()` on the fd
        # NUMBER, which the next socket the process opens reuses — the next
        # test's workstation daemon — so this proxy went on answering `502` to
        # connections meant for it (measured: `config` answered "The
        # workstation answered 502." in the test after this file).
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # not connected is fine for a listening socket on some kernels
        self.sock.close()
        self.thread.join(timeout=5)


@pytest.fixture
def proxy(monkeypatch):
    rec = Recorder()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, rec.url)
    for name in ("ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, RANGES)
    monkeypatch.delenv(P.TLS_PIN_ENV, raising=False)
    yield rec
    rec.close()


def _daemon(tmp_path, *, tls=None):
    system = SingleUserSystem(tmp_path / "homes", backend="remote")
    server = make_server(system, TOKEN, bind="127.0.0.2", port=0, tls=tls)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return server, server.server_address[1]


@pytest.fixture
def plain(tmp_path):
    server, port = _daemon(tmp_path)
    yield port
    server.shutdown()
    server.server_close()


@pytest.fixture
def tls(tmp_path):
    plan = install.Plan(dry_run=False, root=tmp_path / "install-root")
    pin = install.make_certificate(plan, ["127.0.0.2", "ws.lan"])
    ctx = server_context(plan.path(install.TLS_DIR / "cert.pem"),
                         plan.path(install.TLS_DIR / "key.pem"))
    server, port = _daemon(tmp_path, tls=ctx)
    yield port, pin
    server.shutdown()
    server.server_close()


# ── the rule, as `direct_mounts` says it ─────────────────────────────────────

def test_the_two_addresses_in_the_row_go_direct(proxy):
    """The row's `Verify:`, in httpx's own routing: with that environment, the
    client a call is made with sends these two to no proxy."""
    for url, host in (("https://10.1.2.3:7040", "10.1.2.3"), ("https://192.168.1.50", "192.168.1.50")):
        mounts = paced_http.direct_mounts(url)
        assert mounts == {f"all://{host}": None}
        with httpx.Client() as before, httpx.Client(mounts=mounts) as after:
            assert before._transport_for_url(httpx.URL(url)) is not before._transport, \
                "premise: httpx alone sends it to the proxy"
            assert after._transport_for_url(httpx.URL(url)) is after._transport


@pytest.mark.parametrize("url,addresses,expected", [
    ("https://8.8.8.8", (), {}),                                     # in no range
    ("https://ws.lan:7040", (), {}),                                 # a name, not looked up
    ("https://ws.lan:7040", ("192.168.1.9", "10.0.0.4"), {"all://ws.lan": None}),
    ("https://ws.lan:7040", ("192.168.1.9", "8.8.8.8"), {}),         # every address, or none
    ("https://ws.lan:7040", ("not-an-address",), {}),
])
def test_what_goes_direct_and_what_the_environment_keeps(proxy, url, addresses, expected):
    assert paced_http.direct_mounts(url, addresses=addresses) == expected


def test_an_ipv6_range_is_read_too(proxy, monkeypatch):
    # `::/96` holds every IPv4 address's number; an IPv4 address is still not in it.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "fd00::/8,::/96")
    assert paced_http.direct_mounts("https://[fd00::5]:7040") == {"all://[fd00::5]": None}
    assert paced_http.direct_mounts("https://10.1.2.3") == {}, "a v4 address is in no v6 range"


def test_nothing_changes_without_a_proxy_or_a_range(monkeypatch, proxy):
    monkeypatch.setenv("NO_PROXY", "localhost,10.0.0.5,not/a-range")
    monkeypatch.setenv("no_proxy", "localhost,10.0.0.5,not/a-range")
    assert paced_http.no_proxy_ranges() == ()
    assert paced_http.direct_mounts("https://10.0.0.5") == {}
    monkeypatch.setenv("NO_PROXY", RANGES)
    monkeypatch.setenv("no_proxy", RANGES)
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name)
    assert paced_http.direct_mounts("https://10.1.2.3") == {}, "no proxy for https: nothing to skip"
    assert paced_http.direct_mounts("http://10.1.2.3") == {"all://10.1.2.3": None}


# ── the workstation, reached for real ────────────────────────────────────────

def test_a_workstation_over_https_in_a_named_range_is_reached_direct(proxy, tls, monkeypatch):
    port, pin = tls
    monkeypatch.setenv(P.TLS_PIN_ENV, pin)
    c = WorkstationClient(f"https://127.0.0.2:{port}", TOKEN)
    assert run(c.health())["agent"] == P.AGENT_NAME
    ann = account_for("ann")
    run(c.ensure(ann))
    seen = []
    out = run(c.exec(ann, "echo streamed", on_output=lambda k, d: seen.append(d)))
    assert out["exit_code"] == 0 and "streamed" in "".join(seen)
    assert proxy.lines == [], "the proxy was handed the workstation's connection"


def test_a_workstation_over_plain_http_in_a_named_range_is_reached_direct(proxy, plain):
    c = WorkstationClient(f"http://127.0.0.2:{plain}", TOKEN)
    assert run(c.health())["agent"] == P.AGENT_NAME
    assert run(c.exec(account_for("ann"), "echo hi"))["stdout"].strip() == "hi"
    assert proxy.lines == []


def test_a_name_goes_direct_when_every_address_is_in_a_range(proxy, tls, monkeypatch):
    port, pin = tls
    monkeypatch.setenv(P.TLS_PIN_ENV, pin)
    real = socket.getaddrinfo

    def lookup(host, *a, **k):
        if host in ("ws.lan", b"ws.lan"):  # anyio asks in bytes
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.2", a[0] if a else 0))]
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    assert run(WorkstationClient(f"https://ws.lan:{port}", TOKEN).health())["agent"] == P.AGENT_NAME
    assert proxy.lines == []


def test_without_a_range_the_environment_still_decides(proxy, tls, monkeypatch):
    """The control: nothing here decides on its own that a private address
    skips the operator's proxy — and the proxy in these tests is real."""
    port, pin = tls
    monkeypatch.setenv(P.TLS_PIN_ENV, pin)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "localhost")
    with pytest.raises(WorkstationError) as e:
        run(WorkstationClient(f"https://127.0.0.2:{port}", TOKEN).health())
    assert e.value.code == "unavailable"
    assert proxy.lines == [f"CONNECT 127.0.0.2:{port} HTTP/1.1"]


# ── `paced_http`'s own client: direct, and still paced ───────────────────────

def test_paced_http_goes_direct_and_is_still_paced(proxy, plain, monkeypatch):
    from src.rate_limiter import outbound
    paced = []

    async def acquire_async(host, **k):
        paced.append(host)
        return 0.0

    monkeypatch.setattr(outbound, "acquire_async", acquire_async)
    monkeypatch.setattr(outbound, "acquire", lambda host, **k: paced.append(host) or 0.0)
    url = f"http://127.0.0.2:{plain}{P.ROUTES['health'][1]}"
    assert run(paced_http.get(url)).json()["agent"] == P.AGENT_NAME
    assert paced_http.get_sync(url).json()["agent"] == P.AGENT_NAME
    assert paced == ["127.0.0.2", "127.0.0.2"]
    assert proxy.lines == []
