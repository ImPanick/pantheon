# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a note's listing says when it is due.

`manage_notes` keeps a reminder's `due_date`, and its `list` and `search`
printed every note's title and the first 80 characters of its body — never the
date. So Morning Brief, whose runbook has always said "keep the notes due today
or overdue", and Home Maintenance, Bill & Renewal Tracker and Gift & Date
Keeper after it, were told to sort by a date the tool never showed them: a
model could only guess. Found writing Morning Brief's substance (`P24-27`).
"""

from __future__ import annotations

import asyncio
import json
import uuid

from src.agents import evals as E


def _list(action: str = "list", **extra) -> str:
    from src.tools.notes import do_manage_notes
    out = asyncio.run(do_manage_notes(json.dumps({"action": action, **extra}), owner=E.EVAL_OWNER))
    return out.get("results") or out.get("response") or ""


def test_a_reminder_is_listed_with_its_due_date_and_a_plain_note_without_one():
    from core.database import Note
    with E.isolated() as (factory, _data):
        db = factory()
        db.add(Note(id=str(uuid.uuid4()), owner=E.EVAL_OWNER, title="Renew passport",
                    content="Form at the post office", due_date="2026-10-25T09:00:00"))
        db.add(Note(id=str(uuid.uuid4()), owner=E.EVAL_OWNER, title="Gift ideas", content="Books"))
        db.commit()
        db.close()
        listed = _list()
        found = _list("search", query="passport")
    lines = {ln.split("**")[1]: ln for ln in listed.split("\n") if "**" in ln}
    assert "due 2026-10-25T09:00:00" in lines["Renew passport"]
    assert "due" not in lines["Gift ideas"]
    assert "due 2026-10-25T09:00:00" in found, "a search shows the date too"
