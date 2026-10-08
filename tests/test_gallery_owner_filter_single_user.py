# SPDX-License-Identifier: AGPL-3.0-or-later
"""_owner_filter separated single-user mode from anonymous callers.

When AUTH_ENABLED=false, get_current_user returned None and gallery routes
stayed all-visible; with auth on, the same None meant an anonymous caller and
gallery queries failed closed. There is always authentication now
(`D-2026-10-07-02` §2), so None is an anonymous caller whatever the variable
says, and every query for it fails closed.
"""
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryImage
from routes.gallery_helpers import _owner_filter

_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_ENGINE = create_engine(f"sqlite:///{_TMPDB.name}", connect_args={"check_same_thread": False}, poolclass=NullPool)
cdb.Base.metadata.create_all(_ENGINE)
_TS = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False)


def _seed(*owners):
    db = _TS()
    try:
        db.query(GalleryImage).delete()
        for o in owners:
            db.add(GalleryImage(id=str(uuid.uuid4()), filename=f"{uuid.uuid4().hex}.png", owner=o))
        db.commit()
    finally:
        db.close()


def test_none_user_sees_nothing_whatever_auth_enabled_says(monkeypatch):
    """Single-user mode returned every row here (3) until `D-2026-10-07-02` §2.
    `AUTH_ENABLED=false` is ignored now: nobody sees nothing."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _seed(None, None, "alice")
    db = _TS()
    try:
        assert _owner_filter(db.query(GalleryImage), None).count() == 0
    finally:
        db.close()


def test_named_user_is_still_scoped():
    _seed("alice", "alice", "bob", None)
    db = _TS()
    try:
        assert _owner_filter(db.query(GalleryImage), "alice").count() == 2
        assert _owner_filter(db.query(GalleryImage), "bob").count() == 1
    finally:
        db.close()


def test_none_user_blocks_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _seed(None, "alice", "bob")
    db = _TS()
    try:
        assert _owner_filter(db.query(GalleryImage), None).count() == 0
    finally:
        db.close()
