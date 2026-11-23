# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's voice: one character, a few dials the person sets, and nudges
Apollo makes from their reactions that they can see and undo in one tap.

The outline (*Personality, adaptation and brand*): "One consistent character
with dials the person sets: terse or warm, playful or dry, how often it
checks in ... The presets in `src/reminder_personas.py` set the starting
point." Settled call 1 is B: "Apollo nudges them from your reactions, shows
each change, and one tap undoes it."

- **Dials.** `warmth` (terse to warm) and `play` (dry to playful) run from -2
  to 2; 0 is Apollo's own voice. How often it checks in is the rhythm's
  check-in interval (`rhythm.py`), which Apollo may nudge too, but never turn
  on or off.
- **Presets** set the dials to a starting point named after the built-in
  characters that fit Apollo's one rule of leading with the point (Razor,
  Spark, Strategist). Socrates (answers only in questions) and Nietzsche
  (one philosophy for everything) don't, so they aren't offered here.
- **Nudges.** Apollo moves a dial one step with a reason drawn from what the
  person did. Each nudge is shown and undoable. It never nudges a dial the
  person set in the last week, never in a direction they undid in the last
  month, and at most once a day per dial.
- **Pushback is not a dial.** `PUSHBACK` is in every frame, whatever the dials
  say (and in `frame.CHARACTER`); `pushback.py` measures each model on it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.apollo.errors import ApolloRefused

DIALS = ("warmth", "play")
LOW, HIGH = -2, 2
ENDS = {"warmth": ("terse", "warm"), "play": ("dry", "playful"), "checkins": ("fewer", "more")}
TOWARD = {w: (dial, -1 if i == 0 else 1) for dial, pair in ENDS.items() for i, w in enumerate(pair)}

PRESETS = {
    "apollo": {"name": "Apollo", "warmth": 0, "play": 0},
    "razor": {"name": "Razor", "warmth": -2, "play": -2},
    "strategist": {"name": "Strategist", "warmth": 0, "play": -1},
    "spark": {"name": "Spark", "warmth": 1, "play": 2},
}

LINES = {
    "warmth": {
        -2: "Be terse: the answer and nothing else. No greeting, no softeners.",
        -1: "Be brief and businesslike.",
        1: "Be warm: a friendly word where it fits, and notice how things went for them.",
        2: "Be very warm and personal: ask after the small things they mentioned (how Thursday went), and still keep it short.",
    },
    "play": {
        -2: "Be dry: no jokes, no exclamation marks.",
        -1: "Keep it mostly dry; a light touch at most.",
        1: "Be a little playful: a light line when the moment allows, and joke back when they joke.",
        2: "Be playful: quick wit and lively phrasing, never at the cost of the point.",
    },
}

PUSHBACK = ("No voice setting softens pushback: when a plan has a hole or they're wrong, say so "
            "plainly with the evidence, and hold to it if they push without new evidence.")

HISTORY_MAX = 40
QUIET_AFTER_PERSON = timedelta(days=7)
RESPECT_UNDO = timedelta(days=30)
ONE_A_DAY = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() + "Z" if d else None


def _when(text: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text).rstrip("Z"))
    except (TypeError, ValueError):
        return None


def row(db, owner: str, *, make: bool = True):
    from core.database import ApolloVoice
    r = db.query(ApolloVoice).filter(ApolloVoice.owner == owner).first()
    if r is None and make:
        r = ApolloVoice(owner=owner, warmth=0, play=0, preset="apollo", changes="[]")
        db.add(r)
        db.flush()
    return r


def _changes(r) -> List[Dict[str, Any]]:
    try:
        out = json.loads(r.changes or "[]") if r is not None else []
        return [c for c in out if isinstance(c, dict)] if isinstance(out, list) else []
    except ValueError:
        return []


def _keep(r, changes: List[Dict[str, Any]]) -> None:
    r.changes = json.dumps(changes[-HISTORY_MAX:])


def _value(db, owner: str, r, dial: str) -> int:
    if dial == "checkins":
        from src.apollo import rhythm
        return int(rhythm.to_dict(db, owner)["checkin_hours"])
    return int(getattr(r, dial) or 0)


