# SPDX-License-Identifier: AGPL-3.0-or-later
"""The inventory test: every tool in the suite, offered and callable.

The owner, 2026-10-14, verbatim: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided. Ensure its capable of using
Pantheon's entire suite of tooling and skills etc."*

This file is the **inventory**, not a list. Every name it asks about comes from
a register the product itself reads — `src/tool_schemas.py`'s
`FUNCTION_TOOL_SCHEMAS`, a real `McpManager` holding a real stdio MCP server,
and `SkillsManager.index_for` — so **a tool added tomorrow is in these cases
with nobody editing this file**, which is the whole point. A hand-written list
would be a second register, and a second register goes stale the first time
somebody adds a tool (`Law 7`).

For every tool it asks two questions, and the second matters more: *a tool that
is offered and then cannot be called is the worse defect of the two.*

  1. **Does it reach the model?** Driven through `stream_agent_loop` — the
     product's one loop for Chat mode and Agent mode both — with the request
     recorded, and read back through `src/llm_core.py`'s own payload builders
     so the answer is given per provider shape: the OpenAI-compatible `tools`
     array, the Anthropic `input_schema` shape, the harmony-aliased surface,
     and the prompt itself, which is the only channel a fenced route has.
  2. **Can it be called?** The model emits a call in each of the five shapes a
     local server actually emits (`fx6-tools` measured them), and the loop has
     to parse it, build a `ToolBlock` for that tool and hand it to the
     dispatcher — or refuse it with one sentence a person can read.

Three verdicts, never a boolean (`Law 10`): `reached`, `held` (a named gate
withheld it, with the gate's own sentence — **a pass**, and `FORBIDDEN.md`
Part 2 is why), `missing` (every gate allowed it and it still did not reach the
model). `prompt_only` is a fourth: the prompt named it and the request's array
did not, which is the `Law 13` split the model complains about in the owner's
own export.

Nothing is stubbed but the model, and `Law 19` applies to the numbers: the
baseline table in `/work/notes/fx9-proof.md` is evidence about `0bd089d` and
nothing else. The configuration matrix is `scripts/tool-suite-matrix.py`; this
file runs the cells a test session can afford and keeps the invariants that
must hold in every cell.
"""
import asyncio
import json
import os

import pytest

from tests.helpers import tool_suite_probe as probe


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    return str(tmp_path_factory.mktemp("tool-suite"))


def _run(coro):
    return asyncio.run(coro)


# ── the inventory is derived, not written down ───────────────────────────────

def test_the_builtin_inventory_is_the_register_itself():
    """`FUNCTION_TOOL_SCHEMAS` is the source of truth, and the only one.

    74 on `0bd089d`. The assertion is not the number — a number in a test is
    the hand-written list this file exists to avoid — it is that the inventory
    and the register are the same set, so tool 75 is in the inventory on the
    commit that adds it.
    """
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    register = {(e.get("function") or {}).get("name") for e in FUNCTION_TOOL_SCHEMAS
                if e.get("type") == "function"}
    register.discard(None)
    assert set(probe.builtin_tool_names()) == register
    assert len(register) >= 74, "the register shrank; `Law 1` says add, never subtract"


def test_every_builtin_in_the_inventory_can_be_probed():
    """A probe turn and a minimal argument object exist for every name.

    Both are derived from the tool's own entry, so this is the guard that a new
    tool is genuinely covered rather than silently skipped: a name with no
    schema would produce an empty probe and pass by accident.
    """
    for tool in probe.builtin_tool_names():
        assert tool in probe.bare_naming_turn(tool)
        assert tool in probe.naming_turn(tool)
        args = probe.minimal_args(tool)
        assert isinstance(args, dict)


def test_a_required_argument_is_filled_from_the_tools_own_schema():
    """`web_search` needs a `query`, and the register is where that is written.

    `_REQUIRED_NATIVE_TOOL_ARGS` refuses a native call that omits it, so a
    probe sending `{}` would measure its own omission. Measured on `0bd089d`:
    with `{}`, `web_search` was dropped in three of the five reply shapes.
    """
    assert probe.minimal_args("web_search").get("query")
    assert probe.minimal_args("web_fetch").get("url")
    assert probe.minimal_args("read_file").get("path")
    # A tool whose schema requires nothing gets nothing invented for it.
    assert probe.minimal_args("get_workspace") == {}


