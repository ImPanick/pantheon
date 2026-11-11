# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2097`. Nobody mode keeps nothing.

The button reads *"Nobody — no memory, nothing saved"*, and the owner's ruling
is that it means it: *"Nobody mode is 'incognito' which should 'discard'
everything in that session."* Measured on `dev@9f6fcbe`, a Nobody chat kept:

* a picture it made — the file, a Gallery row with its prompt, and the prompt
  in the log — on the direct image path and the agent's (`image_gen`'s own
  process);
* whatever the agent wrote with the tools Nobody did not withhold: documents,
  notes, calendar, tasks, todos, research, RAG, the Gallery's editor;
* an uploaded photo, promoted into the Gallery;
* a reply read aloud, in the speech cache;
* the turn's `llm_round` event, tied to the chat after the chat was gone;
* and, when the chat ended, its documents — detached into the Library — and
  its pictures' Gallery rows, soft-deleted with their prompts.

Every test here calls the product: the real `/api/chat_stream` route (the
foreground-routing harness, the model stood in for), the real tool
dispatcher, the real upload and speech routes, `SessionManager.delete_session`
over a real SQLite file. Each failed on the unfixed tree.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import types
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import routes.chat_routes as chat_routes
from core.database import (
    ChatMessage,
    Document,
    DocumentVersion,
    Event,
    GalleryImage,
    Session as DbSession,
)
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

