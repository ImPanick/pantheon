# SPDX-License-Identifier: AGPL-3.0-or-later
"""A name the turn can offer is a name the model can call.

The owner, 2026-10-14: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided."*

`fx9-proof` asked whether every tool reaches the model and `fx10-channel` asked
whether the fenced prompt names what the turn offers. **Neither could see this
defect**, and the reason is the denominator: both derive their inventory from
`FUNCTION_TOOL_SCHEMAS` (`tool_suite_probe.builtin_tool_names`), so a name with
no schema *and* no prose is outside the question they ask. Measured on
`747cda6` by driving the real loop and spying on `_assemble_prompt`: an admin's
ordinary turn handed the prompt builder **84** names, the request's array
carried **73**, the prompt named **79**, and **4** were in neither channel —
`builtin_browser`, `vault_get`, `vault_search`, `vault_unlock`.

So the question this file asks is the other one: **for every name the planner
may offer, is there a channel that carries a call for it?** Two channels, and
each is asked by driving the product rather than by comparing registers
(`Law 20`):

  * **native** — a `FUNCTION_TOOL_SCHEMAS` entry, so the name is in the
    request's `tools` array, *and* `function_call_to_tool_block` converts a
    call for it. A schema nothing routes is not a channel.
  * **fenced** — `_assemble_prompt(..., compact=False)` names it, *and*
    `parse_tool_blocks` routes a fence tagged with it. Prose advertising a
    fence the parser drops is not a channel either.

`neither` is the failure. `fenced_only` is **not** a failure here and the count
is reported instead: seven names are fenced-channel-only by a decision three
documents state (`P17-06`, `mcp_servers/email_server.py`'s `list_tools`,
`.pantheon/check-mcp-schemas.py` rule C), and overturning that decision is not
this file's business — `/work/notes/fx11-reach.md` carries the number and the
row.

`Law 1`: nothing here lifts a gate. The three vault tools keep every one of
their controls — `NON_ADMIN_BLOCKED_TOOLS`, their `NON_ADMIN_BLOCKED_REASONS`
sentences, `tool_capabilities`' effects, `agent_stops._CREDENTIAL_TOOLS`, their
dispatch arms and `require_admin` on `/api/vault/*` — and the cases below
assert that they do. What changed is that the planner no longer *offers* a name
the model cannot call.
"""
import asyncio
import json
import os

import pytest

from tests.helpers import tool_suite_probe as probe

#: The four names `known_tool_names()` holds and no channel carries, measured
#: on `747cda6`. Quoted so a reader can see what the invariant was built from;
#: **no assertion below is written against this list** — every one of them asks
#: the product's own registers, so a fifth name of the same shape fails them
#: with nobody editing this file (`Law 14`, `Law 20`).
MEASURED_ON_747CDA6 = ("builtin_browser", "vault_get", "vault_search", "vault_unlock")


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    return str(tmp_path_factory.mktemp("selectable"))


def _run(coro):
    return asyncio.run(coro)


# ── the invariant, over the product's own name lists ────────────────────────

def test_every_name_the_planner_may_offer_has_a_channel():
    """**The one assertion.** A selectable name with no channel fails this.

    The denominator is `src.tool_policy.selectable_tool_names()`, which is the
    planner's own candidate line; the channels are the real prompt builder and
    the real two converters. Red on `747cda6` with the four names above.
    """
    report = probe.channel_report(probe.offerable_names())
    assert report.neither == [], (
        "selectable and uncallable — the planner can offer these and the model "
        f"has no way to call them: {report.neither}")


def test_nothing_the_two_channels_advertise_is_unroutable():
    """The other direction, which the same report answers: a name the prompt
    or the array carries that neither converter will route. `Law 13` — the two
    halves of one channel have to agree."""
    report = probe.channel_report(probe.offerable_names())
    assert report.unroutable == [], report.unroutable


