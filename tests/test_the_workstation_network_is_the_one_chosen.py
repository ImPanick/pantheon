# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-06` — the network the workstation has is the one the admin chose.

The adversary is named in `D-2026-09-30-03`: content the agent reads steers it
into running code that reaches devices on the owner's network. With `sudo` on
(the default) that code is root in the workstation, so the mode is held by the
network gate (`workstation/gate.py`), outside it; the daemon holds it for
accounts where its machine lets it; and the panel says which, never more.

Everything here calls the shipped code (`Law 20`):

  * **what *internet* means** — the protocol's one list, against the standard
    library's own idea of a non-global address;
  * **the rules** — `netrules.ruleset` for each mode, and, where this runs as
    root with `nft` and `unshare`, the same rules loaded into a kernel (a
    throwaway network namespace, never this machine's) and read back, with
    real sockets refused or let through;
  * **the gate** — its mode written, read back from the kernel and self-tested
    before it is reported, kept across a restart, and its HTTP routes behind
    its own token;
  * **the daemon** — `config` takes the mode, `health` reports what this
    machine holds, and the Ubuntu system holds it for accounts only when it
    has CAP_NET_ADMIN, without touching the machine's rules otherwise;
  * **Pantheon** — `sync_config` pushes the admin's mode to the real daemon and
    to a real gate, fails closed when a gate is there and does not take it,
    and `network_view` gives the panel one word for each state.

The end-to-end probes, in the real image under Docker, are opt-in:
`tests/test_the_workstation_network_holds_in_the_image.py`.
"""
from __future__ import annotations

import asyncio
import errno
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from src import workstation_access as wa
from src import workstation_client as wc
from src.workstation_client import NetGateClient, WorkstationClient, WorkstationError
from tests.helpers.workstation_daemon import TEST_TOKEN, running_workstation
from workstation import gate as G
from workstation import netrules as N
from workstation import protocol as P
from workstation.agentd import SingleUserSystem, Workstation, load_or_create_token
from workstation.agentd import WorkstationError as DaemonError
from tests.helpers.signed_in import ADMIN, signed_in

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


# ── what *internet* excludes ──────────────────────────────────────────────────

def _nets(names):
    return [ipaddress.ip_network(n) for n in names]


def test_internet_excludes_every_range_the_standard_library_calls_not_global():
    """The stdlib's private tables are the reference a reviewer can check by
    hand; a Python that adds a range reddens this until the list follows."""
    v4, v6 = _nets(P.INTERNET_EXCLUDED_V4), _nets(P.INTERNET_EXCLUDED_V6)
    for net in ipaddress._IPv4Constants._private_networks:  # noqa: SLF001
        assert any(net.subnet_of(x) for x in v4), f"{net} is not global and not excluded"
    for net in ipaddress._IPv6Constants._private_networks:  # noqa: SLF001
        assert any(net.subnet_of(x) for x in v6), f"{net} is not global and not excluded"
    shared = ipaddress.ip_network("100.64.0.0/10")  # CGNAT and Tailscale: not global either
    assert any(shared.subnet_of(x) for x in v4)


def test_internet_excludes_nothing_global_but_multicast_and_site_local():
    """What is on top of the stdlib's list, named: multicast (never a host on
    the internet) and the deprecated site-local range."""
    extras = {"224.0.0.0/3", "fec0::/10", "ff00::/8"}
    for name in (*P.INTERNET_EXCLUDED_V4, *P.INTERNET_EXCLUDED_V6):
        net = ipaddress.ip_network(name)
        if name in extras:
            continue
        for addr in (net.network_address, net.broadcast_address):
            exceptions = (getattr(ipaddress._IPv4Constants, "_private_networks_exceptions", [])  # noqa: SLF001
                          + getattr(ipaddress._IPv6Constants, "_private_networks_exceptions", []))  # noqa: SLF001
            assert not addr.is_global or any(addr in e for e in exceptions), (name, addr)


@pytest.mark.parametrize("address,excluded", [
    ("192.168.1.1", True), ("10.0.0.5", True), ("172.18.0.2", True), ("169.254.169.254", True),
    ("100.100.100.100", True), ("127.0.0.1", True), ("192.168.65.254", True), ("fd00::1", True),
    ("fe80::1", True), ("::ffff:192.168.1.1", True), ("2002:c0a8:101::1", True),
    ("1.1.1.1", False), ("8.8.8.8", False), ("151.101.1.69", False), ("2606:4700::1111", False),
])
def test_what_internet_lets_through_and_what_it_refuses(address, excluded):
    assert N._excluded(address) is excluded  # noqa: SLF001


def test_the_protocol_names_who_holds_the_mode_in_one_word_each():
    # `B992` added `hypervisor`: the VM backend's host holding *none* outside
    # each machine (`tests/test_the_vm_backend_holds_the_network_mode.py`).
    assert P.NETWORK_ENFORCEMENT == ("gate", "accounts", "none", "hypervisor")
    assert set(P.GATE_SELF_TESTS) == {"refused", "not_needed"}
    assert P.GATE_PORT != P.DEFAULT_PORT
    assert set(P.GATE_ROUTES) == {"health", "mode"}


# ── the rules, as text ────────────────────────────────────────────────────────

def _chain(text: str) -> List[str]:
    lines = text.splitlines()
    start = lines.index("  chain output {")
    return [ln.strip() for ln in lines[start + 2:] if ln.startswith("    ")]


def test_full_writes_nothing_and_removes_what_was_there():
    text = N.ruleset("full")
    assert text.splitlines() == [f"table inet {N.GATE_TABLE} {{}}", f"delete table inet {N.GATE_TABLE}"]


def test_internet_refuses_the_excluded_ranges_and_keeps_loopback_and_replies():
    rules = _chain(N.ruleset("internet"))
    assert rules[0] == "ct direction reply accept"
    assert rules.index('oifname "lo" accept') < rules.index(
        "ip daddr @excluded4 reject with icmpx admin-prohibited")
    assert "ip6 daddr @excluded6 reject with icmpx admin-prohibited" in rules
    text = N.ruleset("internet")
    for net in P.INTERNET_EXCLUDED_V4 + P.INTERNET_EXCLUDED_V6:
        assert net in text
    assert f'comment "{N.COMMENT_PREFIX}internet"' in text


def test_none_refuses_everything_but_loopback_and_dockers_resolver_too():
    rules = _chain(N.ruleset("none"))
    assert rules == ["ct direction reply accept",
                     f"ip daddr {N.DOCKER_DNS} reject with icmpx admin-prohibited",
                     'oifname "lo" accept',
                     "reject with icmpx admin-prohibited"]


def test_the_accounts_rules_touch_only_the_account_uids():
    rules = _chain(N.ruleset("none", table=N.ACCOUNTS_TABLE, uids=(20000, 59999)))
    assert rules[0] == "ct direction reply accept"
    assert all(r.startswith("meta skuid 20000-59999 ") for r in rules[1:])


def test_a_lan_resolver_answers_dns_under_internet_and_nothing_else_of_it():
    rules = _chain(N.ruleset("internet", resolvers=["192.168.1.1"]))
    assert "ip daddr { 192.168.1.1 } meta l4proto { tcp, udp } th dport 53 accept" in rules
    assert not any("192.168.1.1" in r for r in _chain(N.ruleset("none", resolvers=["192.168.1.1"])))


def test_lan_resolvers_are_read_from_resolv_conf_and_loopback_is_not_one(tmp_path):
    conf = tmp_path / "resolv.conf"
    conf.write_text("nameserver 127.0.0.11\nnameserver 192.168.1.1\nnameserver 1.1.1.1\n"
                    "nameserver fe80::1%eth0\noptions ndots:0\n")
    assert N.lan_resolvers(conf) == ["192.168.1.1", "fe80::1"]


def test_an_unknown_mode_or_a_strange_table_is_refused():
    with pytest.raises(ValueError):
        N.ruleset("lan-only")
    with pytest.raises(ValueError):
        N.ruleset("none", table="x; flush ruleset")


# ── the rules, in a kernel (a throwaway namespace) ───────────────────────────

def _kernel_ready() -> Optional[str]:
    if os.geteuid() != 0:
        return "needs root to make a network namespace"
    if not (shutil.which("unshare") and shutil.which("nft")):
        return "needs unshare and nft"
    probe = subprocess.run(["unshare", "-n", "nft", "list", "ruleset"], capture_output=True)
    if probe.returncode != 0:
        return f"cannot make a network namespace here: {probe.stderr.decode()[-200:]}"
    return None


_IN_NETNS = textwrap.dedent(r"""
    import errno, fcntl, json, os, socket, struct, sys
    sys.path.insert(0, sys.argv[1])
    from workstation import netrules as N
    mode, scope = sys.argv[2], sys.argv[3]
    # A new namespace's loopback starts down.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flags = struct.unpack("16sH", fcntl.ioctl(s, 0x8913, struct.pack("16sH", b"lo", 0))[:18])[1]
    fcntl.ioctl(s, 0x8914, struct.pack("16sH", b"lo", flags | 1))
    table = N.ACCOUNTS_TABLE if scope == "accounts" else N.GATE_TABLE
    uids = (20000, 59999) if scope == "accounts" else None
    N.apply(N.ruleset(mode, table=table, uids=uids))
    out = {"in_force": N.in_force(table)}
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(4)
    port = listener.getsockname()[1]
    def attempt(addr):
        pid = os.fork()
        if pid == 0:
            if who == "account":
                os.setgid(20001); os.setuid(20001)
            c = socket.socket(); c.settimeout(2)
            os._exit(c.connect_ex(addr) or 0)
        return os.waitpid(pid, 0)[1] >> 8
    for who in ("account", "root"):
        out[who] = {"dns": errno.errorcode.get(attempt((N.DOCKER_DNS, 53)), "OK"),
                    "loopback": errno.errorcode.get(attempt(("127.0.0.1", port)), "OK")}
    print(json.dumps(out))
