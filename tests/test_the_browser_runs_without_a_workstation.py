# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner (2026-10-31): *"the browser should be able to run without needing a
workstation/VM entirely — and be linkable to the LLM itself as well"*, and
*"turning it on does nothing"* of the workstation.

The browser half: `src/local_browser.py` hosts `workstation/browser.py`'s
Firefox in Pantheon itself for a person the workstation would not answer, the
window's routes and the `agent_browser` tool reach it through `browser_for`,
and every connection it makes goes through a proxy that keeps it on the public
web. The workstation half: the stack's VM host makes its image the first time
the workstation is switched on, not when it starts.

Driven: the real proxy on a real socket, the real routes through the app, the
real tool through its handler; Firefox itself is the one stand-in (it is not
on this machine — `test_the_agent_browser_is_the_persons_own.py` drives the
same `AccountBrowser` against a real one where it is).
"""

from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path

import pytest

import src.local_browser as LB
from src.workstation_client import WorkstationError
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


# ── where it may go ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("address, allowed", [
    ("127.0.0.1", False), ("::1", False), ("169.254.169.254", False),
    ("10.0.0.5", False), ("172.18.0.3", False), ("192.168.1.1", False),
    ("93.184.215.14", True), ("2606:2800:21f:cb07:6820:80da:af6b:8b2c", True),
])
def test_it_reaches_public_addresses_only(monkeypatch, address, allowed):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(LB.socket, "getaddrinfo",
                        lambda host, port, **kw: [(family, socket.SOCK_STREAM, 6, "", (address, port))])
    got, why = LB._allowed_address("somewhere.example", 443)
    assert (got == address) is allowed
    assert bool(why) is (not allowed)


def test_one_private_answer_among_public_ones_refuses_the_name(monkeypatch):
    monkeypatch.setattr(LB.socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))])
    assert LB._allowed_address("rebind.example", 80)[0] is None


def _ask(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        out = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                return out
            out += chunk


def test_the_proxy_refuses_this_machine_however_it_is_asked():
    """A real service on loopback, asked for through the proxy by CONNECT and
    by an absolute URL: both refused, and the service never sees a byte."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(0.5)
    target = srv.getsockname()[1]
    proxy = LB.GuardProxy()
    try:
        port = proxy.port()
        for req in (f"CONNECT 127.0.0.1:{target} HTTP/1.1\r\nHost: 127.0.0.1:{target}\r\n\r\n",
                    f"GET http://localhost:{target}/secret HTTP/1.1\r\nHost: localhost\r\n\r\n",
                    f"CONNECT [::1]:{target} HTTP/1.1\r\n\r\n"):
            answer = _ask(port, req.encode())
            assert answer.startswith(b"HTTP/1.1 403"), answer[:80]
            assert b"does not open addresses on this machine" in answer
        with pytest.raises(socket.timeout):
            srv.accept()
    finally:
        proxy.stop()
        srv.close()


def test_the_profile_sends_everything_through_the_proxy():
    prefs = LB.proxy_prefs(41234)
    for line in ('user_pref("network.proxy.type", 1);',
                 'user_pref("network.proxy.http_port", 41234);',
                 'user_pref("network.proxy.ssl_port", 41234);',
                 'user_pref("network.proxy.no_proxies_on", "");',
                 'user_pref("network.proxy.allow_hijacking_localhost", true);',
                 'user_pref("network.proxy.failover_direct", false);',
                 'user_pref("media.peerconnection.enabled", false);',
                 'user_pref("network.http.http3.enable", false);',
                 'user_pref("network.trr.mode", 5);'):
        assert line in prefs, line


