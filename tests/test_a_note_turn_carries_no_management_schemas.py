# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1489` — a note, to-do or reminder turn does not pay for fifteen management
schemas.

The row (the remainder of `B1387`): `_detect_admin_intent` is true for *"add a
note to remind me to call the dentist"* (`_ADMIN_KEYWORDS` carries the note
words), so `_prompt_tool_names` added all fifteen `_ADMIN_PROMPT_FORCE_INCLUDE`
names though the domain seed already supplies `manage_notes`. Dropping the
keywords breaks the `Law 1` pin that *"open my notes file"* is an admin turn.

Measured on `ffaf6671` before the change, driven through the real loop with a
caller's narrow `relevant_tools`: the dentist turn's request carried
`manage_endpoints`, `manage_mcp`, `manage_tokens`, `pipeline` and the other
force-include names. The narrower rule (`agent_loop._only_note_words`): a turn
whose only request words are note words, none of them naming a file, is served
by the `notes_calendar_tasks` seed alone.

`Verify:` a turn whose only management word is a note word carries no
force-include name the domain seed did not add, and *"open my notes file"*
still offers `manage_documents`.
"""
import pytest

import src.agent_loop as al
from tests.test_a_first_message_is_not_a_lesser_message import _base, _drive

NARROW = {"web_search", "ask_user"}
NOTE_ONLY = [
    "add a note to remind me to call the dentist",
    "put milk on my todo list",
    "set a reminder for the dentist on friday",
    "show my notes",
]


@pytest.mark.parametrize("text", NOTE_ONLY)
def test_a_note_only_turn_carries_only_what_the_domain_seed_added(monkeypatch, text):
    # Still an admin turn: `Law 1`, and `_detect_admin_intent` did not move.
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is True
    _base(monkeypatch)
    sent = _drive(monkeypatch, message=text, relevant_tools=set(NARROW))
    tools = set(sent[0]["tools"])
    seeded = al._DOMAIN_TOOL_MAP["notes_calendar_tasks"]
    forced = tools & al._ADMIN_PROMPT_FORCE_INCLUDE
    assert forced <= seeded, (
        f"{text!r} carries management schemas the domain seed did not add: "
        f"{sorted(forced - seeded)}")
    assert "manage_notes" in tools, "the note tool is still the seed's"


@pytest.mark.parametrize("text", ["open my notes file", "open notes.md"])
def test_a_note_word_that_names_a_file_still_offers_the_document_tool(monkeypatch, text):
    """The reason the note words are in `_ADMIN_KEYWORDS` at all."""
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is True
    _base(monkeypatch)
    sent = _drive(monkeypatch, message=text, relevant_tools=set(NARROW))
    assert "manage_documents" in sent[0]["tools"], sent[0]["tools"]
    assert "manage_documents" in sent[0]["prompt"]


def test_a_note_word_beside_a_management_request_keeps_the_management_tools(monkeypatch):
    """The narrowing is for note-only turns. *"…and my sessions"* is a
    management request in its own right."""
    _base(monkeypatch)
    sent = _drive(monkeypatch, message="list my todos and my sessions",
                  relevant_tools=set(NARROW))
    assert "manage_session" in sent[0]["tools"], sent[0]["tools"]


def test_the_rule_reads_the_request_words_not_the_whole_sentence():
    """`_only_note_words` is the predicate the loop asks; these are its edges."""
    def only(text):
        return al._only_note_words([{"role": "user", "content": text}])

    assert only("add a note to remind me to call the dentist") is True
    assert only("open my notes file") is False          # names a file
    assert only("open notes.md") is False               # names a file
    assert only("list my todos and my sessions") is False
    assert only("archive this chat") is False
    assert only("the weather tomorrow") is False        # not an admin turn at all