def test_the_mcp_inventory_comes_from_the_manager_under_its_protected_name(scratch):
    """`FORBIDDEN.md` Part 1: `mcp__{server_id}__{tool_name}`, from a real server."""

    async def go():
        async with probe.probe_world(os.path.join(scratch, "mcp-names"),
                                     mcp_states=("up",)) as world:
            names = probe.mcp_tool_names(world.managers["up"])
            assert names == ["mcp__probe__probe_echo", "mcp__probe__probe_inventory"]
            for name in names:
                assert probe.split_name(name)

    _run(go())


def test_a_skill_in_the_store_either_reaches_the_index_or_names_its_blocker(scratch):
    """`index_for`, not `load()` — the list the loop injects (`P8-51`).

    A skill that is in the store and not in the index is either a defect or a
    gate, and the harness has to be able to say which. The only gate here is
    `requires_toolsets`: `_build_base_prompt` passes
    `set(TOOL_SECTIONS) - disabled`, so a skill requiring a tool with no
    prompt section is dropped. Measured on `0bd089d`: `probe-file-sweep`
    requires `ls` and `grep`, neither of which has a section, and it reaches
    nobody. That is filed as a defect; what this case keeps is that no skill
    disappears without the harness naming the reason.
    """

    async def go():
        async with probe.probe_world(os.path.join(scratch, "skill-names"),
                                     mcp_states=("absent",)) as world:
            names = probe.skill_names(world.data_dir, probe.ADMIN_USER)
            assert names, "the probe's own skills did not reach the store at all"
            for name, _cat, toolsets, _body in probe.PROBE_SKILLS:
                if name in names:
                    continue
                blockers = probe.skill_toolset_blocker(toolsets)
                assert blockers, (
                    f"{name} was written, is not in the index, and no gate "
                    f"accounts for it")

    _run(go())


def test_the_prompt_section_gate_on_a_skill_is_read_from_the_products_sets():
    """`tools_with_no_prompt_section` must be the two registers, not a list."""
    from src.agent_loop import TOOL_SECTIONS

    missing = probe.tools_with_no_prompt_section()
    assert set(missing) == set(probe.builtin_tool_names()) - set(TOOL_SECTIONS.keys())
    # If this ever becomes empty, every skill's declared toolset is nameable in
    # the prompt and the gate above cannot fire. That is the fix, not a failure.
    assert probe.skill_toolset_blocker(["read_file"]) == []


# ── question 1: reach, per provider shape ───────────────────────────────────

