# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B492` — a feature whose host the limiter is holding says so, to whoever is
using it, with the time it clears, in `static/js/runStatus.js`'s words.

`P15-11` gave the limiter's snapshot one reader on a non-admin surface — the
mailbox's 60-second poll, which carried `sync: {source: 'unavailable',
retry_in}`. Every other host it holds was visible only in Settings → System,
behind `require_admin`: a throttled search returned no results and the
Forge's HuggingFace list said *"Couldn't load trending models (…)"*.
`B1533` paced the search providers, which made the refusal real; this makes it
said, through three surfaces a non-admin uses:

  * **Compare's search** — `POST /api/search/query` answers a held provider
    with `sync: {source: 'throttled', retry_in}` (it was a red `Error:`), and
    `POST /api/search` (Compare's shared pre-search) when every provider is held;
  * **the chat's web search** — the turn's `web_sources` frame carries `sync`
    with no sources, as `rag_frames` carries `off` (`B1287`);
  * **the Forge's HuggingFace list** — `GET /api/cookbook/hf-latest`.

Driven end to end: a real limiter primed the way a provider's `429` with
`Retry-After` primes it, the real routes answering through FastAPI's
TestClient, and each answer handed, as the browser gets it, to the real client
function that draws it — run in node, importing the real `runStatus.js`.
"""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture
def limiter(monkeypatch, tmp_path):
    """A fresh limiter whose cooldowns are written under `tmp_path`."""
    import src.constants as constants
    import src.rate_limiter as rl

    monkeypatch.setattr(constants, "OUTBOUND_STATE_FILE", str(tmp_path / "outbound.json"))
    fresh = rl.OutboundHostLimiter()
    monkeypatch.setattr(rl, "outbound", fresh)

    def hold(host, seconds):
        fresh.observe(host, 429, {"Retry-After": str(seconds)})
    return SimpleNamespace(hold=hold, limiter=fresh)


@pytest.fixture
def search_app(monkeypatch):
    import services.search.core as core
    from routes.search.search_routes import setup_search_routes

    monkeypatch.setenv("DATA_BRAVE_API_KEY", "brave-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setattr(core, "_read_search_cache", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(setup_search_routes())
    return TestClient(app)


def _node(script: str, tmp_path: Path) -> dict:
    """Run `script` as a module beside copies of the client files it imports."""
    (tmp_path / "compare").mkdir(exist_ok=True)
    for rel in ("runStatus.js", "ragNotice.js", "compare/searchOutcome.js"):
        shutil.copy(JS / rel, tmp_path / rel)
    case = tmp_path / "case.mjs"
    case.write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", str(case)], cwd=tmp_path, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the server says it ──────────────────────────────────────────────────────

def test_a_held_provider_answers_comparing_search_with_when(limiter, search_app):
    limiter.hold("api.search.brave.com", 240)
    r = search_app.post("/api/search/query", data={"query": "who owns the seabed", "provider": "brave"})
    body = r.json()
    assert body["results"] == [] and body["label"] == "Brave Search"
    assert body["sync"]["source"] == "throttled"
    assert 230 <= body["sync"]["retry_in"] <= 240


def test_every_provider_held_is_a_paused_search_not_an_empty_one(limiter, search_app, monkeypatch):
    import services.search.core as core

    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "brave"})
    monkeypatch.setattr(core, "_build_provider_chain", lambda primary: ["brave", "tavily"])
    limiter.hold("api.search.brave.com", 240)
    limiter.hold("api.tavily.com", 90)
    body = search_app.post("/api/search", data={"query": "who owns the seabed"}).json()
    assert body["sources"] == []
    assert body["sync"]["source"] == "throttled"
    assert 80 <= body["sync"]["retry_in"] <= 90, "the soonest provider back is when search is"
    assert body["context"].startswith("Web search is paused")


def test_a_search_that_was_not_held_carries_no_sync(limiter, search_app, monkeypatch):
    """The other half: nothing held, nothing said — a `sync` on every answer
    would be furniture."""
    import services.search.core as core

    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "brave"})
    monkeypatch.setattr(core, "_build_provider_chain", lambda primary: ["brave"])
    monkeypatch.setattr(core, "_call_provider", lambda *a, **k: [])
    body = search_app.post("/api/search", data={"query": "q"}).json()
    assert "sync" not in body


def test_the_chat_turn_carries_the_pause_in_its_web_frame(limiter, monkeypatch):
    """`ChatProcessor` runs the real web search on a chain the limiter holds;
    the route's frame builder says it, as `rag_frames` says `off`."""
    import services.search.core as core
    from routes.chat_routes import web_frames
    from src.chat_processor import ChatProcessor
    from unittest.mock import MagicMock

    monkeypatch.setattr(core, "_read_search_cache", lambda *a, **k: None)
    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "brave"})
    monkeypatch.setattr(core, "_build_provider_chain", lambda primary: ["brave"])
    monkeypatch.setenv("DATA_BRAVE_API_KEY", "brave-key")
    monkeypatch.setattr("src.llm_core.llm_call", lambda *a, **k: "who owns the seabed")
    limiter.hold("api.search.brave.com", 300)

    processor = ChatProcessor(memory_manager=MagicMock(), personal_docs_manager=MagicMock())
    session = SimpleNamespace(endpoint_url="http://local", model="test", headers={})
    _preface, _rag, web_sources = processor.build_context_preface(
        message="Who owns the seabed?", session=session, use_web=True, use_rag=False,
        use_memory=False)
    assert web_sources == []
    ctx = SimpleNamespace(web_sync=processor._last_web_sync)
    [frame] = web_frames(ctx, web_sources)
    data = json.loads(frame[len("data: "):])
    assert data["type"] == "web_sources" and data["data"] == []
    assert data["sync"]["source"] == "throttled" and 290 <= data["sync"]["retry_in"] <= 300
    # and a turn whose search ran says nothing new
    assert web_frames(SimpleNamespace(web_sync=None), []) == []


def test_the_forge_trending_list_says_huggingface_is_held(limiter, monkeypatch):
    import routes.cookbook_routes as cb
    from src import model_hubs
    from src.auth_helpers import require_user

    monkeypatch.setattr(model_hubs, "allowed", lambda: True)
    limiter.hold("huggingface.co", 600)
    router = cb.setup_cookbook_routes() if hasattr(cb, "setup_cookbook_routes") else cb.router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: "guest-bob"
    body = TestClient(app).get("/api/cookbook/hf-latest?vram_gb=0&limit=3").json()
    assert body["models"] == []
    assert body["sync"]["source"] == "throttled" and 590 <= body["sync"]["retry_in"] <= 600


# ── …and the client says it in runStatus.js's words ─────────────────────────

@needs_node
def test_each_surface_draws_the_pause_with_the_shared_words(limiter, search_app, monkeypatch, tmp_path):
    """The real answers above, handed to the real client code: Compare's
    `searchOutcome`, the chat's `noteWebFrame`, and the Forge's
    `_trendingEmptyText` beside `runStatus.syncNotice`."""
    import services.search.core as core
    from tests.helpers.js_source import js_definition

    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "brave"})
    monkeypatch.setattr(core, "_build_provider_chain", lambda primary: ["brave"])
    limiter.hold("api.search.brave.com", 240)
    compare = search_app.post("/api/search/query", data={"query": "q", "provider": "brave"}).json()
    shared = search_app.post("/api/search", data={"query": "q"}).json()
    frame = {"type": "web_sources", "data": [], "sync": shared["sync"]}
    forge_answer = {"models": [], "error": "huggingface.co has rate-limited us",
                    "sync": {"source": "throttled", "retry_in": 600}}

    cookbook = (JS / "cookbook.js").read_text(encoding="utf-8")
    trending = js_definition(cookbook, cookbook.index("function _trendingEmptyText("))
    out = _node(f"""
        import {{ syncNotice }} from './runStatus.js';
        import {{ noteWebFrame }} from './ragNotice.js';
        import {{ searchOutcome }} from './compare/searchOutcome.js';
        {trending}
        const toasts = [];
        noteWebFrame({json.dumps(frame)}, (t) => toasts.push(t));
        noteWebFrame({{ type: 'web_sources', data: [{{ url: 'https://a.example' }}] }}, (t) => toasts.push(t));
        const forge = {json.dumps(forge_answer)};
        console.log(JSON.stringify({{
          compare: searchOutcome({json.dumps(compare)}),
          chat: toasts,
          forge: _trendingEmptyText({{ held: syncNotice(forge.sync, 'HuggingFace'), lastErr: forge.error }}),
          forgeFailed: _trendingEmptyText({{ lastErr: 'HF API HTTP 500' }}),
        }}));
    """, tmp_path)
    assert out["compare"]["kind"] == "held"
    assert out["compare"]["text"] == "Brave Search is paused — retrying in 4 min"
    assert out["chat"] == ["Web search is paused — retrying in 4 min"]
    assert out["forge"] == "HuggingFace is paused — retrying in 10 min"
    assert out["forgeFailed"] == "Couldn't load trending models (HF API HTTP 500)"


@needs_node
def test_an_ordinary_failure_is_still_a_failure_in_compare(tmp_path):
    """`Law 1`: an error that is not a pause keeps its red `Error:`."""
    out = _node("""
        import { searchOutcome } from './compare/searchOutcome.js';
        console.log(JSON.stringify({
          failed: searchOutcome({ results: [], error: 'Unknown provider' }),
          empty: searchOutcome({ results: [] }),
          found: searchOutcome({ results: [{ url: 'https://a.example' }] }),
        }));
    """, tmp_path)
    assert out == {"failed": {"kind": "error", "text": "Error: Unknown provider"},
                   "empty": {"kind": "empty", "text": "No results found"},
                   "found": {"kind": "results", "text": ""}}


def test_the_words_live_in_one_client_file():
    """`Law 13`: no client file but `runStatus.js` spells the throttle's
    sentence (its two shapes: with a countdown, and without one)."""
    from tests.helpers.source_text import blank_text

    shapes = ("paused — retrying", "until the service lets us back in")
    spelled = [p.relative_to(ROOT).as_posix() for p in sorted(JS.rglob("*.js"))
               if any(w in blank_text(p.read_text(encoding="utf-8")) for w in shapes)
               and p.name != "runStatus.js"]
    assert spelled == []