PROMPT = "a lighthouse on the north shore at dusk, for nobody"


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A real SQLite file behind every `SessionLocal` the paths here open, and
    the generated-images folder in `tmp_path`."""
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    import src.database as sdb
    import routes.chat_helpers as chat_helpers
    import core.session_manager as session_manager_module
    from src import ai_interaction, session_image_cleanup

    for module in (cdb, sdb, chat_helpers, session_manager_module):
        monkeypatch.setattr(module, "SessionLocal", factory, raising=False)
    images = tmp_path / "generated_images"
    images.mkdir()
    monkeypatch.setattr(ai_interaction, "GENERATED_IMAGES_DIR", str(images))
    monkeypatch.setattr(session_image_cleanup, "GENERATED_IMAGES_DIR", str(images))
    yield SimpleNamespace(db=factory, images=images)
    engine.dispose()


def _image_api(monkeypatch):
    """The image endpoint: answers every generation and edit with one PNG."""
    import httpx
    from src import ai_interaction, settings

    config = {"image_gen_enabled": True, "image_model": "gpt-image-1"}
    monkeypatch.setattr(settings, "load_settings", lambda *a, **k: config)
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None, *a, **k: config.get(key, default))
    monkeypatch.setattr(ai_interaction, "_resolve_model", lambda *a, **k: (
        "http://images.invalid/v1/chat/completions", "gpt-image-1", {}))

    class _Answer:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}

    class _Missing:
        status_code = 404

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            return _Answer()

        async def get(self, url, **kwargs):
            return _Missing()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _kept(store):
    with store.db() as db:
        rows = db.query(GalleryImage).count()
    return rows, sorted(p.name for p in store.images.iterdir())


def _drive(endpoint, request):
    async def go():
        response = await endpoint(request)
        return [chunk async for chunk in response.body_iterator]

    return asyncio.run(go())


def _events(sent):
    out = []
    for chunk in sent:
        for line in chunk.splitlines():
            if line.startswith("data: ") and line[6:].strip().startswith("{"):
                out.append(json.loads(line[6:]))
    return out


def _nobody_request(mode):
    request = _RouteRequest(mode)
    request._form["incognito"] = "true"
    request._form["compare_mode"] = "false"
    return request


# ── the picture: made, shown, kept nowhere ───────────────────────────────────


@pytest.mark.parametrize("edit", [False, True], ids=["generated", "edited"])
def test_a_picture_made_in_nobody_is_shown_and_kept_nowhere(monkeypatch, tmp_path, store, caplog, edit):
    """The direct image path (a chat on an image model): `do_generate_image`,
    or `do_edit_image` with a photo attached."""
    _image_api(monkeypatch)
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured)
    monkeypatch.setattr(chat_routes, "coerce_message_and_session", lambda *a, **k: (PROMPT, "session-1"))
    monkeypatch.setattr(chat_routes, "_is_image_generation_session", lambda *a, **k: True)
    source = tmp_path / "cat.png"
    source.write_bytes(PNG)
    monkeypatch.setattr(chat_routes, "_first_image_attachment", lambda *a, **k: (
        {"id": "u1", "name": "cat.png", "path": str(source)} if edit else None))

    with caplog.at_level(logging.DEBUG):
        sent = _drive(endpoint, _nobody_request("chat"))

    shown = [e for e in _events(sent) if e.get("type") == "generated_image"]
    assert shown, f"no picture was shown: {_events(sent)[-4:]}"
    assert shown[0]["url"].startswith("data:image/png;base64,"), shown[0]["url"][:60]
    assert not shown[0].get("image_id")
    assert _kept(store) == (0, []), "a Nobody picture left a Gallery row or a file"
    logged = [r.getMessage() for r in caplog.records if PROMPT in r.getMessage()]
    assert not logged, f"the Nobody prompt was logged: {logged}"
    assert not captured.get("added_messages"), "the Nobody turn was added to the chat"


def test_the_same_picture_outside_nobody_is_kept(monkeypatch, tmp_path, store):
    """The control: the harness does reach the writers, so the test above is a
    measurement and not an absence of one."""
    _image_api(monkeypatch)
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {})
    monkeypatch.setattr(chat_routes, "coerce_message_and_session", lambda *a, **k: (PROMPT, "session-1"))
    monkeypatch.setattr(chat_routes, "_is_image_generation_session", lambda *a, **k: True)
    monkeypatch.setattr(chat_routes, "_first_image_attachment", lambda *a, **k: None)
    with store.db() as db:
        db.add(DbSession(id="session-1", owner="alice", name="Chat", endpoint_url="x", model="m"))
        db.commit()
    request = _RouteRequest("chat")
    request._form["compare_mode"] = "false"

    sent = _drive(endpoint, request)

    shown = [e for e in _events(sent) if e.get("type") == "generated_image"]
    assert shown and shown[0]["url"].startswith("/api/generated-image/")
    rows, files = _kept(store)
    assert rows == 1 and len(files) == 1


def test_the_agent_s_pictures_in_nobody_are_shown_and_kept_nowhere(monkeypatch, store, caplog):
    """The agent's `generate_image` goes to the `image_gen` server, its own
    process, which writes a file and a Gallery row for every picture and can
    not know which turn asked. In Nobody it is made in this process instead.
    Its `edit_image` (`src/tools/image.py`) saved the edit as a new Gallery
    picture; in Nobody the edit is shown and not saved.

    Driven through the route, whose turn the call belongs to: the model is
    stood in for, the tool calls are the real dispatcher's. The owner is an
    admin so the qualified `mcp__` spelling is dispatched rather than refused."""
    import src.constants as constants
    from src import paced_http, tool_execution
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block, format_tool_result

    _image_api(monkeypatch)
    server_calls = []

    class _Server:
        async def call_tool(self, name, args):
            server_calls.append((name, args))
            return {"stdout": "Generated image for: x\nDirect link: /api/generated-image/abcdefabcdef.png",
                    "exit_code": 0}

    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: _Server())
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    # A picture already in the Gallery, for the edit to start from.
    monkeypatch.setattr(constants, "GENERATED_IMAGES_DIR", str(store.images))
    (store.images / "source000000.png").write_bytes(PNG)
    with store.db() as db:
        db.add(GalleryImage(id="img-src", filename="source000000.png", prompt="a cat",
                            owner="alice", is_active=True))
        db.commit()

    class _Edited:
        status_code = 200

        def json(self):
            return {"image": base64.b64encode(PNG).decode()}

    async def _edit_service(url, **kwargs):
        return _Edited()

    monkeypatch.setattr(paced_http, "post", _edit_service)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    ran = {}
    calls = {
        "generate_image": PROMPT,
        "mcp__image_gen__generate_image": json.dumps({"prompt": PROMPT}),
        "edit_image": json.dumps({"image_id": "img-src", "action": "rembg", "prompt": PROMPT}),
    }

    async def agent(endpoint_url, model, messages, **kwargs):
        assert "edit_image" not in kwargs["disabled_tools"]
        for name, content in calls.items():
            desc, result = await execute_tool_block(
                ToolBlock(name, content), session_id="session-1", owner="alice",
                security_context=NO_TOOL_SECURITY_CONTEXT)
            ran[name] = (desc, result)
        yield f'data: {json.dumps({"delta": "done"})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent)

    with caplog.at_level(logging.DEBUG):
        _drive(endpoint, _nobody_request("agent"))

    assert set(ran) == set(calls), ran
    assert not server_calls, f"the image server was called in Nobody: {server_calls}"
    for name, (desc, result) in ran.items():
        assert str(result.get("image_url", "")).startswith("data:image/png;base64,"), (name, result)
        told = format_tool_result(desc, result)
        assert "base64," not in told and len(told) < 2000, (name, told[:300])
    assert _kept(store) == (1, ["source000000.png"]), "only the picture it started from is kept"
    assert not [r for r in caplog.records if PROMPT in r.getMessage()], "the prompt was logged"


def test_a_picture_with_no_file_reaches_the_model_as_a_sentence():
    """`format_tool_result` echoed `image_url` into the result's JSON tail —
    harmless for `/api/generated-image/<name>`, and up to 8,000 characters of
    base64 for a picture whose address is the picture."""
    from src.tool_execution import format_tool_result

    data_url = "data:image/png;base64," + base64.b64encode(PNG * 400).decode()
    told = format_tool_result("generate_image", {
        "results": f"Generated image for: {PROMPT}", "image_url": data_url,
        "image_model": "gpt-image-1", "exit_code": 0})
    assert "base64," not in told, told[:400]
    assert "gpt-image-1" in told, "the rest of the result still reaches the model"


# ── what the agent may reach ─────────────────────────────────────────────────


def _disabled_in_a_turn(monkeypatch, request):
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    seen = {}

    async def agent(endpoint_url, model, messages, **kwargs):
        seen["disabled"] = kwargs.get("disabled_tools")
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent)
    _drive(endpoint, request)
    return seen["disabled"]


#: Each writes into what Pantheon keeps for the person.
WRITERS = ("create_document", "update_document", "edit_document", "suggest_document",
           "manage_documents", "manage_notes", "manage_calendar", "manage_tasks", "todowrite",
           "trigger_research", "manage_research", "manage_rag", "mcp__rag__manage_rag",
           "manage_workflows", "manage_contact", "ledger_table")


def test_a_nobody_turn_withholds_every_tool_that_writes_what_pantheon_keeps(monkeypatch):
    from src.tool_policy import LIFTABLE_REASONS

    disabled = _disabled_in_a_turn(monkeypatch, _nobody_request("agent"))
    missing = [name for name in WRITERS if name not in disabled]
    assert not missing, f"Nobody still offers {missing}"
    for name in WRITERS:
        assert not (disabled.reasons_for(name) & LIFTABLE_REASONS), (
            f"{name} is withheld for a reason a clamp may lift: {disabled.reasons_for(name)}")
    # The reads it always withheld, still withheld.
    for name in ("manage_memory", "search_chats", "manage_skills", "list_sessions"):
        assert name in disabled
    # The pictures still run: they keep nothing (above).
    assert "generate_image" not in disabled and "edit_image" not in disabled


def test_an_ordinary_turn_is_offered_the_writers(monkeypatch):
    request = _RouteRequest("agent")
    request._form["compare_mode"] = "false"
    disabled = _disabled_in_a_turn(monkeypatch, request)
    assert not [name for name in ("create_document", "manage_notes", "todowrite") if name in disabled]


def _mode_a_research_request_sets(monkeypatch, request):
    """The mode the route writes for a turn that asks for research, which is
    the decision to run it: `research` starts the run that keeps a report and
    its findings."""
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {})
    modes = []
    monkeypatch.setattr(chat_routes, "set_session_mode", lambda sid, mode, *a, **k: modes.append(mode))
    monkeypatch.setattr(chat_routes, "_resolve_research_endpoint", lambda sess: ("http://x", "m", {}))
    request._form["use_research"] = "true"
    sent = _drive(endpoint, request)
    return modes, _events(sent)


def test_a_nobody_turn_starts_no_research(monkeypatch):
    """The browser turns research off when Nobody comes on; a request that
    sends both is answered as Nobody, not as research."""
    modes, events = _mode_a_research_request_sets(monkeypatch, _nobody_request("chat"))
    assert modes and "research" not in modes, modes
    assert not [e for e in events if e.get("suffix") == "Research"]


def test_an_ordinary_research_request_is_research(monkeypatch):
    request = _RouteRequest("chat")
    request._form["compare_mode"] = "false"
    modes, _ = _mode_a_research_request_sets(monkeypatch, request)
    assert "research" in modes, "the control: the harness reaches the decision"


# ── what the turn's own bookkeeping keeps ────────────────────────────────────


def test_a_nobody_turn_is_counted_but_not_tied_to_its_chat(monkeypatch, store):
    from routes import chat_helpers

    with store.db() as db:
        db.add(DbSession(id="session-1", owner="alice", name="Nobody", endpoint_url="x", model="m"))
        db.commit()
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {})
    monkeypatch.setattr(chat_routes, "save_assistant_response", chat_helpers.save_assistant_response)
    monkeypatch.setattr(chat_routes, "run_post_response_tasks", chat_helpers.run_post_response_tasks)
    monkeypatch.setattr(cdb, "update_session_last_accessed", lambda sid: None, raising=False)

    _drive(endpoint, _nobody_request("chat"))

    with store.db() as db:
        rounds = db.query(Event).filter(Event.kind == "llm_round").all()
        assert rounds, "the turn was not counted at all — the drive measured nothing"
        assert [r.session_id for r in rounds] == [None] * len(rounds), (
            "a Nobody turn's event names its chat")
        assert db.query(ChatMessage).count() == 0


def test_the_webhook_hears_nothing_of_a_nobody_turn():
    """`chat.completed` carried the person's words and the reply to wherever
    the hook points; `fire_message_event` already refused the same for the
    person's message."""
    from routes.chat_helpers import run_post_response_tasks

    fired = []
    hooks = SimpleNamespace(fire_and_forget=lambda event, payload: fired.append((event, payload)))
    sess = SimpleNamespace(endpoint_url="x", model="m", headers={}, history=[], name="Nobody")

    asyncio.run(run_post_response_tasks(
        sess, SimpleNamespace(save_sessions=lambda: None), "session-1", PROMPT, "a reply",
        None, {"auto_memory": False, "auto_skills": False}, None, None, hooks,
        incognito=True, owner="alice"))
    assert not fired, fired

    asyncio.run(run_post_response_tasks(
        sess, SimpleNamespace(save_sessions=lambda: None), "session-1", PROMPT, "a reply",
        None, {"auto_memory": False, "auto_skills": False}, None, None, hooks,
        incognito=False, owner="alice"))
    assert [event for event, _ in fired] == ["chat.completed"], "the control"