def test_the_proxy_prefs_are_written_after_the_shipped_ones(tmp_path):
    """`AccountBrowser.extra_prefs` lands in `user.js`, after `USER_JS`."""
    from workstation import browser as B
    b = B.AccountBrowser([], {}, tmp_path / "profile", True)
    b.extra_prefs = LB.proxy_prefs(9)

    class Stop(Exception):
        pass

    def no_launch(*a, **kw):
        raise Stop()

    import workstation.browser as mod
    orig_which, orig_popen = mod.find_firefox, mod.subprocess.Popen
    mod.find_firefox, mod.subprocess.Popen = (lambda: "/bin/true"), no_launch
    try:
        with pytest.raises(Stop):
            b.start()
    finally:
        mod.find_firefox, mod.subprocess.Popen = orig_which, orig_popen
    text = (tmp_path / "profile" / "user.js").read_text()
    assert text.startswith(B.USER_JS) and text.endswith(LB.proxy_prefs(9))


def test_firefox_is_found_by_either_name(monkeypatch, tmp_path):
    from workstation import browser as B
    monkeypatch.delenv(B.FIREFOX_ENV, raising=False)
    monkeypatch.setattr(B.shutil, "which", lambda n: "/usr/bin/firefox-esr" if n == "firefox-esr" else None)
    assert B.find_firefox() == "/usr/bin/firefox-esr"
    exe = tmp_path / "ff"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv(B.FIREFOX_ENV, str(exe))
    assert B.find_firefox() == str(exe)
    monkeypatch.setenv(B.FIREFOX_ENV, str(tmp_path / "missing"))
    assert B.find_firefox() is None


def test_the_image_installs_firefox_for_it():
    text = (ROOT / "Dockerfile").read_text()
    assert "    firefox-esr \\\n" in text
    stack = (ROOT / "docker-compose.yml").read_text()
    assert 'shm_size: "1gb"' in stack


# ── whose browser ─────────────────────────────────────────────────────────────

@pytest.fixture
def no_workstation(monkeypatch):
    import src.workstation_access as wa

    def refuse(owner, auth_manager=None):
        raise WorkstationError("off", wa.OFF_SENTENCE)

    monkeypatch.setattr(wa, "workstation_for", refuse)
    monkeypatch.setattr(LB, "may_use", lambda owner, auth_manager=None: True)
    monkeypatch.setattr(LB, "firefox_here", lambda: True)


def test_without_a_workstation_it_is_pantheons_own(no_workstation):
    client, account = LB.browser_for("alice")
    assert isinstance(client, LB.LocalBrowserClient)
    assert account == P.account_name("alice") if hasattr(P, "account_name") else account
    assert LB.unavailable_reason("alice") is None
    assert LB.runs_in(client) is None


def test_with_a_workstation_it_is_the_workstations(monkeypatch):
    import src.workstation_access as wa
    sentinel = object()
    monkeypatch.setattr(wa, "workstation_for", lambda owner, auth_manager=None: (sentinel, "pws-alice"))
    assert LB.browser_for("alice") == (sentinel, "pws-alice")
    assert LB.runs_in(sentinel) == LB.RUNS_IN_WORKSTATION


def test_no_firefox_and_no_workstation_says_both(no_workstation, monkeypatch):
    monkeypatch.setattr(LB, "firefox_here", lambda: False)
    with pytest.raises(WorkstationError) as caught:
        LB.browser_for("alice")
    assert caught.value.message == LB.NO_FIREFOX_SENTENCE
    assert "Settings → Workstation" in LB.unavailable_reason("alice")


def test_a_person_without_the_privilege_has_neither(no_workstation, monkeypatch):
    monkeypatch.setattr(LB, "may_use", lambda owner, auth_manager=None: False)
    with pytest.raises(WorkstationError) as caught:
        LB.browser_for("alice")
    assert caught.value.code == "not_permitted"


def test_an_api_token_is_not_offered_it(no_workstation):
    assert LB.unavailable_reason("alice", delegated_credential=True) == LB.TOKEN_SENTENCE


# ── one holder, as on the workstation ─────────────────────────────────────────