@pytest.mark.parametrize("mcp_state", ["up", "down", "absent"])
def test_the_whole_suite_is_either_offered_or_held_with_a_reason(scratch, mcp_state):
    """Every tool: `reached`, `held` with its gate's sentence, or a named gap.

    The assertion is not "nothing is missing" — on `0bd089d` plenty is, and the
    baseline table says how much. It is that **every** tool lands in one of the
    four verdicts and that a `held` verdict carries the gate and the sentence,
    because a tool withheld without a reason is indistinguishable from a tool
    lost, and that is the ambiguity `Law 10` is about.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp=mcp_state)
        async with probe.probe_world(os.path.join(scratch, f"reach-{mcp_state}"),
                                     mcp_states=(mcp_state,)) as world:
            inventory = probe.suite_inventory(world.manager(cell),
                                              data_dir=world.data_dir,
                                              owner=world.owner(cell))
            assert len(inventory.builtins) == len(probe.builtin_tool_names())
            rows = await probe.reach_report(world, cell, inventory)
            assert {r.tool for r in rows} == set(inventory.tools)
            for row in rows:
                assert row.verdict in probe.REACH_VERDICTS, row
                if row.verdict == "held":
                    assert row.gate and row.sentence, (
                        f"{row.tool} was withheld with no sentence a person can read")
                if row.verdict == "reached":
                    assert row.channels

    _run(go())


def test_a_tool_that_reaches_the_model_reaches_every_provider_shape(scratch):
    """One captured request, four shapes, one set of names.

    A tool in the OpenAI array has to survive the Anthropic conversion and the
    harmony aliasing, because those are the same request to a different
    provider. The harmony surface renames a colliding built-in on purpose
    (`_HARMONY_TOOL_ALIASES`), so the comparison allows exactly that rename and
    nothing else.
    """

    async def go():
        from src.llm_core import _HARMONY_TOOL_ALIASES

        cell = probe.Cell(embeddings="down", mcp="up")
        async with probe.probe_world(os.path.join(scratch, "shapes"),
                                     mcp_states=("up",)) as world:
            record = await probe.drive_turn(
                world, cell, "Search the web for the fastest route to Leeds.")
            shapes = record.shapes(cell.model)
            assert shapes["openai"], "the request carried no tools at all"
            assert shapes["anthropic"] == shapes["openai"], (
                "a tool reached the OpenAI array and not the Anthropic one")
            expected = sorted(_HARMONY_TOOL_ALIASES.get(n, n) for n in shapes["openai"])
            assert shapes["harmony"] == expected

    _run(go())


def test_a_registered_mcp_tool_reaches_the_model_in_every_shape(scratch):
    """The owner's sentence, in one case: *"even with its own MCP's provided."*"""

    async def go():
        cell = probe.Cell(embeddings="down", mcp="up")
        async with probe.probe_world(os.path.join(scratch, "mcp-reach"),
                                     mcp_states=("up",)) as world:
            name = "mcp__probe__probe_echo"
            record = await probe.drive_turn(world, cell, probe.bare_naming_turn(name))
            shapes = record.shapes(cell.model)
            for shape in ("openai", "anthropic", "harmony"):
                assert name in shapes[shape], f"the MCP tool is absent from {shape}"

    _run(go())


def test_a_down_mcp_server_does_not_cost_the_builtin_suite(scratch):
    """A server that is not answering must not subtract from what is offered.

    `fx6-tools`' `B-NEW-2` is the other direction (MCP tools dropped when
    retrieval could not see them). This is the control for it: a dead server is
    allowed to contribute nothing and not allowed to take anything away.
    """

    async def go():
        async with probe.probe_world(os.path.join(scratch, "down-cost"),
                                     mcp_states=("down", "absent")) as world:
            down = await probe.drive_turn(world, probe.Cell(embeddings="down", mcp="down"),
                                          probe.ORDINARY_TURN)
            none = await probe.drive_turn(world, probe.Cell(embeddings="down", mcp="absent"),
                                          probe.ORDINARY_TURN)
            assert down.offered() >= none.offered(), (
                f"a dead MCP server removed {sorted(none.offered() - down.offered())} "
                f"from the request")

    _run(go())


def test_a_skill_reaches_the_model_through_the_catalogue_the_loop_injects(scratch):
    """A skill is in the suite, so it gets the same question as a tool."""

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "skill-reach"),
                                     mcp_states=("absent",)) as world:
            inventory = probe.suite_inventory(world.manager(cell),
                                              data_dir=world.data_dir,
                                              owner=world.owner(cell))
            rows = await probe.skill_reach(world, cell, inventory)
            assert rows, "no skill was in the inventory, so nothing was asked"
            assert {r.tool for r in rows} == set(inventory.skills)
            for row in rows:
                assert row.verdict in ("reached", "missing")

    _run(go())


