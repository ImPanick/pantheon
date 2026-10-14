# SPDX-License-Identifier: AGPL-3.0-or-later
"""On a fenced route the prompt is the only channel, so it must name the offer.

MEASURED ON THE BASE (`b6a1bbf`) with `tool_suite_probe.fenced_route_reach` —
one turn per tool, the person naming the tool outright, against an Ollama URL
that carries no `tools` array (`B39`'s policy, by URL, which `fx6-tools`
deliberately left alone):

    FENCED admin: suite=79 named=68 held=1 missing=7 max_array=2
    FENCED user:  suite=76 named=29 held=45 missing=2 max_array=0

The seven an admin could reach by neither channel were
`edit_image`, `host_shell`, `list_cookbook_servers`, `ls`, `manage_bg_jobs`,
`scan_email_unsubscribes`, `unsubscribe_email` — and the cause is one line of
assembly: `_assemble_prompt`'s full (fenced) branch walks `TOOL_SECTIONS`,
which holds **61** entries for a **74**-name register, so fifteen tools that
the person's privileges allow, the suite planner offers and `TOOL_TAGS` can
carry had nothing in the prompt that named them. Eight of the fifteen were
backticked incidentally by rules prose; the other seven were not, and luck is
not a channel.

(The brief's numbers — 25 named, 50 missing — were measured on `0bd089d`,
before `fx9-suite` made the selected set the whole suite within a budget.
`Law 3`: re-measured here, the gap was 7, not 50.)

These cases drive the assembly and the parser (`Law 20`); none of them reads
the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.agent_loop as al  # noqa: E402
from src.agent_tools import TOOL_TAGS  # noqa: E402
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS  # noqa: E402
from tests.helpers.tool_suite_probe import prompt_tool_names  # noqa: E402

#: The seven the base measurement could reach by neither channel.
UNREACHABLE_ON_THE_BASE = (
    "edit_image", "host_shell", "list_cookbook_servers", "ls",
    "manage_bg_jobs", "scan_email_unsubscribes", "unsubscribe_email",
)


def _register_names():
    return sorted(
        (e.get("function") or {}).get("name") for e in FUNCTION_TOOL_SCHEMAS
        if (e.get("function") or {}).get("name")
    )


def _fenced_prompt(offered):
    """The prompt a fenced route gets for this offered set.

    `compact=False` is not a choice this test makes: `_compact_prompt_applies`
    is `is_api_model`, and a fenced route is `is_api_model = False` (`B39`).
    """
    return al._assemble_prompt(set(offered), set(), compact=False)


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------


def test_every_tool_the_turn_offers_is_named_in_the_fenced_prompt():
    """The whole finding. `missing=7` on the base."""
    names = _register_names()
    named = prompt_tool_names(_fenced_prompt(names))
    missing = sorted(n for n in names if n not in named)
    assert missing == [], missing


@pytest.mark.parametrize("tool", UNREACHABLE_ON_THE_BASE)
def test_a_tool_with_no_prompt_section_is_named_anyway(tool):
    """One case per name the base could not reach, so a regression says which."""
    assert tool not in al.TOOL_SECTIONS, (
        f"{tool} has a section now — this case is about the ones that do not")
    assert tool in prompt_tool_names(_fenced_prompt(_register_names()))


def test_the_line_is_the_registers_own_words_not_a_second_copy():
    """`Law 7`. The description and the argument names come from the schema the
    model is shown, so the prompt cannot drift from what the tool takes."""
    line = al._register_tool_line("host_shell")
    schema = next(e["function"] for e in FUNCTION_TOOL_SCHEMAS
                  if (e.get("function") or {}).get("name") == "host_shell")
    assert line.startswith("- ```host_shell```")
    assert schema["description"][:60] in line
    for arg in schema["parameters"]["properties"]:
        assert arg in line, arg
    # Required arguments are marked, because a JSON body missing one is the
    # commonest way a fenced call fails.
    assert "command*" in line


def test_the_prompt_still_does_not_name_a_tool_this_turn_withholds():
    """`B1304`'s rule holds: the new lines are for the OFFERED set only."""
    offered = {"ask_user", "update_plan", "ls", "read_file"}
    named = prompt_tool_names(_fenced_prompt(offered))
    assert "ls" in named
    for withheld in ("host_shell", "edit_image", "unsubscribe_email",
                     "manage_bg_jobs", "list_cookbook_servers"):
        assert withheld not in named, withheld


