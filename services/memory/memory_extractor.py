# SPDX-License-Identifier: AGPL-3.0-or-later
"""
memory_extractor.py

Background auto-extraction of facts from chat conversations.
After each LLM response, this module sends the last few messages to the LLM
asking it to extract memorable facts, then stores them in both memory.json
and the FAISS vector index.

Periodically audits all memories via LLM to consolidate duplicates,
rewrite vague entries, and remove junk.
"""

import hashlib
import json
import logging
import os
import re
import time
from typing import Optional

from src.memory import (
    MemoryManager,
    MemoryStoreUnreadable,
    new_provenance,
    normalise_confidence,
)
from src.memory_edges import (
    EDGE_CONTRADICTS,
    EDGE_SUPERSEDES,
    STATUS_COMMITTED,
    STATUS_PROPOSED,
    attach as attach_edge,
    is_committed,
    live as live_memories,
)
# `P13-01`. The floor is **imported, not copied.** `skill_extractor` has scored
# every extracted skill 0..1 and dropped anything under this number since long
# before the Brain had a confidence concept at all, and the row asks for "the
# same shape, the same tuning surface, one fewer concept to learn". A second
# constant here would be a second tuning surface that drifts from the first the
# day somebody moves one of them (`Law 14`), so moving the skill floor moves
# the memory floor, on purpose.
from services.memory.skill_extractor import MIN_CONFIDENCE

logger = logging.getLogger(__name__)

# What the extractor assumes when the model returns no `confidence` at all.
# `skill_extractor` uses the same number for the same reason: a model that did
# not answer the question has not expressed doubt, and defaulting below the
# floor would silently discard every fact from a model too small to follow the
# schema.
DEFAULT_CONFIDENCE = 0.7

# `_fallback_memory_candidates` is not a model. It is a handful of regexes over
# the user's own sentence — "my name is X" — so the floor, which exists to drop
# a *model's* uncertainty, has nothing to act on. Recorded high and explicitly
# rather than left unset, because "a pattern matched your own words" is a
# stronger provenance than anything the LLM path can offer, and a blank here
# would read as "not recorded" when the truth is "recorded, and by the most
# reliable producer in this module".
FALLBACK_CONFIDENCE = 0.9

# `P13-03`. The two producers in this module, named so a record can say which
# of them wrote it. `source` already says "auto" for both, which is exactly the
# distinction the row is about.
PRODUCER_LLM = "memory_extractor.llm"
PRODUCER_FALLBACK = "memory_extractor.pattern"
PRODUCER_AUDIT = "memory_extractor.audit"


def _tidy_state_path(memory_manager) -> str:
    """Sidecar JSON next to memory.json that remembers the fingerprint of
    the last successfully-audited state per owner. Lets the audit short-
    circuit when nothing has changed since the previous tidy — running
    the LLM again on an already-clean list was wasting 30-120s per call
    and occasionally timing out on the second pass."""
    return os.path.join(os.path.dirname(memory_manager.memory_file), "memory_tidy_state.json")


def _fingerprint_entries(entries) -> str:
    """Stable hash of an owner's memories — order-independent, depends
    only on id+text+category. Any add/edit/delete invalidates it."""
    items = sorted(
        (str(e.get("id", "")), e.get("text", ""), e.get("category", ""))
        for e in _memory_dicts(entries)
    )
    h = hashlib.sha256()
    for triple in items:
        h.update(("\x1f".join(triple) + "\x1e").encode("utf-8"))
    return h.hexdigest()


def _memory_dicts(entries):
    for entry in entries or []:
        if isinstance(entry, dict):
            yield entry


def _load_tidy_state(memory_manager) -> dict:
    path = _tidy_state_path(memory_manager)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_tidy_state(memory_manager, owner: Optional[str], fingerprint: str) -> None:
    path = _tidy_state_path(memory_manager)
    state = _load_tidy_state(memory_manager)
    state[owner or ""] = {"fingerprint": fingerprint}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        logger.warning(f"Could not persist tidy fingerprint: {e}")

EXTRACT_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Analyze the conversation and extract ONLY "
    "durable personal facts about the user that would be useful across many future conversations.\n\n"
    "Good examples: name, job title, city, family members, long-term projects, strong preferences.\n"
    "Bad examples: what they asked about today, temporary moods, generic statements, "
    "things the assistant said, one-off tasks, opinions on the current topic.\n\n"
    "Rules:\n"
    "- MAX 2 facts per conversation — only the most important\n"
    "- Only extract facts the USER stated or clearly implied\n"
    "- Each fact must be a single short sentence (under 15 words)\n"
    "- If a fact is similar to something likely already known, skip it\n"
    "- If nothing durable was revealed, return []\n\n"
    "Return a JSON array of objects with 'text', 'category', 'confidence' and "
    "'quote' fields.\n"
    "Categories: 'identity', 'preference', 'fact', 'contact', 'project', 'goal'\n"
    # `P13-01`. The same question the skill extractor has always asked, asked
    # of a fact instead of a procedure.
    "- 'confidence': 0.0-1.0, how sure you are the user actually stated or "
    "clearly implied this. Be honest; a low number is better than a wrong fact.\n"
    # `P13-03`. A citation, checked against the transcript before it is stored
    # — see `_verified_quote`. Asking for it costs nothing when the model
    # cannot supply one, and an unverifiable quote is discarded rather than
    # believed.
    "- 'quote': the user's own words this came from, copied EXACTLY from the "
    "transcript above. Do not paraphrase and do not invent one.\n\n"
    "Return ONLY valid JSON, no markdown fences."
)

# How many recent messages to include for extraction
CONTEXT_WINDOW = 6

