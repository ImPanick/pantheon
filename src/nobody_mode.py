# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2097`. Nobody mode keeps nothing.

The button says *"Nobody — no memory, nothing saved"* (`static/index.html`),
and the owner's ruling is that it means it: *"Nobody mode is 'incognito' which
should 'discard' everything in that session."* Until this module the chat's
own transcript was the only thing it kept out of storage. A picture made in
Nobody was written to disk and to the Gallery with its prompt, and the prompt
logged; the agent could write a document, a note, a calendar event, a task, a
todo list or a research report; an uploaded photo went into the Gallery; a
reply read aloud went into the speech cache; and every tool call's first line
went into the log.

One rule, in one place, and two ways it is applied:

* **What the agent may not reach** (`withheld_writes`): every tool whose
  registered effect is ``write_private`` — a write into what Pantheon keeps
  for the person (`src/tool_capabilities.py`) — beside the reads of their
  memory, past chats, skills and sessions this mode always withheld (listed
  where they always were, `routes/chat_routes.py`). Derived from the effects
  register, so a write tool added later is withheld without anyone
  remembering this list. ``generate_image`` and ``edit_image`` are the
  exceptions: they run, keeping nothing (below), because a picture shown and
  not saved is what Nobody can honestly offer.
* **What a writer does when it runs anyway** (`keeps_nothing`): the turn sets
  a flag (`turn_scope`) that the writers on its path ask — the image maker
  returns its picture as data instead of a file, the speech cache, the upload
  promotions and the event log keep nothing of it.

And when the chat ends, `forget_session` takes whatever an older build left
behind with it, instead of detaching it into the Library.
"""
from __future__ import annotations

import base64
import contextvars
import logging
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

#: What the browser names a Nobody chat (`static/js/sessions.js`), and the
#: name an older build used. The startup purge (`app.py`) already went by
#: these; now every reader does.
NOBODY_SESSION_NAMES = ("Nobody", "Incognito")

#: Write tools that still run in Nobody, because they keep nothing there: a
#: picture made or edited is shown in the chat as data, with no file and no
#: Gallery row (`src/ai_interaction.py`, `src/tools/image.py`). `edit_image`
#: is also the name the direct image path asks about for an attached photo
#: (`B1814`), so withholding it would refuse that edit outright.
KEPT_RUNNING = frozenset({"generate_image", "edit_image"})

#: Said to the model in place of a picture's data (`format_tool_result`).
SHOWN_NOT_SAVED = "(shown to the person in this chat; Nobody mode saves no file)"

_keeps_nothing: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "pantheon_nobody_turn", default=False
)


def keeps_nothing() -> bool:
    """Whether the work running now is a Nobody turn's."""
    return _keeps_nothing.get()


@contextmanager
def turn_scope(enabled: bool) -> Iterator[None]:
    """Mark the work inside as a Nobody turn's when *enabled*.

    A task or a worker thread started inside inherits the mark (`asyncio`
    copies the context), which is how a picture made in a task the stream
    awaits still knows."""
    token = _keeps_nothing.set(bool(enabled))
    try:
        yield
    finally:
        try:
            _keeps_nothing.reset(token)
        except ValueError:
            # Ended in another context (a streamed reply's generator closed
            # elsewhere); that context's copy goes with it.
            pass


def withheld_writes() -> frozenset:
    """Every tool that writes into what Pantheon keeps for the person, less the
    ones that run keeping nothing: what Nobody withholds beside its reads."""
    from src.tool_capabilities import TOOL_CAPABILITIES, ToolEffect

    from src.tool_execution import _MCP_TOOL_MAP

    writes = {
        name for name, caps in TOOL_CAPABILITIES.items()
        if ToolEffect.WRITE_PRIVATE in caps.effects
    }
    bare = writes - KEPT_RUNNING
    # A built-in server's tool reaches the model by its bare name; the
    # qualified spelling of a withheld one is withheld with it, so neither
    # spelling is a way round (`mcp__rag__manage_rag`).
    qualified = {
        f"mcp__{server}__{tool}" for name, (server, tool) in _MCP_TOOL_MAP.items()
        if name in bare
    }
    return frozenset(bare | qualified)


def is_nobody_session_name(name: Optional[str]) -> bool:
    return (name or "").strip() in NOBODY_SESSION_NAMES


_PICTURE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def picture_data_url(raw: bytes) -> str:
    """A picture as a ``data:`` address the chat draws (`safeDisplayImageSrc`
    takes png, jpeg, gif and webp), for a picture that has no file."""
    mime = "image/png"
    for signature, kind in _PICTURE_SIGNATURES:
        if raw.startswith(signature):
            mime = kind
            break
    else:
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def is_data_url(value) -> bool:
    return isinstance(value, str) and value.startswith("data:")


def forget_session(db, session_id: str) -> None:
    """Take a Nobody chat's leftovers with it: its pictures and their files,
    its documents and their versions, its messages, and its transcript held in
    memory. The caller deletes the chat's row and commits.

    A Nobody turn writes none of these now; this is for what an older build
    wrote, and for a session someone ends while a turn is still running."""
    from core.database import ChatMessage, Document, DocumentVersion
    from src.session_image_cleanup import (
        _generated_image_path_for_cleanup,
        session_gallery_images,
    )

    for img in session_gallery_images(db, session_id):
        path = _generated_image_path_for_cleanup(img.filename) if img.filename else None
        if path is not None and path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not remove a Nobody chat's picture: %s", exc)
        db.delete(img)

    doc_ids = [row[0] for row in db.query(Document.id).filter(Document.session_id == session_id).all()]
    if doc_ids:
        db.query(DocumentVersion).filter(DocumentVersion.document_id.in_(doc_ids)).delete(
            synchronize_session=False)
        db.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)

    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete(
        synchronize_session=False)

    try:
        from routes.chat_helpers import forget_incognito_transcript
        forget_incognito_transcript(session_id)
    except Exception:  # noqa: BLE001 — the transcript also expires on its own
        pass
