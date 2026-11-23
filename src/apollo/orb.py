# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's orb: what the model may point it at (phase 6).

The orb is drawn in the browser (`static/js/apolloOrb.js`). The model moves it
with `ui_control show <place> ...`, and this module turns that command into the
`orb_show` event the browser follows. It names places, not CSS, because a model
doesn't know the page: the pane, a section of it, one task, the composer, a
code block in the chat (with a line range), or a code view another part of the
app has registered by name, such as an editor.

Nothing here reads or changes anything on the server. Pointing is the
browser's own business, and a place the page doesn't have is a no-op there.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# place -> what follows it: None (nothing), "id" (required token), "n" (optional count)
PLACES: Dict[str, Optional[str]] = {
    "home": None,         # back to where the person put it
    "pane": None,         # Apollo's pane
    "needs_you": None,    # the pane's Needs you section
    "activity": None,     # the pane's Activity section
    "task": "id",         # one task's row in the pane
    "chat_input": None,   # the composer
    "code": "n",          # a code block in this chat; 1 is the newest
    "view": "id",         # a code view registered by name (an editor, a diff)
}
ALIASES = {"composer": "chat_input", "input": "chat_input", "needs": "needs_you",
           "editor": "view", "back": "home"}
MAX_LINES = 400          # the widest line range one show may mark
MAX_LABEL = 140          # the words beside the orb stay a line
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_RANGE = re.compile(r"^(?:lines?=)?(\d{1,6})(?:\s*[-–:]\s*(\d{1,6}))?$")

USAGE = ("show needs: show <place> [id] [lines=A-B] [label]. Places: "
         + ", ".join(PLACES) + ".")


def parse_lines(text: str) -> Optional[List[int]]:
    """`12-18`, `lines=12-18` or `12` as [from, to]; None when it isn't one.
    A backwards range is put the right way round; a range wider than
    `MAX_LINES` is cut to it."""
    m = _RANGE.match(str(text or "").strip())
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if a < 1 or b < 1:
        return None
    a, b = min(a, b), max(a, b)
    return [a, min(b, a + MAX_LINES - 1)]


def show(parts: List[str]) -> Dict[str, Any]:
    """`parts` is the command split into words, `show` first."""
    words = [str(p) for p in parts[1:]]
    if not words:
        return {"error": USAGE}
    place = words.pop(0).strip().lower()
    place = ALIASES.get(place, place)
    if place not in PLACES:
        return {"error": f"There is no place called “{place}”. {USAGE}"}
    out: Dict[str, Any] = {"ui_event": "orb_show", "place": place}
    takes = PLACES[place]
    if takes == "id":
        if not words or not _ID.match(words[0]):
            return {"error": f"show {place} needs the {'task id' if place == 'task' else 'view name'} next."}
        out["target"] = words.pop(0)
    elif (takes == "n" and words and words[0].isdigit() and not words[0].startswith("0")
          and not (len(words) > 2 and words[1] in ("-", "–", "to"))):
        out["target"] = min(int(words.pop(0)), 50)
    if words and place in ("code", "view"):
        lines = None
        if len(words) > 2 and words[1] in ("-", "–", "to"):   # "12 - 18", "12 to 18"
            lines = parse_lines(f"{words[0]}-{words[2]}")
            if lines:
                del words[:3]
        if lines is None:
            lines = parse_lines(words[0])
            if lines:
                words.pop(0)
        if lines:
            out["lines"] = lines
    label = " ".join(w for w in words if w).strip()
    if label:
        out["label"] = label[:MAX_LABEL]
    what = {"home": "Sent the orb home", "pane": "Pointing at the pane",
            "needs_you": "Pointing at Needs you", "activity": "Pointing at Activity",
            "task": f"Pointing at task {out.get('target', '')}", "chat_input": "Pointing at the message box",
            "code": "Pointing at the code", "view": f"Pointing at {out.get('target', '')}"}[place]
    if "lines" in out:
        a, b = out["lines"]
        what += f", line {a}" if a == b else f", lines {a} to {b}"
    out["results"] = what + ". If that place isn't on their screen, nothing moves."
    return out


def show_content(args: Dict[str, Any]) -> str:
    """The structured `ui_control` call (`action: show`) as the command line
    `do_ui_control` reads: name is the place, value its id or count."""
    bits = ["show", str(args.get("name") or args.get("place") or "").strip()]
    value = str(args.get("value") or args.get("target") or "").strip()
    if value:
        bits.append(value)
    lines = str(args.get("lines") or "").strip()
    if lines:
        bits.append(f"lines={lines.replace(' ', '')}")
    label = str(args.get("label") or "").strip()
    if label:
        bits.append(" ".join(label.split()))
    return " ".join(b for b in bits if b)
