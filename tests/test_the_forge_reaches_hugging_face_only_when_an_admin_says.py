# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1229` — opening the Forge reached huggingface.co with nothing switched on.

Measured on `299bd50`: the Forge asked `GET /api/hwfit/models?refresh_catalog=1`
as it opened, and the server walked up to 40 pages of huggingface.co's
collections beside the answer (`P15-05`'s budget, `P23-07`'s thread); the same
open asked `/api/cookbook/ollama/library`, which fetched `ollama.com/search`. A
fresh install, opened and used, reached two vendors — the `Law 16` test failed
exactly where the 0.2.0 release notes say it passes.

The owner, 2026-10-07: *"hugging face should be toggleable inside the admin
settings, along with how the LLM is served etc."* One instance setting,
`forge_model_hubs`, shipped off, read only through `src/model_hubs.py`; every
request the Forge makes to either host asks it — the catalog refresh, the image
collections, the trending list, the GGUF file list, the agent's lookup, the
Ollama library, and a download started by hand, which says where the switch is
instead of reaching out.

Driven, not read (`Law 20`): the real route handlers on a real router, the real
settings route with an admin and a non-admin, the real refresh in its thread.
Two independent probes say nothing left: the socket tripwire from
`test_no_egress_on_boot.py` (DNS and `connect`, with this sandbox's proxy
variables removed so a request would resolve its host), and a spy on the
process-wide `OutboundHostLimiter`, which every third-party call asks first.
With the switch on, the same paths ask the limiter for the host and make the
request — the limiter stays on every call (`FORBIDDEN.md` Part 2).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.model_hubs as model_hubs
from tests.test_no_egress_on_boot import no_egress  # noqa: F401 — the socket tripwire

_REPO = Path(__file__).resolve().parents[1]
_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
_HUBS = set(model_hubs.HOSTS)


# ── The world: a data directory of our own, and the two probes ─────────────

@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """`DATA_DIR` rebound by name, not by reloading (`B130`): the settings file,
    the Forge's own state file, and the catalog caches the refresh writes."""
    import routes.cookbook_routes as cookbook_routes
    import services.hwfit.hf_discovery as hf
    import services.hwfit.models as models
    import src.constants
    import src.settings

    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(cookbook_routes, "COOKBOOK_STATE_FILE", str(tmp_path / "cookbook_state.json"))
    monkeypatch.setattr(hf, "MLX_COMMUNITY_CACHE", tmp_path / "hwfit" / "mlx.json")
    monkeypatch.setattr(hf, "HF_COLLECTION_MODELS_CACHE", tmp_path / "hwfit" / "hf.json")
    monkeypatch.setattr(hf, "_last_forced_refresh", 0.0)
    monkeypatch.setattr(models, "_refresh_state", {"state": "idle"})
    models.reset_model_cache()
    src.settings._invalidate_caches()
    yield tmp_path
    src.settings._invalidate_caches()
    models.reset_model_cache()


@pytest.fixture
def asked(monkeypatch):
    """Every host the limiter is asked for — which every third-party call does
    first — recorded, then let through."""
    from src.rate_limiter import outbound

    hosts = []
    real_sync, real_async = outbound.acquire, outbound.acquire_async

    def acquire(host, *a, **k):
        hosts.append(host)
        return real_sync(host, *a, **k)

    async def acquire_async(host, *a, **k):
        hosts.append(host)
        return await real_async(host, *a, **k)

    monkeypatch.setattr(outbound, "acquire", acquire)
    monkeypatch.setattr(outbound, "acquire_async", acquire_async)
    return hosts


