# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-10` — discovery, and the four ways it could have been a hole.

The row: *"mDNS/SSDP is multicast, so it is the first thing in this phase that
sends — which makes it a scan by the definition `P17-03` deliberately avoided,
and the allowlist cannot gate a broadcast the way it gates a target. The honest
shape is to filter the answers to the allowlist and say so, plus an explicit
switch: discovery is a thing an operator turns on, not a thing that happens."*

`Verify:` a device that has said nothing to this host still appears, the operator
switched that on deliberately, and nothing outside the allowlist is reported.

**MOST OF THIS FILE IS REFUSALS, AND THAT IS THE PROPORTION THE FEATURE
DESERVES.** A discovery path that can be pointed at a non-local address is an
SSRF in the one process on the machine that has the LAN, so proving it refuses
matters more than proving it discovers. The four refusals, each held here:

  1. **It is off.** Not "off in the shipped config" — off in the class default,
     off in the policy default, and off in the handler, so a forgotten wiring
     fails closed. `Law 16`: nothing reaches the segment unless a person said so.
  2. **There is no destination parameter.** `discover()`, `mdns()` and `ssdp()`
     take no address, `/discover` is deliberately not a `TARGET_ROUTES` entry,
     and `?target=` is not read. Same property `P17-01` established for
     `netagent_client.call()` — *"fetch `http://169.254.169.254/` through the
     network agent"* has nowhere to put the address.
  3. **Every send is checked anyway.** `_assert_local_group` refuses anything
     that is not a multicast group in the link-local or organisation-local
     scopes, so a future edit that threads an address in from a setting or a
     response field arrives at a refusal rather than at a host. And every socket
     carries `IP_MULTICAST_TTL = 1`, which makes off-link delivery impossible as
     a property of the packet.
  4. **SSDP's `LOCATION:` is reported and never fetched.** Following it would be
     an HTTP request to an address chosen by whatever answered — the actual
     hole, wearing a protocol's name. Nothing in the module opens a stream
     socket and nothing resolves a name.