AUDIT_SYSTEM_PROMPT = (
    "You are a memory database curator. Be CONSERVATIVE: remove only TRUE "
    "duplicates and clearly useless entries. Every distinct fact must survive. "
    "When in doubt, KEEP the entry. Return the cleaned list.\n\n"
    "Rules:\n"
    "1. MERGE only entries that state the SAME fact in different words. If you "
    "are not sure two entries are the same fact, KEEP BOTH.\n"
    "   Merge: 'User's name is Sam' + 'The user is called Sam' -> one.\n"
    "   Do NOT merge related-but-distinct facts: 'Likes Python' and 'Uses "
    "Python at work' are DIFFERENT — keep both.\n"
    "2. REMOVE only entries that are genuinely worthless: about what the AI did "
    "(not the user), empty, or meaningless. Do NOT drop a real fact just "
    "because it seems minor or niche.\n"
    "3. Keep the original wording. Only lightly trim obvious redundancy — do "
    "NOT aggressively rewrite or shorten.\n"
    "4. Preserve the 'id' of the entry you keep when merging.\n"
    "5. Never invent facts. When unsure, KEEP.\n"
    # `P13-09`. The pass could merge and remove but had no way to SAY what it
    # had done, so consolidation was a winner picked quietly. These two fields
    # are how it says so, and both are validated against the ids that were sent
    # before anything is written.
    "6. When you merge entries, list the ids you merged INTO the survivor in "
    "its 'merged_from' array. Do not drop an id silently.\n"
    "7. When two entries you KEPT state incompatible facts, list each other's "
    "id in their 'contradicts' array. Recording a conflict is not resolving "
    "it — keep both entries and do not choose between them.\n\n"
    "Return a JSON array of objects with fields: id, text, category, "
    "merged_from (array of ids, may be empty), contradicts (array of ids, may "
    "be empty).\n"
    "Return ONLY valid JSON, no markdown fences."
)

AUDIT_INTERVAL = 5  # audit every N new memories added
_extractions_since_audit = 0


def _message_text(message) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return " ".join(p for p in parts if p).strip()
    return ""


def _message_role(message) -> str:
    role = getattr(message, "role", None)
    if role is None and isinstance(message, dict):
        role = message.get("role")
    return str(role or "").lower()


def _clean_memory_value(value: str, max_len: int = 80) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" .,!?:;\"'`“”‘’")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
    if not value or len(value) > max_len:
        return ""
    if re.search(r"https?://|@|[{}<>]", value):
        return ""
    return value


def _fallback_memory_candidates(messages) -> list[dict]:
    """Extract obvious durable facts without relying on the LLM.

    This is deliberately narrow. The LLM remains the main extractor, but
    simple identity/preference/goal statements should not silently vanish just
    because the background model judged them too conversational.
    """
    candidates = []
    seen = set()
    # `P13-01` / `P13-03`. This path knows exactly which message it matched and
    # matched it on the user's own words, so it records both — and it is the
    # only producer in this module that can name a message index without asking
    # a model to cite itself.
    cursor = {"index": None, "text": ""}

    def add(text: str, category: str):
        text = _clean_memory_value(text, 120)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "text": text,
            "category": category,
            "confidence": FALLBACK_CONFIDENCE,
            "producer": PRODUCER_FALLBACK,
            "message_index": cursor["index"],
            "quote": cursor["text"],
        })

    for _index, msg in enumerate(messages):
        if _message_role(msg) != "user":
            continue
        text = _message_text(msg)
        if not text:
            continue
        cursor["index"], cursor["text"] = _index, text

        m = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z0-9 .'\-]{1,50})\b", text, re.I)
        if m:
            name = _clean_memory_value(m.group(1), 50)
            if name:
                add(f"User's name is {name}.", "identity")

        m = re.search(r"\bcall me\s+([A-Za-z][A-Za-z0-9 .'\-]{1,50})\b", text, re.I)
        if m:
            name = _clean_memory_value(m.group(1), 50)
            if name:
                add(f"User wants to be called {name}.", "identity")

        m = re.search(r"\bi (?:live in|am from|'m from)\s+([^.!?\n]{2,80})", text, re.I)
        if m:
            place = _clean_memory_value(m.group(1), 80)
            if place:
                add(f"User lives in {place}.", "identity")

        m = re.search(r"\bi (prefer|like|love|hate|do not like|don't like)\s+([^.!?\n]{4,100})", text, re.I)
        if m:
            preference = _clean_memory_value(m.group(2), 100)
            if preference:
                # The same pattern catches likes and dislikes; keep the stored
                # sentiment faithful instead of recording every match as a
                # preference ("I hate cilantro" must not become "User prefers
                # cilantro").
                verb = m.group(1).lower()
                if verb in ("hate", "do not like", "don't like"):
                    add(f"User dislikes {preference}.", "preference")
                else:
                    add(f"User prefers {preference}.", "preference")

        m = re.search(
            r"\bi (?:(?:want|would like|plan|hope) to|wanna) "
            r"(?:go|travel|move|visit) to\s+([^.!?\n]{2,80})",
            text,
            re.I,
        )
        if m:
            destination = _clean_memory_value(m.group(1), 80)
            if destination:
                add(f"User wants to visit {destination}.", "goal")

    return candidates[:2]


# A citation shorter than this matches by accident. "Sam" appears in any
# message containing the word and proves nothing about where a fact came from,
# so a quote that short is treated as absent rather than as evidence.
_MIN_QUOTE_CHARS = 8

_WHITESPACE = re.compile(r"\s+")


def _normalised(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "")).strip().lower()


def _verified_quote(quote, messages):
    """`(message_index, quote)` when the model's citation is really in the
    transcript, `(None, None)` when it is not. `P13-03`.

    **The model is not trusted for this.** Asked to cite its source, a model
    will produce a plausible sentence the user never typed, and a fabricated
    citation is worse than no citation: `quote` is the one field a person would
    read to decide whether to believe a memory, so it has to be checked against
    the thing it claims to quote.

    Only user messages are searched. The prompt asks for "the user's own
    words", and a fact sourced from something the assistant said is exactly
    what `EXTRACT_SYSTEM_PROMPT` lists under "Bad examples".
    """
    needle = _normalised(quote)
    if len(needle) < _MIN_QUOTE_CHARS:
        return None, None
    for index, message in enumerate(messages or []):
        if _message_role(message) != "user":
            continue
        if needle in _normalised(_message_text(message)):
            return index, (quote or "").strip()
    return None, None


