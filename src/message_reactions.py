# SPDX-License-Identifier: AGPL-3.0-or-later
"""
message_reactions.py

Emoji reactions between the person and the model, both ways (`B1736`).

The owner (2026-11-01): the model can "heart" a detailed idea message (one
that gives it a really good amount of information, so it need not chase
thoughts down), thumbs-up a steer, laugh when humour is applied; and the
person can do the same to the model's replies.

How each direction works, on any model:

* **The model reacts** by opening its reply with a marker, ``[react:❤️]``.
  No tool call: a marker works in Chat mode, on models with no tool calling,
  and on small local models (gpt-oss, Qwen Coder, Gemma through LM Studio or
  Ollama) as well as cloud ones. A spelled name is accepted too
  (``[react: heart]``), since small models often write the word. The marker
  never reaches the screen: `ReactionStreamFilter` lifts it out of the live
  stream and sends a ``reaction`` event instead, and `take_reaction` lifts it
  out of the saved reply. The reaction is stored on the person's message as
  ``metadata.reactions.assistant``.
* **The person reacts** from a reply's footer (``POST
  /api/session/{id}/react``). The reaction is stored on the reply as
  ``metadata.reactions.user`` and the model hears about it on its next turn
  through one short application note before the latest message
  (`reaction_note`), naming at most `NOTE_LIMIT` recent replies.

Budget: the instruction is one constant system line (it keeps the system
prompt byte-identical turn to turn, so a local server's prompt cache holds),
and the note is absent on most turns. Both are skipped when the person turns
Reactions off (`reactions_enabled` preference).

A leaf: nothing here imports the app at module load, so routes and the loop
can both import it.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: The person's palette, in the order the picker shows it.
USER_REACTIONS: Tuple[str, ...] = ("👍", "❤️", "😂", "🎉", "🤔", "👎")
#: The model's palette: no thumbs-down at the person.
MODEL_REACTIONS: Tuple[str, ...] = ("👍", "❤️", "😂", "🎉", "🤔")

#: What each reaction means, said to the model in the note.
MEANING = {
    "👍": "acknowledged",
    "❤️": "loved it",
    "😂": "found it funny",
    "🎉": "celebrating",
    "🤔": "unsure about it",
    "👎": "it missed",
}

#: Names a model may write for an emoji, lower case, separators dropped.
_NAMES = {
    "👍": ("thumbsup", "thumbup", "+1", "like", "ok", "ack", "yes", "thumbs"),
    "❤️": ("heart", "love", "redheart", "<3"),
    "😂": ("laugh", "joy", "lol", "haha", "funny", "laughing", "tearsofjoy"),
    "🎉": ("tada", "party", "celebrate", "hooray", "partypopper", "congrats"),
    "🤔": ("thinking", "think", "hmm", "thinkingface"),
    "👎": ("thumbsdown", "dislike", "-1"),
}

#: The most replies the note names on one turn, and how far back it looks.
NOTE_LIMIT = 3
NOTE_LOOKBACK = 4

_SKIN_AND_VARIATION = re.compile("[︎️\U0001f3fb-\U0001f3ff‍]")


def normalize(raw: Any, allowed: Tuple[str, ...] = USER_REACTIONS) -> Optional[str]:
    """The palette emoji `raw` names, or None. Takes the emoji itself (with or
    without its variation selector or a skin tone) or one of its names."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().strip(":").strip()
    if not value:
        return None
    bare = _SKIN_AND_VARIATION.sub("", value)
    for emoji in allowed:
        if bare == _SKIN_AND_VARIATION.sub("", emoji):
            return emoji
    word = re.sub(r"[\s_\-]+", "", value.lower()) if value not in ("+1", "-1") else value
    for emoji in allowed:
        if word in _NAMES.get(emoji, ()):
            return emoji
    return None


# ── the turn's switch ────────────────────────────────────────────────────────

_turn_on: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "pantheon_reactions_turn", default=False
)


def wanted(uprefs: Optional[dict], *, compare_mode: bool = False) -> bool:
    """Whether this person's chat turn offers the model a reaction. Compare
    mode sends one message to several models side by side, where a reaction
    from each would be noise."""
    if compare_mode:
        return False
    return bool((uprefs or {}).get("reactions_enabled", True))


def turn_enabled() -> bool:
    return _turn_on.get()


@contextmanager
def turn_scope(enabled: bool) -> Iterator[None]:
    token = _turn_on.set(bool(enabled))
    try:
        yield
    finally:
        try:
            _turn_on.reset(token)
        except ValueError:
            # The scope ended in another context (a streamed reply's generator
            # closed elsewhere); that context's copy goes with it.
            pass