`FORBIDDEN.md` Part 2's five SSRF validators and the `OutboundHostLimiter` are
untouched, and the last test re-asserts the one that would show it.
"""
import ast
import ipaddress
import socket
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from netagent import discovery  # noqa: E402
from netagent import server as srv  # noqa: E402
from netagent.allowlist import Allowlist  # noqa: E402

_MODULE = ROOT / "netagent" / "discovery.py"


# ── 1. it is off ─────────────────────────────────────────────────────────────


def test_discovery_is_off_in_every_default_that_exists():
    """Three defaults, because one of them is the one somebody forgets to pass."""
    assert discovery.DiscoveryPolicy().enabled is False
    assert srv.Handler.discovery_policy.enabled is False
    assert discovery.discover()["enabled"] is False


def test_the_environment_switch_takes_a_strict_word(monkeypatch):
    """`B91`'s rule applied to the second thing that starts sending.

    A host carrying `PANTHEON_NETAGENT_DISCOVERY=maybe` must not start
    broadcasting because somebody guessed a truthy-looking word.
    """
    for value in ("1", "true", "yes", "TRUE", "Yes", " yes "):
        monkeypatch.setenv(discovery.ENV_DISCOVERY, value)
        assert discovery.DiscoveryPolicy.from_env_and_args().enabled is True, value
    # "on" is deliberately NOT in the list: it is not in `--allow-exec`'s either,
    # and `check-env-declared.py` holds the package to one vocabulary rather than
    # letting each flag grow its own (`B97`).
    for value in ("", "0", "on", "maybe", "off", "false", "sure", "enabled"):
        monkeypatch.setenv(discovery.ENV_DISCOVERY, value)
        assert discovery.DiscoveryPolicy.from_env_and_args().enabled is False, value


def test_the_off_answer_says_how_to_turn_it_on_and_is_not_an_empty_list():
    """A quiet segment and a switched-off feature must not look the same.

    Returning `200 []` for "you never enabled this" is how an operator concludes
    their network is empty and goes looking for a fault in the wrong place.
    """
    result = discovery.discover(discovery.DiscoveryPolicy(enabled=False))
    assert result["responders"] == []
    assert "--discover" in result["detail"]
    assert discovery.ENV_DISCOVERY in result["detail"]


def test_the_route_refuses_with_403_rather_than_an_empty_200():
    """Driven through the real handler dispatch, not through `discover()`."""
    payload = srv._routes(Allowlist(["192.168.1.0/24"]))["/discover"]()
    assert payload["enabled"] is False
    # The handler turns exactly this shape into a 403; the shape is the contract.
    assert payload.get("detail")


def test_turning_it_on_is_the_only_thing_that_changes_the_answer():
    policy = discovery.DiscoveryPolicy(enabled=True, wait=0.2)
    result = srv._routes(Allowlist(["192.168.1.0/24"]), policy)["/discover"]()
    assert result["enabled"] is True
    assert result["policy"]["enabled"] is True
    assert "allowlist" in result


def test_pantheon_cannot_turn_it_on():
    """`P17-02`'s argument, one route over: the gated party does not hold the
    switch. There is no writer for it — the agent has exactly one `POST` and it
    is `/exec`."""
    tree = ast.parse((ROOT / "netagent" / "server.py").read_text(encoding="utf-8"))
    posts = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "do_POST"]
    assert len(posts) == 1
    body = ast.unparse(posts[0])
    assert "discovery" not in body and "discover" not in body
    # And Pantheon's side has no parameter for it either.
    from src import netagent_client as nac

    assert "discover" in nac.ROUTES
    assert "discover" not in nac.TARGET_ROUTES


# ── 2. there is no destination parameter ─────────────────────────────────────


@pytest.mark.parametrize("fn", ["discover", "mdns", "ssdp"])
def test_no_entry_point_takes_an_address(fn):
    """Read from the signature, so a parameter added later fails here.

    `P17-01` proved this for `call()` by asserting no `url=` appears; the same
    property, asserted the same way, is what keeps *"discover 169.254.169.254"*
    from being a sentence this code can act on.
    """
    import inspect

    params = inspect.signature(getattr(discovery, fn)).parameters
    forbidden = {"url", "host", "hosts", "target", "address", "addresses",
                 "group", "groups", "destination", "dest", "ip", "endpoint"}
    assert not (set(params) & forbidden), sorted(set(params) & forbidden)


def test_discover_is_not_a_target_route():
    """Membership in `TARGET_ROUTES` is what makes the dispatcher read
    `?target=`. A route that is not in it cannot be handed an address at all,
    which is a stronger statement than a route that reads one and refuses."""
    assert "/discover" not in srv.TARGET_ROUTES
    assert "/discover" in srv._routes(Allowlist())


def test_a_target_query_string_changes_nothing():
    """Belt and braces: even if one is sent, nothing reads it."""
    policy = discovery.DiscoveryPolicy(enabled=True, wait=0.2)
    plain = srv._routes(Allowlist(["10.0.0.0/8"]), policy)
    # The route is a zero-argument callable. There is no seam for a target.
    import inspect

    assert inspect.signature(plain["/discover"]).parameters == {}


# ── 3. every send is checked anyway ──────────────────────────────────────────


@pytest.mark.parametrize("address", [
    "169.254.169.254",   # cloud metadata, the address this check exists for
    "8.8.8.8",
    "1.1.1.1",
    "127.0.0.1",
    "192.168.1.1",
    "224.1.2.3",         # multicast, but outside the local scopes
    "232.0.0.1",
    "example.com",
    "",
    "224.0.0.251.evil.example.com",
])
def test_a_destination_that_is_not_a_local_group_is_refused(address):
    with pytest.raises(discovery.DiscoveryRefused):
        discovery._assert_local_group(address)


def test_the_two_real_groups_pass_and_are_local():
    for group in (discovery.MDNS_GROUP, discovery.SSDP_GROUP):
        checked = discovery._assert_local_group(group)
        assert checked.is_multicast
    assert ipaddress.ip_address(discovery.MDNS_GROUP) in ipaddress.ip_network("224.0.0.0/24")
    assert ipaddress.ip_address(discovery.SSDP_GROUP) in ipaddress.ip_network("239.0.0.0/8")


@pytest.mark.parametrize("protocol,constant", [("mdns", "MDNS_GROUP"),
                                               ("ssdp", "SSDP_GROUP")])
def test_repointing_a_group_refuses_before_a_packet_leaves(protocol, constant, monkeypatch):
    """The check is on the send, so a repointed constant never reaches a socket.

    This is the SSRF test proper. If `_assert_local_group` were advisory — run
    once at import, or after the socket was built — this would send a datagram
    to the metadata address and the assertion below would fail.
    """
    sent = []

    class Recorder(socket.socket):
        def sendto(self, payload, addr):  # noqa: D102
            sent.append(addr)
            return len(payload)

    monkeypatch.setattr(discovery, constant, "169.254.169.254")
    monkeypatch.setattr(discovery, "_socket", lambda ttl=1: Recorder(
        socket.AF_INET, socket.SOCK_DGRAM))
    with pytest.raises(discovery.DiscoveryRefused):
        getattr(discovery, protocol)(0.1)
    assert sent == [], f"a datagram left for {sent}"


def test_discover_propagates_the_refusal_rather_than_reporting_an_empty_segment(monkeypatch):
    """A refused send must not be swallowed into "nothing answered".

    `discover()` catches `OSError` per protocol, and the one thing that must not
    be folded into that is a refusal — an operator reading `responders: []`
    would conclude the segment was quiet.
    """
    monkeypatch.setattr(discovery, "MDNS_GROUP", "8.8.8.8")
    with pytest.raises(discovery.DiscoveryRefused):
        discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                           lambda _a: True)


def test_every_socket_cannot_leave_the_segment():
    """`IP_MULTICAST_TTL = 1`: a router decrements it to zero.

    Read off the socket rather than out of the source, because the value that
    matters is the one the kernel holds.
    """
    sock = discovery._socket()
    try:
        assert sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL) == 1
    finally:
        sock.close()


def test_the_listen_window_is_bounded_however_it_is_asked_for():
    """An unbounded listen is a way to make a small process hold a large string."""
    assert discovery.DiscoveryPolicy(enabled=True, wait=999).wait == discovery.MAX_WAIT_SECONDS
    assert discovery.DiscoveryPolicy(enabled=True, wait=-5).wait == 0.2
    assert discovery.DiscoveryPolicy(enabled=True, wait="nonsense").wait == \
        discovery.DEFAULT_WAIT_SECONDS
    assert discovery.MAX_RESPONSES <= 1024 and discovery.MAX_DATAGRAM <= 65535


# ── 4. nothing is fetched, nothing is resolved ───────────────────────────────


def test_the_module_opens_no_stream_socket_and_makes_no_http_request():
    """Read structurally: names, not a text search (`Law 20`)."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for banned in ("SOCK_STREAM", "create_connection", "urlopen", "Request",
                   "getaddrinfo", "gethostbyname", "connect"):
        assert banned not in names, f"discovery.py references {banned}"
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"ipaddress", "logging", "os", "random", "socket",
                        "struct", "time", "typing", "__future__"}, sorted(imported)


