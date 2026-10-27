# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1022` — module-level `httpx` calls read `NO_PROXY` as httpx does.

`httpx.get(url)` builds a client inside and takes no `mounts=`, so `B1014`'s
rule — a `NO_PROXY` range is a range (`paced_http.direct_mounts`, `B982`) —
could not reach it: with a proxy configured and `NO_PROXY=10.0.0.0/8,
127.0.0.0/8`, a call to `http://127.0.0.1:…` went to the proxy. 51 such calls
were counted against `check-outbound.py --max-env`; this pass moved thirteen of
them — the LAN-facing model discovery probes, the service-health probe, CardDAV
(×6), the embedding endpoint test, and the STT and TTS API calls — onto
`paced_http`, which routes by the range and paces by the limiter (free for a
local host, polite to a hosted one), with redirects left unfollowed as
`httpx.get` left them.

Driven (`Law 20`): each real function asks a real HTTP server on loopback,
with a real recording proxy in `HTTP_PROXY` and only ranges in `NO_PROXY`.
Before, every one of these reached the proxy; now none does, and each gets the
origin's answer.
"""
from __future__ import annotations

import http.server
import json
import threading

import pytest

_VCARD = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:wren-1\r\nFN:Wren Hollis\r\nEMAIL:wren@example.test\r\nEND:VCARD\r\n"


def _server(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def world(monkeypatch):
    asked = {"origin": [], "proxy": []}
    world_state = {"image_url": ""}

    class Origin(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_GET(self):  # noqa: N802
            asked["origin"].append(("GET", self.path))
            if self.path == "/v1/models":
                return self._send(200, json.dumps({"data": [{"id": "alpha-7b"}]}).encode())
            if self.path == "/dav/contacts":
                return self._send(200, _VCARD.encode(), "text/vcard")
            if self.path == "/generated/chair.png":
                return self._send(503)          # the tool keeps the URL, writes nothing
            return self._send(200, b'{"ok": true}')

        def do_REPORT(self):  # noqa: N802
            self._read()
            asked["origin"].append(("REPORT", self.path))
            self._send(405)                     # no REPORT: the plain-GET fallback

        def do_POST(self):  # noqa: N802
            self._read()
            asked["origin"].append(("POST", self.path))
            if self.path.endswith("/audio/transcriptions"):
                return self._send(200, b'{"text": "hello there"}')
            if self.path.endswith("/audio/speech"):
                return self._send(200, b"ID3-mp3-bytes", "audio/mpeg")
            if self.path.endswith("/images/generations"):
                return self._send(200, json.dumps({"data": [{"url": world_state["image_url"]}]}).encode())
            if self.path.endswith("/chat/completions"):
                return self._send(200, json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "from the LAN"}}]}).encode())
            return self._send(200, json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode())

        def log_message(self, *a):
            pass

    class Proxy(http.server.BaseHTTPRequestHandler):
        def _any(self):
            asked["proxy"].append((self.command, self.path))
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = do_PUT = do_DELETE = do_REPORT = _any  # noqa: N815

        def log_message(self, *a):
            pass

    origin, proxy = _server(Origin), _server(Proxy)
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
    for var in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(var, proxy_url)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "10.0.0.0/8,127.0.0.0/8")    # ranges only: no names
    from src.rate_limiter import OutboundHostLimiter
    import src.rate_limiter as rl
    monkeypatch.setattr(rl, "outbound", OutboundHostLimiter({}))
    world_state["port"] = origin.server_address[1]
    world_state["asked"] = asked
    yield world_state
    origin.shutdown()
    proxy.shutdown()


def test_model_discovery_reaches_a_lan_server_direct(world):
    from src.model_discovery import ModelDiscovery

    found = ModelDiscovery(default_host="127.0.0.1")._check_port("127.0.0.1", world["port"])
    assert found and found["models"] == ["alpha-7b"]
    assert world["asked"]["proxy"] == []


def test_the_service_health_probe_reaches_its_service_direct(world):
    from src.service_health import _http_get

    r = _http_get(f"http://127.0.0.1:{world['port']}/healthz", timeout=3)
    assert r.status_code == 200
    assert world["asked"]["proxy"] == []


def test_carddav_reads_a_lan_address_book_direct(world, monkeypatch):
    import routes.contacts.contacts_routes as C

    monkeypatch.setattr(C, "_get_carddav_config", lambda: {
        "url": f"http://127.0.0.1:{world['port']}/dav/contacts", "username": "", "password": ""})
    contacts = C._fetch_contacts(force=True)
    assert [c.get("name") for c in contacts] == ["Wren Hollis"]
    assert ("REPORT", "/dav/contacts") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


@pytest.fixture
def speech_endpoint(world, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.database as D
    from core.database import Base, ModelEndpoint

    engine = create_engine(f"sqlite:///{tmp_path / 'ep.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[ModelEndpoint.__table__])
    factory = sessionmaker(bind=engine)
    db = factory()
    db.add(ModelEndpoint(id="speech", name="Speech box", is_enabled=True,
                         base_url=f"http://127.0.0.1:{world['port']}/v1"))
    db.commit()
    db.close()
    monkeypatch.setattr(D, "SessionLocal", factory)
    return "speech"


def test_stt_and_tts_reach_a_lan_speech_server_direct(world, speech_endpoint, tmp_path):
    from services.stt.stt_service import STTService
    from services.tts.tts_service import TTSService

    assert STTService()._transcribe_api(b"\x1a\x45", speech_endpoint, "whisper-1") == "hello there"
    assert TTSService(cache_dir=str(tmp_path / "tts"))._synthesize_api(
        "hello", speech_endpoint, "tts-1", "alloy") == b"ID3-mp3-bytes"
    assert world["asked"]["proxy"] == []


def test_nothing_was_routed_by_luck(world):
    """The control: a module-level `httpx.get` in the same environment still
    goes to the proxy — the routing above is the conversion, not the setup."""
    import httpx

    r = httpx.get(f"http://127.0.0.1:{world['port']}/healthz", timeout=3)
    assert r.status_code == 502
    assert world["asked"]["proxy"] == [("GET", f"http://127.0.0.1:{world['port']}/healthz")]


def test_the_embedding_endpoint_check_reaches_a_lan_server_direct(world, monkeypatch):
    """`POST /api/embeddings/endpoint` tests the endpoint before saving it.
    The save is stopped right after the check, so nothing else it touches
    (the environment, the RAG singleton) moves."""
    import routes.embedding_routes as E

    class _Checked(Exception):
        pass

    def stop(data):
        raise _Checked(data)

    monkeypatch.setattr(E, "_save_custom_endpoint", stop)
    set_endpoint = next(r.endpoint for r in E.setup_embedding_routes().routes
                        if r.path == "/api/embeddings/endpoint" and "POST" in r.methods)
    with pytest.raises(_Checked):
        set_endpoint(url=f"http://127.0.0.1:{world['port']}/v1/embeddings", model="m", api_key="")
    assert ("POST", "/v1/embeddings") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


# ── wave t: the rest of the model probes, and the OAuth and device flows ────
#
# 27 → 3. The model probes the row named first (`model_routes` ×7,
# `model_context` ×3, `llm_core`'s model list ×2, `chat_helpers` ×1) and the
# OAuth and device flows (ChatGPT ×5, Copilot ×3, the mailbox's token refresh
# and callback ×3) moved onto `paced_http`. And then 3 → 0: the non-streamed
# model call is routed as its streamed twin is (`llm_core._post_routed`, not
# paced — `Law 16` clause 2), and `ai_interaction`'s two image downloads are
# awaited through `paced_http`.

def test_the_endpoint_probes_reach_a_lan_model_server_direct(world, monkeypatch):
    import routes.model_routes as M
    import src.endpoint_resolver as R

    monkeypatch.setattr(R, "resolve_url", lambda url: url, raising=False)
    base = f"http://127.0.0.1:{world['port']}/v1"
    assert M._probe_endpoint(base, None) == ["alpha-7b"]
    assert M._ping_endpoint(base)["reachable"] is True
    assert M._probe_single_model(base, None, "alpha-7b")["status"] == "ok"
    assert {("GET", "/v1/models"), ("POST", "/v1/chat/completions")} <= set(world["asked"]["origin"])
    assert world["asked"]["proxy"] == []


def test_the_context_window_lookup_and_the_model_list_reach_it_direct(world, monkeypatch):
    import src.endpoint_resolver as R
    import src.llm_core as L
    import src.model_context as C

    monkeypatch.setattr(R, "resolve_url", lambda url: url, raising=False)
    monkeypatch.setattr(C, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(L, "_configured_cached_model_ids", lambda url, **k: [])
    base = f"http://127.0.0.1:{world['port']}/v1"
    C._query_context_length(base, "alpha-7b")
    assert L.list_model_ids(base, timeout=3) == ["alpha-7b"]
    assert ("GET", "/slots") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


def test_the_lm_studio_probe_reaches_it_direct(world):
    from src import chat_helpers

    chat_helpers._lmstudio_models_cache.clear()
    chat_helpers._probe_lmstudio_models(f"http://127.0.0.1:{world['port']}/v1/chat/completions")
    assert ("GET", "/api/v1/models") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


def test_a_device_flow_on_a_host_in_the_range_goes_direct(world):
    """GitHub Enterprise on the LAN is the case: Copilot's device flow and
    model list against a host `NO_PROXY` puts in a range."""
    from src import copilot

    copilot.fetch_models(f"http://127.0.0.1:{world['port']}", "tok", timeout=3)
    assert ("GET", "/models") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


def test_the_model_call_itself_reaches_a_lan_model_server_direct(world, monkeypatch):
    """`llm_call`'s non-streamed request — `httpx.post` until the last three
    of `B1022` — to a model server `NO_PROXY` puts in a range."""
    import src.endpoint_resolver as R
    import src.llm_core as L
    import src.model_context as C

    monkeypatch.setattr(R, "resolve_url", lambda url: url, raising=False)
    monkeypatch.setattr(C, "_configured_endpoint_kind", lambda url: None)
    L._response_cache.clear()
    url = f"http://127.0.0.1:{world['port']}/v1/chat/completions"
    answer = L.llm_call(url, "alpha-7b", [{"role": "user", "content": "hello"}], timeout=5)
    assert "from the LAN" in str(answer)
    assert ("POST", "/v1/chat/completions") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []


async def test_a_generated_image_on_the_lan_is_fetched_direct(world, monkeypatch):
    """An image server on the LAN that answers with a URL: `do_generate_image`
    fetches the picture from it, not from the proxy (its download was
    `httpx.get` until `B1022`'s last three). The origin answers the download
    503, so the tool keeps the URL and writes nothing."""
    import src.ai_interaction as A
    import src.settings as settings

    monkeypatch.setattr(settings, "load_settings", lambda: {})
    base = f"http://127.0.0.1:{world['port']}/v1"

    monkeypatch.setattr(A, "_resolve_model",
                        lambda spec, owner=None, **k: (f"{base}/chat/completions", "dall-e-3", {}))
    picture = f"http://127.0.0.1:{world['port']}/generated/chair.png"
    world["image_url"] = picture
    result = await A.do_generate_image("draw a chair\ndall-e-3")
    assert result.get("image_url") == picture, result
    assert ("POST", "/v1/images/generations") in world["asked"]["origin"]
    assert ("GET", "/generated/chair.png") in world["asked"]["origin"]
    assert world["asked"]["proxy"] == []