class _FakeBrowser:
    def __init__(self):
        self.done = []
        self.extra_prefs = ""

    def act(self, action, body, who="agent"):
        self.done.append((who, action))
        return {"ok": True, "action": action, "url": "https://example.org/", "title": "Example",
                "tabs": [{"tab": "t1", "url": "https://example.org/", "current": True}]}

    def frame(self, if_none_match="", since=0):
        if if_none_match == "same":
            return None
        return {"mime": "image/png", "data_b64": "aGk=", "digest": "0123456789abcdef",
                "width": P.BROWSER_WIDTH, "height": P.BROWSER_HEIGHT, "url": "https://example.org/",
                "title": "Example", "tabs": [], "activity": [], "seq": 0}

    def note(self, action, body, who="person"):
        return {"ok": True, "action": action, "notes": []}


@pytest.fixture
def host(tmp_path, monkeypatch):
    h = LB.LocalBrowsers(tmp_path / "browser")
    fake = _FakeBrowser()
    monkeypatch.setattr(h.browsers, "get", lambda account: fake)
    yield h, fake
    h.stop_all()


def test_a_person_who_took_over_makes_the_agent_wait(host):
    h, fake = host
    client = LB.LocalBrowserClient(h)
    run(client.browser("pws-alice", "open", url="https://example.org/"))
    assert run(client.control("pws-alice", "person"))["holder"] == "person"
    with pytest.raises(WorkstationError) as caught:
        run(client.browser("pws-alice", "click", ref=1))
    assert caught.value.code == "busy"
    # The person's own hand, the frame and the notes still go through.
    run(client.browser("pws-alice", "click", holder="person", ref=1))
    assert run(client.browser("pws-alice", "frame"))["digest"] == "0123456789abcdef"
    assert run(client.browser("pws-alice", "frame", if_none_match="same")) is None
    assert run(client.browser("pws-alice", "notes"))["ok"]
    assert run(client.ensure("pws-alice"))["holder"] == "person"
    run(client.control("pws-alice", "agent"))
    run(client.browser("pws-alice", "click", ref=1))
    assert fake.done == [("agent", "open"), ("person", "click"), ("agent", "click")]
    # The proxy's port is in the profile it starts with.
    assert "network.proxy.http_port" in fake.extra_prefs


def test_a_browser_nobody_used_for_a_while_is_stopped(host, monkeypatch):
    h, _fake = host
    stopped = []
    monkeypatch.setattr(h.browsers, "stop", lambda account: stopped.append(account))
    client = LB.LocalBrowserClient(h)
    run(client.browser("pws-bob", "read"))
    h._used["pws-bob"] -= LB.IDLE_STOP_S + 1
    run(client.browser("pws-alice", "read"))
    assert stopped == ["pws-bob"]


def test_the_tool_drives_pantheons_own_browser(host, monkeypatch):
    """`agent_browser`, through its handler, on Pantheon's own browser: the
    result carries no `ran_in` (that is said of the workstation only)."""
    h, fake = host
    from src.agent_tools import browser_tools as BT

    async def ready(owner, auth_manager=None):
        return LB.LocalBrowserClient(h), "pws-alice"

    monkeypatch.setattr(LB, "ready_browser", ready)
    out = run(BT.BrowserTool().execute('{"action": "open", "url": "https://example.org/"}',
                                       {"owner": "alice"}))
    assert out["exit_code"] == 0 and "ran_in" not in out, out
    assert "Example" in out["output"]
    assert fake.done == [("agent", "open")]


# ── the window's routes reach it ─────────────────────────────────────────────