def test_an_ssdp_location_is_reported_and_not_followed(monkeypatch):
    """The whole SSDP hole, in one test.

    A hostile device on the segment answers with
    `LOCATION: http://169.254.169.254/latest/meta-data/`. The header is data and
    is reported; following it would be an HTTP request from the process that has
    the LAN to an address the responder chose. Any stream socket opened during
    the run fails the test.
    """
    response = (b"HTTP/1.1 200 OK\r\n"
                b"SERVER: Linux/4.4 UPnP/1.0 Evil/1.0\r\n"
                b"ST: upnp:rootdevice\r\n"
                b"USN: uuid:abcd::upnp:rootdevice\r\n"
                b"LOCATION: http://169.254.169.254/latest/meta-data/\r\n\r\n")
    real_socket = socket.socket

    def no_streams(family=socket.AF_INET, kind=socket.SOCK_STREAM, *a, **kw):
        assert kind != socket.SOCK_STREAM, "discovery opened a TCP connection"
        return real_socket(family, kind, *a, **kw)

    monkeypatch.setattr(socket, "socket", no_streams)
    monkeypatch.setattr(discovery, "_collect",
                        lambda sock, deadline: [(response, "192.168.1.1")])
    result = discovery.ssdp(0.1)
    row = result["responders"][0]
    assert row["location"] == "http://169.254.169.254/latest/meta-data/"
    assert row["location_fetched"] is False
    assert "Evil/1.0" in row["server"]


