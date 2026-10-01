# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B996` — `manage_documents`' function schema offers `read`.

The tool handled `read` (aliases `view`/`open`/`get`, paged with `offset` and
`limit`), and the system prompt and `BUILTIN_TOOL_DESCRIPTIONS` told the model
to use it, but the function schema's `action` enum was `list, delete, tidy` plus
the folder actions and declared no `offset`. A model on the function-calling
channel that keeps to its schema — and some providers enforce an enum — could
list documents and never open one.

Driven, not read (`Law 20`): the schema is the object the loop hands the
provider; the call goes through `function_call_to_tool_block`, the function
that turns a native call into the block the dispatcher runs, then through
`execute_tool_block` against a real database.
"""

import asyncio
import json

import pytest

from tests.test_the_agent_files_documents import doc, lib  # noqa: F401

import core.database as cdb  # noqa: E402
from src.agent_tools.document_tools import FOLDER_ACTIONS  # noqa: E402
from src.tool_capabilities import ToolEffect, capabilities_for_action  # noqa: E402
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block  # noqa: E402
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block  # noqa: E402

#: Every action `ManageDocumentTool` answers under its own name. The aliases
#: (`view`, `open`, `get`, `reorganize`) are spellings the dispatcher forgives;
#: the schema offers each action once.
HANDLED = {"list", "read", "delete", "tidy"} | set(FOLDER_ACTIONS)


def _schema():
    return next(s["function"] for s in FUNCTION_TOOL_SCHEMAS
                if s["function"]["name"] == "manage_documents")


def test_the_schema_offers_read_and_its_paging():
    params = _schema()["parameters"]["properties"]
    assert "read" in params["action"]["enum"]
    assert params["offset"]["type"] == "integer"
    assert params["limit"]["type"] == "integer"
    assert "read" in params["document_id"]["description"]
    assert "read" in _schema()["description"]


def test_the_schema_offers_every_action_the_tool_answers_and_nothing_else():
    assert set(_schema()["parameters"]["properties"]["action"]["enum"]) == HANDLED


@pytest.mark.parametrize("action", sorted(HANDLED))
def test_every_offered_action_is_classified_rather_than_failing_high(action):
    """An action the approval card cannot classify is treated as the worst case
    (`_ambiguous_private_manager_action`); `read` must be a read."""
    effects = capabilities_for_action("manage_documents", json.dumps({"action": action})).effects
    if action in ("list", "read", "list_folders"):
        assert effects == frozenset({ToolEffect.READ_PRIVATE}), action
    else:
        assert ToolEffect.WRITE_PRIVATE in effects, action


def _native(args):
    """A function call exactly as a model following the schema would emit it."""
    block = function_call_to_tool_block("manage_documents", json.dumps(args))
    assert block is not None
    _desc, result = asyncio.run(execute_tool_block(
        block, session_id="chat-a", owner="alice", security_context=NO_TOOL_SECURITY_CONTEXT))
    return result


def test_a_model_keeping_to_its_schema_reads_a_document_page_by_page(lib):  # noqa: F811
    body = "".join(f"line {i:03d}\n" for i in range(60))
    db = lib()
    doc_id = doc(lib, "Long notes")
    db.query(cdb.Document).filter(cdb.Document.id == doc_id).update(
        {cdb.Document.current_content: body})
    db.commit()
    db.close()

    first = _native({"action": "read", "document_id": doc_id, "limit": 100})
    assert first["exit_code"] == 0, first
    page = first["document"]
    assert page["content"].startswith(body[:100]) and page["truncated"] is True
    assert body[100:110] not in page["content"]
    assert page["next_offset"] == 100
    nxt = _native({"action": "read", "document_id": doc_id, "offset": page["next_offset"],
                   "limit": 100})
    assert nxt["document"]["content"].startswith(body[100:200])
    assert nxt["document"]["offset"] == 100

    # Another person's document is not found, by this channel as by the other.
    bobs = doc(lib, "Bob's", owner="bob")
    refused = _native({"action": "read", "document_id": bobs})
    assert refused["exit_code"] == 1 and "not found" in refused["error"]