# ── the marker ───────────────────────────────────────────────────────────────

_MARKER_RE = re.compile(
    r"\[\s*react(?:ion)?\s*[:=]\s*([^\[\]\n]{1,32}?)\s*\][ \t]*(?:\r?\n)?",
    re.IGNORECASE,
)
_MARKER_MAX = 48

INSTRUCTION = (
    "Reactions: like a colleague in chat, you may react to the person's latest "
    "message with one emoji by starting your reply with [react:EMOJI], using "
    "one of " + " ".join(MODEL_REACTIONS) + ". ❤️ a detailed, well-specified "
    "idea; 👍 a steer or correction you will follow; 😂 real humour. Most "
    "messages get none. The marker is hidden; never mention it."
)


def take_reaction(text: Any) -> Tuple[Any, Optional[str]]:
    """`text` without its reaction markers, and the first marker's emoji (None
    when there was none or it named nothing in the model's palette)."""
    if not isinstance(text, str) or "[" not in text:
        return text, None
    found: List[Optional[str]] = []

    def _cut(match: re.Match) -> str:
        found.append(normalize(match.group(1), MODEL_REACTIONS))
        return ""

    cleaned = _MARKER_RE.sub(_cut, text)
    if not found:
        return text, None
    emoji = next((e for e in found if e), None)
    return cleaned, emoji


def _could_become_marker(tail: str) -> bool:
    """Whether `tail` (starting at ``[``) may still grow into a marker."""
    if len(tail) > _MARKER_MAX or "\n" in tail or "]" in tail:
        return False
    body = tail[1:].lstrip().lower()
    word = re.match(r"[a-z]*", body).group(0)
    rest = body[len(word):]
    if not rest.strip():
        return "reaction".startswith(word)
    if word not in ("react", "reaction"):
        return False
    return rest.lstrip()[:1] in (":", "=")


