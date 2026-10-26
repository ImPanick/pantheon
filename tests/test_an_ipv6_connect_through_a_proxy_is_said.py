# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1024`: httpcore writes an IPv6 `CONNECT` authority without brackets, and
`docs/setup.md` says so — for exactly as long as it is true.

The request goes to a one-shot fake proxy on loopback that records the first
line it is sent and answers 502, so nothing leaves the machine. When httpcore
brackets the address (RFC 9110 §7.2), the first test fails and says to delete
the paragraph — the limitation stated in the guide is measured, not remembered.
"""
import pathlib
import socket
import threading

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETUP = ROOT / "docs" / "setup.md"
TARGET = "https://[fd00::5]:7040/"


def _connect_line(**client_kw) -> bytes:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(10)
    seen = []

    def serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            seen.append(conn.recv(4096).split(b"\r\n", 1)[0])
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    proxy = f"http://127.0.0.1:{srv.getsockname()[1]}"
    try:
        with httpx.Client(proxy=proxy, trust_env=False, **client_kw) as client:
            try:
                client.get(TARGET, timeout=5)
            except httpx.ProxyError:
                pass
    finally:
        t.join(5)
        srv.close()
    assert seen, "the fake proxy was never asked"
    return seen[0]


def test_the_connect_line_is_still_unbracketed_and_the_guide_says_so():
    line = _connect_line()
    if line == b"CONNECT [fd00::5]:7040 HTTP/1.1":
        raise AssertionError(
            "httpcore now brackets an IPv6 CONNECT authority: delete the "
            "'Behind an outbound proxy: exempt IPv6 destinations' paragraph from "
            "docs/setup.md, and this test with it (B1024).")
    assert line == b"CONNECT fd00::5:7040 HTTP/1.1", line
    guide = SETUP.read_text(encoding="utf-8")
    assert "CONNECT fd00::5:7040 HTTP/1.1" in guide, \
        "docs/setup.md must say what an IPv6 CONNECT through a proxy looks like (B1024)"


def test_the_guides_remedy_works_a_single_ipv6_address_in_no_proxy_goes_direct(monkeypatch):
    """The paragraph's advice — list the address in `NO_PROXY` — is driven
    through httpx's own environment reader, without sending anything."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,fd00::5")
    for name in ("https_proxy", "no_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    with httpx.Client() as client:
        direct = client._transport_for_url(httpx.URL(TARGET))
        proxied = client._transport_for_url(httpx.URL("https://[fd00::6]:7040/"))
        assert direct is client._transport, "an IPv6 address in NO_PROXY must go direct"
        assert proxied is not client._transport, "an address not in NO_PROXY uses the proxy"
