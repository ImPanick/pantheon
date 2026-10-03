# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1100` — a `pantheon-qwen3` finetune running a workflow AI step is offered
only the step's own tools.

On that model a turn that reads as notes, a document or plain chat took one
of three fixed prompts (`_minimal_pantheon_notes_messages`, the doc prompt,
`_minimal_pantheon_general_messages`, each opening "You are Pantheon."), which
tell the model to use `manage_notes`, `manage_calendar`, `manage_tasks`, the
document tools, `manage_memory` and the email tools — and clamped the turn's
tools to them: the notes mode lifted its three managers out of the denylist
the step's list had built, and the general mode disabled every tool, the
step's own included. Every call outside the list was still refused (`P22-16`,
`test_an_ai_step_uses_only_its_tools`), but the model was told to use what it
may not, and on a general turn could not use what it may. The three modes now
stand down when a step names its tools: the step's list is the selection, and
the agent prompt offers exactly it.

What this does not change, measured and said (`Law 10`): the agent prompt's
base rules and the date context still mention `manage_memory`, `manage_notes`,
`manage_calendar` and `manage_tasks` in their guidance prose, for every model
on every turn, a step or not — filed as a new row in the handoff note.

Driven through the real loop with a scripted model (`Law 20`): what the model
was SENT, read off the one seam (`stream_llm_with_fallback`).
"""
import pytest

from src.tool_policy import ToolPolicy
from tests.test_an_ai_step_uses_only_its_tools import _base, _drive

QWEN = "pantheon-qwen3-notes"
STEP = {"web_search"}
# The tools the three fixed prompts tell the model to use, and the step's list
# does not hold.
OUTSIDE = ("manage_notes", "manage_calendar", "manage_tasks", "manage_memory",
           "list_email_accounts", "list_emails", "create_document", "edit_document",
           "update_document", "suggest_document")
FIXED_PROMPT = "You are Pantheon."      # how each of the three opens

TURNS = {
    "notes": "add a note: buy milk, and remind me tomorrow at nine",
    "document": "write a document about tide tables",
    "general": "look up this week's tide tables for Oslo and summarise them",
}


def _offered(system):
    """The tools a fenced prompt offers: its ```name sections."""
    return sorted(n for n in (*OUTSIDE, *STEP) if f"```{n}" in system)


@pytest.mark.parametrize("turn", sorted(TURNS))
def test_a_steps_list_is_what_the_finetune_is_offered(monkeypatch, turn):
    _base(monkeypatch, native=False)
    _events, sent = _drive(monkeypatch, ["Nothing to do."], message=TURNS[turn], model=QWEN,
                           policy=ToolPolicy(allowed_tools=STEP))
    system = sent[0]["system"]
    assert FIXED_PROMPT not in sent[0]["prompt"], f"a {turn} turn took a finetune's fixed prompt"
    assert _offered(system) == sorted(STEP), f"a {turn} turn on a step limited to web_search"


def test_a_notes_turns_managers_stay_refused(monkeypatch):
    """The notes mode no longer lifts its managers out of the step's denylist:
    a call to one is refused with the step's reason, before it runs."""
    _base(monkeypatch, native=False)
    executed = []
    events, _sent = _drive(monkeypatch, ['```manage_notes\n{"action": "add", "content": "milk"}\n```'],
                           message=TURNS["notes"], model=QWEN, executed=executed,
                           policy=ToolPolicy(allowed_tools=STEP))
    [blocked] = [e for e in events if e.get("type") == "tool_blocked"]
    assert blocked["reason"] == "“manage_notes” is not one of this step's tools."
    assert executed == []


def test_without_a_list_the_finetune_keeps_its_modes(monkeypatch):
    """`Law 1`, and the probe sees what it measures: the same turns with no
    step list still take the finetune's fixed prompts."""
    _base(monkeypatch, native=False)
    for turn in ("notes", "general"):
        _events, sent = _drive(monkeypatch, ["Nothing to do."], message=TURNS[turn], model=QWEN,
                               policy=ToolPolicy())
        assert FIXED_PROMPT in sent[0]["prompt"], turn
    _events, notes = _drive(monkeypatch, ["Nothing to do."], message=TURNS["notes"], model=QWEN,
                            policy=ToolPolicy())
    assert "Use manage_notes for notes" in notes[0]["system"]


def test_another_model_on_the_same_step_is_offered_the_same(monkeypatch):
    _base(monkeypatch, native=False)
    for turn in sorted(TURNS):
        _events, sent = _drive(monkeypatch, ["Nothing to do."], message=TURNS[turn], model="scripted",
                               policy=ToolPolicy(allowed_tools=STEP))
        assert _offered(sent[0]["system"]) == sorted(STEP), turn
