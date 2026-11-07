# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1922`. An image the agent makes belongs to the person it made it for.

The agent's `generate_image` runs in the built-in `image_gen` MCP server, and
the dispatcher sent that server what the model wrote and nothing more: the
person the call ran for reached `_call_mcp_tool` and stopped there. So every
gallery row the server wrote had no owner. Its maker never saw it in the
Gallery, which lists a person's own rows; the server picked the image model
from every account's endpoints; and within the hour the null-owner sweep gave
the row, prompt and all, to the first admin, after which the maker's own link
answered 404. A model could also put `_pantheon_owner` in its arguments, and
that name went on the row.

Now the dispatcher drops every `_pantheon_` key the model sent and adds the
person itself, under the bare name and the qualified one; the server puts that
person on the row and finds the model among their endpoints and the shared
ones, as `do_generate_image` does. The route had two more holes: an ownership
check that raised served the file anyway (now 503), and `Cache-Control:
public` let a shared cache hand one person's image to another (now `private`).

Ported from upstream Odysseus 6fceb6cc (#6268), with `_odysseus_owner` as
`_pantheon_owner`. Its in-memory registry, its refusal of images with no row
and its auth-off branch are not ported. Driven (`Law 20`): the real dispatcher
with a fake MCP manager, the real server over a temp database, the real route.
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as cdb
import src.database as legacy_database
from tests.helpers.signed_in import ADMIN, MEMBER, signed_in

IMAGE_LINK = "/api/generated-image/0123456789ab.png"


class _FakeMcp:
    """The MCP manager, as far as the dispatcher sees it: what it was asked."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return {"stdout": f"Generated image for: a fox\nDirect link: {IMAGE_LINK}\n"
                          "model: gpt-image-1\nsize: 1024x1024", "exit_code": 0}


@pytest.fixture
def dispatcher(monkeypatch, tmp_path):
    import src.tool_execution as tool_execution

    signed_in(monkeypatch, tmp_path / "auth")   # ada is the admin, bob a member
    mcp = _FakeMcp()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    def run(tool, content, owner):
        block = SimpleNamespace(tool_type=tool, content=content)
        return asyncio.run(tool_execution.execute_tool_block(
            block, owner=owner, security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT))

    return run, mcp


def test_the_server_is_told_whom_the_image_is_for(dispatcher):
    run, mcp = dispatcher
    _desc, result = run("generate_image", "a fox in the snow", MEMBER)
    assert result["exit_code"] == 0, result
    assert mcp.calls == [("mcp__image_gen__generate_image",
                          {"prompt": "a fox in the snow", "_pantheon_owner": MEMBER})]
    assert result["image_url"] == IMAGE_LINK


def test_an_owner_the_model_names_is_not_believed(dispatcher):
    run, mcp = dispatcher
    run("generate_image", json.dumps({"prompt": "a fox", "_pantheon_owner": ADMIN,
                                      "_pantheon_private": True}), MEMBER)
    assert mcp.calls == [("mcp__image_gen__generate_image",
                          {"prompt": "a fox", "_pantheon_owner": MEMBER})]


def test_with_nobody_to_name_the_model_names_nobody_either(dispatcher):
    run, mcp = dispatcher
    run("generate_image", json.dumps({"prompt": "a fox", "_pantheon_owner": ADMIN}), None)
    assert mcp.calls == [("mcp__image_gen__generate_image", {"prompt": "a fox"})]


def test_the_qualified_name_is_told_too_and_draws_its_image(dispatcher):
    """Only an admin reaches an `mcp__` name. It was given what the model
    wrote, owner included, and its image link stayed in the text."""
    run, mcp = dispatcher
    _desc, result = run("mcp__image_gen__generate_image",
                        json.dumps({"prompt": "a fox", "_pantheon_owner": MEMBER}), ADMIN)
    assert mcp.calls == [("mcp__image_gen__generate_image",
                          {"prompt": "a fox", "_pantheon_owner": ADMIN})]
    assert result["image_url"] == IMAGE_LINK


# ── the server ───────────────────────────────────────────────────────────────

class _Reply:
    status_code = 200
    text = ""

    def json(self):
        return {"data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nfox").decode()}]}


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        return _Reply()


@pytest.fixture
def image_server(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import httpx
    import mcp_servers.image_gen_server as server
    import src.ai_interaction as ai_interaction
    import src.settings as settings

    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(legacy_database, "SessionLocal", factory)
    monkeypatch.setattr(server, "GENERATED_IMAGES_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None, *a, **k: default)
    monkeypatch.setattr(settings, "load_settings", lambda *a, **k: {"image_model": "gpt-image-1"})
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    resolved = []

    def resolve(spec, owner=None, model_type=None):
        resolved.append(owner)
        return "https://images.example/v1/chat/completions", "gpt-image-1", {}

    monkeypatch.setattr(ai_interaction, "_resolve_model", resolve)

    def make(arguments):
        resolved.clear()
        text = asyncio.run(server.call_tool("generate_image", arguments))[0].text
        assert "Direct link: /api/generated-image/" in text, text
        return list(resolved)

    def rows():
        with factory() as db:
            return [(r.prompt, r.owner) for r in db.query(cdb.GalleryImage).all()]

    yield make, rows
    engine.dispose()


def test_the_gallery_row_is_the_persons_and_the_model_is_found_among_theirs(image_server):
    make, rows = image_server
    assert set(make({"prompt": "a fox", "_pantheon_owner": MEMBER})) == {MEMBER}
    # Named by nobody, or by a blank, an image is made as it always was.
    assert set(make({"prompt": "a cat", "_pantheon_owner": "   "})) == {None}
    assert set(make({"prompt": "an owl"})) == {None}
    assert rows() == [("a fox", MEMBER), ("a cat", None), ("an owl", None)]


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def route(monkeypatch, tmp_path):
    from src import generated_images
    from tests.helpers.fresh_import import import_app_in_this_test

    app_module = import_app_in_this_test(monkeypatch)
    image_dir = tmp_path / "generated"
    image_dir.mkdir()
    (image_dir / "0123456789ab.png").write_bytes(b"\x89PNG\r\n\x1a\nfox")
    monkeypatch.setattr(generated_images, "GENERATED_IMAGE_DIR", image_dir)
    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(cdb.GalleryImage(id="g1", filename="0123456789ab.png", prompt="a fox", owner=MEMBER))
        db.commit()
    monkeypatch.setattr(cdb, "SessionLocal", factory)

    def ask(person):
        request = SimpleNamespace(state=SimpleNamespace(current_user=person))
        return app_module.serve_generated_image("0123456789ab.png", request)

    yield ask, monkeypatch
    engine.dispose()


def test_its_maker_alone_is_served_it_and_for_their_browser_alone(route):
    ask, _monkeypatch = route
    response = ask(MEMBER)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    with pytest.raises(HTTPException) as refused:
        ask(ADMIN)
    assert refused.value.status_code == 404


def test_an_ownership_check_that_fails_serves_nothing(route):
    ask, monkeypatch = route

    def broken():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(cdb, "SessionLocal", broken)
    with pytest.raises(HTTPException) as refused:
        ask(ADMIN)
    assert refused.value.status_code == 503
