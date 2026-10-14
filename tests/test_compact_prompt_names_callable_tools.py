# SPDX-License-Identifier: AGPL-3.0-or-later
"""H09 — the compact prompt named two tools the model had no way to call.

`_assemble_prompt(compact=True)` is what every native-tool-calling route gets.
It opens with *"Only the tool schemas provided by the API are available for this
turn… do not write tool syntax or tool instructions in chat"*, then lists the
tools — and two of them, `generate_image` and `manage_research`, are the only
members of `TOOL_SECTIONS` with no `FUNCTION_TOOL_SCHEMAS` entry. No schema is
ever sent for them, and the fenced fallback is shut for exactly these models
(`skip_fenced=is_api_model and not allow_fenced_for_api`). Both channels closed,
both names offered. The same prompt then instructs the model to *say what is
missing instead of pretending* — while handing it a list that is the thing
misleading it.

The row asked for the guard rather than the two instances, so that is what these
test: a compact list may only name a tool that has a schema. The two current
offenders are asserted as a *starting* condition, not as the fix, because a fix
written against those two names would let the third one through.

**2026-10-14 (`B1356`, agent:`fx11-reach`): the orphan set is one, not two,
and this file's docstring said what to do about that** — *"if this ever goes to
zero the guard below still has to stay, because it is what keeps it at zero"*.
`manage_research` was given a `FUNCTION_TOOL_SCHEMAS` entry, because nothing in
the tree ever declared it fenced-only: six of the seven schema-less built-ins
are blessed by name (`P17-06`'s five email drafting tools and
`.pantheon/check-mcp-schemas.py` rule C's `generate_image`) and it was named by
none of them, so `H09`'s reading of it as an accident is the one the evidence
supports.

`B1357` / `D-2026-10-14-01` §1 then closed the last one: `generate_image` has a
schema too, so **no section is an orphan any more** and the compact prompt
names every tool it lists. That removes this file's two *instances* and leaves
its *mechanism* cases untouched and load-bearing — a synthetic schemaless
section is still omitted, and still logged rather than vanishing quietly. Which
is the right shape for a guard: it was never supposed to depend on a particular
tool being broken.
"""
import pytest

import src.agent_loop as A
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def _schema_names():
    return {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS if s.get("function")}


def test_no_section_is_an_orphan_any_more():
    """Not the fix — the starting condition, and it has reached zero.

    Two orphans when this file was written, one after `B1356` gave
    `manage_research` a schema, **none** after `B1357` gave `generate_image`
    one. This case's own docstring predicted this moment: *"If this ever goes
    to zero the guard below still has to stay, because it is what keeps it at
    zero."* It does stay — `test_a_new_schemaless_section_is_omitted_too` and
    `test_omission_is_logged_rather_than_silent` drive a synthetic section and
    need no broken tool to be meaningful.
    """
    orphans = set(A.TOOL_SECTIONS) - _schema_names()
    assert orphans == set(), (
        "a prompt section with no function schema: the compact prompt would "
        f"have to omit it to stay honest: {sorted(orphans)}")


def test_the_compact_prompt_names_no_tool_it_cannot_call():
    """The guard, over the whole real registry rather than the two known names."""
    prompt = A._assemble_prompt(set(A.TOOL_SECTIONS), compact=True)
    listed = {ln[3:-1] for ln in prompt.splitlines()
              if ln.startswith("- `") and ln.endswith("`")}
    assert listed, "precondition: the prompt lists something"
    assert listed <= _schema_names(), (
        f"named but not callable: {sorted(listed - _schema_names())}"
    )


def test_the_two_former_offenders_are_named_because_they_are_callable_now():
    """Both of this file's instances have crossed over, and for one reason.

    `manage_research` was omitted from the compact prompt until `B1356` gave it
    a schema; `generate_image` was omitted until `B1357` did. The guard never
    changed — it names a tool exactly when the tool is callable — so the right
    assertion today is that all three are named, and the rule is held by the
    synthetic cases below rather than by either of these names.
    """
    prompt = A._assemble_prompt({"generate_image", "manage_research", "bash"},
                                compact=True)
    assert "- `bash`" in prompt
    assert "- `generate_image`" in prompt
    assert "- `manage_research`" in prompt


def test_a_new_schemaless_section_is_omitted_too(monkeypatch):
    """The point of doing this as a guard. A tool added to `TOOL_SECTIONS`
    without a schema — the exact way the two current ones arrived — must not be
    able to reintroduce the defect."""
    monkeypatch.setitem(A.TOOL_SECTIONS, "brand_new_toy", "- `brand_new_toy`")
    prompt = A._assemble_prompt({"brand_new_toy", "bash"}, compact=True)
    assert "- `brand_new_toy`" not in prompt
    assert "- `bash`" in prompt


def test_omission_is_logged_rather_than_silent(monkeypatch, caplog):
    """A tool silently vanishing from a prompt is how the next one of these
    hides. Either the schema is missing or the section should not exist, and
    both deserve a line."""
    monkeypatch.setitem(A.TOOL_SECTIONS, "brand_new_toy", "- `brand_new_toy`")
    with caplog.at_level("WARNING", logger="src.agent_loop"):
        A._assemble_prompt({"brand_new_toy"}, compact=True)
    assert any("brand_new_toy" in r.getMessage() for r in caplog.records), caplog.text


def test_the_full_prompt_is_untouched():
    """The non-compact prompt documents FENCED syntax and is sent to routes
    where fenced parsing is live, so `generate_image` is genuinely reachable
    there. Filtering it out of that prompt would delete a working capability —
    the opposite of this row."""
    prompt = A._assemble_prompt({"generate_image", "bash"}, compact=False)
    assert "generate_image" in prompt


def test_a_disabled_tool_is_still_excluded():
    """The pre-existing `disabled` filter has to survive the new one."""
    prompt = A._assemble_prompt({"bash", "web_search"}, {"bash"}, compact=True)
    assert "- `bash`" not in prompt
    assert "- `web_search`" in prompt


def test_schema_backed_names_are_cached_but_correct():
    A._SCHEMA_BACKED_NAMES = None
    first = A._schema_backed_tool_names()
    assert first == _schema_names()
    assert A._schema_backed_tool_names() is first, "second call must reuse the cache"