def test_the_windows_routes_answer_from_pantheons_own(host, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.workstation_routes as R

    h, fake = host
    monkeypatch.setattr(R, "require_user", lambda request: "alice")
    monkeypatch.setattr(LB, "browser_for",
                        lambda owner, auth_manager=None: (LB.LocalBrowserClient(h), "pws-alice"))
    app = FastAPI()
    app.include_router(R.setup_workstation_routes())
    c = TestClient(app)
    frame = c.get("/api/workstation/browser").json()
    assert frame["runs_in"] == "pantheon" and frame["digest"] == "0123456789abcdef"
    assert c.get("/api/workstation/browser?if_none_match=same").status_code == 304
    assert c.post("/api/workstation/control", json={"holder": "person"}).json()["holder"] == "person"
    assert c.get("/api/workstation/control").json()["holder"] == "person"
    acted = c.post("/api/workstation/browser", json={"action": "open", "url": "https://example.org/"})
    assert acted.status_code == 200 and acted.json()["title"] == "Example"


# ── the workstation half: its image waits until it is switched on ─────────────

def test_the_stacks_vm_host_makes_its_image_when_first_asked(tmp_path, monkeypatch):
    from workstation import vm
    base = tmp_path / "base.img"
    base.write_bytes(b"x")
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", base_image=base, payload=vm.PACKAGE_DIR,
                     image_on_first_use=True)
    assert fleet.image_state == "waiting" and fleet.machine()["image"] == "waiting"
    assert "waiting" in P.MACHINE_IMAGE_STATES
    started = threading.Event()
    monkeypatch.setattr(fleet, "prepare_image", started.set)
    with pytest.raises(vm.WorkstationError) as caught:
        fleet.ready("pws-alice")
    assert "starts making it now" in caught.value.message
    assert started.wait(5) and fleet.image_state == "preparing"
    assert fleet.want_image() is False, "asked once, made once"


def test_switching_it_on_is_what_asks_for_the_image(tmp_path, monkeypatch):
    """`config` is what Pantheon sends once the switch is on."""
    from workstation import vm
    base = tmp_path / "base.img"
    base.write_bytes(b"x")
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", base_image=base, payload=vm.PACKAGE_DIR,
                     image_on_first_use=True)
    asked = []
    monkeypatch.setattr(fleet, "want_image", lambda: asked.append(True) or True)
    station = vm.VmStation(fleet, "pws_token")
    station.config({"sudo": True})
    assert asked == [True]


def test_pantheon_sends_config_to_a_host_that_waits(monkeypatch):
    import src.workstation_access as wa

    class Client:
        def __init__(self):
            self.configs = []

        async def health(self):
            return {"sudo": True, "network": wa.network_setting(), "admins": wa.admin_accounts(),
                    "backend": "vm", "machine": {"accel": "kvm", "image": "waiting"}}

        async def config(self, **kw):
            self.configs.append(kw)
            return {}

    monkeypatch.setattr(wa, "sudo_wanted", lambda backend=None: True)
    monkeypatch.setattr(wa.wc, "gate_for", lambda client: None)
    c = Client()
    daemon = run(wa.sync_config(c))
    assert c.configs == [{"sudo": True}]
    assert daemon["machine"]["image"] == "preparing"


def test_a_second_vm_host_on_the_same_volume_does_not_start(tmp_path):
    from workstation import vm
    first = vm.hold_state(tmp_path / "state")
    assert first is not None
    try:
        import subprocess
        import sys
        code = ("import sys; from pathlib import Path; from workstation import vm; "
                f"sys.exit(0 if vm.hold_state(Path({str(tmp_path / 'state')!r})) is None else 1)")
        assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
    finally:
        first.close()


# ── a workstation that is on but not ready (2026-10-31, the owner's local test) ──

class _NotReady:
    """A workstation client whose machine cannot start yet."""

    def __init__(self, code="unavailable"):
        self.code = code
        self.asked = []

    async def _no(self, name):
        self.asked.append(name)
        raise WorkstationError(self.code, "The workstation is still making the machine image.")

    async def browser(self, account, action, **kw):
        return await self._no("browser")

    async def control(self, account, holder):
        return await self._no("control")

    async def ensure(self, account):
        return await self._no("ensure")

    async def names(self, account, names, pins):
        return await self._no("names")


