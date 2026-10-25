# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P16-20` (`D-2026-10-25-02`) — the agent tasks about the operator's own
networks, and the hard gates loosen for exactly that.

The owner, 2026-10-25: *"Having it able to act and be agentic, so it needs its
'hard gates' loosened a bit. This is authorization for just that. The user and
its agents should be able to task about their network… subnets and all."*

Four things, each pinned here:

  * a `network` tool — list the interfaces and declared networks, sweep a range
    for live hosts, probe a host's ports — bounded to a /22, scoped to the
    person's declared networks, and list-only on an untrusted one;
  * the daemon scanner is a TCP connect (no raw-packet capability), driven here
    against this machine's own loopback;
  * server-side fetches reach the LAN and tailnet when `agent_lan_reach` is on,
    and never loopback or cloud metadata;
  * the tool and the LAN fetch are off when `agent_lan_reach` is off.

Measured before this file (on `b71e1b8`): the agent could not scan a subnet,
and `web_fetch` refused every private address — a router page by URL was a
"Blocked non-public URL".
"""

from __future__ import annotations

import ipaddress

import pytest

from src.agent_tools import network_tools as NT
from workstation import netscan as NS
from workstation import protocol as P


# ── the daemon scanner, stdlib, against this machine's loopback ───────────────

def test_the_scanner_finds_a_listening_port_on_loopback():
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        got = NS.ports({"host": "127.0.0.1", "ports": [port, port + 1 if port < 65535 else port - 1]})
        assert got["reachable"] is True
        assert any(p["port"] == port for p in got["open"]), "the listening port is open"
        scanned = NS.scan({"target": "127.0.0.1", "ports": [port]})
        assert scanned["up"] == 1 and scanned["hosts"][0]["ip"] == "127.0.0.1"
        assert scanned["hosts"][0]["open"][0]["port"] == port
    finally:
        srv.close()


def test_a_sweep_is_bounded_to_a_slash_22():
    assert P.NET_SCAN_MAX_HOSTS == 1024
    # /22 is 1024 addresses — allowed; /21 is 2048 — refused with a sentence.
    ok, _ = NS._addresses_of("10.1.0.0/22")
    assert len(ok) <= P.NET_SCAN_MAX_HOSTS
    with pytest.raises(NS.NetScanError) as e:
        NS._addresses_of("10.1.0.0/21")
    assert "at most 1024" in e.value.message and "/22" in e.value.message


def test_the_scanner_needs_no_raw_packet_capability():
    # Liveness is a TCP connect; a refused connect still proves a host is there.
    assert NS._probe("127.0.0.1", 0, 0.3) in ("refused", "filtered")
    # It never asks the kernel for a raw socket — the whole point of `connect`.
    import inspect
    src = inspect.getsource(NS)
    assert "SOCK_RAW" not in src and "AF_PACKET" not in src


def test_interfaces_are_honest_when_ip_is_missing(monkeypatch):
    monkeypatch.setattr(NS.shutil, "which", lambda name: None)
    got = NS.act("interfaces", {})
    assert got["interfaces"] == [] and got["ip_available"] is False


# ── the tool: parsing, scope, trust ──────────────────────────────────────────

def test_parse_and_describe():
    a, err = NT.parse_args("scan 192.168.1.0/24")
    assert err is None and a == {"action": "scan", "target": "192.168.1.0/24"}
    assert NT.describe(a) == "scan 192.168.1.0/24"
    assert NT.parse_args({"action": "ports"})[1], "ports needs a host"
    assert NT.parse_args("list")[0]["action"] == "list"
    a2, err2 = NT.parse_args({"action": "scan", "target": "10.0.0.0/24", "ports": [22, 80]})
    assert err2 is None and a2["ports"] == [22, 80]


def _declare(monkeypatch, nets):
    from src import networks as N
    monkeypatch.setattr(N, "_raw_networks", lambda: nets)


def test_an_untrusted_network_is_list_only(monkeypatch):
    _declare(monkeypatch, [{"name": "guest", "cidrs": ["192.168.9.0/24"], "trust": "untrusted"},
                           {"name": "lab", "cidrs": ["10.4.0.0/24"], "trust": "trusted"}])
    # A sweep of the untrusted net is refused with a sentence; a probe of one of
    # its hosts, and any scan of the trusted net, is fine.
    assert "untrusted" in (NT._scope_refusal("192.168.9.0/24", "scan") or "")
    assert NT._scope_refusal("192.168.9.10", "ports") is None
    assert NT._scope_refusal("10.4.0.0/24", "scan") is None


def test_a_run_scoped_to_one_network_cannot_scan_another(monkeypatch):
    from src import networks as N
    _declare(monkeypatch, [{"name": "lab", "cidrs": ["10.4.0.0/24"], "trust": "trusted"},
                           {"name": "prod", "cidrs": ["10.9.0.0/24"], "trust": "trusted"}])
    with N.scoped_to(["lab"]):
        assert NT._scope_refusal("10.4.0.0/24", "scan") is None
        refusal = NT._scope_refusal("10.9.0.0/24", "scan")
        assert refusal and "lab" in refusal
    # No scope in force (the shipped state): anything declared-or-not is reachable.
    assert NT._scope_refusal("10.9.0.0/24", "scan") is None


def test_the_tool_is_off_when_lan_reach_is_off(monkeypatch):
    import asyncio
    monkeypatch.setattr(NT, "lan_reach_on", lambda: False)
    out = asyncio.get_event_loop().run_until_complete(
        NT.run_network({"action": "scan", "target": "10.0.0.0/24"}, owner="ada"))
    assert out["exit_code"] == 1 and "turned off" in out["error"]


# ── capabilities: list looks, scan/ports reach ───────────────────────────────

def test_the_gate_treats_list_as_looking_and_a_scan_as_reaching():
    from src.tool_capabilities import capabilities_for_action, ToolEffect
    looked = capabilities_for_action("network", "list")
    reached = capabilities_for_action("network", '{"action": "scan", "target": "10.0.0.0/24"}')
    assert ToolEffect.NETWORK_EGRESS not in looked.effects, "listing is local, looking"
    assert ToolEffect.NETWORK_EGRESS in reached.effects, "a scan reaches out"


def test_a_tainted_run_asks_before_a_scan_but_not_before_a_list():
    from src.tool_capabilities import ToolRunSecurityContext
    ctx = ToolRunSecurityContext(external_untrusted_context_seen=True)
    assert ctx.decision_for("network", "list").allowed is True
    assert ctx.decision_for("network", '{"action":"scan","target":"10.0.0.0/24"}').allowed is False


# ── the LAN fetch loosening, gated and floored ───────────────────────────────

@pytest.mark.parametrize("addr", ["10.0.0.5", "172.16.0.1", "192.168.1.1", "100.64.0.1", "fc00::1"])
def test_the_lan_is_reachable_when_reach_is_on(addr):
    import src.outbound_fetch as of
    assert of._is_private_address(ipaddress.ip_address(addr), allow_lan=True) is False
    assert of._is_private_address(ipaddress.ip_address(addr), allow_lan=False) is True


@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "169.254.169.254", "fe80::1", "224.0.0.1", "0.0.0.0"])
def test_loopback_and_metadata_are_refused_whatever_the_setting(addr):
    import src.outbound_fetch as of
    assert of._is_private_address(ipaddress.ip_address(addr), allow_lan=True) is True
    assert of._is_private_address(ipaddress.ip_address(addr), allow_lan=False) is True


def test_the_fetch_setting_defaults_on_and_reads_the_store(monkeypatch):
    import src.outbound_fetch as of
    monkeypatch.setattr(of, "get_setting", lambda k, d=None: True, raising=False)
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: True)
    assert of._lan_reach_on() is True
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: False)
    assert of._lan_reach_on() is False


# ── it is registered everywhere a tool must be ───────────────────────────────

def test_the_tool_is_wired_through_every_surface():
    from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_capabilities import _ACTION_CAPABILITIES
    import src.agent_loop as loop
    assert "network" in TOOL_HANDLERS and "network" in TOOL_TAGS
    assert any(s["function"]["name"] == "network" for s in FUNCTION_TOOL_SCHEMAS)
    assert "network" in BUILTIN_TOOL_DESCRIPTIONS and "network" in loop.TOOL_SECTIONS
    assert set(_ACTION_CAPABILITIES["network"]) == {"list", "scan", "ports"}
