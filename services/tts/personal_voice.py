# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1730`. Each person's own Conversation: the switch, and the voice it speaks in.

The owner, 2026-11-01, on the switch that makes the agent say its replies:
*"This should be a "Conversation" switch not speak replies aloud - we make it
personal-able"*. So both are a person's own preferences (`/api/prefs`, beside
their shortcuts), never the instance's settings an admin writes:

- `conversation`: `true` while the agent says every reply out loud as it is
  written (the composer's Conversation chip, and Settings → Conversation);
- `conversation_voice`: `{"engine", "voice", "speed"}`, the voice they hear,
  everywhere Pantheon speaks to them (Conversation, the read-aloud button and
  a voice chat). `engine` "" is the server's voice (Settings → Voice, an
  admin's); "browser" is their own device's voices, which the page speaks with
  and the server never sees. `speed` `None` is the voice's own.

Held to a shape here, and read back through `choice_for`, because
`routes/tts_routes.py` hands what is stored to the voice service, and the
page merges it into a select.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

CONVERSATION_PREF = "conversation"
CONVERSATION_VOICE_PREF = "conversation_voice"

# The engines a person may pick: the three this server speaks with, and their
# own device's. `local` (Kokoro through PyTorch on a CUDA GPU) and
# `endpoint:<id>` stay the admin's to choose as the server's voice.
PERSONAL_ENGINES = ("kokoro", "chatterbox", "piper", "browser")
_VOICE_MAX = 120
SPEED_MIN, SPEED_MAX = 0.5, 2.0


def checked_conversation(value: Any) -> bool:
    """The stored switch, or a 400."""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise HTTPException(400, "Conversation is on (true) or off (false).")
    return value


def checked_voice(value: Any) -> Optional[Dict[str, Any]]:
    """The stored voice, or a 400 saying what is wrong with it. `None` (or
    an empty object) is the server's voice at its own speed."""
    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise HTTPException(400, "Your voice is an object of engine, voice and speed.")
    engine = value.get("engine") or ""
    if not isinstance(engine, str) or (engine and engine not in PERSONAL_ENGINES):
        raise HTTPException(400, f"“{str(engine)[:40]}” is not a voice you can choose "
                                 f"({', '.join(PERSONAL_ENGINES)}, or blank for the server's).")
    voice = value.get("voice") or ""
    if not isinstance(voice, str) or len(voice) > _VOICE_MAX:
        raise HTTPException(400, "That voice's name is not one.")
    speed = value.get("speed")
    if speed is not None:
        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            raise HTTPException(400, "Speed is a number, like 1 or 1.25.")
        if not SPEED_MIN <= float(speed) <= SPEED_MAX:
            raise HTTPException(400, f"Speed is between {SPEED_MIN:g}× and {SPEED_MAX:g}×.")
        speed = float(speed)
    return {"engine": engine, "voice": voice.strip(), "speed": speed}


def choice_from(value: Any) -> Optional[Dict[str, Any]]:
    """`checked_voice` for what is already stored: a value that is not one
    (written by hand, or by an older build) is the server's voice, never an
    error on every sentence."""
    try:
        return checked_voice(value)
    except HTTPException:
        return None


def prefs_for(user: Optional[str]) -> Dict[str, Any]:
    from routes.prefs_routes import _load_for_user
    try:
        return _load_for_user(user)
    except Exception:  # an unreadable store speaks in the server's voice
        return {}


def choice_for(user: Optional[str]) -> Optional[Dict[str, Any]]:
    """The voice `user` chose for themselves, or `None` for the server's."""
    return choice_from(prefs_for(user).get(CONVERSATION_VOICE_PREF))


def conversation_on(user: Optional[str]) -> bool:
    return prefs_for(user).get(CONVERSATION_PREF) is True
