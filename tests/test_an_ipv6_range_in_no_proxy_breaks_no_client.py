# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1013` — an IPv6 range in `NO_PROXY` breaks no client.

Measured with httpx 0.28.1: with `NO_PROXY=localhost,fd00::/8`, `httpx.Client()`
and `httpx.AsyncClient()` raise `InvalidURL: Invalid port: ':'` at construction —
httpx turns `fd00::/8` into the pattern `all://[fd00::/8]` and its own URL parser
refuses it — whether or not a proxy is set. So every client that read the
environment failed: model calls, the workstation, `httpx.get`. A *single* IPv6
address is read fine: the sandbox this was measured in has `::1` and `::` in its
`NO_PROXY`, and its clients build (a case below says so).

Now httpx's reader is wrapped once at start (`paced_http.guard_environment_reader`,
called by `app.py` and the image MCP server): an entry httpx cannot parse is kept
from httpx, said in the log, and nowhere else — the environment is untouched,
and `direct_mounts` still reads the range, so `fd00::5` still goes direct.

Driven (`Law 20`): a proxy that writes down every connection it is handed and
forwards none (`B982`'s), a model server that answers like one, the real
workstation daemon, Pantheon's real model call and workstation client, and a
fresh process importing the app the way it starts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from src import paced_http
from test_a_range_in_no_proxy_is_honoured import Recorder

REPO = Path(__file__).resolve().parent.parent
V6 = "localhost,fd00::/8"
TOKEN = "pws_b1013-the-token-for-the-workstation"


@pytest.fixture
def unguarded(monkeypatch):
    """httpx's own reader in place, as before start. Whatever was there — an
    earlier case's guard, or the app's — is put back afterwards (one patch,
    undone in one step: `B1002`)."""
    import httpx._client as hc
    import httpx._utils as hu
    monkeypatch.setattr(hc, "get_environment_proxies", hu.get_environment_proxies)


@pytest.fixture
def v6(monkeypatch, unguarded):
    rec = Recorder()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, rec.url)
    for name in ("ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, V6)
    monkeypatch.setattr(paced_http, "_SAID", set(), raising=False)
    yield rec
    rec.close()


# ── the premise, and what this sandbox has ───────────────────────────────────

def test_the_premise_httpx_alone_builds_no_client(v6):
    for build in (httpx.Client, httpx.AsyncClient):
        with pytest.raises(httpx.InvalidURL):
            build()
    with pytest.raises(httpx.InvalidURL):
        httpx.get("http://localhost:9/")


def test_single_ipv6_addresses_as_in_this_sandbox_were_never_the_problem(monkeypatch, unguarded):
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "localhost,127.0.0.1,::1,127.0.0.0/8,::")
    with httpx.Client() as c:
        assert {"all://[::1]", "all://[::]"} <= {m.pattern for m in c._mounts}


# ── after start ──────────────────────────────────────────────────────────────

def test_after_start_every_client_builds_and_keeps_the_rest(v6):
    assert paced_http.guard_environment_reader() == ("fd00::/8",)
    for build in (httpx.Client, httpx.AsyncClient):
        client = build()
        patterns = {m.pattern for m in client._mounts}
        # The proxies and every entry httpx can read are still httpx's.
        assert patterns == {"all://localhost", "http://", "https://"}, patterns
        asyncio.run(client.aclose()) if isinstance(client, httpx.AsyncClient) else client.close()


class _Model(BaseHTTPRequestHandler):
    """Answers a chat completion as an OpenAI-compatible server does."""

    def do_POST(self):  # noqa: N802 — the stdlib's name
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"id": "c1", "object": "chat.completion", "model": "m",
                           "choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant", "content": "pong"}}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_a_model_call_succeeds(v6, model_server, monkeypatch):
    """The row's `Verify:`, first half: Pantheon's real model call."""
    from src import llm_core
    paced_http.guard_environment_reader()
    # The process-wide client, built fresh in this environment (`B1014` keys it
    # by how its destination is routed).
    monkeypatch.setattr(llm_core, "_http_client", None)
    monkeypatch.setattr(llm_core, "_direct_clients", {}, raising=False)
    answer = asyncio.run(llm_core.llm_call_async(
        f"http://localhost:{model_server}/v1", "m", [{"role": "user", "content": "ping"}],
        max_retries=1))
    assert answer == "pong"
    assert v6.lines == [], "the model call went to the proxy"