def _text_duplicate_of(new_text: str, existing: list, threshold: float = 0.6):
    """The memory `new_text` restates, or None. Jaccard similarity.

    `P13-15` changed this from a predicate to a lookup, and that is the whole
    shape of the row: it always knew *which* memory the new fact duplicated and
    threw the answer away on the return statement. Every caller was about to
    `continue`, so nobody noticed the information leaving.
    """
    new_tokens = set(new_text.lower().split())
    if not new_tokens:
        return None
    for entry in _memory_dicts(existing):
        old_tokens = set(entry.get("text", "").lower().split())
        if not old_tokens:
            continue
        if len(new_tokens & old_tokens) / len(new_tokens | old_tokens) >= threshold:
            return entry
    return None


def _is_text_duplicate(new_text: str, existing: list, threshold: float = 0.6) -> bool:
    """Whether `new_text` restates something already stored.

    Kept because callers outside this module ask the yes/no question (`Law 1`),
    and it is one line over the lookup rather than a second implementation of
    the comparison (`Law 14`).
    """
    return _text_duplicate_of(new_text, existing, threshold) is not None


def _note_restatement(memory_manager, entry, session, fact_text: str) -> None:
    """The person said a thing they have said before. `P13-15`.

    All three dedupe paths land here. Before this row each of them located the
    matching memory and then `continue`d, so **the moment a fact was confirmed
    for the eleventh time was the moment the observation was discarded** — the
    strongest signal available for what belongs in a Brain, computed exactly and
    dropped. Same defect class as the thirteen `P4` rows, reached from the other
    side: a value computed, used for one branch, and never recorded.

    Guarded, because a counter must never cost a user their extracted facts.
    """
    if not isinstance(entry, dict) or not entry.get("id"):
        return
    session_id = getattr(session, "session_id", None) or getattr(session, "name", None)
    try:
        memory_manager.record_mention(entry["id"], session_id)
    except Exception as e:  # pragma: no cover - a counter is never worth a failure
        logger.warning("Could not record a mention for %s: %s", entry["id"], e)
    else:
        logger.debug("Memory mention: '%s' restates %s", fact_text[:50], entry["id"])


# `P13-05`. The two answers a commitment can have, as an enum and never as a
# boolean. `Law 10`: `ok: false` beside a `reason` is read both as *the commit
# failed* and as *the memory was not acceptable*, and the reviewer incident that
# law is built on is eight good findings discarded over exactly that ambiguity.
COMMIT_COMMITTED = "committed"
COMMIT_REFUSED = "refused"

# What the gate will not promote, phrased for a person rather than for a log.
# Each one is a refusal that changes nothing on the record.
_REFUSE_UNREADABLE = "the memory store could not be read, so nothing was changed"
_REFUSE_UNKNOWN = "no memory with that id"
_REFUSE_ALREADY = "this memory is already committed"
_REFUSE_EMPTY = "there is nothing here to commit"

# Shorter than this is not a fact, it is a fragment. `extract_and_store` has
# dropped candidates on this number since before the gate existed, as a bare
# `5` on its own line; naming it and using it in both places is `Law 14` at its
# smallest scale — the alternative is one length rule with two values the day
# somebody tunes either.
MIN_TEXT_CHARS = 5


