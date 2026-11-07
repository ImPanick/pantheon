# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1876` — a request that says "workflow", "automation", "automate" or
"Workbench", or describes one by its event ("when a document is created …"),
is offered the tool that drafts and runs workflows.

`draft_workflow` sits inside `manage_tasks`, and `manage_tasks` reached a turn
only through schedule words (`tool_index._KEYWORD_HINTS`, `_SCHEDULE_RE`, a
cadence after "every") or the notes/tasks domain's regex
(`agent_loop._classify_agent_request`). None of them knew the room's own name
("Automations"), the word "workflow", or an event phrased as a sentence; the
map's brief for `manage_tasks` said "scheduled jobs", so `find_tools
"automation"` found two email tools. **Measured on `5e4c8ec`** through the real
agent loop (the audit's probe, the harness of
`test_a_first_message_is_not_a_lesser_message.py`): `manage_tasks` was not
offered for "draft a workflow for me that summarises new mail", nor for the
drafter's own example "When a document is created, write a three-line summary
of it."; `select_without_embeddings` returned no `manage_tasks` for "make an
automation in the workbench", "run my bank-mail workflow now", "automate
posting my GitHub issues to chat"; `find_tool_matches("automation")` answered
`['reply_to_email', 'serve_model']`.

Now one pair of patterns (`tool_index.WORKFLOW_WORDS_RE`,
`WORKFLOW_EVENT_RE`) is asked by both the keyword selector and the domain
classifier (`Law 7`); the map says "scheduled jobs, automations and
workflows". A turn that says none of it is offered exactly what it was: the
cost lands on workflow turns only.
"""

import pytest

from src.tool_index import ToolIndex
from src.tools.system import find_tool_matches
from src.workflow_assist import EXAMPLE_SENTENCES
from tests.test_a_first_message_is_not_a_lesser_message import (
    ORDINARY_TURN, _base, _drive, _mcp_manager,
)

ASKED = (
    "Draft a workflow for me that summarises new mail.",
    "Make an automation in the Workbench.",
    "Run my bank-mail workflow now.",
    "Automate posting my GitHub issues to chat.",
    "Whenever a new invoice is added to my documents, total it up for me.",
    "List my automations.",
) + EXAMPLE_SENTENCES

NOT_ASKED = (
    ORDINARY_TURN,
    "What is the capital of France, and why is it there?",
    "When I was young we lived by the sea; tell me about tides.",
)


@pytest.mark.parametrize("text", ASKED)
def test_the_keyword_selector_offers_manage_tasks(text):
    assert "manage_tasks" in ToolIndex.select_without_embeddings(text, set())


@pytest.mark.parametrize("text", ASKED)
def test_the_first_message_through_the_real_loop_carries_manage_tasks(monkeypatch, text):
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=text, prompt_type="agent")
    assert "manage_tasks" in sent[0]["tools"], sent[0]["tools"]


@pytest.mark.parametrize("text", NOT_ASKED)
def test_a_turn_that_asks_for_none_of_it_is_offered_what_it_was(monkeypatch, text):
    assert "manage_tasks" not in ToolIndex.select_without_embeddings(text, set())
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=text, prompt_type="agent")
    assert "manage_tasks" not in sent[0]["tools"], sent[0]["tools"]


@pytest.mark.parametrize("query", ["automation", "workflow", "automate this", "workbench"])
def test_find_tools_finds_the_workflow_tool_by_the_rooms_words(query):
    found = [row["name"] for row in find_tool_matches(query, mcp_tools={})]
    assert found and found[0] == "manage_tasks", found


def test_the_map_names_workflows_beside_scheduled_jobs():
    from src.tool_map import brief
    assert brief("manage_tasks") == "scheduled jobs, automations and workflows"