def test_a_fenced_route_has_only_the_prompt_so_the_prompt_is_measured(scratch):
    """An Ollama endpoint that has not declared `supports_tools` sends no array.

    `B39`'s measured policy, by URL and not by model name, which `fx6-tools`
    left exactly as it found it. On that route a tool reaches the model only if
    the prompt names it, so the harness measures the prompt as a channel in its
    own right.

    `tools_with_no_prompt_section()` is **not** a ceiling on that, and the
    first version of this case assumed it was. Measured: `api_call` and
    `manage_rag` have no `TOOL_SECTIONS` entry and are still backticked by the
    rules blocks, so a tool can be named in the prompt without having a section
    of its own. The two facts are separate — the missing section is what hides
    a skill that requires the tool (`index_for`'s `active_toolsets`), not what
    hides the tool.

    The assertion is the arithmetic, not the score: the route carries no array
    and every tool gets exactly one of the three verdicts. The score for
    `0bd089d` is in `/work/notes/fx9-proof.md`.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "fenced"),
                                     mcp_states=("absent",)) as world:
            inventory = probe.suite_inventory(world.manager(cell),
                                              data_dir=world.data_dir,
                                              owner=world.owner(cell))
            report = await probe.fenced_route_reach(world, cell, inventory)
            assert report.offered_array == 0, (
                "a route Pantheon treats as fenced still carried a tools array")
            buckets = [set(report.named_in_prompt), set(report.missing),
                       set(report.held)]
            assert set().union(*buckets) == set(inventory.tools)
            for i, left in enumerate(buckets):
                for right in buckets[i + 1:]:
                    assert left.isdisjoint(right), sorted(left & right)

    _run(go())


def test_the_inventory_separates_the_skills_stored_from_the_skills_indexed(scratch):
    """A skill in the store and not in the index reaches nobody.

    Reporting only `index_for` would hide it, so the inventory carries both and
    the gap is a number. Measured on `0bd089d`: four written, three indexed.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "skill-gap"),
                                     mcp_states=("absent",)) as world:
            inventory = probe.suite_inventory(world.manager(cell),
                                              data_dir=world.data_dir,
                                              owner=world.owner(cell))
            assert set(inventory.skills) <= set(inventory.skills_stored)
            for name in set(inventory.skills_stored) - set(inventory.skills):
                requires = next(t for n, _c, t, _b in probe.PROBE_SKILLS if n == name)
                assert probe.skill_toolset_blocker(requires), (
                    f"{name} is in the store, out of the index, and no gate "
                    f"accounts for it")

    _run(go())


# ── question 2: callable, in all five shapes a server emits ─────────────────

CALLABLE_SAMPLE = [
    "update_plan",          # a loop primitive: always available, always callable
    "ask_user",
    "manage_memory",
    "web_search",           # a required argument the register names
    "read_file",
    "bash",                 # driven to the dispatch boundary, never run
    "ls",
    "manage_skills",        # the door a skill is called through
    "mcp__probe__probe_echo",
]


def test_every_shape_a_server_emits_reaches_the_dispatcher(scratch):
    """The five shapes, driven through the loop's own readers.

    `native` is the OpenAI `tool_calls` channel; the other four are content,
    which is the only channel on a route that carries no array. A shape that
    parses for one tool and not another is the defect `fx6-tools` found twice
    (bare JSON worked only for `web_search`; a fenced MCP tag never matched).
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="up")
        async with probe.probe_world(os.path.join(scratch, "calls"),
                                     mcp_states=("up",)) as world:
            inventory = probe.suite_inventory(world.manager(cell),
                                              data_dir=world.data_dir,
                                              owner=world.owner(cell))
            rows = await probe.call_report(world, cell, inventory,
                                           names=CALLABLE_SAMPLE)
            dropped = [f"{r.tool}/{r.shape}: {r.detail}" for r in rows
                       if r.verdict == "dropped"]
            assert not dropped, "a call the model wrote reached nothing:\n" + "\n".join(dropped)
            assert {r.shape for r in rows} == set(probe.REPLY_SHAPES)
            for row in rows:
                assert row.verdict in probe.CALL_VERDICTS, row

    _run(go())


def test_ask_user_is_held_on_purpose_first_and_dispatches_after_a_tool(scratch):
    """The one tool whose call the loop declines by design, and why.

    `ask_user` as the **first** act of a turn, before anything has been looked
    at, is not dispatched: the loop replaces the block with an instruction to
    look first (`_MAX_ASK_FIRST_NUDGES`). That is a decision, not a drop, and
    the probe has to be able to tell the two apart — otherwise every future
    measurement of `ask_user` reads as a defect. After a tool has run, the same
    call dispatches.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "ask-user"),
                                     mcp_states=("absent",)) as world:
            ask = probe.reply_shapes("ask_user", probe.minimal_args("ask_user"))["native"]
            first = await probe.drive_turn(world, cell, "Decide what to do here.",
                                           script=[ask, "Done."], max_rounds=3)
            verdict, detail = probe._call_verdict(first, "ask_user")  # native: no echo
            assert verdict == "nudged", (verdict, detail)

            plan = probe.reply_shapes("update_plan",
                                      {"plan": "- [ ] look\n- [ ] ask"})["native"]
            after = await probe.drive_turn(world, cell, "Decide what to do here.",
                                           script=[plan, ask, "Done."], max_rounds=4)
            assert any(t == "ask_user" for t, _ in after.dispatched), after.dispatched

    _run(go())