def test_a_disabled_tool_gets_no_line_of_its_own():
    """The privilege and feature gates are upstream and stay upstream.

    Asserted as *no usage line*, not as *the name appears nowhere*: the rule
    pruner's documented rule is per LINE — *"Prefer `grep`, `glob`, and `ls`
    over shell equivalents when available"* survives on `grep` and `glob`, and
    rewriting prose is not something a filter can do honestly (`B1311`).
    What this row controls is whether the tool is advertised as callable.
    """
    prompt = al._assemble_prompt(set(_register_names()), {"host_shell", "ls"},
                                 compact=False)
    assert "- ```host_shell```" not in prompt
    assert "- ```ls```" not in prompt
    assert "- ```edit_image```" in prompt


def test_the_fenced_prompt_only_names_what_the_fence_can_carry(monkeypatch, caplog):
    """`H09`'s guard, pointed the other way: there a compact-prompt name needs a
    schema, here a fenced-prompt name needs a `TOOL_TAGS` entry — otherwise the
    prompt advertises a call the parser will not read."""
    monkeypatch.setattr(al, "TOOL_TAGS", TOOL_TAGS - {"host_shell"})
    with caplog.at_level("WARNING"):
        named = prompt_tool_names(_fenced_prompt(_register_names()))
    assert "host_shell" not in named
    assert any("host_shell" in rec.getMessage() for rec in caplog.records), \
        "an offered tool with no fence tag must be loud, not silent"


#: The five email tools with a fence tag, no function schema and no prompt
#: section. `mcp_servers/email_server.py` says of them that Pantheon "reaches
#: them through the fenced channel, which takes no schema" — measured on the
#: base, the fenced channel named eleven of the sixteen email tools and not
#: these five.
FENCED_ONLY_EMAIL_TOOLS = (
    "ai_draft_email_reply", "download_attachment", "draft_email",
    "draft_email_reply", "search_emails",
)


@pytest.mark.parametrize("tool", FENCED_ONLY_EMAIL_TOOLS)
def test_a_fenced_only_email_tool_is_named_too(tool):
    """No schema to derive from, so the line comes from the register agent-mode
    retrieval already embeds (`src/tool_index.BUILTIN_TOOL_DESCRIPTIONS`) —
    not from new prose written here (`Law 7`)."""
    from src.tool_policy import known_tool_names
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS

    line = al._register_tool_line(tool)
    assert line.startswith(f"- ```{tool}```"), line
    assert BUILTIN_TOOL_DESCRIPTIONS[tool][:50] in line
    assert tool in prompt_tool_names(_fenced_prompt(set(known_tool_names())))


def test_every_name_the_fence_can_carry_is_nameable():
    """`TOOL_TAGS` is the set `parse_tool_blocks` will route. Offer all of it
    and the prompt names all of it — otherwise the two halves of one channel
    disagree (`Law 13`)."""
    from src.tool_policy import known_tool_names

    named = prompt_tool_names(_fenced_prompt(set(known_tool_names())))
    assert sorted(n for n in TOOL_TAGS if n not in named) == []


def test_an_operators_own_words_win_here_too(monkeypatch):
    """`_section_text` already honours `builtin_tool_overrides` for a sectioned
    tool; a section-less one is not a second policy."""
    monkeypatch.setattr(al, "get_builtin_overrides",
                        lambda: {"ls": "List a directory. Mine, not the register's."})
    line = al._register_tool_line("ls")
    assert "Mine, not the register's." in line
    assert "```ls```" in line


