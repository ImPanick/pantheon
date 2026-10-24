# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-01` … `P26-03` · Notes pinned to the live page, kept by the daemon.

The owner (2026-10-24): *"the "Design" suite - where you can add real-time
notes to the browser similar to how Claude has it as well as Codex."*

A note belongs to an **element**, not a pixel: when it is made, the page is
asked what is under the point (`browser.ANCHOR_FN`) and the note keeps what
finds that element again — a selector, its tag and role, a little of its text.
Each frame the window shows, the page is asked where those elements are now
(`browser.LOCATE_FN`), so a note follows its element through a reflow, a resize
or a re-render, and says *lost* — never floats over the wrong thing — when the
element is gone.

A drawing (arrow, circle, box, free line) is kept in page pixels with the
note it was drawn beside; the window draws it over the frame and crops the
two together when the notes are sent (`P26-03`), so the model is shown the
mark, not asked to imagine coordinates.

The notes are the person's browser's own, kept here beside it — one
`NoteBook` per account, written to the browser profile's folder so a
restart keeps them — and the agent reads and closes them through the same
daemon (`agent_browser notes`, `note_done`): one list, two hands.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

NOTES_FILE = "pantheon-notes.json"
NOTES_MAX = 200
NOTE_TEXT_MAX = 2000
SAID_MAX = 600
SHAPES_MAX = 12
POINTS_MAX = 200
SHAPE_KINDS = ("arrow", "circle", "box", "line")
STATUSES = ("open", "sent", "done", "declined")


class NoteRefused(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _page_key(url: str) -> str:
    """A note is for a page: its address without the fragment."""
    return str(url or "").split("#", 1)[0][:2000]


def clean_shape(raw: Any, width: int, height: int) -> Dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("kind") not in SHAPE_KINDS:
        raise NoteRefused(f"A drawing is one of {', '.join(SHAPE_KINDS)}.")
    pts = raw.get("points")
    if not isinstance(pts, list) or not 2 <= len(pts) <= POINTS_MAX:
        raise NoteRefused(f"A drawing has 2 to {POINTS_MAX} points.")
    out = []
    for p in pts:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)):
            raise NoteRefused("A point is [x, y] on the page.")
        # Relative to the note's element, so a drawing follows it: a mark
        # beside the element is a negative offset, bounded by a screen each way.
        out.append([max(-width, min(int(p[0]), 2 * width)), max(-height, min(int(p[1]), 2 * height))])
    if raw["kind"] != "line":
        out = [out[0], out[-1]]
    return {"kind": raw["kind"], "points": out}


class NoteBook:
    """One account's notes, across pages."""

    def __init__(self, folder: Optional[Path]):
        self.path = (folder / NOTES_FILE) if folder else None
        self.lock = threading.Lock()
        self.notes: List[Dict[str, Any]] = []
        self.next_n = 1
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return   # a notes file that cannot be read starts an empty book; the browser itself is unaffected
        if isinstance(data, dict) and isinstance(data.get("notes"), list):
            self.notes = [n for n in data["notes"] if isinstance(n, dict) and "id" in n][:NOTES_MAX]
            self.next_n = max([int(n.get("n") or 0) for n in self.notes] + [0]) + 1

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"notes": self.notes}), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass   # unsaved notes still live in memory for this run; the next save tries again

    def _get(self, note_id: Any) -> Dict[str, Any]:
        for n in self.notes:
            if n["id"] == note_id or (isinstance(note_id, int) and n.get("n") == note_id):
                return n
        raise NoteRefused(f"There is no note {note_id}.")

    def add(self, url: str, anchor: Dict[str, Any], text: str, at: List[int]) -> Dict[str, Any]:
        text = str(text or "").strip()
        if len(text) > NOTE_TEXT_MAX:
            raise NoteRefused(f"A note is at most {NOTE_TEXT_MAX} characters.")
        with self.lock:
            live = [n for n in self.notes if n["status"] in ("open", "sent")]
            if len(live) >= NOTES_MAX:
                raise NoteRefused(f"At most {NOTES_MAX} open notes; close some first.")
            note = {"id": f"note-{int(time.time() * 1000):x}-{self.next_n}", "n": self.next_n,
                    "page": _page_key(url), "anchor": anchor, "at": at, "text": text,
                    "shapes": [], "status": "open", "said": "", "created": time.time()}
            self.next_n += 1
            self.notes = [n for n in self.notes if n["status"] in ("open", "sent")] + \
                [n for n in self.notes if n["status"] not in ("open", "sent")][-NOTES_MAX:]
            self.notes.append(note)
            self._save()
            return dict(note)

    def edit(self, note_id: Any, *, text: Optional[str] = None, shapes: Optional[List] = None,
             width: int = 0, height: int = 0) -> Dict[str, Any]:
        with self.lock:
            n = self._get(note_id)
            if text is not None:
                text = str(text).strip()
                if len(text) > NOTE_TEXT_MAX:
                    raise NoteRefused(f"A note is at most {NOTE_TEXT_MAX} characters.")
                n["text"] = text
            if shapes is not None:
                if not isinstance(shapes, list) or len(shapes) > SHAPES_MAX:
                    raise NoteRefused(f"At most {SHAPES_MAX} drawings on one note.")
                n["shapes"] = [clean_shape(s, width, height) for s in shapes]
            self._save()
            return dict(n)

    def remove(self, note_id: Any) -> None:
        with self.lock:
            n = self._get(note_id)
            self.notes.remove(n)
            self._save()

    def mark(self, note_ids: List[Any], status: str, said: str = "") -> List[Dict[str, Any]]:
        if status not in STATUSES:
            raise NoteRefused(f"A note's status is one of {', '.join(STATUSES)}.")
        out = []
        with self.lock:
            for i in note_ids:
                n = self._get(i)
                n["status"] = status
                if said:
                    n["said"] = str(said)[:SAID_MAX]
                out.append(dict(n))
            self._save()
        return out

    def for_page(self, url: Optional[str] = None, *, open_only: bool = False) -> List[Dict[str, Any]]:
        key = _page_key(url) if url is not None else None
        with self.lock:
            return [dict(n) for n in self.notes
                    if (key is None or n["page"] == key)
                    and (not open_only or n["status"] in ("open", "sent"))]
