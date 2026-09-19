# SPDX-License-Identifier: AGPL-3.0-or-later
"""provider_import.py — reading a conversation export the person hands over.

`P13-06`. ChatGPT, Claude and Gemini all let a person download their own
conversations. This module turns one of those files into the person's **own
turns**, in order, so the extraction pipe that already exists has something
worth reading.

**`Law 16`, and it is the whole shape of this module.** An import reads a file
the user gave us. Nothing here fetches, resolves, validates against a vendor,
checks a schema version or asks anybody whether a file is genuine — there is no
network client in this file and no code path that could acquire one. The
question the law asks is *"who owns the address at the other end"*, and the
answer here is that there is no other end: the bytes came off the person's own
disk through a form upload and never leave the process. `B723` closed a hole of
exactly this shape two waves ago, and the temptation on an importer is always
the same one — a "just check the export format version" call.

**Only the person's own messages are read, and that is a correctness decision
rather than a privacy one.** A memory is a fact about the person; the
assistant's half of a transcript is a fact about a model's output, and three
years of another assistant's confident wrong answers is the single worst corpus
this product could be handed. So `assistant` turns are dropped before anything
is extracted, and the count of what was dropped is reported rather than hidden.

**Sniffing is structural, never by filename.** All three exports are called
some variant of `conversations.json`, the person may have renamed it, and a
file that gets misread as the wrong provider silently yields nothing. Each
recogniser below keys on a field only that provider's shape has, and the
verdict is a provider name or `None` — never a guess (`Law 10`).

The formats, as of the exports these were written against:

* **ChatGPT** — a JSON array of conversations, each with a `mapping` dict of
  node-id → `{message: {author: {role}, content: {parts: [...]}}}`. The graph
  is a tree (edits create branches); this reads every user node rather than one
  path through it, because a message the person typed and then edited is still
  a message the person typed.
* **Claude** — a JSON array of conversations, each with `chat_messages`, whose
  entries carry `sender: "human" | "assistant"` and their text in either a flat
  `text` field or a `content` array of typed blocks. Both spellings ship, so
  both are read.
* **Gemini** — Google Takeout "My Activity", a JSON array of activity records
  whose `title` reads `"Prompted <what the person typed>"`. There is no
  assistant half in this file at all, which is why the shape looks nothing like
  the other two.

Liberal in what it accepts and loud about what it could not read: *"0 memories
imported"* with no reason is the failure mode an importer actually has, so
`read_export` reports `conversations`, `messages`, `dropped_assistant` and
`truncated` beside the text rather than only the text.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CHATGPT = "chatgpt"
CLAUDE = "claude"
GEMINI = "gemini"

# The order is the sniffing order and it is deliberate: each key below is
# unique to its provider's shape, so the order cannot change an answer today —
# it is fixed so that the day a fourth format overlaps with one of these, the
# tie is resolved by a line somebody wrote rather than by dict iteration.
PROVIDERS = (CHATGPT, CLAUDE, GEMINI)

# Google Takeout writes the prompt into the activity title behind this word.
# Matched case-insensitively with the whitespace collapsed, because the export
# has shipped with one space and with two.
_GEMINI_PROMPT_PREFIX = "prompted"

# How much of an export reaches the extractor. A full ChatGPT archive is years
# of conversation and an extraction prompt is one call: the cap is here rather
# than at the route so that what was dropped can be *counted* and reported,
# which is the difference between a truncation and a silent one. The existing
# generic import path truncates at 15,000 characters by slicing the raw text
# and appending "[Truncated]" into the middle of the prompt; this returns the
# fact as a field instead.
DEFAULT_CHAR_BUDGET = 15000

# A single message longer than this is a pasted document, not a sentence about
# the person. Kept, but clipped, so one 400KB paste cannot eat the whole budget
# and leave every other turn unread.
MAX_MESSAGE_CHARS = 2000


def _text_of(value) -> str:
    """The readable text in a message body, whichever shape it arrived in.

    Handles a bare string, a list of typed blocks (`{"type": "text", "text":
    …}`), and a list of bare strings. Anything else — an image part, a tool
    result, a citation blob — contributes nothing rather than its `repr`, which
    is what a permissive `str()` here would put into somebody's memories.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        out = []
        for part in value:
            if isinstance(part, str) and part.strip():
                out.append(part.strip())
            elif isinstance(part, dict):
                inner = part.get("text")
                if isinstance(inner, str) and inner.strip():
                    out.append(inner.strip())
        return "\n".join(out).strip()
    return ""


def _looks_like(rows, predicate) -> bool:
    """Whether any dict in the first few rows satisfies `predicate`.

    The first few and not all of them: an export's first entry can be an empty
    conversation, and reading a 200MB list twice to sniff it is a cost for no
    extra certainty.
    """
    seen = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        seen += 1
        if predicate(row):
            return True
        if seen >= 25:
            break
    return False


def sniff(parsed) -> Optional[str]:
    """Which provider wrote this, or `None`. `P13-06`.

    `None` is a real answer and the caller must treat it as one: an export this
    does not recognise falls through to the generic import path, which is what
    every `.json` upload got before this row existed. Guessing would be worse
    than not recognising it — a Claude export read as a ChatGPT one yields
    nothing at all, and *"0 facts found"* is indistinguishable from a file with
    nothing in it.
    """
    if not isinstance(parsed, list) or not parsed:
        return None
    if _looks_like(parsed, lambda r: isinstance(r.get("mapping"), dict)):
        return CHATGPT
    if _looks_like(parsed, lambda r: isinstance(r.get("chat_messages"), list)):
        return CLAUDE
    if _looks_like(parsed, _is_gemini_activity):
        return GEMINI
    return None