@pytest.fixture
def direct(monkeypatch):
    """No proxy: a request would have to resolve its own host, which the
    tripwire records."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


def _switch(on: bool) -> None:
    import src.settings as S

    s = S.load_settings()
    s["forge_model_hubs"] = on
    S.save_settings(s)


class _Manager:
    is_configured = True

    def is_admin(self, user):
        return user == "ada"

    def get_username_for_token(self, token):
        return token or None


def _forge(user: str = "ada") -> TestClient:
    """The real Forge router behind the smallest auth the routes ask."""
    from routes.cookbook_routes import setup_cookbook_routes

    app = FastAPI()
    app.state.auth_manager = _Manager()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_cookbook_routes())
    return TestClient(app, raise_server_exceptions=False)


def _hwfit(path: str):
    from routes.hwfit_routes import setup_hwfit_routes

    for route in setup_hwfit_routes().routes:
        if getattr(route, "path", "").endswith(path) and "GET" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"hwfit {path} route not found")


def _until(predicate, seconds=10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ── The switch ──────────────────────────────────────────────────────────────

def test_the_switch_ships_off(datadir):
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["forge_model_hubs"] is False
    assert model_hubs.allowed() is False


def test_only_a_stored_true_is_on(datadir):
    """A hand-edited `"true"` is not a yes: the route stores only booleans, and
    a string the reader took as on would be a panel saying off over a Forge
    reaching out."""
    Path(datadir / "settings.json").write_text(json.dumps({"forge_model_hubs": "true"}))
    import src.settings as S
    S._invalidate_caches()
    assert model_hubs.allowed() is False
    _switch(True)
    assert model_hubs.allowed() is True


def _settings_route():
    import sys
    import types

    core = sys.modules.get("core")
    if core is None:
        core = types.ModuleType("core")
        sys.modules["core"] = core
    core.__path__ = [str(_REPO / "core")]
    from routes.auth_routes import setup_auth_routes

    for route in setup_auth_routes(_Manager()).routes:
        if getattr(route, "path", "") == "/api/auth/settings" and "POST" in route.methods:
            return route.endpoint
    raise AssertionError("POST /api/auth/settings not found")


class _Req:
    def __init__(self, body, user):
        from routes.auth_routes import SESSION_COOKIE
        self.cookies = {SESSION_COOKIE: user}
        self._body = body

    async def json(self):
        return self._body


def test_an_admin_switches_it_and_nobody_else_can(datadir):
    from fastapi import HTTPException
    import src.settings as S

    post = _settings_route()
    with pytest.raises(HTTPException) as refused:
        asyncio.run(post(_Req({"forge_model_hubs": True}, "bob")))
    assert refused.value.status_code == 403
    assert model_hubs.allowed() is False

    for bad in ("true", 1, None, [], {}):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(post(_Req({"forge_model_hubs": bad}, "ada")))
        assert caught.value.status_code == 400 and "forge_model_hubs" in str(caught.value.detail)
    assert model_hubs.allowed() is False

    asyncio.run(post(_Req({"forge_model_hubs": True}, "ada")))
    assert model_hubs.allowed() is True and S.load_settings()["forge_model_hubs"] is True
    asyncio.run(post(_Req({"forge_model_hubs": False}, "ada")))
    assert model_hubs.allowed() is False


# ── Off: opening the Forge, and everything it can ask, reaches nobody ──────

def test_opening_the_forge_reaches_nobody(datadir, direct, asked, no_egress):  # noqa: F811
    """What the Forge sends as it opens on a fresh install: the model list with
    `refresh_catalog=1`, then the Ollama library for the same list."""
    import services.hwfit.models as models

    payload = _hwfit("/models")(limit=50, refresh_catalog=True)
    assert payload["catalog_refresh"] == {"state": "off"}
    assert payload["models"], "the bundled catalog is still the list"
    time.sleep(0.3)  # a thread, had one started, would be asking by now
    assert models.catalog_refresh_status()["state"] == "idle"

    library = _forge().get("/api/cookbook/ollama/library").json()
    assert library["hubs_off"] is True and library["models"], "the curated list still answers"

    assert asked == [] and no_egress == []
    assert not (datadir / "hwfit").exists(), "a refused refresh wrote a cache"


def test_the_state_tells_the_forge_and_is_never_stored(datadir):
    client = _forge()
    assert client.get("/api/cookbook/state").json()["env"]["modelHubs"] is False
    _switch(True)
    time.sleep(1.6)  # the state answer is cached for 1.5 s
    state = client.get("/api/cookbook/state").json()
    assert state["env"]["modelHubs"] is True
    state["env"]["servers"] = [{"host": "", "name": "Local"}]
    assert client.post("/api/cookbook/state", json=state).json()["ok"] is True
    on_disk = json.loads((datadir / "cookbook_state.json").read_text())
    assert "modelHubs" not in on_disk["env"], "the setting's answer was written into the Forge's file"


def test_every_lookup_says_the_hubs_are_off_and_reaches_nobody(datadir, direct, asked, no_egress, monkeypatch):  # noqa: F811
    from src.tools.cookbook import _cookbook_hf_model_info

    client = _forge()
    latest = client.get("/api/cookbook/hf-latest?limit=2").json()
    assert latest == {"models": [], "error": model_hubs.OFF_SENTENCE, "hubs_off": True}
    gguf = client.get("/api/cookbook/hf-gguf-files?repo_id=Qwen/Qwen3-8B-GGUF").json()
    assert gguf["ok"] is False and gguf["hubs_off"] is True and gguf["error"] == model_hubs.OFF_SENTENCE
    info = asyncio.run(_cookbook_hf_model_info("Qwen/Qwen3-8B"))
    assert info["error"] == model_hubs.OFF_SENTENCE

    # The image registry is empty by design (`image_models.IMAGE_MODEL_REGISTRY`):
    # its rows come from Hugging Face, so off they are what this process has.
    import services.hwfit.image_models as image_models
    assert _hwfit("/image-models")(sort="fit")["models"] == []
    monkeypatch.setattr(image_models, "_HF_COLLECTION_CACHE", {"ts": 0, "models": [{
        "id": "black-forest-labs/FLUX.2-klein", "name": "FLUX.2 klein", "provider": "BFL",
        "params_b": 4, "vram_bf16": 9.0, "vram_fp8": 5.0, "vram_q4": 3.0,
        "default_quant": "BF16", "quality": 80, "speed": 70, "capabilities": ["diffusers"],
        "description": "fetched earlier, while the switch was on", "quant_repos": {}}]})
    assert [m["id"] for m in _hwfit("/image-models")(sort="fit")["models"]] == [
        "black-forest-labs/FLUX.2-klein"], "the rows already fetched are still the list"

    assert asked == [] and no_egress == []


def test_the_image_paths_request_function_asks_too(datadir, direct, asked, no_egress):  # noqa: F811
    """`_hf_get_json` is the one request in `image_models`; its search caller is
    switched off today (`_should_discover_variants`), so it is asked directly —
    the day that caller comes back, it is already behind the switch."""
    import services.hwfit.image_models as image_models

    assert image_models._hf_get_json("https://huggingface.co/api/collections/x") is None
    assert image_models._hf_model_search("flux fp8") == []
    assert asked == [] and no_egress == []


@pytest.mark.parametrize("body", [
    {"repo_id": "Qwen/Qwen3-8B"},
    {"repo_id": "qwen2.5:7b", "backend": "ollama"},
], ids=["hugging face", "ollama"])
def test_a_download_started_by_hand_says_where_the_switch_is(datadir, direct, asked, no_egress, body, monkeypatch):  # noqa: F811
    from routes import shell_routes

    logs = datadir / "tmux"
    monkeypatch.setattr(shell_routes, "TMUX_LOG_DIR", logs)
    import routes.cookbook_routes as cookbook_routes
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", logs)
    answer = _forge().post("/api/model/download", json=body).json()
    assert answer == {"ok": False, "error": model_hubs.OFF_SENTENCE, "hubs_off": True}
    assert not logs.exists(), "a download script was written for a refused download"
    assert asked == [] and no_egress == []


def test_the_agents_search_says_the_switch_rather_than_no_models(datadir, monkeypatch):
    """`search_hf_models` read an empty answer as "No models found" — a claim
    about Hugging Face nobody was allowed to check."""
    import src.tools.cookbook as tools

    class _Resp:
        def json(self):
            return {"models": [], "error": model_hubs.OFF_SENTENCE, "hubs_off": True}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    said = asyncio.run(tools.do_search_hf_models(json.dumps({"query": "qwen"})))
    assert said == {"error": model_hubs.OFF_SENTENCE, "exit_code": 1}


# ── On: the refresh happens, paced, and a switch turned off stops it ───────

class _Page:
    """One page of collections, with a next link, as huggingface.co answers."""

    status = 200

    def __init__(self, url):
        self.url = url
        self.headers = {"Link": f'<{url}&p=next>; rel="next"'}

    def read(self, *_a):
        return b"[]"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def huggingface(monkeypatch):
    """huggingface.co, answering every page — the requests recorded."""
    import services.hwfit.hf_discovery as hf
    from src.rate_limiter import HostPolicy, OutboundHostLimiter
    import src.rate_limiter as rl

    monkeypatch.setattr(rl, "outbound", OutboundHostLimiter(
        {"huggingface.co": HostPolicy(min_interval=0.0, jitter=0.0)}))
    monkeypatch.setattr(hf, "_hf_token", lambda: "")
    urls = []

    def _open(req, timeout=None):
        urls.append(req.full_url)
        return _Page(req.full_url)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    return urls


def test_with_the_switch_on_the_refresh_reaches_hugging_face_paced(datadir, huggingface, monkeypatch):
    import services.hwfit.models as models
    import src.rate_limiter as rl

    hosts = []
    real = rl.outbound.acquire
    monkeypatch.setattr(rl.outbound, "acquire", lambda host, *a, **k: (hosts.append(host), real(host, *a, **k))[1])
    _switch(True)
    payload = _hwfit("/models")(limit=5, refresh_catalog=True)
    assert payload["catalog_refresh"]["state"] == "running"
    assert _until(lambda: models.catalog_refresh_status()["state"] in ("done", "failed"))
    assert models.catalog_refresh_status()["state"] == "done", models.catalog_refresh_status()
    assert huggingface, "the refresh made no request"
    assert all(u.startswith("https://huggingface.co/api/collections?") for u in huggingface)
    # `FORBIDDEN.md` Part 2: one limiter acquisition per request, no fewer.
    assert hosts == ["huggingface.co"] * len(huggingface)


def test_a_switch_turned_off_mid_refresh_stops_it_at_the_next_request(datadir, huggingface, monkeypatch):
    import services.hwfit.hf_discovery as hf

    _switch(True)
    first_url = []

    def _open(req, timeout=None):
        first_url.append(req.full_url)
        _switch(False)          # an admin turns it off while the first page is out
        return _Page(req.full_url)

    monkeypatch.setattr(hf.urllib.request, "urlopen", _open)
    source = next(s for s in hf.HF_COLLECTION_SOURCES if s["key"] == "qwen")
    with pytest.raises(model_hubs.ModelHubsOff):
        hf.fetch_collection_models(source, budget=[40])
    assert len(first_url) == 1, f"{len(first_url)} requests after the switch went off"
    assert hf.refresh_hf_collection_models_cache(force=True) == []
    assert len(first_url) == 1
    assert not hf.HF_COLLECTION_MODELS_CACHE.exists()


def test_with_the_switch_on_the_lookups_ask_their_hosts(datadir, asked, monkeypatch):
    """The trending list and the Ollama library go out again — through
    `paced_http`, which asks the limiter first."""
    from src import paced_http

    went = []

    class _Answer:
        status_code = 200
        text = ""
        content = b"[]"
        headers = {}

        def json(self):
            return []

    async def fake_request(method, url, **kwargs):
        from src.rate_limiter import outbound
        await outbound.acquire_async(paced_http._host(url))
        went.append(url)
        return _Answer()

    monkeypatch.setattr(paced_http, "request", fake_request)
    _switch(True)
    client = _forge()
    assert "hubs_off" not in client.get("/api/cookbook/hf-latest?limit=2").json()
    assert "hubs_off" not in client.get("/api/cookbook/ollama/library").json()
    assert [u.split("/")[2] for u in went] == ["huggingface.co", "ollama.com"]
    assert asked == ["huggingface.co", "ollama.com"]


def test_with_the_switch_on_a_download_goes_past_the_gate(datadir, monkeypatch):
    import routes.cookbook_routes as cookbook_routes

    async def no_tmux(*a, **k):
        return False

    monkeypatch.setattr(cookbook_routes, "_binary_available", no_tmux)
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", datadir / "tmux")
    _switch(True)
    answer = _forge().post("/api/model/download", json={"repo_id": "Qwen/Qwen3-8B"}).json()
    assert "hubs_off" not in answer and "tmux" in answer["error"], answer
