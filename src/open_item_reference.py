# SPDX-License-Identifier: AGPL-3.0-or-later
"""Does the person's message call on what is open beside the chat?

`B2140`. An editor document or an email reader can stay open while the person
asks about something else, and every turn sent the document's whole text (no
cap) or the email's header, an 1,800-character preview and about 2,500
characters of instructions. The owner's ruling of 2026-11-15: stored material
reaches the model only when the person attaches it or calls on it.

These readers answer one question from the person's own words: did they point
at the open item? "This document", "the draft", "rewrite it", "fix the intro",
"what does it say", "reply", the document's own title. A bare word such as
"change", "text" or "word" in an unrelated sentence ("change my calendar")
is not a reference any more.
"""
from __future__ import annotations

import re

# Nouns a person uses for an open piece of writing or a part of it.
_DOC_NOUNS = (
    r"document|doc|draft|text|poem|story|essay|outline|letter|paragraph|stanza|"
    r"verse|chapter|piece|writing|article|memo|script|wording|intro|introduction|"
    r"conclusion|title|heading|section|sentence|file|itinerary|table"
)

# Verbs that act on writing.
_EDIT_VERBS = (
    r"make|change|update|fix|edit|rewrite|rework|revise|replace|remove|delete|add|"
    r"append|insert|set|turn|write|draft|continue|finish|expand|shorten|tighten|"
    r"polish|improve|proofread|reword|translate|format|reformat|condense|cut|trim"
)

_PARTS = (
    r"day\s*\d+|row|rows|column|columns|table|section|chapter|part|paragraph|"
    r"paragraphs|line|lines|title|heading|body|intro|introduction|conclusion|"
    r"itinerary|draft|content|stanza|verse|sentence|sentences|bullet|bullets|"
    r"ending|opening|step|steps|point|points|item|items"
)

_POINTS_AT_OPEN = [
    # "this document", "the draft", "my essay", "the intro"
    re.compile(rf"\b(?:this|that|the|my|our|current|open|opened)\s+(?:{_DOC_NOUNS})s?\b"),
    # "what I gave you", "what's open", "on my screen"
    re.compile(
        r"\bwhat (?:i|i've|i have) (?:gave|given|sent|shared|opened|open|wrote|written|"
        r"have open|am looking at|'m looking at)\b"
        r"|\bwhat(?:'s| is) open\b|\bon (?:my|the) screen\b|\bin front of me\b"
        r"|\b(?:beside|next to) the chat\b|\bin the editor\b"
    ),
    # an action aimed at "it" / "this" / "that"
    re.compile(
        rf"\b(?:summari[sz]e|read|explain|translate|{_EDIT_VERBS}|review|check|"
        r"reply to|respond to|answer|forward|look at|go over|critique)\b"
        r"(?:\s+\w+){0,3}?\s+(?:it|this|that)\b"
        r"(?!\s+(?:the|a|an|i|you|we|they|he|she|is|was|it|there|my|your|our|his|her|works?)\b)"
    ),
    re.compile(r"\bwhat does (?:it|this|that) say\b|\btl;?dr\b|\bwhat(?:'s| is) (?:it|this) about\b"),
    # an edit aimed at a part: "fix the intro", "add another stanza", "day 3 change ..."
    re.compile(rf"\b(?:{_EDIT_VERBS})\b.{{0,80}}\b(?:{_PARTS})\b"),
    re.compile(rf"\b(?:{_PARTS})\b.{{0,80}}\b(?:{_EDIT_VERBS})\b"),
    # "add it there", "put this in it"
    re.compile(r"\b(?:add|insert|include|apply|put)\b.+\b(?:to it|to this|there|in it|in this|in the text)\b"),
    # "make it longer", "expand this"
    re.compile(
        r"\b(?:make|expand|extend|continue|shorten|lengthen|finish)\s+(?:it|this)\b"
    ),
    # feedback on it
    re.compile(
        rf"\b(?:feedback|suggestions?|thoughts|critique|notes|opinion)\b.{{0,30}}\b(?:on|for|about)\s+"
        rf"(?:(?:it|this|that)\b|(?:my|the|this)\s+(?:{_DOC_NOUNS})s?\b)"
    ),
    # a bare editing imperative: "proofread", "suggest improvements", "check the grammar"
    re.compile(
        r"^(?:please\s+|can you\s+|could you\s+|now\s+|ok(?:ay)?,?\s+)?"
        r"(?:suggest|proofread|polish|improve|tighten|shorten|lengthen|summari[sz]e|translate|"
        r"continue|finish|edit|revise|reword|rewrite|reformat|format|expand|condense|review|check)\b"
        r"(?:\s+(?:it|this|that|some|any|more|the\s+(?:grammar|spelling|tone|style|flow|wording))\b"
        r"|\s+(?:improvements?|changes|edits|suggestions|feedback|grammar|spelling)\b"
        r"|\s*(?:please)?\s*[.!?]*$)"
    ),
    re.compile(r"\b(?:all caps|uppercase|lowercase|title case)\b"),
]

# Words that, with an email open, are about that email.
_EMAIL_WORDS = re.compile(
    r"\b(?:e-?mails?|mail|reply|respond|response|forward|sender|"
    r"tell them|tell her|tell him|say (?:hi|thanks|yes|no)|thank them|thanks|ack|lmk|"
    r"unsubscribe|archive it|delete it|mark it)\b"
)

# Titles that say nothing about what the document is.
_GENERIC_TITLES = {
    "", "untitled", "untitled document", "new document", "document", "doc",
    "new email", "new mail", "new message", "draft", "notes", "note",
}


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def refers_to_open_item(text: object) -> bool:
    """The person's words point at something open beside the chat."""
    t = _clean(text)
    return bool(t) and any(p.search(t) for p in _POINTS_AT_OPEN)


def names_title(text: object, title: object) -> bool:
    """The person names the open document by its title."""
    t, ti = _clean(text), _clean(title)
    if ti in _GENERIC_TITLES or len(ti) < 4:
        return False
    stem = re.sub(r"\.[a-z0-9]{1,5}$", "", ti)
    return ti in t or (len(stem) >= 4 and stem in t)


def refers_to_open_email(text: object, subject: object = "", sender: object = "") -> bool:
    """With an email open in the reader, the person's words are about it."""
    t = _clean(text)
    if not t:
        return False
    if _EMAIL_WORDS.search(t) or refers_to_open_item(t):
        return True
    return names_title(t, subject) or names_title(t, sender)


def calls_for_writing(text: object) -> bool:
    """Words that may mean "write into the open document" ("write a poem").

    Used only where the document's size is not known yet (the route's Chat to
    Agent promotion), so a turn that may write into the open document still
    reaches the tools that can."""
    return bool(re.search(r"\b(?:write|draft|compose|create|add|put|insert|type|fill)\b", _clean(text)))
