# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2004`. The Gallery search box matched what was typed only as one phrase.

`GET /api/gallery/library?search=` (the Gallery's search box, and the email
composer's attach-from-gallery search) built a single `%{search}%` LIKE over
the prompt, the tags and the AI tags. Two words were found only side by side
and in that order, so *red car* missed *a car that is red* and *a red sports
car on a beach* — and AI prompts are long, so that is the ordinary case. A
`%` or an `_` in the box was a wildcard rather than a character: `%` showed
every picture. The tag filter (`?tag=`) had the same wildcards.

Now every word typed must appear somewhere in the prompt, tags or AI tags, in
any order, and `%`, `_` and `\\` are matched as themselves (escaped with
`escape_like_pattern`, the helper Ctrl+K's title search already used,
`B1249`). Only the first sixteen words count: one LIKE clause per word, and
SQLite refuses an expression nested about a thousand deep, so an uncapped
chain would turn a pasted paragraph into a 500 where the single LIKE answered.

Ported from upstream Odysseus 04f8546d (#6584); the cases are upstream's,
with an owner on every picture (a null user sees nothing in Pantheon).
"""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryImage
import routes.gallery_routes as gallery_routes

PICTURES = {
    # id: (prompt, tags, owner)
    "img-red-car": ("a car that is red", "", "alice"),
    "img-red-sports": ("a red sports car on a beach", "", "alice"),
    "img-boat": ("blue boat on the lake", "lake", "alice"),
    "img-percent": ("100% cotton shirt", "sale_2024", "alice"),
    "img-backslash": (r"C:\photos\sunset", "", "alice"),
    "img-bob-red-car": ("a red car", "", "bob"),
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gallery_search.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(gallery_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda request: "alice")

    db = session_factory()
    try:
        db.add_all([
            GalleryImage(
                id=image_id, filename=f"{uuid.uuid4().hex}.png", prompt=prompt,
                model="model-a", tags=tags, ai_tags="", owner=owner,
                is_active=True, file_size=10,
            )
            for image_id, (prompt, tags, owner) in PICTURES.items()
        ])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    yield TestClient(app)
    engine.dispose()


def _found(client, **params):
    res = client.get("/api/gallery/library", params=params)
    assert res.status_code == 200, res.text
    return {item["id"] for item in res.json()["items"]}


def test_two_words_find_every_picture_that_has_both_in_any_order(client):
    assert _found(client, search="red car") == {"img-red-car", "img-red-sports"}
    assert _found(client, search="car red") == {"img-red-car", "img-red-sports"}


def test_a_percent_sign_or_an_underscore_in_the_search_is_a_character(client):
    assert _found(client, search="%") == {"img-percent"}
    assert _found(client, search="_") == {"img-percent"}


def test_a_percent_sign_or_an_underscore_in_the_tag_filter_is_a_character(client):
    assert _found(client, tag="%") == set()
    assert _found(client, tag="_") == {"img-percent"}


def test_a_backslash_finds_only_the_prompt_that_has_one(client):
    assert _found(client, search="\\") == {"img-backslash"}


def test_one_word_or_a_phrase_in_order_finds_what_it_found_before(client):
    assert _found(client, search="beach") == {"img-red-sports"}
    assert _found(client, search="RED") == {"img-red-car", "img-red-sports"}
    assert _found(client, search="red sports car") == {"img-red-sports"}
    assert _found(client, search="cotton", tag="sale_2024") == {"img-percent"}


def test_a_pasted_paragraph_gets_an_answer_and_not_a_server_error(client):
    paragraph = " ".join(f"word{i}" for i in range(2000))
    assert _found(client, search=paragraph) == set()