""")


def _in_netns(mode: str, scope: str) -> Dict:
    done = subprocess.run(["unshare", "-n", sys.executable, "-c", _IN_NETNS, str(ROOT), mode, scope],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("mode", P.NETWORK_MODES)
@pytest.mark.parametrize("scope", ["gate", "accounts"])
def test_the_kernel_loads_each_mode_and_says_which_one_it_has(mode, scope):
    why = _kernel_ready()
    if why:
        pytest.skip(why)
    out = _in_netns(mode, scope)
    assert out["in_force"] == mode
    # Loopback is the workstation talking to itself: open in every mode.
    assert out["account"]["loopback"] == out["root"]["loopback"] == "OK"
    # Docker's resolver is refused under `none` — to every process for the
    # gate, to accounts only for the daemon's own rules. Elsewhere nothing
    # listens there, so the far end refuses instead.
    refused = "EHOSTUNREACH"
    assert out["account"]["dns"] == (refused if mode == "none" else "ECONNREFUSED")
    assert out["root"]["dns"] == (refused if mode == "none" and scope == "gate" else "ECONNREFUSED")


def test_the_self_test_believes_only_a_refusal_the_rules_make():
    assert N.self_test(connect=lambda a, t: errno.EHOSTUNREACH) == "refused"
    assert N.self_test(connect=lambda a, t: errno.EPERM) == "refused"
    for code in (0, errno.ECONNREFUSED, errno.ETIMEDOUT, errno.ENETUNREACH):
        with pytest.raises(N.RulesError):
            N.self_test(connect=lambda a, t, c=code: c)


def test_the_self_test_is_aimed_at_an_address_that_is_never_a_host():
    host, _port = N.SELF_TEST_ADDRESS
    assert ipaddress.ip_address(host) in ipaddress.ip_network("192.0.2.0/24")  # RFC 5737
    assert N._excluded(host)  # noqa: SLF001 — refused by internet and by none


# ── the gate ──────────────────────────────────────────────────────────────────

class FakeNft:
    """`nft` as the gate drives it: `-f -` loads a table (whatever the text's
    comment says), `-j list table` answers what is loaded. `refuse` makes a
    load fail; `lie` makes the kernel report another mode than was written."""

    def __init__(self):
        self.loaded: Optional[str] = None
        self.inputs: List[str] = []
        self.refuse = False
        self.lie: Optional[str] = None

    def __call__(self, argv, stdin=None):
        if argv[1:] == ["-f", "-"]:
            if self.refuse:
                return 1, "", "Error: Could not process rule: Operation not permitted"
            self.inputs.append(stdin)
            mark = f'comment "{N.COMMENT_PREFIX}'
            self.loaded = stdin.split(mark)[1].split('"')[0] if mark in stdin else None
            return 0, "", ""
        if argv[1:4] == ["-j", "list", "table"]:
            loaded = self.lie or self.loaded
            if loaded is None:
                return 1, "", "Error: No such file or directory"
            return 0, json.dumps({"nftables": [{"table": {
                "family": "inet", "name": argv[-1], "comment": N.COMMENT_PREFIX + loaded}}]}), ""
        raise AssertionError(argv)


def _gate(tmp_path, nft=None, tests=None):
    nft = nft or FakeNft()
    calls = tests if tests is not None else []
    gate = G.Gate(tmp_path / "gate-state", run=nft, nft="nft",
                  self_test=lambda: calls.append("tested") or "refused", resolvers=lambda: [])
    return gate, nft, calls


def test_a_new_gate_starts_at_none_until_pantheon_says_otherwise(tmp_path):
    gate, nft, tested = _gate(tmp_path)
    state = gate.start()
    assert G.BOOT_MODE == "none"
    assert state["mode"] == "none" and state["enforcement"] == "gate"
    assert state["self_test"] == "refused" and tested == ["tested"]
    assert nft.loaded == "none"


def test_the_gate_writes_the_mode_reads_it_back_and_tests_it(tmp_path):
    gate, nft, tested = _gate(tmp_path)
    state = gate.set_mode("internet")
    assert nft.inputs[-1] == N.ruleset("internet", table=N.GATE_TABLE)
    assert (state["mode"], state["self_test"], state["agent"]) == ("internet", "refused",
                                                                   P.GATE_AGENT_NAME)
    assert gate.health()["mode"] == "internet"
    full = gate.set_mode("full")
    assert full["self_test"] == "not_needed" and tested == ["tested"]


def test_the_gate_keeps_its_mode_so_a_restart_puts_it_back(tmp_path):
    gate, _nft, _ = _gate(tmp_path)
    gate.set_mode("internet")
    again, nft2, _ = _gate(tmp_path)
    assert again.kept_mode() == "internet"
    assert again.start()["mode"] == "internet" and nft2.loaded == "internet"


def test_the_gate_reports_what_the_kernel_has_not_what_it_asked_for(tmp_path):
    gate, nft, _ = _gate(tmp_path)
    gate.set_mode("none")
    nft.lie = "full"
    with pytest.raises(DaemonError) as e:
        gate.set_mode("internet")
    assert e.value.code == "unavailable" and "full" in e.value.message
    assert gate.health()["mode"] == "full", "the health must say what is loaded"
    assert gate.kept_mode() == "none", "a mode that did not take is not kept"


def test_a_refused_load_or_a_failed_self_test_is_an_error_not_a_mode(tmp_path):
    gate, nft, _ = _gate(tmp_path)
    gate.set_mode("full")
    nft.refuse = True
    with pytest.raises(DaemonError):
        gate.set_mode("none")
    assert gate.health()["mode"] == "full"
    failing = G.Gate(tmp_path / "other", run=FakeNft(), nft="nft", resolvers=lambda: [],
                     self_test=lambda: (_ for _ in ()).throw(N.RulesError("not refused")))
    with pytest.raises(DaemonError):
        failing.set_mode("internet")
    assert failing.kept_mode() == G.BOOT_MODE


def test_the_gate_refuses_a_mode_the_protocol_does_not_name(tmp_path):
    gate, _nft, _ = _gate(tmp_path)
    with pytest.raises(DaemonError) as e:
        gate.set_mode("lan-only")
    assert e.value.code == "bad_request"


def test_the_gate_never_takes_the_workstations_token_variable(tmp_path, monkeypatch):
    """`env=None`: a value the workstation's environment names is one its root
    could know, so the gate makes its own."""
    monkeypatch.setenv(P.TOKEN_ENV, "pws_the-workstations-own")
    gate_token = load_or_create_token(tmp_path / "gate-pairing", env=None)
    assert gate_token != "pws_the-workstations-own" and gate_token.startswith(P.TOKEN_PREFIX)
    assert load_or_create_token(tmp_path / "ws-pairing") == "pws_the-workstations-own"


class RunningGate:
    def __init__(self, tmp_path, token="pwn_gate-token", nft=None):
        self.gate, self.nft, _ = _gate(tmp_path, nft)
        self.gate.start()
        self.token = token
        self.server = G.make_server(self.gate, token, bind="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def running_gate(tmp_path):
    g = RunningGate(tmp_path)
    try:
        yield g
    finally:
        g.close()


def test_anyone_may_ask_the_gate_its_mode_and_only_the_token_changes_it(running_gate):
    open_client = NetGateClient(running_gate.url, "")
    assert run(open_client.health())["mode"] == "none"
    with pytest.raises(WorkstationError) as e:
        run(NetGateClient(running_gate.url, "pwn_wrong").set_mode("full"))
    assert e.value.code == "unauthorized" and "network gate" in e.value.message
    with pytest.raises(WorkstationError):
        run(open_client.set_mode("full"))
    assert run(open_client.health())["mode"] == "none", "a refused caller moved the gate"
    held = run(NetGateClient(running_gate.url, running_gate.token).set_mode("internet"))
    assert held["mode"] == "internet" and running_gate.nft.loaded == "internet"


def test_the_gate_answers_401_before_it_says_whether_a_route_exists(running_gate):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(running_gate.url + "/v1/elsewhere", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401
    req.add_header("Authorization", f"Bearer {running_gate.token}")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 404


def test_something_else_on_the_gates_port_is_not_taken_for_the_gate():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b'{"ok": true, "agent": "a router"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Other)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(WorkstationError) as e:
            run(NetGateClient(f"http://127.0.0.1:{server.server_address[1]}", "").health())
    finally:
        server.shutdown()
        server.server_close()
    assert "not the workstation's network gate" in e.value.message


# ── the daemon ────────────────────────────────────────────────────────────────

def test_the_daemon_takes_the_mode_and_says_it_holds_nothing_here(tmp_path):
    station = Workstation(SingleUserSystem(tmp_path / "homes"), TEST_TOKEN)
    answer = station.config({"network": "internet"})
    assert answer["network"] == "internet"
    assert answer["network_enforcement"] == "none" and answer["network_in_force"] is None
    assert isinstance(answer["root_can_change_network"], bool)
    assert station.health(True)["network"] == "internet"
    with pytest.raises(DaemonError) as e:
        station.config({"network": "lan-only"})
    assert e.value.code == "bad_request"
    assert station.health(True)["network"] == "internet", "a refused mode was recorded"


def test_an_unauthenticated_caller_learns_nothing_of_the_network(tmp_path):
    station = Workstation(SingleUserSystem(tmp_path / "homes"), TEST_TOKEN)
    assert not {"network", "network_in_force", "network_enforcement"} & set(station.health(False))


@pytest.fixture
def ubuntu_rules(tmp_path, monkeypatch):
    """`UbuntuSystem` without `prepare` (no accounts made, no root needed), its
    nft calls recorded instead of run, and whether it holds CAP_NET_ADMIN set
    by the test."""
    from workstation import ubuntu as U
    calls: List[str] = []
    loaded: Dict[str, Optional[str]] = {"mode": None}
    state = {"cap": True}

    def apply(text, **kw):
        calls.append(text)
        mark = f'comment "{N.COMMENT_PREFIX}'
        loaded["mode"] = text.split(mark)[1].split('"')[0] if mark in text else None

    monkeypatch.setattr(N, "apply", apply)
    monkeypatch.setattr(N, "in_force", lambda table, **kw: loaded["mode"] or "full")
    monkeypatch.setattr(N, "nft_path", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(N, "capability", lambda bit, field="CapEff", status=None: state["cap"])
    monkeypatch.setattr(N, "lan_resolvers", lambda *a: [])

    def make():
        return U.UbuntuSystem(tmp_path / "homes", prepare=False,
                              sudoers_path=tmp_path / "sudoers", runtime_root=tmp_path / "run")
    return make, calls, state


def test_ubuntu_holds_the_mode_for_accounts_when_it_may(ubuntu_rules):
    make, calls, _ = ubuntu_rules
    system = make()
    system.set_network("internet")
    assert calls[-1] == N.ruleset("internet", table=N.ACCOUNTS_TABLE, uids=(20000, 59999))
    report = system.network_report()
    assert (report["network_in_force"], report["network_enforcement"]) == ("internet", "accounts")
    # Kept like `sudo`: a restarted daemon starts from the admin's last word.
    again = make()
    assert again.network == "internet"


def test_ubuntu_without_cap_net_admin_writes_nothing_and_says_so(ubuntu_rules):
    make, calls, state = ubuntu_rules
    state["cap"] = False
    system = make()
    system.set_network("none")
    assert calls == []
    report = system.network_report()
    assert (report["network_in_force"], report["network_enforcement"]) == (None, "none")
    assert system.network == "none", "the admin's choice is still recorded"


def test_full_on_a_machine_that_never_narrowed_touches_no_rules(ubuntu_rules):
    make, calls, _ = ubuntu_rules
    system = make()
    system._hold_network("full")  # noqa: SLF001 — what `prepare` does at start
    assert calls == []
    system.set_network("none")
    system.set_network("full")
    assert calls[-1] == N.ruleset("full", table=N.ACCOUNTS_TABLE, uids=(20000, 59999))


# ── Pantheon: the mode pushed, and the gate ───────────────────────────────────

@pytest.fixture
def settings(monkeypatch):
    """The admin's settings as a dict both modules read, and no gate or
    workstation variable from the shell running this."""
    values = {"workstation_enabled": True, "workstation_sudo": True,
              "workstation_network": "full", "workstation_route_tools": True}
    read = lambda key, default=None: values.get(key, default)  # noqa: E731
    monkeypatch.setattr(wa, "_setting", read)
    monkeypatch.setattr(wc, "_setting", read)
    for name in (P.URL_ENV, P.TOKEN_ENV, P.GATE_URL_ENV, P.GATE_PAIRING_DIR_ENV):
        monkeypatch.delenv(name, raising=False)
    # The daemon in these tests is this test process, which may be root with
    # every capability; the shipped workstation has CAP_NET_ADMIN in no set
    # (the overlay). Said here, and the other case has its own test below.
    monkeypatch.setattr(N, "capability", lambda bit, field="CapEff", status=None: False)
    return values


def _point_at_gate(monkeypatch, tmp_path, gate: RunningGate, url: Optional[str] = None):
    pairing = tmp_path / "gate-pairing"
    pairing.mkdir(exist_ok=True)
    (pairing / P.TOKEN_FILENAME).write_text(gate.token + "\n")
    monkeypatch.setenv(P.GATE_PAIRING_DIR_ENV, str(pairing))
    monkeypatch.setenv(P.GATE_URL_ENV, url or gate.url)


@pytest.mark.parametrize("mode", P.NETWORK_MODES)
def test_the_admins_mode_reaches_the_daemon_and_the_gate(tmp_path, settings, monkeypatch, mode):
    settings["workstation_network"] = mode
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        with running_workstation(tmp_path) as ws:
            daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
            assert ws.system.network == mode
        assert daemon["network"] == mode
        assert daemon["network_gate"]["mode"] == mode and (gate.nft.loaded or "full") == mode
        view = wa.network_view(mode, daemon)
        assert view["state"] == ("unrestricted" if mode == "full" else "enforced")
        assert view["enforcement"] == "gate"
    finally:
        gate.close()


def test_a_workstation_whose_root_could_rewrite_the_gate_is_not_called_enforced(
        tmp_path, settings, monkeypatch):
    """The gate's rules sit in a namespace the workstation shares. A workstation
    run with CAP_NET_ADMIN (an overlay someone edited) could rewrite them, and
    the daemon says so — so the panel says *only while sudo is off*."""
    monkeypatch.setattr(N, "capability", lambda bit, field="CapEff", status=None:
                        bit == N.CAP_NET_ADMIN and field == "CapBnd")
    settings["workstation_network"] = "internet"
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        with running_workstation(tmp_path) as ws:
            daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert daemon["root_can_change_network"] is True
        assert wa.network_view("internet", daemon)["state"] == "liftable"
        daemon["sudo"] = False
        assert wa.network_view("internet", daemon)["state"] == "enforced_sudo_off"
    finally:
        gate.close()


def test_a_gate_already_holding_the_mode_is_asked_not_told(tmp_path, settings, monkeypatch):
    settings["workstation_network"] = "none"   # the gate boots at none
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        with running_workstation(tmp_path) as ws:
            run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert len(gate.nft.inputs) == 1, "the gate was rewritten with the mode it had"
    finally:
        gate.close()


def test_a_gate_that_does_not_take_the_mode_stops_the_call(tmp_path, settings, monkeypatch):
    """Fail closed: every tool call syncs first, and a command must not run
    under a wider network than the admin set because the gate refused."""
    settings["workstation_network"] = "internet"
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        gate.nft.refuse = True
        with running_workstation(tmp_path) as ws:
            with pytest.raises(WorkstationError) as e:
                run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert "network gate could not put “internet” in force" in e.value.message
        (tmp_path / "gate-pairing" / P.TOKEN_FILENAME).write_text("pwn_wrong\n")
        gate.nft.refuse = False
        with running_workstation(tmp_path) as ws:
            with pytest.raises(WorkstationError) as e:
                run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert e.value.code == "unauthorized"
    finally:
        gate.close()


def test_a_gate_in_front_of_another_host_is_not_claimed_for_this_one(tmp_path, settings,
                                                                      monkeypatch):
    settings["workstation_network"] = "internet"
    gate = RunningGate(tmp_path)
    try:
        port = gate.url.rsplit(":", 1)[1]
        _point_at_gate(monkeypatch, tmp_path, gate, url=f"http://localhost:{port}")
        with running_workstation(tmp_path) as ws:   # the daemon is at 127.0.0.1
            daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert "network_gate" not in daemon and gate.nft.loaded == "none"
        assert wa.network_view("internet", daemon)["state"] == "needs_recreate"
    finally:
        gate.close()


def test_no_gate_at_all_is_said_as_what_it_is(tmp_path, settings):
    settings["workstation_network"] = "none"
    with running_workstation(tmp_path) as ws:
        daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
    assert ws.system.network == "none" and "network_gate" not in daemon
    assert wa.network_view("none", daemon)["state"] == "needs_recreate"


def test_the_tool_path_refuses_to_run_when_the_gate_will_not_hold_the_mode(tmp_path, settings,
                                                                          monkeypatch):
    """The gate boots at `none`, the admin chose `internet`, and the gate's
    `nft` refuses: the command is not run, and the tool says why."""
    from src.agent_tools.workstation_tools import run_in_workstation
    # The install's admin, signed in (`D-2026-10-07-02` §2 — this was the
    # single-user owner, nobody, under `AUTH_ENABLED=false`).
    signed_in(monkeypatch, tmp_path / "auth", members=())
    settings["workstation_network"] = "internet"
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        gate.nft.refuse = True
        with running_workstation(tmp_path) as ws:
            settings["workstation_url"] = ws.url
            settings["workstation_token"] = ws.token
            _desc, result = run(run_in_workstation("bash", "touch ran-here", owner=ADMIN))
            ran = (ws.root / P.account_name(ADMIN) / "ran-here").exists()
        assert result.get("exit_code") == 1 and "network gate" in result.get("error", "")
        assert not ran, "the command ran under a network the admin did not choose"
    finally:
        gate.close()


# ── one word for the panel ───────────────────────────────────────────────────

GATE = {"mode": "internet", "enforcement": "gate"}


@pytest.mark.parametrize("chosen,daemon,state", [
    ("internet", None, "unknown"),
    ("full", {"backend": "container", "sudo": True}, "unrestricted"),
    ("full", {"backend": "container", "network_gate": {"mode": "full"}}, "unrestricted"),
    ("internet", {"backend": "container", "sudo": True, "network_gate": GATE}, "enforced"),
    ("none", {"backend": "container", "network_gate": {"mode": "internet"}}, "pending"),
    ("internet", {"backend": "container", "sudo": True, "root_can_change_network": True,
                  "network_gate": GATE}, "liftable"),
    ("internet", {"backend": "container", "sudo": False, "root_can_change_network": True,
                  "network_gate": GATE}, "enforced_sudo_off"),
    ("internet", {"backend": "vm", "sudo": False, "network_enforcement": "accounts",
                  "network_in_force": "internet"}, "enforced_sudo_off"),
    ("internet", {"backend": "vm", "sudo": True, "network_enforcement": "accounts",
                  "network_in_force": "internet"}, "liftable"),
    ("none", {"backend": "vm", "sudo": False, "network_enforcement": "accounts",
              "network_in_force": "internet"}, "pending"),
    ("internet", {"backend": "container", "sudo": False, "network_enforcement": "none"},
     "needs_recreate"),
    ("none", {"backend": "remote", "sudo": False}, "not_enforced"),
])
def test_each_state_has_its_word(chosen, daemon, state):
    view = wa.network_view(chosen, daemon)
    assert view["state"] == state and view["chosen"] == chosen
    assert view["state"] in wa.NETWORK_STATES


def test_the_status_answer_carries_the_network_as_it_is(tmp_path, settings, monkeypatch):
    settings["workstation_network"] = "internet"
    signed_in(monkeypatch, tmp_path / "auth", members=())
    gate = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        with running_workstation(tmp_path) as ws:
            settings["workstation_url"] = ws.url
            settings["workstation_token"] = ws.token
            status = run(wa.status_for(ADMIN, is_admin=True))
        assert status["state"] == "up"
        assert status["network"] == {"chosen": "internet", "in_force": "internet",
                                     "enforcement": "gate", "state": "enforced"}
        settings["workstation_enabled"] = False
        off = run(wa.status_for(ADMIN, is_admin=True))
        assert off["network"]["state"] == "unknown"
    finally:
        gate.close()


def test_a_person_who_may_not_use_it_is_not_told_the_admins_network(tmp_path, settings,
                                                                    monkeypatch):
    monkeypatch.setattr(wa, "may_use", lambda owner, auth_manager=None: False)
    settings["workstation_network"] = "none"
    status = run(wa.status_for("bob", is_admin=False))
    assert status["state"] == "not_permitted" and status["network"] is None


# ── the overlay, as compose resolves it ──────────────────────────────────────

def _compose(pgid="1234"):
    if not shutil.which("docker"):
        pytest.skip("the docker CLI is not installed here")
    env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_FILE", "PGID")}
    env["PGID"] = pgid
    done = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "-f",
                           "docker/workstation.yml", "config", "--format", "json"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose is not installed here")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_gate_holds_net_admin_and_nothing_else_it_does_not_need():
    gate = _compose()["services"]["workstation-net"]
    assert gate["build"]["context"] == str(ROOT / "workstation")
    assert gate["entrypoint"][-3:] == ["python3", "-m", "workstation.gate"]
    assert gate["cap_drop"] == ["ALL"] and sorted(gate["cap_add"]) == ["CHOWN", "NET_ADMIN"]
    assert not gate.get("privileged") and not gate.get("ports") and not gate.get("devices")
    assert gate.get("network_mode") in (None, ""), "the gate must own its namespace"
    assert gate["networks"]["default"]["aliases"] == [P.DEFAULT_HOST]
    mounts = [(m["source"], m["target"]) for m in gate["volumes"]]
    assert mounts == [("workstation-net-pairing", P.DEFAULT_GATE_PAIRING_DIR)]
    assert gate.get("healthcheck", {}).get("test")


def test_the_workstation_lives_in_the_gates_namespace_without_raw_sockets():
    cfg = _compose()
    ws = cfg["services"]["workstation"]
    assert ws["network_mode"] == "service:workstation-net"
    assert "NET_RAW" in ws["cap_drop"] and not ws.get("cap_add") and not ws.get("privileged")
    assert ws["depends_on"]["workstation-net"]["condition"] == "service_healthy"


def test_only_pantheon_and_the_gate_mount_the_gates_token():
    cfg = _compose()
    holders = {name: [(m["target"], bool(m.get("read_only"))) for m in svc.get("volumes", [])
                      if m.get("source") == "workstation-net-pairing"]
               for name, svc in cfg["services"].items()}
    holders = {k: v for k, v in holders.items() if v}
    assert holders == {"workstation-net": [(P.DEFAULT_GATE_PAIRING_DIR, False)],
                       "pantheon": [(P.DEFAULT_GATE_PAIRING_DIR, True)]}
    pantheon = cfg["services"]["pantheon"]
    assert pantheon["environment"][P.GATE_URL_ENV] == f"http://{P.DEFAULT_HOST}:{P.GATE_PORT}"


# ── the namespace the workstation runs in ────────────────────────────────────

def _names(*rounds):
    """`socket.if_nameindex` as it answers round after round, then the last."""
    seq = list(rounds)

    def names():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return names


def test_a_workstation_left_with_only_loopback_stops_so_it_is_started_again():
    from workstation.__main__ import watch_namespace
    lost = threading.Event()
    eth, lo = [(1, "lo"), (2, "eth0")], [(1, "lo")]
    thread = watch_namespace(lost.set, interval=0.01, names=_names(eth, eth, lo, lo))
    thread.join(timeout=5)
    assert lost.is_set()


def test_one_missed_look_is_not_a_lost_namespace_and_none_is_not_watched():
    from workstation.__main__ import watch_namespace
    lost, stop = threading.Event(), threading.Event()
    eth, lo = [(1, "lo"), (2, "eth0")], [(1, "lo")]
    thread = watch_namespace(lost.set, interval=0.01, names=_names(eth, lo, eth), stopped=stop)
    assert not lost.wait(0.3)
    stop.set()
    thread.join(timeout=5)
    assert watch_namespace(lost.set, names=lambda: [(1, "lo")]) is None


def test_the_gate_runs_alone_as_the_image_copies_it(tmp_path):
    """`python3 -m workstation.gate` from the image's copy of the package, by
    an isolated interpreter: nothing but the standard library."""
    dest = tmp_path / "workstation"
    dest.mkdir()
    for path in (ROOT / "workstation").glob("*.py"):
        shutil.copy(path, dest / path.name)
    helped = subprocess.run(
        [sys.executable, "-I", "-c", "import sys, runpy; sys.path.insert(0, '.'); "
         "runpy.run_module('workstation.gate', run_name='__main__')", "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0, helped.stderr
    assert "network gate" in helped.stdout and str(P.GATE_PORT) in helped.stdout
