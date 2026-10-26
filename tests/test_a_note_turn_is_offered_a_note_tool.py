# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1387`: a turn whose only management word is *note* is offered a note tool.

The row: `_ADMIN_KEYWORDS` carries `note`, `notes`, `todo`, `todos`,
`reminder` and `reminders`, and `_ADMIN_PROMPT_FORCE_INCLUDE` holds no note
tool, so *"add a note to remind me to call the dentist"* is an admin turn that
"still does not put a note tool in front of the model".

`Law 3`, measured from the loop (2026-10-26): the first half is true and the
second is not. The note keywords are exactly the words
`_classify_agent_request` maps to the `notes_calendar_tasks` domain, and the
loop seeds every detected domain's tools into the turn's set
(`stream_agent_loop`, *"If deterministic domain detection fired, seed the
corresponding domain tools"*) — including onto a caller's own narrow
`relevant_tools`. So every turn the note keywords make an admin turn already
carries `manage_notes` (and `manage_calendar`/`manage_tasks`) in the request.
The force-include set does not need a second copy of them.

The row's `Verify:` — *"a turn whose only management word is `note` either is
not an admin turn, or is one that puts a note tool in the request — asserted
from the loop, not from the keyword list"* — is these cases, and the last one
shows which mechanism carries the tool, so a change to it fails here.
"""
import pytest

import src.agent_loop as al
from src.tool_security import NON_ADMIN_BLOCKED_TOOLS
from tests.test_a_first_message_is_not_a_lesser_message import _base, _drive

NOTE_TURNS = [
    "add a note to remind me to call the dentist",
    "put milk on my todo list",
    "set a reminder for the dentist on friday",
    "open my notes file",
]
#: A caller's own narrow set: the case in which nothing but the loop's own
#: additions can bring a note tool in.
NARROW = {"web_search", "ask_user"}


@pytest.mark.parametrize("text", NOTE_TURNS)
def test_an_admin_turn_from_a_note_word_carries_a_note_tool(monkeypatch, text):
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is True, (
        "the note keywords stay admin words (`Law 1`; *open my notes file* is "
        "pinned as an admin turn)")
    _base(monkeypatch)
    sent = _drive(monkeypatch, message=text, relevant_tools=set(NARROW))
    assert "manage_notes" in sent[0]["tools"], (
        f"{text!r} is an admin turn and the request carries no note tool: "
        f"{sent[0]['tools']}")
    assert "manage_notes" in sent[0]["prompt"], "the prompt does not name it"


def test_a_non_admins_note_turn_is_not_handed_a_tool_their_cap_refuses(monkeypatch):
    """`Law 1` the other way: `manage_calendar` is in
    `NON_ADMIN_BLOCKED_TOOLS`, so the cap removes it from a non-admin's
    request; `manage_notes` is theirs to use."""
    assert "manage_calendar" in NON_ADMIN_BLOCKED_TOOLS
    _base(monkeypatch, blocked=NON_ADMIN_BLOCKED_TOOLS)
    sent = _drive(monkeypatch, message=NOTE_TURNS[0], relevant_tools=set(NARROW))
    assert "manage_calendar" not in sent[0]["tools"]
    assert "manage_notes" in sent[0]["tools"]


def test_the_note_tool_arrives_by_the_domain_seed(monkeypatch):
    """Which road the tool takes. Empty the notes domain's entry in
    `_DOMAIN_TOOL_MAP` and the note tool is gone from the same turn, so it is
    the domain seed — not `_ADMIN_PROMPT_FORCE_INCLUDE` — that answers the row,
    and a change to either is a change this file sees."""
    assert "manage_notes" not in al._ADMIN_PROMPT_FORCE_INCLUDE
    _base(monkeypatch)
    monkeypatch.setitem(al._DOMAIN_TOOL_MAP, "notes_calendar_tasks", set())
    sent = _drive(monkeypatch, message=NOTE_TURNS[0], relevant_tools=set(NARROW))
    assert "manage_notes" not in sent[0]["tools"]
