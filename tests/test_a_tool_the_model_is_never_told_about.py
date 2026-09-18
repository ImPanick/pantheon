# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-06` — being dispatchable and being offered are different properties.

The row asked for *"the rule that decides where a new capability goes"*, and
`.pantheon/check-tool-surface.py` answered half of it in 2026-09-10: whatever
shape you pick, here are the registers, and a name missing from one of them
fails silently. That half had shipped four times.

**The half nobody had a rule for is the other end.** Checks A–E prove a tool can
be *executed*. Nothing proved the model is ever *told the tool exists*. Measured
on this tree while closing the row: **five names** — `draft_email`,
`draft_email_reply`, `ai_draft_email_reply`, `search_emails`,
`download_attachment` — were in `TOOL_TAGS`, classified in `TOOL_CAPABILITIES`,
routed through `BUILTIN_EMAIL_TOOLS` to `mcp__email__*`, and served with full
descriptions by `mcp_servers/email_server.py`, and **no channel the model reads
named any of them**: no function schema (deliberate — fenced-channel only), no
`BUILTIN_TOOL_DESCRIPTIONS` entry so agent-mode retrieval could not surface
them, no keyword hint, no `_DOMAIN_TOOL_MAP` domain, no mention in the system
prompt, and built-in servers are skipped from
`get_tool_descriptions_for_prompt`.

Meanwhile `send_email`'s own schema, which the model does read, says *"for
normal assistant-written mail prefer `draft_email` so the user reviews it
first"*. That is `B66` with the sides swapped — there the prompt named a tool
the tags did not carry — and here the unreachable half was the one that shows
the user the mail before it goes.

These tests drive the registers and the selector, not the files.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

import src.agent_tools  # noqa: E402, F401 — the cycle, see mcp_servers/rag_server.py
from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS  # noqa: E402
from src.tool_index import ALWAYS_AVAILABLE, BUILTIN_TOOL_DESCRIPTIONS, ToolIndex  # noqa: E402
from src.tool_security import BUILTIN_EMAIL_TOOLS  # noqa: E402

# The five, named rather than derived: a derived list would go empty the day
# somebody deletes the descriptions, and this test would pass on the defect.
SILENT_FIVE = ("draft_email", "draft_email_reply", "ai_draft_email_reply",
               "search_emails", "download_attachment")


def _checker():
    spec = importlib.util.spec_from_file_location(
        "_check_tool_surface", ROOT / ".pantheon" / "check-tool-surface.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── the defect ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SILENT_FIVE)
def test_the_five_are_dispatchable_and_now_announced(name):
    """Both halves, because only the first was ever true."""
    assert name in TOOL_TAGS, "the fence parser would drop the block with no error"
    assert name in BUILTIN_EMAIL_TOOLS, "nothing would route it"
    assert name in BUILTIN_TOOL_DESCRIPTIONS, (
        f"{name} is dispatchable and agent-mode retrieval cannot surface it")
    assert len(BUILTIN_TOOL_DESCRIPTIONS[name]) > 80, (
        "an embedding corpus entry too short to distinguish this tool from its "
        "neighbours is an entry in name only")


def test_the_selector_reaches_the_draft_tools_without_embeddings():
    """The path that runs when there is no vector service reaches them too.

    An index description alone leaves them reachable only when ChromaDB is up.
    The keyword set calls itself the whole email toolset and was missing five of
    eighteen, so on the degraded path the agent could send mail and could not
    draft it — while being told to prefer the draft.
    """
    selected = ToolIndex.select_without_embeddings(
        "draft an email to sam about the invoice", set(ALWAYS_AVAILABLE))
    for name in SILENT_FIVE:
        assert name in selected, name
    assert "send_email" in selected, "the send path must not have been traded away"


def test_the_whole_email_family_is_one_set_not_a_subset():
    """`Law 13` in one assertion: the hint set covers every email tool.

    The defect was a list that named thirteen of eighteen and described itself
    as all of them. Derived from `BUILTIN_EMAIL_TOOLS` so a sixteenth email tool
    added tomorrow fails here rather than being quietly unreachable.
    """
    hinted = set()
    for keywords, tools in ToolIndex._KEYWORD_HINTS.items():
        if "email" in keywords:
            hinted |= tools
    assert set(BUILTIN_EMAIL_TOOLS) <= hinted, sorted(set(BUILTIN_EMAIL_TOOLS) - hinted)


# ── the rule, driven ─────────────────────────────────────────────────────────


def test_check_f_reports_a_tool_nothing_announces():
    """The rule fires on the input that broke, and not on the one that didn't."""
    checker = _checker()
    assert checker.unannounced(
        {"a", "b"}, schema_names={"a"}, descriptions={}, prompt_names=set()) == ["b"]
    # Any one channel is enough — that is the rule, not an accident of ordering.
    for channel in ("schema_names", "descriptions", "prompt_names"):
        kwargs = {"schema_names": set(), "descriptions": {}, "prompt_names": set()}
        kwargs[channel] = {"b"}
        assert checker.unannounced({"b"}, **kwargs) == []


def test_check_f_would_have_caught_the_five():
    """Against the real registers, minus the entries this row added."""
    checker = _checker()
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    schemas = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS
               if isinstance(s, dict) and "function" in s}
    before = {k: v for k, v in BUILTIN_TOOL_DESCRIPTIONS.items()
              if k not in SILENT_FIVE}
    # `prompt_names` is empty because the system prompt names none of the five,
    # which is itself the measurement.
    assert checker.unannounced(TOOL_TAGS, schemas, before, set()) == sorted(SILENT_FIVE)
    assert checker.unannounced(TOOL_TAGS, schemas, BUILTIN_TOOL_DESCRIPTIONS, set()) == []