def test_a_real_mcp_tool_call_goes_to_the_server_and_comes_back(scratch):
    """Not the boundary: the real dispatcher, the real server, the real reply.

    This is the half of the owner's report that a schema count cannot answer.
    `probe_echo` is read-only by construction, so it is one of the tools this
    suite drives for real.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="up")
        async with probe.probe_world(os.path.join(scratch, "mcp-call"),
                                     mcp_states=("up",)) as world:
            name = "mcp__probe__probe_echo"
            record = await probe.drive_turn(
                world, cell, probe.bare_naming_turn(name),
                script=[probe.reply_shapes(name, {"text": "hello"})["native"], "Done."],
                dispatch="real", max_rounds=3)
            assert any(t == name for t, _ in record.dispatched)
            outputs = [str(e.get("output") or "") for e in record.events
                       if e.get("type") == "tool_output"]
            assert any("probe_echo: hello" in o for o in outputs), outputs

    _run(go())


def test_a_tool_a_gate_holds_is_held_with_a_sentence_not_silence(scratch):
    """A held call is a **pass**, and the sentence is what makes it one.

    `FORBIDDEN.md` Part 2: nothing here lifts a control. What is checked is
    that the person is told. A non-admin's `bash` must not run, and must not
    vanish either.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent", privilege="user")
        async with probe.probe_world(os.path.join(scratch, "held"),
                                     mcp_states=("absent",)) as world:
            record = await probe.drive_turn(
                world, cell, "Run `bash` for me.",
                script=[probe.reply_shapes("bash", {"command": "true"})["native"], "Done."],
                dispatch="real", max_rounds=3)
            said = " ".join(
                str(e.get("output") or e.get("reason") or e.get("message") or "")
                for e in record.events
                if e.get("type") in ("tool_output", "tool_blocked"))
            assert said.strip(), "a non-admin's `bash` was refused in silence"
            # The control, stated so that standing the gate down reddens this
            # case rather than slipping past it: the answer has to say it was
            # refused and who may do it. Measured: with
            # `is_public_blocked_tool` forced False, the command RUNS and the
            # output is its own, which fails both halves.
            lowered = said.lower()
            assert "bash" in lowered, said[:200]
            assert any(word in lowered for word in
                       ("disabled", "restricted", "admin", "not available",
                        "requires")), said[:200]
            # Measured on `0bd089d`: the sentence a non-admin actually reads is
            # *"Tool 'bash' is disabled by the current request policy."* — the
            # loop's generic one, because `blocked_tools_for_owner` put the
            # name in `disabled_tools` before the dispatcher's own refusal,
            # which would have said *why*. Filed; what is kept here is that it
            # is a refusal naming the tool and the command did not run.
            assert "exit_code" not in lowered

    _run(go())


def test_the_two_loop_primitives_are_in_the_array_and_not_only_the_prompt(scratch):
    """`ask_user` and `update_plan` are in the `tools` array on every turn.

    `_build_base_prompt` force-includes both as the loop's irreducible
    primitives, so the prompt has always named them; fx6's `B-NEW-1` is the
    half where the schema filter did not, and a native-tools turn named two
    tools the request withheld (`Law 13`). Pinned directly rather than left to
    a mutation: taking them back out of `_tool_schemas_for_route`'s
    `schema_names` changes nothing measurable, because `ALWAYS_AVAILABLE`
    carries both into the selected set on every path — so the only way to keep
    this honest is to assert the array itself.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "primitives"),
                                     mcp_states=("absent",)) as world:
            for text in (probe.ORDINARY_TURN, "Tell me a joke.",
                         probe.SAMPLE_TURNS["owner"]):
                record = await probe.drive_turn(world, cell, text)
                if not record.requests:
                    continue          # the direct low-signal path: no array at all
                offered = record.offered()
                if not offered:
                    continue
                for name in ("ask_user", "update_plan"):
                    assert name in offered, (text[:40], sorted(offered))

    _run(go())


def test_a_call_to_a_name_nobody_registered_is_not_routed(scratch):
    """The control this lane must never stand down.

    A name the register does not know may be refused; it may not be dispatched.
    `function_call_to_tool_block` is where that is decided, and a harness that
    made an unknown name routable would make every other case meaningless.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent")
        async with probe.probe_world(os.path.join(scratch, "control"),
                                     mcp_states=("absent",)) as world:
            row = await probe.unknown_name_control(world, cell)
            assert row.verdict != "routed", row.detail
            assert "dispatched" not in row.detail
            assert row.verdict in probe.CALL_VERDICTS

    _run(go())


