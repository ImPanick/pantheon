# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2026`. A new document began with its language word.

`create_document` reads its text as lines: the title, then the language,
then the content, and it takes the second line as the language only when it
names one the editor has (python, html, markdown, ...). Every door that
writes that text for a model wrote the language as it came. A native call
with `language: "English"` (the language the text is in) or `"py"` was saved
with `English` or `py` as its first line, and the editor showed it: a Python
file that begins with `py` does not run. The same happened to a call leaked
into the model's text as raw JSON, to a written call whose second line was
`py`, and to the document made from a long code block the model left in the
chat, where only `py`, `js` and `ts` were mapped, so a ```sh or ```kotlin
block saved `sh` or `kotlin` above the code.

Now one rule reads the word (`normalize_document_language`). A short name is
the language of the file suffix it is, from the one register of those
(`src.document_processor.LANGUAGE_ALIASES`, `B100`), and a word the editor
has no language for is left out, so the tool works the language out from the
content, as it does when a call gives none. A written call keeps a second
line that names no language, which may be its text. A code block whose tag
names no editor language is saved as text, with the tag in its title.

Upstream Odysseus dropped `en`, `eng` and `english` in 218d7624 and gave the
schema a list of languages; the list is not taken, because the rule covers
every door without changing what providers and the small-model tool map are
sent.

Driven: the real conversions, the real tool on a real SQLite file
(`tests/test_an_uploaded_document_keeps_its_name.py`'s harness), and the real
agent loop with a scripted model.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from src.agent_tools.document_tools import CreateDocumentTool, set_active_document
from src.tool_parsing import parse_tool_blocks
from src.tool_schemas import function_call_to_tool_block
from tests.test_an_uploaded_document_keeps_its_name import _doc, env  # noqa: F401


@pytest.fixture(autouse=True)
def _no_document_left_open():
    yield
    set_active_document(None)


def _native(**args) -> str:
    """The text a native `create_document` call reaches the tool as."""
    return function_call_to_tool_block("create_document", json.dumps(args)).content


def _leaked(**args) -> str:
    """The same call, leaked into the model's text as raw JSON."""
    (block,) = parse_tool_blocks(json.dumps({"type": "function", "function": {
        "name": "create_document", "arguments": json.dumps(args)}}))
    assert block.tool_type == "create_document"
    return block.content


DOORS = pytest.mark.parametrize("convert", [_native, _leaked], ids=["native", "leaked"])


def _save(text: str):
    out = asyncio.run(CreateDocumentTool().execute(text, {"session_id": "chat-1", "owner": None}))
    assert out.get("doc_id"), out
    return out["doc_id"]


@DOORS
def test_a_language_the_editor_has_no_name_for_is_left_out(convert):
    for word in ("English", "en"):
        assert convert(title="Trip notes", language=word, content="Day 1: Paris") == (
            "Trip notes\nDay 1: Paris"), word


@DOORS
@pytest.mark.parametrize("word, language",
                         [("py", "python"), ("md", "markdown"), ("sh", "bash"), ("yml", "yaml")])
def test_a_short_name_is_written_as_its_language(convert, word, language):
    assert convert(title="calc", language=word, content="print(1)") == f"calc\n{language}\nprint(1)"


@DOORS
def test_an_editor_language_or_none_is_written_as_before(convert):
    assert convert(title="Plan", language="markdown", content="# Q3") == "Plan\nmarkdown\n# Q3"
    assert convert(title="Plan", content="# Q3") == "Plan\n# Q3"


def test_the_saved_document_begins_with_its_content(env):
    doc = _doc(env, _save(_native(title="Trip notes", language="English", content="Day 1: Paris")))
    assert (doc.title, doc.current_content) == ("Trip notes", "Day 1: Paris")
    doc = _doc(env, _save(_native(title="calc", language="py", content="print(1)")))
    assert (doc.title, doc.language, doc.current_content) == ("calc", "python", "print(1)")


def test_a_written_call_with_a_short_name_is_read_as_that_language(env):
    doc = _doc(env, _save("calc\npy\nprint(1)"))
    assert (doc.title, doc.language, doc.current_content) == ("calc", "python", "print(1)")
    doc = _doc(env, _save("<title>calc</title>\n<language>py</language>\n<content>\nprint(1)\n</content>"))
    assert (doc.title, doc.language, doc.current_content) == ("calc", "python", "print(1)")


def test_a_written_second_line_that_names_no_language_stays_in_the_text(env):
    """In a written call the second line may be the text itself, so only a
    language is taken out of it."""
    doc = _doc(env, _save("Trip notes\nEnglish breakfast at eight\nDay 1: Paris"))
    assert doc.current_content == "English breakfast at eight\nDay 1: Paris"
    doc = _doc(env, _save("Trip notes\nEnglish\nDay 1: Paris"))
    assert doc.current_content == "English\nDay 1: Paris"


# ── a long code block the model left in the chat ────────────────────────────

def _code_left_in_chat(monkeypatch, reply: str) -> list[str]:
    """Run one turn whose model answers `reply` and return the text of each
    document the loop made from it."""
    import src.agent_loop as agent_loop

    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    replies = iter([reply])

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    ran = []

    async def fake_execute(block, *args, **kwargs):
        ran.append(block)
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    async def turn():
        return [chunk async for chunk in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write me the script"}],
            max_rounds=2, owner="alice", session_id="b2026")]

    asyncio.run(turn())
    return [block.content for block in ran if block.tool_type == "create_document"]


SCRIPT = "\n".join(["set -e"] + [f"echo step {i}" for i in range(40)])


@pytest.mark.parametrize("tag, title, language", [
    ("sh", "Code (bash)", "bash"),
    ("kotlin", "Code (kotlin)", "text"),
    ("js", "Code (javascript)", "javascript"),
    ("", "Code (text)", "text"),
], ids=["sh", "kotlin", "js", "untagged"])
def test_a_long_code_block_becomes_a_document_whose_second_line_is_a_language(
        monkeypatch, tag, title, language):
    made = _code_left_in_chat(monkeypatch, f"Here it is:\n```{tag}\n{SCRIPT}\n```")
    assert made == [f"{title}\n{language}\n{SCRIPT}"]
