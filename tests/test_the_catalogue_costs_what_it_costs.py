# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-21` — the skills catalogue joins the budget, and stops lying about its size.

**Both halves of the row's premise were re-measured on 2026-09-19 and both moved.**

*"~15 tokens per published skill."* Measured by publishing the whole bundled
library into a fresh store and rendering the real block through
`render_skill_index_block`: **286 entries, 80,610 characters, 24,187 tokens**
by the product's own `estimate_tokens` — **84.6 tokens per entry**, with a
median entry line of 275 characters and a longest of 1,001. Not 15. The block
on its own is **four times** the 6,000-token default `agent_input_token_budget`,
and nothing anywhere trimmed it.

*"on every single request."* Also not what ships. All 286 bundled skills parse
with `status: draft` (no `status:` in their frontmatter, and `Skill.from_markdown`
defaults to draft), and `index_for` admits only published skills plus
teacher-escalation drafts. Measured on a fresh data dir with the real library:
`index_for()` returns **0** entries and the rendered block is **0** characters.
So on a stock install the catalogue costs nothing, and the cost the row is about
arrives the moment somebody publishes — which is one click per skill.

The second clause of the row is the counter. `uses` is incremented in
`agent_loop._build_system_prompt` for every skill *shown* to the model, so it
counts retrievals, and it then feeds a `* 1.05` multiplier back into the score
that did the retrieving — keyword luck compounding into more keyword luck.
`uses` keeps its meaning (`Law 1`, `Law 2`: it is on the wire and on the card);
`opens` is the new counter, incremented when the model actually fetches the
SKILL.md through `manage_skills action=view`, and it is `opens` that earns the
boost now.
"""

import json

import pytest

from services.memory.skill_injection import (
    INDEX_TRUNCATION_NOTE,
    render_skill_index_block,
)
from services.memory.skills import SkillsManager
from src.context_budget import (
    MAX_PROMPT_BUDGET_CHARS,
    MIN_PROMPT_BUDGET_CHARS,
    PROMPT_BUDGETS,
    SKILL_INDEX_BUDGET,
    context_window_report,
    resolve_prompt_budget,
)
from src.tools.system import do_manage_skills


def _index(n, desc_chars=200):
    return [{"name": f"skill-{i:03d}", "description": "d" * desc_chars,
             "category": "general", "status": "published"} for i in range(n)]


# ---------------------------------------------------------------------------
# The budget exists, is resolvable, and is one policy with the others
# ---------------------------------------------------------------------------

def test_the_skill_index_is_a_budget_and_not_a_constant():
    assert SKILL_INDEX_BUDGET in PROMPT_BUDGETS
    assert resolve_prompt_budget(SKILL_INDEX_BUDGET) == PROMPT_BUDGETS[SKILL_INDEX_BUDGET]


def test_the_budget_resolves_through_the_same_layers_as_every_other_limit(monkeypatch):
    """`P12-04` made context budgets one policy. This is that policy applied to
    the seventh thing that eats the window, not an eighth resolver beside it."""
    import src.limit_policy as limit_policy

    seen = {}

    def _fake(key, *, default, env_name=None, owner=None, minimum=1, maximum=None):
        seen.update({"key": key, "default": default, "env_name": env_name,
                     "minimum": minimum, "maximum": maximum})
        return limit_policy.ResolvedLimit(value=4321, source="role")

    monkeypatch.setattr(limit_policy, "resolve_int_limit", _fake)
    assert resolve_prompt_budget(SKILL_INDEX_BUDGET, owner="alice") == 4321
    assert seen["key"] == SKILL_INDEX_BUDGET
    assert seen["default"] == PROMPT_BUDGETS[SKILL_INDEX_BUDGET]
    # Settings-only, like the six attachment budgets — and held to a floor, so a
    # configured `1` cannot render a heading with no catalogue under it.
    assert seen["env_name"] is None
    assert seen["minimum"] == MIN_PROMPT_BUDGET_CHARS
    assert seen["maximum"] == MAX_PROMPT_BUDGET_CHARS


def test_the_budget_is_registered_where_a_person_can_change_it():
    from src.settings import DEFAULT_SETTINGS, LIMIT_RANGES
    assert SKILL_INDEX_BUDGET in DEFAULT_SETTINGS
    assert SKILL_INDEX_BUDGET in LIMIT_RANGES


# ---------------------------------------------------------------------------
# The renderer honours it, and says what it left out
# ---------------------------------------------------------------------------

def test_an_oversized_catalogue_is_cut_to_the_budget():
    block = render_skill_index_block(_index(300), budget_chars=4000)
    assert len(block) <= 4000, len(block)


def test_the_model_is_told_the_list_is_partial_and_how_to_see_the_rest():
    """A model handed a truncated catalogue with no note concludes the missing
    skills do not exist. That is worse than a long list."""
    block = render_skill_index_block(_index(300), budget_chars=4000)
    assert INDEX_TRUNCATION_NOTE.split("{")[0].strip() in block
    assert "manage_skills" in block
    shown = block.count("\n- `")
    assert f"{300 - shown} more" in block, block[-400:]


def test_a_catalogue_that_fits_is_untouched_and_carries_no_note():
    small = _index(3, desc_chars=20)
    assert render_skill_index_block(small) == render_skill_index_block(
        small, budget_chars=10 ** 6)
    assert "more" not in render_skill_index_block(small).split("\n")[-1]


def test_what_survives_the_cut_is_what_the_model_actually_opened():
    """Ranking by `uses` would keep whatever keyword luck retrieved most often.
    `opens` is the model fetching the whole SKILL.md — a deliberate act.

    The budget here holds exactly **one** entry, so the two orderings give
    different answers rather than merely different positions in the same list.
    """
    idx = _index(40, desc_chars=200)
    idx[37]["opens"] = 9           # opened once and a bit, never a lucky match
    idx[38]["uses"] = 400          # retrieved constantly, never once opened
    block = render_skill_index_block(idx, budget_chars=900)
    assert block.count("\n- `") == 1, block
    assert "skill-037" in block and "skill-038" not in block, block


def test_the_default_budget_binds_on_a_library_nobody_has_yet():
    """No `budget_chars` passed: the number comes from
    `context_skill_index_chars`, which is what makes both callers — the loop and
    the preview — bounded without either of them asking.

    300 entries of the measured median size render ~67,000 characters. The
    default has to cut that, and has to leave a library that fits alone."""
    big = render_skill_index_block(_index(300, desc_chars=200))
    assert len(big) <= PROMPT_BUDGETS[SKILL_INDEX_BUDGET], len(big)
    assert "more skills are installed" in big

    small = render_skill_index_block(_index(6, desc_chars=60))
    assert "more skills are installed" not in small


def test_the_renderer_reports_what_it_did_to_whoever_asked():
    report: dict = {}
    render_skill_index_block(_index(300, desc_chars=200), report=report)
    assert report["skill_index_truncated"] is True
    assert report["skill_index_omitted"] > 0
    assert report["skill_index_chars"] <= PROMPT_BUDGETS[SKILL_INDEX_BUDGET]

    report2: dict = {}
    render_skill_index_block(_index(2, desc_chars=20), report=report2)
    assert report2 == {"skill_index_chars": report2["skill_index_chars"],
                       "skill_index_truncated": False, "skill_index_omitted": 0}


def test_the_index_carries_the_counters_the_cut_decides_on(tmp_path):
    """`index_for` is where the renderer gets `opens` from. Without them the
    ranking is a stable sort on nothing and the cut is alphabetical."""
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="rotate-logs", description="d", when_to_use="w",
                 procedure=["p"], source="user", status="published", owner=None)
    sm.record_use("rotate-logs", owner=None)
    sm.record_open("rotate-logs", owner=None)
    sm.record_open("rotate-logs", owner=None)
    row = sm.index_for(owner=None)[0]
    assert row["uses"] == 1 and row["opens"] == 2


def test_zero_entries_still_render_as_nothing_at_all():
    assert render_skill_index_block([], budget_chars=10) == ""
    assert render_skill_index_block(None) == ""


def test_the_budget_cannot_cut_the_block_below_its_own_header():
    """A budget smaller than the preamble would otherwise produce a header with
    no skills under it — a catalogue that says the library is empty."""
    block = render_skill_index_block(_index(5), budget_chars=1)
    assert block == "" or block.count("\n- `") >= 1


# ---------------------------------------------------------------------------
# The composer's `skills` segment stops saying `measured: false`
# ---------------------------------------------------------------------------

def test_the_skills_segment_is_measured_when_the_block_is_handed_in():
    report = context_window_report(turn=None, prompt={"skill_index_chars": 80610})
    seg = next(s for s in report["segments"] if s["key"] == "skills")
    assert seg["measured"] is True
    assert seg["chars"] == 80610
    assert seg["tokens"] > 0
    assert seg["budget_chars"] == PROMPT_BUDGETS[SKILL_INDEX_BUDGET]


def test_an_unmeasured_skills_segment_is_still_absent_rather_than_zero():
    seg = next(s for s in context_window_report()["segments"] if s["key"] == "skills")
    assert seg["measured"] is False
    assert "chars" not in seg


# ---------------------------------------------------------------------------
# Retrievals and opens are two different numbers
# ---------------------------------------------------------------------------

def test_a_retrieval_and_an_open_are_counted_separately(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="rotate-logs", description="rotate the logs",
                 when_to_use="logs are big", procedure=["rotate"],
                 source="user", status="published", owner=None)
    sm.record_use("rotate-logs", owner=None)
    sm.record_use("rotate-logs", owner=None)
    sm.record_open("rotate-logs", owner=None)

    row = next(s for s in sm.load(owner=None) if s["name"] == "rotate-logs")
    assert row["uses"] == 2, "uses keeps counting retrievals — Law 1"
    assert row["opens"] == 1


def test_the_retrieval_boost_is_earned_by_opens_not_by_retrievals(tmp_path):
    """The `* 1.05` used to key off `uses`, which is written by the retriever
    itself — so one keyword coincidence made the next one likelier, forever."""
    sm = SkillsManager(str(tmp_path), library_root="")
    base = {"description": "rotate the nginx logs on a full disk",
            "when_to_use": "when the nginx logs have filled the disk",
            "procedure": ["run logrotate"], "source": "user",
            "status": "published", "owner": None}
    sm.add_skill(name="lucky", **base)
    sm.add_skill(name="opened", **base)
    for _ in range(50):
        sm.record_use("lucky", owner=None)
    sm.record_open("opened", owner=None)

    pool = sm.load(owner=None)
    query = "rotate the nginx logs on a full disk"
    ranked = [s["name"] for s in sm.get_relevant_skills(query, skills=pool,
                                                        threshold=0.0, max_items=2)]
    assert ranked[0] == "opened", ranked


@pytest.mark.asyncio
async def test_viewing_a_skill_through_the_tool_records_an_open(tmp_path, monkeypatch):
    """`Law 20` — driven through the handler, because the whole point is that an
    open is an act the model performs and not a number a function sets."""
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="rotate-logs", description="rotate the logs",
                 when_to_use="logs are big", procedure=["rotate"],
                 source="user", status="published", owner=None)
    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(str(tmp_path), library_root=""))

    out = await do_manage_skills(json.dumps({"action": "view", "name": "rotate-logs"}),
                                 owner=None)
    assert "rotate-logs" in out.get("results", "")
    row = next(s for s in SkillsManager(str(tmp_path), library_root="").load(owner=None)
               if s["name"] == "rotate-logs")
    assert row["opens"] == 1
    assert row["uses"] == 0, "opening is not retrieving"


@pytest.mark.asyncio
async def test_the_preview_endpoint_says_what_the_catalogue_costs_and_is_allowed(tmp_path):
    """`GET /api/skills/index` is `P8-06`'s answer to *what does the model
    actually have access to?* — and until now it answered with a character count
    and nothing to compare it against. It is also the only wired consumer of the
    `prompt` accounting, so the measurement is not a number with no reader."""
    from routes.skills_routes import setup_skills_routes

    sm = SkillsManager(str(tmp_path), library_root="")
    for i in range(3):
        sm.add_skill(name=f"skill-{i}", description="d" * 60, when_to_use="w",
                     procedure=["p"], source="user", status="published", owner=None)
    router = setup_skills_routes(sm)
    handler = next(r.endpoint for r in router.routes
                   if r.path == "/api/skills/index" and "GET" in r.methods)

    class _Req:
        class state:
            current_user = None

    out = await handler(_Req())
    assert out["count"] == 3
    assert out["budget"]["chars"] == out["prompt_chars"]
    assert out["budget"]["budget_chars"] == PROMPT_BUDGETS[SKILL_INDEX_BUDGET]
    assert out["budget"]["tokens"] > 0
    assert out["budget"]["truncated"] is False
    assert out["budget"]["listed"] == 3