def test_a_workstation_call_succeeds(v6, tmp_path):
    """The row's `Verify:`, second half: Pantheon's real workstation client and
    the real daemon."""
    from src.workstation_client import WorkstationClient, account_for
    from workstation import protocol as P
    from workstation.agentd import SingleUserSystem, make_server
    paced_http.guard_environment_reader()
    server = make_server(SingleUserSystem(tmp_path / "homes", backend="remote"), TOKEN,
                         bind="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    try:
        c = WorkstationClient(f"http://localhost:{server.server_address[1]}", TOKEN)
        assert asyncio.run(c.health())["agent"] == P.AGENT_NAME
        assert asyncio.run(c.exec(account_for("ann"), "echo hi"))["stdout"].strip() == "hi"
    finally:
        server.shutdown()
        server.server_close()
    assert v6.lines == []


def test_fd00_5_is_still_direct(v6):
    """The row's `Verify:`, last clause. No IPv6 route is needed to tell: sent
    direct, the connection fails here without the proxy hearing of it; left to
    the environment, the proxy is handed it."""
    paced_http.guard_environment_reader()
    url = "https://[fd00::5]:7040/"
    mounts = paced_http.direct_mounts(url)
    assert mounts == {"all://[fd00::5]": None}
    with httpx.Client(mounts=mounts, timeout=3) as direct:
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            direct.get(url)
    assert v6.lines == [], "sent to the proxy though NO_PROXY's range holds it"
    with httpx.Client(timeout=5) as environment:
        with pytest.raises(httpx.HTTPError):
            environment.get(url)
    # Measured: httpcore 1.0.9 writes this authority without its brackets.
    assert v6.lines == ["CONNECT fd00::5:7040 HTTP/1.1"], "control: the proxy is real"


def test_it_is_said_once_at_start_and_the_environment_is_untouched(v6, caplog):
    import httpx._utils as hu
    caplog.set_level(logging.WARNING, logger="src.paced_http")
    paced_http.guard_environment_reader()
    paced_http.guard_environment_reader()
    httpx.Client().close()
    said = [r.getMessage() for r in caplog.records if r.name == "src.paced_http"]
    assert len(said) == 1 and "fd00::/8" in said[0] and "B1013" in said[0], said
    # Kept from httpx and nowhere else.
    before = hu.get_environment_proxies()
    assert paced_http.readable_environment_proxies() == {
        k: v for k, v in before.items() if k != "all://[fd00::/8]"}
    assert os.environ["NO_PROXY"] == os.environ["no_proxy"] == V6
    assert any(str(net) == "fd00::/8" for net in paced_http.no_proxy_ranges())


def test_nothing_is_kept_from_httpx_that_it_can_read(monkeypatch, unguarded, caplog):
    """This sandbox's own `NO_PROXY` (single IPv6 addresses, IPv4 ranges): the
    guard keeps nothing from httpx and says nothing."""
    import httpx._utils as hu
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "localhost,127.0.0.1,::1,127.0.0.0/8,::,10.0.0.0/8")
    caplog.set_level(logging.WARNING, logger="src.paced_http")
    assert paced_http.guard_environment_reader() == ()
    assert paced_http.readable_environment_proxies() == hu.get_environment_proxies()
    assert not [r for r in caplog.records if r.name == "src.paced_http"]


# ── the processes that build clients install it at start ─────────────────────

_PROBE = """
import httpx
{imports}
httpx.Client().close()
c = httpx.AsyncClient()
print("built")
"""


@pytest.mark.parametrize("imports", [
    "import app",
    "import importlib.util as u\n"
    "spec = u.spec_from_file_location('image_gen_server', 'mcp_servers/image_gen_server.py')\n"
    "spec.loader.exec_module(u.module_from_spec(spec))",
], ids=["app", "image-mcp-server"])
def test_a_process_pantheon_starts_builds_its_clients(tmp_path, imports):
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("no_proxy", "http_proxy", "https_proxy", "all_proxy")}
    env.update({"NO_PROXY": V6, "HTTPS_PROXY": "http://127.0.0.1:9",
                "PANTHEON_DATA_DIR": str(tmp_path), "PYTHONPATH": str(REPO)})
    done = subprocess.run([sys.executable, "-c", _PROBE.format(imports=imports)], cwd=REPO,
                          env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "built" in done.stdout, done.stderr[-3000:]
    assert "NO_PROXY holds fd00::/8" in done.stderr