def commit_memory(memory_manager, memory_id: str, *, by: str = None,
                  owner: str = None, memory_vector=None) -> dict:
    """Bind a proposed memory. The explicit act `P13-05` is about.

    Until this, extraction and commitment were one event: the background
    extractor wrote straight into the store, and the only thing between a
    sentence somebody typed in frustration and a fact the assistant treats as
    true was a confidence number the extractor gave itself. The phase preamble
    names where that ends — a competitor's behavioural policy list holding raw
    venting *"promoted to a rule at 95%"*.

    **The gate refuses four things, and what it does NOT refuse is the
    interesting half.** It does not re-apply the confidence floor. That floor
    belongs at extraction, where nobody has looked at the candidate yet; a
    person who has read a proposal and decided to keep it has performed the
    strongest signal this system can receive, and `setting_is_explicit` —
    `H06`, `H08`, `D-2026-09-08-02`, `D-2026-09-09-01` — says a thing a person
    typed beats a thing the system inferred. A gate that could veto them would
    make this an approval queue with a second opinion, which is not a quality
    gate, it is a disagreement.

    **A refused restatement is recorded rather than dropped.** `P13-15`'s whole
    finding was that the moment a fact is confirmed is the moment the
    observation gets discarded; somebody proposing a thing the Brain already
    knows is a mention of the memory that knows it, and `record_mention` is
    where that goes. The duplicate check is `_text_duplicate_of`, which already
    answers *"which memory does this restate"* — Jaccard at 0.6, so it catches a
    restatement and not a rewording, and that limit is stated here rather than
    left for somebody to discover.

    Returns `{"verdict": ..., "reason": ..., "memory_id": ...}` and, on a
    refused duplicate, `"duplicate_of"`. Never raises: a commitment that throws
    is a button that does nothing.
    """
    def _refuse(reason, **extra):
        row = {"verdict": COMMIT_REFUSED, "reason": reason, "memory_id": memory_id}
        row.update(extra)
        _record_commit(row, by)
        return row

    if not memory_id:
        return _refuse(_REFUSE_UNKNOWN)
    try:
        entries = memory_manager.load_all_for_update()
    except MemoryStoreUnreadable as e:
        # Strict, for the reason `#5673` exists: a read-modify-write that
        # degrades to `[]` saves one memory over everything a person had, and
        # the writes are atomic so the loss is durable.
        logger.error("Refusing to commit, memory store unreadable: %s", e)
        return _refuse(_REFUSE_UNREADABLE)

    entry = next((e for e in entries if e.get("id") == memory_id), None)
    if entry is None:
        return _refuse(_REFUSE_UNKNOWN)
    if is_committed(entry):
        return _refuse(_REFUSE_ALREADY)

    text = (entry.get("text") or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        return _refuse(_REFUSE_EMPTY)

    # Scoped to this memory's own owner and to what is already COMMITTED. A
    # proposal does not make another proposal a duplicate: neither is binding
    # yet, and refusing the second would let whichever arrived first win an
    # argument nobody had.
    mine = [e for e in entries
            if e is not entry and is_committed(e)
            and (owner is None or e.get("owner") == owner or e.get("owner") is None)]
    match = next(iter(memory_manager.find_duplicates(text, mine)), None) \
        or _text_duplicate_of(text, mine)
    if match is not None:
        _note_restatement(memory_manager, match, None, text)
        return _refuse(
            f'the Brain already knows this — "{(match.get("text") or "")[:60]}"',
            duplicate_of=match.get("id"))

    entry["status"] = STATUS_COMMITTED
    entry["committed_at"] = int(time.time())
    entry["committed_by"] = by
    memory_manager.save(entries)

    # Only now does it reach the index. A proposal is deliberately never
    # embedded: `live()` excludes it from the boot-time rebuild, so an index
    # that held one would have different contents before and after a restart,
    # and an index whose contents depend on when you last rebooted is the class
    # of bug `P0-05` shipped. The cost is stated rather than hidden — a
    # restatement of a PROPOSAL is caught by text dedupe alone, so a reworded
    # one starts a second proposal.
    if memory_vector is not None and getattr(memory_vector, "healthy", False):
        try:
            memory_vector.add(entry["id"], text)
        except Exception as e:
            logger.warning("Memory vector add failed for %s: %s", entry["id"], e)

    row = {"verdict": COMMIT_COMMITTED, "reason": "committed", "memory_id": memory_id}
    _record_commit(row, by)
    return row


def _record_commit(row: dict, by: str = None) -> None:
    """The audit trail, in the table `P14-01` already built for this.

    *"Can be audited afterwards"* is the row's own wording, and it needs no
    store of its own: `events` already answers "what happened at 14:02" for
    tool calls, retrievals and approvals, and a commitment is the same kind of
    thing. `outcome` carries the verdict, so a refusal is as visible as a
    promotion — a log that only records successes cannot answer the question
    anybody actually asks it.
    """
    try:
        from src.events import record_event
        record_event("memory", name="commit", owner=by,
                     outcome=row["verdict"],
                     detail={"memory_id": row.get("memory_id"),
                             "reason": row.get("reason"),
                             "duplicate_of": row.get("duplicate_of")})
    except Exception:
        logger.debug("commit event not recorded", exc_info=True)


def _parse_extraction_json(raw: str) -> list:
    """Parse the extraction LLM's reply into a list of facts, tolerating
    reasoning-model noise.

    The model emits <think>…</think> (and sometimes a prose preamble or a
    ```json fence) AROUND the JSON array; without stripping it, json.loads
    bombs and the run silently yields "0 candidates". Pure str -> list (no
    LLM/network); returns [] on any parse failure instead of raising.
    """
    text = (raw or "").strip()
    try:
        from src.text_helpers import strip_think as _strip_think
        text = _strip_think(text, prose=True, prompt_echo=True).strip()
    except Exception:
        pass
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # JSON may still be embedded in surrounding commentary (leading prose or
    # trailing remarks like "[...] Done!") — slice from the first '[' to the
    # last ']' whenever both exist. Slice unconditionally: a reply that starts
    # with '[' can still carry trailing commentary that breaks json.loads.
    _start = text.find("[")
    _end = text.rfind("]")
    if 0 <= _start < _end:
        text = text[_start : _end + 1]

    try:
        facts = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Memory extraction returned non-JSON: %r", (raw or "")[:120])
        return []
    except Exception:
        logger.debug("Memory extraction returned non-JSON: %r", (raw or "")[:120])
        return []
    return facts if isinstance(facts, list) else []


async def extract_and_store(
    session,
    memory_manager,
    memory_vector,
    endpoint_url: str,
    model: str,
    headers: Optional[dict] = None,
):
    """Extract facts from recent conversation and store them.

    Designed to run as a background task (asyncio.create_task).
    Errors are logged, never raised.
    """
    if not endpoint_url or not model:
        logger.debug("[memory-extract] No model or URL provided, skipping")
        return

    try:
        from src.llm_core import llm_call_async

        # Get last N messages from session
        messages = session.get_context_messages()
        recent = messages[-CONTEXT_WINDOW:] if len(messages) > CONTEXT_WINDOW else messages

        if len(recent) < 2:
            return  # Need at least a user message and assistant response

        # Strip media (images/audio) from messages — background memory extraction
        # only needs the text. The VL-generated descriptions are already in the
        # text content of the messages. This avoids sending image tokens to
        # non-vision models and prevents accidental "vision grounding" triggers.
        stripped_recent = []
        for msg in recent:
            role = msg.get("role")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Filter out multimodal blocks that aren't text
                text_only = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if not text_only and content:
                    continue
                content = text_only
            stripped_recent.append({"role": role, "content": content})

        if not stripped_recent:
            return

        fallback_facts = _fallback_memory_candidates(stripped_recent)

        # Flatten the window into a SINGLE user message instead of appending the
        # raw alternating role messages. Passed as raw chat messages, the model
        # treats the window as a conversation to CONTINUE rather than a transcript
        # to ANALYZE, so it reliably extracts nothing — typically returning `[]`
        # (and, depending on the input, sometimes an empty or <think>-only
        # completion when the window ends on an assistant turn). This was the real
        # cause of auto-memory logging "0 candidates" on every run. Reframing it as
        # one "analyze this transcript, return the JSON array" user message makes
        # the model actually extract. Controlled repro on this model: 0/6 trials
        # with the old structure vs 6/6 with this one. The skill extractor flattens
        # for the same reason.
        def _flatten_msg(m):
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(
                    b.get("text", "") for b in c
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            return f"{m.get('role', '?')}: {c}"

        transcript = "\n\n".join(_flatten_msg(m) for m in stripped_recent)
        extraction_messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                "Conversation to analyze:\n\n" + transcript
                + "\n\nReturn the JSON array of durable facts now (or [] if none)."
            )},
        ]

        facts = []
        try:
            raw = await llm_call_async(
                endpoint_url,
                model,
                extraction_messages,
                temperature=0.1,
                # A reasoning model spends most of its budget on <think> tokens
                # BEFORE emitting the JSON, so the old 500 truncated the response
                # before any JSON appeared → every run logged "0 candidates". The
                # audit path hit the same wall and raised to 16384; extraction's
                # output (a short facts list) is small, so an ample ceiling is
                # enough once thinking has room.
                max_tokens=4096,
                headers=headers,
            )

            # Parse JSON, tolerating reasoning-model noise (<think> blocks, a
            # ```json fence, and leading/trailing commentary). See
            # _parse_extraction_json — returns [] rather than raising.
            facts = _parse_extraction_json(raw)
        except Exception as e:
            logger.warning(f"LLM memory extraction failed; using fallback candidates if available: {e}")

        if not isinstance(facts, list):
            facts = []

        if fallback_facts:
            facts = list(facts) + fallback_facts

        if not facts:
            logger.info("Auto memory extraction ran: 0 candidates")
            return

        # Get owner from session
        _owner = getattr(session, 'owner', None)

        # Strict load: this is a read-modify-write. Degrading to [] here would
        # save only the newly extracted facts and drop the entire store.
        try:
            existing = memory_manager.load_all_for_update()
        except MemoryStoreUnreadable as e:
            logger.error("Skipping auto memory extraction, store unreadable: %s", e)
            return
        added = 0
        added_entries = []

        # `P13-05`. Whether this run BINDS what it extracts or merely proposes
        # it. Read once per run rather than per fact, and shaped exactly like
        # `skill_extractor`'s auto-publish gate — same preference name pattern,
        # same default, same swallowed import — because this is that mechanism
        # lifted onto the other half of the feature and a second shape would be
        # a second thing to learn (`Law 14`).
        #
        # **Default ON, and it has to be.** Flipping it would mean every
        # existing install stops remembering anything new until somebody finds
        # a review queue that no surface draws yet (`B710`). A person who wants
        # extraction to propose turns it off; the mechanism is here, wired end
        # to end, for the moment the Brain page can show them the queue.
        _status = STATUS_COMMITTED
        try:
            from routes.prefs_routes import _load_for_user as _load_prefs
            if not (_load_prefs(_owner) or {}).get("auto_approve_memories", True):
                _status = STATUS_PROPOSED
        except Exception:
            pass

        dropped_low_confidence = 0
        for fact in facts:
            if isinstance(fact, str):
                fact_text = fact
                category = "fact"
                confidence = DEFAULT_CONFIDENCE
                producer = PRODUCER_LLM
                message_index, quote = None, None
            elif isinstance(fact, dict):
                fact_text = fact.get("text", "").strip()
                category = fact.get("category", "fact")
                # `P13-01`. A model that answered the question is believed; one
                # that did not is given the same benefit of the doubt the skill
                # extractor gives it, and one that answered with nonsense falls
                # back to the default rather than to zero — "unparseable" and
                # "not sure" are different claims and only the second should
                # cost a fact its place.
                confidence = normalise_confidence(
                    fact.get("confidence"), DEFAULT_CONFIDENCE)
                producer = fact.get("producer") or PRODUCER_LLM
                if producer == PRODUCER_FALLBACK:
                    # Already a verified match on the user's own sentence: this
                    # path found the message itself rather than asking for a
                    # citation, so there is nothing to check.
                    message_index = fact.get("message_index")
                    quote = fact.get("quote")
                else:
                    message_index, quote = _verified_quote(
                        fact.get("quote"), stripped_recent)
            else:
                continue

            if not fact_text or len(fact_text) < MIN_TEXT_CHARS:
                continue

            # `P13-01`. The skill extractor's floor, on the other half of the
            # feature. `MIN_CONFIDENCE` is imported rather than restated, so
            # this is the same number in the same place for both.
            if confidence is not None and confidence < MIN_CONFIDENCE:
                dropped_low_confidence += 1
                logger.debug(
                    "[memory-extract] '%s' below confidence floor (%.2f < %.2f) — dropped",
                    fact_text[:50], confidence, MIN_CONFIDENCE,
                )
                continue

            # Dedup: check vector similarity first (fast), then exact text match.
            # A runtime embedding/ChromaDB failure (backend OOM, model evicted,
            # remote endpoint down) must not abort the whole batch — fall through
            # to the text/fuzzy dedup below instead of losing every validated
            # fact extracted this session. (`.healthy` is only set at init, so
            # it does not catch failures that develop later.)
            if memory_vector and memory_vector.healthy:
                try:
                    existing_id = memory_vector.find_similar(fact_text, threshold=0.72)
                except Exception as e:
                    logger.warning(f"Memory dedup (vector) unavailable, using text fallback: {e}")
                    existing_id = None
                if existing_id:
                    # The vector store is a single shared collection with no
                    # owner metadata, so find_similar can return ANOTHER
                    # tenant's memory. Only treat it as a duplicate when the
                    # match is this user's own (or a legacy unowned) memory —
                    # otherwise the user's freshly-extracted fact would be
                    # silently dropped. Mirror the owner predicate used by the
                    # text dedup below; cross-tenant/stale matches fall through.
                    _match = next((e for e in existing if e.get("id") == existing_id), None)
                    if _match is not None and (_match.get("owner") == _owner or _match.get("owner") is None):
                        _note_restatement(memory_manager, _match, session, fact_text)
                        continue

            # Text dedup fallback: exact match + fuzzy similarity
            user_existing = [e for e in existing if e.get("owner") == _owner or e.get("owner") is None] if _owner else existing
            _exact = memory_manager.find_duplicates(fact_text, user_existing)
            if _exact:
                _note_restatement(memory_manager, _exact[0], session, fact_text)
                continue
            # Fuzzy text similarity check (catches rephrased duplicates when vector index is unavailable)
            _fuzzy = _text_duplicate_of(fact_text, user_existing)
            if _fuzzy is not None:
                _note_restatement(memory_manager, _fuzzy, session, fact_text)
                continue

            entry = memory_manager.add_entry(
                fact_text, source="auto", category=category, owner=_owner,
                confidence=confidence,
                # `P13-03`. `session_id` is set below and is not repeated in
                # here — one fact, one place (`Law 7`).
                provenance=new_provenance(producer, message_index, quote),
                status=_status,
            )
            # Auto-pin identity facts (name, job, location) — core context.
            # A proposal can carry `pinned` and still not surface: `live()`
            # excludes it before anything reads the flag, so the pin takes
            # effect at the moment of commitment rather than being lost.
            if category == "identity":
                entry["pinned"] = True
            if hasattr(session, "session_id"):
                entry["session_id"] = session.session_id
            elif hasattr(session, "name"):
                entry["session_id"] = session.name

            existing.append(entry)

            # Add to vector index. The JSON store (saved below) is the source of
            # truth and the keyword path can still retrieve this entry, so a vector
            # write failure must not drop the fact or abort the remaining batch.
            #
            # `P13-05`: not for a proposal. `live()` excludes proposals from the
            # boot-time rebuild, so indexing one would give the index different
            # contents before and after a restart. `commit_memory` adds it at
            # the moment it starts binding.
            if _status == STATUS_COMMITTED and memory_vector and memory_vector.healthy:
                try:
                    memory_vector.add(entry["id"], fact_text)
                except Exception as e:
                    logger.warning(f"Memory vector add failed for {entry['id']}: {e}")

            added += 1
            # `P8-23`. The events fired below are one per memory, so they carry
            # one memory each. Collected rather than re-derived from `existing`,
            # which also holds everything that was already there.
            added_entries.append(entry)

        if added > 0:
            memory_manager.save(existing)
            try:
                from src.event_bus import fire_event
                for _entry in added_entries:
                    fire_event("memory_added", _owner,
                               {"memory_id": _entry.get("id"),
                                "text": _entry.get("text")})
            except Exception:
                logger.debug("memory_added event dispatch failed", exc_info=True)
            logger.info(f"Auto-extracted {added} memories from session")

            global _extractions_since_audit
            _extractions_since_audit += added
            if _extractions_since_audit >= AUDIT_INTERVAL:
                _extractions_since_audit = 0
                logger.info("Audit threshold reached, running memory audit")
                await audit_memories(
                    memory_manager, memory_vector, endpoint_url, model, headers, owner=_owner
                )
        elif dropped_low_confidence:
            # Said out loud rather than logged as a plain zero. "0 added"
            # after a run that extracted three facts and dropped all three
            # under the floor looks identical to a model that returned
            # nothing, and they are opposite problems.
            logger.info(
                "Auto memory extraction ran: 0 added (%d below the %.2f "
                "confidence floor)", dropped_low_confidence, MIN_CONFIDENCE)
        else:
            logger.info("Auto memory extraction ran: 0 added")

    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")


