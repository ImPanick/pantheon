# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1014` — every httpx client honours a range in `NO_PROXY`.

httpx reads names and single addresses in `NO_PROXY`, not ranges (`B982`).
`paced_http`'s own clients and the workstation client read the ranges
(`direct_mounts`); 58 `httpx.Client(`/`httpx.AsyncClient(` constructions in 22
files did not, so on a host with an operator's proxy a model server, Pantheon's
own API on `127.0.0.2`, an embedding server or a LAN ntfy in a named range was
sent to the proxy anyway. Now every construction says how it is routed —
`mounts=paced_http.direct_mounts(url)`, or `transport=`/`trust_env=False`
where httpx reads no environment proxy at all — and `check-outbound.py` fails
on one that does not. The six that call a third party (an ntfy and a Discord
test, a reminder's webhook and ntfy, Google's token exchange, Miniflux) now go
through `paced_http` as well, so the limiter sees them.

Driven (`Law 20`): a proxy that writes down every connection it is handed and
forwards none (`B982`'s), servers on `127.0.0.2` — in the range `127.0.0.0/8`,
and not named — answering like a model server, Pantheon's own API, an
embedding server and an ntfy; Pantheon's real model call, cookbook tool,
embedding client and reminder; each with its control (no range: the proxy is
handed it). And the checker, run on the tree and on files written for it.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from test_a_range_in_no_proxy_is_honoured import Recorder

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-outbound.py"
RANGES = "localhost,127.0.0.0/8"


@pytest.fixture
def proxy(monkeypatch):
    rec = Recorder()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, rec.url)
    for name in ("ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, RANGES)
    yield rec
    rec.close()


def _no_range(monkeypatch):
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "localhost")


class _Answers(BaseHTTPRequestHandler):
    """Answers by path, and writes down what it was asked."""
    answers: dict = {}
    seen: list = []

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).seen.append((self.command, self.path.split("?")[0], body))
        payload = type(self).answers.get(self.path.split("?")[0], {})
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _answer  # noqa: N815 — the stdlib's names

    def log_message(self, *a):
        pass


