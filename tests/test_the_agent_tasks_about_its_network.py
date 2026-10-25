# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P16-20` (`D-2026-10-25-02`), trimmed by `D-2026-10-25-03` — the agent can
say what network the workstation is on and whether it can reach a host. Nothing
more.

The owner, 2026-10-25: *"literally just a 'what's around me' thing"* —
connectivity across their own networks. So:

  * a `network` tool with two actions — `list` (interfaces and declared
    networks) and `reach` (one host, one port: connected, refused, or no
    answer, and whether the route went through the gateway);
  * no range action and no port list: one connection per call;
  * a network marked **untrusted** is listed but never connected to — by this
    tool (checked on the server, and again in the workstation after the name
    resolves there) or by a page fetch;
  * server-side fetches reach the LAN and tailnet when `agent_lan_reach` is on,
    never loopback or cloud metadata, and the tool is off when it is off.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from src.agent_tools import network_tools as NT
from workstation import netcheck as NC
from workstation import protocol as P


# ── the daemon check, stdlib, against this machine's loopback ─────────────────

def _listening():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def test_reach_says_connected_when_something_listens():
    srv, port = _listening()
    try:
        got = NC.reach({"host": "127.0.0.1", "port": port})
        assert got["result"] == "connected" and got["address"] == "127.0.0.1"
    finally:
        srv.close()


def test_reach_says_refused_when_nothing_listens():
    srv, port = _listening()
    srv.close()   # the port is now free; a connect is refused by the kernel
    got = NC.reach({"host": "127.0.0.1", "port": port})
    assert got["result"] == "refused"


def test_reach_is_one_host_and_one_port():
    with pytest.raises(NC.NetCheckError):
        NC.reach({"host": "10.0.0.0/24", "port": 80})
    with pytest.raises(NC.NetCheckError):
        NC.reach({"host": "10.0.0.5", "port": [22, 80]})
    with pytest.raises(NC.NetCheckError):
        NC.reach({"host": "10.0.0.5"})


def test_the_daemon_refuses_a_name_that_resolves_into_a_denied_range():
    """A name not listed in an untrusted network, but resolving into one in the
    workstation, is refused there — before a packet leaves."""
    srv, port = _listening()
    try:
        with pytest.raises(NC.NetCheckError) as e:
            NC.reach({"host": "localhost", "port": port,
                      "deny": [{"name": "guest", "cidrs": ["127.0.0.0/8", "::1/128"]}]})
        assert e.value.code == "forbidden" and "guest" in e.value.message
    finally:
        srv.close()


def test_a_malformed_deny_list_is_refused_not_ignored():
    with pytest.raises(NC.NetCheckError):
        NC.reach({"host": "127.0.0.1", "port": 80, "deny": [{"name": "x", "cidrs": ["nope"]}]})


def test_the_route_through_the_gateway_is_named():
    own = [ipaddress.ip_network("192.168.50.0/24")]
    assert NC._via_gateway(ipaddress.ip_address("192.168.50.9"), own) is False
    assert NC._via_gateway(ipaddress.ip_address("10.9.9.9"), own) is True
    text = NT.reach_text({"host": "10.9.9.9", "port": 443, "result": "no answer",
                          "timeout_ms": 3000, "via_gateway": True})
    assert "gateway/firewall" in text and "first place to look" in text


def test_the_protocol_has_no_range_or_port_list_action():
    assert P.NETWORK_ACTIONS == ("interfaces", "reach")
    assert not hasattr(P, "NET_SCAN_MAX_HOSTS")
    assert NT.ACTIONS == ("list", "reach")


def test_interfaces_are_honest_when_ip_is_missing(monkeypatch):
    monkeypatch.setattr(NC.shutil, "which", lambda name: None)
    got = NC.act("interfaces", {})
    assert got["interfaces"] == [] and got["ip_available"] is False


# ── the tool: parsing, scope, trust ──────────────────────────────────────────

@pytest.mark.parametrize("line, host, port", [
    ("reach 192.168.1.10 443", "192.168.1.10", 443),
    ("reach 192.168.1.10:443", "192.168.1.10", 443),
    ("reach nas.lan 5000", "nas.lan", 5000),
    ("reach [fd00::5]:22", "fd00::5", 22),
    ("reach fd00::5 22", "fd00::5", 22),
])
def test_the_line_form_parses(line, host, port):
    a, err = NT.parse_args(line)
    assert err is None and a == {"action": "reach", "host": host, "port": port}


def test_parse_refuses_what_the_tool_no_longer_does():
    assert NT.parse_args("list")[0]["action"] == "list"
    assert NT.parse_args({"action": "scan", "target": "10.0.0.0/24"})[1]
    assert NT.parse_args({"action": "ports", "host": "10.0.0.5"})[1]
    assert "range" in NT.parse_args({"action": "reach", "host": "10.0.0.0/24", "port": 80})[1]
    assert NT.parse_args({"action": "reach", "host": "10.0.0.5"})[1], "reach needs a port"
    assert NT.describe({"action": "reach", "host": "h", "port": 22}) == "reach h:22"


