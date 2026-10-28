# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from tests.helpers.fresh_import import reimported_under_stubs

# This module needs the real agent-tool stack; importing it pulls in heavy
# DB/auth deps, so we stub those just long enough to import, then restore them.
# We deliberately do NOT pop src.tool_execution: popping and re-importing it
# rebinds the `src` package's `tool_execution` attribute, so a later
# `import src.tool_execution as te` resolves to a different module object than
# the one its functions live in - which silently breaks tests that monkeypatch
# it (e.g. test_edit_file's admin gate).
#
# `B1633`: and `src.agent_tools` is the same. The block here popped the three
# modules and imported them again by hand, put the stubs back, and left the
# second copies in `sys.modules` for the rest of the session — at collection,
# so before any test ran. A file collected earlier that had bound the first
# `src.agent_tools` then patched a `TOOL_HANDLERS` the dispatcher, importing at
# call time, never read: all three runs of
# `tests/test_a_hired_run_with_no_document_in_hand_writes_nothing.py` failed in
# the full suite with their spy never called. `reimported_under_stubs` (`B983`)
# is the one way this suite re-imports under stubs: the file keeps the copies
# it imported and everyone after it gets `sys.modules` back.
with reimported_under_stubs(
    pop=["src.agent_tools", "src.tool_parsing", "src.tool_schemas"],
    stub_if_absent=[
        "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext", "sqlalchemy.ext.declarative",
        "sqlalchemy.ext.hybrid", "sqlalchemy.sql", "sqlalchemy.sql.expression",
        "src.database", "core.models", "core.database", "core.auth",
    ],
):
    import src.agent_tools  # noqa: E402,F401
    from src.tool_schemas import function_call_to_tool_block  # noqa: E402


@pytest.mark.parametrize("arguments", [
    '["ls -la"]',   # JSON array
    '"ls -la"',     # bare JSON string
    '42',            # JSON number
    'true',          # JSON bool
    'null',          # JSON null
])
def test_non_object_arguments_do_not_crash(arguments):
    """A native function call whose arguments are valid JSON but not an object
    must not raise (it used to throw AttributeError: 'list' object has no
    attribute 'get', aborting the entire agent stream)."""
    block = function_call_to_tool_block("bash", arguments)
    # Coerced to empty args -> empty bash command, but importantly NO crash.
    assert block is not None
    assert block.tool_type == "bash"
    assert block.content == ""


@pytest.mark.parametrize("tool_name", ["list_emails", "mcp__email__list_emails"])
def test_email_mcp_non_object_arguments_are_rejected(tool_name):
    block = function_call_to_tool_block(tool_name, '["INBOX"]')

    assert block is None


def test_edit_document_skips_non_object_edit_items():
    block = function_call_to_tool_block(
        "edit_document",
        '{"edits": ["bad", 42, null, {"find": "old", "replace": "new"}]}',
    )

    assert block is not None
    assert block.tool_type == "edit_document"
    assert block.content == "<<<FIND>>>\nold\n<<<REPLACE>>>\nnew\n<<<END>>>"


def test_suggest_document_skips_non_object_suggestion_items():
    block = function_call_to_tool_block(
        "suggest_document",
        '{"suggestions": ["bad", 42, null, {"find": "old", "replace": "new", "reason": "clearer"}]}',
    )

    assert block is not None
    assert block.tool_type == "suggest_document"
    assert block.content == (
        "<<<FIND>>>\nold\n<<<SUGGEST>>>\nnew\n<<<REASON>>>\nclearer\n<<<END>>>"
    )


def test_ui_control_open_email_reply_preserves_structured_body():
    block = function_call_to_tool_block(
        "ui_control",
        '{"action":"open_email_reply","uid":"3228","folder":"INBOX","mode":"reply","body":"Hi Andy,\\n\\nNo thank you.\\n\\nBest,"}',
    )

    assert block is not None
    assert block.tool_type == "ui_control"
    assert block.content == "open_email_reply 3228 INBOX reply Hi Andy,\n\nNo thank you.\n\nBest,"
