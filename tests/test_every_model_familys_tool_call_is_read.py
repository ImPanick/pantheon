# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1727`. A tool call reaches the tools whichever model family wrote it.

The owner (2026-11-01): Qwen Coder 30B built a landing page "within a file
structure and referenced its own files numerous times but those files could
not be located", while Gemma made files that could be found — *"Ensure the
Tools/MCP/Skills etc are LLM agnostic — so that ALL LLMs can use them."*

Measured before this row: Qwen3-Coder's own call
`<tool_call><function=write_file><parameter=path>…` parsed to nothing and the
stripper removed it from the reply, so the call vanished without a file, a card
or an error. The same held for eight more families. A local server is meant to
turn each into structured `tool_calls`; when its template parser misses, the
text reaches Pantheon, and `tool_parsing._normalize_foreign_tool_markup` reads
it into the one Hermes shape the parser executes and the stripper hides.

`B1914`. Such a reply often shows a command in a fence as well ("to preview
it, run ```bash …```"), and the fence ran while the call was dropped. The
tests at the end pin that a call made outside every fence outranks the fences.
"""

import json
import time

import pytest

import src.agent_tools  # noqa: F401  (break agent_tools<->tool_parsing import cycle)
import src.tool_parsing as tool_parsing
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks

ARGS = {"path": "site/a.css", "content": "body{}"}
A = json.dumps(ARGS)

# Each family's text exactly as its chat template writes it.
FAMILIES = {
    "qwen3_coder": (
        "<tool_call>\n<function=write_file>\n<parameter=path>\nsite/a.css\n</parameter>\n"
        "<parameter=content>\nbody{}\n</parameter>\n</function>\n</tool_call>"
    ),
    "qwen3_coder_unwrapped": (
        "<function=write_file>\n<parameter=path>\nsite/a.css\n</parameter>\n"
        "<parameter=content>\nbody{}\n</parameter>\n</function>"
    ),
    "hermes": '<tool_call>\n{"name": "write_file", "arguments": %s}\n</tool_call>' % A,
    "hermes_with_parameters_key": '<tool_call>{"name": "write_file", "parameters": %s}</tool_call>' % A,
    "llama3_python_tag": '<|python_tag|>{"name": "write_file", "parameters": %s}<|eom_id|>' % A,
    "llama3_bare_reply": '{"name": "write_file", "parameters": %s}' % A,
    "mistral_v3": '[TOOL_CALLS] [{"name": "write_file", "arguments": %s}]' % A,
    "mistral_v11": "[TOOL_CALLS]write_file[ARGS]%s" % A,
    "mistral_v13_call_id": "[TOOL_CALLS]write_file[CALL_ID]a1b2c3d4e[ARGS]%s" % A,
    "glm_45": (
        "<tool_call>write_file\n<arg_key>path</arg_key>\n<arg_value>site/a.css</arg_value>\n"
        "<arg_key>content</arg_key>\n<arg_value>body{}</arg_value>\n</tool_call>"
    ),
    "gpt_oss_harmony": "<|channel|>commentary to=functions.write_file <|constrain|>json<|message|>%s<|call|>" % A,
    "kimi_k2": (
        "<|tool_calls_section_begin|><|tool_call_begin|>functions.write_file:0"
        "<|tool_call_argument_begin|>%s<|tool_call_end|><|tool_calls_section_end|>" % A
    ),
    "deepseek_v3": (
        "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>write_file\n"
        "```json\n%s\n```<｜tool▁call▁end｜><｜tool▁calls▁end｜>" % A
    ),
    "granite": '<|tool_call|>[{"name": "write_file", "arguments": %s}]' % A,
    "phi4_mini": '<|tool_call|>[{"name": "write_file", "arguments": %s}]<|/tool_call|>' % A,
    "phi4_functools": 'functools[{"name": "write_file", "arguments": %s}]' % A,
}


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_each_familys_call_becomes_the_same_tool_call(family):
    text = FAMILIES[family]
    blocks = parse_tool_blocks(text)
    assert [(b.tool_type, b.content) for b in blocks] == [("write_file", "site/a.css\nbody{}")], family
    # ...and none of the markup is left for the person to read.
    assert strip_tool_blocks(text) == "", (family, strip_tool_blocks(text))


def test_the_owners_case_every_file_of_a_site_is_written():
    """Qwen Coder writing a site in several calls, with prose between them."""
    reply = (
        "I'll set up the folders first.\n"
        "<tool_call>\n<function=bash>\n<parameter=command>\nmkdir -p site/css site/js\n"
        "</parameter>\n</function>\n</tool_call>\n"
        "Now the page and its manifest.\n"
        "<tool_call>\n<function=write_file>\n<parameter=path>\nsite/index.html\n</parameter>\n"
        "<parameter=content>\n<!DOCTYPE html>\n<link rel=\"stylesheet\" href=\"css/style.css\">\n"
        "</parameter>\n</function>\n</tool_call>\n"
        "<tool_call>\n<function=write_file>\n<parameter=path>\nsite/package.json\n</parameter>\n"
        "<parameter=content>\n{\"name\": \"game\", \"version\": 42}\n</parameter>\n</function>\n</tool_call>\n"
        "Done."
    )
    blocks = [(b.tool_type, b.content) for b in parse_tool_blocks(reply)]
    assert blocks == [
        ("bash", "mkdir -p site/css site/js"),
        ("write_file", 'site/index.html\n<!DOCTYPE html>\n<link rel="stylesheet" href="css/style.css">'),
        # A file whose content is JSON is written as those characters, not re-encoded.
        ("write_file", 'site/package.json\n{"name": "game", "version": 42}'),
    ]
    assert strip_tool_blocks(reply) == (
        "I'll set up the folders first.\n\nNow the page and its manifest.\n\nDone."
    )


def test_a_call_cut_off_by_its_stop_token_still_runs():
    text = "<tool_call>\n<function=write_file>\n<parameter=path>\na.txt\n</parameter>\n<parameter=content>\nhello"
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == [("write_file", "a.txt\nhello")]


def test_a_files_own_closing_tag_cannot_end_the_call_early():
    text = (
        "<tool_call>\n<function=write_file>\n<parameter=path>\nt.md\n</parameter>\n"
        "<parameter=content>\nuse </tool_call> here\n</parameter>\n</function>\n</tool_call>"
    )
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == [("write_file", "t.md\nuse </tool_call> here")]


def test_an_mcp_tool_is_reached_the_same_way():
    text = "<function=mcp__abc123__lookup>\n<parameter=ticket>\nPAN-7\n</parameter>\n</function>"
    blocks = parse_tool_blocks(text)
    assert [(b.tool_type, json.loads(b.content)) for b in blocks] == [("mcp__abc123__lookup", {"ticket": "PAN-7"})]


@pytest.mark.parametrize("prose", [
    'The format looks like {"name": "write_file", "parameters": {"path": "x"}} — use it like that.',
    "You can use functools.partial or functools [cache] for that.",
    "<|python_tag|>print('hi')",
    '{"name": "make_coffee", "parameters": {}}',
    "Mistral writes [TOOL_CALLS] before its calls.",
])
def test_prose_about_tools_stays_prose(prose):
    assert parse_tool_blocks(prose) == []
    assert strip_tool_blocks(prose) == prose.strip()


_BUDGET_S = 4.0


@pytest.mark.parametrize("flood", [
    "<function=a>" * 20000,
    "<function=a>" * 20000 + "</function>",
    "<function=a>" + "<parameter=x>" * 20000,
    "<tool_call>a<arg_key>" * 20000,
    "[TOOL_CALLS]a[ARGS]" * 20000,
    '[TOOL_CALLS] {"a"' * 20000,
    '[TOOL_CALLS] ["' + 'x[TOOL_CALLS] ["' * 20000,
    "to=functions.a " * 20000 + "<|message|>",
    "<|tool_call_begin|>" * 20000,
    "<|python_tag|>{" * 20000,
], ids=["qwen-openers", "qwen-closer-at-end", "qwen-params", "glm", "mistral-v11",
        "marker-json", "marker-string", "gpt-oss", "kimi", "python-tag"])
def test_a_flood_of_openers_is_read_in_linear_time(flood):
    start = time.perf_counter()
    parse_tool_blocks(flood)
    strip_tool_blocks(flood)
    assert time.perf_counter() - start < _BUDGET_S


# `B1914`. A reply that shows a fenced example and makes its call in explicit
# markup ran the example and dropped the call: the fences were read first and
# the markup only when no fence made a call. A call made outside every fence
# and inline code now outranks the fences, and the fences that did not run stay
# in the reply. The first two tests are upstream Odysseus 84aa9a91's.

def test_explicit_call_wins_over_an_illustrative_fence():
    text = (
        "Example:\n"
        "```bash\n"
        "echo example\n"
        "```\n"
        "Now execute:\n"
        '[TOOL_CALL]{tool => "shell", args => {--command "printf real"}}[/TOOL_CALL]'
    )
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == [("bash", "printf real")]


def test_mixed_parse_and_strip_leave_the_nonexecuted_fence_visible():
    text = (
        "Example:\n"
        "```bash\n"
        "echo example\n"
        "```\n"
        '[TOOL_CALL]{tool => "shell", args => {--command "printf real"}}[/TOOL_CALL]'
    )
    cleaned = strip_tool_blocks(text)
    assert "echo example" in cleaned
    assert "[TOOL_CALL]" not in cleaned
    assert "printf real" not in cleaned


def test_the_owners_site_is_written_when_the_reply_also_says_how_to_preview_it():
    """Qwen Coder writing the files, then showing the command that serves them.
    Before `B1914` the preview server started and neither file was written."""
    reply = (
        "I'll write the page and its stylesheet.\n"
        "<tool_call>\n<function=write_file>\n<parameter=path>\nsite/index.html\n</parameter>\n"
        "<parameter=content>\n<!DOCTYPE html>\n<link rel=\"stylesheet\" href=\"style.css\">\n"
        "</parameter>\n</function>\n</tool_call>\n"
        "<tool_call>\n<function=write_file>\n<parameter=path>\nsite/README.md\n</parameter>\n"
        "<parameter=content>\n# Site\n\nServe it with:\n\n```bash\npython3 -m http.server 8000\n```\n"
        "</parameter>\n</function>\n</tool_call>\n"
        "To preview it, run:\n```bash\ncd site && python3 -m http.server 8000\n```\n"
    )
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(reply)] == [
        ("write_file", 'site/index.html\n<!DOCTYPE html>\n<link rel="stylesheet" href="style.css">'),
        # The fence in the README is the README's.
        ("write_file", "site/README.md\n# Site\n\nServe it with:\n\n```bash\npython3 -m http.server 8000\n```"),
    ]
    assert strip_tool_blocks(reply) == (
        "I'll write the page and its stylesheet.\n\nTo preview it, run:\n"
        "```bash\ncd site && python3 -m http.server 8000\n```"
    )


def test_a_fence_in_a_files_content_is_written_and_not_run():
    """The fence inside an `<invoke>` call's content was read as a call of its
    own, so `npm start` ran and the README was never written."""
    text = (
        '<invoke name="write_file"><parameter name="path">README.md</parameter>'
        '<parameter name="content"># Site\n\nStart it with:\n\n```bash\nnpm start\n```\n</parameter></invoke>'
    )
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == [
        ("write_file", "README.md\n# Site\n\nStart it with:\n\n```bash\nnpm start\n```")]
    assert strip_tool_blocks(text) == ""


def test_only_a_call_outside_every_fence_outranks_the_fences():
    """Upstream reads the markup anywhere in the reply, so a ```write_file whose
    content is a fixture holding a call would run that call instead of writing
    the file. Markup inside a fence or inline code is what that fence holds:
    while there is any, the fences run as they always did, and so they do when
    the markup makes no call."""
    fixture = (
        "```write_file\ntests/fixture.txt\n"
        '<tool_call>{"name": "bash", "arguments": {"command": "rm -rf build"}}</tool_call>\n```'
    )
    written = [("write_file", 'tests/fixture.txt\n<tool_call>{"name": "bash", '
                              '"arguments": {"command": "rm -rf build"}}</tool_call>')]
    as_before = {
        fixture: written,
        # The fixture's call never runs, even beside one made outside it.
        fixture + '\nNow list it.\n<tool_call>{"name": "bash", "arguments": {"command": "ls build"}}</tool_call>':
            written,
        "```web_search\nwhat does [TOOL_CALL] mean in Mistral output\n```": [
            ("web_search", "what does [TOOL_CALL] mean in Mistral output")],
        'The format is `<tool_call>{"name": "bash", "arguments": {"command": "rm -rf ~"}}</tool_call>`.\n'
        "```bash\nls\n```": [("bash", "ls")],
        "I'll answer with a <tool_call> once I have looked.\n```bash\nls -la\n```": [("bash", "ls -la")],
    }
    for text, calls in as_before.items():
        assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == calls, text
    # And a fence beside a call made outside it is an example.
    text = (
        "For example, to start clean you could run:\n```bash\nrm -rf build\n```\n"
        'Let me look first.\n<tool_call>{"name": "bash", "arguments": {"command": "ls build"}}</tool_call>'
    )
    assert [(b.tool_type, b.content) for b in parse_tool_blocks(text)] == [("bash", "ls build")]
    assert "rm -rf build" in strip_tool_blocks(text)