def test_the_selectable_register_is_the_routable_half_of_the_known_one():
    """`known_tool_names()` is unchanged, and that is deliberate (`Law 1`).

    Its own docstring says what it is for — *"prompt hiding and
    denylisting"* — and a denylist register must be **generous**: a name it
    misses is a name a guide-only turn fails to hide. An offer register must be
    **exact**: a name it over-counts is a name the model can never call. One
    function cannot hold both requirements, which is the `Law 10` finding here;
    `selectable_tool_names()` is the second, derived answer.
    """
    from src.tool_policy import known_tool_names, selectable_tool_names

    known = set(known_tool_names())
    selectable = set(selectable_tool_names())
    assert selectable < known, "the offer register must be a strict subset"
    # Nothing is invented: every selectable name is a known name.
    assert not (selectable - known)
    # And the difference is exactly the names nothing routes.
    from src.tool_schemas import dispatch_name_for
    assert sorted(known - selectable) == sorted(
        n for n in known if dispatch_name_for(n) is None)


def test_the_four_names_measured_on_the_base_are_the_difference():
    """`Law 6`: the count, before and after, from the same registers.

    This is the only case that mentions the four by name, and it mentions them
    as a **measurement of this tree**, not as the rule — the rule is the two
    cases above, which a fifth name of the same shape would redden.
    """
    from src.tool_policy import known_tool_names, selectable_tool_names

    assert sorted(set(known_tool_names()) - set(selectable_tool_names())) == sorted(
        MEASURED_ON_747CDA6)


def test_a_new_name_with_neither_channel_is_caught(monkeypatch):
    """The guard, not the four instances. A name added to the denylist register
    tomorrow with no schema and no fence tag is not selectable."""
    import src.tool_policy as tp

    real = tp.known_tool_names
    monkeypatch.setattr(tp, "known_tool_names",
                        lambda: set(real()) | {"definitely_not_a_pantheon_tool"})
    assert "definitely_not_a_pantheon_tool" not in tp.selectable_tool_names()
    assert "bash" in tp.selectable_tool_names()


# ── the routing rule, stated once and held equal to the converter ───────────

def test_the_routing_rule_agrees_with_the_converter_for_every_known_name():
    """`Law 7`. `dispatch_name_for` is the one statement of *"will anything
    route a call for this name"*, and `function_call_to_tool_block` is the
    converter that has to agree with it. Driven over every name in the
    register, with each tool's own minimal arguments so a refusal is never the
    probe's own omission."""
    from src.tool_policy import known_tool_names
    from src.tool_schemas import dispatch_name_for, function_call_to_tool_block

    for name in sorted(known_tool_names()):
        args = json.dumps(probe.minimal_args(name))
        block = function_call_to_tool_block(name, args)
        expected = dispatch_name_for(name)
        assert (block is None) == (expected is None), name
        if block is not None:
            assert block.tool_type == expected, (name, block.tool_type, expected)


def test_an_email_tool_still_routes_to_the_email_server():
    """`FORBIDDEN.md` Part 1: the 16 built-in email tool names, and the
    `mcp__{server_id}__{tool_name}` shape they dispatch as. Neither is
    rewritten by the rule being named."""
    from src.tool_security import BUILTIN_EMAIL_TOOLS
    from src.tool_schemas import dispatch_name_for

    assert len(BUILTIN_EMAIL_TOOLS) == 16
    for name in sorted(BUILTIN_EMAIL_TOOLS):
        assert dispatch_name_for(name) == f"mcp__email__{name}", name


def test_an_alias_dispatches_as_the_tool_it_aliases():
    """`_TOOL_NAME_MAP` is read, not bypassed: `read_research` is a name a
    model emits and `manage_research` is what runs."""
    from src.tool_schemas import dispatch_name_for

    assert dispatch_name_for("read_research") == "manage_research"
    assert dispatch_name_for("definitely_not_a_pantheon_tool") is None


def test_a_qualified_mcp_name_routes_whatever_server_it_names():
    """Part 1 again. Any `mcp__*` name converts — the manager answers whether
    the server is there, and that answer is a dispatch-time sentence rather
    than a silent drop."""
    from src.tool_schemas import dispatch_name_for

    assert dispatch_name_for("mcp__weather__lookup") == "mcp__weather__lookup"
    assert dispatch_name_for("mcp__builtin_browser__browser_navigate") == (
        "mcp__builtin_browser__browser_navigate")


# ── the four, one by one, with the reason each is not selectable ────────────