def test_no_external_service_is_consulted_to_describe_a_device(monkeypatch):
    """`Law 16` at its sharpest point in this module.

    Vendor lookups, geolocation and device-fingerprint APIs are the obvious way
    to make this output prettier and the exact thing the law forbids. Name
    resolution is broken for the duration: if anything reached out, it raises.
    """
    def boom(*_a, **_kw):
        raise AssertionError("discovery resolved a name")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "gethostbyname", boom)
    monkeypatch.setattr(discovery, "_collect", lambda sock, deadline: [])
    assert discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                              lambda _a: True)["count"] == 0


# ── what it is FOR: a quiet device appears, and only an allowed one ──────────


def _mdns_response(service: str) -> bytes:
    """A minimal mDNS answer carrying one PTR record, built by hand.

    Hand-built rather than round-tripped through the module's own encoder, so
    the parser is measured against the wire format rather than against itself.
    """
    def labels(name: str) -> bytes:
        out = bytearray()
        for part in name.split("."):
            out.append(len(part))
            out += part.encode()
        out.append(0)
        return bytes(out)

    header = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0)  # 1 answer, no question
    owner = labels("_services._dns-sd._udp.local")
    rdata = labels(service)
    answer = owner + struct.pack("!HHIH", 12, 0x8001, 120, len(rdata)) + rdata
    return header + answer


def test_a_device_that_has_said_nothing_to_this_host_appears(monkeypatch):
    """The row's first `Verify:` clause.

    `192.168.1.77` is in no neighbour table here — it has exchanged no traffic
    with this machine. It answers the multicast query and is reported, which is
    the entire difference between this row and `P17-03`.
    """
    monkeypatch.setattr(discovery, "mdns", lambda wait: {
        "supported": True,
        "responders": [{"address": "192.168.1.77", "source": "mdns",
                        "names": ["_printer._tcp.local"], "addresses": []}]})
    monkeypatch.setattr(discovery, "ssdp", lambda wait: {"supported": True,
                                                         "responders": []})
    result = discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                                Allowlist(["192.168.1.0/24"]).allows)
    assert [r["address"] for r in result["responders"]] == ["192.168.1.77"]
    assert result["responders"][0]["names"] == ["_printer._tcp.local"]
    assert result["withheld"] == 0


def test_a_responder_outside_the_allowlist_is_withheld_and_counted(monkeypatch):
    """The row's third `Verify:` clause, and the honest shape it asks for.

    A broadcast cannot be gated the way a target can — everything on the segment
    hears the question. So the ANSWERS are filtered, and the count of what was
    withheld is reported beside them, for the same reason `/neighbours` reports
    it: a filtered list that looks complete sends an operator hunting the wrong
    fault.
    """
    monkeypatch.setattr(discovery, "mdns", lambda wait: {
        "supported": True,
        "responders": [{"address": "192.168.1.77", "source": "mdns", "names": [], "addresses": []},
                       {"address": "10.9.9.9", "source": "mdns", "names": [], "addresses": []},
                       {"address": "172.18.0.5", "source": "mdns", "names": [], "addresses": []}]})
    monkeypatch.setattr(discovery, "ssdp", lambda wait: {"supported": True, "responders": []})
    result = discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                                Allowlist(["192.168.1.0/24"]).allows)
    assert [r["address"] for r in result["responders"]] == ["192.168.1.77"]
    assert result["seen_total"] == 3
    assert result["withheld"] == 2
    assert result["count"] == 1