@pytest.fixture
def lan():
    """A server on 127.0.0.2: in `127.0.0.0/8`, not named in `NO_PROXY`."""
    handler = type("Handler", (_Answers,), {"answers": {}, "seen": []})
    server = ThreadingHTTPServer(("127.0.0.2", 0), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    server.base = f"http://127.0.0.2:{server.server_address[1]}"
    yield server
    server.shutdown()
    server.server_close()


# ── the operator's model server ──────────────────────────────────────────────

def _model_call(lan, monkeypatch):
    from src import llm_core
    lan.RequestHandlerClass.answers["/v1/chat/completions"] = {
        "id": "c1", "object": "chat.completion", "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "pong"}}]}
    monkeypatch.setattr(llm_core, "_http_client", None)
    monkeypatch.setattr(llm_core, "_direct_clients", {}, raising=False)
    return asyncio.run(llm_core.llm_call_async(
        f"{lan.base}/v1", "m", [{"role": "user", "content": "ping"}], max_retries=1))


def test_a_model_server_in_a_range_is_reached_direct(proxy, lan, monkeypatch):
    assert _model_call(lan, monkeypatch) == "pong"
    assert proxy.lines == [], "the model call was handed to the proxy"


def test_control_without_the_range_the_proxy_is_handed_the_model_call(proxy, lan, monkeypatch):
    _no_range(monkeypatch)
    with pytest.raises(Exception):
        _model_call(lan, monkeypatch)
    assert proxy.lines and proxy.lines[0].startswith(f"POST {lan.base}/v1/chat/completions")


def test_the_shared_model_client_is_shared_except_where_a_range_routes(proxy, monkeypatch):
    from src import llm_core
    monkeypatch.setattr(llm_core, "_http_client", None)
    monkeypatch.setattr(llm_core, "_direct_clients", {})
    lan_a = llm_core._client_for("http://127.0.0.2:1/v1/chat/completions")
    assert lan_a is llm_core._client_for("http://127.0.0.2:1/v1/models")
    cloud = llm_core._client_for("https://api.example.test/v1/chat/completions")
    assert cloud is llm_core._get_http_client() and cloud is not lan_a
    assert llm_core._client_for("https://8.8.8.8/v1") is cloud


# ── Pantheon's own API, reached by an agent tool ─────────────────────────────

def _cookbook(lan, monkeypatch):
    import src.tool_implementations as facade
    from src.tools import cookbook
    monkeypatch.setattr(facade, "_INTERNAL_BASE", lan.base)
    lan.RequestHandlerClass.answers["/api/cookbook/state"] = {
        "env": {"servers": [{"name": "gpu", "host": "10.0.0.7"}]}}
    return asyncio.run(cookbook._cookbook_servers())


def test_pantheons_own_api_in_a_range_is_reached_direct(proxy, lan, monkeypatch):
    got = _cookbook(lan, monkeypatch)
    assert [h["host"] for h in got["hosts"]] == ["10.0.0.7"], got
    assert proxy.lines == []


def test_control_without_the_range_the_tool_call_goes_to_the_proxy(proxy, lan, monkeypatch):
    _no_range(monkeypatch)
    assert _cookbook(lan, monkeypatch)["hosts"] == []
    assert proxy.lines == [f"GET {lan.base}/api/cookbook/state HTTP/1.1"]


# ── an embedding server ──────────────────────────────────────────────────────

def test_an_embedding_server_in_a_range_is_reached_direct(proxy, lan):
    from src.embeddings import EmbeddingClient
    lan.RequestHandlerClass.answers["/v1/embeddings"] = {
        "data": [{"index": 0, "embedding": [3.0, 4.0]}]}
    vecs = EmbeddingClient(url=f"{lan.base}/v1/embeddings", model="e").encode(["x"])
    assert vecs.shape == (1, 2)
    assert proxy.lines == []


# ── a third party, paced as well as routed ───────────────────────────────────

def _remind(lan, monkeypatch):
    from unittest.mock import patch

    from routes.note_routes import dispatch_reminder
    from src.rate_limiter import outbound
    paced = []

    async def acquire_async(host, **k):
        paced.append(host)
        return 0.0

    monkeypatch.setattr(outbound, "acquire_async", acquire_async)
    ntfy = [{"preset": "ntfy", "enabled": True, "base_url": lan.base, "api_key": "",
             "name": "ntfy"}]
    with patch("src.integrations.load_integrations", return_value=ntfy):
        result = asyncio.run(dispatch_reminder(
            "Title", "Body", note_id="", queue_browser=False,
            settings_override={"reminder_channel": "ntfy", "reminder_llm_synthesis": False,
                               "reminder_ntfy_topic": "reminders"}))
    return result, paced


def test_a_reminder_to_a_lan_ntfy_is_paced_and_reached_direct(proxy, lan, monkeypatch):
    result, paced = _remind(lan, monkeypatch)
    assert result["ntfy_sent"] is True, result
    assert [(m, p) for m, p, _ in lan.RequestHandlerClass.seen] == [("POST", "/reminders")]
    assert paced == ["127.0.0.2"], "the limiter did not see the send"
    assert proxy.lines == []


def test_control_without_the_range_the_reminder_goes_to_the_proxy(proxy, lan, monkeypatch):
    _no_range(monkeypatch)
    result, _ = _remind(lan, monkeypatch)
    assert result["ntfy_sent"] is False
    assert proxy.lines == [f"POST {lan.base}/reminders HTTP/1.1"]


@pytest.mark.parametrize("preset, path", [("discord_webhook", "/hook"), ("ntfy", "/reminders")])
def test_an_integrations_test_button_is_paced_and_reached_direct(proxy, lan, monkeypatch,
                                                                 preset, path):
    """Settings' *Test* on a Discord webhook or an ntfy server: the real route,
    one send, seen by the limiter, sent direct."""
    from types import SimpleNamespace

    from routes import auth_routes
    from src.rate_limiter import outbound
    paced = []

    async def acquire_async(host, **k):
        paced.append(host)
        return 0.0

    monkeypatch.setattr(outbound, "acquire_async", acquire_async)
    base = lan.base + ("/hook" if preset == "discord_webhook" else "")
    monkeypatch.setattr(auth_routes, "get_integration",
                        lambda i: {"id": i, "preset": preset, "base_url": base})
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: {"reminder_ntfy_topic": "reminders"})
    router = auth_routes.setup_auth_routes(SimpleNamespace(
        get_username_for_token=lambda token: "admin", is_admin=lambda user: True))
    endpoint = next(r.endpoint for r in router.routes
                    if r.path.endswith("/integrations/{integration_id}/test"))
    result = asyncio.run(endpoint("i1", SimpleNamespace(cookies={})))
    assert result["ok"] is True, result
    assert [(m, p) for m, p, _ in lan.RequestHandlerClass.seen] == [("POST", path)]
    assert paced == ["127.0.0.2"], "the limiter did not see the send"
    assert proxy.lines == []


# ── the checker ──────────────────────────────────────────────────────────────

def _run(args, cwd=ROOT):
    return subprocess.run([sys.executable, str(cwd / ".pantheon" / "check-outbound.py"), *args],
                          cwd=cwd, capture_output=True, text=True, timeout=300)


def test_no_client_in_the_tree_leaves_its_routing_to_httpx():
    """The row's `Verify:` — and the budgets CI pins hold."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    line = ci.split("check-outbound.py", 1)[1].splitlines()[0].split()
    budget, env_budget = line[line.index("--max") + 1], line[line.index("--max-env") + 1]
    r = _run(["--max", budget, "--max-env", env_budget])
    assert r.returncode == 0, r.stdout[-3000:]
    assert "httpx clients that say nothing of how they are routed 0" in r.stdout


@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    (dst / ".pantheon").mkdir(parents=True)
    (dst / "src").mkdir()
    (dst / ".pantheon" / "check-outbound.py").write_bytes(CHECKER.read_bytes())
    return dst


@pytest.mark.parametrize("construction, said", [
    ("httpx.AsyncClient(timeout=5)", False),
    ("httpx.AsyncClient(timeout=5, mounts=None)", False),
    ("httpx.AsyncClient(timeout=5, mounts=paced_http.direct_mounts(url))", True),
    ("httpx.AsyncClient(timeout=5, transport=t)", True),
    ("httpx.AsyncClient(timeout=5, trust_env=False)", True),
    ("httpx.AsyncClient(timeout=5, trust_env=True)", False),
], ids=["nothing", "mounts-none", "direct-mounts", "transport", "no-env", "env"])
def test_a_construction_that_says_nothing_fails_with_no_budget(repo, construction, said):
    (repo / "src" / "thing.py").write_text(
        "import httpx\nfrom src import paced_http\n"
        "async def fetch(url, t=None):\n"
        f"    async with {construction} as client:\n"
        "        return await paced_http.request('GET', url, client=client)\n",
        encoding="utf-8")
    r = _run(["--max", "1000", "--max-env", "1000"], repo)
    assert (r.returncode == 0) is said, r.stdout
    assert ("UNROUTED    src/thing.py:4 in fetch()" in r.stdout) is not said, r.stdout


def test_a_module_level_call_is_counted_against_its_own_budget(repo):
    (repo / "src" / "thing.py").write_text(
        "import httpx\n"
        "def probe(url):\n"
        "    return httpx.get(url, timeout=2)\n"
        "def probe_without_env(url):\n"
        "    return httpx.get(url, timeout=2, trust_env=False)\n",
        encoding="utf-8")
    assert _run(["--max", "1000", "--max-env", "1"], repo).returncode == 0
    r = _run(["--max", "1000", "--max-env", "0"], repo)
    assert r.returncode == 1 and "ENV-BUDGET  1 module-level httpx calls, budget is 0" in r.stdout


def test_routing_a_client_is_not_pacing_it(repo):
    """`direct_mounts` lives in `paced_http` and paces nothing: a function that
    only routes with it is still an unpaced call in the inventory."""
    (repo / "src" / "thing.py").write_text(
        "import httpx\nfrom src import paced_http\n"
        "async def routed(url):\n"
        "    from src import paced_http\n"
        "    async with httpx.AsyncClient(mounts=paced_http.direct_mounts(url)) as client:\n"
        "        return await client.post(url, json={})\n"
        "async def paced(url):\n"
        "    async with httpx.AsyncClient(mounts=paced_http.direct_mounts(url)) as client:\n"
        "        return await paced_http.request('POST', url, client=client, json={})\n",
        encoding="utf-8")
    r = _run([], repo)
    assert "unpaced outbound calls 1 in 1 file(s)" in r.stdout, r.stdout
    assert "routed()  client.post" in r.stdout and "paced()" not in r.stdout