def test_check_g_reports_one_name_with_two_live_implementations():
    """`B66`'s shape: a built-in server's tool that also has a native handler."""
    checker = _checker()
    assert checker.doubly_implemented({"rag": {"manage_rag"}},
                                      {"manage_rag": object()}) == [("rag", "manage_rag")]
    assert checker.doubly_implemented({"rag": {"manage_rag"}}, {"bash": object()}) == []
    # And it is clean on the real tree, which is the property being held.
    from src.builtin_mcp import _BUILTIN_SERVERS

    server_tools = {sid: checker._mcp_server_tool_names(rel)
                    for sid, (rel, _label) in _BUILTIN_SERVERS.items()}
    assert checker.doubly_implemented(server_tools, TOOL_HANDLERS) == []


def test_the_checker_passes_on_this_tree():
    """End to end, as CI runs it — the seven checks together, not the two."""
    result = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "check-tool-surface.py")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "announced to the model" in result.stdout, (
        "the summary line must report check F's figure, or a reader cannot tell "
        "whether it ran")


# ── the census the row asked for, re-measured ────────────────────────────────


def test_the_surface_is_three_shapes_and_the_rows_numbers_were_stale():
    """`P17-06` says "28 tools and 4 built-in MCP servers". Both are wrong.

    Not a nitpick: the row's framing — *native tool or MCP server* — is a
    two-way choice, and 28 was a count of classes in one directory. The
    dispatch-branch tools in `src/tool_execution.py` are neither, and there are
    more of them than there are classes. A contributor handed a two-way rule for
    a three-way surface picks by taste, which is what the row set out to fix.
    """
    import ast

    modules = sorted((ROOT / "src" / "agent_tools").glob("*.py"))
    classes = sum(len([n for n in ast.parse(p.read_text(encoding="utf-8")).body
                       if isinstance(n, ast.ClassDef)]) for p in modules)
    from src.builtin_mcp import _BUILTIN_SERVERS

    assert len(TOOL_TAGS) >= 80, "the surface is the tag set, not one directory"
    assert classes == 29 and len(modules) == 12, (classes, len(modules))
    assert len(_BUILTIN_SERVERS) == 3, "memory stopped being connected in B67"
    assert len(list((ROOT / "mcp_servers").glob("*_server.py"))) == 4, (
        "four server files, three of them connected — the row counted files")