def _is_gemini_activity(row: Dict) -> bool:
    """A Takeout activity record from Gemini (or Bard, which it used to be).

    Both halves are required. `title` alone matches any Takeout export — Search,
    Maps, YouTube — and importing a person's search history as memories on the
    strength of one field is the kind of mistake that is only visible after it
    has happened.
    """
    if not isinstance(row.get("title"), str):
        return False
    haystack = " ".join([
        str(row.get("header") or ""),
        " ".join(str(p) for p in (row.get("products") or [])
                 if isinstance(p, (str, int))),
    ]).lower()
    return "gemini" in haystack or "bard" in haystack


def _chatgpt_turns(parsed) -> Dict:
    kept, dropped = [], 0
    for convo in parsed:
        if not isinstance(convo, dict):
            continue
        mapping = convo.get("mapping")
        if not isinstance(mapping, dict):
            continue
        rows = []
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            meta = message.get("metadata")
            if isinstance(meta, dict) and meta.get("is_visually_hidden_from_conversation"):
                # Context the product injected, not something the person typed.
                continue
            author = message.get("author")
            role = author.get("role") if isinstance(author, dict) else None
            if role != "user":
                dropped += 1 if role == "assistant" else 0
                continue
            content = message.get("content")
            text = _text_of(content.get("parts") if isinstance(content, dict) else content)
            if text:
                rows.append((message.get("create_time") or 0, text))
        # Ordered inside the conversation, because a `mapping` is a dict of
        # tree nodes and its iteration order is storage order, not the order
        # anybody said anything in.
        rows.sort(key=lambda row: row[0] or 0)
        if rows:
            kept.append({"title": str(convo.get("title") or "").strip(),
                         "messages": [text for _at, text in rows]})
    return {"conversations": kept, "dropped_assistant": dropped}


def _claude_turns(parsed) -> Dict:
    kept, dropped = [], 0
    for convo in parsed:
        if not isinstance(convo, dict):
            continue
        messages = convo.get("chat_messages")
        if not isinstance(messages, list):
            continue
        rows = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("sender") != "human":
                dropped += 1 if message.get("sender") == "assistant" else 0
                continue
            # `text` is the flat spelling and `content` the block spelling.
            # Both ship, in the same file in some exports, and taking whichever
            # is non-empty is how a message with an attachment beside its prose
            # keeps its prose.
            text = _text_of(message.get("text")) or _text_of(message.get("content"))
            if text:
                rows.append(text)
        if rows:
            kept.append({"title": str(convo.get("name") or "").strip(),
                         "messages": rows})
    return {"conversations": kept, "dropped_assistant": dropped}


def _gemini_turns(parsed) -> Dict:
    rows = []
    for record in parsed:
        if not isinstance(record, dict) or not _is_gemini_activity(record):
            continue
        title = str(record.get("title") or "").strip()
        head = " ".join(title.split())
        if head.lower().startswith(_GEMINI_PROMPT_PREFIX):
            text = head[len(_GEMINI_PROMPT_PREFIX):].strip()
        else:
            # An activity record that is not a prompt — an app open, a
            # setting change. Skipped rather than imported as a sentence the
            # person said.
            continue
        if text:
            rows.append(text)
    # One pseudo-conversation: Takeout has no conversation boundaries at all,
    # and inventing them from timestamps would be a guess presented as a
    # record. Saying so here is cheaper than a reader wondering why the count
    # is always 1.
    return {"conversations": ([{"title": "Gemini activity", "messages": rows}]
                              if rows else []),
            "dropped_assistant": 0}


_READERS = {CHATGPT: _chatgpt_turns, CLAUDE: _claude_turns, GEMINI: _gemini_turns}


def read_export(parsed, char_budget: int = DEFAULT_CHAR_BUDGET) -> Optional[Dict]:
    """One export → the person's own words, bounded. `P13-06`.

    Returns `None` when the file is not a recognised export, and otherwise::

        {"provider": str, "conversations": int, "messages": int,
         "dropped_assistant": int, "truncated": bool, "text": str}

    `text` is the transcript handed to extraction: one `## title` heading per
    conversation and one line per message, which is a format the existing
    import prompt already reads well because it is the shape a document has.

    **Every count is of what happened, not of what was in the file.**
    `messages` is what is in `text`; `truncated` says the budget stopped it.
    An importer that reports the size of the upload rather than the size of
    what it read is the one that tells somebody 4,000 messages were imported
    when 60 were.
    """
    provider = sniff(parsed)
    if provider is None:
        return None
    read = _READERS[provider](parsed)

    lines, used, messages, truncated = [], 0, 0, False
    for convo in read["conversations"]:
        if truncated:
            break
        header = f"## {convo['title']}" if convo["title"] else "##"
        pending = [header]
        for text in convo["messages"]:
            clipped = text[:MAX_MESSAGE_CHARS]
            if used + len(clipped) > char_budget:
                truncated = True
                break
            pending.append(clipped)
            used += len(clipped)
            messages += 1
        if len(pending) > 1:
            lines.extend(pending)

    logger.info("Provider import: %s export, %d conversations, %d of the "
                "person's messages read, %d assistant turns dropped%s",
                provider, len(read["conversations"]), messages,
                read["dropped_assistant"], ", truncated" if truncated else "")
    return {
        "provider": provider,
        "conversations": len(read["conversations"]),
        "messages": messages,
        "dropped_assistant": read["dropped_assistant"],
        "truncated": truncated,
        "text": "\n".join(lines),
    }
