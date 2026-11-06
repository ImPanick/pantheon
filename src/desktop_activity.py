# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the agent's hand did on a workstation desktop, for the screen window to
draw. `B1754` (Panick, 2026-11-06: *"does it have a dedicated Agent mouse? (Fit
to theme, of course)"*, then "Overlay hand on the desktop" on the card).

The live browser has had its hand since `P25-07`: an arrow in the theme's
accent that glides to where the agent acts, a ring where a click lands, and a
caption saying what it does (`static/js/browserWindow.js`). The desktop had
none — the agent moved the real X pointer, the stock one, which is the
person's pointer too, so nothing on the screen said whose hand it was. This is
the desktop's feed for the same hand.

**Recorded where the agent acts.** `computer` (`src/agent_tools/computer_tools.py`)
says each input action here before it sends it (`begin`, phase "doing") and
marks it after (`finish`, "done" or "failed"). A screenshot is not an action
on the screen and is not recorded; a person's own input is never recorded —
their hand is theirs, and the window draws only the agent's.

**Kept in this process, per account, briefly.** Like `screen_marks`, which the
same tool keeps per person: a feed of the last `KEPT` actions, each forgotten
after `TTL_S`. A restart forgets them, which costs a hand that has not moved
yet — never an action. The route that reads it is
`GET /api/workstation/desktop/activity` (`routes/workstation_routes.py`).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

KEPT = 40
TTL_S = 600.0
PHASES = ("doing", "done", "failed")
#: The point fields an entry carries, in the screen's own pixels.
_POINTS = ("x", "y", "to_x", "to_y")
_LABEL_MAX = 160

_lock = threading.Lock()
_feeds: Dict[str, List[Dict[str, Any]]] = {}
_last = 0   # the newest seq handed out in this process


def _next() -> int:
    global _last
    _last += 1
    return _last


def _key(account: Optional[str]) -> str:
    return str(account or "").strip().lower()


def _prune(feed: List[Dict[str, Any]], now: float) -> None:
    feed[:] = [e for e in feed if now - e["_at"] <= TTL_S][-KEPT:]


def begin(account: Optional[str], action: str, label: str, args: Dict[str, Any]) -> Optional[int]:
    """One agent action said before it is done; its id, or None for nobody."""
    key = _key(account)
    if not key:
        return None
    now = time.monotonic()
    with _lock:
        seq = _next()
        entry: Dict[str, Any] = {"id": seq, "seq": seq, "_at": now, "at": time.time(),
                                 "who": "agent", "action": str(action),
                                 "label": str(label or action)[:_LABEL_MAX], "phase": "doing"}
        for k in _POINTS:
            v = args.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                entry[k] = v
        feed = _feeds.setdefault(key, [])
        feed.append(entry)
        _prune(feed, now)
    return seq


def finish(account: Optional[str], entry_id: Optional[int], ok: bool) -> None:
    """The action marked done (or failed), with a new `seq` so a reader that
    already saw it "doing" hears that it ended."""
    if entry_id is None:
        return
    with _lock:
        for e in _feeds.get(_key(account), []):
            if e["id"] == entry_id:
                e["phase"] = "done" if ok else "failed"
                e["seq"] = _next()
                return


def since(account: Optional[str], seq: int = 0) -> Dict[str, Any]:
    """`{"activity": [...], "seq": n}`: the entries changed after `seq`,
    oldest first, and the newest `seq` there is to ask after next time. A
    `seq` from before a restart (newer than any here) reads as 0, so a window
    left open across one keeps drawing."""
    now = time.monotonic()
    with _lock:
        if seq > _last:
            seq = 0
        feed = _feeds.get(_key(account), [])
        _prune(feed, now)
        out = [{k: v for k, v in e.items() if not k.startswith("_")}
               for e in sorted(feed, key=lambda e: e["seq"]) if e["seq"] > seq]
        newest = _last
    return {"activity": out, "seq": newest}


def forget(account: Optional[str] = None) -> None:
    """One account's feed dropped (a reset), or every feed (the tests)."""
    with _lock:
        if account is None:
            _feeds.clear()
        else:
            _feeds.pop(_key(account), None)


__all__ = ["KEPT", "PHASES", "TTL_S", "begin", "finish", "forget", "since"]
