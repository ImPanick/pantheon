# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1902`. Two of the tool parser's patterns took seconds on one model reply.

Every reply on the agent path goes through `parse_tool_blocks` and
`strip_tool_blocks`, synchronously, on the server's one event loop, and two of
their patterns were super-linear in the reply's length:

  * **the plain `ui_control open_panel …` rescue** (Pattern 7) was
    `^\\s*(?:`{1,3})?\\s*ui_control … \\s*(?:`{1,3})?\\s*$` under `(?im)`,
    searched over the whole reply: `^` tried every line start and the two
    `\\s*` around the optional backticks split a run of blank lines every
    possible way. Measured on `62c93ba2`: 1,500 newlines took 13.5 s to parse
    and 13.6 s again to strip, and 1,000 lines of a space took 17.6 s (cubic);
  * **the Gemma wrapper** (Pattern 4b) was one lazy pattern that rescanned to
    the end of the reply from every `<|tool_call|>call:x{` opener: 4,000 of them
    with no closer took 6.4 s (quadratic).

A local model's runaway blank-line output is enough, and so is text a prompt
injection asks for. Now the rescue is tried once per `ui_control` in the reply,
with a pattern that matches exactly what the old one matched, and the Gemma
wrapper is read by the forward-only scanner the other delimited patterns use.

Two halves, as `tests/test_redos_llm_parsers.py` pins its fixes:

  * **the same answer**: the old patterns are copied in below, and the new code
    must find and strip, span for span, what they did, on the inputs the
    behaviour tests pin and on thousands of seeded random strings;
  * **linear time**: each flood is 100,000 characters or more and runs in a
    fresh interpreter (`tests/helpers/timed_process.py`), timed after its
    imports, against a 4 s budget. The new code takes well under a second on
    each; the old code is still running when the process is killed.

The Gemma split is upstream Odysseus da3800b6's. Its plain-UI helper changed
what a reply with a fenced command saves, so the rescue here is Pantheon's own.
"""

import random
import re

import pytest

import src.agent_tools  # noqa: F401  (break agent_tools<->tool_parsing import cycle)
# The module, not its helpers: on the tree before `B1902` the helpers are not
# there, and the floods below must still run there, and fail.
import src.tool_parsing as tool_parsing
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks
from tests.helpers.timed_process import seconds_in_a_fresh_process

# The two patterns as they were before `B1902`, character for character.
_OLD_PLAIN_UI = re.compile(
    r"(?im)^\s*(?:`{1,3})?\s*ui_control\s+open_panel\s+"
    r"(documents?|library|gallery|images?|email|inbox|mail|sessions?|chats?|history|"
    r"notes?|brain|memor(?:y|ies)|skills?|settings|preferences|cookbook|models?)"
    r"\s*(?:`{1,3})?\s*$"
)
_OLD_GEMMA = re.compile(
    r"<\|?tool_call\|?>\s*call:([\w\d_-]+)\s*(\{[\s\S]*?\})\s*<\|?tool_call\|?>",
    re.IGNORECASE,
)

_BUDGET_S = 4.0

# The inputs `tests/test_plain_ui_control_open_panel.py` pins, and replies a
# model really writes around the command.
_PLAIN_UI_PINNED = [
    "ui_control open_panel notes",
    "``ui_control open_panel cookbook```",
    "I'll open it now.\nui_control open_panel notes",
    "ui_control switch_model gemma4:31b",
    "bash ls",
    "Sure:\n```\nui_control open_panel gallery\n```\nThere you go.",
    "```bash\nls\n```\nui_control open_panel email",
    "Text\n````\nui_control open_panel chats\n````",
    "   ui_control   open_panel   inbox   ",
    "UI_CONTROL OPEN_PANEL Memories",
    "x ui_control open_panel notes",
    "ui_control open_panel notes\n\n\nThen the gallery:\nui_control open_panel gallery\n",
    "\n\n  `ui_control open_panel settings`  \n\nDone.",
    "ui_control open_panel notesX\nui_control open_panel notes",
]

_PLAIN_UI_TOKENS = [
    ["ui_control open_panel notes", "UI_CONTROL  open_panel Gallery", "ui_control open_panel x",
     "`", "```", "````", " ", "\t", "\n", "\n\n", "x", "ui_control", "open_panel", "notes", "\r"],
    ["ui_control open_panel notes", "ui_control\topen_panel\nmemories", "UI_CONTROL open_panel settings ",
     "`", "``", "```", "````", " ", "\t", "\n", "\r\n", " \n", "\n ", "x", "s", "ui_control", "\x85"],
]


def _random_texts(token_sets, seed, count, longest):
    texts = []
    for offset, tokens in enumerate(token_sets):
        rng = random.Random(seed + offset)
        texts += ["".join(rng.choices(tokens, k=rng.randint(0, longest))) for _ in range(count)]
    return texts


def test_the_panel_rescue_finds_and_strips_what_it_always_did():
    for text in _PLAIN_UI_PINNED + _random_texts(_PLAIN_UI_TOKENS, 1902, 10_000, 14):
        old = list(_OLD_PLAIN_UI.finditer(text))
        new = list(tool_parsing._iter_plain_ui_open_panel(text))
        assert [(m.span(), m.group(1)) for m in new] == [(m.span(), m.group(1)) for m in old], repr(text)
        assert tool_parsing._strip_plain_ui_open_panel(text) == _OLD_PLAIN_UI.sub("", text), repr(text)
    # Through the entry points: the first command is the one that runs, and a
    # fenced command goes from the saved reply with its fence, as it always did.
    reply = "UI_CONTROL OPEN_PANEL Memories\nui_control open_panel notes"
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(reply)] == [
        ("ui_control", "open_panel memories")]
    assert strip_tool_blocks("Sure:\n```\nui_control open_panel gallery\n```\nThere you go.") == (
        "Sure:\n\nThere you go.")


_GEMMA_PINNED = [
    "ordinary prose", "<|tool_call|>call:web_search{query: 'news'}<|tool_call|>",
    "before<tool_call> call:read-file {\npath: 'README.md'\n} <tool_call>after",
    "<tool_call>call:x{a}<tool_call>call:y{b}<tool_call>",
    "<tool_call>call:x{<tool_call>call:y{b}<tool_call>",
    "<tool_call>call:x{unclosed", "}<tool_call><tool_call>call:x{unclosed",
    "<|TOOL_CALL|>call:web_search {\"query\": \"a}b\"} \n <tool_call|> and after",
]

_GEMMA_TOKENS = [
    ["<|tool_call|>", "<tool_call>", "<|tool_call>", "call:", "call:web_search", "x", "{", "}",
     " ", "\n", "a", "-"],
]


def test_the_gemma_wrapper_reads_and_strips_what_it_always_did():
    # Upstream's cases (da3800b6), and random strings over the wrapper's tokens.
    opener, closer = tool_parsing._GEMMA_TOOL_CALL_OPEN_RE, tool_parsing._GEMMA_TOOL_CALL_CLOSE_RE
    for text in _GEMMA_PINNED + _random_texts(_GEMMA_TOKENS, 1902, 6000, 16):
        new = [(name, "{" + body + "}") for name, body in tool_parsing._iter_named_blocks(text, opener, closer)]
        assert new == _OLD_GEMMA.findall(text), repr(text)
        assert tool_parsing._strip_delimited(text, opener, closer) == _OLD_GEMMA.sub("", text), repr(text)
    raw = '<|tool_call|>call:web_search{"query":"news"}<|tool_call|>'
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(raw)] == [("web_search", "news")]
    assert strip_tool_blocks(raw) == ""


@pytest.mark.parametrize("flood", [
    r"'\n' * 100_000",
    r"' \n' * 100_000",
    r"'\n' * 100_000 + 'ui_control x'",
    r"' ' * 100_000 + 'Xui_control open_panel notes'",
    r"'ui_control open_panel notes' + ' ' * 100_000 + 'X'",
    r"'<|tool_call|>call:x{' * 20_000",
], ids=["blank-lines", "space-lines", "blank-lines-then-a-near-miss", "spaces-then-a-mid-line-command",
        "a-command-then-spaces", "gemma-openers"])
def test_a_flood_is_parsed_and_stripped_within_the_budget(flood):
    seconds = seconds_in_a_fresh_process(
        "import src.agent_tools\n"
        "from src.tool_parsing import parse_tool_blocks, strip_tool_blocks\n"
        f"text = {flood}",
        "parse_tool_blocks(text)\nstrip_tool_blocks(text)",
    )
    assert seconds < _BUDGET_S, f"{flood}: {seconds:.1f} s"
