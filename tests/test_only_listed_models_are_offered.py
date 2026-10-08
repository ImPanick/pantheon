# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-07-02` §1 (`B1259`) — a model is offered only when an
enumeration that succeeded named it.

The owner, 2026-10-07: *"never populate a fabricated model. … Pantheon will
only ever show models successfully enumerated... including models pulled from
successful api link with openai, and anthropic etc."*

Measured on `fcd559e` (the base), each a name nothing had listed, offered:

  * an Anthropic endpoint whose `GET /v1/models` was refused answered ten
    built-in `claude-*` names (`ANTHROPIC_MODELS`) when no key was set;
  * a host `_PROVIDER_CURATED` knows (Groq here) answered eight curated names
    when its listing failed;
  * an endpoint that stopped answering kept the names it listed before — the
    background refresh "never clears a non-empty cached model list" — and the
    picker offered them (`CHAT-M-23`'s dimmed rows);
  * a pinned name the endpoint did not list was offered;
  * `/api/default-chat` answered a saved default model the endpoint no longer
    listed, and the composer opened a chat on it;
  * `GET /api/providers` with `OPENAI_API_KEY` set answered six OpenAI names
    written in `src/model_discovery.py`.

Driven, not read (`Law 20`): the real model routes on a real router over a real
SQLite file, against local list servers (`tests/helpers/model_lists.py`) — an
OpenAI-compatible one, and an Anthropic-shaped one reached under Anthropic's
own host name resolved to 127.0.0.1, so the Anthropic branch is the one that
runs and nothing leaves the machine (`Law 16`).
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, ModelEndpoint
from tests.helpers.model_lists import ListServer, closed_port, no_proxy, point_hosts_at


# ── the world ───────────────────────────────────────────────────────────────

class _Manager:
    is_configured = True

    def is_admin(self, user):
        return user == "ada"


@pytest.fixture
def world(tmp_path, monkeypatch):
    import routes.model_routes as model_routes
    import src.endpoint_resolver as endpoint_resolver
    import src.settings

    no_proxy(monkeypatch)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[ModelEndpoint.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(model_routes, "SessionLocal", factory)
    monkeypatch.setattr(endpoint_resolver, "SessionLocal", factory)
    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    src.settings._invalidate_caches()
    # The listing state is per process; each test starts from none.
    if hasattr(model_routes, "_LISTING_STATE"):
        monkeypatch.setattr(model_routes, "_LISTING_STATE", {})
    servers = []

    class World:
        db = factory

        def serve(self, models, **kw):
            s = ListServer(models, **kw)
            servers.append(s)
            return s

        def client(self, user="ada", discovery=None):
            app = FastAPI()
            app.state.auth_manager = _Manager()

            @app.middleware("http")
            async def _who(request, call_next):
                request.state.current_user = user
                return await call_next(request)

            app.include_router(model_routes.setup_model_routes(discovery))
            return TestClient(app)

        def add(self, ep_id, base_url, **cols):
            db = factory()
            db.add(ModelEndpoint(id=ep_id, name=cols.pop("name", ep_id), base_url=base_url,
                                 is_enabled=True, **cols))
            db.commit()
            db.close()

        def row(self, ep_id):
            db = factory()
            try:
                return db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            finally:
                db.close()

        def item(self, client, ep_id, **params):
            res = client.get("/api/models", params=params)
            assert res.status_code == 200, res.text
            return next(i for i in res.json()["items"] if i["endpoint_id"] == ep_id)

    yield World()
    for s in servers:
        s.stop()
    src.settings._invalidate_caches()


def _settle(predicate, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _save_settings(**values):
    import src.settings as S
    s = S.load_settings()
    s.update(values)
    S.save_settings(s)


# ── a local server, and what it lists ───────────────────────────────────────

def test_a_local_server_offers_exactly_what_it_lists(world):
    srv = world.serve(["alpha-7b", "beta-13b"])
    c = world.client()
    made = c.post("/api/model-endpoints", data={"name": "Office LLM", "base_url": srv.base,
                                                "endpoint_kind": "local", "require_models": "true"})
    assert made.status_code == 200, made.text
    item = world.item(c, made.json()["id"])
    assert sorted(item["models"] + item["models_extra"]) == ["alpha-7b", "beta-13b"]
    assert not item.get("offline")


def test_a_dead_endpoint_offers_none_of_the_names_it_listed_before(world):
    """The background refresh asked, nothing answered: the endpoint is one line
    saying so, and its old names are not on offer. On the base it kept them."""
    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local",
              cached_models=json.dumps(["alpha-7b"]))
    c = world.client()
    assert world.item(c, "office")["models"] == ["alpha-7b"]
    srv.stop()
    c.get("/api/models", params={"refresh": "true"})        # starts the refresh
    assert _settle(lambda: world.row("office").cached_models is None), \
        "a failed listing kept the names it listed before"
    item = world.item(c, "office", refresh="false")
    assert item["models"] == [] and item["models_extra"] == []
    assert item["offline"] is True
    assert item["down_line"] == "Office LLM isn't answering."


def test_retry_asks_again_and_the_names_come_back(world):
    """Retry is `?retry=<id>`: that endpoint is listed now and the fresh list
    answered — for a member too, on an endpoint they can see."""
    srv = world.serve(["alpha-7b"])
    port = srv.port
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local")
    srv.stop()
    member = world.client(user="bob")
    down = world.item(member, "office", retry="office")
    assert down["models"] == [] and down["down_line"] == "Office LLM isn't answering."
    world.serve(["alpha-7b", "gamma-3b"], port=port)          # it comes back
    back = world.item(member, "office", retry="office")
    assert sorted(back["models"] + back["models_extra"]) == ["alpha-7b", "gamma-3b"]
    assert not back.get("offline")


def test_a_member_cannot_retry_an_endpoint_that_is_not_theirs(world):
    srv = world.serve(["alpha-7b"])
    world.add("adas", srv.base, name="Ada's box", endpoint_kind="local", owner="ada")
    res = world.client(user="bob").get("/api/models", params={"retry": "adas"})
    assert res.status_code == 404
    assert srv.asked == [], "a refused retry still asked the endpoint"


def test_a_pinned_name_the_endpoint_does_not_list_is_not_offered(world):
    srv = world.serve(["alpha-7b"])
    world.add("proxy", srv.base, name="Proxy", endpoint_kind="api", api_key="k",
              cached_models=json.dumps(["alpha-7b"]),
              pinned_models=json.dumps(["alpha-7b", "typed-by-hand"]))
    item = world.item(world.client(), "proxy")
    assert item["models"] + item["models_extra"] == ["alpha-7b"]
    # Added Models still shows the pin, marked, so it can be unpinned.
    rows = world.client().get("/api/model-endpoints/proxy/models").json()
    assert {r["id"]: r["is_listed"] for r in rows} == {"alpha-7b": True, "typed-by-hand": False}


def test_a_launch_name_the_server_does_not_list_is_not_offered(world):
    """The Forge pins the name it launched; a server that lists an alias
    offers the alias. The base offered both, the pin unlisted."""
    srv = world.serve(["served-alias"])
    world.add("forge", srv.base, name="Qwen3-8B", endpoint_kind="local",
              cached_models=json.dumps(["served-alias"]),
              pinned_models=json.dumps(["Qwen/Qwen3-8B"]))
    item = world.item(world.client(), "forge")
    assert item["models"] + item["models_extra"] == ["served-alias"]


def test_a_server_still_loading_its_model_says_so(world):
    srv = world.serve(["alpha-7b"], loading=True)
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local")
    item = world.item(world.client(), "office", retry="office")
    assert item["models"] == [] and item["down_line"] == "Office LLM is loading its model."


# ── a provider's own list call ──────────────────────────────────────────────

def test_anthropic_offers_what_its_list_call_answers_for_a_key_that_answered(world, monkeypatch):
    srv = world.serve(["claude-fixture-sonnet", "claude-fixture-haiku"], anthropic_key="good")
    point_hosts_at(monkeypatch, {"api.anthropic.com": srv.port})
    base = f"http://api.anthropic.com:{srv.port}"
    c = world.client()
    good = c.post("/api/model-endpoints", data={"name": "Anthropic", "base_url": base,
                                                "api_key": "good", "endpoint_kind": "api"})
    assert good.status_code == 200, good.text
    assert sorted(good.json()["models"]) == ["claude-fixture-haiku", "claude-fixture-sonnet"]
    assert srv.asked[-1]["x-api-key"] == "good"
    item = world.item(c, good.json()["id"])
    assert sorted(item["models"] + item["models_extra"]) == ["claude-fixture-haiku",
                                                              "claude-fixture-sonnet"]


@pytest.mark.parametrize("key,line", [("wrong-key", "Anthropic refused its key."),
                                      ("", "Anthropic wants a key.")])
def test_anthropic_offers_nothing_when_its_list_call_is_refused(world, monkeypatch, key, line):
    """With no key the base answered ten built-in `claude-*` names. The line
    says the why: the list call answered, refusing the key (or asking for
    one) — not "isn't answering"."""
    srv = world.serve(["claude-fixture-sonnet"], anthropic_key="good")
    point_hosts_at(monkeypatch, {"api.anthropic.com": srv.port})
    c = world.client()
    made = c.post("/api/model-endpoints", data={"name": "Anthropic", "endpoint_kind": "api",
                                                "base_url": f"http://api.anthropic.com:{srv.port}",
                                                "api_key": key})
    assert made.status_code == 200, made.text
    assert made.json()["models"] == []
    item = world.item(c, made.json()["id"])
    assert item["models"] == [] and item["offline"] is True
    assert item["down_line"] == line


def test_a_curated_host_whose_listing_fails_lists_nothing(world, monkeypatch):
    """Groq's host, nothing listening, no key yet: the base answered
    `_PROVIDER_CURATED`'s eight Groq names."""
    port = closed_port()
    point_hosts_at(monkeypatch, {"api.groq.com": port})
    c = world.client()
    made = c.post("/api/model-endpoints", data={"name": "Groq", "endpoint_kind": "api",
                                                "base_url": f"http://api.groq.com:{port}/openai/v1"})
    assert made.status_code == 200, made.text
    assert made.json()["models"] == []
    assert world.item(c, made.json()["id"])["models"] == []


def test_providers_lists_openai_by_its_own_call(world, monkeypatch):
    """`GET /api/providers` with the server's OpenAI key: OpenAI's own list
    for that key, not six names written in the source."""
    import src.model_discovery as md

    srv = world.serve(["gpt-fixture-1"])
    point_hosts_at(monkeypatch, {"api.openai.com": srv.port})
    monkeypatch.setattr(md.ModelDiscovery, "discover_models", lambda self: {"hosts": [], "items": []})
    discovery = md.ModelDiscovery("127.0.0.1", "sk-fixture")
    # The provider's address, with the fixture's port: the real listing call.
    import routes.model_routes as model_routes
    real_probe = model_routes._probe_endpoint

    def probe(base, key, **kw):
        return real_probe(base.replace("https://api.openai.com", f"http://api.openai.com:{srv.port}"),
                          key, **kw)
    monkeypatch.setattr(model_routes, "_probe_endpoint", probe)
    res = world.client(discovery=discovery).get("/api/providers", params={"refresh": "true"})
    assert res.status_code == 200, res.text
    openai = [p for p in res.json()["providers"] if p["provider"] == "openai"]
    assert openai and openai[0]["items"][0]["models"] == ["gpt-fixture-1"]
    assert srv.asked and srv.asked[-1]["authorization"] == "Bearer sk-fixture"


# ── the saved default ───────────────────────────────────────────────────────

def test_a_saved_default_that_is_not_listed_is_not_answered_and_says_why(world):
    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local",
              cached_models=json.dumps(["alpha-7b"]))
    _save_settings(default_endpoint_id="office", default_model="gone-70b")
    got = world.client().get("/api/default-chat").json()
    assert got["model"] == "" and got["endpoint_url"] == ""
    assert got["reason"] == "gone-70b isn't listed by Office LLM now. Pick another from the model menu."


def test_a_saved_default_on_an_endpoint_that_is_not_answering_says_so(world):
    world.add("office", f"http://127.0.0.1:{closed_port()}/v1", name="Office LLM",
              endpoint_kind="local")
    _save_settings(default_endpoint_id="office", default_model="alpha-7b")
    got = world.client().get("/api/default-chat").json()
    assert got["model"] == ""
    assert got["reason"] == "Office LLM isn't answering. Pick another from the model menu."


def test_a_saved_default_that_is_listed_is_answered(world):
    srv = world.serve(["alpha-7b"])
    world.add("office", srv.base, name="Office LLM", endpoint_kind="local",
              cached_models=json.dumps(["alpha-7b"]))
    _save_settings(default_endpoint_id="office", default_model="alpha-7b")
    got = world.client().get("/api/default-chat").json()
    assert got["model"] == "alpha-7b" and got["endpoint_url"].endswith("/chat/completions")
    assert not got.get("reason")