def _declare(monkeypatch, nets):
    from src import networks as N
    monkeypatch.setattr(N, "_raw_networks", lambda: nets)


def test_an_untrusted_network_is_never_reached(monkeypatch):
    _declare(monkeypatch, [{"name": "guest", "cidrs": ["192.168.9.0/24"], "trust": "untrusted"},
                           {"name": "lab", "cidrs": ["10.4.0.0/24"], "trust": "trusted"}])
    refusal = NT._refusal("192.168.9.10")
    assert refusal and "untrusted" in refusal and "guest" in refusal
    assert NT._refusal("10.4.0.5") is None
    from src import networks as N
    assert N.untrusted_ranges() == [{"name": "guest", "cidrs": ["192.168.9.0/24"]}]


def test_a_run_scoped_to_one_network_cannot_reach_another(monkeypatch):
    from src import networks as N
    _declare(monkeypatch, [{"name": "lab", "cidrs": ["10.4.0.0/24"], "trust": "trusted"},
                           {"name": "prod", "cidrs": ["10.9.0.0/24"], "trust": "trusted"}])
    with N.scoped_to(["lab"]):
        assert NT._refusal("10.4.0.5") is None
        refusal = NT._refusal("10.9.0.5")
        assert refusal and "lab" in refusal
    assert NT._refusal("10.9.0.5") is None


def test_the_tool_is_off_when_lan_reach_is_off(monkeypatch):
    import asyncio
    monkeypatch.setattr(NT, "lan_reach_on", lambda: False)
    out = asyncio.new_event_loop().run_until_complete(
        NT.run_network({"action": "reach", "host": "10.0.0.5", "port": 80}, owner="ada"))
    assert out["exit_code"] == 1 and "turned off" in out["error"]


# ── capabilities: list looks, reach reaches ──────────────────────────────────

def test_the_gate_treats_list_as_looking_and_reach_as_reaching():
    from src.tool_capabilities import capabilities_for_action, ToolEffect
    looked = capabilities_for_action("network", "list")
    reached = capabilities_for_action("network", '{"action": "reach", "host": "10.0.0.5", "port": 80}')
    line = capabilities_for_action("network", "reach 10.0.0.5 80")
    assert ToolEffect.NETWORK_EGRESS not in looked.effects
    assert ToolEffect.NETWORK_EGRESS in reached.effects
    assert ToolEffect.NETWORK_EGRESS in line.effects


def test_a_tainted_run_asks_before_a_reach_but_not_before_a_list():
    from src.tool_capabilities import ToolRunSecurityContext
    ctx = ToolRunSecurityContext(external_untrusted_context_seen=True)
    assert ctx.decision_for("network", "list").allowed is True
    assert ctx.decision_for("network", '{"action":"reach","host":"10.0.0.5","port":80}').allowed is False


# ── the LAN fetch, gated and floored; untrusted refused ──────────────────────

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


def test_a_fetch_into_an_untrusted_network_is_refused(monkeypatch):
    import httpx
    import src.outbound_fetch as of
    monkeypatch.setattr(of, "lan_allowed", lambda: True)
    _declare(monkeypatch, [{"name": "guest", "cidrs": ["192.168.9.0/24"], "trust": "untrusted"}])
    with pytest.raises(httpx.RequestError) as e:
        of._resolve_public_ips("http://192.168.9.20/")
    assert "untrusted" in str(e.value)
    # by name, where the name resolves into the untrusted range
    with pytest.raises(httpx.RequestError):
        of._resolve_public_ips("http://printer.lan/",
                               resolver=lambda h: [ipaddress.ip_address("192.168.9.30")])
    assert of._public_http_url("http://192.168.9.20/") is False
    # a trusted LAN address is fine
    assert of._resolve_public_ips("http://192.168.1.20/") == [ipaddress.ip_address("192.168.1.20")]


def test_the_fetch_setting_defaults_on_and_reads_the_store(monkeypatch):
    import importlib
    import sys
    import src.outbound_fetch as of
    importlib.import_module("src.settings")
    # The module `_lan_reach_on` imports from — whatever sys.modules holds now,
    # since other tests in a full run swap settings modules around.
    settings = sys.modules["src.settings"]
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
    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "network")
    assert schema["function"]["parameters"]["properties"]["action"]["enum"] == ["list", "reach"]
    assert "network" in BUILTIN_TOOL_DESCRIPTIONS and "network" in loop.TOOL_SECTIONS
    assert set(_ACTION_CAPABILITIES["network"]) == {"list", "reach"}