def _absorb(survivor: dict, merged: dict) -> None:
    """Fold what a merged-away memory knew into the one that outlived it. `P13-09`.

    **Confidence is raised to `max`, never incremented.** `P13-01` fixes
    confidence as the extractor's self-report at the moment of extraction — the
    number that must not move on its own — and two independent extractions
    agreeing is the one event that is genuinely evidence about it. `max` says
    "the best-evidenced of these" and cannot invent a growth curve; an
    increment would, and after enough tidies everything would read 1.0.

    **`mentions` is summed and `mention_sessions` is not.** Every mention was a
    real statement by the person, so the sum is exact. Sessions are not: the
    same conversation can have produced a mention of both records, and counts
    alone cannot tell. The distinct-session ids are unioned where both records
    kept them (`P13-15` bounds that list at 32) and the count is the larger of
    that union and either original — which can under-count and cannot
    over-count. Over-counting durability is the failure that matters: it makes
    a guess look like a pattern.
    """
    survivor_conf = normalise_confidence(survivor.get("confidence"))
    merged_conf = normalise_confidence(merged.get("confidence"))
    if merged_conf is not None:
        survivor["confidence"] = merged_conf if survivor_conf is None \
            else max(survivor_conf, merged_conf)

    survivor["mentions"] = (int(survivor.get("mentions", 0) or 0)
                            + int(merged.get("mentions", 0) or 0))

    ids = [i for i in (survivor.get("mention_session_ids") or []) if i]
    for sid in (merged.get("mention_session_ids") or []):
        if sid and sid not in ids:
            ids.append(sid)
    if ids:
        # `P13-15` owns this bound and states why (beyond it the count is kept
        # and the ids are forgotten, because the oldest session id has already
        # done its work). Read from there rather than restated as a literal:
        # two copies of one number is one of them going stale (`Law 7`).
        survivor["mention_session_ids"] = ids[-MemoryManager.MENTION_SESSION_MEMORY:]
    survivor["mention_sessions"] = max(
        len(ids),
        int(survivor.get("mention_sessions", 0) or 0),
        int(merged.get("mention_sessions", 0) or 0),
    )

    first = [t for t in (survivor.get("first_mentioned"), merged.get("first_mentioned"),
                         survivor.get("timestamp"), merged.get("timestamp")) if t]
    if first:
        # The older of the two: the fact has been known since whichever record
        # heard it first, and the merge is not the moment it was learned.
        survivor["first_mentioned"] = min(int(t) for t in first)


