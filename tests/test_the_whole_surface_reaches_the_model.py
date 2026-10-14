# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner's report, as a property over the whole surface rather than a census.

Twice now, in the same words: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided. Ensure its capable of using
Pantheon's entire suite of tooling and skills etc.."* The first answer was the
`fx9`–`fx11` wave, which measured a **curated inventory of 77 tool names** and
reported 76/77. The second report is the argument against that method: a census
cannot find a name its author did not think to list, and six of the names it
did list were reachable on one channel only — `selectable_tool_names()` was 81
while `FUNCTION_TOOL_SCHEMAS` held 75, and nothing asserted those two numbers
against each other.

So the denominator here is never written down. Every case asks the product for
its own surface and then asserts a property of **all** of it, which is what
makes a name added tomorrow covered with nobody editing this file (`Law 14`,
`Law 20`). `D-2026-10-14-01` is the ruling these properties encode.

The engine is `tests/helpers/tool_suite_probe.channel_report`, which answers
"which channel carries this name" by building the real prompt and converting a
real call through `parse_tool_blocks` and `function_call_to_tool_block` — not by
comparing two registers, which is the comparison that passed while a converter
refused the name.

What lives elsewhere, deliberately, so this file holds the whole-surface
property and not a second copy of each part:

  * per-name routing equality — `test_a_selectable_tool_is_a_callable_tool.py`
  * a built-in server's tools skipped by both channels (`B1355`) — the same file
  * the eight-register rule, as CI runs it — `.pantheon/check-tool-surface.py`,
    driven by `test_a_tool_the_model_is_never_told_about.py`
  * the skills half, end to end — `test_the_whole_skill_suite_reaches_the_model.py`
