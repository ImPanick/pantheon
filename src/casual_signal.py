# SPDX-License-Identifier: AGPL-3.0-or-later
"""
casual_signal.py

One regex pair and one predicate: is this message a short greeting or slang
with no request in it? `B823`, and `D-2026-09-09-01`'s *"one regex, one bit,
per turn"* made literal.

Until `B823` this pair and its predicate existed twice, byte for byte, in
`src/agent_loop.py` and `routes/chat_helpers.py`. The two copies gate
different things — the loop's decides whether a turn inherits stale context
for tool retrieval, the route's decides whether memory, skills, RAG and docs
are pulled — so the day somebody widened the blocklist in one of them (a new
tool noun, the likeliest edit there is) the product would have suppressed
skills for a message it still pulled memory for, and nothing would have
failed. `Law 14`: this module is the one copy, a leaf like
`src/memory_edges.py` and `src/memory_style.py`, and both callers import it.

`src/memory_style.py` keeps its own narrower `_GREETING` on purpose and says
why: this blocklist is about tool nouns, which is a different question with a
different right answer. Do not fold it in here.

Nothing here imports anything from the app, so either caller can import it
without a cycle.
"""

import re

_CASUAL_OPENING_RE = re.compile(
    r"^\s*(?:h+i+|hey+|hello+|yo+|sup+|what'?s up|wass?up|hiya|howdy|"
    r"lol|lmao|haha+|hehe+|thanks?|thank you|ty|idk|dunno|meh|bruh|bro)\b(?P<tail>.*)$",
    re.IGNORECASE,
)
_CASUAL_BLOCKLIST_RE = re.compile(
    r"\b(?:cookbook|serve|serving|launch|start|vllm|sglang|llama\.?cpp|ollama|"
    r"download|model|email|document|doc|note|calendar|task|search|web|research|"
    r"file|folder|repo|git|settings?|endpoint|api|token|mcp)\b",
    re.IGNORECASE,
)


def _is_casual_low_signal(text: str) -> bool:
    """True for short greetings/slang that carry no request: such a turn
    should neither inherit stale context for tool retrieval (the loop) nor
    pull memory, skills, RAG or docs (the chat route)."""
    s = str(text or "").strip()
    m = _CASUAL_OPENING_RE.match(s)
    if not m:
        return False
    tail = m.group("tail") or ""
    if _CASUAL_BLOCKLIST_RE.search(tail):
        return False
    # Allow a short vocative/address after the opener without hardcoding the
    # address term itself: "hey man", "yo dude", "sup <name>". Longer tails are
    # more likely to be an actual request and should get normal context/tooling.
    tail_words = re.findall(r"[A-Za-z0-9_'-]+", tail)
    return len(tail_words) <= 2