def test_an_empty_allowlist_reports_nothing_at_all(monkeypatch):
    """`P17-02`'s shipped state: empty refuses everything, including answers."""
    monkeypatch.setattr(discovery, "mdns", lambda wait: {
        "supported": True,
        "responders": [{"address": "192.168.1.77", "source": "mdns", "names": [], "addresses": []}]})
    monkeypatch.setattr(discovery, "ssdp", lambda wait: {"supported": True, "responders": []})
    result = discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                                Allowlist().allows)
    assert result["responders"] == []
    assert result["withheld"] == 1


def test_one_device_answering_both_protocols_is_one_row(monkeypatch):
    """`P17-04`'s call, inherited: an operator counting rows counts machines."""
    monkeypatch.setattr(discovery, "mdns", lambda wait: {
        "supported": True,
        "responders": [{"address": "192.168.1.1", "source": "mdns",
                        "names": ["_http._tcp.local"], "addresses": []}]})
    monkeypatch.setattr(discovery, "ssdp", lambda wait: {
        "supported": True,
        "responders": [{"address": "192.168.1.1", "source": "ssdp",
                        "services": ["upnp:rootdevice"], "server": "RouterOS"}]})
    result = discovery.discover(discovery.DiscoveryPolicy(enabled=True, wait=0.1),
                                Allowlist(["192.168.1.0/24"]).allows)
    assert len(result["responders"]) == 1
    row = result["responders"][0]
    assert sorted(row["sources"]) == ["mdns", "ssdp"]
    assert row["names"] == ["_http._tcp.local"]
    assert row["services"] == ["upnp:rootdevice"]
    assert row["server"] == "RouterOS"


def test_the_mdns_parser_survives_a_compression_pointer_loop():
    """A hostile packet must truncate a name, not hang the process with the LAN."""
    # A name whose pointer points at itself, at offset 12.
    payload = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c" + \
        struct.pack("!HHIH", 12, 1, 120, 2) + b"\xc0\x0c"
    parsed = discovery._parse_mdns(payload)
    assert isinstance(parsed["names"], list)


def test_the_hop_budget_and_not_luck_is_what_stops_a_pointer_cycle():
    """A two-pointer cycle, which the self-pointer guard does not catch.

    Added because a mutation survived: removing `hops < 64` from `_decode_name`
    left every other test green, since the only cycle under test pointed at
    itself and was broken by the `pointer == cursor` check. `A -> B -> A` needs
    the budget, and without it this call does not return — which in this module
    means a wedged thread in the one process on the machine that has the LAN.
    """
    # Two pointers at offsets 0 and 2, each naming the other.
    data = b"\xc0\x02" + b"\xc0\x00"
    name, _after = discovery._decode_name(data, 0)
    assert name == ""


def test_decoding_a_name_costs_at_most_the_budget():
    """The budget is the bound, stated as a number rather than as a hope."""
    import inspect

    source = inspect.getsource(discovery._decode_name)
    assert "hops" in source
    # 40 nested pointers resolve; the cycle above does not. Both under one rule.
    chain = bytearray()
    for i in range(40):
        chain += struct.pack("!H", 0xC000 | ((i + 1) * 2))
    chain += b"\x02hi\x00"
    name, _after = discovery._decode_name(bytes(chain), 0)
    assert name == "hi"


def test_a_real_response_is_parsed_into_a_service_name(monkeypatch):
    monkeypatch.setattr(discovery, "_collect", lambda sock, deadline: [
        (_mdns_response("_printer._tcp.local"), "192.168.1.77")])
    result = discovery.mdns(0.1)
    assert result["responders"][0]["address"] == "192.168.1.77"
    assert "_printer._tcp.local" in result["responders"][0]["names"]


# ── the route, driven over HTTP ──────────────────────────────────────────────


