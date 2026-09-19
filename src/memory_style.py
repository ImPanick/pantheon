# SPDX-License-Identifier: AGPL-3.0-or-later
"""
memory_style.py

How this person writes, what is different about it right now, and what the
assistant does about that. `P13-17`, `P13-18`, `P13-19`, `P13-20`, which are
one design and are ruled on together by `D-2026-09-09-01`.

**Three layers, and conflating them is the whole failure mode.** The decision
says it plainly and this module keeps them in three separate functions with
three separate lifetimes:

* `observe()` + `fold()` → **style**, slow and stable, months. A profile.
* `read()` → **state**, this turn, stored nowhere. A reading.
* `register()` → **register**, what the assistant does about it. An output.

*"An assistant that decided you were angry in March and has been careful with
you ever since is what happens when 2 is stored like 1."* So the reading is a
return value and never a field: `read()` takes the profile and a window of
messages and computes an answer, and there is no setter anywhere in this file
that could write one down.

**The baseline is personal and never population, and this module holds no
population anything.** There is no sentiment model, no trained weights, no word
list scored for valence — only counters, and every judgement below is a ratio
against *this person's own* counters. The owner writes *"PRESS!!"* and *"lol"*
as ordinary register; a population-trained sentiment model reads that as
elevated and is wrong every single time, and the way to not make that mistake
is to have nothing in the file that could.

**Nothing here needs a model, a network or a key.** It is arithmetic over
strings. That is not a happy accident: a fresh install with nothing linked must
work (`Law 16`), and a feature that learns how you write by asking a cloud model
would be the single worst thing in this product to send anywhere.

**The line this module may not cross**, from the decision: it records *how to be
useful to this person* and never *how this person is doing*. `FORBIDDEN_WORDS`
below is that sentence made executable — every trait name, bucket, sentence and
register field this module can emit is checked against it by a test, so the rule
fails a build rather than surviving as a comment somebody meant.

**Why it imports nothing from the project.** Same reason `src/memory_edges.py`
and `src/retrieval_engine.py` do not: `src/memory.py` imports
`src/memory_retrieval.py` at module scope, and both the store and the chat
preface need these names. A vocabulary that depends on the subsystem storing it
is a vocabulary you cannot test without the subsystem.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

# ── the kind of record this is ────────────────────────────────────────────────

# `P13-17`. **Not a memory**, and the row is emphatic about why: *"a memory is a
# fact about the world the person told us, this is a disposition we observed,
# and filing observations as things-they-said is how a Brain starts lying about
# its sources."* Same store, its own kind. The name lives here rather than in
# `src/memory_edges.py` because that module's subject is relations between
# memories and this is a statement about what a record IS — but `live()` there
# is still the one predicate that honours it, because two answers to *"does this
# surface"* is the failure `P13-05` already spent a paragraph on.
KIND_STYLE = "style"

# Everything written before this row. A record with no `kind` is a memory, for
# exactly the reason `P13-05` gave `status` a value rather than a `None`: this
# is not a judgement nobody made about an old record, it is what the record
# already is.
KIND_MEMORY = "memory"

KINDS = (KIND_MEMORY, KIND_STYLE)


def kind_of(record) -> str:
    """The kind of a record, normalising anything unrecognised to `memory`.

    An unrecognised value reads as a memory for the same reason an unrecognised
    `status` reads as committed (`P13-05`): a hand-edited typo in a JSON file
    must not make records vanish, and of the two ways to be wrong here,
    *"a style note got treated as a memory"* is visible in the Brain and
    *"every memory stopped surfacing"* is the least visible failure this product
    can have.
    """
    if not isinstance(record, dict):
        return KIND_MEMORY
    value = record.get("kind")
    return value if value in KINDS else KIND_MEMORY


# ── the line this module may not cross ────────────────────────────────────────

# `D-2026-09-09-01`: *"the profile records how to be useful to this person and
# not how this person is doing. 'Writes shorter under pressure; wants the fix
# before the explanation' is a working note. 'Seems anxious lately' is not
# something a text box should be keeping about anybody, and no row here may
# produce it."*
#
# This tuple is that paragraph as a test fixture. It is checked against every
# trait id, every bucket id, every sentence this module renders and every key of
# the register — not against the source file, because a file-wide grep would
# match the sentence you are reading (`Law 20`, and `H10` is the worked example:
# it asserted `"innerHTML" not in panel` and the only occurrence was the comment
# explaining why the panel does not use it).
FORBIDDEN_WORDS = (
    "angry", "anger", "anxious", "anxiety", "sad", "happy", "upset", "mood",
    "moody", "emotion", "emotional", "feeling", "feels", "stressed", "stress",
    "frustrated", "frustration", "depressed", "irritated", "annoyed", "calm",
    "excited", "worried", "distressed", "tense", "agitated", "cheerful",
)


# ── observation: one message in, counters out ─────────────────────────────────

_WORD = re.compile(r"[A-Za-z0-9_'’-]+")
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")

# Emoji and pictographs. Ranges rather than a list, because a list of emoji is a
# list that goes stale every time Unicode ships.
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF←-⇿⬀-⯿]"
)

# Laughter and joke markers. **This is not a humour detector and it is not
# trying to be** (`P13-20`): detecting that somebody jokes is the trivial half,
# and every meaning-bearing decision about it happens in `fold_humour` against
# this person's own learned association. All this does is notice the observable.
_LAUGH = re.compile(
    r"(?:\blol\b|\blmao\b|\blmfao\b|\brofl\b|\bha(?:ha)+\b|\bhe(?:he)+\b|"
    r"\bheh\b|\bjk\b|\b/s\b|\bkek\b|\bteehee\b)",
    re.IGNORECASE,
)

# Profanity, as *observables* and not as a moral category. The list is short and
# stem-based on purpose: it exists to be counted against the person's own rate,
# and a longer list would not change a ratio it appears on both sides of.
_PROFANITY = re.compile(
    r"\b(?:fuck\w*|shit\w*|damn\w*|crap\w*|bollocks|bugger\w*|arse\w*|ass(?:hole)?s?|"
    r"bastard\w*|bitch\w*|piss\w*|wank\w*|twat\w*|prick\w*|cunt\w*|dick(?:head)?s?)\b",
    re.IGNORECASE,
)

# Complaint markers. Used by `P13-20` and **only** by `P13-20`: a joke wrapped
# around one of these is the *wrapper* case, where the complaint is real and the
# joke is packaging. Nothing else in this module reads it, because "the person
# complained" is a fact about the message and not a fact about the person.
_COMPLAINT = re.compile(
    r"(?:\bbroken?\b|\bdoesn'?t work\b|\bdidn'?t work\b|\bstill (?:not|doesn)\b|"
    r"\bfail(?:s|ed|ing)?\b|\bwrong\b|\bagain\b.*\?|\bwhy (?:is|does|doesn|won)\b|"
    r"\bno(?:pe)? (?:it|that)\b|\bthat'?s not\b)",
    re.IGNORECASE,
)

# A greeting at the top of a message. Deliberately NOT the casual-opening regex
# from `src/agent_loop.py` / `routes/chat_helpers.py`: that one decides whether a
# turn should inherit stale context and its blocklist is about tool nouns, which
# is a different question with a different right answer. Copying it would have
# made a third copy of a regex this tree already carries two of (`B823`).
_GREETING = re.compile(
    r"^\s*(?:hi+|hey+|hello+|yo+|sup|hiya|howdy|morning|afternoon|evening|"
    r"good (?:morning|afternoon|evening))\b",
    re.IGNORECASE,
)

# Code, paths, identifiers, flags. "Technical density" in the decision's list.
_TECHNICAL = re.compile(
    r"(?:`[^`]+`|\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z][A-Za-z]*\b|"
    r"(?:^|\s)[-/][A-Za-z][\w./-]*|\b\w+\.(?:py|js|json|ya?ml|sh|md|ts|css|html)\b|"
    r"\b[A-Z][A-Z0-9_]{2,}\b)"
)

# Instructing rather than asking. A short, blunt list of imperative openers: the
# distinction the decision names is *"whether they instruct or ask"*, and a
# question mark answers the second half on its own.
_IMPERATIVE = re.compile(
    r"^\s*(?:please\s+)?(?:make|do|add|write|fix|change|run|show|give|build|"
    r"remove|delete|use|set|check|find|open|close|stop|start|put|move|send|"
    r"update|create|explain|tell|list|try)\b",
    re.IGNORECASE,
)

# The counter names an observation carries. Every one is a count or a total, so
# two observations fold by adding — which is the whole reason the profile can be
# kept as running sums and never needs the transcript it came from.
OBSERVATION_FIELDS = (
    "messages", "words", "sentences", "lower_open", "caps_words", "exclaims",
    "profanity", "profanity_messages", "emoji", "technical", "questions",
    "imperatives", "greetings", "laughs", "laugh_messages", "complaints",
)


def observe(text: str) -> Dict[str, int]:
    """Count one user message. `P13-17`.

    Returns a dict of the counters in `OBSERVATION_FIELDS`, all integers, all
    additive. **No judgement is made here and none can be**: this function
    cannot see the person's history, so there is nothing for it to be a
    deviation from. That separation is the design — `read()` is the only place a
    number becomes a signal, and it needs a baseline to do it.
    """
    raw = str(text or "")
    stripped = raw.strip()
    counts = {name: 0 for name in OBSERVATION_FIELDS}
    if not stripped:
        return counts

    words = _WORD.findall(stripped)
    sentences = len([s for s in _SENTENCE_END.split(stripped) if s.strip()]) or 1
    profanity = len(_PROFANITY.findall(stripped))
    laughs = len(_LAUGH.findall(stripped))

    counts["messages"] = 1
    counts["words"] = len(words)
    counts["sentences"] = sentences
    counts["lower_open"] = 1 if stripped[:1].islower() else 0
    counts["caps_words"] = len([w for w in words if len(w) > 1 and w.isupper()])
    counts["exclaims"] = stripped.count("!")
    counts["profanity"] = profanity
    counts["profanity_messages"] = 1 if profanity else 0
    counts["emoji"] = len(_EMOJI.findall(stripped))
    counts["technical"] = len(_TECHNICAL.findall(stripped))
    counts["questions"] = 1 if stripped.endswith("?") else 0
    counts["imperatives"] = 1 if _IMPERATIVE.match(stripped) else 0
    counts["greetings"] = 1 if _GREETING.match(stripped) else 0
    counts["laughs"] = laughs
    counts["laugh_messages"] = 1 if laughs else 0
    counts["complaints"] = 1 if _COMPLAINT.search(stripped) else 0
    return counts


def fold(totals: Optional[Dict], observation: Dict[str, int]) -> Dict[str, int]:
    """Add one observation into the running totals. `P13-17`.

    Pure, and returns a new dict rather than mutating either argument — the
    caller that writes the store is `MemoryManager.record_style_observation`,
    and a function that both computes and persists is one you cannot test
    without a filesystem.
    """
    out = {name: 0 for name in OBSERVATION_FIELDS}
    for name in OBSERVATION_FIELDS:
        try:
            out[name] = int((totals or {}).get(name, 0) or 0)
        except (TypeError, ValueError):
            out[name] = 0
        try:
            out[name] += int((observation or {}).get(name, 0) or 0)
        except (TypeError, ValueError):
            pass
    return out


# ── the profile: buckets, because a sentence that moves is a sentence nobody
#    can edit ───────────────────────────────────────────────────────────────────

# `P13-17`'s `Verify:` says *"a profile exists after N conversations"*. N is in
# **messages** here and not conversations, because a conversation is not a unit
# of writing — one person's conversation is forty lines and another's is two, and
# a threshold in conversations would give the second person a profile built from
# almost nothing.
#
# Twenty is chosen to be defensible rather than tuned, and the reason it is not
# tuned is worth writing down: there is no golden set for *"did we describe you
# correctly"* and `D-2026-09-09-01` says there cannot be one. What there is
# instead is the edit signal, and the honest way to pick a floor with no
# instrument is to pick one a person can argue with.
PROFILE_MIN_MESSAGES = 20

# **Buckets, and they are the load-bearing design choice in this half of the
# file.** A trait could be a number, and then every sentence in the profile
# would change on every message — which breaks two things at once. The person
# cannot edit a sentence that rewrites itself under them (`P13-17`: *"edits are
# the only error signal this feature can have"*), and the profile is injected as
# a **system** message, where turn-to-turn text invalidates the KV-cache prefix
# on every request for exactly the local llama.cpp / LM Studio backends this
# project exists to serve (`src/user_time.py:216`, issue #2927).
#
# A bucketed trait changes when the person's writing genuinely changes category,
# which is months, which is what `D-2026-09-09-01` calls this layer.
TRAIT_LENGTH = "length"
TRAIT_CASE = "case"
TRAIT_PROFANITY = "profanity"
TRAIT_EMOJI = "emoji"
TRAIT_TECHNICAL = "technical"
TRAIT_MODE = "mode"

TRAITS = (TRAIT_LENGTH, TRAIT_CASE, TRAIT_PROFANITY, TRAIT_EMOJI,
          TRAIT_TECHNICAL, TRAIT_MODE)

# Bucket ids and the sentence each one renders. The sentences are written in the
# first person plural of a working note — *"wants"*, *"writes"* — because the
# person reads and edits them, and a profile that reads like a clinical record is
# one nobody corrects.
_BUCKETS: Dict[str, Sequence] = {
    TRAIT_LENGTH: (
        ("terse", "Writes short — a line or two, rarely more."),
        ("measured", "Writes in a few sentences at a time."),
        ("expansive", "Writes at length, several sentences at a time."),
    ),
    TRAIT_CASE: (
        ("lowercase", "Types in lower case and does not punctuate for form."),
        ("sentence_case", "Capitalises and punctuates normally."),
    ),
    TRAIT_PROFANITY: (
        ("none", "Does not swear."),
        ("punctuation", "Swears as ordinary punctuation — it carries no weight."),
        ("emphasis", "Swears rarely, and it marks emphasis when it happens."),
    ),
    TRAIT_EMOJI: (
        ("none", "Does not use emoji."),
        ("some", "Uses emoji."),
    ),
    TRAIT_TECHNICAL: (
        ("plain", "Writes in plain prose."),
        ("technical", "Writes with code, paths and identifiers inline."),
    ),
    TRAIT_MODE: (
        ("asks", "Tends to ask rather than instruct."),
        ("instructs", "Tends to instruct rather than ask."),
        ("mixed", "Asks and instructs about equally."),
    ),
}


def _rate(totals: Dict, field: str, per: str = "messages") -> float:
    try:
        denominator = float(totals.get(per, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if denominator <= 0:
        return 0.0
    try:
        return float(totals.get(field, 0) or 0) / denominator
    except (TypeError, ValueError):
        return 0.0


def traits(totals: Optional[Dict]) -> Dict[str, str]:
    """Bucket the running totals into one value per trait. `P13-17`.

    Returns `{}` when there is not enough history, rather than a set of
    defaults. **A person with no history gets no profile, not an average one** —
    the same call `P13-18` makes for the reading and `P13-01` made for
    confidence, for the same reason: a value invented for somebody nobody has
    observed looks exactly like a value somebody measured.
    """
    totals = totals or {}
    try:
        messages = int(totals.get("messages", 0) or 0)
    except (TypeError, ValueError):
        messages = 0
    if messages < PROFILE_MIN_MESSAGES:
        return {}

    words_per_message = _rate(totals, "words")
    out = {}

    if words_per_message < 12:
        out[TRAIT_LENGTH] = "terse"
    elif words_per_message < 40:
        out[TRAIT_LENGTH] = "measured"
    else:
        out[TRAIT_LENGTH] = "expansive"

    out[TRAIT_CASE] = "lowercase" if _rate(totals, "lower_open") >= 0.5 else "sentence_case"

    # **The row's own worked example, and the one place the personal baseline is
    # doing visible work.** Two people can swear at the same rate per message
    # and mean opposite things by it, and the separator is not the rate — it is
    # how *spread out* it is. Somebody who swears in most messages is swearing as
    # punctuation and a swear from them says nothing; somebody who swears in one
    # message in ten is marking that message, and `read()` below only treats
    # profanity as a signal for the second person. That is
    # `D-2026-09-09-01`'s *"a swear count is not an emotion signal, a swear count
    # against this person's own baseline is"*, implemented rather than quoted.
    profanity_share = _rate(totals, "profanity_messages")
    if profanity_share <= 0:
        out[TRAIT_PROFANITY] = "none"
    elif profanity_share >= 0.25:
        out[TRAIT_PROFANITY] = "punctuation"
    else:
        out[TRAIT_PROFANITY] = "emphasis"

    out[TRAIT_EMOJI] = "some" if _rate(totals, "emoji") >= 0.1 else "none"
    out[TRAIT_TECHNICAL] = "technical" if _rate(totals, "technical") >= 1.0 else "plain"

    asks, instructs = _rate(totals, "questions"), _rate(totals, "imperatives")
    if asks >= instructs * 1.5:
        out[TRAIT_MODE] = "asks"
    elif instructs >= asks * 1.5:
        out[TRAIT_MODE] = "instructs"
    else:
        out[TRAIT_MODE] = "mixed"
    return out


def sentences(trait_values: Optional[Dict[str, str]]) -> List[str]:
    """The profile as the person reads it. `P13-17`.

    Plain sentences, one per trait, in a fixed order so the text is stable
    between renders — a list that reorders itself is a list whose diff is
    useless, and the diff is how anybody notices we described them wrongly.
    """
    out = []
    for trait in TRAITS:
        value = (trait_values or {}).get(trait)
        for bucket, sentence in _BUCKETS.get(trait, ()):
            if bucket == value:
                out.append(sentence)
                break
    return out


def profile_text(trait_values: Optional[Dict[str, str]]) -> str:
    """The stored `text` of the style record: the sentences, newline-joined."""
    return "\n".join(sentences(trait_values))


# ── the reading: this turn, against their own norm, stored nowhere ────────────

SIGNAL_SHORTER = "writing_shorter_than_usual"
SIGNAL_EMPHATIC = "more_emphatic_than_usual"
SIGNAL_NO_GREETING = "opening_without_the_usual_greeting"
SIGNAL_SWEARING = "swearing_more_than_usual"

SIGNALS = (SIGNAL_SHORTER, SIGNAL_EMPHATIC, SIGNAL_NO_GREETING, SIGNAL_SWEARING)

# **Every signal name above is an observable and none of them is a state.**
# *"Writing shorter than usual"* is a thing that is true of the text; *"under
# pressure"* is a thing somebody would be, and this module is not allowed to
# hold that (`FORBIDDEN_WORDS`). The register maps observables to delivery, and
# at no point does a word for a person's interior appear on the path.

# How much of the window the newest message is worth. `D-2026-09-09-01`: *"it
# must decay, because a reading that persists becomes a belief."* Decay here is
# structural rather than scheduled — the reading is computed from a window of
# the current session's messages with the newest weighted most, it is returned
# rather than stored, and the window belongs to the session. There is no field
# to expire because there is no field.
READING_WINDOW = 6
READING_DECAY = 0.6

# Below this, `register()` returns the neutral register and the assistant
# behaves normally. `D-2026-09-09-01`: *"low confidence means behave normally —
# not 'behave gently'. Softening everything for someone who is not upset is
# patronising, and it is the failure people actually notice and resent."*
REGISTER_MIN_CONFIDENCE = 0.5


def _weighted(window: Sequence[str]) -> Dict[str, float]:
    """Fold a window of messages into decayed per-message rates."""
    recent = [m for m in (window or []) if str(m or "").strip()][-READING_WINDOW:]
    if not recent:
        return {}
    out = {name: 0.0 for name in OBSERVATION_FIELDS}
    weight_total = 0.0
    # Newest last, so the newest message gets weight 1.0 and each older one is
    # multiplied down. An older message is still evidence; it is just less of it.
    for offset, text in enumerate(reversed(recent)):
        weight = READING_DECAY ** offset
        counts = observe(text)
        for name in OBSERVATION_FIELDS:
            out[name] += counts[name] * weight
        weight_total += weight
    return {name: value / weight_total for name, value in out.items()}


def read(profile_totals: Optional[Dict], window: Sequence[str]) -> Dict:
    """What is different about how this person is writing right now. `P13-18`.

    Returns `{"signals": [...], "confidence": 0.0..1.0, "baseline": bool}`.
    **Never stored**: this is the volatile layer, and the decision's failure case
    is an assistant that decided something about you in March. It cannot happen
    to a return value.

    **A person with no history is read as nothing, not as neutral.** With fewer
    than `PROFILE_MIN_MESSAGES` behind them there is no baseline, so there is no
    deviation to compute, so the answer is an empty signal list at zero
    confidence — and `register()` turns that into *behave exactly as you would
    have*. Reading a new user as "neutral" would be a claim; reading them as
    nothing is the absence of one.

    **`baseline` is why that distinction survives the return**, and it is a third
    field rather than an inference from the other two because *"we could not
    look"* and *"we looked and nothing was unusual"* are opposite findings that
    both render as an empty list (`Law 10`). `P13-20` is the caller that needs
    them apart: writing exactly as you always do is evidence about your humour,
    and having no history yet is not.
    """
    baseline = profile_totals or {}
    try:
        messages = int(baseline.get("messages", 0) or 0)
    except (TypeError, ValueError):
        messages = 0
    if messages < PROFILE_MIN_MESSAGES:
        return {"signals": [], "confidence": 0.0, "baseline": False}

    unremarkable = {"signals": [], "confidence": 0.0, "baseline": True}
    now = _weighted(window)
    if not now:
        return unremarkable

    trait_values = traits(baseline)
    signals = []

    base_words = _rate(baseline, "words")
    if base_words > 0 and now["words"] <= base_words * 0.5:
        signals.append(SIGNAL_SHORTER)

    base_emphasis = _rate(baseline, "caps_words") + _rate(baseline, "exclaims")
    live_emphasis = now["caps_words"] + now["exclaims"]
    if live_emphasis > max(base_emphasis * 2.0, base_emphasis + 0.5):
        signals.append(SIGNAL_EMPHATIC)

    base_greeting = _rate(baseline, "greetings")
    if base_greeting >= 0.3 and now["greetings"] <= base_greeting * 0.25:
        signals.append(SIGNAL_NO_GREETING)

    # **Profanity is a signal only for the person it is a signal for, and the
    # branch is the whole argument of `P13-18` rather than a detail of it.** For
    # somebody whose trait is `punctuation` a swear carries no weight *by
    # definition* — they use it as punctuation, that is what the bucket means —
    # and counting it would be the population-model mistake `D-2026-09-09-01`
    # names: the owner's own *"PRESS!!"* and *"lol"* read as elevated by a scorer
    # that never met them. For the `emphasis` and `none` people the same
    # observable is the loudest thing in the message, and `none` is the stronger
    # of the two rather than a case to skip — somebody who has never sworn in a
    # hundred messages and swears now has deviated further than the person who
    # does it occasionally. That is why this tests for the *excluded* bucket
    # instead of listing the included ones: the exclusion is the claim.
    if trait_values.get(TRAIT_PROFANITY) != "punctuation":
        base_profanity = _rate(baseline, "profanity")
        if now["profanity"] > max(base_profanity * 2.0, base_profanity + 0.5):
            signals.append(SIGNAL_SWEARING)

    if not signals:
        return unremarkable

    # Confidence is how much we have seen and how much of it agrees, and it is
    # capped well under 1.0 on purpose: nothing in this file is ever certain
    # about a person, and a number that can read 1.0 invites a caller to treat it
    # as one.
    history = min(messages / (PROFILE_MIN_MESSAGES * 5.0), 1.0)
    agreement = min(len(signals) / 2.0, 1.0)
    confidence = round(min(0.35 + 0.4 * history + 0.25 * agreement, 0.9), 3)
    return {"signals": sorted(signals), "confidence": confidence, "baseline": True}


# ── humour: nothing happens until it is learned ───────────────────────────────

HUMOUR_DEFUSE = "defuse"
HUMOUR_RELAXED = "relaxed"
HUMOUR_WRAPPER = "wrapper"

HUMOUR_MEANINGS = (HUMOUR_DEFUSE, HUMOUR_RELAXED, HUMOUR_WRAPPER)

# How many joking turns before the association is allowed to mean anything, and
# how far ahead the leader must be. `D-2026-09-09-01`: *"abstaining is not
# caution here, it is correctness: mistaking a wrapped complaint for a good mood
# is the most alienating error the whole feature could make."* Both gates are
# required, and the margin is the one that matters — six observations split
# three-two-one is not evidence of anything.
HUMOUR_MIN_EVIDENCE = 6
HUMOUR_MIN_MARGIN = 2.0


def classify_humour(observation: Dict[str, int], reading: Optional[Dict]) -> Optional[str]:
    """Which of the three this joking turn is evidence for. `P13-20`.

    `None` when the turn carries no humour, and `None` is also the honest answer
    for a joking turn with no reading to classify it against — the association is
    learned from what the joke *co-occurs with*, and before a baseline exists
    there is nothing for it to co-occur with.

    The three cases are the decision's three, in the order that matters:

    * a joke wrapped round a complaint is a **wrapper**, and the complaint is
      the real message. Checked first, because a wrapped complaint also looks
      like the other two and is the one this feature must not get wrong;
    * a joke alongside a deviation is a **defuse**;
    * a joke with the person writing exactly as they always do is **relaxed**.
    """
    if not (observation or {}).get("laugh_messages"):
        return None
    if not (reading or {}).get("baseline"):
        # No baseline, so there is nothing for the joke to co-occur *with*. This
        # is the branch that keeps a brand-new user from teaching the system the
        # wrong association out of their first six messages.
        return None
    if not (reading or {}).get("signals"):
        return HUMOUR_RELAXED
    if (observation or {}).get("complaints"):
        return HUMOUR_WRAPPER
    return HUMOUR_DEFUSE


def fold_humour(stored: Optional[Dict], meaning: Optional[str]) -> Dict:
    """Add one classification to the learned counts. `P13-20`. Pure."""
    counts = {name: 0 for name in HUMOUR_MEANINGS}
    for name in HUMOUR_MEANINGS:
        try:
            counts[name] = int(((stored or {}).get("observations") or {}).get(name, 0) or 0)
        except (TypeError, ValueError):
            counts[name] = 0
    if meaning in HUMOUR_MEANINGS:
        counts[meaning] += 1
    return {"observations": counts, "means": humour_means(counts)}


def humour_means(counts: Optional[Dict]) -> Optional[str]:
    """What this person's humour means, or `None` while it is not known.

    `None` is the answer for a long time and that is the row working, not the
    row failing: *"it produces no register change until there is evidence for
    which one this person is."* A counter cannot separate the three meanings,
    so what separates them is a margin over enough turns, and until there is one
    the answer is that we do not know.
    """
    counts = counts or {}
    try:
        tally = {name: int(counts.get(name, 0) or 0) for name in HUMOUR_MEANINGS}
    except (TypeError, ValueError):
        return None
    total = sum(tally.values())
    if total < HUMOUR_MIN_EVIDENCE:
        return None
    ranked = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
    leader, best = ranked[0]
    runner_up = ranked[1][1]
    if best < HUMOUR_MIN_EVIDENCE / 2.0:
        return None
    if runner_up > 0 and best < runner_up * HUMOUR_MIN_MARGIN:
        return None
    return leader


# ── register: what the assistant does about it ────────────────────────────────

# Four dials, and the constraint on the whole set is one sentence from the
# decision: *"a reading may change how much is said, how directly, and whether
# the assistant asks or acts. It may not change what is true, and it may not add
# feelings the assistant does not have."* Every value below is a property of
# delivery. There is no dial here that could change a claim, because there is no
# dial here that refers to content.
REGISTER_NEUTRAL = {
    "length": "normal",
    "hedging": "normal",
    "clarify": "normal",
    "humour": "normal",
}


def register(reading: Optional[Dict], *, humour: Optional[str] = None,
             joking: bool = False, persona_is_explicit: bool = False) -> Dict:
    """What to do about the reading. `P13-19`, `P13-20`.

    Returns a dict with the keys of `REGISTER_NEUTRAL`.

    **An explicit choice always beats an inferred one.** A chosen persona wins
    over a reading, every time — `setting_is_explicit` (`H06`, `H08`,
    `D-2026-09-08-02`, `P13-05`), and `D-2026-09-09-01` says which way it points
    here: *"someone running Razor asked for blunt and minimal; a reading that
    they seem playful today does not get to soften it."* So the persona branch
    returns the neutral register and does not merely lose a tiebreak.

    **The move under pressure is shorter, not softer**, and it is the line the
    feature lives on. *"Detecting pressure and responding with sympathy is the
    failure everyone ships: it answers impatience with more words, which is
    exactly backwards."* So the signals below reduce length, remove hedging and
    make the assistant act rather than ask. None of them makes it kinder.
    """
    out = dict(REGISTER_NEUTRAL)
    if persona_is_explicit:
        return out

    signals = set((reading or {}).get("signals") or ())
    confidence = float((reading or {}).get("confidence") or 0.0)
    pressure = bool(signals) and confidence >= REGISTER_MIN_CONFIDENCE

    # `P13-20`. A joke changes nothing until the association is learned, and the
    # `None` branch is the row's whole point rather than a fallthrough.
    if joking and humour in HUMOUR_MEANINGS:
        if humour == HUMOUR_RELAXED:
            out["humour"] = "welcome"
        else:
            # `defuse` and `wrapper` both mean the joke is not an invitation.
            # They differ in what else they imply: a wrapper says the complaint
            # underneath is real, which is the same instruction as pressure —
            # lead with the fix.
            out["humour"] = "avoid"
            pressure = True

    if pressure:
        out["length"] = "shorter"
        out["hedging"] = "none"
        out["clarify"] = "act"
    return out


def is_neutral(reg: Optional[Dict]) -> bool:
    """Whether this register asks for anything at all."""
    return dict(reg or REGISTER_NEUTRAL) == REGISTER_NEUTRAL


_REGISTER_LINES = {
    ("length", "shorter"): "Keep this reply shorter than usual.",
    ("hedging", "none"): "Skip the caveats and preamble; lead with the answer.",
    ("clarify", "act"): "Make the obvious call rather than asking a clarifying question.",
    ("humour", "welcome"): "A light touch is welcome.",
    ("humour", "avoid"): "Play it straight; no jokes.",
}

# The guard rides in the message itself rather than living only in this file's
# comments, because the model is the component that has to honour it. Two
# clauses, and they are the decision's two hard limits: delivery only, and no
# commentary on the person.
REGISTER_GUARD = (
    "This is about delivery only. It does not change any fact, qualifier or "
    "recommendation, and you must not mention it or comment on the user's "
    "state."
)


def register_text(reg: Optional[Dict]) -> str:
    """Render a register as the instruction the model receives. `P13-19`.

    Empty string for a neutral register, and the caller must treat that as
    *"add no message"* rather than *"add an empty one"*: a turn where the
    assistant should behave normally is a turn with nothing extra on the wire.

    **There was an `is_neutral()` guard here and mutation testing proved it
    could never change an answer**, because `REGISTER_NEUTRAL`'s values have no
    entry in `_REGISTER_LINES` — a neutral register produces no lines, and the
    `not lines` check below already returns. That is `P13-04`'s `due` verdict,
    `P13-14`'s `cutoff`, `P13-15`'s `sessions <= 1`, `P13-09`'s parse-site id
    check and `P13-05`'s redundant owner check, for the sixth time in this
    phase: **a branch that cannot distinguish itself from its own absence is
    not a control.** One reachable gate, and it is the one that stays correct
    when somebody adds a dial whose neutral value does have a line.
    """
    reg = dict(reg or REGISTER_NEUTRAL)
    lines = [_REGISTER_LINES[(key, value)] for key, value in reg.items()
             if (key, value) in _REGISTER_LINES]
    if not lines:
        return ""
    return "How to pitch this reply: " + " ".join(lines) + " " + REGISTER_GUARD