"""

from __future__ import annotations

import glob
import os
import re

import pytest

from tests.helpers import tool_suite_probe as probe

#: The one name `known_tool_names()` carries that no channel should: a **server
#: id**, not a tool. `FORBIDDEN.md` Part 1 lists it under *built-in MCP server
#: ids*; it is the word the browser toggle accepts and the marker
#: `_expand_browser_mcp_tools` turns into that server's real qualified tool
#: names. There is nothing for a channel to carry, so it is exempt — and the
#: exemption is written here, once, with its reason, rather than being a quiet
#: subtraction inside an assertion.
NOT_A_TOOL = frozenset({"builtin_browser"})


@pytest.fixture(scope="module")
def report():
    return probe.channel_report(probe.offerable_names())


# ── the headline property ──────────────────────────────────────────────────


def test_every_offerable_name_is_on_both_channels(report):
    """`B1357` / `D-2026-10-14-01` §1, as the property rather than the count.

    A name the turn may offer has to be callable however the person's model
    talks: through the request's `tools` array on a native-tools route, and
    through the fenced prompt on a local one. A name on one channel only is the
    owner's *"intermittent"* in its exact mechanism — it works or not depending
    on which model was picked, which is not a thing a person can be expected to
    reason about.

    Measured before the ruling: six names were `fenced_only` — five email
    drafting tools and `generate_image` — and three more were in neither
    channel while still sitting in four registers.
    """
    assert report.of("fenced_only") == [], (
        "offered on the fenced prompt only, so a native-tools route cannot "
        f"call them: {report.of('fenced_only')}")
    assert report.of("native_only") == [], (
        "offered in the request array only, so a fenced route cannot call "
        f"them: {report.of('native_only')}")
    assert report.of("neither") == [], (
        f"offered and callable on no channel at all: {report.of('neither')}")
    # Said positively, so the case cannot pass on an empty report.
    assert report.rows, "the probe offered nothing — this would assert nothing"
    assert report.of("both") == sorted(r.name for r in report.rows)


def test_nothing_the_model_is_shown_is_unroutable(report):
    """The other direction: advertised and nothing will route it.

    `unroutable` is the probe's own reading of *the prompt or the array names
    it and `dispatch_name_for` returns `None`* — the shape that answered a call
    with *"The model returned an empty response. Please try again or switch to
    a different model."*
    """
    assert report.unroutable == [], report.unroutable


# ── the registers behind it, each as a property ────────────────────────────


def test_every_tagged_tool_is_announced_somewhere_the_model_can_see():
    """Check F's rule, held as a test rather than only in CI.

    A tool can be dispatchable and still be one *"the model is never told
    about"*: no schema, no retrieval description, unnamed in the prompt. That
    shipped four times before the checker existed, and `B1357` was the fifth —
    announced in the prompt, missing from the array.
    """
    from src.agent_tools import TOOL_TAGS
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    schemas = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS
               if isinstance(s, dict) and "function" in s}
    announced = schemas | set(BUILTIN_TOOL_DESCRIPTIONS)
    silent = sorted(set(TOOL_TAGS) - announced)
    assert silent == [], (
        f"dispatchable and announced nowhere the model can see: {silent}")


def test_every_tagged_tool_has_a_capability_classification():
    """Check C's rule. The approval card has to know what a tool does, or the
    person is asked to approve a thing the product cannot describe."""
    from src.agent_tools import TOOL_TAGS
    from src.tool_capabilities import TOOL_CAPABILITIES

    unclassified = sorted(set(TOOL_TAGS) - set(TOOL_CAPABILITIES))
    assert unclassified == [], unclassified


def test_the_two_offer_registers_agree():
    """`selectable_tool_names()` is what a turn may offer and
    `FUNCTION_TOOL_SCHEMAS` is one of the two channels that carries an offer.
    Nothing asserted them against each other, which is how six names sat in the
    gap: 81 selectable against 75 schemas on `545fb9d`."""
    from src.tool_policy import selectable_tool_names
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    schemas = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS
               if isinstance(s, dict) and "function" in s}
    selectable = set(selectable_tool_names())
    assert sorted(selectable - schemas) == [], sorted(selectable - schemas)
    assert sorted(schemas - selectable) == [], sorted(schemas - selectable)


def test_the_only_name_without_a_channel_is_a_server_id():
    """The exemption, named with its reason (`Law 10`).

    `known_tool_names()` is a **denylist** register and has to be generous; the
    offer register has to be exact. The difference between them is therefore
    not empty by design — but every member of it needs a reason, and today
    there is exactly one member and one reason.
    """
    from src.tool_policy import known_tool_names, selectable_tool_names

    difference = set(known_tool_names()) - set(selectable_tool_names())
    assert difference == set(NOT_A_TOOL), sorted(difference)


# ── and the skills half of the owner's sentence ────────────────────────────


def test_no_bundled_skill_declares_a_tool_the_model_cannot_call():
    """*"entire suite of tooling **and skills**"*.

    A skill's `requires_toolsets` joins the turn's offer after being filtered
    against `selectable_tool_names()`, so a skill naming a dead tool does not
    break the turn — it just silently never gets the tool its procedure assumes,
    which reads to the person as the skill not working.

    Measured today across the bundled library: **286** `SKILL.md` files, of
    which **0** declare `requires_toolsets` at all — the key is for skills a
    person or an import creates. So this case asserts nothing about today's
    library and everything about tomorrow's: the moment a bundled skill
    declares a toolset, it has to be one the model can call.
    """
    from src.tool_policy import selectable_tool_names

    selectable = set(selectable_tool_names())
    paths = sorted(set(glob.glob("library/**/SKILL.md", recursive=True)))
    assert paths, "the bundled library moved — this case would assert nothing"

    offenders = {}
    for path in paths:
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        match = re.search(r"^requires_toolsets:\s*(.+)$", text, re.M)
        if not match:
            continue
        for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)):
            if name not in selectable:
                offenders.setdefault(name, []).append(os.path.relpath(path))

    assert offenders == {}, (
        "bundled skills declare toolsets the model cannot call: "
        + "; ".join(f"{n} in {len(f)} skill(s), e.g. {f[0]}"
                    for n, f in sorted(offenders.items())))