async def audit_memories(
    memory_manager,
    memory_vector,
    endpoint_url: str,
    model: str,
    headers: Optional[dict] = None,
    owner: Optional[str] = None,
):
    """Send all memories to the LLM for deduplication and consolidation.

    - Merges near-duplicate entries
    - Rewrites vague entries to be concise
    - Removes junk / non-personal entries
    - Rebuilds the vector index afterwards

    Safe to call manually or from the automatic trigger in extract_and_store.
    Errors are logged, never raised.
    """
    try:
        from src.llm_core import llm_call_async

        owned = memory_manager.load(owner=owner)
        # `P13-09`. The audit reads the LIVE set only. What a previous pass
        # merged away is kept on the record (see below) and must not be sent
        # back to the model — re-auditing an archive would resurrect it as a
        # "duplicate" of the entry that replaced it, and it would also make the
        # tidy fingerprint below never match, so every call would spend a full
        # LLM round discovering nothing had changed.
        archived = [m for m in owned if m not in live_memories(owned)]
        existing = live_memories(owned)
        if not existing:
            logger.info("Memory audit: nothing to audit")
            return {"before": 0, "after": 0}

        before_count = len(existing)

        # Skip the LLM call entirely when this exact set of memories was
        # already audited — the previous tidy left them in a clean state
        # and nothing has changed since. Returns instantly so the UI shows
        # "Already clean" without spending 30-120s on a wasted LLM round.
        # The fingerprint includes id+text+category; any add/edit/delete
        # invalidates it and the audit runs normally.
        current_fp = _fingerprint_entries(existing)
        last_state = _load_tidy_state(memory_manager).get(owner or "") or {}
        if last_state.get("fingerprint") == current_fp:
            logger.info("Memory audit: state unchanged since last tidy — skipping LLM")
            return {
                "before": before_count,
                "after": before_count,
                "already_tidy": True,
            }

        # Build payload: list of {id, text, category} for the LLM
        memory_payload = [
            {"id": m["id"], "text": m["text"], "category": m.get("category", "fact")}
            for m in existing
        ]

        audit_messages = [
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(memory_payload, ensure_ascii=False)},
        ]

        raw = await llm_call_async(
            endpoint_url,
            model,
            audit_messages,
            temperature=0.1,
            # 16384 (was 2000): the deduped list of all memories can be large,
            # and a reasoning model spends tokens thinking first — 2000 truncated
            # the JSON so it never parsed ("bad_json").
            max_tokens=16384,
            headers=headers,
            # Bound the call so the Tidy whirlpool can't spin indefinitely on a
            # slow/large generation.
            timeout=120,
        )

        # Parse the JSON list, tolerating reasoning-model noise: <think> blocks,
        # markdown fences, leading prose, and trailing commas.
        import re as _re
        text = (raw or "").strip()
        text = _re.sub(r'<think(?:ing)?>[\s\S]*?</think(?:ing)?>', '', text, flags=_re.I).strip()

        def _loads_list(s):
            if not s:
                return None
            for cand in (s, _re.sub(r',(\s*[}\]])', r'\1', s)):
                try:
                    v = json.loads(cand)
                    if isinstance(v, list):
                        return v
                except Exception:
                    continue
            return None

        cleaned = _loads_list(text)
        if cleaned is None:
            _m = _re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
            if _m:
                cleaned = _loads_list(_m.group(1).strip())
        if cleaned is None:
            _a, _b = text.find('['), text.rfind(']')
            if _a >= 0 and _b > _a:
                cleaned = _loads_list(text[_a:_b + 1])
        if cleaned is None:
            logger.error(f"Memory audit returned non-JSON: {text[:300]}")
            return {"before": before_count, "after": before_count, "error": "bad_json"}

        # Build lookup of original entries by ID so we can preserve metadata
        originals = {m["id"]: m for m in existing}

        final_entries = []
        claimed_merges = {}      # survivor id -> ids the model says it absorbed
        claimed_conflicts = []   # (id, id) pairs the model says disagree
        for item in cleaned:
            if not isinstance(item, dict):
                continue
            mid = item.get("id", "")
            new_text = item.get("text", "").strip()
            if not new_text:
                continue

            if mid in originals:
                # Preserve original metadata, update text + category
                entry = originals[mid].copy()
                entry["text"] = new_text
                if item.get("category"):
                    entry["category"] = item["category"]
            else:
                # ID not found — skip to avoid inventing entries
                logger.debug(f"Audit returned unknown id {mid}, skipping")
                continue

            # `P13-09`. Both are claims about ids, and a model that answers
            # with an id it invented must be ignored rather than believed —
            # the same discipline `_verified_quote` applies to a citation.
            #
            # The check for that is NOT here, and that is deliberate. Every
            # claim below is resolved against `by_id` (the entries that
            # survived) or refused by `attach_edge`, so an `id in originals`
            # test at this point cannot change any answer — mutation testing
            # proved it: inverting it changed nothing. A branch that cannot
            # change an answer is deleted rather than tested around, which is
            # what `P13-14`'s `cutoff`, `P13-15`'s `sessions <= 1` guard and
            # `B62`'s seven stemmer rules each concluded. What survives is the
            # type test, which is load-bearing: a non-string id is unhashable
            # or unorderable and would raise rather than be ignored.
            for merged_id in (item.get("merged_from") or []):
                if isinstance(merged_id, str):
                    claimed_merges.setdefault(mid, []).append(merged_id)
            for other_id in (item.get("contradicts") or []):
                if isinstance(other_id, str):
                    claimed_conflicts.append((mid, other_id))

            final_entries.append(entry)

        after_count = len(final_entries)

        # Safety net against catastrophic over-deletion. A conservative tidy
        # should never wipe out half the store in one pass — if the model
        # returned far fewer entries than it was given (over-consolidation, a
        # dropped/truncated list, or it ignored ids), treat it as a misfire and
        # DON'T save. Better to no-op than to silently lose memories.
        #
        # `B640`, found while writing `P13-09`'s tests. The `>= 8` floor left
        # every small store unguarded, and "small" is a person's first weeks
        # with the product: a reply that parsed as a list but named no id the
        # store recognises produced `final_entries == []`, which sailed past
        # this check and saved an empty store over a real one. The write is
        # atomic, so the loss was durable. A tidy that would remove EVERYTHING
        # is a misfire at any size — there is no corpus for which "all of it
        # was junk" is the likely reading of a model's answer.
        if before_count > 0 and after_count == 0:
            logger.warning(
                "Memory audit returned nothing usable for %d entries — refusing "
                "as unsafe, keeping originals", before_count)
            return {"before": before_count, "after": before_count,
                    "error": "unsafe_removal"}
        if before_count >= 8 and after_count < before_count * 0.5:
            logger.warning(
                f"Memory audit would cut {before_count} -> {after_count} "
                f"(>50% removed) — refusing as unsafe, keeping originals"
            )
            return {"before": before_count, "after": before_count, "error": "unsafe_removal"}

        # ── `P13-09`: record the consolidation instead of performing it quietly ──
        #
        # Everything above this point is unchanged: the model returned a list,
        # and whatever it did not return was deleted. That deletion is the
        # "picking a winner quietly" the row is about — the pass located a
        # duplicate precisely, chose which copy to keep, and left no trace of
        # either the choice or the corroboration it had just observed. Same
        # defect class as `P13-15`, where the moment a fact was confirmed was
        # the moment the observation was discarded.
        by_id = {e["id"]: e for e in final_entries}
        explicit_survivor = {}
        for survivor_id, merged_ids in claimed_merges.items():
            for merged_id in merged_ids:
                explicit_survivor.setdefault(merged_id, survivor_id)

        superseded = []
        for original in existing:
            if original["id"] in by_id:
                continue
            survivor = by_id.get(explicit_survivor.get(original["id"]))
            if survivor is None:
                # The model dropped this id without saying what absorbed it,
                # which is what a model too small to follow the extended schema
                # will always do. Look for the survivor the same way the
                # extractor's own dedupe does (`Law 14` — `_text_duplicate_of`
                # already answers "which memory does this restate", and it
                # answers it here too). No near-duplicate survives means this
                # was a removal rather than a merge, and removal is still
                # removal.
                survivor = _text_duplicate_of(original.get("text", ""), final_entries)
            if survivor is None:
                continue
            _absorb(survivor, original)
            attach_edge(survivor, EDGE_SUPERSEDES, original["id"], originals,
                        note="merged by the memory audit")
            # Kept, not deleted. `supersedes` already stops it surfacing in
            # every search (`P13-02`), so consolidation still consolidates —
            # what changes is that the copy the audit chose against is still
            # there to be read, corrected or restored, and the record says
            # which entry replaced it.
            archived_copy = dict(original)
            archived_copy["superseded_by"] = survivor["id"]
            superseded.append(archived_copy)

        conflicts = 0
        for left, right in claimed_conflicts:
            if left in by_id and right in by_id:
                if attach_edge(by_id[left], EDGE_CONTRADICTS, right, by_id,
                               note="flagged as incompatible by the memory audit"):
                    conflicts += 1

        if superseded or conflicts:
            logger.info(
                "Memory audit: %d entries superseded rather than deleted, "
                "%d contradictions recorded", len(superseded), conflicts)

        # Merge audited entries back with other users' entries
        if owner:
            # Strict load: the merge below reconstructs the whole file. If this
            # degraded to [] we would save only this owner's audited slice and
            # destroy every other tenant's memories.
            try:
                all_entries = memory_manager.load_all_for_update()
            except MemoryStoreUnreadable as e:
                logger.error("Aborting memory audit save, store unreadable: %s", e)
                return {
                    "before": before_count,
                    "after": before_count,
                    "error": "store_unreadable",
                }
            audited_ids = {e["id"] for e in final_entries}
            other_entries = [e for e in all_entries if e.get("owner") != owner and (e.get("owner") is not None)]
            # Also keep legacy entries that weren't part of this audit
            for e in all_entries:
                if e.get("owner") is None and e["id"] not in audited_ids and e["id"] not in {o["id"] for o in other_entries}:
                    other_entries.append(e)
            saved_entries = final_entries + superseded + archived + other_entries
        else:
            saved_entries = final_entries + superseded + archived
        memory_manager.save(saved_entries)
        logger.info(
            "Memory audit complete: %d -> %d entries (%d superseded and kept, "
            "%d removed)",
            before_count, after_count, len(superseded),
            before_count - after_count - len(superseded),
        )

        # Rebuild vector index from the full saved set, not just this owner's
        # slice — otherwise the shared collection is wiped of every other
        # owner's entries until they happen to run their own audit.
        #
        # `P13-09`: the LIVE set of that, though. A superseded memory that
        # stayed in the index would still be returned by
        # `MemoryVectorStore.find_similar`, which is what the extractor's first
        # dedupe gate calls — so the next time the person stated the fact, the
        # restatement would be credited to the archived copy and the live one
        # would never hear about it. The scorer filters them out anyway
        # (`P13-02`); this stops them being found by the path that does not go
        # through the scorer at all.
        if memory_vector and memory_vector.healthy:
            memory_vector.rebuild(live_memories(saved_entries))

        # Persist the post-tidy fingerprint so the next call short-circuits
        # if nothing has changed in the meantime.
        _save_tidy_state(memory_manager, owner, _fingerprint_entries(final_entries))

        return {
            "before": before_count,
            "after": after_count,
            # Additive. `before - after` has always meant "stopped surfacing";
            # what is new is that most of that is now recoverable rather than
            # gone, and a caller that reports "12 removed" when 11 of them are
            # one click from being restored is telling a person something
            # frightening and false.
            "superseded": len(superseded),
            "contradictions": conflicts,
        }

    except Exception as e:
        logger.error(f"Memory audit failed: {e}")
        return {"error": str(e)}
