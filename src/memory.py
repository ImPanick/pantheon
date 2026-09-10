# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging
import os
import time
import uuid
import re
from typing import List, Dict, Tuple
from datetime import datetime

from src import memory_retrieval

logger = logging.getLogger(__name__)


class MemoryStoreUnreadable(RuntimeError):
    """memory.json exists on disk but could not be read or parsed.

    "The contents are unknown" is categorically different from "there are no
    memories". A read-modify-write caller that conflates the two appends to an
    empty view and then persists it, destroying the whole store — the writes
    are atomic, so the loss is durable. Raised by
    :meth:`MemoryManager.load_all_for_update` so those callers fail closed.
    """


def tokenize(text: str) -> List[str]:
    """Simple tokenizer that splits on whitespace and removes punctuation."""
    return [word.strip('.,!?";') for word in text.split()]

# Keyword categories for semantic matching. Lifted out of
# `get_relevant_memories` (`H11`) so the diagnostic view can show a person how
# their question was read, and so the lists themselves can be inspected — they
# are the whole of the query classifier, and `B40` is what happens when nobody
# can see them. Order is the precedence order and is deliberate: identity first,
# so a question about who someone is beats one that merely mentions a phone
# number.
QUERY_KEYWORD_GROUPS = (
    ("identity", ["name", "who", "i", "am", "called", "identity", "myself", "me", "my"]),
    ("contact", ["phone", "email", "address", "contact", "number", "where", "located", "reach"]),
    ("preference", ["like", "prefer", "favorite", "want", "love", "hate", "dislike", "enjoy", "interested"]),
    ("task", ["todo", "task", "remind", "meeting", "appointment", "schedule", "deadline"]),
    ("fact", ["what", "when", "where", "how", "why", "explain", "describe", "information", "know"]),
)


def classify_query(query: str):
    """The older, broader query classifier: one of the group names, or None.

    **`P13-14`: this no longer describes the retriever.** It was written for the
    Jaccard scorer that used to live in this file, and when that scorer was
    replaced the ranking's intent test went with it —
    `src/memory_retrieval.query_intent` is the one the boost consults now, and
    `POST /api/memory/debug` reports that one. Kept rather than deleted (`Law
    1`) because it answers a real question and callers may want it; renamed in
    its documentation rather than in its signature because a function that
    silently stops meaning what it says is exactly the defect `B61` was about.

    The two differ, and the difference is worth knowing: this one has a `fact`
    group matching "what", "when", "where" and "how", which is most questions,
    and `query_intent` deliberately has no such group — a boost that fires for
    everything is not a boost.

    Before `B40` the honest answer here for almost any question was "identity",
    including "what is the build timeout".
    """
    return _query_type((query or "").lower(), QUERY_KEYWORD_GROUPS)


def _is_identity_memory(text: str) -> bool:
    """Whether a memory looks like it says who someone is. `B40`.

    Lifted verbatim out of `get_relevant_memories` so it can be named, tested
    and — when someone gets to it — narrowed. It is much broader than it looks:
    `\\b[A-Z][a-z]+ [A-Z][a-z]+\\b` matches ANY two consecutive capitalised
    words, so "Bridge Street", "Docker Compose" and "Hacker News" all qualify.
    Widening this predicate is a retrieval-quality change rather than a bug
    fix, so it is left exactly as found and filed as `P13-11`.
    """
    lowered = (text or "").lower()
    return any([
        re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text or ""),
        any(word in lowered for word in
            ["name is", "i'm", "i am", "called", "my name", "named", "call me"]),
    ])


def _matches_keyword(text: str, word: str) -> bool:
    """Whether `word` appears in `text` as a WORD, not as a substring. `B40`."""
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def _query_type(query_lower: str, groups):
    """First group whose keyword appears in the query, or None. `B40`.

    Order matters and is the caller's: identity is checked first, so a query
    that is genuinely about who someone is wins over one that merely mentions a
    phone number. That ordering was always the intent; it just never got a
    chance to run, because substring matching made the first group match
    everything.
    """
    for name, words in groups:
        if any(_matches_keyword(query_lower, word) for word in words):
            return name
    return None