def test_a_workstation_still_making_its_image_leaves_the_browser_to_pantheons_own(host):
    """The owner's screenshot: the workstation on and answering, its machine
    image still being made — and *No browser to show*. Every call the
    workstation cannot take now is Pantheon's own browser's."""
    h, fake = host
    ws = _NotReady()
    client = LB.FallbackBrowser(ws, LB.LocalBrowserClient(h))
    frame = run(client.browser("pws-alice", "frame"))
    assert frame["digest"] == "0123456789abcdef" and LB.runs_in(client) is None
    assert run(client.control("pws-alice", "person"))["holder"] == "person"
    assert run(client.ensure("pws-alice"))["holder"] == "person"
    assert ws.asked == ["browser", "control", "ensure"]
    # Mapped names stay the workstation's: refused, so not remembered as sent.
    with pytest.raises(WorkstationError):
        run(client.names("pws-alice", {}, []))


def test_a_refusal_that_is_not_about_readiness_is_not_papered_over(host):
    h, _fake = host
    client = LB.FallbackBrowser(_NotReady("bad_request"), LB.LocalBrowserClient(h))
    with pytest.raises(WorkstationError) as caught:
        run(client.browser("pws-alice", "open", url="https://example.org/"))
    assert caught.value.code == "bad_request"


def test_the_tool_uses_pantheons_browser_while_the_workstation_is_not_ready(monkeypatch):
    import src.workstation_access as wa
    ws = _NotReady()
    monkeypatch.setattr(wa, "workstation_for", lambda owner, auth_manager=None: (ws, "pws-alice"))
    monkeypatch.setattr(LB, "may_use", lambda owner, auth_manager=None: True)
    monkeypatch.setattr(LB, "firefox_here", lambda: True)

    async def not_ready(owner, auth_manager=None):
        raise WorkstationError("unavailable", "The workstation is still making the machine image.")

    monkeypatch.setattr(wa, "ensure_ready", not_ready)
    client, account = run(LB.ready_browser("alice"))
    assert isinstance(client, LB.LocalBrowserClient) and account == "pws-alice"
    assert client.owner == "alice"


# ── full access: the LAN, when the admin lets agents reach it ─────────────────

def test_with_lan_reach_the_lan_opens_but_never_pantheons_own_network(monkeypatch):
    monkeypatch.setattr(LB, "_own_networks", lambda: [__import__("ipaddress").ip_network("172.18.0.0/16")])

    def answer(address):
        monkeypatch.setattr(LB.socket, "getaddrinfo",
                            lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))])

    answer("192.168.1.20")
    assert LB._allowed_address("nas.lan", 80, allow_lan=True)[0] == "192.168.1.20"
    assert LB._allowed_address("nas.lan", 80, allow_lan=False)[0] is None
    answer("172.18.0.4")
    assert "Pantheon's own network" in LB._allowed_address("chromadb", 8000, allow_lan=True)[1]
    for always in ("127.0.0.1", "169.254.169.254"):
        answer(always)
        assert LB._allowed_address("x", 80, allow_lan=True)[0] is None, always


def test_the_lan_is_asked_of_each_person(tmp_path, monkeypatch):
    import src.outbound_fetch as OF
    h = LB.LocalBrowsers(tmp_path / "b")
    try:
        monkeypatch.setattr(OF, "_lan_reach_on", lambda: True)
        monkeypatch.setattr(OF, "may_reach_lan", lambda owner: owner == "alice")
        h._owners.update({"pws-alice": "alice", "pws-bob": "bob"})
        assert h.proxy_for("pws-alice").allow_lan() is True
        assert h.proxy_for("pws-bob").allow_lan() is False
        assert h.proxy_for("pws-alice") is h.proxy_for("pws-alice")
        monkeypatch.setattr(OF, "_lan_reach_on", lambda: False)
        assert h.proxy_for("pws-alice").allow_lan() is False
    finally:
        h.stop_all()
