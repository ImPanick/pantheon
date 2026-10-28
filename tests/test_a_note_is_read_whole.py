# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a note opened by its id is read whole.

`manage_notes`' own schema tells a model to "use list/search to find candidate
notes, then view with the note id when you need the full body". `view` printed
the note through the listing's formatter — its title and the first 80
characters of its body — so the full body was never reachable. Found writing
Bookmark Librarian, whose links live in one note, and Language Partner and
Tutor, which read the person's answers from a note: each saw the first line
and nothing after it. A listing still shows a snippet; a note opened shows all
of itself.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from src.agents import evals as E

LINKS = "\n".join(f"https://site{n}.example/article-{n}" for n in range(1, 9))


def _call(action: str, **extra) -> dict:
    from src.tools.notes import do_manage_notes
    return asyncio.run(do_manage_notes(json.dumps({"action": action, **extra}), owner=E.EVAL_OWNER))


def test_a_long_note_opened_by_its_id_shows_its_whole_body_and_a_listing_a_snippet():
    from core.database import Note
    with E.isolated() as (factory, _data):
        db = factory()
        nid = str(uuid.uuid4())
        db.add(Note(id=nid, owner=E.EVAL_OWNER, title="Bookmarks", content=LINKS))
        db.commit()
        db.close()
        viewed = json.dumps(_call("view", id=nid[:8]))
        listed = json.dumps(_call("list"))
    assert "https://site8.example/article-8" in viewed, "the eighth link, well past 80 characters"
    assert "https://site1.example/article-1" in viewed
    assert "https://site8.example/article-8" not in listed, "a listing stays a snippet"


def test_a_checklist_opened_by_its_id_still_shows_every_item():
    from core.database import Note
    with E.isolated() as (factory, _data):
        db = factory()
        nid = str(uuid.uuid4())
        db.add(Note(id=nid, owner=E.EVAL_OWNER, title="Packing", note_type="checklist",
                    items=json.dumps([{"text": "Passport", "done": True}, {"text": "Adapter", "done": False}])))
        db.commit()
        db.close()
        viewed = json.dumps(_call("view", id=nid))
    assert "[x] 0: Passport" in viewed and "[ ] 1: Adapter" in viewed