def test_builtin_browser_is_a_server_id_and_keeps_both_its_jobs():
    """`FORBIDDEN.md` Part 1 lists `builtin_browser` under *built-in MCP server
    ids*, not under tool names, and it has two jobs that this row must not
    break (`Law 1`): it is the word `manage_settings`/`ui_control` accept for
    *disable the browser* (`admin_tools._ALIASES["browser"]`), and it is the
    route-level intent marker `_expand_browser_mcp_tools` turns into the
    server's own qualified tool names. Both still work; what stopped is the
    bare id being offered to the model as if it were a tool."""
    import src.agent_loop as al
    from src.tool_policy import known_tool_names, selectable_tool_names

    assert "builtin_browser" in known_tool_names()
    assert "builtin_browser" not in selectable_tool_names()
    assert al._BROWSER_MCP_PREFIX == "mcp__builtin_browser__"

    class _Mgr:
        def get_all_tools(self):
            return [{"server_id": "builtin_browser", "is_disabled": False,
                     "qualified_name": "mcp__builtin_browser__browser_navigate"}]

    expanded = al._expand_browser_mcp_tools({"builtin_browser"}, _Mgr())
    assert "mcp__builtin_browser__browser_navigate" in expanded


def test_the_browser_toggle_still_knows_the_word():
    """The alias table is where `builtin_browser` earns its place in the
    denylist register, so it is read here rather than described."""
    import inspect

    from src.agent_tools import admin_tools

    source = inspect.getsource(admin_tools.do_manage_settings)
    assert '"browser": ["builtin_browser"]' in source


@pytest.mark.parametrize("tool", ["vault_get", "vault_search", "vault_unlock"])
def test_a_vault_tool_keeps_every_control_it_had(tool):
    """`FORBIDDEN.md` Part 2. Unselectable is not ungated: every control over
    the vault tools is asserted to be exactly where it was, so a later reader
    cannot mistake this row for a relaxation."""
    from src.agent_stops import _CREDENTIAL_TOOLS
    from src.tool_capabilities import TOOL_CAPABILITIES
    from src.tool_security import (NON_ADMIN_BLOCKED_REASONS,
                                   NON_ADMIN_BLOCKED_TOOLS,
                                   is_public_blocked_tool)

    assert tool in NON_ADMIN_BLOCKED_TOOLS
    assert NON_ADMIN_BLOCKED_REASONS[tool]
    assert is_public_blocked_tool(tool)
    assert tool in _CREDENTIAL_TOOLS
    assert tool in TOOL_CAPABILITIES


@pytest.mark.parametrize("tool", ["vault_get", "vault_search", "vault_unlock"])
def test_a_vault_tool_is_still_dispatchable_by_name(tool):
    """`Law 1` the other way: the dispatch arm is untouched, so a person's own
    automation, a workflow step that names it (`P22-16`) or an approved card
    still runs it. Only the *offer* was withdrawn."""
    import inspect

    from src import tool_execution

    assert f'tool == "{tool}"' in inspect.getsource(tool_execution)


def test_the_vault_routes_are_still_admin_only():
    """The vault's surface is Settings, and that is the premise this row rests
    on: `require_admin` on every `/api/vault/*` route."""
    import inspect

    from routes.vault import vault_routes

    source = inspect.getsource(vault_routes.setup_vault_routes)
    assert source.count("require_admin(request)") >= 5


def test_the_vault_was_already_out_of_the_retrieval_registry():
    """The evidence that this was a decision and not an oversight, read from
    the product: `BUILTIN_TOOL_DESCRIPTIONS` is the corpus retrieval embeds,
    the vault names are not in it, and `index_builtin_tools` actively prunes
    stale `builtin_*` rows naming *"removed tools like the old vault_* set"*."""
    import inspect

    from src import tool_index

    for name in ("vault_get", "vault_search", "vault_unlock"):
        assert name not in tool_index.BUILTIN_TOOL_DESCRIPTIONS
    assert "old vault_* set" in inspect.getsource(tool_index.ToolIndex.index_builtin_tools)


# ── question 4: the owner's own MCP tools ──────────────────────────────────

