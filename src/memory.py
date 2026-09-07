
import json
import logging
import os
import time
import uuid
import re
from typing import List, Dict, Tuple
from datetime import datetime

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
    """How the retriever reads this question: one of the group names, or None.

    Public because the diagnostic shows it (`H11`), and because it is the most
    surprising single fact a person learns there — before `B40` the honest
    answer for almost any question was "identity", including "what is the
    build timeout".
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

    def get_relevant_memories(self, query: str, memories: list, threshold: float = 0.05, max_items: int = 8):
        """Get memories that are relevant to the query based on text similarity and semantic keyword matching.

        Unchanged contract: a plain list of memory dicts, best first. Five
        callers unpack it that way. The scoring lives in
        `explain_relevant_memories`, which keeps the score and the reason that
        this one throws away (`H11`).
        """
        return [row["memory"] for row in
                self.explain_relevant_memories(query, memories, threshold, max_items)]

    def explain_relevant_memories(self, query: str, memories: list, threshold: float = 0.05, max_items: int = 8):
        """The same selection, with the score and the reason kept. `H11`.

        Returns `[{"memory": dict, "score": float, "reason": str}]`, best first.

        This function is the whole of `H11`. `POST /api/memory/debug` is
        documented as *"Debug which memories would be triggered for a query"*
        and could only ever answer the WHICH, because the score and the boost
        that produced it were computed and discarded on the last line. A person
        asking "why did it remember that" was being handed a list and told to
        infer the answer.

        The reasons are written from what the code does, not from what it is
        supposed to do — which is why building this found `B40`.
        """
        if not memories or not query.strip():
            return []
            

        query_lower = query.lower()

        # Determine query type based on keywords.
        #
        # `B40`. This was `any(word in query_lower for word in ...)` — a
        # SUBSTRING test — and `identity_words` contains `"i"`, `"am"`, `"me"`
        # and `"my"`. So "what **i**s the weather" is an identity question, and
        # so is "expla**i**n the code", "f**i**nd the invoice" and "what
        # ti**me**". Measured over ten ordinary queries: **ten of ten
        # classified as identity**, which meant the identity branch was
        # effectively the only branch and the contact, preference and task
        # boosts below had never run in production.
        #
        # Word boundaries, which is what "contains the keyword" was always
        # meant to say. The same ten now classify as fact, task, contact and
        # identity in the shapes you would expect, and "who am I" and "what is
        # my name" are still identity.
        query_type = classify_query(query)
        
        relevant = []
        other_memories = []

        # `B40`. This used to partition the memories in two and score only the
        # "other" half, so a memory the `_is_identity_memory` test caught was
        # **never scored at all** unless the query classified as identity — not
        # even by the exact-phrase rule below, which says in as many words that
        # a verbatim match is highly relevant. With a memory reading "Joseph
        # Jeffrey works at Afrog Labs", the query "Afrog Labs" returned
        # nothing, and so did "where does Joseph Jeffrey work".
        #
        # And `_is_identity_memory` catches far more than names: its regex is
        # any two consecutive capitalised words, so "the office is at 12 Bridge
        # Street" and "deploys with Docker Compose on Sunday" are both
        # "identity memories".
        #
        # The deliberate part is kept exactly as it was written: for an
        # identity QUERY, identity memories are admitted at 0.9 regardless of
        # similarity. That is what the original comment says it wants, and with
        # classification fixed it now happens only for questions that really
        # are about identity. What is removed is the accidental half — that
        # everything else about them was thrown away.
        for memory in memories:
            if query_type == "identity" and _is_identity_memory(memory.get("text", "")):
                # High score for identity memories in identity queries
                relevant.append((0.9, memory,
                                 "this reads as a question about identity, and this memory "
                                 "looks like it says who someone is — admitted without "
                                 "scoring, ahead of anything matched on words"))
                continue
            other_memories.append(memory)

        # Process the rest with similarity scoring
        for memory in other_memories:
            memory_text = memory["text"].lower()
            memory_tokens = set(tokenize(memory_text))
            query_tokens = set(tokenize(query_lower))
            
            # Calculate base Jaccard similarity
            if not query_tokens or not memory_tokens:
                continue
                
            shared = query_tokens & memory_tokens
            base_similarity = len(shared) / len(query_tokens | memory_tokens)
            final_score = base_similarity
            why = (("shares " + ", ".join(sorted(shared)[:4])) if shared
                   else "no words in common with the query")
            
            # Apply boosts based on semantic matching
            if query_type == "contact":
                # Boost memories with contact information
                has_contact_info = any(word in memory_text for word in ["@gmail.com", "@", ".com", 
                                                                     "phone", "number", "address", 
                                                                     "http", "www", "tel:"])
                if has_contact_info:
                    final_score *= 1.4  # 40% boost for contact-related memories
                    why += f", and got a 40% boost because this reads as a contact question and the memory carries contact details"
            
            elif query_type == "preference":
                # Boost memories with preference indicators
                has_preference = any(word in memory_text for word in ["like", "love", "hate", "dislike", 
                                                                   "prefer", "favorite", "enjoy", "interested"])
                if has_preference:
                    final_score *= 1.3  # 30% boost for preference-related memories
                    why += f", and got a 30% boost because this reads as a preference question and the memory carries a preference word"
            
            elif query_type == "task":
                # Boost memories with task indicators
                has_task = any(word in memory_text for word in ["todo", "task", "remind", "meeting", 
                                                              "appointment", "schedule", "deadline", "need to"])
                if has_task:
                    final_score *= 1.3  # 30% boost for task-related memories
                    why += f", and got a 30% boost because this reads as a task question and the memory carries a task word"
            
            # Always consider exact phrase matches as highly relevant
            if query.lower() in memory["text"].lower():
                final_score = max(final_score, 0.8)  # Ensure high relevance for exact matches
                why = "the query appears in this memory word for word"
            
            # Include memory if it meets threshold after boosts
            if final_score >= threshold:
                relevant.append((final_score, memory, why))
        
        # Sort by final score (descending) and return top matches
        relevant.sort(key=lambda x: x[0], reverse=True)
        return [{"memory": mem, "score": round(score, 4), "reason": why}
                for score, mem, why in relevant[:max_items]]