# ── what the person hands it ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_photo_sent_in_nobody_is_not_put_in_the_gallery(tmp_path, monkeypatch):
    import routes.upload_routes as up
    from src.upload_handler import UploadHandler

    engine = create_engine(f"sqlite:///{tmp_path / 'gallery.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    gallery_dir = tmp_path / "generated_images"
    monkeypatch.setattr(up, "SessionLocal", factory)
    monkeypatch.setattr(up, "GENERATED_IMAGES_DIR", str(gallery_dir))
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    router, _ = up.setup_upload_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/upload" and "POST" in r.methods)
    request = types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"),
                                    state=types.SimpleNamespace(current_user="alice"))

    result = await endpoint(request, [types.SimpleNamespace(filename="me.png", file=io.BytesIO(PNG))],
                            session_id="session-1", incognito="true")

    assert result["files"] and "gallery_id" not in result["files"][0]
    with factory() as db:
        assert db.query(GalleryImage).count() == 0
    assert not gallery_dir.exists() or not list(gallery_dir.iterdir())
    engine.dispose()


def test_a_reply_read_aloud_in_nobody_is_not_kept_in_the_speech_cache(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.tts_routes import setup_tts_routes
    from services.tts.tts_service import TTSService

    class _Speaker(TTSService):
        personal_voices = None   # the shared voice, as an install with none chosen

        @property
        def available(self):
            return True

        def _load_settings(self):
            return {}

        def _resolve(self, settings, choice=None):
            return "endpoint:e1", "tts-1", "alloy", 1.0, None

        def _synthesize_api(self, text, endpoint_id, model, voice, speed):
            return b"ID3" + b"\x00" * 64

    cache = tmp_path / "tts"
    app = FastAPI()
    app.include_router(setup_tts_routes(_Speaker(cache_dir=str(cache))))
    with TestClient(app) as client:
        said = client.post("/api/tts/synthesize", json={"text": PROMPT, "incognito": True})
        assert said.status_code == 200 and said.content.startswith(b"ID3")
        assert not list(cache.iterdir()), "a Nobody reply was kept as sound"
        client.post("/api/tts/synthesize", json={"text": PROMPT})
        assert len(list(cache.iterdir())) == 1, "the control: an ordinary reply is cached"


# ── when the chat ends ───────────────────────────────────────────────────────


def _nobody_chat_with_leftovers(store, name="Nobody"):
    picture = store.images / "aaaaaaaaaaaa.png"
    picture.write_bytes(PNG)
    with store.db() as db:
        db.add(DbSession(id="n1", owner="alice", name=name, endpoint_url="x", model="m"))
        db.flush()
        db.add(GalleryImage(id="img-1", filename=picture.name, prompt=PROMPT, owner="alice",
                            session_id="n1", is_active=True))
        db.add(Document(id="doc-1", session_id="n1", title="Notes", current_content=PROMPT, owner="alice"))
        db.add(DocumentVersion(id="v-1", document_id="doc-1", version_number=1, content=PROMPT))
        db.add(ChatMessage(id="m-1", session_id="n1", role="user", content=PROMPT))
        db.commit()
    return picture


def _left(store):
    with store.db() as db:
        return {
            "sessions": db.query(DbSession).count(),
            "pictures": db.query(GalleryImage).count(),
            "documents": db.query(Document).count(),
            "versions": db.query(DocumentVersion).count(),
            "messages": db.query(ChatMessage).count(),
        }


NOTHING = {"sessions": 0, "pictures": 0, "documents": 0, "versions": 0, "messages": 0}


def test_ending_a_nobody_chat_leaves_no_rows_behind(store):
    """`DELETE /api/session/{id}` — which the browser sends for a Nobody chat
    it leaves — detached the chat's documents into the Library and
    soft-deleted its pictures, prompt and all."""
    import core.session_manager as session_manager_module
    from routes import chat_helpers

    picture = _nobody_chat_with_leftovers(store)
    chat_helpers._append_incognito_message("n1", "user", PROMPT)
    manager = session_manager_module.SessionManager.__new__(session_manager_module.SessionManager)
    manager.sessions = {}

    assert manager.delete_session("n1")

    assert _left(store) == NOTHING
    assert not picture.exists()
    assert chat_helpers._incognito_messages("n1") == [], "the transcript outlived the chat"


def test_the_sweep_takes_an_idle_nobody_chat_whole(store, monkeypatch):
    """The daily sweep deleted chats named *Incognito*, the name before the
    rename, by their row alone; a *Nobody* chat waited for the empty-chat rule
    and left what it held."""
    import datetime as _dt
    from src.session_actions import run_auto_sort

    _nobody_chat_with_leftovers(store)
    with store.db() as db:
        row = db.query(DbSession).filter(DbSession.id == "n1").one()
        old = _dt.datetime(2026, 1, 1)
        row.created_at = row.updated_at = row.last_accessed = old
        db.query(ChatMessage).delete()   # a Nobody chat has none of its own
        db.commit()

    asyncio.run(run_auto_sort("alice", skip_llm=True))

    assert _left(store) == NOTHING
