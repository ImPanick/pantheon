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
"""

import json
import time

import pytest

import src.agent_tools  # noqa: F401  (break agent_tools<->tool_parsing import cycle)
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