_A_FENCED_CALL = "```bash\nls\n```\n"


@pytest.mark.parametrize("flood", [
    _A_FENCED_CALL + "<tool_call>" + "`x`" * 50_000,
    _A_FENCED_CALL + "<tool_call>`" + " " * 200_000,
    _A_FENCED_CALL + "<invoke```" + "<" * 100_000,
    _A_FENCED_CALL + "<tool_call>" + "</" * 100_000,
    _A_FENCED_CALL + "<tool_call>" * 20_000,
    _A_FENCED_CALL + '<invoke name="x">' * 20_000,
    _A_FENCED_CALL + "<" + " " * 200_000,
    (_A_FENCED_CALL + '<tool_call>{"name": "bash", "arguments": {"command": "pwd"}}</tool_call>\n') * 2_000,
], ids=["inline-code", "unclosed-inline-code", "unclosed-fence", "closer-starts", "openers",
        "invoke-openers", "a-bracket-then-spaces", "fences-and-calls"])
def test_a_fenced_call_beside_a_flood_of_markup_is_read_in_linear_time(flood):
    """Since `B1914` the markup of every reply with a fenced call is read too."""
    start = time.perf_counter()
    # The helper by its module: the tree before `B1914` has none, and fails here.
    tool_parsing._explicit_calls_outside_fences(flood)
    parse_tool_blocks(flood)
    strip_tool_blocks(flood)
    assert time.perf_counter() - start < _BUDGET_S