def test_a_built_in_servers_tools_are_not_offered_on_channels_that_skip_them(scratch):
    """`B-NEW-2` (agent:`fx11-reach`). `_suite_mcp_tools` reads
    `get_all_tools`, which keeps every server; the two channels read
    `get_all_openai_schemas` and `get_tool_descriptions_for_prompt`, which both
    skip a built-in Python server — so `mcp__email__*`, `mcp__rag__*` and
    `mcp__image_gen__*` were in the suite and in no channel, at **zero** cost
    to the window budget because the cost map comes from the schema call.

    Driven with a real stdio server registered under the built-in id `rag`,
    which is also `is_builtin`'s own documented hazard: *"an operator
    registering their own server under a stale id … would have had its tools
    hidden from both call channels with no error anywhere"*.
    """

    async def go():
        import sys

        import src.agent_loop as al
        from src.mcp_manager import McpManager

        root = os.path.join(scratch, "builtin-id")
        script = probe.write_mcp_server(os.path.join(root, "mcp"))
        mgr = McpManager()
        started = False
        for _ in range(4):
            try:
                if await mgr.connect_server("rag", "srv-rag", "stdio",
                                            command=sys.executable, args=[script],
                                            env={"PANTHEON_TOOL_SUITE_PROBE": "1"}):
                    started = True
                    break
            except BaseException:                       # noqa: BLE001
                pass
            await asyncio.sleep(0.4)
        if not started:
            pytest.skip("the probe's own MCP server would not start")
        try:
            names, costs, _by_server = al._suite_mcp_tools(mgr, {})
            schemas = {(s.get("function") or {}).get("name")
                       for s in (mgr.get_all_openai_schemas({}) or [])}
            prose = mgr.get_tool_descriptions_for_prompt({}, channel="both") or ""
            assert not mgr.reaches_model_channels("rag")
            # The suite must not carry a name neither channel carries.
            assert names == {n for n in names if n in schemas or n in prose}, names
            assert sorted(names) == sorted(costs), (
                "a name in the suite with no cost is a free offer")
        finally:
            await mgr.disconnect_all()

    _run(go())


def test_an_operator_registered_servers_tools_still_reach_both_channels(scratch):
    """The other half, and the one that must not regress: a server a person
    registered keeps its tools in the array **and** in the prompt block, under
    the protected `mcp__{server_id}__{tool_name}` spelling."""

    async def go():
        import src.agent_loop as al

        cell = probe.Cell(embeddings="down", mcp="up")
        async with probe.probe_world(os.path.join(scratch, "mcp-up"),
                                     mcp_states=("up",)) as world:
            mgr = world.manager(cell)
            assert mgr.reaches_model_channels("probe")
            names, costs, _by = al._suite_mcp_tools(mgr, {})
            assert names, "the probe's server serves two tools"
            schemas = {(s.get("function") or {}).get("name")
                       for s in (mgr.get_all_openai_schemas({}) or [])}
            prose = mgr.get_tool_descriptions_for_prompt({}, channel="both") or ""
            for name in sorted(names):
                assert name.startswith("mcp__probe__"), name
                assert name in schemas, name
                assert name in prose, name
                assert name in costs, name
            report = probe.channel_report(sorted(names), mcp_mgr=mgr)
            assert report.neither == [], report.neither

    _run(go())


# ── the same question through the real loop ────────────────────────────────

def test_an_ordinary_admin_turn_offers_nothing_it_cannot_carry(scratch):
    """The integration form, and the measurement the note's numbers come from.

    `effective` is the offer minus the names the route disabled **after** the
    plan was made — on `747cda6` that is `generate_image`, which the planner
    counted as a candidate and the route then hid, and which is `fx11-cap`'s
    row rather than this one. The assertion is about what is left: every name
    the prompt and the array were actually built from reached one of them.
    """

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent", window="large",
                          mode="chat", privilege="admin")
        async with probe.probe_world(os.path.join(scratch, "turn-admin"),
                                     mcp_states=("absent",)) as world:
            gap = await probe.offer_channel_gap(world, cell)
            assert gap.offered, "the turn offered nothing at all"
            assert gap.neither == [], (
                f"offered {len(gap.offered)}, array {len(gap.array)}, prompt "
                f"{len(gap.prompt_named)}, in neither channel: {gap.neither}")

    _run(go())


