# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging
import math
import os
import time
import uuid
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from src import memory_edges, memory_retrieval, memory_style
# `P13-02`'s edge vocabulary is imported for ONE name — `status_of`, which
# `P13-05` put beside `live()` because `live()` is the predicate it feeds — and
# nothing from it is re-exported.
# It lives in `src/memory_edges.py` — which imports nothing from the project —
# because retrieval is where the relations have to be honoured and this file
# already imports retrieval. Re-exporting the names through here would give
# them two import paths for no caller, which is how a second vocabulary starts
# (`Law 13`, `Law 14`). `edges` appears below only as a field this file
# defaults, the same way `mentions` is.

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


# ── Confidence ────────────────────────────────────────────────────────────────

def normalise_confidence(value, default=None):
    """A memory's 0..1 confidence, or `default` when there is no usable number.

    `P13-01`. This is the extractor's **self-report at the moment of
    extraction**, and it does not move on its own afterwards. What moves on its
    own is corroboration — `mentions` and `mention_sessions` (`P13-15`) — and
    keeping the two apart is the entire point of having both. PandAtlas ships
    the merged version and it reads `CONFIDENCE 66%` beside `1 mentions`:
    two-thirds certainty from a single unconfirmed statement, which *looks*
    like evidence and is not.

    `None` means **not recorded**, and it is the honest answer for every memory
    written before this row existed. That is the same call `P13-15` made for
    `mentions` ("legacy memories read zero, not one") for the same reason: a
    number invented for a record that never had one makes an old memory look
    freshly assessed.

    Clamped rather than rejected, because a model asked for 0..1 will
    occasionally answer 1.5 and the useful reading of that is "very sure", not
    "unparseable".
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN — float("nan") parses and then poisons any compare
        return default
    return round(min(max(number, 0.0), 1.0), 3)


# ── Provenance ────────────────────────────────────────────────────────────────

# The user's own words are copied onto the record, so they are bounded. Long
# enough to be recognisable, short enough that the store does not become a
# second transcript.
PROVENANCE_QUOTE_LIMIT = 240


def new_provenance(producer: str, message_index: int = None, quote: str = None) -> Dict:
    """Where a memory came from. `P13-03`.

    Three fields, and what is **not** here matters as much as what is:

    * `producer` — the code path that wrote this record. Not `source`, which
      already exists and says *user* / *auto* / *ai_agent*: that is who, this
      is which. `source="ai_agent"` cannot tell the MCP `memory_add` tool from
      `ai_interaction` from a builtin action, and "which tool produced this" is
      the row's own wording.
    * `message_index` — which message in the session, `None` when the producer
      genuinely cannot know. The background extractor is handed a flattened
      six-message transcript and gets back sentences, so it can only know this
      via `quote`; pretending otherwise would be a number that looks like a
      record and is a guess.
    * `quote` — the words this was drawn from, **verified against the
      transcript by the caller**, never trusted. A model asked to cite its
      source will invent one, and an invented citation is worse than none: it
      is the one field a person would use to decide whether to believe the
      memory.

    **`session_id` is deliberately absent.** It is already on the record, and
    `/api/memory/by-session` and the timeline read it there. A second copy
    inside `provenance` is two places to change one fact, and the one that does
    not get changed is the one somebody reads (`Law 7`).
    """
    row = {"producer": str(producer), "message_index": None, "quote": None}
    if isinstance(message_index, int) and not isinstance(message_index, bool) \
            and message_index >= 0:
        row["message_index"] = message_index
    if quote:
        row["quote"] = str(quote).strip()[:PROVENANCE_QUOTE_LIMIT]
    return row


# ── Decay and archive, `P13-04` ───────────────────────────────────────────────

# Six months in which nothing retrieved it, nobody restated it and nobody
# edited it. One window, deliberately: the shape of this curve is not something
# anybody here can calibrate — there is no golden set for *"should this memory
# still be believed"* the way `P13-13` built one for retrieval — so the honest
# design is the one a person can read off a page and argue with, not the one
# with the best-looking maths. `Law 15` is this phase's acceptance criterion and
# "fades in 12 days" is legible where a half-life is not.
ARCHIVE_AFTER_DAYS = 180

# The three verdicts, an enum rather than a boolean (`Law 10`). `held: true`
# and `fades: false` are the same sentence read two ways, and this one gets
# read by a panel, by the audit and by a person.
#
# **`due` is a verdict of its own because the alternative was a dead branch.**
# It started as `fades` with `days == 0`, and a mutation proved the verdict half
# of the due test could never change an answer — held rows report `days: None`,
# so `days == 0` alone already decided it. That is `P13-14`'s `cutoff`,
# `P13-15`'s `sessions <= 1`, `P13-09`'s parse-site id check and `P13-05`'s
# redundant owner check, for the fifth time in this phase: a branch that cannot
# distinguish itself from its own absence is not a control. Splitting the state
# out makes one field load-bearing instead of two half-fields, and it is the
# better surface anyway — *"due to fade"* and *"fades in 12 days"* are different
# things to tell somebody.
ARCHIVE_FADES = "fades"
ARCHIVE_HELD = "held"
ARCHIVE_DUE = "due"


def last_evidence(memory: Dict) -> int:
    """The most recent moment anything happened to this memory. `P13-04`.

    Four dates, and the newest wins. Each is a different kind of evidence that
    the fact is still live, and the store already records all four:

    * `last_used` — the system reached for it (`increment_uses`);
    * `last_mentioned` — the person stated it again (`P13-15`);
    * `committed_at` — somebody performed the explicit act (`P13-05`);
    * `timestamp` — it was written or edited (`PUT /{id}` moves this).

    **A record from before any of the first three existed falls back to
    `timestamp`**, which is `P13-15`'s `first_mentioned` call reapplied: *we
    started recording late* is a worse answer than the one the record already
    knows. What that fallback must not do is archive a memory the assistant has
    been leaning on for a year, and `archive_forecast` is where that is handled
    rather than here — this function answers one question and does not also
    make the decision.
    """
    if not isinstance(memory, dict):
        return 0
    dates = [memory.get("last_used"), memory.get("last_mentioned"),
             memory.get("committed_at"), memory.get("timestamp")]
    best = 0
    for value in dates:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > best:
            best = number
    return best


def archive_forecast(memory: Dict, now: float = None, superseded: bool = False) -> Dict:
    """Whether this memory fades, and how long it has. `P13-04`.

    Returns `{"verdict": ARCHIVE_HELD | ARCHIVE_FADES | ARCHIVE_DUE,
    "reason": str, "days": int | None}` — `days` is whole days until archive on
    a fading memory, `0` on a due one, and `None` on a held one.

    **Four things are held, and the last is the migration guard.**

    * **Pinned.** A person pinned it, and an inferred rule does not overrule a
      typed one — `setting_is_explicit` (`H06`, `H08`, `D-2026-09-08-02`,
      `D-2026-09-09-01`, `P13-05`) on its sixth application here.
    * **Not committed.** A proposal is already invisible to every prompt, and
      archiving one would hide it from the review queue `B710` still owes a
      surface. An already-archived memory is held for the same reason: this is
      idempotent, not a ratchet that keeps re-firing an event.
    * **Superseded.** `P13-09` already stopped it surfacing and wrote
      `superseded_by` saying which entry replaced it. A record carrying two
      unrelated reasons for the same silence is one nobody can read.
    * **Used, but before anybody recorded when.** `uses > 0` with no
      `last_used` is every memory in every store that existed before this row.
      The record knows the assistant reached for it and does not know the date;
      falling back to `timestamp` there would archive the most-used memories on
      an old install the first time somebody pressed Audit. It is held until it
      is next injected, which stamps `last_used` and starts the clock honestly.

    **No durability multiplier, and that is a decision rather than an
    omission.** Extending the window by `mention_sessions` was the obvious next
    move — `P13-15` already has that curve and `memory_retrieval` already
    spends 5% of the score on it. It is not here because the dates above
    already carry *"still alive"*: a fact the person keeps raising has a recent
    `last_mentioned` and never reaches the window at all, and a fact nobody has
    said or used in six months is exactly what this row exists for however
    often it was said before. A second tuning surface on one signal is two
    knobs for one idea (`Law 14`), and this one is recoverable in a click.
    """
    if not isinstance(memory, dict):
        return {"verdict": ARCHIVE_HELD, "reason": "not a memory", "days": None}
    if memory.get("pinned"):
        return {"verdict": ARCHIVE_HELD, "reason": "pinned by you", "days": None}
    if memory_edges.status_of(memory) != memory_edges.STATUS_COMMITTED:
        return {"verdict": ARCHIVE_HELD,
                "reason": f"not committed — {memory_edges.status_of(memory)}",
                "days": None}
    if superseded:
        return {"verdict": ARCHIVE_HELD,
                "reason": "superseded by another memory", "days": None}
    if int(memory.get("uses", 0) or 0) > 0 and not memory.get("last_used"):
        return {"verdict": ARCHIVE_HELD,
                "reason": "used before this was recorded, so the date is unknown",
                "days": None}

    seen = last_evidence(memory)
    if not seen:
        # No date at all anywhere on the record. "Undated" is not "old", and
        # guessing which would be the one mistake this row cannot make.
        return {"verdict": ARCHIVE_HELD, "reason": "no date on the record", "days": None}
    days_quiet = ((now if now is not None else time.time()) - seen) / 86400
    left = ARCHIVE_AFTER_DAYS - days_quiet
    quiet_for = f"nothing has used or restated it for {int(max(days_quiet, 0))} days"
    if left <= 0:
        return {"verdict": ARCHIVE_DUE, "reason": quiet_for, "days": 0}
    # Rounded UP, and the direction is the whole point: `int()` on a window with
    # half a day left reads `0`, and a reader who sees `0` beside `fades` will
    # act on it. A memory must not be hurried toward archive by a rounding rule
    # that was written to make a sentence read nicely.
    return {"verdict": ARCHIVE_FADES, "reason": quiet_for,
            "days": int(math.ceil(left))}


def due_for_archive(memories: List[Dict], now: float = None) -> List[str]:
    """The ids that have run out of window. `P13-04`.

    Pure: it reads and decides, it does not write. The caller that writes is
    `MemoryManager.archive`, and the caller that decides *when to ask* is the
    audit — because the audit is the pass whose job is already "keep the store
    from becoming noise", and a second maintenance sweep beside it would be
    `Law 14` in the shape of a cron job.

    Superseded ids come from the edge index rather than from a second walk of
    the store: `memory_edges` owns the answer to *"has this been replaced"* and
    two definitions of stale is how a memory disappears from search and keeps
    being sent to a model anyway.
    """
    rows = [m for m in memories if isinstance(m, dict)]
    stale = memory_edges.superseded_ids(rows)
    return [m["id"] for m in rows
            if m.get("id")
            and archive_forecast(
                m, now, superseded=m.get("id") in stale)["verdict"] == ARCHIVE_DUE]


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
            # `P13-17`. Normalised rather than defaulted-if-absent, for the same
            # reason `status` is one line below its own comment: every record
            # written before this row IS a memory — that is not a judgement
            # nobody made, it is what the record already is — and a hand-edited
            # typo must read as a memory rather than as a record of no known
            # kind that nothing knows how to show.
            entry["kind"] = memory_style.kind_of(entry)
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
            # `P13-01` / `P13-02` / `P13-03`. All three default to "not
            # recorded" rather than to a value. A memory written before any of
            # these rows has no extractor self-report, no relations and no idea
            # which message it came from, and the store is the wrong place to
            # invent one — the same call `mentions` made two rows earlier.
            # `edges` is the exception and defaults to `[]`, because "this
            # memory has no relations" is a thing the store genuinely knows.
            if "confidence" not in entry:
                entry["confidence"] = None
            else:
                entry["confidence"] = normalise_confidence(entry["confidence"])
            if "provenance" not in entry:
                entry["provenance"] = None
            # `P13-05`. The one field here whose honest default is a VALUE and
            # not "not recorded", and the difference is worth stating because
            # the three above it went the other way. `confidence`, `provenance`
            # and `mentions` describe judgements nobody made about an old
            # record, so inventing one would make it look freshly assessed.
            # Commitment is not a judgement about the record, it is what the
            # record already IS: every memory in a store today is being
            # injected into prompts, so `committed` is the true reading and
            # `proposed` would be an upgrade that silently stopped the Brain
            # working. Normalised through `status_of`, so a hand-edited typo
            # reads as committed rather than vanishing from every prompt.
            entry["status"] = memory_edges.status_of(entry)
            if not isinstance(entry.get("edges"), list):
                entry["edges"] = []
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
    
    def add_entry(self, text: str, source: str = "user", category: str = "fact",
                  owner: str = None, confidence=None, provenance: Dict = None,
                  status: str = None, kind: str = None) -> Dict:
        """Add a new memory entry.

        `confidence` (`P13-01`) is how sure the producer was, 0..1, or `None`
        for a producer that does not report one — a person typing into the
        Brain is not a 1.0, they are a source that was never asked.

        `provenance` (`P13-03`) is which message and which producer this came
        from. It deliberately does **not** carry `session_id`: that field
        already exists on the record, `/api/memory/by-session` and the timeline
        read it there, and copying it inside would be two places to change one
        fact (`Law 7`).

        `status` (`P13-05`) defaults to committed, and the default belongs to
        the caller that omits it rather than to the store: a person typing into
        the Brain has already performed the explicit act this row is about, and
        asking them to perform it twice is a modal dialog rather than a quality
        gate. The producer that passes `proposed` is background extraction,
        because that is the one that was never asked.
        """
        if not text.strip():
            raise ValueError("Memory text cannot be empty")

        entry = {
            "id": str(uuid.uuid4()),
            "text": text.strip(),
            "timestamp": int(time.time()),
            "source": source,
            "category": category,
            # `P13-17`. What this record IS, as opposed to what it says. A
            # memory is a fact about the world the person told us; a style note
            # is a disposition we observed, and filing the second as the first
            # is how a Brain starts lying about its sources. Defaults to
            # `memory` through `kind_of`, so every caller that does not know
            # about this row keeps writing memories.
            "kind": memory_style.kind_of({"kind": kind}),
            "uses": 0,
            # `P13-15`. Beside `uses` and initialised for the same reason it is:
            # a caller reading the returned dict should not have to know that
            # `load` backfills these. Zero, not one — creating a memory is the
            # first time it was said, and `first_mentioned` records that; a
            # count of 1 here would double-count the moment of creation.
            "mentions": 0,
            "mention_sessions": 0,
            "first_mentioned": int(time.time()),
            # `P13-04`. `None` and not the creation time: a memory nobody has
            # retrieved yet has not been retrieved, and stamping it with "now"
            # would make every new memory look like it had already earned its
            # place. `last_evidence` falls back to `timestamp` for exactly this
            # case, so a fresh memory still gets its full window.
            "last_used": None,
            # `P13-01` / `P13-02` / `P13-03`, initialised here for the same
            # reason `mentions` is: a caller reading the returned dict should
            # not have to know that `load` backfills them.
            "confidence": normalise_confidence(confidence),
            "provenance": provenance if isinstance(provenance, dict) else None,
            "status": memory_edges.status_of({"status": status}),
            # `P13-05`. `None` until somebody commits it, and `None` forever for
            # a memory that was born committed — the act is what these record,
            # and there was no act to date or attribute. Initialised here rather
            # than left absent for the same reason `mentions` is: a caller
            # reading the returned dict should not have to know what `load`
            # backfills.
            "committed_at": None,
            "committed_by": None,
            "edges": [],
        }
        if owner:
            entry["owner"] = owner
        return entry

    def increment_uses(self, ids: List[str]) -> None:
        """Bump the uses counter for each memory id. Called after a memory has
        actually been injected into a chat's context (not just retrieved).

        **`last_used` is recorded here, and its absence was `P13-04`'s real
        defect.** The row's premise — *reinforcement already ships* — is true
        and was half of one: this method knew a memory had just been reached
        for and recorded only *how many times*, never *when*, so the store
        could not answer the one question the row asks (*"has anything
        retrieved this lately"*) about any record in it. Same shape as
        `P13-15`, where the moment a fact was confirmed was the moment the
        observation was discarded, and same shape as `P13-10` a layer up.

        It is not a new concept either (`Law 14`): `services/memory/skills.py`
        `record_use` has kept `{"uses": …, "last_used": …}` in its usage
        sidecar since long before the Brain had a decay notion. This is that
        pair, on the other half of the feature, exactly the way `P13-01` and
        `P13-05` lifted the confidence floor and the draft state across.
        """
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
        now = int(time.time())
        for e in entries:
            if e.get("id") in id_set:
                e["uses"] = int(e.get("uses", 0) or 0) + 1
                e["last_used"] = now
                changed = True
        if changed:
            self.save(entries)

    def archive(self, ids: List[str], reason: str = None) -> List[Dict]:
        """Move memories to `archived`. `P13-04`. Returns the entries changed.

        The only writer of that status, for the reason `memory_edges.attach` is
        the only writer of edges: the decision is made in one place
        (`due_for_archive`), written in one place, and recorded in one place.

        **Nothing is dropped and nothing is rewritten.** The text, the
        confidence, the provenance, the mentions and the edges all stay exactly
        as they were — the record simply stops being one of the things `live()`
        returns. `archived_at` and `archived_reason` are added because a person
        looking at a memory that went quiet deserves to be told when and why,
        and because *"the store decided"* is not an answer anybody can act on.

        Refuses to touch a memory that is not currently committed, so a second
        call cannot re-stamp the date on something already archived and a
        proposal cannot be archived out from under the review queue.
        """
        if not ids:
            return []
        id_set = set(ids)
        try:
            entries = self.load_all_for_update()
        except MemoryStoreUnreadable as e:
            logger.error("Skipping archive, memory store unreadable: %s", e)
            return []
        changed = []
        now = int(time.time())
        for entry in entries:
            if entry.get("id") not in id_set:
                continue
            if memory_edges.status_of(entry) != memory_edges.STATUS_COMMITTED:
                continue
            entry["status"] = memory_edges.STATUS_ARCHIVED
            entry["archived_at"] = now
            entry["archived_reason"] = str(reason) if reason else None
            changed.append(entry)
        if changed:
            self.save(entries)
        return changed
    
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

    # ── the style profile, `P13-17` / `P13-20` ───────────────────────────────

    def style_profile(self, owner: str = None) -> Optional[Dict]:
        """This person's style record, or `None` if there is not one yet.

        One record per owner, found by kind rather than by a stored id: the id
        would be a second place the answer to *"which record is the profile"*
        lives, and `P13-03` already declined to copy `session_id` into
        `provenance` for that reason (`Law 7`).

        **Ownerless records are visible to everybody and that is deliberate**,
        because it is what the rest of this store already does — `load(owner)`
        is an equality filter and `claim_ownerless` exists precisely because
        single-user installs write no owner at all. A profile that vanished the
        day auth was switched on would be the same defect from the other side.
        """
        for entry in self.load_all():
            if memory_style.kind_of(entry) != memory_style.KIND_STYLE:
                continue
            if owner is None or entry.get("owner") in (owner, None):
                return entry
        return None

    def record_style_observation(self, text: str, owner: str = None,
                                 reading: Optional[Dict] = None) -> Optional[Dict]:
        """Fold one user message into the style profile. `P13-17`, `P13-20`.

        Returns the profile record, or `None` when the message carried nothing
        and no record existed to update.

        **What is stored is counters, and never the message.** The profile holds
        sums — words, sentences, how many messages opened in lower case — and at
        no point does the text that produced them reach the record. That is not
        only a size argument: `D-2026-09-09-01` calls this the most intimate data
        the product would ever hold, and a store of counters cannot be read back
        as a transcript however it leaks.

        **The sentences are re-rendered on every call and rewritten only when
        they change.** `traits()` buckets, so the text moves when the person's
        writing moves category and not when a number moves — which is what makes
        it editable at all (a sentence that rewrites itself under somebody is a
        sentence they cannot correct) and what keeps it out of the KV-cache
        problem `src/user_time.py:216` documents.

        **A profile the person has edited is not overwritten**, and that is the
        row's error signal doing its job: *"edits are the only error signal this
        feature can have"*. Once `style_edited` is set, the counters keep
        accumulating — the observation is still true — and the sentences stay as
        the person left them until they clear it. Overwriting their correction
        with our own next bucket change is precisely how a system teaches people
        that correcting it is pointless.
        """
        observation = memory_style.observe(text)
        if not observation.get("messages"):
            return None
        try:
            entries = self.load_all_for_update()
        except MemoryStoreUnreadable as e:
            logger.error("Skipping style observation, memory store unreadable: %s", e)
            return None

        record = None
        for entry in entries:
            if memory_style.kind_of(entry) != memory_style.KIND_STYLE:
                continue
            if owner is None or entry.get("owner") in (owner, None):
                record = entry
                break

        if record is None:
            # `add_entry` refuses empty text, and it is right to: a memory with
            # no text is a bug everywhere else in this store. The profile record
            # is built here instead, from the same field set, because its text
            # is *derived* and does not exist until the first fold produces a
            # bucket. Going through `add_entry` with a placeholder would have
            # put a sentence nobody wrote in front of the person.
            record = {
                "id": str(uuid.uuid4()),
                "text": "",
                "timestamp": int(time.time()),
                "source": "auto",
                "category": "style",
                "kind": memory_style.KIND_STYLE,
                "uses": 0,
                "mentions": 0,
                "mention_sessions": 0,
                "first_mentioned": int(time.time()),
                "last_used": None,
                "confidence": None,
                "provenance": new_provenance("memory_style.observe"),
                "status": memory_edges.STATUS_COMMITTED,
                "committed_at": None,
                "committed_by": None,
                "edges": [],
                "style": {},
            }
            if owner:
                record["owner"] = owner
            entries.append(record)

        totals = memory_style.fold(record.get("style"), observation)
        record["style"] = totals
        record["timestamp"] = int(time.time())

        # `P13-20`. The association is learned from what a joke co-occurs with,
        # so the classification needs the reading that was computed for this same
        # turn — which the caller already has, because it used it to pick a
        # register. Recomputing it here would be a second answer to one question.
        meaning = memory_style.classify_humour(observation, reading)
        if meaning or record.get("humour"):
            record["humour"] = memory_style.fold_humour(record.get("humour"), meaning)

        if not record.get("style_edited"):
            rendered = memory_style.profile_text(memory_style.traits(totals))
            if rendered != record.get("text"):
                record["text"] = rendered
        self.save(entries)
        return record

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
