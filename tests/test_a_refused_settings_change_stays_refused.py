# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B957`. `load_settings()` handed back its own cache, so a writer that
assigned into what it got and then raised, refused or failed to save had
already changed what every other reader saw — for up to `_CACHE_TTL` — and the
next unrelated save in that window wrote it to disk.

Every case here drives a real writer (a route through its real router, a tool,
an action) with its save made to fail after it has assigned, then asks the
store. Nothing reads a source file (`Law 20`). The cache window is widened for
the test so a slow request cannot close it and turn a leak into a pass.
"""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _DiskFull(OSError):
    pass


def _refuse(*_a, **_k):
    raise _DiskFull("the disk is full")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """`src.settings` on temp files, with a cache window no test can outlast."""
    import src.settings as S

    sp = tmp_path / "settings.json"
    fp = tmp_path / "features.json"
    sp.write_text(json.dumps({"agent_email_confirm": True}), encoding="utf-8")
    fp.write_text(json.dumps({"deep_research": False}), encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(S, "FEATURES_FILE", str(fp))
    monkeypatch.setattr(S, "_CACHE_TTL", 3600.0)
    S._invalidate_caches()
    yield S
    S._invalidate_caches()


def _on_disk(S, key):
    raw = json.loads(Path(S.SETTINGS_FILE).read_text(encoding="utf-8"))
    return raw.get(key, S.DEFAULT_SETTINGS.get(key))


def _nothing_moved(S, key, before):
    """The refused change is in nobody's answer, and an unrelated save in the
    same window does not write it."""
    assert S.get_setting(key) == before, "a refused change is visible to readers"
    assert S.load_settings().get(key) == before
    unrelated = S.load_settings()
    unrelated["b957_unrelated"] = 7
    S.save_settings(unrelated)
    assert _on_disk(S, key) == before, "the next unrelated save persisted it"
    assert _on_disk(S, "b957_unrelated") == 7


def _admin_headers():
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
    return {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db(monkeypatch):
    """A throwaway SQLite with the real tables, as `core.database.SessionLocal`."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as D

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    D.Base.metadata.create_all(engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(D, "SessionLocal", maker)
    yield maker
    engine.dispose()


# ── the source ───────────────────────────────────────────────────────────────

def test_what_load_settings_returns_belongs_to_the_caller(store):
    S = store
    S.get_setting("agent_email_confirm")          # warm the cache
    a = S.load_settings()
    a["agent_email_confirm"] = False
    a["networks"].append({"name": "lab", "cidrs": ["10.9.0.0/16"]})
    b = S.load_settings()
    assert a is not b
    assert b["agent_email_confirm"] is True
    assert b["networks"] == []
    assert S.get_setting("networks") == []


def test_a_value_get_setting_returns_belongs_to_the_caller(store):
    S = store
    nets = S.get_setting("networks")
    nets.append({"name": "lab"})
    keys = S.get_setting("keybinds")
    keys["search"] = "ctrl+q"
    assert S.get_setting("networks") == []
    assert S.get_setting("keybinds")["search"] == S.DEFAULT_SETTINGS["keybinds"]["search"]


def test_get_setting_does_not_copy_the_whole_store(store, monkeypatch):
    """The hot path stays cheap: one value is copied, never the dict."""
    S = store
    seen = []
    real = S._owned_copy

    def counting(value):
        seen.append(value)
        return real(value)

    S.get_setting("agent_email_confirm")
    monkeypatch.setattr(S, "_owned_copy", counting)
    assert S.get_setting("agent_email_confirm") is True
    assert S.get_setting("networks") == []
    assert not any(isinstance(v, dict) and "agent_email_confirm" in v for v in seen), (
        "get_setting copied the whole settings dict")
    assert len(seen) <= 2


def test_an_unreadable_file_does_not_hand_out_the_shipped_defaults(store):
    """`P3-16`'s path returns defaults uncached; they were `dict(DEFAULT_SETTINGS)`,
    which shares every nested default with the module constant."""
    S = store
    Path(S.SETTINGS_FILE).write_text("{ not json", encoding="utf-8")
    S._invalidate_caches()
    s = S.load_settings()
    s["networks"].append({"name": "lab"})
    s["keybinds"]["search"] = "ctrl+q"
    assert S.DEFAULT_SETTINGS["networks"] == []
    assert S.DEFAULT_SETTINGS["keybinds"]["search"] == "ctrl+k"


def test_what_load_features_returns_belongs_to_the_caller(store):
    S = store
    S.load_features()
    f = S.load_features()
    f["deep_research"] = True
    assert S.load_features()["deep_research"] is False


def test_a_replaced_loader_still_answers_every_read(store, monkeypatch):
    """Thirteen test files steer `get_setting` by replacing `load_settings`; the
    fast path must not route round the replacement."""
    S = store
    monkeypatch.setattr(S, "load_settings", lambda: {"search_result_count": 42})
    assert S.get_setting("search_result_count") == 42
    assert S.get_setting("agent_email_confirm", "absent") == "absent"


# ── each writer, driven ──────────────────────────────────────────────────────

def _backup_router():
    from routes.backup_routes import setup_backup_routes

    class _Mgr:
        def load(self, **k): return []
        def load_all_for_update(self): return []
        def load_all(self): return []
        def get_all(self): return {}
        def save(self, *a, **k): return None

    return setup_backup_routes(_Mgr(), _Mgr(), _Mgr())


def test_import_settings_that_fail_to_save(store, monkeypatch):
    import routes.backup_routes as B
    S = store
    S.get_setting("agent_email_confirm")
    monkeypatch.setattr(B, "save_settings", _refuse)
    r = _client(_backup_router()).post(
        "/api/import", headers=_admin_headers(),
        json={"settings": {"agent_email_confirm": False}})
    assert r.status_code == 500
    _nothing_moved(S, "agent_email_confirm", True)


def test_import_features_that_fail_to_save(store, monkeypatch):
    import routes.backup_routes as B
    S = store
    S.load_features()
    monkeypatch.setattr(B, "save_features", _refuse)
    r = _client(_backup_router()).post(
        "/api/import", headers=_admin_headers(),
        json={"features": {"deep_research": True}})
    assert r.status_code == 500
    assert S.load_features()["deep_research"] is False


def test_contacts_config_that_fails_to_save(store, monkeypatch):
    """`PUT /api/contacts/config` reads `settings.json` through its own module's `_load_settings`
    (a second door onto the file, named at its definition), so it never saw the
    cache and never leaked through it — this passes on the old tree too, and
    pins that it still does not leak."""
    import routes.contacts.contacts_routes as C
    S = store
    S.get_setting("carddav_username")
    monkeypatch.setattr(C, "_save_settings", _refuse)
    r = _client(C.setup_contacts_routes()).put(
        "/api/contacts/config", headers=_admin_headers(),
        json={"carddav_username": "mallory"})
    assert r.status_code == 500
    _nothing_moved(S, "carddav_username", S.DEFAULT_SETTINGS.get("carddav_username"))


def test_email_config_that_fails_to_save(store, monkeypatch):
    """`PUT /api/email/config` reads `settings.json` through its own module's `_load_settings`
    (a second door onto the file, named at its definition), so it never saw the
    cache and never leaked through it — this passes on the old tree too, and
    pins that it still does not leak."""
    import routes.email_routes as E
    from routes.email_helpers import require_owner
    S = store
    before = S.get_setting("email_auto_tag")
    monkeypatch.setattr(E, "_save_settings", _refuse)
    app = FastAPI()
    app.include_router(E.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: ""
    r = TestClient(app, raise_server_exceptions=False).put(
        "/api/email/config", json={"email_auto_tag": not before})
    assert r.status_code == 500
    _nothing_moved(S, "email_auto_tag", before)


def test_the_tool_denylist_that_fails_to_save(store, monkeypatch):
    import routes.model_routes as M
    S = store
    before = S.get_setting("disabled_tools")
    monkeypatch.setattr(M, "_save_settings", _refuse)
    r = _client(M.setup_model_routes(model_discovery=None)).post(
        "/api/tools", headers=_admin_headers(), json={"disabled": ["bash"]})
    assert r.status_code == 500
    _nothing_moved(S, "disabled_tools", before)


def test_a_new_endpoint_that_fails_to_become_the_default(store, db, monkeypatch):
    import routes.model_routes as M
    S = store
    S.get_setting("default_endpoint_id")
    monkeypatch.setattr(M, "SessionLocal", db)
    monkeypatch.setattr(M, "_save_settings", _refuse)
    r = _client(M.setup_model_routes(model_discovery=None)).post(
        "/api/model-endpoints", headers=_admin_headers(),
        data={"base_url": "http://127.0.0.1:9/v1", "skip_probe": "true",
              "pinned_models": "local-model"})
    assert r.status_code == 500, r.text
    _nothing_moved(S, "default_endpoint_id", S.DEFAULT_SETTINGS.get("default_endpoint_id"))


def _first_builtin_name():
    from src.agent_loop import TOOL_SECTIONS
    key = next(iter(TOOL_SECTIONS))
    return key[0] if isinstance(key, tuple) else key


def _skills_client(tmp_path):
    from routes.skills_routes import SkillsManager, setup_skills_routes
    return _client(setup_skills_routes(SkillsManager(str(tmp_path / "skills"), library_root="")))


def test_a_builtin_override_that_fails_to_save(store, tmp_path, monkeypatch):
    """The nested case: the writer assigns into `builtin_tool_overrides`, a dict
    inside the settings, before it saves — a shallow copy would still leak."""
    S = store
    name = _first_builtin_name()
    before = S.get_setting("builtin_tool_overrides")
    real = S.save_settings
    monkeypatch.setattr(S, "save_settings", _refuse)
    r = _skills_client(tmp_path).put(f"/api/skills/builtin/{name}",
                                     headers=_admin_headers(), json={"text": "be terse"})
    assert r.status_code == 500
    monkeypatch.setattr(S, "save_settings", real)
    _nothing_moved(S, "builtin_tool_overrides", before)


def test_a_builtin_reset_that_fails_to_save(store, tmp_path, monkeypatch):
    S = store
    name = _first_builtin_name()
    seeded = S.load_settings()
    seeded["builtin_tool_overrides"] = {name: "be terse"}
    S.save_settings(seeded)
    S.get_setting("builtin_tool_overrides")
    real = S.save_settings
    monkeypatch.setattr(S, "save_settings", _refuse)
    r = _skills_client(tmp_path).delete(f"/api/skills/builtin/{name}", headers=_admin_headers())
    assert r.status_code == 500
    monkeypatch.setattr(S, "save_settings", real)
    _nothing_moved(S, "builtin_tool_overrides", {name: "be terse"})


def test_manage_settings_that_fails_to_save(store, db, monkeypatch):
    S = store
    from src.agent_tools.admin_tools import do_manage_settings
    before = S.get_setting("search_result_count")
    real = S.save_settings
    monkeypatch.setattr(S, "save_settings", _refuse)
    out = asyncio.run(do_manage_settings(json.dumps(
        {"action": "set", "key": "search_result_count", "value": before + 3})))
    assert out.get("exit_code") == 1, out
    monkeypatch.setattr(S, "save_settings", real)
    _nothing_moved(S, "search_result_count", before)


def test_an_email_scan_whose_flag_save_fails(store, monkeypatch):
    """`_run_auto_summarize_once` reads `settings.json` through its own module's `_load_settings`
    (a second door onto the file, named at its definition), so it never saw the
    cache and never leaked through it — this passes on the old tree too, and
    pins that it still does not leak."""
    import routes.email_pollers as P
    S = store
    before = S.get_setting("email_auto_summarize")
    monkeypatch.setattr(P, "_save_settings", _refuse)
    with pytest.raises(_DiskFull):
        asyncio.run(P._run_auto_summarize_once(do_summary=not before))
    _nothing_moved(S, "email_auto_summarize", before)


def test_a_scheduled_serve_whose_default_save_fails(store, tmp_path, monkeypatch):
    """The action swallows the failure and logs it, so the leak was silent."""
    from src import builtin_actions

    class _Served:
        content = b"{}"

        def json(self):
            return {"ok": True, "session_id": "tmux-1", "endpoint_id": "ep-served"}

    async def _post(self, *_a, **_k):
        return _Served()

    state = tmp_path / "cookbook_state.json"
    state.write_text(json.dumps({"env": {"servers": []}}), encoding="utf-8")
    monkeypatch.setattr(builtin_actions, "COOKBOOK_STATE_FILE", str(state))
    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    S = store
    before = S.get_setting("default_endpoint_id")
    real = S.save_settings
    monkeypatch.setattr(S, "save_settings", _refuse)
    message, ok = asyncio.run(builtin_actions.action_cookbook_serve(
        owner="", task_name="serve", command=json.dumps(
            {"repo_id": "org/model", "cmd": "llama-server --port 8080"})))
    assert ok is True, message
    monkeypatch.setattr(S, "save_settings", real)
    _nothing_moved(S, "default_endpoint_id", before)


def _cookbook_closure(name):
    """A function defined inside `setup_cookbook_routes`, taken from the real
    router's handlers by the name it is closed over as."""
    from routes.cookbook_routes import setup_cookbook_routes
    router = setup_cookbook_routes()
    for route in router.routes:
        fn = getattr(route, "endpoint", None)
        code = getattr(fn, "__code__", None)
        if not code or name not in code.co_freevars:
            continue
        cell = fn.__closure__[code.co_freevars.index(name)]
        return cell.cell_contents
    raise AssertionError(f"no handler closes over {name}")


def test_an_image_endpoint_registration_whose_save_fails(store, db, monkeypatch):
    """`_auto_register_image_endpoint` catches everything and logs it, so this
    leak was silent too."""
    S = store
    register = _cookbook_closure("_auto_register_image_endpoint")
    before = S.get_setting("image_gen_enabled")
    real = S.save_settings
    monkeypatch.setattr(S, "save_settings", _refuse)
    req = types.SimpleNamespace(cmd="python diffusion_server.py --port 8123",
                                repo_id="org/diffuser")
    register(req, None)
    monkeypatch.setattr(S, "save_settings", real)
    _nothing_moved(S, "image_gen_enabled", before)
    _nothing_moved(S, "image_model", S.DEFAULT_SETTINGS.get("image_model"))