class ReactionStreamFilter:
    """Lifts reaction markers out of a chat stream's SSE text.

    A marker may arrive split over several deltas, so text from a ``[`` that
    could still become one is held back (at most `_MARKER_MAX` characters) until
    it either closes as a marker, which is dropped and announced once as
    ``data: {"type": "reaction", "role": "assistant", "emoji": …}``, or turns out
    to be ordinary text, which is sent on. Thinking deltas pass untouched, and
    anything that is not a delta first flushes what is held so order is kept.
    """

    def __init__(self) -> None:
        self._held = ""
        self._held_data: Optional[dict] = None
        self.emoji: Optional[str] = None
        self._announced = False
        # A marker split from the words after it leaves their leading space.
        self._trim_next = False

    @staticmethod
    def _parse(chunk: Any) -> Optional[dict]:
        if not isinstance(chunk, str) or not chunk.startswith("data: "):
            return None
        body = chunk[6:].strip()
        if not body.startswith("{"):
            return None
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("delta"), str):
            return None
        if data.get("thinking") or data.get("type"):
            return None
        return data

    @staticmethod
    def _frame(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    def flush(self) -> List[str]:
        if not self._held:
            return []
        data = dict(self._held_data or {})
        data["delta"] = self._held
        self._held, self._held_data = "", None
        return [self._frame(data)]

    def feed(self, chunk: Any) -> List[str]:
        data = self._parse(chunk)
        if data is None:
            return self.flush() + [chunk]
        text = self._held + data["delta"]
        self._held, self._held_data = "", None
        if self._trim_next:
            text = text.lstrip(" \t")
            self._trim_next = not text
        out: List[str] = []
        if "[" in text:
            cleaned, emoji = take_reaction(text)
            if cleaned != text:
                text = cleaned
                self._trim_next = not text
                if emoji and not self._announced:
                    self.emoji = emoji
                    self._announced = True
                    out.append(self._frame(
                        {"type": "reaction", "role": "assistant", "emoji": emoji}))
            cut = text.rfind("[")
            if cut >= 0 and _could_become_marker(text[cut:]):
                self._held, self._held_data = text[cut:], data
                text = text[:cut]
        if text:
            data = dict(data)
            data["delta"] = text
            out.append(self._frame(data))
        return out


# ── what the model is told ───────────────────────────────────────────────────

def _metadata(message: Any) -> dict:
    meta = message.get("metadata") if isinstance(message, dict) else getattr(message, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _plain(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text") or "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _opening(content: Any, words: int = 8) -> str:
    text = re.sub(r"<(think|thinking)>.*?</\1>", " ", _plain(content), flags=re.S | re.I)
    text = re.sub(r"[`*_#>\[\]]+", " ", text)
    parts = text.split()
    if not parts:
        return ""
    snippet = " ".join(parts[:words])
    return snippet + ("…" if len(parts) > words else "")


def reaction_note(messages: List[Dict[str, Any]]) -> Optional[str]:
    """One short line on the person's recent reactions to the model's replies,
    or None. Looks at the last `NOTE_LOOKBACK` replies and names at most
    `NOTE_LIMIT`; the newest reply is called "your last reply"."""
    replies = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]
    recent = replies[-NOTE_LOOKBACK:]
    lines: List[str] = []
    for index, reply in enumerate(reversed(recent)):
        emoji = normalize((_metadata(reply).get("reactions") or {}).get("user"))
        if not emoji:
            continue
        if index == 0:
            where = "your last reply"
        else:
            opening = _opening(reply.get("content"))
            where = f'your reply that began "{opening}"' if opening else "an earlier reply"
        lines.append(f"{emoji} ({MEANING.get(emoji, 'reacted')}) on {where}")
        if len(lines) >= NOTE_LIMIT:
            break
    if not lines:
        return None
    return "The person reacted: " + "; ".join(lines) + "."


def with_reactions(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`messages` with the reaction instruction after the leading system
    messages and, when the person reacted lately, the note right before their
    latest message. Returns a new list; the transcript is not touched."""
    from src.prompt_security import turn_note_message

    out = list(messages or [])
    at = 0
    while at < len(out) and isinstance(out[at], dict) and out[at].get("role") == "system":
        at += 1
    out.insert(at, {"role": "system", "content": INSTRUCTION})
    note = reaction_note(out)
    if note:
        last_user = next((i for i in range(len(out) - 1, -1, -1)
                          if isinstance(out[i], dict) and out[i].get("role") == "user"), None)
        if last_user is not None:
            out.insert(last_user, turn_note_message(note))
    return out


# ── where a reaction is kept ─────────────────────────────────────────────────

def set_on(metadata: Optional[dict], role: str, emoji: Optional[str]) -> dict:
    """`metadata` with `role`'s reaction set (or taken off for None)."""
    meta = dict(metadata or {})
    reactions = dict(meta.get("reactions") or {})
    if emoji:
        reactions[role] = emoji
    else:
        reactions.pop(role, None)
    if reactions:
        meta["reactions"] = reactions
    else:
        meta.pop("reactions", None)
    return meta


def persist(session_id: str, message_id: Any, role: str, emoji: Optional[str]) -> bool:
    """Write one reaction onto a stored message's row, merging into the
    metadata the row already has. False when there is no such row."""
    if not message_id:
        return False
    from core.database import SessionLocal, ChatMessage as DbChatMessage

    db = SessionLocal()
    try:
        row = db.query(DbChatMessage).filter(
            DbChatMessage.id == str(message_id),
            DbChatMessage.session_id == str(session_id or ""),
        ).first()
        if row is None:
            return False
        try:
            meta = json.loads(row.meta_data) if row.meta_data else {}
        except (json.JSONDecodeError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        row.meta_data = json.dumps(set_on(meta, role, emoji))
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Failed to save a reaction")
        return False
    finally:
        db.close()


def react_in_history(history: list, message_id: Any, role: str, emoji: Optional[str]) -> Optional[Any]:
    """Set the reaction on the in-memory message whose ``_db_id`` is
    `message_id`. Returns that message, or None."""
    for item in reversed(history or []):
        meta = _metadata(item)
        if meta.get("_db_id") == message_id:
            new_meta = set_on(meta, role, emoji)
            meta.clear()
            meta.update(new_meta)
            if isinstance(item, dict) and "metadata" not in item:
                item["metadata"] = meta
            return item
    return None


def react_to_latest_person_message(sess, session_id: str, emoji: Optional[str]) -> Optional[str]:
    """The model's reaction, onto the person's latest message in `sess`, in
    memory and on its row. Returns that message's id, or None."""
    if not emoji:
        return None
    for item in reversed(getattr(sess, "history", None) or []):
        role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
        if role != "user":
            continue
        meta = _metadata(item)
        if meta.get("hidden"):
            continue
        new_meta = set_on(meta, "assistant", emoji)
        if isinstance(item, dict):
            item["metadata"] = new_meta
        else:
            item.metadata = new_meta
        message_id = new_meta.get("_db_id")
        if message_id:
            persist(session_id, message_id, "assistant", emoji)
        return message_id
    return None
