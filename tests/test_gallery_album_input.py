# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2005`. An album rename or move with a malformed body was a 500, or a blank name.

`PUT /api/gallery/albums/{id}` stored the `name` and `description` it was
sent as they came: a name of spaces became the album's name, and a number, a
list or an object failed in the database as a bare 500. A body that was not
a JSON object (an array, `null`, or not JSON at all) was a 500 as well.
`POST /api/gallery/albums/{id}/add` and `/remove` handed `image_ids` straight
to the query, so a string, a number or `null` was a 500 too, and so was a new
album (`POST /api/gallery/albums`) whose name was not text. The Gallery never
sends any of these (it trims, refuses a blank name and always sends a list),
but an API token or the agent's `app_api` can, and a 500 tells neither what
to correct.

Now each of the four routes checks its body before it opens the database and
answers 400 saying what was wrong. What the Gallery sends is answered as
before, except that a rename's name is stored trimmed, as a new album's
already was.

Ported from upstream Odysseus 76061498 (#6822); its cases are upstream's,
with `cover_id` and album creation checked as well.
"""
import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryAlbum, GalleryImage
import routes.gallery_routes as gallery_routes

NOT_JSON = object()


class _Request:
    """All the album routes read of a request: its JSON body."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        if self._body is NOT_JSON:
            raise json.JSONDecodeError("Expecting property name", "{not json", 1)
        return self._body


def _no_database():
    raise AssertionError("the database was opened before the body was checked")


def _refused(monkeypatch, path, method, body, *path_args):
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda request: "alice")
    monkeypatch.setattr(gallery_routes, "SessionLocal", _no_database)
    route = next(r for r in gallery_routes.setup_gallery_routes().routes
                 if r.path == path and method in r.methods)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(route.endpoint(_Request(body), *path_args))
    assert refused.value.status_code == 400
    return refused.value.detail


@pytest.mark.parametrize("body", [
    {"name": ""},
    {"name": "   "},
    {"name": 123},
    {"name": ["x"]},
    {"description": {"a": 1}},
    {"cover_id": ["x"]},
    {"cover_id": 5},
    [1],
    None,
    NOT_JSON,
])
def test_a_rename_with_a_blank_name_or_a_malformed_body_is_refused_first(monkeypatch, body):
    _refused(monkeypatch, "/api/gallery/albums/{album_id}", "PUT", body, "album-1")


@pytest.mark.parametrize("verb", ["add", "remove"])
@pytest.mark.parametrize("body", [
    {"image_ids": "abc"},
    {"image_ids": 5},
    {"image_ids": None},
    {"image_ids": [{"a": 1}]},
    {"image_ids": ["ok", 1]},
    [1],
    NOT_JSON,
])
def test_image_ids_that_are_not_a_list_of_ids_are_refused_first(monkeypatch, verb, body):
    _refused(monkeypatch, f"/api/gallery/albums/{{album_id}}/{verb}", "POST", body, "album-1")


@pytest.mark.parametrize("body", [
    {"name": 123},
    {"name": ["x"]},
    {"name": "Trip", "description": {"a": 1}},
    [1],
    NOT_JSON,
])
def test_a_new_album_with_a_malformed_body_is_refused_first(monkeypatch, body):
    _refused(monkeypatch, "/api/gallery/albums", "POST", body)


def test_the_refusal_says_what_was_wrong(monkeypatch):
    album = "/api/gallery/albums/{album_id}"
    assert _refused(monkeypatch, f"{album}/add", "POST",
                    {"image_ids": "abc"}, "a") == "image_ids must be a list of image ids"
    assert _refused(monkeypatch, album, "PUT", {"name": "  "}, "a") == "Album name required"
    assert _refused(monkeypatch, album, "PUT", [1], "a") == "The request body must be a JSON object."
    assert _refused(monkeypatch, album, "PUT", NOT_JSON, "a") == "The request body must be JSON."


@pytest.fixture()
def gallery(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'albums.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(gallery_routes, "SessionLocal", factory)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda request: "alice")
    db = factory()
    try:
        db.add_all([
            GalleryAlbum(id="album-alice", name="Alice album", owner="alice"),
            GalleryAlbum(id="album-bob", name="Bob album", owner="bob"),
            *(GalleryImage(id=f"img-{owner}", filename=f"{uuid.uuid4().hex}.png",
                           prompt="p", model="m", tags="", ai_tags="", owner=owner,
                           album_id=f"album-{owner}", is_active=True, file_size=10)
              for owner in ("alice", "bob")),
        ])
        db.commit()
    finally:
        db.close()
    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    yield TestClient(app), factory
    engine.dispose()


def _row(factory, model, row_id):
    db = factory()
    try:
        return db.get(model, row_id)
    finally:
        db.close()


def test_a_rename_and_a_new_cover_from_the_gallery_are_answered_as_before(gallery):
    http, factory = gallery
    url = "/api/gallery/albums/album-alice"
    assert http.put(url, json={"name": "Trip"}).json() == {"ok": True}
    assert http.put(url, json={"cover_id": "img-alice"}).json() == {"ok": True}
    album = _row(factory, GalleryAlbum, "album-alice")
    assert (album.name, album.cover_id) == ("Trip", "img-alice")
    assert http.put(url, json={"cover_id": ""}).json() == {"ok": True}
    assert _row(factory, GalleryAlbum, "album-alice").cover_id is None


def test_moving_pictures_out_of_and_into_an_album_is_answered_as_before(gallery):
    http, factory = gallery
    url = "/api/gallery/albums/album-alice"
    assert http.post(f"{url}/remove", json={"image_ids": ["img-alice"]}).json() == {"ok": True}
    assert _row(factory, GalleryImage, "img-alice").album_id is None
    assert http.post(f"{url}/add", json={"image_ids": ["img-alice"]}).json() == {"ok": True, "count": 1}
    assert _row(factory, GalleryImage, "img-alice").album_id == "album-alice"


def test_a_new_album_from_the_gallery_is_made_as_before(gallery):
    http, factory = gallery
    made = http.post("/api/gallery/albums", json={"name": "  Vacation 2026 "}).json()
    assert made["ok"] is True and made["name"] == "Vacation 2026"
    assert _row(factory, GalleryAlbum, made["id"]).owner == "alice"


def test_someone_elses_picture_is_still_neither_a_cover_nor_moved(gallery):
    http, factory = gallery
    url = "/api/gallery/albums/album-alice"
    assert http.put(url, json={"cover_id": "img-bob"}).status_code == 404
    assert http.post(f"{url}/add", json={"image_ids": ["img-bob"]}).status_code == 200
    assert _row(factory, GalleryImage, "img-bob").album_id == "album-bob"


def test_a_renamed_album_keeps_its_name_without_the_spaces_around_it(gallery):
    http, factory = gallery
    assert http.put("/api/gallery/albums/album-alice", json={"name": "  Trip  "}).status_code == 200
    assert _row(factory, GalleryAlbum, "album-alice").name == "Trip"


def test_a_body_that_is_not_json_is_answered_400_over_http(gallery):
    http, _factory = gallery
    res = http.put("/api/gallery/albums/album-alice", content=b"{not json",
                   headers={"Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["detail"] == "The request body must be JSON."