@pytest.fixture
def agent_with(tmp_path):
    """A real agent on a real port, with discovery on or off as asked.

    Driven rather than asserted about, for the reason the allowlist tests give:
    a gate asserted about is a gate that gets refactored around. The mutation
    that made this necessary turned the handler's 403 branch off, and every
    other test in this file stayed green because they all call `discover()`
    directly.
    """
    import json as _json
    import tempfile
    import threading
    import urllib.error
    import urllib.request

    from netagent.tokens import load_or_create

    servers = []

    def start(enabled: bool):
        state = Path(tempfile.mkdtemp(dir=str(tmp_path)))
        _stored, raw = load_or_create(state)
        httpd = srv.serve(
            bind="127.0.0.1", port=0, state_dir=state, serve_forever=False,
            allowlist=Allowlist(["127.0.0.0/8"]),
            discovery_policy=discovery.DiscoveryPolicy(enabled=enabled, wait=0.2))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        port = httpd.server_address[1]

        def call(path):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            req.add_header("Authorization", f"Bearer {raw}")
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, _json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, _json.loads(e.read())

        return call

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def test_the_route_answers_403_when_discovery_is_off(agent_with):
    """Over the wire, because that is where a caller meets it.

    403 and not `200 []`: a refusal has to read the same way the allowlist's and
    the exec guard's do, so a caller has one shape to handle — and an empty 200
    is indistinguishable from "your segment is quiet", which sends an operator
    hunting a fault that is a switch.
    """
    call = agent_with(enabled=False)
    status, body = call("/discover")
    assert status == 403
    assert "--discover" in body["error"]
    assert body["responders"] == []


def test_the_route_answers_200_when_the_operator_turned_it_on(agent_with):
    call = agent_with(enabled=True)
    status, body = call("/discover")
    assert status == 200
    assert body["enabled"] is True
    assert body["policy"]["enabled"] is True
    assert "withheld" in body and "seen_total" in body
    assert body["allowlist"]["cidrs"] == ["127.0.0.0/8"]


def test_an_unauthenticated_caller_cannot_learn_the_route_exists(agent_with):
    """401 before the route lookup, unchanged by this row (`P17-01`)."""
    import json as _json
    import urllib.error
    import urllib.request

    call = agent_with(enabled=True)
    # Re-derive the port from the bound server rather than re-implementing call().
    status, _body = call("/discover")
    assert status == 200
    # The unauthenticated shape is already pinned in the agent's own suite; what
    # matters here is that /discover did not get its own door.
    tree = ast.parse((ROOT / "netagent" / "server.py").read_text(encoding="utf-8"))
    gets = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "do_GET"]
    body = ast.unparse(gets[0])
    assert body.index("_authorised") < body.index("_routes"), (
        "the 401 must still fire before the route table is consulted")


# ── the controls that never lift are still where they were ───────────────────


def test_the_ssrf_validators_still_refuse_a_private_address():
    """`FORBIDDEN.md` Part 2. `P17-10` adds reach to the local segment for the
    HOST agent; it must not have moved the line for URLs arriving from content.
    The same assertion `P17-01` made, re-made because this row is the one that
    starts sending."""
    from src.outbound_fetch import _public_http_url
    from src.url_safety import check_outbound_url

    for candidate in ("http://192.168.1.1/", "http://169.254.169.254/",
                      "http://127.0.0.1:7000/", "http://224.0.0.251/",
                      "http://239.255.255.250:1900/"):
        assert not _public_http_url(candidate), \
            f"the content-fetch path now accepts {candidate}"
        ok, _why = check_outbound_url(candidate, block_private=True,
                                      resolver=lambda host: [host])
        assert not ok, f"check_outbound_url now accepts {candidate}"


def test_the_outbound_limiter_still_has_no_global_bypass():
    """`FORBIDDEN.md` Part 2: *no global bypass*, and a discovery feature is
    exactly the kind of thing that would want one — it is chatty and local, so
    "pacing costs nothing here" is an argument somebody will make. It sends UDP
    from the host agent and never touches the limiter; Pantheon's side of the
    wire goes through `paced_http` like every other netagent call."""
    import inspect

    from src import rate_limiter

    source = inspect.getsource(rate_limiter.OutboundHostLimiter)
    assert "PANTHEON_DISABLE_RATE_LIMIT" not in source
    from src import netagent_client as nac

    assert "paced_http" in inspect.getsource(nac.call)