def get_text_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts."""
    if not text1 or not text2:
        return 0.0
    
    tokens1 = set(tokenize(text1.lower()))
    tokens2 = set(tokenize(text2.lower()))
    
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
        
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    
    return len(intersection) / len(union)

class MemoryManager:
    def __init__(self, data_dir: str):
        self.memory_file = os.path.join(data_dir, "memory.json")
        self.ensure_file_exists()
        
    def extract_memory_from_chat(self, chat_history: List[Dict], session_id: str = None) -> List[Dict]:
        """
        Extract memory entries from chat history as a fallback when LLM fails.
        
        Args:
            chat_history: List of chat messages with 'role' and 'content' keys
            session_id: Optional session ID to associate with extracted memories
            
        Returns:
            List of memory entries with text, timestamp, and optional session_id
        """
        memories = []
        
        for msg in chat_history:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "assistant":
                content = str(msg.get("content", ""))
                lines = content.split('\n')
                
                for line in lines:
                    line = line.strip()
                    # Look for bullet points or numbered lists that might contain memories
                    if re.match(r'^[-*•]|\d+\.', line):
                        # Extract the text after the bullet/number. Group both
                        # markers so the capture applies to either — the previous
                        # `^[-*•]|\d+\.\s*(.*)` put the group on the numbered branch
                        # only, so a bullet line matched with group(1)=None and
                        # crashed on .strip().
                        text_match = re.match(r'^(?:[-*•]|\d+\.)\s*(.*)', line)
                        if text_match:
                            text = text_match.group(1).strip()
                            if text:
                                memories.append({
                                    "text": text,
                                    "timestamp": int(datetime.now().timestamp()),
                                    "session_id": session_id
                                })
                    # If we see a heading that suggests memories
                    elif re.search(r'memory|fact|note|remember', line, re.I):
                        pass
                    # If we see a clear separator or end
                    elif re.match(r'^={3,}|-{3,}|_{3,}', line):
                        pass
                        
        return memories
        
    def process_inline_memory_command(self, message: str) -> Tuple[bool, str]:
        """
        Check if a message is an inline memory command (e.g. "remember: X").
        
        Args:
            message: The user message to check
            
        Returns:
            Tuple of (is_command, extracted_text) where is_command is True if 
            the message matches the memory command pattern
        """
        # Pattern for memory commands: "remember: X", "memorize: X", "save: X", etc.
        pattern = r'^(?:remember|memorize|save|note|store)[:\-]?\s+(.+)$'
        match = re.match(pattern, message.strip(), re.IGNORECASE)
        
        if match:
            return True, match.group(1).strip()
        else:
            return False, ""
    
    def ensure_file_exists(self):
        """Create memory file if it doesn't exist."""
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    
    def _read_entries(self) -> List[Dict]:
        """Parse the store, or raise :class:`MemoryStoreUnreadable`.

        Returns ``[]`` only when the file genuinely does not exist. Every other
        failure mode raises, so callers can tell "no memories" apart from
        "couldn't read the memories".
        """
        if not os.path.exists(self.memory_file):
            return []

        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError as e:
            # PermissionError is an OSError (a scanner holding the file, a
            # permissions problem, bad media).
            raise MemoryStoreUnreadable(
                f"cannot read {self.memory_file}: {e}"
            ) from e
        except json.JSONDecodeError as e:
            # This is the branch that actually destroyed stores: the file reads
            # back fine, so nothing stops the save that follows. A truncated
            # memory.json is reachable because core/database.py rewrites it with
            # a plain open(..,"w") + json.dump during migration.
            #
            # Preserved behaviour: a corrupt store still gets one shot at the
            # pre-JSON memory.txt migration. Only raise when that finds nothing,
            # so we never report "empty" for a store we simply failed to parse.
            legacy = self._migrate_from_legacy()
            if legacy:
                return legacy
            raise MemoryStoreUnreadable(
                f"{self.memory_file} is not valid JSON: {e}"
            ) from e

        if not isinstance(data, list):
            raise MemoryStoreUnreadable(
                f"{self.memory_file} is not a JSON array (got {type(data).__name__})"
            )
        return self._validate_entries(data)

    def load_all(self) -> List[Dict]:
        """Load all memory entries from JSON file (unfiltered).

        Lenient by design: this feeds display, search, and context-injection
        paths, so an unreadable store degrades to an empty list rather than
        breaking chat. Never build a value from this that you intend to save
        back — use :meth:`load_all_for_update` for that.
        """
        try:
            return self._read_entries()
        except MemoryStoreUnreadable as e:
            logger.error("Error loading memory.json: %s", e)
            return []

    def load_all_for_update(self) -> List[Dict]:
        """Load for a read-modify-write cycle.

        Propagates :class:`MemoryStoreUnreadable` instead of degrading to ``[]``
        so a caller can never append to an empty view and persist it over a
        store that was only temporarily unreadable (issue #5673).
        """
        return self._read_entries()

    def load(self, owner: str = None) -> List[Dict]:
        """Load memory entries, optionally filtered by owner."""
        entries = self.load_all()
        if owner is None:
            return entries
        return [e for e in entries if e.get("owner") == owner]

    def claim_ownerless(self, owner: str):
        """Assign all ownerless memory entries to the given owner."""
        try:
            entries = self.load_all_for_update()
        except MemoryStoreUnreadable as e:
            # Skip the sweep rather than rewrite the store from an unknown view.
            logger.error("Skipping ownerless claim, memory store unreadable: %s", e)
            return
        changed = False
        claimed = 0
        for entry in entries:
            if not entry.get("owner"):
                entry["owner"] = owner
                changed = True
                claimed += 1
        if changed:
            self.save(entries)
            logger.info("Claimed %d ownerless memories for %s", claimed, owner)
    
    def _validate_entries(self, entries: List[Dict]) -> List[Dict]:
        """Ensure all entries have required fields."""
        validated = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if "id" not in entry:
                entry["id"] = str(uuid.uuid4())
            if "timestamp" not in entry:
                entry["timestamp"] = int(time.time())
            if "source" not in entry:
                entry["source"] = "unknown"
            if "category" not in entry:
                entry["category"] = "fact"
            if "uses" not in entry:
                entry["uses"] = 0
            # `P13-15`. Every memory predates this counter, so the honest
            # default is zero-mentions-observed rather than one — the store
            # cannot know how often a fact was said before anyone was counting,
            # and inventing a 1 would make an old memory look freshly confirmed.
            if "mentions" not in entry:
                entry["mentions"] = 0
            if "mention_sessions" not in entry:
                entry["mention_sessions"] = 0
            validated.append(entry)
        return validated
    
    def _migrate_from_legacy(self) -> List[Dict]:
        """Migrate from old text format to JSON if needed."""
        legacy_path = os.path.join(os.path.dirname(self.memory_file), "memory.txt")
        if not os.path.exists(legacy_path):
            return []
            
        logger.info("Converting legacy memory.txt to new JSON format")
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip()]
            
            entries = []
            for line in lines:
                entries.append({
                    "id": str(uuid.uuid4()),
                    "text": line,
                    "timestamp": int(time.time()),
                    "source": "user",
                    "category": "fact"
                })
            
            self.save(entries)
            return entries
        except Exception as e:
            logger.error("Failed to convert legacy memory: %s", e)
            return []
    
    def save(self, entries: List[Dict]):
        """Save memory entries to JSON file."""
        # Validate entries before saving
        for entry in entries:
            if "id" not in entry:
                entry["id"] = str(uuid.uuid4())
            if "timestamp" not in entry:
                entry["timestamp"] = int(time.time())
            if "source" not in entry:
                entry["source"] = "user"
            if "category" not in entry:
                entry["category"] = "fact"
        
        # Use atomic write
        tmp_file = self.memory_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, self.memory_file)
    
    def add_entry(self, text: str, source: str = "user", category: str = "fact", owner: str = None) -> Dict:
        """Add a new memory entry."""
        if not text.strip():
            raise ValueError("Memory text cannot be empty")

        entry = {
            "id": str(uuid.uuid4()),
            "text": text.strip(),
            "timestamp": int(time.time()),
            "source": source,
            "category": category,
            "uses": 0,
            # `P13-15`. Beside `uses` and initialised for the same reason it is:
            # a caller reading the returned dict should not have to know that
            # `load` backfills these. Zero, not one — creating a memory is the
            # first time it was said, and `first_mentioned` records that; a
            # count of 1 here would double-count the moment of creation.
            "mentions": 0,
            "mention_sessions": 0,
            "first_mentioned": int(time.time()),
        }
        if owner:
            entry["owner"] = owner
        return entry

    def increment_uses(self, ids: List[str]) -> None:
        """Bump the uses counter for each memory id. Called after a memory has
        actually been injected into a chat's context (not just retrieved)."""
        if not ids:
            return
        id_set = set(ids)
        try:
            entries = self.load_all_for_update()
        except MemoryStoreUnreadable as e:
            # Best-effort counter; never worth rewriting the store blind.
            logger.error("Skipping uses bump, memory store unreadable: %s", e)
            return
        changed = False
        for e in entries:
            if e.get("id") in id_set:
                e["uses"] = int(e.get("uses", 0) or 0) + 1
                changed = True
        if changed:
            self.save(entries)
    
    # `P13-15`. How many distinct conversations a restatement is remembered
    # from. Extraction runs after every response, so a fact repeated three times
    # inside one conversation is one conversation's worth of evidence and not
    # three — the durability signal is *across* sessions. This bounds the list
    # that makes that distinction; beyond it the count is kept and the ids are
    # forgotten, because the oldest session id has already done its work.
    MENTION_SESSION_MEMORY = 32

    def record_mention(self, memory_id: str, session_id: str | None = None) -> dict | None:
        """The person said this again. `P13-15`.

        **This is not `increment_uses`, and keeping them apart is the row.**
        `uses` counts **recalls** — how often the system reached for a fact and
        put it in a prompt. This counts **mentions** — how often the person
        stated it, and in how many separate conversations. A memory the
        assistant keeps injecting and a memory the person keeps raising are
        different kinds of important, and one counter cannot mean both.

        Before this, the moment a restatement was detected was the moment it was
        discarded: all three dedupe paths in the extractor located the matching
        memory precisely and then `continue`d. The strongest available signal
        for what belongs in a Brain was computed and dropped on the floor.

        Returns the updated entry, or None if the id is unknown or the store
        could not be read — a counter is never worth rewriting the store blind.
        """
        if not memory_id:
            return None
        try:
            entries = self.load_all_for_update()
        except MemoryStoreUnreadable as e:
            logger.error("Skipping mention bump, memory store unreadable: %s", e)
            return None
        for entry in entries:
            if entry.get("id") != memory_id:
                continue
            entry["mentions"] = int(entry.get("mentions", 0) or 0) + 1
            entry["last_mentioned"] = int(time.time())
            # `first_mentioned` is the moment the fact entered the store, which
            # is the first time it was said. Backfilled from `timestamp` rather
            # than left empty, because "we started counting late" is a worse
            # answer than the one the record already knows.
            entry.setdefault("first_mentioned", int(entry.get("timestamp", 0) or 0))
            if session_id:
                seen = [s for s in (entry.get("mention_session_ids") or []) if s]
                if session_id not in seen:
                    entry["mention_sessions"] = int(entry.get("mention_sessions", 0) or 0) + 1
                    seen.append(session_id)
                    entry["mention_session_ids"] = seen[-self.MENTION_SESSION_MEMORY:]
            self.save(entries)
            return entry
        return None

    def find_duplicates(self, text: str, entries: List[Dict] = None) -> List[Dict]:
        """Find duplicate memory entries based on text content."""
        if entries is None:
            entries = self.load()
            
        text_lower = text.strip().lower()
        return [entry for entry in entries if entry["text"].lower() == text_lower]
            
    def categorize_memory_by_relevance(self, message: str, memories: list):
        """Categorize memories by type and relevance"""
        categories = {
            "contacts": [],
            "preferences": [],
            "facts": [],
            "tasks": []
        }
        
        msg_lower = message.lower()
        
        for mem in memories:
            text_lower = mem["text"].lower()
            
            # Contact info
            if any(word in text_lower for word in ["phone", "email", "address", "lives", "works"]):
                if any(word in msg_lower for word in ["contact", "phone", "address", "email"]):
                    categories["contacts"].append(mem)
            
            # Personal preferences
            elif any(word in text_lower for word in ["likes", "dislikes", "prefers", "favorite"]):
                if any(word in msg_lower for word in ["like", "prefer", "favorite", "want"]):
                    categories["preferences"].append(mem)
            
            # Tasks and todos
            elif any(word in text_lower for word in ["todo", "task", "remind", "meeting"]):
                if any(word in msg_lower for word in ["todo", "task", "schedule", "remind"]):
                    categories["tasks"].append(mem)
            
            # General facts - only if very relevant
            else:
                if get_text_similarity(message, mem["text"]) > 0.4:
                    categories["facts"].append(mem)
        
        return categories

    def get_relevant_memories(self, query: str, memories: list, threshold: float = 0.05,
                              max_items: int = 8, vector=None):
        """Memories relevant to the query, best first.

        `P13-14`. **The scoring is `src/memory_retrieval.py` now.** What used to
        live here — Jaccard token overlap plus four hand-written keyword lists —
        was the worse of the two scorers this tree carried, and it served the
        surfaces that mattered most: this method feeds the Brain panel's search
        and debug endpoints, the agent's own MCP `memory_search`, the memory
        provider's fallback, and `ai_interaction`. The better one fed the chat
        preface and nothing else, **so the agent got the worse one.**

        Measured before it was replaced, on `.pantheon/fixtures/retrieval_probe.json`
        with no vector service: Jaccard `recall@5 0.40, MRR 0.319`; BM25 with
        corpus IDF `0.63, 0.633`. `Law 9` — a number, not an adjective.

        `threshold` is accepted and ignored, and that is deliberate rather than
        sloppy: five call sites pass `threshold=0.05`, and the scorer behind
        this now has three gates that a single similarity floor cannot express.
        Dropping the parameter breaks all five for no gain; honouring it would
        mean re-introducing a knob that no longer describes anything. This is a
        compatibility surface and it says so rather than pretending.

        `vector` is new and optional. A caller holding a live index passes it
        and gets semantic ranking; one that does not gets BM25, and `B61` makes
        the difference visible rather than silent.
        """
        return [row["memory"] for row in
                self.explain_relevant_memories(query, memories, threshold, max_items,
                                               vector=vector)]

    def explain_relevant_memories(self, query: str, memories: list, threshold: float = 0.05,
                                  max_items: int = 8, vector=None):
        """The same selection, with the score and the reason kept. `H11`.

        Returns `[{"memory": dict, "score": float, "reason": str}]`, best first.

        `POST /api/memory/debug` is documented as *"Debug which memories would
        be triggered for a query"* and could only ever answer the WHICH, because
        the score and the boost that produced it were computed and discarded on
        the last line. Building this is what found `B40`.

        `P13-14` keeps that contract and changes what is under it. One scoring
        pass serves both this and `get_relevant_memories`, because a diagnostic
        that re-scores is a diagnostic that can disagree with the thing it is
        explaining. The reasons are still written from what the code does rather
        than from what it is supposed to do — that discipline is why this
        function found a bug the first time it was built.
        """
        return memory_retrieval.explain(query, memories, max_items, vector=vector)
