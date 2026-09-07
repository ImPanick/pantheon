# SPDX-License-Identifier: AGPL-3.0-or-later
"""`Law 16`, enforced by a tripwire rather than by reading.

Every finding in `P16` was found by a person reading code. That works once and
does not hold: the next convenience default will look as reasonable as
`npx -y @playwright/mcp@latest` did, and its comment will explain the choice
just as plainly. What holds is a test that makes the machine try.

This installs a socket guard that allows loopback, the docker host alias and
private/link-local ranges, and raises on anything else. Then it does the things
a fresh install does before a user has configured anything, and asserts nothing
tried to leave the box.

Deliberately NOT mocked at the library level. Guarding `httpx` would miss
`urllib`, guarding both would miss `subprocess` -> `npx`, and the npm fetch was
the worst offender. The guard sits at `socket.socket.connect`, which every one
of them reaches eventually.
"""
import ipaddress
import socket
import sys

import pytest


class EgressAttempted(AssertionError):
    """Something tried to leave the machine on a fresh install."""


def _is_local(host: str) -> bool:
    if not host:
        return True
    if host in ("localhost", "host.docker.internal", "::1", "0.0.0.0", ""):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A name we could not resolve without a lookup. Resolving it here would
        # itself be egress, so treat an unrecognised name as off-box.
        return False
    # `not is_global` rather than an enumeration of private ranges. The first
    # version listed loopback/private/link-local and called Tailscale egress:
    # tailnet addresses live in 100.64.0.0/10, which is RFC 6598 shared space,
    # and `is_private` is False for it. That would have made this guard fire on
    # the product doing its actual job -- reaching a model server on the LAN or
    # over Tailscale -- which is the failure mode a strict guard has.
    return not ip.is_global


@pytest.fixture
def no_egress(monkeypatch):
    """Raise on any connect() to an address outside this machine or its LAN."""
    attempts = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(sock, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else str(address)
        if not _is_local(str(host)):
            attempts.append(str(host))
            raise EgressAttempted(f"connect() to {host!r}")
        return real_connect(sock, address, *a, **k)

    def guard_ex(sock, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else str(address)
        if not _is_local(str(host)):
            attempts.append(str(host))
            raise EgressAttempted(f"connect_ex() to {host!r}")
        return real_connect_ex(sock, address, *a, **k)

    def guard_dns(host, *a, **k):
        # A DNS lookup for an off-box name is itself a request leaving the
        # machine, and it is the step that precedes every one of these.
        if not _is_local(str(host)):
            attempts.append(f"dns:{host}")
            raise EgressAttempted(f"getaddrinfo({host!r})")
        return real_getaddrinfo(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guard_dns)
    return attempts


def test_the_guard_actually_fires(no_egress):
    """A tripwire that cannot trip is decoration. Prove it before trusting it."""
    with pytest.raises(EgressAttempted):
        socket.create_connection(("example.com", 80), timeout=0.1)
    assert no_egress


# The two tests below exist because a mutation run showed the one above cannot
# tell which layer stopped the connection. Blunt the DNS guard and the connect
# guard catches it; blunt the connect guard and DNS catches it; only blunting
# both goes red. That is defence in depth working exactly as intended -- and it
# means the combined test cannot prove either half is alive. So each is exercised
# on a path the other cannot reach.

def test_the_connect_guard_works_without_any_dns(no_egress):
    """Only connect() can stop a raw socket, so this proves that half alone.

    Note `socket.create_connection` is deliberately not used: it calls
    `getaddrinfo` even for a literal IP address, to normalise it into an
    addrinfo tuple -- so the DNS guard fires first and the connect guard is
    never reached. Which is the exact confusion this test exists to remove.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.1)
    try:
        with pytest.raises(EgressAttempted):
            sock.connect(("8.8.8.8", 53))
    finally:
        sock.close()
    assert no_egress == ["8.8.8.8"]


def test_the_dns_guard_works_without_any_connect(no_egress):
    """Resolving alone is already a request leaving the machine.

    It is also the step that precedes every other kind of egress, which is why
    it is guarded separately rather than trusted to the connect that follows.
    """
    with pytest.raises(EgressAttempted):
        socket.getaddrinfo("registry.npmjs.org", 443)
    assert no_egress == ["dns:registry.npmjs.org"]


def test_the_guard_permits_the_local_network(no_egress):
    """It must not be so strict that it bans the product's actual job."""
    for host in ("127.0.0.1", "localhost", "192.168.1.50", "10.0.0.4", "100.64.0.1"):
        assert _is_local(host), f"{host} should be reachable on a self-hosted product"
    for host in ("huggingface.co", "8.8.8.8", "registry.npmjs.org", "1.1.1.1"):
        assert not _is_local(host), f"{host} should count as egress"


def test_importing_the_settings_layer_reaches_nothing(no_egress):
    from src.settings import DEFAULT_SETTINGS, load_settings

    load_settings()
    assert DEFAULT_SETTINGS
    assert no_egress == []


def test_building_the_builtin_mcp_registry_reaches_nothing(no_egress, monkeypatch):
    """The npm fetch lived here, three seconds after every boot."""
    monkeypatch.delenv("PANTHEON_BROWSER_MCP_REQUIRE_CACHE", raising=False)
    sys.modules.pop("src.builtin_mcp", None)
    import importlib

    mod = importlib.import_module("src.builtin_mcp")
    assert mod.BROWSER_MCP_REQUIRE_CACHE is True
    assert no_egress == []


def test_the_bundled_skill_library_loads_with_no_network(no_egress, tmp_path):
    """286 skills, offline. The whole point of vendoring them."""
    from services.memory.skills import SkillsManager

    skills = SkillsManager(str(tmp_path)).load_all()
    assert len(skills) >= 250
    assert no_egress == []


def test_the_embedding_lanes_reach_nothing_without_permission(no_egress, monkeypatch):
    """The first chat message used to fetch ~90MB from HuggingFace here."""
    from src import embedding_lanes as el

    monkeypatch.setattr(el, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(el, "model_download_allowed", lambda: False)
    with pytest.raises(el.ModelDownloadNotPermitted):
        el._build_fastembed_client()
    assert no_egress == []


def test_the_search_defaults_reach_nothing(no_egress):
    """An empty fallback chain means a failed local provider stops there."""
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["search_fallback_chain"] == []
    assert no_egress == []


def test_the_outbound_limiter_itself_reaches_nothing(no_egress):
    from src.rate_limiter import outbound

    outbound.acquire("example.test")
    outbound.observe("example.test", 200, {})
    assert no_egress == []