# ── the matrix's own arithmetic ─────────────────────────────────────────────

def test_the_matrix_is_the_five_axes_the_brief_names():
    """72 cells: embeddings x MCP x window x mode x privilege."""
    cells = probe.full_matrix()
    assert len(cells) == 72
    assert {c.embeddings for c in cells} == set(probe.EMBEDDINGS)
    assert {c.mcp for c in cells} == set(probe.MCP_STATES)
    assert {c.window for c in cells} == set(probe.WINDOWS)
    assert {c.mode for c in cells} == set(probe.MODES)
    assert {c.privilege for c in cells} == set(probe.PRIVILEGES)
    assert len({c.id for c in cells}) == 72


def test_a_cell_that_varies_across_its_own_repeats_is_reported_as_varying():
    """The owner's word is *intermittent*, so variance is the measurement.

    A cell whose offered set differs between two runs of the same turn is a
    finding even when every individual run looks fine, so the arithmetic that
    decides that is pinned rather than trusted.
    """
    steady = probe.CellResult(cell=probe.Cell(), suite=3, builtins=2, mcp=1, skills=0,
                              repeats=[["a", "b"], ["a", "b"], ["a", "b"]])
    assert steady.identical
    assert steady.drift == []
    jittery = probe.CellResult(cell=probe.Cell(), suite=3, builtins=2, mcp=1, skills=0,
                               repeats=[["a", "b"], ["a"], ["a", "b"]])
    assert not jittery.identical
    assert jittery.drift == ["b"]
    assert "NO" in probe.render_table([jittery])


def test_the_table_says_which_commit_it_is_evidence_about():
    """`Law 19`. A table with no commit is a claim about no tree."""
    sha = probe.commit_sha()
    assert sha and sha != "unknown"
    rendered = probe.render_summary([], seconds=1.0)
    assert sha.split()[0] in rendered


def test_the_window_axis_is_a_real_window_the_endpoint_reports(scratch):
    """The window comes from the endpoint, through `src/model_context.py`.

    `FIX-2026-10-14.md` puts the whole register at ~18,300 tokens, so `small`
    is a window the suite does not fit and `large` is one it fits twice over.
    On `0bd089d` the window does not narrow the `tools` array at all — it only
    trims messages — and that is a measurement this test makes available
    rather than an expectation it encodes.
    """
    from src.model_context import get_context_length_known

    async def go():
        async with probe.probe_world(os.path.join(scratch, "window"),
                                     mcp_states=("absent",)) as world:
            for window, model in probe.WINDOW_MODELS.items():
                ctx, known = get_context_length_known(world.endpoint.url, model)
                assert known, f"the probe endpoint did not report a window for {window}"
                assert ctx == probe.WINDOW_TOKENS[window]

    _run(go())


def test_the_gate_table_reads_the_products_own_sets():
    """`gate_holding` must not be a second copy of the privilege policy."""
    from src import tool_security as ts

    for tool in sorted(ts.NON_ADMIN_BLOCKED_TOOLS):
        gate = probe.gate_holding(tool, admin=False)
        assert gate is not None and gate.sentence, tool
        assert probe.gate_holding(tool, admin=True) is None, tool
    assert probe.gate_holding("mcp__probe__probe_echo", admin=False) is not None
    assert probe.gate_holding("mcp__probe__probe_echo", admin=True) is None
    off = probe.gate_holding("web_search", admin=True, features={"web_search": False})
    assert off is not None and off.name == "feature flag"