def _apply(db, owner: str, r, dial: str, value: int) -> None:
    if dial == "checkins":
        from src.apollo import rhythm
        rhythm.save(db, owner, checkin_hours=int(value))
    else:
        setattr(r, dial, int(value))


def _record(r, dial: str, old: int, new: int, by: str, reason: Optional[str] = None,
            **extra) -> Dict[str, Any]:
    change = {"id": uuid.uuid4().hex[:12], "dial": dial, "from": old, "to": new, "by": by,
              "reason": reason, "at": _iso(_now()), "undone": False, **extra}
    changes = _changes(r)
    changes.append(change)
    _keep(r, changes)
    return change


def _dial_value(value: Any, dial: str) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ApolloRefused(f"{dial} is a whole number from {LOW} to {HIGH}.")
    if not LOW <= v <= HIGH:
        raise ApolloRefused(f"{dial} runs from {LOW} to {HIGH}.")
    return v


def set_voice(db, owner: str, *, warmth: Any = None, play: Any = None, preset: Any = None) -> Dict[str, Any]:
    """The person sets a preset, a dial, or both (a dial wins over its preset)."""
    r = row(db, owner)
    target: Dict[str, int] = {}
    if preset is not None:
        key = str(preset).strip().lower()
        if key not in PRESETS:
            raise ApolloRefused("That isn't one of Apollo's presets.")
        r.preset = key
        target.update({d: PRESETS[key][d] for d in DIALS})
    if warmth is not None:
        target["warmth"] = _dial_value(warmth, "warmth")
    if play is not None:
        target["play"] = _dial_value(play, "play")
    for dial, value in target.items():
        old = int(getattr(r, dial) or 0)
        if old != value:
            setattr(r, dial, value)
            _record(r, dial, old, value, "person")
    if preset is None and target:
        match = [k for k, p in PRESETS.items() if all(p[d] == int(getattr(r, d) or 0) for d in DIALS)]
        r.preset = match[0] if match else None
    db.flush()
    return to_dict(db, owner)


def _direction(change: Dict[str, Any]) -> int:
    """+1 toward the second end of the dial (warm, playful, more), else -1."""
    went_up = (change.get("to") or 0) > (change.get("from") or 0)
    if change.get("dial") == "checkins":
        went_up = not went_up          # a shorter interval is more check-ins
    return 1 if went_up else -1


def _steps(dial: str) -> List[int]:
    if dial == "checkins":
        from src.apollo.rhythm import CHECKIN_HOURS
        # Fewer check-ins is a longer interval. 0 (off) is never a nudge.
        return sorted((h for h in CHECKIN_HOURS if h), reverse=True)
    return list(range(LOW, HIGH + 1))


def nudge(db, owner: str, toward: Any, reason: Any) -> Dict[str, Any]:
    """Apollo moves one dial one step `toward` an end (terse, warm, dry,
    playful, fewer, more), with the reason from the person's reactions.
    Refused, in a sentence Apollo can pass on, when the person set that dial
    lately, undid that direction lately, it was nudged today, it's already at
    the end, or (for check-ins) they're off."""
    word = str(toward or "").strip().lower()
    if word not in TOWARD:
        raise ApolloRefused("A nudge goes toward terse, warm, dry, playful, fewer or more (check-ins).")
    why = " ".join(str(reason or "").split())
    if not why:
        raise ApolloRefused("A nudge needs the reason: what they did that suggests it.")
    if len(why) > 200:
        raise ApolloRefused("Keep the reason to a line.")
    dial, sign = TOWARD[word]
    r = row(db, owner)
    now = _now()
    for c in reversed(_changes(r)):
        if c.get("dial") != dial:
            continue
        at = _when(c.get("at")) or now
        if c.get("by") == "person" and not c.get("undo_of") and now - at < QUIET_AFTER_PERSON:
            raise ApolloRefused(f"They set {dial} themselves this week, so leave it.")
        if c.get("by") == "apollo" and now - at < ONE_A_DAY:
            raise ApolloRefused(f"{dial.capitalize()} was already nudged today.")
        if c.get("undone") and c.get("by") == "apollo" and now - at < RESPECT_UNDO \
                and _direction(c) == sign:
            raise ApolloRefused(f"They undid a nudge toward {word} this month, so don't try it again.")
    old = _value(db, owner, r, dial)
    steps = _steps(dial)
    if dial == "checkins" and old == 0:
        raise ApolloRefused("Check-ins are off; only they turn them on.")
    if old not in steps:
        raise ApolloRefused(f"{dial.capitalize()} isn't at a setting Apollo can step from.")
    i = steps.index(old) + sign
    if not 0 <= i < len(steps):
        raise ApolloRefused(f"{dial.capitalize()} is already as {word} as it goes.")
    new = steps[i]
    _apply(db, owner, r, dial, new)
    change = _record(r, dial, old, new, "apollo", why)
    db.flush()
    return change