def test_an_ordinary_non_admin_turn_offers_nothing_it_cannot_carry(scratch):
    """The gates do the opposite of hiding the defect here: a non-admin's offer
    is a third of an admin's, and `builtin_browser` was in it on `747cda6`
    because no privilege gate names a server id."""

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent", window="large",
                          mode="chat", privilege="user")
        async with probe.probe_world(os.path.join(scratch, "turn-user"),
                                     mcp_states=("absent",)) as world:
            gap = await probe.offer_channel_gap(world, cell)
            assert gap.offered
            assert gap.neither == [], gap.neither

    _run(go())


def test_a_skill_opened_by_name_cannot_unlock_an_uncallable_tool(scratch):
    """A skill's `requires_toolsets` names join the turn's set after being
    checked against a register, and `known_tool_names()` was that register — so
    a skill declaring `requires_toolsets: [grep, vault_get]` put an uncallable
    name in the offer.

    Driven rather than grepped (`Law 20`): a real skill in the store, the model
    scripted to call `manage_skills action=view` for it, and the **next**
    round's offer read out of `_assemble_prompt`. `grep` arrives, `vault_get`
    does not.
    """

    async def go():
        import src.agent_loop as al
        from services.memory.skills import SkillsManager

        cell = probe.Cell(embeddings="down", mcp="absent", window="large",
                          mode="chat", privilege="admin")
        async with probe.probe_world(os.path.join(scratch, "skill-unlock"),
                                     mcp_states=("absent",)) as world:
            SkillsManager(world.data_dir).add_skill(
                name="probe-vault-reach",
                description="Open the vault and grep what it found.",
                category="general",
                when_to_use="Open the vault and grep what it found.",
                procedure=["Search the vault.", "Grep the result."],
                requires_toolsets=["grep", "vault_get"],
                status="published",
                source="user",
                owner=probe.ADMIN_USER,
            )
            rounds = []
            real = al._assemble_prompt

            def spy(tool_names, disabled_tools=None, compact=False, suite_notice=""):
                rounds.append(set(tool_names))
                return real(tool_names, disabled_tools, compact, suite_notice)

            al._assemble_prompt = spy
            try:
                record = await probe.drive_turn(
                    world, cell, "Follow the probe-vault-reach skill.",
                    script=[probe.reply_shapes(
                        "manage_skills",
                        {"action": "view", "name": "probe-vault-reach"})["native"],
                        "Done."],
                    max_rounds=3)
            finally:
                al._assemble_prompt = real
            assert ("manage_skills", '{"action": "view", "name": "probe-vault-reach"}'
                    ) in [(t, c) for t, c in record.dispatched], record.dispatched
            unlocked = set().union(*rounds) if rounds else set()
            assert "grep" in unlocked, "the skill's callable tool still arrives"
            assert "vault_get" not in unlocked, (
                "a skill unlocked a name no channel carries")

    _run(go())


# ── what is NOT closed here, with the number it costs ──────────────────────

def test_the_fenced_only_names_are_counted_and_named_by_their_registers():
    """`fenced_only` is reported, not asserted away. Seven names have a fence
    tag and no function schema, so on a native-tools route they are in no
    channel at all — which is the owner's *"intermittent"* arriving as *"which
    model did you pick"*. Five are the email drafting set (`P17-06`), one is
    `generate_image` (`.pantheon/check-mcp-schemas.py` rule C calls it *"the
    legitimate shape"*) and one is `manage_research`, which nothing explains.
    Filed as `B-NEW-3` (agent:`fx11-reach`); the count is pinned here so a
    silent eighth is a red test.
    """
    from src.agent_tools import TOOL_TAGS
    import src.agent_loop as al

    fenced_only = sorted(set(TOOL_TAGS) - set(al._schema_backed_tool_names()))
    assert fenced_only == [
        "ai_draft_email_reply", "download_attachment", "draft_email",
        "draft_email_reply", "generate_image", "manage_research", "search_emails",
    ], fenced_only
    report = probe.channel_report(probe.offerable_names())
    assert sorted(report.fenced_only) == fenced_only, report.fenced_only
