# SPDX-License-Identifier: AGPL-3.0-or-later
"""What deleting a chat takes out of the gallery.

A chat's pictures go with it: the images stamped with its id and the ones its
tool events name. `B1811`: the tool events were the whole rule, whoever owned
the image and whichever chat it belonged to, and a fork (the Fork button on a
reply, or /fork) copies its source's tool events on purpose
(`test_fork_session_metadata.py`). So deleting a fork retired every picture the
original still showed and unlinked the files, and deleting the original broke
the fork's pictures the same way. A chat whose stored metadata named someone
else's image (`update-last-meta` merges what its caller sends) deleted that
too.

Now a chat takes only its owner's images or ownerless ones (the built-in
image_gen MCP server stamps no owner), only those no other chat owns, and none
that another chat still shows; the last chat that shows a picture takes it
along. Driven: the real `SessionManager.delete_session` over a real SQLite
file, with one picture from each of Pantheon's three image writers.

Upstream Odysseus fixed the cross-chat half in e5e23e64
(`session_gallery_images`; its scope test is reused below). Its owner rule
skips ownerless images, which would leave the MCP server's pictures behind for
good when their chat goes, so that part is Pantheon's own.
"""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.session_manager as session_manager_module
from core.database import Base, ChatMessage, GalleryImage, Session
from src import session_image_cleanup