def undo(db, owner: str, change_id: Any) -> Dict[str, Any]:
    """Put a dial back where a change found it. One tap, either side's change."""
    r = row(db, owner)
    changes = _changes(r)
    hit = next((c for c in changes if c.get("id") == str(change_id or "")), None)
    if hit is None:
        raise ApolloRefused("That change isn't in Apollo's voice history.", 404)
    if hit.get("undone"):
        raise ApolloRefused("That change was already undone.", 409)
    later = [c for c in changes[changes.index(hit) + 1:] if c.get("dial") == hit["dial"] and not c.get("undone")]
    if later:
        raise ApolloRefused("The dial has moved since; undo the newer change first.", 409)
    if hit["dial"] == "checkins" and _value(db, owner, r, "checkins") == 0:
        raise ApolloRefused("Check-ins are off now, so there's nothing to put back.", 409)
    _apply(db, owner, r, hit["dial"], hit["from"])
    hit["undone"] = True
    _keep(r, changes)
    _record(r, hit["dial"], hit["to"], hit["from"], "person", None, undo_of=hit["id"])
    db.flush()
    return to_dict(db, owner)


def describe(change: Dict[str, Any]) -> str:
    """A change in plain words: "Apollo made itself warmer: …"."""
    dial, up = change.get("dial"), (change.get("to") or 0) > (change.get("from") or 0)
    if dial == "checkins":
        up = (change.get("to") or 0) < (change.get("from") or 0)   # a shorter interval is more
        what = "checks in more often" if up else "checks in less often"
        words = f"now every {change.get('to')} hours" if change.get("to") != 1 else "now every hour"
        head = f"Apollo {what} ({words})" if change.get("by") == "apollo" else f"Check-ins {words}"
    else:
        word = ENDS[dial][1 if up else 0]
        comp = {"terse": "terser", "warm": "warmer", "dry": "drier", "playful": "more playful"}[word]
        head = f"Apollo made itself {comp}" if change.get("by") == "apollo" else f"You made Apollo {comp}"
    return f"{head}: {change['reason']}" if change.get("reason") else f"{head}."


def lines_for(warmth: int = 0, play: int = 0) -> List[str]:
    """What the frame says of a voice: one line per dial off centre, then the
    pushback line, which is always there."""
    out = [LINES[d][v] for d, v in (("warmth", int(warmth or 0)), ("play", int(play or 0))) if v]
    out.append(PUSHBACK)
    return out


def lines(db, owner: str) -> List[str]:
    r = row(db, owner, make=False)
    return lines_for(getattr(r, "warmth", 0), getattr(r, "play", 0))


def to_dict(db, owner: str) -> Dict[str, Any]:
    r = row(db, owner)
    changes = _changes(r)
    recent = [dict(c, words=describe(c)) for c in reversed(changes)
              if c.get("by") == "apollo" and not c.get("undone")][:3]
    return {"warmth": int(r.warmth or 0), "play": int(r.play or 0), "preset": r.preset,
            "presets": [{"id": k, "name": p["name"], "warmth": p["warmth"], "play": p["play"]}
                        for k, p in PRESETS.items()],
            "nudges": recent, "pushback": PUSHBACK}