# ---------------------------------------------------------------------------
# Offered means callable: the five shapes `fx6-tools` made parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", UNREACHABLE_ON_THE_BASE)
def test_the_fence_the_prompt_advertises_actually_parses(tool):
    """A tool the prompt now names has to be callable on the channel it names.

    The body is the JSON object the line advertises — `function_call_to_tool_block`
    converts a native call for these tools to `json.dumps(args)`, so the fenced
    body is the same shape by construction.
    """
    from src.agent_tools import parse_tool_blocks

    reply = f"Here you go.\n\n```{tool}\n{{}}\n```\n"
    blocks = parse_tool_blocks(reply)
    assert [b.tool_type for b in blocks] == [tool], blocks


@pytest.mark.parametrize("tool", UNREACHABLE_ON_THE_BASE)
def test_every_shape_a_local_server_emits_still_carries_these_names(tool):
    """`fx6-tools`' five shapes, asked of the seven names this row adds to the
    prompt — a prompt promise with no parser behind it is `Law 13`."""
    from tests.helpers.tool_suite_probe import reply_shapes
    from src.agent_loop import function_call_to_tool_block, parse_tool_blocks

    shapes = reply_shapes(tool, {})
    carried = {}
    for shape, payload in shapes.items():
        if shape == "native":
            call = payload["calls"][0]
            block = function_call_to_tool_block(call["name"], call["arguments"])
            carried[shape] = block is not None
            continue
        carried[shape] = bool(parse_tool_blocks(payload))
    assert all(carried.values()), carried


# ---------------------------------------------------------------------------
# `Law 1` — nothing that worked stops working
# ---------------------------------------------------------------------------


def test_the_full_prompt_fallback_is_byte_identical():
    """`AGENT_SYSTEM_PROMPT` is assembled at import from `TOOL_SECTIONS` alone,
    which is the retrieval-unavailable fallback. It must not move."""
    assert al.AGENT_SYSTEM_PROMPT == al._assemble_prompt(set(al.TOOL_SECTIONS))


def test_a_sectioned_tool_still_gets_its_own_block():
    prompt = _fenced_prompt(_register_names())
    assert "```read_file\n<file path>\n```" in prompt
    assert prompt.count("- ```manage_memory```") == 1


def test_the_suite_budget_charges_the_new_lines():
    """`Law 10`. A line the prompt pays for on every turn is a line the suite
    planner has to count, or the budget under-charges exactly where this row
    added prose."""
    costs = al._suite_prompt_token_costs()
    for tool in UNREACHABLE_ON_THE_BASE:
        assert costs.get(tool, 0) > 0, tool
    for name in al.TOOL_SECTIONS:
        assert costs.get(name, 0) > 0, name


def test_a_name_no_register_describes_gets_no_line(monkeypatch):
    """Asserted directly because no mutation can reach it: measured on this
    tree, `TOOL_TAGS` and `src/tool_index.BUILTIN_TOOL_DESCRIPTIONS` hold the
    same 81 names, so today every fence-taggable tool has a description. The
    guard is for the day one does not — a selector's set is not a licence to
    invent a tool."""
    import src.tool_index as ti

    monkeypatch.setattr(ti, "BUILTIN_TOOL_DESCRIPTIONS", {})
    assert al._register_tool_line("draft_email") == ""
    # A tool with a schema is unaffected: it never reaches the fallback.
    assert al._register_tool_line("ls").startswith("- ```ls```")


def test_an_mcp_tool_is_not_given_a_builtin_line():
    """MCP tools have their own block, built by the manager from the server's
    own words (`get_tool_descriptions_for_prompt`). One home each (`Law 7`)."""
    assert al._register_tool_line("mcp__srv__probe_echo") == ""
    assert al._register_tool_line("definitely_not_a_pantheon_tool") == ""
    prompt = _fenced_prompt(set(_register_names()) | {"mcp__srv__probe_echo"})
    assert "mcp__srv__probe_echo" not in prompt