def test_cleanup_session_images_deactivates_gallery_rows_and_unlinks_files(tmp_path, monkeypatch):
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    linked_file = image_dir / "aaaaaaaaaaaa.png"
    event_file = image_dir / "bbbbbbbbbbbb.png"
    linked_file.write_bytes(b"linked")
    event_file.write_bytes(b"event")
    monkeypatch.setattr(session_image_cleanup, "GENERATED_IMAGES_DIR", str(image_dir))

    engine = create_engine(
        f"sqlite:///{tmp_path / 'cleanup.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        db.add(Session(id="chat-1", name="Image chat", endpoint_url="http://local", model="image-model", owner="alice"))
        db.add(
            GalleryImage(
                id="img-linked",
                filename=linked_file.name,
                prompt="linked",
                owner="alice",
                session_id="chat-1",
                is_active=True,
            )
        )
        db.add(
            GalleryImage(
                id="img-event",
                filename=event_file.name,
                prompt="event",
                owner="alice",
                is_active=True,
            )
        )
        db.add(
            ChatMessage(
                id="msg-1",
                session_id="chat-1",
                role="assistant",
                content="Generated image",
                meta_data=json.dumps(
                    {
                        "tool_events": [
                            {
                                "image_id": "img-event",
                                "image_url": f"/api/generated-image/{event_file.name}",
                            }
                        ]
                    }
                ),
            )
        )
        db.commit()

        removed = session_image_cleanup.cleanup_session_images("chat-1", db=db)

        assert removed == 2
        assert not linked_file.exists()
        assert not event_file.exists()
        assert db.query(GalleryImage).filter_by(id="img-linked").first().is_active is False
        assert db.query(GalleryImage).filter_by(id="img-event").first().is_active is False
    finally:
        db.close()


# One picture from each of Pantheon's image writers, and the tool event each
# chat stores for it.
CHAT_PIC, EDIT_PIC, MCP_PIC = "111111111111.png", "222222222222.png", "333333333333.png"
EVENTS = [
    # The image chat (`ai_interaction._save_to_gallery`): stamps the chat and
    # its owner; the stream stores image_id and image_url.
    {"tool": "generate_image", "image_id": "img-chat", "image_url": f"/api/generated-image/{CHAT_PIC}"},
    # The agent's edit_image (`src/tools/image.py`): stamps the owner only; the
    # agent loop stores image_url only.
    {"tool": "edit_image", "image_url": f"/api/generated-image/{EDIT_PIC}"},
    # The agent's generate_image through the built-in image_gen MCP server:
    # stamps neither.
    {"tool": "generate_image", "image_url": f"/api/generated-image/{MCP_PIC}"},
]
KEPT = {"img-chat": (True, True), "img-edit": (True, True), "img-mcp": (True, True)}
GONE = {"img-chat": (False, False), "img-edit": (False, False), "img-mcp": (False, False)}


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    monkeypatch.setattr(session_image_cleanup, "GENERATED_IMAGES_DIR", str(image_dir))
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chats.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(session_manager_module, "SessionLocal", factory)
    manager = session_manager_module.SessionManager.__new__(session_manager_module.SessionManager)
    manager.sessions = {}
    yield SimpleNamespace(dir=image_dir, db=factory, manager=manager)
    engine.dispose()


def _chat(db, chat_id, owner, events):
    db.add(Session(id=chat_id, name=chat_id, endpoint_url="http://local", model="image-model", owner=owner))
    db.flush()
    for n, event in enumerate(events):
        db.add(ChatMessage(id=f"{chat_id}-{n}", session_id=chat_id, role="assistant",
                           content="Here it is", meta_data=json.dumps({"tool_events": [event]})))


def _original(gallery):
    """Alice's chat A, with one picture from each writer."""
    for name in (CHAT_PIC, EDIT_PIC, MCP_PIC):
        (gallery.dir / name).write_bytes(b"png")
    with gallery.db() as db:
        _chat(db, "A", "alice", EVENTS)
        db.add(GalleryImage(id="img-chat", filename=CHAT_PIC, prompt="a cat", owner="alice",
                            session_id="A", is_active=True))
        db.add(GalleryImage(id="img-edit", filename=EDIT_PIC, prompt="the cat, upscaled",
                            owner="alice", is_active=True))
        db.add(GalleryImage(id="img-mcp", filename=MCP_PIC, prompt="a dog", is_active=True))
        db.commit()


def _fork(gallery, source, fork_id):
    """What `fork_session` stores: the source's owner, each message's metadata copied."""
    with gallery.db() as db:
        origin = db.get(Session, source)
        db.add(Session(id=fork_id, name=f"Fork: {origin.name}", endpoint_url=origin.endpoint_url,
                       model=origin.model, owner=origin.owner))
        db.flush()
        for message in db.query(ChatMessage).filter_by(session_id=source).order_by(ChatMessage.id):
            db.add(ChatMessage(id=f"{fork_id}-{message.id}", session_id=fork_id, role=message.role,
                               content=message.content, meta_data=message.meta_data))
        db.commit()


def _pictures(gallery):
    """Each image's (still in the gallery, file still on disk)."""
    with gallery.db() as db:
        return {img.id: (img.is_active, (gallery.dir / img.filename).exists())
                for img in db.query(GalleryImage).all()}


def test_deleting_a_fork_keeps_every_picture_the_original_shows(gallery):
    _original(gallery)
    _fork(gallery, "A", "B")

    assert gallery.manager.delete_session("B")

    assert _pictures(gallery) == KEPT


def test_deleting_the_original_keeps_what_its_fork_shows_and_the_fork_takes_it_along(gallery):
    _original(gallery)
    _fork(gallery, "A", "B")

    assert gallery.manager.delete_session("A")
    assert _pictures(gallery) == KEPT
    with gallery.db() as db:
        assert db.get(GalleryImage, "img-chat").session_id is None, "its chat is gone"

    assert gallery.manager.delete_session("B")
    assert _pictures(gallery) == GONE


def test_a_chat_on_its_own_still_takes_every_picture_along(gallery):
    # Unchanged, and the ownerless MCP picture is among them: a rule that read
    # only the chat owner's images would leave it behind, a live row and a
    # file nobody's gallery lists.
    _original(gallery)

    assert gallery.manager.delete_session("A")

    assert _pictures(gallery) == GONE


def test_a_chat_that_names_someone_elses_pictures_deletes_none_of_them(gallery):
    _original(gallery)
    with gallery.db() as db:
        _chat(db, "X", "bob", EVENTS)
        db.commit()

    assert gallery.manager.delete_session("X")

    assert _pictures(gallery) == KEPT


def test_hundreds_of_pictures_are_checked_in_slices_sqlite_can_read(gallery):
    # Each picture is two LIKE terms, and SQLite refuses an OR chain of more
    # than 1,000. Unsliced, the check fails and the last chat leaves them all.
    names = [f"{n:012x}.png" for n in range(520)]
    with gallery.db() as db:
        db.add(Session(id="A", name="A", endpoint_url="http://local", model="image-model", owner="alice"))
        db.flush()
        for n, name in enumerate(names):
            db.add(GalleryImage(id=f"img-{n}", filename=name, prompt="", owner="alice",
                                session_id="A", is_active=True))
        db.add(ChatMessage(id="A-0", session_id="A", role="assistant", content="Here they are",
                           meta_data=json.dumps({"tool_events": [
                               {"image_id": f"img-{n}", "image_url": f"/api/generated-image/{name}"}
                               for n, name in enumerate(names)]})))
        db.commit()
    _fork(gallery, "A", "B")

    assert gallery.manager.delete_session("B")
    with gallery.db() as db:
        assert db.query(GalleryImage).filter_by(is_active=True).count() == 520

    assert gallery.manager.delete_session("A")
    with gallery.db() as db:
        assert db.query(GalleryImage).filter_by(is_active=True).count() == 0


def test_image_references_do_not_delete_another_chat_or_owners_gallery(tmp_path, monkeypatch):
    # Upstream Odysseus e5e23e64 (tests/test_chat_image_preservation.py), with
    # len() for .count(): Pantheon's selector returns a list.
    engine = create_engine(f"sqlite:///{tmp_path / 'scope.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(session_image_cleanup, "GENERATED_IMAGES_DIR", str(tmp_path))
    with factory() as db:
        db.add(Session(id="chat", name="Test", endpoint_url="http://example.test", model="test", owner="alice"))
        db.add(Session(id="other-chat", name="Other", endpoint_url="http://example.test", model="test", owner="alice"))
        for image_id, owner, chat in [("other-owner", "bob", None), ("other-chat-image", "alice", "other-chat")]:
            db.add(GalleryImage(id=image_id, filename=image_id + ".png", owner=owner, session_id=chat, is_active=True))
        db.add(ChatMessage(id="message", session_id="chat", role="assistant", content="References",
                           meta_data=json.dumps({"tool_events": [{"image_id": "other-owner"},
                                                                 {"image_id": "other-chat-image"}]})))
        db.commit()
        assert len(session_image_cleanup.session_gallery_images(db, "chat")) == 0
        assert session_image_cleanup.cleanup_session_images("chat", db=db) == 0
        assert all(image.is_active for image in db.query(GalleryImage).all())
    engine.dispose()
