# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2027`. A page with a `<title>` of its own was saved under it, and lost it.

`create_document` takes its text in two shapes, and models mix them: lines
(the title, the language if it names one, the content) and a wrapper of
`<title>`, `<language>` and `<content>` elements, which the written call's
template in the prompt suggests with its `<title>`, `<language>` and
`<content>` lines. The tool searched the whole text for those elements and
then stripped every such tag from it. So an HTML page with a `<title>` of
its own, which is how the agent is told to make games and UIs, was saved
under the page's title, with the call's title and `html` as two lines above
`<!DOCTYPE html>` and the page's `<title>` element cut down to its text. An
SVG with a `<title>`, or a note that quotes the tag, went the same way, and
so did a call that gave the title and the language as elements and the page
after them with no `<content>` element.

Now the elements count only as a run at the start of the text, and what the
run does not give is read from the rest as lines. A line a model began with
a bare `<title>`, `<language>` or `<content>` label still counts as that
line, and a `<content>` that opens the rest is the wrapper's, closed or not.
Nothing inside the content is read as the wrapper or stripped from it.

A `<title>` or `<language>` element may set its tags out a line each, as
the search read them: what stands between the tags is the value when it is
one line with blank space around it, and a closing tag alone on the line
after a label's value closes it. A bare label's text runs on to the page's
own `</title>`, over many lines, so it is still read as a label. Each
element is one match where it starts and one search for its closing tag, so
the parse is linear. The search split a run of blank space after a
`<title>` every way it could before it gave up (`B1902`'s class): 2,000
spaces took 3.9 s, seven times as long as 1,000, and one pattern for a
one-line element, such as `[ \\t]*([^\\r\\n]*?)[ \\t]*</title>`, does the
same. The floods below run in a fresh interpreter
(`tests/helpers/timed_process.py`) against a 4 s budget.

Found while porting upstream Odysseus 218d7624, which mends only the
language half of this call (`B2026`).

Driven: the real tool on a real SQLite file
(`tests/test_an_uploaded_document_keeps_its_name.py`'s harness).
"""
from __future__ import annotations

import asyncio
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from src.agent_tools.document_tools import CreateDocumentTool, set_active_document
from src.tool_schemas import function_call_to_tool_block
from tests.helpers.timed_process import seconds_in_a_fresh_process
from tests.test_an_uploaded_document_keeps_its_name import _doc, env  # noqa: F401

PAGE = """<!DOCTYPE html>
<html>
<head>
<title>Snake</title>
</head>
<body><canvas id="board"></canvas></body>
</html>"""
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
       '<title>Logo mark</title><circle cx="4" cy="4" r="3"/></svg>')


@pytest.fixture(autouse=True)
def _no_document_left_open():
    yield
    set_active_document(None)


def _saved(env, text: str):
    """What the tool saves for `text`: the title, language and content."""
    out = asyncio.run(CreateDocumentTool().execute(text, {"session_id": "chat-1", "owner": None}))
    assert out.get("doc_id"), out
    doc = _doc(env, out["doc_id"])
    assert (out["title"], out["content"]) == (doc.title, doc.current_content)
    return doc.title, doc.language, doc.current_content


def test_an_html_page_is_saved_whole_under_the_calls_title(env):
    assert _saved(env, "Snake Game\nhtml\n" + PAGE) == ("Snake Game", "html", PAGE)


def test_a_native_call_for_a_page_is_saved_whole(env):
    block = function_call_to_tool_block("create_document", json.dumps(
        {"title": "Snake Game", "language": "html", "content": PAGE}))
    assert _saved(env, block.content) == ("Snake Game", "html", PAGE)


def test_an_svg_or_a_note_that_quotes_the_tag_keeps_it(env):
    assert _saved(env, "Logo\nsvg\n" + SVG) == ("Logo", "svg", SVG)
    note = "Put the page's name in <title>...</title>, inside <head>."
    assert _saved(env, "Notes\nmarkdown\n" + note) == ("Notes", "markdown", note)


def test_elements_for_the_title_and_language_and_then_the_page(env):
    assert _saved(env, "<title>Snake Game</title>\n<language>html</language>\n" + PAGE) == (
        "Snake Game", "html", PAGE)
    # A `<content>` that was never closed: the generation stopped, or the model left it.
    assert _saved(env, "<title>calc</title>\n<language>python</language>\n<content>\nprint(1)") == (
        "calc", "python", "print(1)")


def test_the_templates_label_lines_are_read_as_labels(env):
    """The prompt's template is a `<title>`, a `<language>` and a `<content>`
    line. A model that keeps them writes each value under its label."""
    text = "<title>\nSnake Game\n<language>\nhtml\n<content>\n" + PAGE
    assert _saved(env, text) == ("Snake Game", "html", PAGE)
    # A label with its value on its line: from it to the page's own
    # `</title>` is many lines, so it is no element.
    assert _saved(env, "<title>Snake Game\n<content>\n" + PAGE) == ("Snake Game", "html", PAGE)


def test_elements_with_each_tag_on_a_line_of_its_own_are_read_as_elements(env):
    """A model that sets the wrapper out puts each tag on a line of its own.
    The search before `B2027` read these elements, and a reading of only
    one-line elements saved the wrapper's tags into the document."""
    text = "<title>\nMy Title\n</title>\n<language>\npython\n</language>\n<content>\nprint('hi')\n</content>"
    assert _saved(env, text) == ("My Title", "python", "print('hi')")


def test_a_title_set_out_on_lines_of_its_own_leaves_no_tag_in_the_document(env):
    """The title alone set out, and the code after it. The search read the
    title here but kept it as the content's first line as well."""
    title, _sniffed, content = _saved(env, "<title>\nMy Title\n</title>\nprint('hi')")
    assert (title, content) == ("My Title", "print('hi')")


def test_a_language_set_out_under_the_title_line_leaves_no_tag_in_the_document(env):
    """Read as lines after a title line: the label, its value and the
    closing tag alone on the line after it."""
    assert _saved(env, "Plan\n<language>\nmarkdown\n</language>\n# Q3") == ("Plan", "markdown", "# Q3")


def test_what_was_read_right_before_is_read_the_same(env):
    wrapped = "<title>Snake Game</title>\n<language>html</language>\n<content>\n" + PAGE + "\n</content>"
    assert _saved(env, wrapped) == ("Snake Game", "html", PAGE)
    assert _saved(env, "<title>calc</title><language>python</language><content>print(1)</content>") == (
        "calc", "python", "print(1)")
    assert _saved(env, "Plan\nmarkdown\n# Q3\n\nthe agent's words") == (
        "Plan", "markdown", "# Q3\n\nthe agent's words")
    assert _saved(env, "Plan\nhtml\n<content>\n<p>hi</p>\n</content>") == ("Plan", "html", "<p>hi</p>")
    assert _saved(env, "<title>Plan\n<language>markdown\n<content># Q3") == ("Plan", "markdown", "# Q3")


_BUDGET_S = 4.0


@pytest.mark.parametrize("flood", [
    r"'<title>' + ' ' * 100_000",
    r"'<language>' + '\t' * 100_000 + 'x'",
    r"'<title>x' + ' ' * 100_000",
    r"'<title>' + ' \n' * 100_000 + 'x' + '\n\t' * 100_000 + '</title>' + '\n' * 100_000",
], ids=["spaces-after-a-tag", "tabs-then-a-letter", "a-value-then-spaces", "blank-lines-around-a-value"])
def test_a_flood_of_blank_space_in_the_wrapper_is_read_within_the_budget(flood):
    seconds = seconds_in_a_fresh_process(
        "import src.agent_tools\n"
        "from src.agent_tools.document_tools import _parse_create_document\n"
        f"text = {flood}",
        "_parse_create_document(text)",
    )
    assert seconds < _BUDGET_S, f"{flood}: {seconds:.1f} s"
