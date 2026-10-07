# SPDX-License-Identifier: AGPL-3.0-or-later
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryAlbum, GalleryImage
import routes.gallery_routes as gallery_routes


def _client_with_gallery(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gallery.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(gallery_routes, "SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add_all(
            [
                GalleryAlbum(id="album-alice", name="Alice album", owner="alice"),
                GalleryAlbum(id="album-bob", name="Bob album", owner="bob"),
                GalleryImage(
                    id="img-alice",
                    filename=f"{uuid.uuid4().hex}.png",
                    prompt="alice prompt",
                    model="model-a",
                    tags="alice-tag",
                    ai_tags="",
                    owner="alice",
                    album_id="album-alice",
                    is_active=True,
                    file_size=10,
                ),
                GalleryImage(
                    id="img-bob",
                    filename=f"{uuid.uuid4().hex}.png",
                    prompt="bob prompt",
                    model="model-b",
                    tags="bob-tag",
                    ai_tags="",
                    owner="bob",
                    album_id="album-bob",
                    is_active=True,
                    file_size=20,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    return TestClient(app)


def test_auth_enabled_null_user_gallery_routes_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    client = _client_with_gallery(monkeypatch, tmp_path)

    library = client.get("/api/gallery/library").json()
    assert library["items"] == []
    assert library["total"] == 0
    assert library["total_tagged"] == 0
    assert library["tags"] == []
    assert library["models"] == []

    shuffled = client.get("/api/gallery/library", params={"sort": "shuffle"}).json()
    assert shuffled["items"] == []
    assert shuffled["total"] == 0

    assert client.get("/api/gallery/tags").json() == {"tags": []}
    assert client.get("/api/gallery/albums").json() == {"albums": []}
    assert client.get("/api/gallery/stats").json() == {
        "total_photos": 0,
        "total_size": 0,
        "total_size_human": "0.0 B",
        "favorites": 0,
        "albums": 0,
    }
    assert client.post("/api/gallery/ai-tag-batch").json() == {
        "ok": True,
        "queued": 0,
        "total_untagged": 0,
        "image_ids": [],
    }


def test_auth_enabled_false_null_user_gallery_routes_fail_closed_too(monkeypatch, tmp_path):
    """Under `AUTH_ENABLED=false` a null user kept single-user mode — both
    people's images, tags, albums and stats, and a batch tag of all of them —
    until `D-2026-10-07-02` §2. The variable is ignored now: the same caller
    gets what the test above gets with it on."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    client = _client_with_gallery(monkeypatch, tmp_path)

    library = client.get("/api/gallery/library").json()
    assert library["items"] == [] and library["total"] == 0
    assert library["tags"] == [] and library["models"] == []
    assert client.get("/api/gallery/tags").json() == {"tags": []}
    assert client.get("/api/gallery/albums").json() == {"albums": []}
    assert client.get("/api/gallery/stats").json()["total_photos"] == 0
    batch = client.post("/api/gallery/ai-tag-batch").json()
    assert batch["queued"] == 0 and batch["image_ids"] == []


def test_authenticated_gallery_routes_remain_owner_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda request: "alice")
    client = _client_with_gallery(monkeypatch, tmp_path)

    library = client.get("/api/gallery/library").json()
    assert [item["id"] for item in library["items"]] == ["img-alice"]
    assert library["total"] == 1
    assert library["tags"] == ["alice-tag"]
    assert library["models"] == ["model-a"]

    assert client.get("/api/gallery/tags").json() == {"tags": ["alice-tag"]}
    albums = client.get("/api/gallery/albums").json()["albums"]
    assert [album["id"] for album in albums] == ["album-alice"]
    assert client.get("/api/gallery/stats").json() == {
        "total_photos": 1,
        "total_size": 10,
        "total_size_human": "10.0 B",
        "favorites": 0,
        "albums": 1,
    }
    assert client.post("/api/gallery/ai-tag-batch").json() == {
        "ok": True,
        "queued": 1,
        "total_untagged": 1,
        "image_ids": ["img-alice"],
    }
